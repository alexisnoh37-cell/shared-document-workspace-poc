from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest

from app import create_app
from config import TestConfig
from services.errors import ConflictError


@pytest.fixture
def collab_app(tmp_path):
    class CollabConfig(TestConfig):
        COLLAB_EDITOR_ENABLED = True
        SESSION_CACHE_DIR = str(tmp_path / "sessions")

    return create_app(CollabConfig)


@pytest.fixture
def collab_client(collab_app):
    return collab_app.test_client()


@pytest.fixture
def collab_csrf_app(tmp_path):
    class CollabCsrfConfig(TestConfig):
        COLLAB_EDITOR_ENABLED = True
        WTF_CSRF_ENABLED = True
        SESSION_CACHE_DIR = str(tmp_path / "sessions")

    return create_app(CollabCsrfConfig)


@pytest.fixture
def collab_csrf_client(collab_csrf_app):
    return collab_csrf_app.test_client()


@pytest.fixture
def collab_editor_app(tmp_path):
    class CollabEditorConfig(TestConfig):
        COLLAB_EDITOR_ENABLED = True
        RHWP_EDITOR_ENABLED = True
        SESSION_CACHE_DIR = str(tmp_path / "sessions")

    return create_app(CollabEditorConfig)


@pytest.fixture
def collab_editor_client(collab_editor_app):
    return collab_editor_app.test_client()


@pytest.fixture
def editor_no_collab_app(tmp_path):
    class EditorNoCollabConfig(TestConfig):
        COLLAB_EDITOR_ENABLED = False
        RHWP_EDITOR_ENABLED = True
        SESSION_CACHE_DIR = str(tmp_path / "sessions")

    return create_app(EditorNoCollabConfig)


@pytest.fixture
def editor_no_collab_client(editor_no_collab_app):
    return editor_no_collab_app.test_client()


def _login(client, email, password="test-password"):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


def _service(app_obj):
    return app_obj.extensions["workspace_service"]


def _chunk(app_obj, code):
    return next(r for r in _service(app_obj).chunks.values() if r["chunk_code"] == code)


def _document_id(app_obj):
    return _service(app_obj).list_documents()[0]["id"]


def _age_lock(app_obj, chunk_id, minutes):
    _service(app_obj).chunks[chunk_id]["locked_at"] = (
        datetime.now(UTC) - timedelta(minutes=minutes)
    ).isoformat()


def test_idle_lock_released_after_threshold(collab_app):
    service = _service(collab_app)
    member = service.get_profile_by_email("renewable2@example.com")
    chunk = _chunk(collab_app, "II-1")
    service.checkout_chunk(member, chunk["id"])
    _age_lock(collab_app, chunk["id"], 31)

    service.list_chunks(_document_id(collab_app))

    refreshed = service.get_chunk(chunk["id"])
    assert refreshed["locked_by"] is None
    assert refreshed["locked_version_no"] is None
    # current_version > 0 -> mirrors force_unlock: chunk goes to "rejected"
    assert refreshed["status"] == "rejected"
    assert any(row["action"] == "lock_idle_released" for row in service.activity_logs)


def test_idle_release_resets_unstarted_chunk_to_not_started(collab_app):
    service = _service(collab_app)
    member = service.get_profile_by_email("renewable2@example.com")
    chunk = _chunk(collab_app, "II-1")
    service.checkout_chunk(member, chunk["id"])
    # simulate a chunk that never had a version uploaded
    service.chunks[chunk["id"]]["current_version"] = 0
    service.chunks[chunk["id"]]["locked_version_no"] = 0
    _age_lock(collab_app, chunk["id"], 31)

    service.list_chunks(_document_id(collab_app))

    refreshed = service.get_chunk(chunk["id"])
    assert refreshed["locked_by"] is None
    assert refreshed["status"] == "not_started"


def test_idle_release_recomputes_document_status(collab_app):
    service = _service(collab_app)
    seed_doc_id = _document_id(collab_app)
    rows = [r for r in service.chunks.values() if r["document_id"] == seed_doc_id]
    for row in rows:
        row["status"] = "approved"
        row["approved_version_id"] = f"approved-{row['id']}"
    service._sync_document_status(seed_doc_id)
    assert service.documents[seed_doc_id]["status"] == "ready_to_confirm"

    member = service.get_profile_by_email("renewable2@example.com")
    stale = _chunk(collab_app, "II-1")
    # attach a stale lock directly so the demotion is driven by the idle sweep,
    # not by the checkout call itself
    service.chunks[stale["id"]].update(
        {"locked_by": member["id"], "locked_version_no": stale["current_version"]}
    )
    _age_lock(collab_app, stale["id"], 31)

    service.list_chunks(seed_doc_id)

    refreshed = service.get_chunk(stale["id"])
    assert refreshed["locked_by"] is None
    assert refreshed["status"] == "rejected"
    # _sync_document_status ran: the approved doc is no longer ready_to_confirm
    assert service.documents[seed_doc_id]["status"] == "in_progress"


def test_idle_sweep_scoped_to_requested_document(collab_app):
    service = _service(collab_app)
    seed_doc_id = _document_id(collab_app)
    manager = service.get_profile_by_email("policy1@example.com")
    policy_member = service.get_profile_by_email("policy2@example.com")
    other_doc = service.create_document(manager, "다른 자료", "")
    other_chunk = service.create_chunk(
        manager, other_doc["id"], "X-1", "다른 조각", policy_member["team_id"]
    )

    renewable_member = service.get_profile_by_email("renewable2@example.com")
    seed_chunk = _chunk(collab_app, "II-1")
    service.checkout_chunk(renewable_member, seed_chunk["id"])
    _age_lock(collab_app, seed_chunk["id"], 31)

    service.checkout_chunk(policy_member, other_chunk["id"])
    _age_lock(collab_app, other_chunk["id"], 31)

    # sweep is scoped to the seed document only
    service.list_chunks(seed_doc_id)

    assert service.chunks[seed_chunk["id"]]["locked_by"] is None
    assert service.chunks[other_chunk["id"]]["locked_by"] == policy_member["id"]

    # an explicit sweep of the other document still releases its idle lock
    service.list_chunks(other_doc["id"])
    assert service.chunks[other_chunk["id"]]["locked_by"] is None


def test_lock_kept_before_threshold(collab_app):
    service = _service(collab_app)
    member = service.get_profile_by_email("renewable2@example.com")
    chunk = _chunk(collab_app, "II-1")
    service.checkout_chunk(member, chunk["id"])
    _age_lock(collab_app, chunk["id"], 5)

    service.list_chunks(_document_id(collab_app))

    assert service.get_chunk(chunk["id"])["locked_by"] == member["id"]


def test_idle_sweeper_is_noop_when_flag_off(app):
    service = _service(app)
    member = service.get_profile_by_email("renewable2@example.com")
    chunk = next(r for r in service.chunks.values() if r["chunk_code"] == "II-1")
    service.checkout_chunk(member, chunk["id"])
    service.chunks[chunk["id"]]["locked_at"] = (
        datetime.now(UTC) - timedelta(minutes=180)
    ).isoformat()

    service.list_chunks(service.list_documents()[0]["id"])

    assert service.get_chunk(chunk["id"])["locked_by"] == member["id"]


def test_stale_lock_cleared_on_checkout(collab_app):
    service = _service(collab_app)
    a = service.get_profile_by_email("renewable2@example.com")
    b = service.get_profile_by_email("renewable3@example.com")
    chunk = _chunk(collab_app, "II-1")
    service.checkout_chunk(a, chunk["id"])
    _age_lock(collab_app, chunk["id"], 45)

    result = service.checkout_chunk(b, chunk["id"])

    assert result["locked_by"] == b["id"]


def test_flag_requires_memory_backend():
    from config import Config

    class BadConfig(Config):
        SECRET_KEY = "x"
        APP_BACKEND = "supabase"
        COLLAB_EDITOR_ENABLED = True

    with pytest.raises(RuntimeError, match="memory"):
        create_app(BadConfig)


def test_collab_routes_absent_when_flag_off(client):
    assert client.get("/collab/documents/x/locks.json").status_code == 404


def test_locks_json_requires_login(collab_client):
    res = collab_client.get("/collab/documents/x/locks.json")
    assert res.status_code == 302
    assert "/auth/login" in res.headers["Location"]


def test_locks_json_unknown_document_returns_404(collab_client):
    _login(collab_client, "renewable2@example.com")
    res = collab_client.get("/collab/documents/does-not-exist/locks.json")
    assert res.status_code == 404
    assert res.get_json()["error"]


def test_locks_json_shape_and_free_state(collab_app, collab_client):
    doc_id = _document_id(collab_app)
    _login(collab_client, "renewable2@example.com")

    res = collab_client.get(f"/collab/documents/{doc_id}/locks.json")
    assert res.status_code == 200
    body = res.get_json()
    assert isinstance(body["poll_seconds"], int)
    assert len(body["chunks"]) == 10
    for row in body["chunks"]:
        assert {"id", "locked", "locked_by_name", "locked_at", "is_mine"} <= set(row)
        assert row["locked"] is False
        assert row["is_mine"] is False


def test_locks_json_reports_owner_and_is_mine(collab_app, collab_client):
    service = _service(collab_app)
    doc_id = _document_id(collab_app)
    chunk = _chunk(collab_app, "II-1")
    service.checkout_chunk(service.get_profile_by_email("renewable2@example.com"), chunk["id"])

    _login(collab_client, "renewable2@example.com")
    mine = collab_client.get(f"/collab/documents/{doc_id}/locks.json").get_json()
    row = next(c for c in mine["chunks"] if c["id"] == chunk["id"])
    assert row["locked"] is True
    assert row["locked_by_name"] == "재생2"
    assert row["is_mine"] is True

    other = collab_app.test_client()
    _login(other, "renewable3@example.com")
    row2 = next(
        c for c in other.get(f"/collab/documents/{doc_id}/locks.json").get_json()["chunks"]
        if c["id"] == chunk["id"]
    )
    assert row2["locked"] is True
    assert row2["is_mine"] is False


def test_locks_json_reflects_idle_release(collab_app, collab_client):
    service = _service(collab_app)
    doc_id = _document_id(collab_app)
    chunk = _chunk(collab_app, "II-1")
    service.checkout_chunk(service.get_profile_by_email("renewable2@example.com"), chunk["id"])
    _age_lock(collab_app, chunk["id"], 31)

    _login(collab_client, "renewable2@example.com")
    row = next(
        c for c in collab_client.get(f"/collab/documents/{doc_id}/locks.json").get_json()["chunks"]
        if c["id"] == chunk["id"]
    )
    assert row["locked"] is False


def test_heartbeat_refreshes_locked_at_for_owner(collab_app, collab_client):
    service = _service(collab_app)
    chunk = _chunk(collab_app, "II-1")
    service.checkout_chunk(service.get_profile_by_email("renewable2@example.com"), chunk["id"])
    _age_lock(collab_app, chunk["id"], 20)

    _login(collab_client, "renewable2@example.com")
    res = collab_client.post(f"/collab/chunks/{chunk['id']}/heartbeat")

    assert res.status_code == 200
    assert res.get_json()["ok"] is True
    fresh = datetime.fromisoformat(service.chunks[chunk["id"]]["locked_at"])
    assert fresh > datetime.now(UTC) - timedelta(minutes=1)


def test_heartbeat_rejected_for_non_owner(collab_app, collab_client):
    service = _service(collab_app)
    chunk = _chunk(collab_app, "II-1")
    service.checkout_chunk(service.get_profile_by_email("renewable2@example.com"), chunk["id"])
    before = service.chunks[chunk["id"]]["locked_at"]

    _login(collab_client, "renewable3@example.com")
    res = collab_client.post(f"/collab/chunks/{chunk['id']}/heartbeat")

    assert res.status_code == 409
    assert res.get_json()["ok"] is False
    assert service.chunks[chunk["id"]]["locked_at"] == before


def test_heartbeat_requires_login(collab_client):
    res = collab_client.post("/collab/chunks/whatever/heartbeat")
    assert res.status_code == 302


def test_detail_page_presence_hooks_when_flag_on(collab_app, collab_client):
    doc_id = _document_id(collab_app)
    _login(collab_client, "renewable2@example.com")
    html = collab_client.get(f"/documents/{doc_id}").text
    assert "js/collab_presence.js" in html
    assert "data-chunk-id=" in html
    assert "data-locks-url=" in html
    assert "data-edit-start" in html


def test_detail_page_clean_when_flag_off(app, client, login_user):
    doc_id = app.extensions["workspace_service"].list_documents()[0]["id"]
    login_user(client, "renewable2@example.com")
    html = client.get(f"/documents/{doc_id}").text
    assert "collab_presence.js" not in html
    assert "data-chunk-id=" not in html
    assert "data-edit-start" not in html


def test_detail_marks_locked_by_other(collab_app, collab_client):
    service = _service(collab_app)
    doc_id = _document_id(collab_app)
    chunk = _chunk(collab_app, "II-1")
    service.checkout_chunk(service.get_profile_by_email("renewable2@example.com"), chunk["id"])

    _login(collab_client, "renewable3@example.com")
    html = collab_client.get(f"/documents/{doc_id}").text
    assert "chunk-editing" in html
    assert "data-locked-by-other" in html


def test_detail_marks_my_own_lock(collab_app, collab_client):
    service = _service(collab_app)
    doc_id = _document_id(collab_app)
    chunk = _chunk(collab_app, "II-1")
    service.checkout_chunk(service.get_profile_by_email("renewable2@example.com"), chunk["id"])

    _login(collab_client, "renewable2@example.com")
    html = collab_client.get(f"/documents/{doc_id}").text
    row = next(
        (line for line in html.splitlines() if f'data-chunk-id="{chunk["id"]}"' in line),
        None,
    )
    assert row is not None
    assert "chunk-editing" in row
    assert "data-locked-by-other" not in html


def test_submit_page_heartbeat_hook_when_flag_on(collab_app, collab_client):
    service = _service(collab_app)
    chunk = _chunk(collab_app, "II-1")
    service.checkout_chunk(service.get_profile_by_email("renewable2@example.com"), chunk["id"])

    _login(collab_client, "renewable2@example.com")
    html = collab_client.get(f"/chunks/{chunk['id']}/submit").text
    assert "js/collab_heartbeat.js" in html
    assert "data-heartbeat-url=" in html


def test_submit_page_no_heartbeat_when_flag_off(app, client, login_user):
    service = app.extensions["workspace_service"]
    chunk = next(r for r in service.chunks.values() if r["chunk_code"] == "II-1")
    service.checkout_chunk(service.get_profile_by_email("renewable2@example.com"), chunk["id"])

    login_user(client, "renewable2@example.com")
    html = client.get(f"/chunks/{chunk['id']}/submit").text
    assert "collab_heartbeat.js" not in html


def test_editor_page_heartbeat_hook_when_flag_on(collab_editor_app, collab_editor_client):
    service = collab_editor_app.extensions["workspace_service"]
    chunk = _chunk(collab_editor_app, "II-1")
    service.checkout_chunk(service.get_profile_by_email("renewable2@example.com"), chunk["id"])

    _login(collab_editor_client, "renewable2@example.com")
    html = collab_editor_client.get(f"/chunks/{chunk['id']}/editor").text
    assert "js/collab_heartbeat.js" in html
    assert "data-heartbeat-url=" in html
    assert 'data-heartbeat-seconds="60"' in html


def test_editor_page_no_heartbeat_when_flag_off(editor_no_collab_app, editor_no_collab_client):
    service = editor_no_collab_app.extensions["workspace_service"]
    chunk = next(r for r in service.chunks.values() if r["chunk_code"] == "II-1")
    service.checkout_chunk(service.get_profile_by_email("renewable2@example.com"), chunk["id"])

    _login(editor_no_collab_client, "renewable2@example.com")
    html = editor_no_collab_client.get(f"/chunks/{chunk['id']}/editor").text
    assert "collab_heartbeat.js" not in html


def test_force_unlock_unchanged_with_flag_on(collab_app, collab_client):
    service = _service(collab_app)
    chunk = _chunk(collab_app, "II-1")
    service.checkout_chunk(service.get_profile_by_email("renewable2@example.com"), chunk["id"])

    _login(collab_client, "renewable1@example.com")
    res = collab_client.post(f"/chunks/{chunk['id']}/force-unlock", follow_redirects=True)
    assert "잠금을 강제로 해제했습니다" in res.text
    assert service.get_chunk(chunk["id"])["locked_by"] is None


def test_concurrent_checkout_still_blocked_with_flag_on(collab_app):
    service = _service(collab_app)
    chunk = _chunk(collab_app, "II-1")
    service.checkout_chunk(service.get_profile_by_email("renewable2@example.com"), chunk["id"])
    with pytest.raises(ConflictError, match="재생2님이 편집 중"):
        service.checkout_chunk(service.get_profile_by_email("renewable3@example.com"), chunk["id"])


def _csrf_token(client, path):
    html = client.get(path).text
    match = re.search(r'name="csrf-token"\s+content="([^"]+)"', html)
    assert match, f"no <meta name=\"csrf-token\"> on {path}"
    return match.group(1)


def _login_csrf(client, email, password="test-password"):
    token = _csrf_token(client, "/auth/login")
    return client.post(
        "/auth/login",
        data={"email": email, "password": password, "csrf_token": token},
        follow_redirects=True,
    )


def test_heartbeat_csrf_contract_when_enabled(collab_csrf_app, collab_csrf_client):
    service = collab_csrf_app.extensions["workspace_service"]
    doc_id = _document_id(collab_csrf_app)
    chunk = _chunk(collab_csrf_app, "II-1")
    service.checkout_chunk(service.get_profile_by_email("renewable2@example.com"), chunk["id"])
    _login_csrf(collab_csrf_client, "renewable2@example.com")

    bare = collab_csrf_client.post(f"/collab/chunks/{chunk['id']}/heartbeat")
    assert bare.status_code == 400

    token = _csrf_token(collab_csrf_client, f"/documents/{doc_id}")
    ok = collab_csrf_client.post(
        f"/collab/chunks/{chunk['id']}/heartbeat",
        headers={"X-CSRFToken": token},
    )
    assert ok.status_code == 200
    assert ok.get_json() == {"ok": True}


def test_config_rejects_nonpositive_idle_minutes():
    class BadConfig(TestConfig):
        COLLAB_EDITOR_ENABLED = True
        COLLAB_LOCK_IDLE_MINUTES = 0

    with pytest.raises(RuntimeError, match="COLLAB_LOCK_IDLE_MINUTES"):
        create_app(BadConfig)


def test_config_rejects_nonpositive_poll_seconds():
    class BadConfig(TestConfig):
        COLLAB_EDITOR_ENABLED = True
        COLLAB_POLL_SECONDS = 0

    with pytest.raises(RuntimeError, match="COLLAB_POLL_SECONDS"):
        create_app(BadConfig)

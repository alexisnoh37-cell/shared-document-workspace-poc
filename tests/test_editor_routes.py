from __future__ import annotations

from io import BytesIO

from services.errors import IntegrationError


def chunk(app, code: str) -> dict:
    service = app.extensions["workspace_service"]
    return next(row for row in service.chunks.values() if row["chunk_code"] == code)


def checkout(client, chunk_id: str):
    return client.post(f"/chunks/{chunk_id}/checkout", follow_redirects=False)


def test_editor_requires_same_team_checkout_owner(app, login_user):
    target = chunk(app, "II-1")

    owner = app.test_client()
    login_user(owner, "renewable2@example.com")
    assert checkout(owner, target["id"]).status_code == 302
    assert owner.get(f"/chunks/{target['id']}/editor").status_code == 200

    same_team = app.test_client()
    login_user(same_team, "renewable3@example.com")
    blocked = same_team.get(f"/chunks/{target['id']}/editor")
    assert blocked.status_code == 400
    assert "먼저 편집 시작" in blocked.text

    other_team = app.test_client()
    login_user(other_team, "hydrogen2@example.com")
    assert other_team.get(f"/chunks/{target['id']}/editor").status_code == 403

    final_manager = app.test_client()
    login_user(final_manager, "policy1@example.com")
    assert final_manager.get(f"/chunks/{target['id']}/editor").status_code == 403


def test_editor_without_checkout_is_rejected(app, client, login_user):
    login_user(client, "renewable2@example.com")
    response = client.get(f"/chunks/{chunk(app, 'II-1')['id']}/editor")
    assert response.status_code == 400
    assert "체크아웃" in response.text


def test_editor_source_uses_locked_version_not_changed_current_version(app, client, login_user):
    service = app.extensions["workspace_service"]
    target = chunk(app, "II-1")
    login_user(client, "renewable2@example.com")
    checkout(client, target["id"])
    locked_no = target["locked_version_no"]
    locked_version = next(
        row
        for row in service.versions.values()
        if row["chunk_id"] == target["id"] and row["version_no"] == locked_no
    )
    expected = service.version_content[locked_version["id"]]
    target["current_version"] += 1

    response = client.get(f"/chunks/{target['id']}/editor/source")
    assert response.status_code == 200
    assert response.data == expected
    assert response.headers["Cache-Control"] == "private, no-store"


def test_web_editor_save_creates_immutable_version_and_unlocks(app, client, login_user):
    service = app.extensions["workspace_service"]
    target = chunk(app, "II-1")
    old_versions = service.list_versions(target["id"])
    old_version_id = old_versions[0]["id"]
    old_content = service.version_content[old_version_id]
    export_content = (service.project_root / "sample_files" / "ii_2.hwpx").read_bytes()

    login_user(client, "renewable2@example.com")
    checkout(client, target["id"])
    response = client.post(
        f"/chunks/{target['id']}/editor/save",
        data={
            "change_reason": "웹 편집 저장 테스트",
            "file": (BytesIO(export_content), "browser-name-is-ignored.exe"),
        },
        headers={"Accept": "application/json"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["versionNo"] == 2
    updated = service.get_chunk(target["id"])
    assert updated["current_version"] == 2
    assert updated["status"] == "submitted"
    assert updated["locked_by"] is None
    assert service.version_content[old_version_id] == old_content
    saved = service.get_version(payload["versionId"])
    assert saved["original_filename"] == "II-1-v2-web.hwpx"
    assert saved["diff_status"] == "succeeded"


def test_web_editor_stale_save_is_rejected(app, client, login_user):
    service = app.extensions["workspace_service"]
    target = chunk(app, "II-1")
    export_content = (service.project_root / "sample_files" / "ii_2.hwpx").read_bytes()
    login_user(client, "renewable2@example.com")
    checkout(client, target["id"])
    target["current_version"] += 1

    response = client.post(
        f"/chunks/{target['id']}/editor/save",
        data={
            "change_reason": "stale 제출",
            "file": (BytesIO(export_content), "export.hwpx"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 409
    assert "최신 버전으로 다시 시작" in response.get_json()["error"]
    assert target["locked_by"] is not None


def test_web_editor_rejects_invalid_export_and_cross_origin(app, client, login_user):
    target = chunk(app, "II-1")
    login_user(client, "renewable2@example.com")
    checkout(client, target["id"])

    invalid = client.post(
        f"/chunks/{target['id']}/editor/save",
        data={
            "change_reason": "잘못된 파일",
            "file": (BytesIO(b"not-a-zip"), "export.hwpx"),
        },
        content_type="multipart/form-data",
    )
    assert invalid.status_code == 400
    assert "HWPX" in invalid.get_json()["error"]

    cross_origin = client.post(
        f"/chunks/{target['id']}/editor/save",
        data={
            "change_reason": "교차 출처",
            "file": (BytesIO(b"PK\x03\x04"), "export.hwpx"),
        },
        headers={"Origin": "https://evil.example"},
        content_type="multipart/form-data",
    )
    assert cross_origin.status_code == 403


def test_kordoc_parse_failure_stops_version_creation(app, client, login_user):
    service = app.extensions["workspace_service"]
    target = chunk(app, "II-1")
    export_content = (service.project_root / "sample_files" / "ii_2.hwpx").read_bytes()

    class RejectingKordoc:
        def parse_bytes(self, *_args, **_kwargs):
            raise IntegrationError("의도된 parse 실패")

    app.extensions["kordoc_service"] = RejectingKordoc()
    login_user(client, "renewable2@example.com")
    checkout(client, target["id"])
    response = client.post(
        f"/chunks/{target['id']}/editor/save",
        data={
            "change_reason": "parse 실패 검증",
            "file": (BytesIO(export_content), "export.hwpx"),
        },
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert "저장 검증에 실패" in response.get_json()["error"]
    assert target["current_version"] == 1
    assert target["locked_by"] is not None


def test_editor_page_keeps_download_upload_fallback(app, client, login_user):
    target = chunk(app, "II-1")
    login_user(client, "renewable2@example.com")
    response = client.post(f"/chunks/{target['id']}/checkout", follow_redirects=True)
    assert "웹에서 수정" in response.text
    assert "최신 파일 다운로드" in response.text
    assert 'name="file"' in response.text

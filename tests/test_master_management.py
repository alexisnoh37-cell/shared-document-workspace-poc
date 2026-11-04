from __future__ import annotations

from services.identity import DELETE_CHUNK_CONFIRMATION_TEXT
from services.permission_service import can_edit_chunk, can_review_chunk


def profile(service, email: str) -> dict:
    return next(row for row in service.list_profiles() if row["email"] == email)


def chunk_for_other_team(service, master: dict) -> dict:
    return next(row for row in service.chunks.values() if row["team_id"] != master["team_id"])


def test_master_can_edit_other_team_but_does_not_gain_review_permission(app):
    service = app.extensions["workspace_service"]
    master = profile(service, "master1@example.com")
    chunk = chunk_for_other_team(service, master)

    assert can_edit_chunk(master, chunk) is True
    assert can_review_chunk(master, chunk) is False

    checked_out = service.checkout_chunk(master, chunk["id"])
    assert checked_out["locked_by"] == master["id"]
    assert checked_out["status"] == "editing"


def test_regular_manager_cannot_rename_document_or_chunk(app, client, login_user):
    service = app.extensions["workspace_service"]
    document = next(iter(service.documents.values()))
    chunk = next(iter(service.chunks.values()))
    login_user(client, "policy1@example.com")

    document_response = client.post(
        f"/admin/documents/{document['id']}/title", data={"title": "변경 시도"}
    )
    chunk_response = client.post(
        f"/admin/chunks/{chunk['id']}/title", data={"title": "변경 시도"}
    )

    assert document_response.status_code == 403
    assert chunk_response.status_code == 403
    assert document["title"] != "변경 시도"
    assert chunk["title"] != "변경 시도"


def test_master_management_ui_and_title_updates(app, client, login_user):
    service = app.extensions["workspace_service"]
    document = next(iter(service.documents.values()))
    chunk = next(iter(service.chunks.values()))
    login_user(client, "master1")

    manage = client.get("/admin/manage")
    assert manage.status_code == 200
    assert "자료명 저장" in manage.text
    assert "이름 저장" in manage.text
    assert "조각 삭제" in manage.text
    assert DELETE_CHUNK_CONFIRMATION_TEXT in manage.text

    renamed_document = client.post(
        f"/admin/documents/{document['id']}/title",
        data={"title": "변경된 자료명"},
        follow_redirects=True,
    )
    renamed_chunk = client.post(
        f"/admin/chunks/{chunk['id']}/title",
        data={"title": "변경된 조각명"},
        follow_redirects=True,
    )

    assert "자료명을 변경했습니다" in renamed_document.text
    assert "조각명을 변경했습니다" in renamed_chunk.text
    assert service.documents[document["id"]]["title"] == "변경된 자료명"
    assert service.chunks[chunk["id"]]["title"] == "변경된 조각명"


def test_locked_chunk_must_be_unlocked_before_master_delete(app, client, login_user):
    service = app.extensions["workspace_service"]
    master = profile(service, "master1@example.com")
    chunk = chunk_for_other_team(service, master)
    login_user(client, "master1")
    service.checkout_chunk(master, chunk["id"])

    blocked = client.post(
        f"/admin/chunks/{chunk['id']}/delete",
        data={"confirmation_text": DELETE_CHUNK_CONFIRMATION_TEXT},
        follow_redirects=True,
    )

    assert "잠금을 해제한 후 삭제하세요" in blocked.text
    assert chunk["id"] in service.chunks

    unlocked = client.post(f"/chunks/{chunk['id']}/force-unlock", follow_redirects=True)
    assert "잠금을 강제로 해제했습니다" in unlocked.text
    assert service.chunks[chunk["id"]]["locked_by"] is None


def test_master_chunk_delete_requires_phrase_and_cascades_versions(app, client, login_user):
    service = app.extensions["workspace_service"]
    chunk = next(
        row
        for row in service.chunks.values()
        if any(version["chunk_id"] == row["id"] for version in service.versions.values())
    )
    document_id = chunk["document_id"]
    version_ids = {
        row["id"] for row in service.versions.values() if row["chunk_id"] == chunk["id"]
    }
    login_user(client, "master1")

    rejected = client.post(
        f"/admin/chunks/{chunk['id']}/delete",
        data={"confirmation_text": "조각 삭제를 확인합니다"},
        follow_redirects=True,
    )
    assert "정확히 입력하세요" in rejected.text
    assert chunk["id"] in service.chunks

    deleted = client.post(
        f"/admin/chunks/{chunk['id']}/delete",
        data={"confirmation_text": DELETE_CHUNK_CONFIRMATION_TEXT},
        follow_redirects=True,
    )
    assert "조각을 영구 삭제했습니다" in deleted.text
    assert document_id in service.documents
    assert chunk["id"] not in service.chunks
    assert not version_ids.intersection(service.versions)
    assert not version_ids.intersection(service.version_content)
    assert any(
        row["action"] == "delete_chunk"
        and row["metadata"]["deleted_chunk_id"] == chunk["id"]
        for row in service.activity_logs
    )

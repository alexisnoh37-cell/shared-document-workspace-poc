from __future__ import annotations

from services.identity import DELETE_CONFIRMATION_TEXT


def seeded_document(app) -> dict:
    service = app.extensions["workspace_service"]
    return next(iter(service.documents.values()))


def test_master1_alias_can_login_and_sees_delete_confirmation(client, login_user):
    response = login_user(client, "master1")

    assert response.status_code == 200
    assert "master1님, 환영합니다." in response.text

    manage = client.get("/admin/manage")
    assert manage.status_code == 200
    assert "자료 영구 삭제" in manage.text
    assert "삭제 시 자료는 복원할 수 없습니다, 삭제하시겠습니까?" in manage.text
    assert DELETE_CONFIRMATION_TEXT in manage.text


def test_regular_final_manager_cannot_see_or_call_delete(app, client, login_user):
    document_id = seeded_document(app)["id"]
    login_user(client, "policy1@example.com")

    manage = client.get("/admin/manage")
    assert manage.status_code == 200
    assert "자료 영구 삭제" not in manage.text

    response = client.post(
        f"/admin/documents/{document_id}/delete",
        data={"confirmation_text": DELETE_CONFIRMATION_TEXT},
    )
    assert response.status_code == 403
    assert "master1 계정만" in response.text
    assert document_id in app.extensions["workspace_service"].documents


def test_master_delete_requires_exact_confirmation(app, client, login_user):
    document_id = seeded_document(app)["id"]
    login_user(client, "master1")

    response = client.post(
        f"/admin/documents/{document_id}/delete",
        data={"confirmation_text": "삭제를 확인합니다"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "정확히 입력하세요" in response.text
    assert document_id in app.extensions["workspace_service"].documents


def test_master_delete_removes_document_chunks_versions_and_content(app, client, login_user):
    service = app.extensions["workspace_service"]
    document_id = seeded_document(app)["id"]
    chunk_ids = {
        row["id"] for row in service.chunks.values() if row["document_id"] == document_id
    }
    version_ids = {
        row["id"] for row in service.versions.values() if row["chunk_id"] in chunk_ids
    }
    assert chunk_ids
    assert version_ids
    login_user(client, "master1")

    response = client.post(
        f"/admin/documents/{document_id}/delete",
        data={"confirmation_text": DELETE_CONFIRMATION_TEXT},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "자료를 영구 삭제했습니다" in response.text
    assert document_id not in service.documents
    assert not chunk_ids.intersection(service.chunks)
    assert not version_ids.intersection(service.versions)
    assert not version_ids.intersection(service.version_content)
    assert any(
        row["action"] == "delete_document"
        and row["metadata"]["deleted_document_id"] == document_id
        for row in service.activity_logs
    )


def test_confirmed_document_cannot_be_deleted(app, client, login_user):
    service = app.extensions["workspace_service"]
    document = seeded_document(app)
    document["status"] = "confirmed"
    login_user(client, "master1")

    response = client.post(
        f"/admin/documents/{document['id']}/delete",
        data={"confirmation_text": DELETE_CONFIRMATION_TEXT},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert "최종확정된 자료는 영구 삭제할 수 없습니다" in response.text
    assert document["id"] in service.documents

from __future__ import annotations


def chunk_id(app, code: str) -> str:
    service = app.extensions["workspace_service"]
    return next(row["id"] for row in service.chunks.values() if row["chunk_code"] == code)


def test_login_required(client):
    response = client.get("/documents")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_login_and_all_documents_visible(client, login_user):
    response = login_user(client, "renewable2@example.com")
    assert response.status_code == 200
    assert "2027년 샘플에너지과 주요업무계획" in response.text
    document_href = response.text.split("/documents/")[1].split('"')[0]
    detail = client.get("/documents/" + document_href)
    assert "에너지 정책 추진현황" in detail.text
    assert "수소산업 육성" in detail.text
    assert "재생에너지 확대" in detail.text


def test_direct_other_team_checkout_returns_403(app, client, login_user):
    login_user(client, "renewable2@example.com")
    response = client.post(f"/chunks/{chunk_id(app, 'III-1')}/checkout")
    assert response.status_code == 403
    assert "본인 소속 팀" in response.text


def test_concurrent_lock_message_across_clients(app, login_user):
    first = app.test_client()
    second = app.test_client()
    target = chunk_id(app, "II-1")

    login_user(first, "renewable2@example.com")
    checked_out = first.post(f"/chunks/{target}/checkout", follow_redirects=True)
    assert "편집 잠금을 획득" in checked_out.text

    login_user(second, "renewable3@example.com")
    blocked = second.post(f"/chunks/{target}/checkout", follow_redirects=True)
    assert "현재 재생2님이 편집 중" in blocked.text


def test_member_cannot_open_review_or_admin(client, login_user):
    login_user(client, "renewable2@example.com")
    assert client.get("/reviews").status_code == 403
    assert client.get("/admin/dashboard").status_code == 403


def test_reviewer_and_final_manager_pages(app, login_user):
    reviewer = app.test_client()
    manager = app.test_client()
    login_user(reviewer, "renewable1@example.com")
    assert reviewer.get("/reviews").status_code == 200
    login_user(manager, "policy1@example.com")
    assert manager.get("/admin/dashboard").status_code == 200
    assert manager.get("/admin/manage").status_code == 200


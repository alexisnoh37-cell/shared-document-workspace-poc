from __future__ import annotations

import os

import pytest


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_SUPABASE_INTEGRATION") != "1",
    reason="실제 Supabase 프로젝트를 지정한 경우에만 실행",
)


def signed_in_client(email: str):
    from supabase import create_client

    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_PUBLISHABLE_KEY"])
    client.auth.sign_in_with_password(
        {"email": email, "password": os.environ["DEMO_ACCOUNT_PASSWORD"]}
    )
    return client


def test_all_active_users_can_read_every_team_but_cannot_checkout_other_team():
    renewable = signed_in_client("renewable2@example.com")
    chunks = renewable.table("chunks").select("id,chunk_code,team_id").execute().data
    assert len(chunks) >= 10
    hydrogen = next(row for row in chunks if row["chunk_code"] == "III-1")

    with pytest.raises(Exception):
        renewable.rpc("checkout_chunk", {"p_chunk_id": hydrogen["id"]}).execute()


def test_own_team_checkout_succeeds_and_reviewer_can_unlock():
    reviewer = signed_in_client("renewable1@example.com")
    chunks = reviewer.table("chunks").select("id,chunk_code,status").execute().data
    target = next(row for row in chunks if row["chunk_code"] == "II-2")
    checked_out = False
    try:
        reviewer.rpc("checkout_chunk", {"p_chunk_id": target["id"]}).execute()
        checked_out = True
        current = reviewer.table("chunks").select("status").eq("id", target["id"]).single().execute()
        assert current.data["status"] == "editing"
    finally:
        if checked_out:
            reviewer.rpc(
                "force_unlock_chunk",
                {"p_chunk_id": target["id"], "p_comment": "통합 테스트 정리"},
            ).execute()


def test_anonymous_client_cannot_read_documents():
    from supabase import create_client

    anonymous = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_PUBLISHABLE_KEY"])
    with pytest.raises(Exception) as exc_info:
        anonymous.table("documents").select("*").execute()

    error = str(exc_info.value)
    assert "permission denied" in error
    assert "42501" in error

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from services.demo_data import sample_filename
from services.errors import AuthorizationError, ConflictError
from services.storage_service import ValidatedUpload


class FakeKordoc:
    def compare_bytes(self, old_content, new_content, old_extension=".hwpx", new_extension=".hwpx"):
        return {
            "status": "not_applicable" if not old_content else "succeeded",
            "summary": "최초 버전으로 비교 대상이 없습니다." if not old_content else "추가 1건 · 삭제 0건 · 수정 1건",
            "data": None if not old_content else {"stats": {"added": 1, "removed": 0, "modified": 1, "unchanged": 2}, "diffs": []},
            "error": None,
        }


def profile(service, email: str) -> dict:
    result = service.get_profile_by_email(email)
    assert result
    return result


def upload_for(service, chunk: dict) -> ValidatedUpload:
    path = service.project_root / "sample_files" / sample_filename(chunk["chunk_code"])
    content = path.read_bytes()
    return ValidatedUpload(
        filename=path.name,
        extension=".hwpx",
        content=content,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def test_demo_seed_has_five_teams_and_sixteen_users(app):
    service = app.extensions["workspace_service"]
    assert len(service.list_teams()) == 5
    assert len(service.list_profiles()) == 16
    assert len(service.list_documents()) == 1
    assert len(service.list_chunks(service.list_documents()[0]["id"])) == 10


def test_other_team_edit_is_denied_even_for_final_manager(app):
    service = app.extensions["workspace_service"]
    manager = profile(service, "policy1@example.com")
    hydrogen_chunk = next(
        row for row in service.chunks.values() if row["chunk_code"] == "III-1"
    )
    with pytest.raises(AuthorizationError):
        service.checkout_chunk(manager, hydrogen_chunk["id"])


def test_same_team_concurrent_checkout_is_blocked(app):
    service = app.extensions["workspace_service"]
    renewable2 = profile(service, "renewable2@example.com")
    renewable3 = profile(service, "renewable3@example.com")
    chunk = next(row for row in service.chunks.values() if row["chunk_code"] == "II-1")
    service.checkout_chunk(renewable2, chunk["id"])
    with pytest.raises(ConflictError, match="재생2님이 편집 중"):
        service.checkout_chunk(renewable3, chunk["id"])


def test_submit_and_team_review_permission(app):
    service = app.extensions["workspace_service"]
    member = profile(service, "renewable2@example.com")
    reviewer = profile(service, "renewable1@example.com")
    other_reviewer = profile(service, "hydrogen1@example.com")
    chunk = next(row for row in service.chunks.values() if row["chunk_code"] == "II-1")

    service.checkout_chunk(member, chunk["id"])
    version = service.checkin_chunk(
        member, chunk["id"], upload_for(service, chunk), "보급 목표 최신화", FakeKordoc()
    )
    assert version["version_no"] >= 1
    assert service.get_chunk(chunk["id"])["status"] == "submitted"

    with pytest.raises(AuthorizationError):
        service.review_chunk(other_reviewer, chunk["id"], "approve", "")
    service.review_chunk(reviewer, chunk["id"], "approve", "")
    approved = service.get_chunk(chunk["id"])
    assert approved["status"] == "approved"
    assert approved["approved_version_id"] == version["id"]


def test_full_workflow_confirmation_snapshot_is_immutable_selection(app):
    service = app.extensions["workspace_service"]
    kordoc = FakeKordoc()
    team_key_by_name = {
        "에너지정책팀": "policy",
        "재생에너지팀": "renewable",
        "수소산업팀": "hydrogen",
        "에너지관리팀": "energy",
        "RE100팀": "re",
    }
    member_email = {
        "에너지정책팀": "policy2@example.com",
        "재생에너지팀": "renewable2@example.com",
        "수소산업팀": "hydrogen2@example.com",
        "에너지관리팀": "energy2@example.com",
        "RE100팀": "re2@example.com",
    }
    reviewer_email = {
        "에너지정책팀": "policy1@example.com",
        "재생에너지팀": "renewable1@example.com",
        "수소산업팀": "hydrogen1@example.com",
        "에너지관리팀": "energy1@example.com",
        "RE100팀": "re1@example.com",
    }
    document_id = service.list_documents()[0]["id"]

    for chunk in service.list_chunks(document_id):
        member = profile(service, member_email[chunk["team_name"]])
        reviewer = profile(service, reviewer_email[chunk["team_name"]])
        service.checkout_chunk(member, chunk["id"])
        version = service.checkin_chunk(
            member, chunk["id"], upload_for(service, chunk), "최종 검토용 최신화", kordoc
        )
        service.review_chunk(reviewer, chunk["id"], "approve", "검토 완료")
        assert service.get_chunk(chunk["id"])["approved_version_id"] == version["id"]

    dashboard = service.dashboard(document_id)
    assert dashboard["progress"] == 100
    assert dashboard["can_confirm"] is True

    manager = profile(service, "policy1@example.com")
    confirmation = service.confirm_document(manager, document_id)
    assert len(confirmation["snapshot_data"]) == 10
    assert service.get_document(document_id)["status"] == "confirmed"
    with pytest.raises(ConflictError):
        own_chunk = next(row for row in service.list_chunks(document_id) if row["team_name"] == "에너지정책팀")
        service.checkout_chunk(manager, own_chunk["id"])

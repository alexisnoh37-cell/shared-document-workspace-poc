from __future__ import annotations

import os
import re
from pathlib import Path
from uuid import uuid4

import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.getenv("WORKSPACE_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
DELETE_CONFIRMATION_TEXT = "삭제를 확인합니다."
DELETE_CHUNK_CONFIRMATION_TEXT = "조각 삭제를 확인합니다."


def csrf_token(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    if not match:
        raise RuntimeError("CSRF 토큰을 찾을 수 없습니다.")
    return match.group(1)


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    password = os.getenv("DEMO_ACCOUNT_PASSWORD", "")
    if not password:
        raise SystemExit("DEMO_ACCOUNT_PASSWORD 환경변수를 설정하세요.")

    title = f"Codex master 관리기능 검증 {uuid4()}"
    document_id = ""
    session = requests.Session()

    login_page = session.get(f"{BASE_URL}/auth/login", timeout=15)
    login_page.raise_for_status()
    logged_in = session.post(
        f"{BASE_URL}/auth/login",
        data={
            "csrf_token": csrf_token(login_page.text),
            "email": "master1",
            "password": password,
        },
        timeout=30,
    )
    logged_in.raise_for_status()
    if not logged_in.url.endswith("/documents"):
        raise RuntimeError("master1 로그인에 실패했습니다.")

    manage = session.get(f"{BASE_URL}/admin/manage", timeout=30)
    manage.raise_for_status()
    if "자료 영구 삭제" not in manage.text or DELETE_CONFIRMATION_TEXT not in manage.text:
        raise RuntimeError("master1 삭제 화면이 표시되지 않습니다.")

    created = session.post(
        f"{BASE_URL}/admin/documents",
        data={
            "csrf_token": csrf_token(manage.text),
            "title": title,
            "description": "삭제 기능 라이브 검증 후 즉시 제거되는 임시 자료",
        },
        timeout=30,
    )
    created.raise_for_status()
    match = re.search(r"/documents/([0-9a-f-]{36})$", created.url)
    if not match:
        raise RuntimeError("임시 자료 ID를 확인할 수 없습니다.")
    document_id = match.group(1)

    manage = session.get(f"{BASE_URL}/admin/manage", timeout=30)
    team_match = re.search(
        r'<option value="([0-9a-f-]{36})">재생에너지팀</option>', manage.text
    )
    if not team_match:
        raise RuntimeError("임시 조각을 배정할 팀 ID를 확인할 수 없습니다.")
    chunk_created = session.post(
        f"{BASE_URL}/admin/documents/{document_id}/chunks",
        data={
            "csrf_token": csrf_token(manage.text),
            "chunk_code": "TMP-1",
            "title": "삭제 연쇄 검증 조각",
            "team_id": team_match.group(1),
        },
        timeout=30,
    )
    chunk_created.raise_for_status()
    if "삭제 연쇄 검증 조각" not in chunk_created.text:
        raise RuntimeError("임시 자료의 하위 조각 생성에 실패했습니다.")
    chunk_match = re.search(r'/admin/chunks/([0-9a-f-]{36})/title', chunk_created.text)
    if not chunk_match:
        raise RuntimeError("임시 조각 ID를 확인할 수 없습니다.")
    chunk_id = chunk_match.group(1)

    renamed_title = f"{title} 이름변경"
    manage = session.get(f"{BASE_URL}/admin/manage", timeout=30)
    renamed_document = session.post(
        f"{BASE_URL}/admin/documents/{document_id}/title",
        data={"csrf_token": csrf_token(manage.text), "title": renamed_title},
        timeout=30,
    )
    renamed_document.raise_for_status()
    if renamed_title not in renamed_document.text:
        raise RuntimeError("자료명 변경에 실패했습니다.")

    manage = session.get(f"{BASE_URL}/admin/manage", timeout=30)
    renamed_chunk = session.post(
        f"{BASE_URL}/admin/chunks/{chunk_id}/title",
        data={"csrf_token": csrf_token(manage.text), "title": "타 팀 편집 검증 조각"},
        timeout=30,
    )
    renamed_chunk.raise_for_status()
    if "타 팀 편집 검증 조각" not in renamed_chunk.text:
        raise RuntimeError("조각명 변경에 실패했습니다.")

    checked_out = session.post(
        f"{BASE_URL}/chunks/{chunk_id}/checkout",
        data={"csrf_token": csrf_token(renamed_chunk.text)},
        timeout=30,
    )
    checked_out.raise_for_status()
    if f"/chunks/{chunk_id}/submit" not in checked_out.url:
        raise RuntimeError("master1의 타 팀 조각 편집 잠금 획득에 실패했습니다.")

    sample_path = PROJECT_ROOT / "sample_files" / "i_1.hwpx"
    with sample_path.open("rb") as sample_file:
        submitted = session.post(
            f"{BASE_URL}/chunks/{chunk_id}/submit",
            data={
                "csrf_token": csrf_token(checked_out.text),
                "change_reason": "master1 타 팀 편집 권한 라이브 검증",
            },
            files={"file": (sample_path.name, sample_file, "application/haansofthwpx")},
            timeout=90,
        )
    submitted.raise_for_status()
    if f"/chunks/{chunk_id}/history" not in submitted.url:
        raise RuntimeError("master1의 타 팀 조각 버전 제출에 실패했습니다.")

    manage = session.get(f"{BASE_URL}/admin/manage", timeout=30)
    rejected_chunk = session.post(
        f"{BASE_URL}/admin/chunks/{chunk_id}/delete",
        data={
            "csrf_token": csrf_token(manage.text),
            "confirmation_text": "조각 삭제를 확인합니다",
        },
        timeout=30,
    )
    rejected_chunk.raise_for_status()
    if "타 팀 편집 검증 조각" not in rejected_chunk.text:
        raise RuntimeError("잘못된 확인 문구인데 조각이 삭제되었습니다.")

    manage = session.get(f"{BASE_URL}/admin/manage", timeout=30)
    deleted_chunk = session.post(
        f"{BASE_URL}/admin/chunks/{chunk_id}/delete",
        data={
            "csrf_token": csrf_token(manage.text),
            "confirmation_text": DELETE_CHUNK_CONFIRMATION_TEXT,
        },
        timeout=30,
    )
    deleted_chunk.raise_for_status()
    manage_after_chunk_delete = session.get(f"{BASE_URL}/admin/manage", timeout=30)
    if "타 팀 편집 검증 조각" in manage_after_chunk_delete.text:
        raise RuntimeError("버전이 있는 임시 조각 삭제에 실패했습니다.")

    manage = session.get(f"{BASE_URL}/admin/manage", timeout=30)
    rejected = session.post(
        f"{BASE_URL}/admin/documents/{document_id}/delete",
        data={
            "csrf_token": csrf_token(manage.text),
            "confirmation_text": "삭제를 확인합니다",
        },
        timeout=30,
    )
    rejected.raise_for_status()
    if renamed_title not in rejected.text:
        raise RuntimeError("잘못된 확인 문구인데 자료가 삭제되었습니다.")

    manage = session.get(f"{BASE_URL}/admin/manage", timeout=30)
    deleted = session.post(
        f"{BASE_URL}/admin/documents/{document_id}/delete",
        data={
            "csrf_token": csrf_token(manage.text),
            "confirmation_text": DELETE_CONFIRMATION_TEXT,
        },
        timeout=30,
    )
    deleted.raise_for_status()
    after_delete = session.get(f"{BASE_URL}/admin/manage", timeout=30)
    after_delete.raise_for_status()
    detail_after_delete = session.get(
        f"{BASE_URL}/documents/{document_id}", timeout=30
    )
    if renamed_title in after_delete.text or detail_after_delete.status_code != 404:
        raise RuntimeError(f"임시 자료 삭제에 실패했습니다: {document_id}")

    print("OK: master1 타 팀 편집, 이름 변경, 조각·자료 영구 삭제를 확인했습니다.")


if __name__ == "__main__":
    main()

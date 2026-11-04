from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.demo_data import (  # noqa: E402
    CHUNK_SPECS,
    DOCUMENT_TITLE,
    TEAM_SPECS,
    stable_id,
)


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"{name} 환경변수를 설정하세요.")
    return value


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    client = create_client(require_env("SUPABASE_URL"), require_env("SUPABASE_SECRET_KEY"))

    manager = (
        client.table("profiles")
        .select("id")
        .eq("email", "policy1@example.com")
        .eq("is_final_manager", True)
        .single()
        .execute()
        .data
    )
    if not manager:
        raise SystemExit("먼저 scripts/seed_demo_users.py를 실행하세요.")

    document_id = stable_id("document", DOCUMENT_TITLE)
    client.table("documents").upsert(
        {
            "id": document_id,
            "series_id": stable_id("series", DOCUMENT_TITLE),
            "revision_no": 1,
            "title": DOCUMENT_TITLE,
            "description": "전산부서 시연을 위한 비실제 샘플 자료입니다.",
            "status": "draft",
            "created_by": manager["id"],
        },
        on_conflict="id",
    ).execute()

    team_ids = {key: stable_id("team", key) for key, _name in TEAM_SPECS}
    chunks = [
        {
            "id": stable_id("chunk", code),
            "document_id": document_id,
            "chunk_code": code,
            "title": title,
            "team_id": team_ids[team_key],
            "display_order": index,
            "is_required": True,
        }
        for index, (code, title, team_key) in enumerate(CHUNK_SPECS, start=1)
    ]
    client.table("chunks").upsert(chunks, on_conflict="id").execute()

    print(f"데모 자료 1건과 조각 {len(chunks)}건을 준비했습니다.")


if __name__ == "__main__":
    main()

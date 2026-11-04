from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.demo_data import CHUNK_SPECS, sample_filename, stable_id  # noqa: E402


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"{name} 환경변수를 설정하세요.")
    return value


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    client = create_client(require_env("SUPABASE_URL"), require_env("SUPABASE_SECRET_KEY"))
    bucket = os.getenv("SUPABASE_STORAGE_BUCKET", "workspace-files")
    document_id = stable_id("document", "2027년 샘플에너지과 주요업무계획")
    manager = (
        client.table("profiles").select("id").eq("email", "policy1@example.com").single().execute().data
    )
    samples = PROJECT_ROOT / "sample_files"

    for code, _title, _team in CHUNK_SPECS:
        chunk_id = stable_id("chunk", code)
        path = samples / sample_filename(code)
        if not path.exists():
            raise SystemExit("먼저 npm run generate:samples를 실행하세요.")
        content = path.read_bytes()
        storage_path = f"documents/{document_id}/chunks/{chunk_id}/v1.hwpx"
        try:
            client.storage.from_(bucket).upload(
                storage_path,
                content,
                file_options={"content-type": "application/haansofthwpx", "upsert": "false"},
            )
        except Exception as exc:
            if "already exists" not in str(exc).lower() and "duplicate" not in str(exc).lower():
                raise
        version = (
            client.table("chunk_versions")
            .upsert(
                {
                    "chunk_id": chunk_id,
                    "version_no": 1,
                    "storage_path": storage_path,
                    "original_filename": path.name,
                    "file_size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "uploaded_by": manager["id"],
                    "change_reason": "초기 배포본",
                    "diff_status": "not_applicable",
                    "diff_summary": "최초 버전으로 비교 대상이 없습니다.",
                },
                on_conflict="chunk_id,version_no",
            )
            .execute()
            .data[0]
        )
        client.table("chunks").update(
            {"current_version": 1, "status": "not_started", "approved_version_id": None}
        ).eq("id", chunk_id).execute()
        print(f"초기 파일 준비 완료: {code} ({version['id']})")


if __name__ == "__main__":
    main()


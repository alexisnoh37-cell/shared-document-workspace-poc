from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from dotenv import load_dotenv
from supabase import create_client

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKUP_ROOT = PROJECT_ROOT / "instance" / "backups"
TABLES = (
    "departments",
    "teams",
    "profiles",
    "documents",
    "chunks",
    "chunk_versions",
    "reviews",
    "document_confirmations",
    "document_confirmation_items",
    "activity_logs",
)


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"{name} 환경변수를 설정하세요.")
    return value


def json_write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def export_table(client, table: str, target: Path) -> int:
    rows: list[dict] = []
    page_size = 1000
    offset = 0
    while True:
        page = (
            client.table(table)
            .select("*")
            .range(offset, offset + page_size - 1)
            .execute()
            .data
            or []
        )
        rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    json_write(target, rows)
    return len(rows)


def export_auth_users(client, target: Path) -> int:
    response = client.auth.admin.list_users()
    users = response if isinstance(response, list) else list(getattr(response, "users", []) or [])
    exported = []
    for user in users:
        exported.append(
            {
                "id": str(getattr(user, "id", "")),
                "email": getattr(user, "email", None),
                "role": getattr(user, "role", None),
                "created_at": getattr(user, "created_at", None),
                "confirmed_at": getattr(user, "confirmed_at", None),
                "last_sign_in_at": getattr(user, "last_sign_in_at", None),
                "user_metadata": getattr(user, "user_metadata", None) or {},
            }
        )
    json_write(target, exported)
    return len(exported)


def item_value(item, name: str, default=None):
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def export_storage(client, bucket_name: str, target: Path) -> list[dict]:
    bucket = client.storage.from_(bucket_name)
    exported: list[dict] = []

    def walk(prefix: str = "") -> None:
        offset = 0
        page_size = 1000
        while True:
            entries = bucket.list(
                prefix,
                {"limit": page_size, "offset": offset, "sortBy": {"column": "name", "order": "asc"}},
            )
            for entry in entries:
                name = str(item_value(entry, "name", ""))
                if not name:
                    continue
                object_path = f"{prefix}/{name}" if prefix else name
                if item_value(entry, "id") is None:
                    walk(object_path)
                    continue
                safe_parts = PurePosixPath(object_path).parts
                if not safe_parts or ".." in safe_parts:
                    raise RuntimeError(f"안전하지 않은 Storage 경로입니다: {object_path}")
                content = bucket.download(object_path)
                output = target.joinpath(*safe_parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(content)
                exported.append(
                    {
                        "path": object_path,
                        "size": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                    }
                )
            if len(entries) < page_size:
                break
            offset += page_size

    walk()
    return exported


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="현재 Supabase 워크스페이스를 로컬에 백업합니다.")
    parser.add_argument(
        "--label",
        default=f"pre-collaboration-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}",
        help="instance/backups 아래에 만들 백업 디렉터리 이름",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.label or any(part in {"", ".", ".."} for part in Path(args.label).parts):
        raise SystemExit("안전한 백업 이름을 입력하세요.")
    load_dotenv(PROJECT_ROOT / ".env")
    backup_dir = DEFAULT_BACKUP_ROOT / args.label
    if backup_dir.exists():
        raise SystemExit(f"이미 존재하는 백업입니다: {backup_dir}")
    backup_dir.mkdir(parents=True)

    client = create_client(require_env("SUPABASE_URL"), require_env("SUPABASE_SECRET_KEY"))
    table_counts = {
        table: export_table(client, table, backup_dir / "database" / f"{table}.json")
        for table in TABLES
    }
    auth_count = export_auth_users(client, backup_dir / "auth" / "users.json")
    bucket_name = os.getenv("SUPABASE_STORAGE_BUCKET", "workspace-files").strip()
    storage_files = export_storage(client, bucket_name, backup_dir / "storage" / bucket_name)

    env_dir = backup_dir / "environment"
    env_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PROJECT_ROOT / ".env", env_dir / ".env")
    manifest = {
        "format_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "label": args.label,
        "source": {
            "supabase_url": require_env("SUPABASE_URL"),
            "storage_bucket": bucket_name,
        },
        "table_counts": table_counts,
        "auth_user_count": auth_count,
        "storage_files": storage_files,
        "environment_backup": "environment/.env",
        "warning": "이 디렉터리는 비밀 키와 업무 파일을 포함하므로 Git에 추가하지 마세요.",
    }
    json_write(backup_dir / "manifest.json", manifest)
    print(f"backup_path={backup_dir}")
    print(f"database_rows={sum(table_counts.values())}")
    print(f"auth_users={auth_count}")
    print(f"storage_files={len(storage_files)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"백업 실패: {exc}", file=sys.stderr)
        raise

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description="로컬 워크스페이스 백업의 무결성을 확인합니다.")
    parser.add_argument("backup", type=Path)
    args = parser.parse_args()
    backup = args.backup.resolve()
    allowed_root = (PROJECT_ROOT / "instance" / "backups").resolve()
    if backup != allowed_root and allowed_root not in backup.parents:
        raise SystemExit("instance/backups 아래의 백업만 검증할 수 있습니다.")

    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    for table, expected_count in manifest["table_counts"].items():
        rows = json.loads((backup / "database" / f"{table}.json").read_text(encoding="utf-8"))
        if len(rows) != expected_count:
            raise RuntimeError(f"{table} 행 수가 일치하지 않습니다.")
    auth_users = json.loads((backup / "auth" / "users.json").read_text(encoding="utf-8"))
    if len(auth_users) != manifest["auth_user_count"]:
        raise RuntimeError("Auth 사용자 수가 일치하지 않습니다.")
    if not (backup / manifest["environment_backup"]).is_file():
        raise RuntimeError("환경설정 백업이 없습니다.")

    storage_root = backup / "storage" / manifest["source"]["storage_bucket"]
    for item in manifest["storage_files"]:
        path = storage_root.joinpath(*PurePosixPath(item["path"]).parts)
        content = path.read_bytes()
        if len(content) != item["size"] or hashlib.sha256(content).hexdigest() != item["sha256"]:
            raise RuntimeError(f"Storage 파일 무결성 오류: {item['path']}")
    print("OK: 백업 행 수, 환경설정, Storage SHA-256 무결성을 확인했습니다.")


if __name__ == "__main__":
    main()

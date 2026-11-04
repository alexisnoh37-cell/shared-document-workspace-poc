from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.demo_data import DEPARTMENT_NAME, TEAM_SPECS, USER_SPECS, stable_id  # noqa: E402


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"{name} 환경변수를 설정하세요.")
    return value


def list_auth_users(admin) -> list:
    response = admin.list_users()
    if isinstance(response, list):
        return response
    return list(getattr(response, "users", []) or [])


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    client = create_client(require_env("SUPABASE_URL"), require_env("SUPABASE_SECRET_KEY"))
    password = require_env("DEMO_ACCOUNT_PASSWORD")
    existing = {getattr(user, "email", "").lower(): user for user in list_auth_users(client.auth.admin)}
    team_ids = {key: stable_id("team", key) for key, _name in TEAM_SPECS}
    department_id = stable_id("department", DEPARTMENT_NAME)
    client.table("departments").upsert(
        {"id": department_id, "name": DEPARTMENT_NAME}, on_conflict="id"
    ).execute()
    for key, team_name in TEAM_SPECS:
        client.table("teams").upsert(
            {"id": team_ids[key], "department_id": department_id, "name": team_name},
            on_conflict="id",
        ).execute()

    for email, name, team_key, role, is_final_manager in USER_SPECS:
        user = existing.get(email)
        if user is None:
            response = client.auth.admin.create_user(
                {"email": email, "password": password, "email_confirm": True}
            )
            user = response.user
        if user is None:
            raise RuntimeError(f"{email} Auth 사용자를 만들 수 없습니다.")
        client.table("profiles").upsert(
            {
                "id": stable_id("profile", email),
                "auth_user_id": str(user.id),
                "email": email,
                "name": name,
                "team_id": team_ids[team_key],
                "role": role,
                "is_final_manager": is_final_manager,
                "active": True,
            },
            on_conflict="auth_user_id",
        ).execute()
        print(f"준비 완료: {email}")

    print("16개 데모 Auth 계정과 프로필을 준비했습니다. 비밀번호 값은 출력하지 않았습니다.")


if __name__ == "__main__":
    main()

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.demo_data import stable_id  # noqa: E402
from services.identity import MASTER_EMAIL, MASTER_LOGIN_ID  # noqa: E402


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

    policy_team_id = stable_id("team", "policy")
    team = (
        client.table("teams")
        .select("id")
        .eq("id", policy_team_id)
        .maybe_single()
        .execute()
        .data
    )
    if not team:
        raise RuntimeError("에너지정책팀이 없습니다. 먼저 기본 데이터 시드를 실행하세요.")

    existing = {
        getattr(user, "email", "").lower(): user
        for user in list_auth_users(client.auth.admin)
    }
    user = existing.get(MASTER_EMAIL)
    if user is None:
        response = client.auth.admin.create_user(
            {"email": MASTER_EMAIL, "password": password, "email_confirm": True}
        )
        user = response.user
    else:
        response = client.auth.admin.update_user_by_id(
            str(user.id), {"password": password, "email_confirm": True}
        )
        user = response.user
    if user is None:
        raise RuntimeError("master1 Auth 사용자를 만들 수 없습니다.")

    client.table("profiles").upsert(
        {
            "id": stable_id("profile", MASTER_EMAIL),
            "auth_user_id": str(user.id),
            "email": MASTER_EMAIL,
            "name": MASTER_LOGIN_ID,
            "team_id": policy_team_id,
            "role": "reviewer",
            "is_final_manager": True,
            "active": True,
        },
        on_conflict="auth_user_id",
    ).execute()
    print("master1 인증 계정과 활성 프로필을 준비했습니다. 비밀번호 값은 출력하지 않았습니다.")


if __name__ == "__main__":
    main()

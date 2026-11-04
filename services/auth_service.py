from __future__ import annotations

import hmac
from typing import Any

from .errors import AuthenticationError, IntegrationError


class MemoryAuthService:
    def __init__(self, workspace: Any, runtime_password: str):
        self.workspace = workspace
        self.runtime_password = runtime_password

    def login(self, email: str, password: str) -> tuple[dict, dict, None]:
        if not self.runtime_password:
            raise IntegrationError("DEMO_ACCOUNT_PASSWORD 환경변수를 설정해야 합니다.")
        profile = self.workspace.get_profile_by_email(email.strip().lower())
        if not profile or not hmac.compare_digest(password, self.runtime_password):
            raise AuthenticationError("이메일 또는 비밀번호가 올바르지 않습니다.")
        if not profile.get("active"):
            raise AuthenticationError("비활성화된 계정입니다.")
        return profile, {"profile_id": profile["id"]}, None

    def restore(self, auth_session: dict) -> tuple[dict | None, None, dict]:
        profile = self.workspace.get_profile(auth_session.get("profile_id", ""))
        if not profile or not profile.get("active"):
            return None, None, {}
        return profile, None, auth_session

    def logout(self, _client: None = None) -> None:
        return None


class SupabaseAuthService:
    def __init__(self, url: str, publishable_key: str):
        if not url or not publishable_key:
            raise IntegrationError(
                "Supabase 모드에는 SUPABASE_URL과 SUPABASE_PUBLISHABLE_KEY가 필요합니다."
            )
        self.url = url
        self.publishable_key = publishable_key

    def _client(self):
        try:
            from supabase import create_client
        except ImportError as exc:
            raise IntegrationError("supabase Python 패키지가 설치되지 않았습니다.") from exc
        return create_client(self.url, self.publishable_key)

    def login(self, email: str, password: str) -> tuple[dict, dict, Any]:
        client = self._client()
        try:
            response = client.auth.sign_in_with_password(
                {"email": email.strip().lower(), "password": password}
            )
            if not response.session or not response.user:
                raise AuthenticationError("로그인 세션을 만들 수 없습니다.")
            profile = self._profile_for_auth_user(client, str(response.user.id))
            auth_session = {
                "access_token": response.session.access_token,
                "refresh_token": response.session.refresh_token,
            }
            return profile, auth_session, client
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError("이메일 또는 비밀번호가 올바르지 않습니다.") from exc

    def restore(self, auth_session: dict) -> tuple[dict | None, Any | None, dict]:
        access_token = auth_session.get("access_token")
        refresh_token = auth_session.get("refresh_token")
        if not access_token or not refresh_token:
            return None, None, {}
        client = self._client()
        try:
            response = client.auth.set_session(access_token, refresh_token)
            if not response.user or not response.session:
                return None, None, {}
            profile = self._profile_for_auth_user(client, str(response.user.id))
            refreshed = {
                "access_token": response.session.access_token,
                "refresh_token": response.session.refresh_token,
            }
            return profile, client, refreshed
        except Exception:
            return None, None, {}

    def logout(self, client: Any | None = None) -> None:
        if client is not None:
            try:
                client.auth.sign_out()
            except Exception:
                pass

    @staticmethod
    def _profile_for_auth_user(client: Any, auth_user_id: str) -> dict:
        response = (
            client.table("profiles")
            .select("*, teams(name)")
            .eq("auth_user_id", auth_user_id)
            .eq("active", True)
            .single()
            .execute()
        )
        profile = response.data
        if not profile:
            raise AuthenticationError("활성 사용자 프로필이 없습니다.")
        team = profile.pop("teams", None) or {}
        profile["team_name"] = team.get("name", "")
        return profile


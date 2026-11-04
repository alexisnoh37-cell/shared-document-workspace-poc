from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "")
    APP_BACKEND = os.getenv("APP_BACKEND", "memory").strip().lower()
    DEBUG = _as_bool(os.getenv("FLASK_DEBUG"), False)
    SESSION_TYPE = "cachelib"
    SESSION_PERMANENT = False
    SESSION_CACHE_DIR = str(BASE_DIR / os.getenv("SESSION_FILE_DIR", "instance/sessions"))
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = _as_bool(os.getenv("SESSION_COOKIE_SECURE"), False)
    SESSION_COOKIE_SAMESITE = "Lax"
    SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
    SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
    SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "").strip()
    SUPABASE_STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "workspace-files").strip()
    DEMO_ACCOUNT_PASSWORD = os.getenv("DEMO_ACCOUNT_PASSWORD", "")
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_UPLOAD_MB", "25")) * 1024 * 1024
    KORDOC_NODE_BIN = os.getenv("KORDOC_NODE_BIN", "node")
    KORDOC_TIMEOUT_SECONDS = int(os.getenv("KORDOC_TIMEOUT_SECONDS", "60"))
    RHWP_EDITOR_ENABLED = _as_bool(os.getenv("RHWP_EDITOR_ENABLED"), False)
    COLLAB_EDITOR_ENABLED = _as_bool(os.getenv("COLLAB_EDITOR_ENABLED"), False)
    COLLAB_LOCK_IDLE_MINUTES = int(os.getenv("COLLAB_LOCK_IDLE_MINUTES", "30"))
    COLLAB_POLL_SECONDS = int(os.getenv("COLLAB_POLL_SECONDS", "3"))
    RHWP_SPIKE_ENABLED = _as_bool(os.getenv("RHWP_SPIKE_ENABLED"), False)
    RHWP_STUDIO_URL = os.getenv(
        "RHWP_STUDIO_URL", "https://edwardkim.github.io/rhwp/"
    ).strip()
    WTF_CSRF_TIME_LIMIT = None


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-only-secret"
    SESSION_TYPE = "cachelib"
    WTF_CSRF_ENABLED = False
    APP_BACKEND = "memory"
    DEMO_ACCOUNT_PASSWORD = "test-password"
    # 테스트 결과가 개발자의 로컬 .env에 좌우되지 않도록 기능 플래그를 고정한다.
    RHWP_EDITOR_ENABLED = True
    RHWP_SPIKE_ENABLED = False
    COLLAB_EDITOR_ENABLED = False

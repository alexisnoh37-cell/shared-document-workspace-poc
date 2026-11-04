from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app  # noqa: E402
from config import TestConfig  # noqa: E402


@pytest.fixture
def app(tmp_path):
    class IsolatedTestConfig(TestConfig):
        SESSION_CACHE_DIR = str(tmp_path / "sessions")

    application = create_app(IsolatedTestConfig)
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, email: str, password: str = "test-password", follow_redirects: bool = True):
    return client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=follow_redirects,
    )


@pytest.fixture
def login_user():
    return login

from __future__ import annotations


MASTER_LOGIN_ID = "master1"
MASTER_EMAIL = "master1@example.com"
DELETE_CONFIRMATION_TEXT = "삭제를 확인합니다."
DELETE_CHUNK_CONFIRMATION_TEXT = "조각 삭제를 확인합니다."


def normalize_login_identifier(value: str) -> str:
    identifier = value.strip().lower()
    return MASTER_EMAIL if identifier == MASTER_LOGIN_ID else identifier

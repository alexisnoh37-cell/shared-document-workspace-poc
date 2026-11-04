from __future__ import annotations

from .errors import AuthorizationError
from .identity import MASTER_EMAIL


def is_master(user: dict) -> bool:
    return bool(
        user.get("active")
        and str(user.get("email", "")).strip().lower() == MASTER_EMAIL
    )


def can_edit_chunk(user: dict, chunk: dict) -> bool:
    return bool(
        user.get("active")
        and (
            is_master(user)
            or (
                user.get("team_id")
                and user.get("team_id") == chunk.get("team_id")
            )
        )
    )


def can_review_chunk(user: dict, chunk: dict) -> bool:
    return bool(
        user.get("active")
        and user.get("role") == "reviewer"
        and user.get("team_id")
        and user.get("team_id") == chunk.get("team_id")
    )


def can_finalize(user: dict) -> bool:
    return bool(user.get("active") and user.get("is_final_manager"))


def can_delete_document(user: dict) -> bool:
    return is_master(user)


def can_force_unlock_chunk(user: dict, chunk: dict) -> bool:
    return can_review_chunk(user, chunk) or is_master(user)


def require_edit(user: dict, chunk: dict) -> None:
    if not can_edit_chunk(user, chunk):
        raise AuthorizationError("본인 소속 팀의 문서 조각만 편집할 수 있습니다.")


def require_review(user: dict, chunk: dict) -> None:
    if not can_review_chunk(user, chunk):
        raise AuthorizationError("소속 팀의 검토자만 승인 또는 반려할 수 있습니다.")


def require_force_unlock(user: dict, chunk: dict) -> None:
    if not can_force_unlock_chunk(user, chunk):
        raise AuthorizationError("소속 팀 검토자 또는 master1만 잠금을 해제할 수 있습니다.")


def require_final_manager(user: dict) -> None:
    if not can_finalize(user):
        raise AuthorizationError("총괄자만 수행할 수 있는 작업입니다.")


def require_master(user: dict) -> None:
    if not can_delete_document(user):
        raise AuthorizationError("자료 영구 삭제는 master1 계정만 수행할 수 있습니다.")

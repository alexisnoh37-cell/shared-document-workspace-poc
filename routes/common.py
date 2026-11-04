from __future__ import annotations

from functools import wraps
from urllib.parse import urljoin, urlparse

from flask import abort, current_app, g, redirect, request, url_for

from services.errors import AuthorizationError
from services.permission_service import require_final_manager, require_master


def workspace():
    return current_app.extensions["workspace_service"]


def kordoc():
    return current_app.extensions["kordoc_service"]


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.current_user is None:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapped


def reviewer_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if g.current_user.get("role") != "reviewer":
            raise AuthorizationError("팀 검토자만 접근할 수 있습니다.")
        return view(*args, **kwargs)

    return wrapped


def final_manager_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        require_final_manager(g.current_user)
        return view(*args, **kwargs)

    return wrapped


def master_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        require_master(g.current_user)
        return view(*args, **kwargs)

    return wrapped


def is_safe_next_url(target: str | None) -> bool:
    if not target:
        return False
    host_url = urlparse(request.host_url)
    redirect_url = urlparse(urljoin(request.host_url, target))
    return redirect_url.scheme in {"http", "https"} and host_url.netloc == redirect_url.netloc


def require_form_value(name: str) -> str:
    value = request.form.get(name, "").strip()
    if not value:
        abort(400)
    return value


def require_same_origin() -> None:
    fetch_site = request.headers.get("Sec-Fetch-Site", "").lower()
    if fetch_site == "cross-site":
        raise AuthorizationError("다른 사이트에서 시작된 저장 요청은 허용하지 않습니다.")

    origin = request.headers.get("Origin")
    if not origin:
        return
    expected = urlparse(request.host_url)
    supplied = urlparse(origin)
    if supplied.scheme not in {"http", "https"} or supplied.netloc != expected.netloc:
        raise AuthorizationError("요청 출처가 현재 워크스페이스와 일치하지 않습니다.")

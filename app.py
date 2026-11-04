from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from cachelib.file import FileSystemCache
from flask import Flask, g, redirect, render_template, session, url_for
from flask_session import Session
from flask_wtf.csrf import CSRFProtect

from config import BASE_DIR, Config
from services.auth_service import MemoryAuthService, SupabaseAuthService
from services.demo_service import MemoryWorkspaceService
from services.errors import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    IntegrationError,
    NotFoundError,
    ValidationError,
)
from services.kordoc_service import KordocService
from services.permission_service import (
    can_delete_document,
    can_edit_chunk,
    can_finalize,
    can_force_unlock_chunk,
    can_review_chunk,
)
from services.supabase_service import SupabaseWorkspaceService


csrf = CSRFProtect()
server_session = Session()


def create_app(config_object=Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)
    _validate_config(app)

    Path(app.config["SESSION_CACHE_DIR"]).mkdir(parents=True, exist_ok=True)
    app.config["SESSION_CACHELIB"] = FileSystemCache(
        cache_dir=app.config["SESSION_CACHE_DIR"],
        threshold=500,
        default_timeout=86400,
    )
    server_session.init_app(app)
    csrf.init_app(app)

    if app.config["APP_BACKEND"] == "memory":
        workspace = MemoryWorkspaceService(
            BASE_DIR,
            idle_lock_minutes=(
                app.config["COLLAB_LOCK_IDLE_MINUTES"]
                if app.config["COLLAB_EDITOR_ENABLED"]
                else None
            ),
        )
        auth = MemoryAuthService(workspace, app.config["DEMO_ACCOUNT_PASSWORD"])
    elif app.config["APP_BACKEND"] == "supabase":
        workspace = SupabaseWorkspaceService(app.config["SUPABASE_STORAGE_BUCKET"])
        auth = SupabaseAuthService(
            app.config["SUPABASE_URL"],
            app.config["SUPABASE_PUBLISHABLE_KEY"],
        )
    else:
        raise RuntimeError("APP_BACKEND는 memory 또는 supabase여야 합니다.")

    app.extensions["workspace_service"] = workspace
    app.extensions["auth_service"] = auth
    app.extensions["kordoc_service"] = KordocService(
        BASE_DIR,
        app.config["KORDOC_NODE_BIN"],
        app.config["KORDOC_TIMEOUT_SECONDS"],
    )

    from routes.admin import bp as admin_bp
    from routes.auth import bp as auth_bp
    from routes.chunks import bp as chunks_bp
    from routes.documents import bp as documents_bp
    from routes.reviews import bp as reviews_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(chunks_bp)
    app.register_blueprint(reviews_bp)
    app.register_blueprint(admin_bp)
    if app.config["RHWP_SPIKE_ENABLED"]:
        from routes.rhwp_spike import bp as rhwp_spike_bp

        app.register_blueprint(rhwp_spike_bp)
    if app.config["COLLAB_EDITOR_ENABLED"]:
        from routes.collab import bp as collab_bp

        app.register_blueprint(collab_bp)

    @app.before_request
    def load_current_user() -> None:
        g.current_user = None
        g.supabase_client = None
        auth_session = session.get("auth")
        if not auth_session:
            return
        profile, client, refreshed = auth.restore(auth_session)
        if not profile:
            session.clear()
            return
        session["auth"] = refreshed
        g.current_user = profile
        g.supabase_client = client

    @app.get("/")
    def index():
        return redirect(url_for("documents.index") if g.current_user else url_for("auth.login"))

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "backend": app.config["APP_BACKEND"],
            "collaboration_enabled": bool(app.config["COLLAB_EDITOR_ENABLED"]),
            "kordoc_worker": str(app.extensions["kordoc_service"].worker),
        }

    @app.template_filter("datetime_ko")
    def datetime_ko(value):
        if not value:
            return "-"
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed.astimezone().strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            return str(value)

    @app.context_processor
    def inject_helpers():
        return {
            "current_user": g.get("current_user"),
            "can_edit_chunk": can_edit_chunk,
            "can_review_chunk": can_review_chunk,
            "can_finalize": can_finalize,
            "can_force_unlock_chunk": can_force_unlock_chunk,
            "can_delete_document": can_delete_document,
            "chunk_status_labels": {
                "not_started": "미착수",
                "editing": "편집중",
                "submitted": "제출완료",
                "approved": "승인",
                "rejected": "반려",
            },
            "document_status_labels": {
                "draft": "작성전",
                "in_progress": "진행중",
                "ready_to_confirm": "확정대기",
                "confirmed": "최종확정",
            },
        }

    @app.errorhandler(AuthorizationError)
    def forbidden(exc):
        return render_template("errors/error.html", code=403, message=str(exc)), 403

    @app.errorhandler(NotFoundError)
    def not_found(exc):
        return render_template("errors/error.html", code=404, message=str(exc)), 404

    @app.errorhandler(ConflictError)
    @app.errorhandler(ValidationError)
    @app.errorhandler(AuthenticationError)
    def bad_request(exc):
        return render_template("errors/error.html", code=400, message=str(exc)), 400

    @app.errorhandler(IntegrationError)
    def integration_error(exc):
        return render_template("errors/error.html", code=503, message=str(exc)), 503

    @app.errorhandler(413)
    def too_large(_exc):
        return render_template(
            "errors/error.html",
            code=413,
            message="업로드 파일이 허용된 최대 크기를 초과했습니다.",
        ), 413

    return app


def _validate_config(app: Flask) -> None:
    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY 환경변수를 설정해야 합니다.")
    if app.config["COLLAB_EDITOR_ENABLED"] and app.config["APP_BACKEND"] != "memory":
        raise RuntimeError(
            "COLLAB_EDITOR_ENABLED는 현재 APP_BACKEND=memory에서만 지원합니다."
        )
    if int(app.config.get("COLLAB_LOCK_IDLE_MINUTES", 30)) < 1:
        raise RuntimeError("COLLAB_LOCK_IDLE_MINUTES는 1 이상이어야 합니다.")
    if int(app.config.get("COLLAB_POLL_SECONDS", 3)) < 1:
        raise RuntimeError("COLLAB_POLL_SECONDS는 1 이상이어야 합니다.")
    if app.config["APP_BACKEND"] == "supabase":
        if not app.config.get("SUPABASE_URL") or not app.config.get("SUPABASE_PUBLISHABLE_KEY"):
            raise RuntimeError(
                "Supabase 모드에는 SUPABASE_URL과 SUPABASE_PUBLISHABLE_KEY가 필요합니다."
            )
    if app.config.get("RHWP_EDITOR_ENABLED") or app.config.get("RHWP_SPIKE_ENABLED"):
        studio_url = urlparse(app.config.get("RHWP_STUDIO_URL", ""))
        if studio_url.scheme not in {"http", "https"} or not studio_url.netloc:
            raise RuntimeError("RHWP_STUDIO_URL은 HTTP(S) URL이어야 합니다.")


if __name__ == "__main__":
    application = create_app()
    application.run(host="127.0.0.1", port=5000, debug=application.config["DEBUG"])

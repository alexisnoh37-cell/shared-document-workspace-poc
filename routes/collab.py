from __future__ import annotations

from datetime import UTC, datetime

from flask import Blueprint, current_app, g, jsonify

from services.errors import NotFoundError

from .common import login_required, workspace


bp = Blueprint("collab", __name__, url_prefix="/collab")


@bp.get("/documents/<document_id>/locks.json")
@login_required
def document_locks(document_id: str):
    try:
        chunks = workspace().list_document_locks(document_id, g.current_user)
    except NotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify(
        {
            "server_time": datetime.now(UTC).isoformat(),
            "poll_seconds": current_app.config["COLLAB_POLL_SECONDS"],
            "chunks": chunks,
        }
    )


@bp.post("/chunks/<chunk_id>/heartbeat")
@login_required
def heartbeat(chunk_id: str):
    ok = workspace().touch_lock(chunk_id, g.current_user)
    return jsonify({"ok": ok}), (200 if ok else 409)

from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from services.errors import ConflictError, ValidationError
from services.permission_service import require_review

from .common import reviewer_required, workspace


bp = Blueprint("reviews", __name__, url_prefix="/reviews")


@bp.get("")
@reviewer_required
def index():
    return render_template("reviews/index.html", chunks=workspace().list_review_queue(g.current_user))


@bp.post("/<chunk_id>")
@reviewer_required
def decide(chunk_id: str):
    chunk = workspace().get_chunk(chunk_id)
    require_review(g.current_user, chunk)
    action = request.form.get("action", "")
    comment = request.form.get("comment", "")
    try:
        workspace().review_chunk(g.current_user, chunk_id, action, comment)
    except (ConflictError, ValidationError) as exc:
        flash(str(exc), "danger")
    else:
        flash("승인했습니다." if action == "approve" else "반려했습니다.", "success")
    return redirect(url_for("reviews.index"))


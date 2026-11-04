from __future__ import annotations

from flask import Blueprint, render_template, request

from .common import login_required, workspace


bp = Blueprint("documents", __name__, url_prefix="/documents")


@bp.get("")
@login_required
def index():
    return render_template("documents/index.html", documents=workspace().list_documents())


@bp.get("/<document_id>")
@login_required
def detail(document_id: str):
    team_id = request.args.get("team", "").strip()
    status = request.args.get("status", "").strip()
    document = workspace().get_document(document_id)
    chunks = workspace().list_chunks(document_id, team_id, status)
    return render_template(
        "documents/detail.html",
        document=document,
        chunks=chunks,
        teams=workspace().list_teams(),
        selected_team=team_id,
        selected_status=status,
    )


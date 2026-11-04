from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from services.errors import ConflictError, IntegrationError, NotFoundError, ValidationError
from services.identity import DELETE_CHUNK_CONFIRMATION_TEXT, DELETE_CONFIRMATION_TEXT

from .common import final_manager_required, master_required, workspace


bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.get("/dashboard")
@final_manager_required
def dashboard():
    documents = workspace().list_documents()
    document_id = request.args.get("document", "").strip()
    if not document_id and documents:
        document_id = documents[0]["id"]
    data = (
        workspace().dashboard(
            document_id,
            request.args.get("team", "").strip(),
            request.args.get("status", "").strip(),
        )
        if document_id
        else None
    )
    return render_template(
        "admin/dashboard.html",
        documents=documents,
        dashboard=data,
        teams=workspace().list_teams(),
        selected_document=document_id,
        selected_team=request.args.get("team", "").strip(),
        selected_status=request.args.get("status", "").strip(),
    )


@bp.post("/documents/<document_id>/confirm")
@final_manager_required
def confirm(document_id: str):
    try:
        workspace().confirm_document(g.current_user, document_id)
    except ConflictError as exc:
        flash(str(exc), "danger")
    else:
        flash("현재 승인 버전을 최종자료로 확정했습니다.", "success")
    return redirect(url_for("admin.dashboard", document=document_id))


@bp.get("/manage")
@final_manager_required
def manage():
    documents = workspace().list_documents()
    chunks_by_document = {
        document["id"]: workspace().list_chunks(document["id"]) for document in documents
    }
    return render_template(
        "admin/manage.html",
        profiles=workspace().list_profiles(),
        teams=workspace().list_teams(),
        documents=documents,
        chunks_by_document=chunks_by_document,
        delete_confirmation_text=DELETE_CONFIRMATION_TEXT,
        delete_chunk_confirmation_text=DELETE_CHUNK_CONFIRMATION_TEXT,
    )


@bp.post("/profiles/<profile_id>/active")
@final_manager_required
def set_profile_active(profile_id: str):
    active = request.form.get("active") == "true"
    try:
        workspace().set_profile_active(g.current_user, profile_id, active)
    except ValidationError as exc:
        flash(str(exc), "danger")
    else:
        flash("사용자 상태를 변경했습니다.", "success")
    return redirect(url_for("admin.manage"))


@bp.post("/documents")
@final_manager_required
def create_document():
    try:
        document = workspace().create_document(
            g.current_user,
            request.form.get("title", ""),
            request.form.get("description", ""),
        )
    except (ConflictError, ValidationError) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("admin.manage"))
    flash("새 자료를 만들었습니다.", "success")
    return redirect(url_for("documents.detail", document_id=document["id"]))


@bp.post("/documents/<document_id>/chunks")
@final_manager_required
def create_chunk(document_id: str):
    try:
        workspace().create_chunk(
            g.current_user,
            document_id,
            request.form.get("chunk_code", ""),
            request.form.get("title", ""),
            request.form.get("team_id", ""),
        )
    except (ConflictError, ValidationError) as exc:
        flash(str(exc), "danger")
    else:
        flash("문서 조각을 추가했습니다.", "success")
    return redirect(url_for("admin.manage"))


@bp.post("/documents/<document_id>/title")
@master_required
def update_document_title(document_id: str):
    try:
        workspace().update_document_title(
            g.current_user, document_id, request.form.get("title", "")
        )
    except (ConflictError, NotFoundError, ValidationError) as exc:
        flash(str(exc), "danger")
    else:
        flash("자료명을 변경했습니다.", "success")
    return redirect(url_for("admin.manage"))


@bp.post("/chunks/<chunk_id>/title")
@master_required
def update_chunk_title(chunk_id: str):
    try:
        workspace().update_chunk_title(
            g.current_user, chunk_id, request.form.get("title", "")
        )
    except (ConflictError, NotFoundError, ValidationError) as exc:
        flash(str(exc), "danger")
    else:
        flash("조각명을 변경했습니다.", "success")
    return redirect(url_for("admin.manage"))


@bp.post("/chunks/<chunk_id>/delete")
@master_required
def delete_chunk(chunk_id: str):
    try:
        result = workspace().delete_chunk(
            g.current_user,
            chunk_id,
            request.form.get("confirmation_text", ""),
        )
    except (ConflictError, IntegrationError, NotFoundError, ValidationError) as exc:
        flash(str(exc), "danger")
    else:
        if result.get("storage_cleanup_failed"):
            flash(
                "조각은 삭제했지만 일부 저장 파일 정리에 실패했습니다. 관리자 로그를 확인하세요.",
                "warning",
            )
        else:
            flash(f"'{result['title']}' 조각을 영구 삭제했습니다.", "success")
    return redirect(url_for("admin.manage"))


@bp.post("/documents/<document_id>/delete")
@master_required
def delete_document(document_id: str):
    try:
        result = workspace().delete_document(
            g.current_user,
            document_id,
            request.form.get("confirmation_text", ""),
        )
    except (ConflictError, IntegrationError, NotFoundError, ValidationError) as exc:
        flash(str(exc), "danger")
    else:
        if result.get("storage_cleanup_failed"):
            flash(
                "자료는 삭제했지만 일부 저장 파일 정리에 실패했습니다. 관리자 로그를 확인하세요.",
                "warning",
            )
        else:
            flash(f"'{result['title']}' 자료를 영구 삭제했습니다.", "success")
    return redirect(url_for("admin.manage"))

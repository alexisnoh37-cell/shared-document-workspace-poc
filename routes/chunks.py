from __future__ import annotations

from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    g,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from services.errors import AuthorizationError, ConflictError, IntegrationError, ValidationError
from services.permission_service import require_edit, require_force_unlock, require_review
from services.storage_service import validate_document_bytes, validate_document_upload

from .common import kordoc, login_required, require_same_origin, workspace


bp = Blueprint("chunks", __name__, url_prefix="/chunks")


@bp.post("/<chunk_id>/checkout")
@login_required
def checkout(chunk_id: str):
    chunk = workspace().get_chunk(chunk_id)
    require_edit(g.current_user, chunk)
    try:
        workspace().checkout_chunk(g.current_user, chunk_id)
    except ConflictError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("documents.detail", document_id=chunk["document_id"]))
    flash(
        "편집 잠금을 획득했습니다. 브라우저에서 수정하거나 최신 파일을 내려받아 수정할 수 있습니다.",
        "success",
    )
    return redirect(url_for("chunks.submit", chunk_id=chunk_id))


@bp.route("/<chunk_id>/submit", methods=["GET", "POST"])
@login_required
def submit(chunk_id: str):
    chunk = workspace().get_chunk(chunk_id)
    require_edit(g.current_user, chunk)
    if chunk.get("locked_by") != g.current_user["id"]:
        raise ConflictError("먼저 편집 시작을 눌러 체크아웃해야 합니다.")

    if request.method == "POST":
        try:
            upload = validate_document_upload(
                request.files.get("file"),
                max_bytes=current_app.config["MAX_CONTENT_LENGTH"],
            )
            version = workspace().checkin_chunk(
                g.current_user,
                chunk_id,
                upload,
                request.form.get("change_reason", ""),
                kordoc(),
            )
        except (ConflictError, ValidationError) as exc:
            flash(str(exc), "danger")
        else:
            flash(f"v{version['version_no']} 제출을 완료했습니다.", "success")
            if version["diff_status"] == "failed":
                flash("파일은 정상 저장했지만 문서 비교 처리에 실패했습니다.", "warning")
            return redirect(url_for("chunks.history", chunk_id=chunk_id))

    versions = workspace().list_versions(chunk_id)
    locked_version = next(
        (row for row in versions if row["version_no"] == chunk.get("locked_version_no")),
        None,
    )
    return render_template(
        "chunks/submit.html",
        chunk=workspace().get_chunk(chunk_id),
        versions=versions,
        web_editor_supported=bool(
            current_app.config["RHWP_EDITOR_ENABLED"]
            and locked_version
            and Path(locked_version["original_filename"]).suffix.lower() == ".hwpx"
        ),
    )


@bp.get("/<chunk_id>/editor")
@login_required
def editor(chunk_id: str):
    chunk, version = _editor_source(chunk_id)
    studio = urlparse(current_app.config["RHWP_STUDIO_URL"])
    response = make_response(
        render_template(
            "chunks/editor.html",
            chunk=chunk,
            version=version,
            studio_url=current_app.config["RHWP_STUDIO_URL"],
        )
    )
    response.headers["Content-Security-Policy"] = (
        f"frame-src {studio.scheme}://{studio.netloc}; frame-ancestors 'self'"
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response


@bp.get("/<chunk_id>/editor/source")
@login_required
def editor_source(chunk_id: str):
    _chunk, version = _editor_source(chunk_id)
    content, filename = workspace().download_version(version["id"])
    response = send_file(
        BytesIO(content),
        as_attachment=False,
        download_name=filename,
        mimetype="application/vnd.hancom.hwpx",
        max_age=0,
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@bp.post("/<chunk_id>/editor/save")
@login_required
def editor_save(chunk_id: str):
    try:
        require_same_origin()
        chunk, source_version = _editor_source(chunk_id)
        exported = request.files.get("file")
        if exported is None:
            raise ValidationError("웹 편집기의 HWPX export 결과가 없습니다.")
        server_filename = f"{chunk['chunk_code']}-v{source_version['version_no'] + 1}-web.hwpx"
        upload = validate_document_bytes(
            exported.read(),
            server_filename,
            expected_extension=".hwpx",
            max_bytes=current_app.config["MAX_CONTENT_LENGTH"],
        )
        try:
            parsed = kordoc().parse_bytes(upload.content, upload.extension)
        except IntegrationError as exc:
            raise ValidationError(f"웹 편집 저장 검증에 실패했습니다: {exc}") from exc
        if parsed["file_type"] != "hwpx" or not parsed["blocks"]:
            raise ValidationError("Kordoc이 유효한 HWPX 문서 내용을 확인하지 못했습니다.")

        version = workspace().checkin_chunk(
            g.current_user,
            chunk_id,
            upload,
            request.form.get("change_reason", ""),
            kordoc(),
        )
    except AuthorizationError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 403
    except ConflictError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409
    except ValidationError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except IntegrationError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 503

    return jsonify(
        {
            "ok": True,
            "versionId": version["id"],
            "versionNo": version["version_no"],
            "filename": version["original_filename"],
            "diffStatus": version["diff_status"],
            "redirectUrl": url_for("chunks.diff", version_id=version["id"]),
        }
    )


@bp.get("/<chunk_id>/history")
@login_required
def history(chunk_id: str):
    return render_template(
        "chunks/history.html",
        chunk=workspace().get_chunk(chunk_id),
        versions=workspace().list_versions(chunk_id),
    )


@bp.get("/versions/<version_id>/diff")
@login_required
def diff(version_id: str):
    version = workspace().get_version(version_id)
    chunk = workspace().get_chunk(version["chunk_id"])
    return render_template("chunks/diff.html", chunk=chunk, version=version)


@bp.post("/versions/<version_id>/retry-diff")
@login_required
def retry_diff(version_id: str):
    version = workspace().get_version(version_id)
    chunk = workspace().get_chunk(version["chunk_id"])
    require_edit(g.current_user, chunk)
    updated = workspace().retry_diff(g.current_user, version_id, kordoc())
    if updated["diff_status"] == "failed":
        flash("문서 비교 재처리에 실패했습니다.", "warning")
    else:
        flash("문서 비교를 다시 처리했습니다.", "success")
    return redirect(url_for("chunks.diff", version_id=version_id))


@bp.get("/versions/<version_id>/download")
@login_required
def download(version_id: str):
    content, filename = workspace().download_version(version_id)
    return send_file(
        BytesIO(content),
        as_attachment=True,
        download_name=filename,
        mimetype="application/octet-stream",
        max_age=0,
    )


@bp.get("/versions/<version_id>/preview")
@login_required
def preview(version_id: str):
    version = workspace().get_version(version_id)
    chunk = workspace().get_chunk(version["chunk_id"])
    return render_template(
        "chunks/preview.html",
        chunk=chunk,
        version=version,
        preview_supported=Path(version["original_filename"]).suffix.lower() == ".hwpx",
    )


@bp.get("/versions/<version_id>/preview.svg")
@login_required
def preview_svg(version_id: str):
    version = workspace().get_version(version_id)
    if Path(version["original_filename"]).suffix.lower() != ".hwpx":
        raise ValidationError("브라우저 미리보기는 HWPX 형식만 지원합니다.")
    content, _filename = workspace().download_version(version_id)
    rendered = kordoc().render_hwpx_svg(content)
    response = Response(rendered["svg"], content_type="image/svg+xml; charset=utf-8")
    response.headers["Content-Disposition"] = 'inline; filename="preview.svg"'
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; img-src data:; style-src 'unsafe-inline'; sandbox"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "private, max-age=3600, immutable"
    return response


@bp.post("/<chunk_id>/force-unlock")
@login_required
def force_unlock(chunk_id: str):
    chunk = workspace().get_chunk(chunk_id)
    require_force_unlock(g.current_user, chunk)
    try:
        workspace().force_unlock(g.current_user, chunk_id, request.form.get("comment", ""))
    except ConflictError as exc:
        flash(str(exc), "warning")
    else:
        flash("잠금을 강제로 해제했습니다.", "success")
    return redirect(url_for("documents.detail", document_id=chunk["document_id"]))


def _editor_source(chunk_id: str) -> tuple[dict, dict]:
    if not current_app.config["RHWP_EDITOR_ENABLED"]:
        raise ValidationError("웹 편집 기능이 비활성화되어 있습니다.")
    chunk = workspace().get_chunk(chunk_id)
    require_edit(g.current_user, chunk)
    if chunk.get("locked_by") != g.current_user["id"]:
        raise ConflictError("먼저 편집 시작을 눌러 체크아웃해야 합니다.")
    document = workspace().get_document(chunk["document_id"])
    if document.get("status") == "confirmed":
        raise ConflictError("최종확정된 자료는 수정할 수 없습니다.")
    locked_version_no = chunk.get("locked_version_no")
    if not isinstance(locked_version_no, int) or locked_version_no <= 0:
        raise ValidationError("웹에서 편집할 기준 HWPX 버전이 없습니다.")
    version = next(
        (
            row
            for row in workspace().list_versions(chunk_id)
            if row["version_no"] == locked_version_no
        ),
        None,
    )
    if not version:
        raise ConflictError("체크아웃 기준 버전을 찾을 수 없습니다. 최신 버전으로 다시 시작하세요.")
    if Path(version["original_filename"]).suffix.lower() != ".hwpx":
        raise ValidationError("HWPX 문서만 브라우저에서 편집할 수 있습니다.")
    return chunk, version

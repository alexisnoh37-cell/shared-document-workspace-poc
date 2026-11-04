from __future__ import annotations

from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request, send_file

from config import BASE_DIR
from services.errors import ValidationError
from services.storage_service import validate_document_bytes

from .common import kordoc, login_required


bp = Blueprint("rhwp_spike", __name__, url_prefix="/dev/rhwp-spike")
SAMPLE_ROOT = BASE_DIR / "sample_files"


def _sample_path(filename: str) -> Path:
    candidate = SAMPLE_ROOT / Path(filename).name
    if candidate.suffix.lower() != ".hwpx" or not candidate.is_file():
        raise ValidationError("Spike 샘플 HWPX를 찾을 수 없습니다.")
    return candidate


@bp.get("")
@login_required
def index():
    samples = sorted(path.name for path in SAMPLE_ROOT.glob("*.hwpx"))
    return render_template(
        "dev/rhwp_spike.html",
        samples=samples,
        studio_url=current_app.config["RHWP_STUDIO_URL"],
    )


@bp.get("/source/<path:filename>")
@login_required
def source(filename: str):
    response = send_file(
        _sample_path(filename),
        mimetype="application/vnd.hancom.hwpx",
        as_attachment=False,
        max_age=0,
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@bp.post("/analyze")
@login_required
def analyze():
    filename = Path(request.form.get("sample", "")).name
    original_path = _sample_path(filename)
    exported = request.files.get("file")
    if exported is None:
        raise ValidationError("rhwp export 결과가 없습니다.")
    upload = validate_document_bytes(
        exported.read(),
        f"{original_path.stem}-rhwp-export.hwpx",
        expected_extension=".hwpx",
        max_bytes=current_app.config["MAX_CONTENT_LENGTH"],
    )
    parsed = kordoc().parse_bytes(upload.content, upload.extension)
    rendered = kordoc().render_hwpx_svg(upload.content)
    comparison = kordoc().compare_bytes(original_path.read_bytes(), upload.content)
    stats = (comparison.get("data") or {}).get("stats") or {}
    changed_diffs = [
        diff
        for diff in (comparison.get("data") or {}).get("diffs", [])
        if diff.get("type") != "unchanged"
    ]
    return jsonify(
        {
            "ok": True,
            "filename": upload.filename,
            "size": upload.size,
            "sha256": upload.sha256,
            "fileType": parsed["file_type"],
            "blockCount": len(parsed["blocks"]),
            "warningCount": len(parsed["warnings"]),
            "pageCount": rendered["page_count"],
            "compareStatus": comparison["status"],
            "compareStats": stats,
            "changedTypes": [diff.get("type") for diff in changed_diffs],
            "changedBlockTypes": [
                (diff.get("after") or diff.get("before") or {}).get("type")
                for diff in changed_diffs
            ],
            "noOp": comparison["status"] == "succeeded"
            and int(stats.get("added", 0)) == 0
            and int(stats.get("removed", 0)) == 0
            and int(stats.get("modified", 0)) == 0,
        }
    )

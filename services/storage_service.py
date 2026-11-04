from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

from werkzeug.datastructures import FileStorage

from .errors import ValidationError


HWP_OLE_SIGNATURE = bytes.fromhex("D0CF11E0A1B11AE1")
ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
ALLOWED_EXTENSIONS = {".hwp", ".hwpx"}
DEFAULT_MAX_DOCUMENT_BYTES = 25 * 1024 * 1024
MAX_HWPX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024


@dataclass(frozen=True)
class ValidatedUpload:
    filename: str
    extension: str
    content: bytes
    size: int
    sha256: str


def validate_document_bytes(
    content: bytes,
    filename: str,
    *,
    expected_extension: str | None = None,
    max_bytes: int = DEFAULT_MAX_DOCUMENT_BYTES,
) -> ValidatedUpload:
    safe_name = Path(filename).name
    extension = Path(safe_name).suffix.lower()
    if expected_extension and extension != expected_extension.lower():
        expected_label = expected_extension.lstrip(".").upper()
        raise ValidationError(f"{expected_label} 파일만 제출할 수 있습니다.")
    if extension not in ALLOWED_EXTENSIONS:
        raise ValidationError("HWP 또는 HWPX 파일만 제출할 수 있습니다.")
    if not content:
        raise ValidationError("빈 파일은 제출할 수 없습니다.")
    if len(content) > max_bytes:
        raise ValidationError("업로드 파일이 허용된 최대 크기를 초과했습니다.")

    if extension == ".hwp" and not content.startswith(HWP_OLE_SIGNATURE):
        raise ValidationError("파일 내용이 올바른 HWP 형식이 아닙니다.")
    if extension == ".hwpx":
        _validate_hwpx_zip(content)

    return ValidatedUpload(
        filename=safe_name,
        extension=extension,
        content=content,
        size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def validate_document_upload(
    upload: FileStorage | None,
    *,
    max_bytes: int = DEFAULT_MAX_DOCUMENT_BYTES,
) -> ValidatedUpload:
    if upload is None or not upload.filename:
        raise ValidationError("제출할 HWP 또는 HWPX 파일을 선택하세요.")
    content = upload.read()
    return validate_document_bytes(content, upload.filename, max_bytes=max_bytes)


def _validate_hwpx_zip(content: bytes) -> None:
    if not content.startswith(ZIP_SIGNATURES):
        raise ValidationError("파일 내용이 올바른 HWPX 형식이 아닙니다.")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if not entries or archive.testzip() is not None:
                raise ValidationError("HWPX 압축 파일이 손상되었습니다.")
            total_uncompressed = 0
            normalized_names = set()
            for entry in entries:
                path = Path(entry.filename.replace("\\", "/"))
                if path.is_absolute() or ".." in path.parts:
                    raise ValidationError("HWPX 내부 경로가 안전하지 않습니다.")
                if entry.flag_bits & 0x1:
                    raise ValidationError("암호화된 HWPX 파일은 제출할 수 없습니다.")
                total_uncompressed += entry.file_size
                if total_uncompressed > MAX_HWPX_UNCOMPRESSED_BYTES:
                    raise ValidationError("HWPX 압축 해제 크기가 허용 범위를 초과했습니다.")
                normalized_names.add(entry.filename.replace("\\", "/"))
            if "mimetype" not in normalized_names or "Contents/content.hpf" not in normalized_names:
                raise ValidationError("필수 구조가 없는 HWPX 파일입니다.")
    except zipfile.BadZipFile as exc:
        raise ValidationError("파일 내용이 올바른 HWPX ZIP 형식이 아닙니다.") from exc

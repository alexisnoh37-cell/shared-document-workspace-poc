from io import BytesIO
from pathlib import Path

import pytest
from werkzeug.datastructures import FileStorage

from services.errors import ValidationError
from services.storage_service import validate_document_bytes, validate_document_upload


def test_valid_hwpx_upload():
    root = Path(__file__).resolve().parents[1]
    content = (root / "sample_files" / "ii_1.hwpx").read_bytes()
    upload = validate_document_upload(FileStorage(stream=BytesIO(content), filename="수정본.hwpx"))
    assert upload.extension == ".hwpx"
    assert upload.size == len(content)
    assert len(upload.sha256) == 64


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("malware.exe", b"MZ"),
        ("fake.hwpx", b"not-a-zip"),
        ("fake.hwp", b"not-an-ole-file"),
    ],
)
def test_invalid_upload_is_rejected(filename, content):
    with pytest.raises(ValidationError):
        validate_document_upload(FileStorage(stream=BytesIO(content), filename=filename))


def test_document_bytes_enforce_server_extension_and_size():
    root = Path(__file__).resolve().parents[1]
    content = (root / "sample_files" / "ii_1.hwpx").read_bytes()
    with pytest.raises(ValidationError, match="HWPX"):
        validate_document_bytes(content, "wrong.hwp", expected_extension=".hwpx")
    with pytest.raises(ValidationError, match="최대 크기"):
        validate_document_bytes(content, "valid.hwpx", max_bytes=10)


def test_hwp_disguised_as_hwpx_is_rejected():
    with pytest.raises(ValidationError, match="HWPX"):
        validate_document_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"fake", "fake.hwpx")

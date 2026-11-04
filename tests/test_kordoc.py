from pathlib import Path

from services.kordoc_service import KordocService


def test_real_kordoc_hwpx_compare():
    root = Path(__file__).resolve().parents[1]
    service = KordocService(root, timeout_seconds=30)
    old_content = (root / "sample_files" / "i_1.hwpx").read_bytes()
    new_content = (root / "sample_files" / "i_2.hwpx").read_bytes()
    result = service.compare_bytes(old_content, new_content)
    assert result["status"] == "succeeded"
    assert result["data"]["stats"]["modified"] >= 1
    assert result["data"]["diffs"]


def test_kordoc_failure_does_not_raise():
    root = Path(__file__).resolve().parents[1]
    service = KordocService(root, node_bin="missing-node-binary", timeout_seconds=1)
    result = service.compare_bytes(b"old", b"new")
    assert result["status"] == "failed"
    assert result["summary"] == "문서 비교 처리 실패"


def test_real_kordoc_hwpx_render():
    root = Path(__file__).resolve().parents[1]
    service = KordocService(root, timeout_seconds=30)
    rendered = service.render_hwpx_svg((root / "sample_files" / "i_1.hwpx").read_bytes())
    assert "<svg" in rendered["svg"][:1000]
    assert rendered["page_count"] >= 1
    assert rendered["stats"]["texts"] >= 1


def test_real_kordoc_hwpx_parse():
    root = Path(__file__).resolve().parents[1]
    service = KordocService(root, timeout_seconds=30)
    parsed = service.parse_bytes((root / "sample_files" / "i_1.hwpx").read_bytes())
    assert parsed["file_type"] == "hwpx"
    assert parsed["blocks"]

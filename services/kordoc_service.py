from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from .errors import IntegrationError


class KordocService:
    def __init__(self, project_root: Path, node_bin: str = "node", timeout_seconds: int = 60):
        self.worker = project_root / "kordoc_worker" / "worker.mjs"
        self.node_bin = node_bin
        self.timeout_seconds = timeout_seconds

    def compare_bytes(
        self,
        old_content: bytes | None,
        new_content: bytes,
        old_extension: str = ".hwpx",
        new_extension: str = ".hwpx",
    ) -> dict:
        if not old_content:
            return {
                "status": "not_applicable",
                "summary": "최초 버전으로 비교 대상이 없습니다.",
                "data": {"stats": {"added": 0, "removed": 0, "modified": 0, "unchanged": 0}},
                "error": None,
            }

        try:
            with tempfile.TemporaryDirectory(prefix="workspace-kordoc-") as tmp:
                tmp_path = Path(tmp)
                old_path = tmp_path / f"old{old_extension}"
                new_path = tmp_path / f"new{new_extension}"
                old_path.write_bytes(old_content)
                new_path.write_bytes(new_content)
                completed = subprocess.run(
                    [self.node_bin, str(self.worker), "compare", str(old_path), str(new_path)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout_seconds,
                    check=False,
                )
            if completed.returncode != 0:
                message = (completed.stderr or completed.stdout or "kordoc 실행 실패").strip()
                return self._failure(message)

            payload = json.loads(completed.stdout)
            if not payload.get("success"):
                return self._failure(str(payload.get("error") or "문서 비교 처리 실패"))

            stats = payload.get("stats") or {}
            summary = (
                f"추가 {int(stats.get('added', 0))}건 · "
                f"삭제 {int(stats.get('removed', 0))}건 · "
                f"수정 {int(stats.get('modified', 0))}건"
            )
            return {
                "status": "succeeded",
                "summary": summary,
                "data": {"stats": stats, "diffs": payload.get("diffs") or []},
                "error": None,
            }
        except subprocess.TimeoutExpired:
            return self._failure(f"kordoc 처리 시간이 {self.timeout_seconds}초를 초과했습니다.")
        except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
            return self._failure(str(exc))

    def parse_bytes(self, content: bytes, extension: str = ".hwpx") -> dict:
        try:
            with tempfile.TemporaryDirectory(prefix="workspace-kordoc-parse-") as tmp:
                source = Path(tmp) / f"document{extension}"
                source.write_bytes(content)
                completed = subprocess.run(
                    [self.node_bin, str(self.worker), "parse", str(source)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout_seconds,
                    check=False,
                )
            if completed.returncode != 0:
                message = (completed.stderr or completed.stdout or "kordoc 파싱 실패").strip()
                raise IntegrationError(message[:1000])
            payload = json.loads(completed.stdout)
            if not payload.get("success"):
                raise IntegrationError(str(payload.get("error") or "문서 파싱 실패")[:1000])
            return {
                "file_type": payload.get("fileType"),
                "markdown": payload.get("markdown") or "",
                "blocks": payload.get("blocks") or [],
                "warnings": payload.get("warnings") or [],
            }
        except subprocess.TimeoutExpired as exc:
            raise IntegrationError(
                f"kordoc 문서 검증 시간이 {self.timeout_seconds}초를 초과했습니다."
            ) from exc
        except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
            raise IntegrationError(f"kordoc 문서 검증 실패: {exc}") from exc

    def render_hwpx_svg(self, content: bytes) -> dict:
        try:
            with tempfile.TemporaryDirectory(prefix="workspace-kordoc-preview-") as tmp:
                source = Path(tmp) / "preview.hwpx"
                source.write_bytes(content)
                completed = subprocess.run(
                    [self.node_bin, str(self.worker), "render", str(source)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout_seconds,
                    check=False,
                )
            if completed.returncode != 0:
                message = (completed.stderr or completed.stdout or "kordoc 렌더 실패").strip()
                raise IntegrationError(message[:1000])

            payload = json.loads(completed.stdout)
            svg = str(payload.get("svg") or "")
            if not payload.get("success") or "<svg" not in svg[:1000]:
                raise IntegrationError("kordoc이 올바른 SVG 미리보기를 만들지 못했습니다.")
            if len(svg.encode("utf-8")) > 30 * 1024 * 1024:
                raise IntegrationError("미리보기 결과가 허용 크기를 초과했습니다.")
            return {
                "svg": svg,
                "width": payload.get("width"),
                "height": payload.get("height"),
                "page_count": int(payload.get("pageCount") or 1),
                "stats": payload.get("stats") or {},
                "warnings": payload.get("warnings") or [],
            }
        except subprocess.TimeoutExpired as exc:
            raise IntegrationError(
                f"kordoc 미리보기 생성 시간이 {self.timeout_seconds}초를 초과했습니다."
            ) from exc
        except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
            raise IntegrationError(f"kordoc 미리보기 생성 실패: {exc}") from exc

    @staticmethod
    def _failure(message: str) -> dict:
        return {
            "status": "failed",
            "summary": "문서 비교 처리 실패",
            "data": None,
            "error": message[:1000],
        }

import { createEditor } from "/static/vendor/rhwp-editor/index.js";

const root = document.querySelector("#rhwp-spike");
if (root) {
  const sample = document.querySelector("#spike-sample");
  const loadButton = document.querySelector("#spike-load");
  const noOpButton = document.querySelector("#spike-noop");
  const downloadButton = document.querySelector("#spike-download");
  const status = document.querySelector("#spike-status");
  const result = document.querySelector("#spike-result");
  let editor;
  let exportedBytes;

  const setStatus = (message, error = false) => {
    status.textContent = message;
    status.className = error ? "mt-3 text-danger" : "mt-3 text-secondary";
  };

  const sourceUrl = () => root.dataset.sourceTemplate.replace("__SAMPLE__", encodeURIComponent(sample.value));

  const loadSample = async () => {
    loadButton.disabled = true;
    noOpButton.disabled = true;
    downloadButton.disabled = true;
    result.classList.add("d-none");
    setStatus(`${sample.value} 다운로드 중…`);
    try {
      const response = await fetch(sourceUrl(), { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error(`샘플 다운로드 실패 (${response.status})`);
      const buffer = await response.arrayBuffer();
      const loaded = await editor.loadFile(buffer, sample.value, {
        skipUnsavedGuard: true,
        suppressDialogs: true,
      });
      exportedBytes = undefined;
      noOpButton.disabled = false;
      setStatus(`${loaded.pageCount}페이지를 로드했습니다. 수정하거나 no-op 검증을 실행하세요.`);
    } catch (error) {
      setStatus(error.message || String(error), true);
    } finally {
      loadButton.disabled = false;
    }
  };

  const exportAndAnalyze = async () => {
    noOpButton.disabled = true;
    downloadButton.disabled = true;
    setStatus("HWPX export 및 Kordoc 검증 중…");
    try {
      exportedBytes = await editor.exportHwpx();
      const form = new FormData();
      form.append("csrf_token", document.querySelector('meta[name="csrf-token"]').content);
      form.append("sample", sample.value);
      form.append("file", new Blob([exportedBytes], { type: "application/vnd.hancom.hwpx" }), "export.hwpx");
      const response = await fetch(root.dataset.analyzeUrl, {
        method: "POST",
        body: form,
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(await response.text() || `검증 실패 (${response.status})`);
      const payload = await response.json();
      result.textContent = JSON.stringify(payload, null, 2);
      result.classList.remove("d-none");
      downloadButton.disabled = false;
      setStatus(payload.noOp ? "no-op round-trip 통과" : "no-op round-trip에서 변경이 감지되었습니다.", !payload.noOp);
    } catch (error) {
      setStatus(error.message || String(error), true);
    } finally {
      noOpButton.disabled = false;
    }
  };

  const downloadExport = () => {
    if (!exportedBytes) return;
    const url = URL.createObjectURL(new Blob([exportedBytes], { type: "application/vnd.hancom.hwpx" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${sample.value.replace(/\.hwpx$/i, "")}-rhwp-export.hwpx`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  loadButton.addEventListener("click", loadSample);
  noOpButton.addEventListener("click", exportAndAnalyze);
  downloadButton.addEventListener("click", downloadExport);

  try {
    editor = await createEditor("#rhwp-editor-container", {
      studioUrl: root.dataset.studioUrl,
      width: "100%",
      height: "100%",
      renderer: "canvas2d",
      requestTimeoutMs: 120000,
    });
    setStatus("편집기를 불러왔습니다. 샘플을 선택하세요.");
  } catch (error) {
    setStatus(`웹 편집기를 불러오지 못했습니다: ${error.message || error}`, true);
  }

  window.addEventListener("pagehide", () => editor?.destroy(), { once: true });
}

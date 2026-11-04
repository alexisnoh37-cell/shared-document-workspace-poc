import { createEditor } from "/static/vendor/rhwp-editor/index.js";

const root = document.querySelector("#rhwp-workflow-editor");
if (root) {
  const form = document.querySelector("#rhwp-save-form");
  const saveButton = document.querySelector("#rhwp-save-button");
  const reasonInput = document.querySelector("#change_reason");
  const statusBox = document.querySelector("#rhwp-editor-status");
  const errorBox = document.querySelector("#rhwp-editor-error");
  const errorMessage = document.querySelector("#rhwp-editor-error-message");
  let editor;
  let ready = false;
  let saving = false;

  const setStatus = (message, busy = false) => {
    statusBox.classList.remove("d-none");
    statusBox.replaceChildren();
    if (busy) {
      const spinner = document.createElement("span");
      spinner.className = "spinner-border spinner-border-sm";
      spinner.setAttribute("aria-hidden", "true");
      statusBox.append(spinner);
    }
    const label = document.createElement("span");
    label.textContent = message;
    statusBox.append(label);
  };

  const hideStatus = () => statusBox.classList.add("d-none");

  const showError = (message) => {
    errorMessage.textContent = message;
    errorBox.classList.remove("d-none");
  };

  const responsePayload = async (response) => {
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) return response.json();
    if (response.redirected && response.url.includes("/auth/login")) {
      return { ok: false, error: "로그인 세션이 만료되었습니다. 다시 로그인하세요." };
    }
    return { ok: false, error: `서버 요청 처리에 실패했습니다. (${response.status})` };
  };

  const initialize = async () => {
    try {
      editor = await createEditor("#rhwp-editor-container", {
        studioUrl: root.dataset.studioUrl,
        width: "100%",
        height: "100%",
        renderer: "canvas2d",
        requestTimeoutMs: 120000,
      });
      const source = await fetch(root.dataset.sourceUrl, {
        credentials: "same-origin",
        cache: "no-store",
        headers: { Accept: "application/vnd.hancom.hwpx" },
      });
      if (!source.ok) throw new Error(`편집 기준 파일을 내려받지 못했습니다. (${source.status})`);
      const loaded = await editor.loadFile(await source.arrayBuffer(), root.dataset.filename, {
        skipUnsavedGuard: true,
        suppressDialogs: true,
      });
      ready = true;
      saveButton.disabled = false;
      setStatus(`${loaded.pageCount}페이지를 불러왔습니다.`);
      window.setTimeout(hideStatus, 1800);
    } catch (error) {
      showError(error.message || String(error));
      hideStatus();
      saveButton.disabled = true;
    }
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!ready || saving) return;
    if (!reasonInput.value.trim()) {
      reasonInput.focus();
      reasonInput.reportValidity();
      return;
    }

    saving = true;
    saveButton.disabled = true;
    errorBox.classList.add("d-none");
    setStatus("HWPX를 내보내고 서버에서 검증·제출하는 중입니다…", true);
    try {
      const bytes = await editor.exportHwpx();
      const data = new FormData();
      data.append("csrf_token", form.elements.csrf_token.value);
      data.append("change_reason", reasonInput.value.trim());
      data.append(
        "file",
        new Blob([bytes], { type: "application/vnd.hancom.hwpx" }),
        "rhwp-export.hwpx",
      );
      const response = await fetch(root.dataset.saveUrl, {
        method: "POST",
        body: data,
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      });
      const payload = await responsePayload(response);
      if (!response.ok || !payload.ok) throw new Error(payload.error || "웹 편집본 저장에 실패했습니다.");

      setStatus(`v${payload.versionNo} 저장을 완료했습니다. 변경 내용을 여는 중입니다…`, true);
      try {
        await editor.notifySaved(payload.filename);
      } catch (error) {
        console.warn("rhwp 저장 완료 통지를 지원하지 않습니다.", error);
      }
      window.location.assign(payload.redirectUrl);
    } catch (error) {
      showError(error.message || String(error));
      hideStatus();
      saving = false;
      saveButton.disabled = !ready;
    }
  });

  window.addEventListener("pagehide", () => editor?.destroy(), { once: true });
  initialize();
}

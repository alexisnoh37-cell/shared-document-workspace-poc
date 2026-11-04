(() => {
  const root = document.getElementById("collab-presence");
  if (!root) return;

  const url = root.dataset.locksUrl;
  const intervalMs = (Number(root.dataset.pollSeconds) || 3) * 1000;

  const apply = (chunks) => {
    for (const chunk of chunks) {
      const row = document.querySelector(`[data-chunk-id="${chunk.id}"]`);
      if (!row) continue;

      const lockedByOther = chunk.locked && !chunk.is_mine;
      row.classList.toggle("chunk-editing", chunk.locked);

      const note = row.querySelector("[data-lock-note]");
      if (note) {
        if (chunk.locked) {
          note.textContent = chunk.is_mine
            ? "🔒 내가 수정 중"
            : `🔒 ${chunk.locked_by_name}님 수정 중`;
          note.hidden = false;
        } else {
          note.textContent = "";
          note.hidden = true;
        }
      }

      const startButton = row.querySelector("[data-edit-start] button");
      if (startButton) {
        if (lockedByOther) startButton.dataset.lockedByOther = "1";
        else delete startButton.dataset.lockedByOther;
      }
    }
  };

  let timerId = null;

  const stop = () => {
    if (timerId !== null) window.clearInterval(timerId);
    timerId = null;
  };

  const poll = async () => {
    try {
      const response = await fetch(url, { credentials: "same-origin", cache: "no-store" });
      const contentType = response.headers.get("content-type") || "";
      if (response.redirected || !contentType.includes("application/json")) {
        // session most likely expired: stop polling a login form and reload
        stop();
        window.location.reload();
        return;
      }
      if (!response.ok) return;
      const data = await response.json();
      apply(data.chunks || []);
    } catch (_error) {
      /* transient network error: keep polling */
    }
  };

  document.addEventListener(
    "submit",
    (event) => {
      const form = event.target;
      if (!form.matches("[data-edit-start]")) return;
      if (form.querySelector("button[data-locked-by-other]")) {
        event.preventDefault();
        event.stopImmediatePropagation();
        window.alert("이미 수정중인 내용입니다.");
      }
    },
    true,
  );

  poll();
  timerId = window.setInterval(poll, intervalMs);
})();

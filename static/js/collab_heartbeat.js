(() => {
  const el = document.querySelector("[data-heartbeat-url]");
  if (!el) return;

  const url = el.dataset.heartbeatUrl;
  if (!url) return;

  // Deliberately slow: the lock only needs a touch well inside the idle
  // auto-release window, not at the screen poll cadence.
  const intervalMs = (Number(el.dataset.heartbeatSeconds) || 60) * 1000;
  // If the tab is left open but untouched for this long, treat the user as away
  // and let the idle sweeper reclaim the lock.
  const awayMs = 3 * 60 * 1000;
  const token = document.querySelector('meta[name="csrf-token"]')?.content;

  let lastActivity = Date.now();
  const markActive = () => {
    lastActivity = Date.now();
  };
  for (const evt of ["pointermove", "pointerdown", "keydown", "focus"]) {
    window.addEventListener(evt, markActive, { passive: true });
  }

  const ping = () => {
    if (document.visibilityState !== "visible") return;
    if (Date.now() - lastActivity > awayMs) return;
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: token ? { "X-CSRFToken": token } : {},
    }).catch(() => {});
  };

  const timerId = window.setInterval(ping, intervalMs);

  const stop = () => window.clearInterval(timerId);
  window.addEventListener("pagehide", stop, { once: true });
  window.addEventListener("beforeunload", stop, { once: true });
})();

(() => {
  const SOURCE = "qwenpaw-browser-bridge-content";
  const HOST_ID = "qwenpaw-browser-bridge-host";

  const state = {
    visible: false,
    statusText: "操控中",
  };

  let host = null;
  let shadowRoot = null;
  let banner = null;
  let status = null;
  let cursor = null;
  let cursorPosition = { x: 24, y: 24 };

  function ensureBanner() {
    if (shadowRoot) {
      return;
    }

    host = document.getElementById(HOST_ID);
    if (!host) {
      host = document.createElement("div");
      host.id = HOST_ID;
      document.documentElement.appendChild(host);
    }

    shadowRoot = host.attachShadow({ mode: "open" });

    const style = document.createElement("style");
    style.textContent = `
      :host {
        all: initial;
      }

      .qwenpaw-banner {
        position: fixed;
        z-index: 2147483647;
        top: 12px;
        left: 50%;
        transform: translateX(-50%);
        display: none;
        align-items: center;
        gap: 10px;
        min-height: 34px;
        max-width: min(720px, calc(100vw - 24px));
        padding: 8px 10px;
        border: 1px solid rgba(20, 24, 36, 0.14);
        border-radius: 8px;
        background: rgba(255, 255, 255, 0.96);
        color: #172033;
        box-shadow: 0 8px 24px rgba(15, 23, 42, 0.18);
        font: 13px/1.35 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }

      .qwenpaw-banner[data-visible="true"] {
        display: flex;
      }

      .qwenpaw-status {
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }

      .qwenpaw-actions {
        display: flex;
        gap: 6px;
        flex: 0 0 auto;
      }

      button {
        appearance: none;
        border: 1px solid rgba(20, 24, 36, 0.18);
        border-radius: 6px;
        background: #f8fafc;
        color: #172033;
        cursor: pointer;
        font: inherit;
        padding: 4px 8px;
      }

      button:hover {
        background: #eef2f7;
      }

      .qwenpaw-cursor {
        position: fixed;
        z-index: 2147483647;
        left: 0;
        top: 0;
        width: 18px;
        height: 18px;
        border: 2px solid #0f766e;
        border-radius: 999px;
        background: rgba(45, 212, 191, 0.16);
        box-shadow: 0 0 0 4px rgba(45, 212, 191, 0.14);
        pointer-events: none;
        transform: translate3d(24px, 24px, 0);
        opacity: 0;
      }

      .qwenpaw-cursor[data-visible="true"] {
        opacity: 1;
      }

      .qwenpaw-cursor[data-flash="true"] {
        animation: qwenpaw-click-flash 260ms ease-out;
      }

      @keyframes qwenpaw-click-flash {
        0% {
          box-shadow: 0 0 0 4px rgba(45, 212, 191, 0.2);
          transform: translate3d(var(--x), var(--y), 0) scale(1);
        }
        50% {
          box-shadow: 0 0 0 12px rgba(45, 212, 191, 0.08);
          transform: translate3d(var(--x), var(--y), 0) scale(1.35);
        }
        100% {
          box-shadow: 0 0 0 4px rgba(45, 212, 191, 0.14);
          transform: translate3d(var(--x), var(--y), 0) scale(1);
        }
      }
    `;

    banner = document.createElement("div");
    banner.className = "qwenpaw-banner";

    status = document.createElement("div");
    status.className = "qwenpaw-status";

    const actions = document.createElement("div");
    actions.className = "qwenpaw-actions";

    const pause = document.createElement("button");
    pause.type = "button";
    pause.textContent = "⏸ 暂停";
    pause.addEventListener("click", () => emit("hitl.paused", {}));

    const stop = document.createElement("button");
    stop.type = "button";
    stop.textContent = "■ 停止";
    stop.addEventListener("click", () => emit("hitl.stopped", {}));

    actions.append(pause, stop);
    cursor = document.createElement("div");
    cursor.className = "qwenpaw-cursor";
    banner.append(status, actions);
    shadowRoot.append(style, banner, cursor);
    render();
  }

  function render() {
    if (!banner || !status) {
      return;
    }
    banner.dataset.visible = state.visible ? "true" : "false";
    status.textContent = `🐾 QwenPaw · 操控中 · "${state.statusText}"`;
  }

  function emit(method, params) {
    chrome.runtime.sendMessage(
      {
        source: SOURCE,
        method,
        params: params || {},
      },
      () => {
        void chrome.runtime.lastError;
      },
    );
  }

  function bezier(start, control, end, t) {
    const oneMinusT = 1 - t;
    return {
      x: oneMinusT * oneMinusT * start.x + 2 * oneMinusT * t * control.x + t * t * end.x,
      y: oneMinusT * oneMinusT * start.y + 2 * oneMinusT * t * control.y + t * t * end.y,
    };
  }

  function setCursorPosition(point) {
    if (!cursor) {
      return;
    }
    cursorPosition = { x: point.x, y: point.y };
    const x = `${point.x}px`;
    const y = `${point.y}px`;
    cursor.style.setProperty("--x", x);
    cursor.style.setProperty("--y", y);
    cursor.style.transform = `translate3d(${x}, ${y}, 0)`;
  }

  function flashCursor() {
    if (!cursor) {
      return;
    }
    cursor.dataset.flash = "false";
    void cursor.offsetWidth;
    cursor.dataset.flash = "true";
    window.setTimeout(() => {
      if (cursor) {
        cursor.dataset.flash = "false";
      }
    }, 280);
  }

  function animateCursor(target) {
    ensureBanner();
    if (!target || typeof target.x !== "number" || typeof target.y !== "number") {
      return Promise.resolve({ ok: true, animationDone: false });
    }

    const start = { ...cursorPosition };
    const end = { x: target.x, y: target.y };
    const control = {
      x: (start.x + end.x) / 2,
      y: Math.min(start.y, end.y) - Math.max(48, Math.abs(end.x - start.x) * 0.18),
    };
    const duration = Math.max(180, Math.min(650, Math.hypot(end.x - start.x, end.y - start.y) * 1.2));
    const started = performance.now();

    cursor.dataset.visible = "true";

    return new Promise((resolve) => {
      function step(now) {
        const t = Math.min(1, (now - started) / duration);
        const eased = 1 - Math.pow(1 - t, 3);
        setCursorPosition(bezier(start, control, end, eased));
        if (t < 1) {
          requestAnimationFrame(step);
          return;
        }

        setCursorPosition(end);
        flashCursor();
        emit("banner.animationDone", { cursor: end });
        resolve({ ok: true, animationDone: true });
      }

      requestAnimationFrame(step);
    });
  }

  async function show(params) {
    ensureBanner();
    state.visible = true;
    if (Object.prototype.hasOwnProperty.call(params, "status_text")) {
      state.statusText = params.status_text || "操控中";
    }
    render();
    const animation = await animateCursor(params.cursor);
    return { ok: true, visible: true, ...animation };
  }

  function hide() {
    ensureBanner();
    state.visible = false;
    render();
    return { ok: true, visible: false };
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || message.source !== "qwenpaw-browser-bridge") {
      return false;
    }

    const params = message.params || {};
    if (message.method === "banner.show") {
      show(params).then(sendResponse);
      return true;
    }
    if (message.method === "banner.hide") {
      sendResponse(hide());
      return false;
    }

    sendResponse({ ok: false, error: `Unknown method: ${message.method}` });
    return false;
  });
})();

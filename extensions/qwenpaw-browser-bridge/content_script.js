(() => {
  const CONTENT_LOADED_FLAG = "__qwenpawBrowserBridgeContentLoaded";
  if (window[CONTENT_LOADED_FLAG]) {
    return;
  }
  window[CONTENT_LOADED_FLAG] = true;

  const SOURCE = "qwenpaw-browser-bridge-content";
  const HOST_ID = "qwenpaw-browser-bridge-host";

  const state = {
    visible: false,
    phase: "thinking",
    statusText: "正在思考...",
  };

  let host = null;
  let shadowRoot = null;
  let banner = null;
  let pulseDot = null;
  let status = null;
  let cursor = null;
  let keyboard = null;
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

      .qwenpaw-pulse-dot {
        width: 9px;
        height: 9px;
        border-radius: 999px;
        flex: 0 0 auto;
      }

      .qwenpaw-pulse-dot[data-phase="thinking"] {
        background: #16a34a;
        animation: qwenpaw-pulse-thinking 1.6s ease-in-out infinite;
      }

      .qwenpaw-pulse-dot[data-phase="acting"] {
        background: #f59e0b;
        animation: qwenpaw-pulse-acting 0.6s ease-in-out infinite;
      }

      .qwenpaw-cursor {
        position: fixed;
        z-index: 2147483647;
        left: 0;
        top: 0;
        width: 28px;
        height: 28px;
        pointer-events: none;
        transform: translate3d(24px, 24px, 0);
        opacity: 0;
        filter: drop-shadow(0 8px 14px rgba(15, 23, 42, 0.24));
      }

      .qwenpaw-cursor[data-visible="true"] {
        opacity: 1;
      }

      .qwenpaw-cursor svg {
        display: block;
        width: 28px;
        height: 28px;
      }

      .qwenpaw-cursor[data-flash="true"] {
        animation: qwenpaw-click-flash 260ms ease-out;
      }

      .qwenpaw-keyboard {
        position: fixed;
        z-index: 2147483647;
        left: 0;
        top: 0;
        max-width: min(360px, calc(100vw - 32px));
        padding: 7px 10px;
        border: 1px solid rgba(20, 24, 36, 0.16);
        border-radius: 8px;
        background: rgba(15, 23, 42, 0.92);
        color: #ffffff;
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.24);
        font: 13px/1.35 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        pointer-events: none;
        opacity: 0;
        transform: translate3d(36px, 56px, 0);
        transition: opacity 140ms ease-out, transform 140ms ease-out;
      }

      .qwenpaw-keyboard[data-visible="true"] {
        opacity: 1;
        transform: translate3d(var(--x), var(--y), 0);
      }

      @keyframes qwenpaw-click-flash {
        0% {
          transform: translate3d(var(--x), var(--y), 0) scale(1);
        }
        50% {
          transform: translate3d(var(--x), var(--y), 0) scale(1.18);
        }
        100% {
          transform: translate3d(var(--x), var(--y), 0) scale(1);
        }
      }

      @keyframes qwenpaw-pulse-thinking {
        0%,
        100% {
          box-shadow: 0 0 0 0 rgba(22, 163, 74, 0.34);
          opacity: 0.72;
        }
        50% {
          box-shadow: 0 0 0 7px rgba(22, 163, 74, 0);
          opacity: 1;
        }
      }

      @keyframes qwenpaw-pulse-acting {
        0%,
        100% {
          box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.38);
          opacity: 0.8;
        }
        50% {
          box-shadow: 0 0 0 8px rgba(245, 158, 11, 0);
          opacity: 1;
        }
      }
    `;

    banner = document.createElement("div");
    banner.className = "qwenpaw-banner";

    pulseDot = document.createElement("div");
    pulseDot.className = "qwenpaw-pulse-dot";

    status = document.createElement("div");
    status.className = "qwenpaw-status";

    cursor = document.createElement("div");
    cursor.className = "qwenpaw-cursor";
    cursor.innerHTML = `
      <svg viewBox="0 0 32 32" aria-hidden="true" focusable="false">
        <path
          d="M12.4 16.3c1.1-1.3 2.1-2.2 3.6-2.2s2.6.9 3.7 2.2c.6.8 1.3 1.4 2.2 1.9 2.2 1.2 2.3 4.2.2 5.5-1.7 1.1-3.8.3-5.2-.5-.6-.3-1.2-.3-1.8 0-1.4.8-3.5 1.6-5.2.5-2.1-1.3-2-4.3.2-5.5.9-.5 1.6-1.1 2.3-1.9Z"
          fill="#ffffff"
          stroke="#0f766e"
          stroke-width="1.7"
        />
        <circle cx="9.7" cy="11.2" r="3" fill="#14b8a6" stroke="#ffffff" stroke-width="1.2" />
        <circle cx="15" cy="8.7" r="3" fill="#0f766e" stroke="#ffffff" stroke-width="1.2" />
        <circle cx="20.8" cy="10.1" r="3" fill="#14b8a6" stroke="#ffffff" stroke-width="1.2" />
        <circle cx="24.1" cy="15" r="2.7" fill="#0f766e" stroke="#ffffff" stroke-width="1.2" />
      </svg>
    `;
    keyboard = document.createElement("div");
    keyboard.className = "qwenpaw-keyboard";
    banner.append(pulseDot, status);
    shadowRoot.append(style, banner, cursor, keyboard);
    render();
  }

  function render() {
    if (!banner || !status) {
      return;
    }
    banner.dataset.visible = state.visible ? "true" : "false";
    if (pulseDot) {
      pulseDot.dataset.phase = state.phase;
    }
    status.textContent = `QwenPaw · ${state.statusText}`;
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
      x:
        oneMinusT * oneMinusT * start.x +
        2 * oneMinusT * t * control.x +
        t * t * end.x,
      y:
        oneMinusT * oneMinusT * start.y +
        2 * oneMinusT * t * control.y +
        t * t * end.y,
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

  function keyboardLabel(input) {
    if (!input || typeof input !== "object") {
      return "";
    }
    if (input.key) {
      return `按键 ${String(input.key).slice(0, 32)}`;
    }
    if (input.text) {
      const value = String(input.text).replace(/\s+/g, " ").trim();
      return `输入 ${value.slice(0, 72)}`;
    }
    return "";
  }

  function showKeyboard(input) {
    ensureBanner();
    if (!keyboard) {
      return;
    }
    const label = keyboardLabel(input);
    if (!label) {
      return;
    }
    const x = `${Math.min(window.innerWidth - 24, cursorPosition.x + 34)}px`;
    const y = `${Math.min(window.innerHeight - 24, cursorPosition.y + 34)}px`;
    keyboard.textContent = label;
    keyboard.style.setProperty("--x", x);
    keyboard.style.setProperty("--y", y);
    keyboard.dataset.visible = "true";
    window.clearTimeout(keyboard._hideTimer);
    keyboard._hideTimer = window.setTimeout(() => {
      if (keyboard) {
        keyboard.dataset.visible = "false";
      }
    }, 1200);
  }

  function animateCursor(target) {
    ensureBanner();
    if (
      !target ||
      typeof target.x !== "number" ||
      typeof target.y !== "number"
    ) {
      return Promise.resolve({ ok: true, animationDone: false });
    }

    const start = { ...cursorPosition };
    const end = { x: target.x, y: target.y };
    const control = {
      x: (start.x + end.x) / 2,
      y:
        Math.min(start.y, end.y) -
        Math.max(48, Math.abs(end.x - start.x) * 0.18),
    };
    const duration = Math.max(
      180,
      Math.min(650, Math.hypot(end.x - start.x, end.y - start.y) * 1.2),
    );
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
      state.statusText = params.status_text || "正在思考...";
    }
    if (Object.prototype.hasOwnProperty.call(params, "phase")) {
      state.phase = params.phase === "acting" ? "acting" : "thinking";
    }
    render();
    const animation = await animateCursor(params.cursor);
    showKeyboard(params.keyboard);
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

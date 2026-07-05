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
    statusText: "QwenPaw",
  };

  let host = null;
  let shadowRoot = null;
  let banner = null;
  let logo = null;
  let divider = null;
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
        gap: 0;
        height: 34px;
        width: 200px;
        padding: 0 12px 0 9px;
        border: 1.5px solid rgba(13, 148, 136, 0.35);
        border-radius: 17px;
        background: #ffffff;
        color: #1a1a1a;
        box-shadow:
          0 2px 8px rgba(13, 148, 136, 0.08),
          0 8px 24px rgba(0, 0, 0, 0.1),
          0 16px 48px rgba(0, 0, 0, 0.06);
        font: 12px/1 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        opacity: 0;
        transition: opacity 200ms ease-out;
      }

      .qwenpaw-banner[data-visible="true"] {
        display: flex;
        opacity: 1;
      }

      .qwenpaw-logo {
        width: 18px;
        height: 18px;
        flex: 0 0 auto;
        margin-right: 6px;
      }

      .qwenpaw-divider {
        width: 1px;
        height: 14px;
        background: rgba(0, 0, 0, 0.1);
        flex: 0 0 auto;
        margin: 0 10px;
      }

      .qwenpaw-status {
        min-width: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        color: #374151;
        font-weight: 450;
        letter-spacing: -0.01em;
      }

      .qwenpaw-pulse-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        flex: 0 0 auto;
        margin-right: 8px;
      }

      .qwenpaw-pulse-dot[data-phase="thinking"] {
        background: #10b981;
        animation: qwenpaw-pulse-thinking 1.6s ease-in-out infinite;
      }

      .qwenpaw-pulse-dot[data-phase="acting"] {
        background: #f59e0b;
        animation: qwenpaw-pulse-acting 0.7s ease-in-out infinite;
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
        0%, 100% { opacity: 0.5; transform: scale(0.85); }
        50% { opacity: 1; transform: scale(1.15); }
      }

      @keyframes qwenpaw-pulse-acting {
        0%, 100% { opacity: 0.7; transform: scale(0.9); }
        50% { opacity: 1; transform: scale(1.25); }
      }
    `;

    banner = document.createElement("div");
    banner.className = "qwenpaw-banner";

    logo = document.createElement("div");
    logo.className = "qwenpaw-logo";
    logo.innerHTML = `
      <svg viewBox="0 0 32 32" fill="none" aria-hidden="true">
        <circle cx="16" cy="16" r="14" fill="rgba(13,148,136,0.08)" stroke="rgba(13,148,136,0.2)" stroke-width="1.2"/>
        <path d="M12.4 17.3c1.1-1.3 2.1-2.2 3.6-2.2s2.6.9 3.7 2.2c.6.8 1.3 1.4 2.2 1.9 2.2 1.2 2.3 4.2.2 5.5-1.7 1.1-3.8.3-5.2-.5-.6-.3-1.2-.3-1.8 0-1.4.8-3.5 1.6-5.2.5-2.1-1.3-2-4.3.2-5.5.9-.5 1.6-1.1 2.3-1.9Z" fill="#0f766e" opacity="0.9"/>
        <circle cx="9.8" cy="12" r="2.2" fill="#14b8a6"/>
        <circle cx="14.6" cy="9.8" r="2.2" fill="#0f766e"/>
        <circle cx="19.8" cy="11" r="2.2" fill="#14b8a6"/>
        <circle cx="22.8" cy="14.8" r="2" fill="#0f766e"/>
      </svg>
    `;

    divider = document.createElement("div");
    divider.className = "qwenpaw-divider";

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
    banner.append(logo, divider, pulseDot, status);
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
    status.textContent = state.statusText;
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
      return `Key ${String(input.key).slice(0, 32)}`;
    }
    if (input.text) {
      const value = String(input.text).replace(/\s+/g, " ").trim();
      return value.slice(0, 72);
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
      state.statusText = params.status_text || "QwenPaw";
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

  function fileUpload() {
    return {
      ok: false,
      error_code: "capability_missing",
      message:
        "File upload is handled through Browser Control CDP setFileInputFiles.",
    };
  }

  function setDialogDecision(params) {
    return {
      ok: true,
      accept: params.accept !== false,
      promptText: params.promptText || "",
    };
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
    if (message.method === "file.upload") {
      sendResponse(fileUpload(params));
      return false;
    }
    if (message.method === "dialog.set") {
      sendResponse(setDialogDecision(params));
      return false;
    }

    sendResponse({ ok: false, error: `Unknown method: ${message.method}` });
    return false;
  });
})();

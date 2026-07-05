const NATIVE_HOST = "com.qwenpaw.browser";
const JSONRPC_VERSION = "2.0";
const RECONNECT_ALARM = "qwenpaw-native-reconnect";
const PRODUCTION_INITIAL_RECONNECT_BACKOFF_SECONDS = 30;
const PRODUCTION_MAX_RECONNECT_BACKOFF_SECONDS = 300;
const CONTROL_TAB_GROUP_TITLE = "QwenPaw";
const CONTROL_TAB_GROUP_COLOR = "blue";

if (typeof importScripts === "function") {
  try {
    importScripts("bridge_config.js");
  } catch (error) {
    // Optional local development config; production builds omit it.
  }
}

const bridgeConfig = globalThis.QWENPAW_BRIDGE_CONFIG || {};
const INITIAL_RECONNECT_BACKOFF_SECONDS =
  Number(bridgeConfig.initialReconnectBackoffSeconds) ||
  PRODUCTION_INITIAL_RECONNECT_BACKOFF_SECONDS;
const MAX_RECONNECT_BACKOFF_SECONDS =
  Number(bridgeConfig.maxReconnectBackoffSeconds) ||
  PRODUCTION_MAX_RECONNECT_BACKOFF_SECONDS;

let nmPort = null;
let nextNotificationId = 1;
let cleanupEpoch = 0;
let reconnectAttempts = 0;
let lastDisconnectReason = "";
const managedTabs = new Set();
const createdTabs = new Set();

async function persistManagedTabs() {
  await chrome.storage.session.set({
    managedTabs: Array.from(managedTabs),
    createdTabs: Array.from(createdTabs),
  });
}

async function restoreManagedTabs() {
  const data = await chrome.storage.session.get(["managedTabs", "createdTabs"]);
  const tabIds = Array.isArray(data.managedTabs) ? data.managedTabs : [];
  for (const tabId of tabIds) {
    managedTabs.add(tabId);
  }
  const createdTabIds = Array.isArray(data.createdTabs)
    ? data.createdTabs
    : [];
  for (const tabId of createdTabIds) {
    createdTabs.add(tabId);
  }
}

function jsonRpcResult(id, result) {
  return { jsonrpc: JSONRPC_VERSION, id, result };
}

function jsonRpcError(id, code, message, data) {
  const error = { code, message };
  if (data !== undefined) {
    error.data = data;
  }
  return { jsonrpc: JSONRPC_VERSION, id, error };
}

function postNative(message) {
  if (!nmPort) {
    return false;
  }

  try {
    nmPort.postMessage(message);
    return true;
  } catch (error) {
    console.warn("Failed to post native message", error);
    return false;
  }
}

function sendEvent(method, params) {
  postNative({
    jsonrpc: JSONRPC_VERSION,
    id: `evt-${nextNotificationId++}`,
    method,
    params: params || {},
  });
}

function hasControlInterest() {
  return managedTabs.size > 0 || createdTabs.size > 0;
}

function tabLifecycleEventParams(tab, extra) {
  const params = { ...(extra || {}) };
  const tabId =
    tab && tab.id !== undefined
      ? tab.id
      : params.tabId !== undefined
        ? params.tabId
        : params.id;

  if (tabId !== undefined) {
    params.id = tabId;
    params.tabId = tabId;
    params.managed = managedTabs.has(tabId);
    params.createdByQwenPaw = createdTabs.has(tabId);
  }

  for (const key of [
    "url",
    "pendingUrl",
    "title",
    "active",
    "windowId",
    "index",
    "openerTabId",
    "status",
    "groupId",
  ]) {
    if (tab && tab[key] !== undefined) {
      params[key] = tab[key];
    }
  }

  return params;
}

function debuggerTarget(tabId) {
  return { tabId };
}

async function installSilentNewContextGuard(tabId) {
  if (!chrome.scripting || !chrome.scripting.executeScript) {
    return { tabId, installed: false, reason: "scripting unavailable" };
  }

  try {
    await chrome.scripting.executeScript({
      target: { tabId, allFrames: true },
      world: "MAIN",
      func: () => {
        const marker = "__qwenpawSilentNewContextGuardInstalled__";
        const stateName = "__qwenpawSilentNewContextGuardState";
        const state = window[stateName] || {
          expiresAt: 0,
          allowNewContext: false,
        };
        window[stateName] = state;
        const now = () => Date.now();

        const isActive = () => {
          const expiresAt = Number(state.expiresAt || 0);
          if (!expiresAt || expiresAt < now()) {
            return false;
          }
          return state.allowNewContext !== true;
        };

        const eventMatchesPoint = (event) => {
          if (!isActive()) {
            return false;
          }
          if (
            typeof event.clientX !== "number" ||
            typeof event.clientY !== "number"
          ) {
            return true;
          }
          const expectedX = Number(state.x);
          const expectedY = Number(state.y);
          if (
            !Number.isFinite(expectedX) ||
            !Number.isFinite(expectedY)
          ) {
            return true;
          }
          return (
            Math.abs(event.clientX - expectedX) <= 3 &&
            Math.abs(event.clientY - expectedY) <= 3
          );
        };

        if (window[marker]) {
          return;
        }
        Object.defineProperty(window, marker, {
          value: true,
          configurable: false,
        });

        const resolveUrl = (url) => {
          if (url === undefined || url === null) {
            return "";
          }
          const raw = String(url).trim();
          if (!raw) {
            return "";
          }
          try {
            return new URL(raw, window.location.href).href;
          } catch (_error) {
            return raw;
          }
        };

        const navigateHere = (url) => {
          if (!isActive()) {
            return false;
          }
          const resolved = resolveUrl(url);
          if (!resolved) {
            return false;
          }
          window.location.assign(resolved);
          return true;
        };

        const originalOpen = window.open;
        if (!window.__qwenpawOriginalWindowOpen) {
          Object.defineProperty(window, "__qwenpawOriginalWindowOpen", {
            value: originalOpen,
            configurable: false,
          });
        }
        window.open = function qwenpawSilentWindowOpen(
          url,
          target,
          features,
        ) {
          if (navigateHere(url)) {
            return window;
          }
          if (typeof originalOpen === "function") {
            return originalOpen.apply(window, arguments);
          }
          return null;
        };

        const findAnchor = (event) => {
          const path =
            typeof event.composedPath === "function"
              ? event.composedPath()
              : [];
          for (const node of path) {
            if (node && node.tagName === "A") {
              return node;
            }
          }
          if (event.target && typeof event.target.closest === "function") {
            return event.target.closest("a[href]");
          }
          return null;
        };

        const restoreTarget = (element, originalTarget) => {
          window.setTimeout(() => {
            if (!element || !element.isConnected) {
              return;
            }
            if (originalTarget) {
              element.setAttribute("target", originalTarget);
            } else {
              element.removeAttribute("target");
            }
          }, 0);
        };

        document.addEventListener(
          "click",
          (event) => {
            if (!eventMatchesPoint(event)) {
              return;
            }
            const anchor = findAnchor(event);
            if (!anchor) {
              return;
            }
            const originalTarget = anchor.getAttribute("target");
            const target = String(originalTarget || "")
              .trim()
              .toLowerCase();
            if (target && target !== "_self") {
              anchor.setAttribute("target", "_self");
              restoreTarget(anchor, originalTarget);
            }
          },
          true,
        );

        document.addEventListener(
          "submit",
          (event) => {
            if (!isActive()) {
              return;
            }
            const form = event.target;
            if (!form || form.tagName !== "FORM") {
              return;
            }
            const originalTarget = form.getAttribute("target");
            const target = String(originalTarget || "")
              .trim()
              .toLowerCase();
            if (target && target !== "_self") {
              form.setAttribute("target", "_self");
              restoreTarget(form, originalTarget);
            }
          },
          true,
        );
      },
    });
    return { tabId, installed: true };
  } catch (error) {
    console.debug(
      "Failed to install silent new-context guard",
      tabId,
      error,
    );
    return { tabId, installed: false, reason: String(error) };
  }
}

async function attachDebugger(tabId) {
  if (managedTabs.has(tabId)) {
    await installSilentNewContextGuard(tabId);
    return { tabId, attached: true, alreadyAttached: true };
  }

  await new Promise((resolve, reject) => {
    chrome.debugger.attach(debuggerTarget(tabId), "1.3", () => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }

      resolve();
    });
  });
  managedTabs.add(tabId);
  await persistManagedTabs();
  await installSilentNewContextGuard(tabId);
  return { tabId, attached: true };
}

async function detachDebugger(tabId) {
  await new Promise((resolve, reject) => {
    chrome.debugger.detach(debuggerTarget(tabId), () => {
      if (chrome.runtime.lastError) {
        const message = chrome.runtime.lastError.message || "";
        if (!message.includes("Debugger is not attached")) {
          reject(new Error(message));
          return;
        }
      }

      resolve();
    });
  });
  managedTabs.delete(tabId);
  await persistManagedTabs();
  return { tabId, detached: true };
}

function sendCdp(tabId, method, params) {
  return new Promise((resolve, reject) => {
    chrome.debugger.sendCommand(
      debuggerTarget(tabId),
      method,
      params || {},
      (result) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }

        resolve(result || {});
      },
    );
  });
}

function isAttachableTab(tab) {
  const url = (tab && tab.url) || "";
  return url.startsWith("http://") || url.startsWith("https://");
}

async function listTabs(queryInfo) {
  const tabs = await chrome.tabs.query(queryInfo || {});
  const liveTabIds = new Set(
    tabs
      .filter((tab) => tab && tab.id !== undefined)
      .map((tab) => tab.id),
  );
  let prunedCreatedTabs = false;
  for (const tabId of Array.from(createdTabs)) {
    if (!liveTabIds.has(tabId)) {
      createdTabs.delete(tabId);
      prunedCreatedTabs = true;
    }
  }
  if (prunedCreatedTabs) {
    await persistManagedTabs();
  }

  const groupCache = new Map();
  const attachGroupInfo = async (tab) => {
    if (
      !tab ||
      !Number.isInteger(tab.groupId) ||
      tab.groupId < 0 ||
      !chrome.tabGroups ||
      !chrome.tabGroups.get
    ) {
      return {};
    }
    if (!groupCache.has(tab.groupId)) {
      try {
        groupCache.set(tab.groupId, await chrome.tabGroups.get(tab.groupId));
      } catch (error) {
        groupCache.set(tab.groupId, null);
      }
    }
    const group = groupCache.get(tab.groupId);
    if (!group) {
      return {};
    }
    return {
      tabGroupId: group.id,
      tabGroupTitle: group.title || "",
      tabGroupColor: group.color || "",
    };
  };

  const visibleTabs = tabs.filter(isAttachableTab);
  return Promise.all(
    visibleTabs.map(async (tab) => ({
      ...tab,
      ...(await attachGroupInfo(tab)),
      managed: tab && tab.id !== undefined ? managedTabs.has(tab.id) : false,
      createdByQwenPaw:
        tab && tab.id !== undefined ? createdTabs.has(tab.id) : false,
    })),
  );
}

async function groupControlTab(tab) {
  if (!tab || tab.id === undefined) {
    return tab;
  }
  if (!chrome.tabs.group || !chrome.tabGroups || !chrome.tabGroups.update) {
    return tab;
  }

  try {
    const groupId = await chrome.tabs.group({ tabIds: tab.id });
    await chrome.tabGroups.update(groupId, {
      title: CONTROL_TAB_GROUP_TITLE,
      color: CONTROL_TAB_GROUP_COLOR,
    });
  } catch (error) {
    console.warn("Failed to group control tab", error);
  }

  return tab;
}

async function createTab(params) {
  const tab = await chrome.tabs.create({
    url: params && params.url ? params.url : "about:blank",
    active:
      params && params.active !== undefined ? Boolean(params.active) : false,
  });
  const controlTab = await groupControlTab(tab);
  if (controlTab && controlTab.id !== undefined) {
    createdTabs.add(controlTab.id);
    await persistManagedTabs();
  }
  return { ...controlTab, createdByQwenPaw: true };
}

async function ensureTabAvailable(params) {
  const tabId = params && params.tabId;
  if (tabId === undefined || tabId === null) {
    throw new Error("tabId required");
  }
  // Do NOT switch the active tab. CDP commands work via the debugger channel
  // regardless of tab visibility. Switching tabs disrupts the user's browsing.
  // Just verify the tab exists and return its current state.
  const tab = await chrome.tabs.get(tabId);
  return { tabId, active: tab && tab.active, windowId: tab && tab.windowId };
}

async function closeTab(params) {
  const tabId = params && params.tabId;
  if (tabId === undefined || tabId === null) {
    throw new Error("tabId required");
  }

  try {
    await sendBannerMessage(tabId, "banner.hide", {});
  } catch (error) {
    console.debug("Failed to hide banner before closing tab", tabId, error);
  }

  if (managedTabs.has(tabId)) {
    try {
      await detachDebugger(tabId);
    } catch (error) {
      console.debug(
        "Failed to detach debugger before closing tab",
        tabId,
        error,
      );
      managedTabs.delete(tabId);
      await persistManagedTabs();
    }
  }

  await chrome.tabs.remove(tabId);
  managedTabs.delete(tabId);
  createdTabs.delete(tabId);
  await persistManagedTabs();
  return { tabId, closed: true };
}

async function ensureContentScript(tabId) {
  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["content_script.js"],
  });
}

function missingContentScriptReceiver(error) {
  const message = error && error.message ? error.message : String(error || "");
  return (
    message.includes("Receiving end does not exist") ||
    message.includes("Could not establish connection")
  );
}

async function sendContentMessage(tabId, method, params) {
  const message = {
    source: "qwenpaw-browser-bridge",
    method,
    params: params || {},
  };

  try {
    return await chrome.tabs.sendMessage(tabId, message);
  } catch (error) {
    if (!missingContentScriptReceiver(error)) {
      throw error;
    }
  }

  await ensureContentScript(tabId);
  return chrome.tabs.sendMessage(tabId, message);
}

async function sendBannerMessage(tabId, method, params) {
  return sendContentMessage(tabId, method, params);
}

async function cleanupOrphans() {
  const epoch = ++cleanupEpoch;
  const tabIds = Array.from(managedTabs);

  for (const tabId of tabIds) {
    if (epoch !== cleanupEpoch) {
      break;
    }

    try {
      await detachDebugger(tabId);
    } catch (error) {
      console.warn("Failed to detach tab during cleanup", tabId, error);
      managedTabs.delete(tabId);
      await persistManagedTabs();
    }

    try {
      await sendBannerMessage(tabId, "banner.hide", {});
    } catch (error) {
      console.debug("Failed to hide banner during cleanup", tabId, error);
    }
  }
}

function reconnectBackoffSeconds() {
  if (reconnectAttempts <= 0) {
    return INITIAL_RECONNECT_BACKOFF_SECONDS;
  }
  return Math.min(
    MAX_RECONNECT_BACKOFF_SECONDS,
    INITIAL_RECONNECT_BACKOFF_SECONDS * Math.pow(2, reconnectAttempts),
  );
}

function scheduleReconnect() {
  const delaySeconds = reconnectBackoffSeconds();
  reconnectAttempts += 1;
  chrome.alarms.create(RECONNECT_ALARM, {
    delayInMinutes: delaySeconds / 60,
  });
}

function clearReconnectAlarm() {
  reconnectAttempts = 0;
  chrome.alarms.clear(RECONNECT_ALARM);
}

function runtimeLastErrorMessage() {
  const lastError = chrome.runtime.lastError;
  return lastError && lastError.message ? lastError.message : "";
}

async function handleMessage(message) {
  const id = message && message.id !== undefined ? message.id : null;
  const params = message && message.params ? message.params : {};

  try {
    switch (message && message.method) {
      case "cdp.send":
        // Page.captureScreenshot works on background tabs when a debugger is
        // attached: chrome.debugger.attach() keeps the renderer alive and CDP
        // forces a synchronous composite before capture. No tab activation
        // needed — same mechanism that headless Chrome relies on.
        return jsonRpcResult(
          id,
          await sendCdp(params.tabId, params.method, params.params || {}),
        );
      case "tabs.list":
        return jsonRpcResult(id, await listTabs(params.query || {}));
      case "tab.attach":
        return jsonRpcResult(id, await attachDebugger(params.tabId));
      case "tab.detach":
        return jsonRpcResult(id, await detachDebugger(params.tabId));
      case "tab.ensure":
        return jsonRpcResult(id, await ensureTabAvailable(params));
      case "tab.close":
        return jsonRpcResult(id, await closeTab(params));
      case "tab.create":
        return jsonRpcResult(id, await createTab(params));
      case "banner.show":
        return jsonRpcResult(
          id,
          await sendBannerMessage(params.tabId, "banner.show", params),
        );
      case "banner.hide":
        return jsonRpcResult(
          id,
          await sendBannerMessage(params.tabId, "banner.hide", params),
        );
      case "file.upload":
        return jsonRpcResult(
          id,
          await sendContentMessage(params.tabId, "file.upload", params),
        );
      case "download.read":
        return jsonRpcResult(id, {
          ok: false,
          error_code: "capability_missing",
          message:
            "Download artifacts are collected through Browser Control CDP events.",
        });
      case "dialog.set":
        return jsonRpcResult(id, {
          ok: true,
          tabId: params.tabId,
          accept: params.accept !== false,
          promptText: params.promptText || "",
        });
      default:
        return jsonRpcError(id, -32601, "Method not found");
    }
  } catch (error) {
    return jsonRpcError(id, -32000, error.message || String(error));
  }
}

function connectNative() {
  if (nmPort) {
    return;
  }

  let port = null;
  try {
    cleanupEpoch++;
    port = chrome.runtime.connectNative(NATIVE_HOST);
    nmPort = port;
    lastDisconnectReason = "";
    clearReconnectAlarm();
  } catch (error) {
    console.warn("Failed to connect native host", error);
    nmPort = null;
    scheduleReconnect();
    return;
  }

  port.onMessage.addListener(async (message) => {
    if (port !== nmPort) {
      return;
    }

    const response = await handleMessage(message);
    postNative(response);
  });

  port.onDisconnect.addListener(async () => {
    const disconnectReason = runtimeLastErrorMessage();
    if (disconnectReason) {
      console.warn("Native host disconnected", disconnectReason);
    }

    if (port !== nmPort) {
      return;
    }

    lastDisconnectReason = disconnectReason;
    nmPort = null;
    await cleanupOrphans();
    sendEvent(
      "bridge.disconnected",
      disconnectReason ? { reason: disconnectReason } : {},
    );
    scheduleReconnect();
  });

  sendEvent("bridge.connected", {
    version: chrome.runtime.getManifest().version,
  });
}

chrome.debugger.onEvent.addListener((source, method, params) => {
  if (!source || source.tabId === undefined || !managedTabs.has(source.tabId)) {
    return;
  }

  sendEvent("cdp.event", {
    tabId: source.tabId,
    method,
    params: params || {},
  });
});

chrome.debugger.onDetach.addListener(async (source, reason) => {
  if (!source || source.tabId === undefined) {
    return;
  }

  managedTabs.delete(source.tabId);
  await persistManagedTabs();
  sendEvent("tab.detached", {
    tabId: source.tabId,
    reason,
  });
});

chrome.webNavigation.onCreatedNavigationTarget.addListener((details) => {
  if (!details || !managedTabs.has(details.sourceTabId)) {
    return;
  }

  sendEvent("webNavigation.createdNavigationTarget", {
    tabId: details.tabId,
    sourceTabId: details.sourceTabId,
    url: details.url || "",
    frameId: details.frameId,
    timeStamp: details.timeStamp,
  });
});

chrome.tabs.onCreated.addListener((tab) => {
  if (!hasControlInterest()) {
    return;
  }

  sendEvent("tabs.created", tabLifecycleEventParams(tab));
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (
    !hasControlInterest() &&
    !managedTabs.has(tabId) &&
    !createdTabs.has(tabId)
  ) {
    return;
  }

  sendEvent(
    "tabs.updated",
    tabLifecycleEventParams(tab, {
      tabId,
      changeInfo: changeInfo || {},
    }),
  );
});

chrome.tabs.onActivated.addListener((activeInfo) => {
  if (!hasControlInterest()) {
    return;
  }

  sendEvent("tabs.activated", activeInfo || {});
});

chrome.tabs.onRemoved.addListener((tabId, removeInfo) => {
  const wasManaged = managedTabs.has(tabId);
  const wasCreated = createdTabs.has(tabId);
  if (!wasManaged && !wasCreated) {
    return;
  }
  sendEvent("tabs.removed", {
    tabId,
    ...(removeInfo || {}),
    managed: wasManaged,
    createdByQwenPaw: wasCreated,
  });
  managedTabs.delete(tabId);
  createdTabs.delete(tabId);
  void persistManagedTabs();
});

chrome.webNavigation.onCompleted.addListener(async (details) => {
  if (!details || details.frameId !== 0 || !managedTabs.has(details.tabId)) {
    return;
  }
  if (!isAttachableTab({ url: details.url })) {
    return;
  }

  try {
    await installSilentNewContextGuard(details.tabId);
    await ensureContentScript(details.tabId);
  } catch (error) {
    console.debug(
      "Failed to re-inject control scripts after navigation",
      details.tabId,
      error,
    );
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message && message.source === "qwenpaw-browser-bridge-popup") {
    if (message.method === "status.get") {
      if (!nmPort) {
        connectNative();
      }
      sendResponse({
        ok: true,
        connected: Boolean(nmPort),
        nativeHost: NATIVE_HOST,
        managedTabsCount: managedTabs.size,
        reconnectAttempts,
        lastDisconnectReason,
        version: chrome.runtime.getManifest().version,
      });
      return false;
    }
  }

  if (!message || message.source !== "qwenpaw-browser-bridge-content") {
    return false;
  }

  const tabId = sender && sender.tab ? sender.tab.id : undefined;
  sendEvent(message.method, {
    ...(message.params || {}),
    tabId,
  });
  sendResponse({ ok: true });
  return false;
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (!alarm || alarm.name !== RECONNECT_ALARM) {
    return;
  }
  if (nmPort) {
    clearReconnectAlarm();
    return;
  }
  connectNative();
});

chrome.runtime.onInstalled.addListener(() => {
  connectNative();
});

chrome.runtime.onStartup.addListener(() => {
  connectNative();
});

async function initialize() {
  await restoreManagedTabs();
  if (managedTabs.size > 0 && !nmPort) {
    await cleanupOrphans();
  }
  connectNative();
}

initialize();

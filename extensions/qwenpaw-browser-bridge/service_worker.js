const NATIVE_HOST = "com.qwenpaw.browser";
const JSONRPC_VERSION = "2.0";
const RECONNECT_ALARM = "qwenpaw-native-reconnect";
const PRODUCTION_INITIAL_RECONNECT_BACKOFF_SECONDS = 30;
const PRODUCTION_MAX_RECONNECT_BACKOFF_SECONDS = 300;
const TAKEOVER_TAB_GROUP_TITLE = "QwenPaw";
const TAKEOVER_TAB_GROUP_COLOR = "blue";

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

async function persistManagedTabs() {
  await chrome.storage.session.set({ managedTabs: Array.from(managedTabs) });
}

async function restoreManagedTabs() {
  const data = await chrome.storage.session.get("managedTabs");
  const tabIds = Array.isArray(data.managedTabs) ? data.managedTabs : [];
  for (const tabId of tabIds) {
    managedTabs.add(tabId);
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

function debuggerTarget(tabId) {
  return { tabId };
}

async function attachDebugger(tabId) {
  if (managedTabs.has(tabId)) {
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
  return tabs.filter(isAttachableTab).map((tab) => ({
    ...tab,
    managed: tab && tab.id !== undefined ? managedTabs.has(tab.id) : false,
  }));
}

async function groupTakeoverTab(tab) {
  if (!tab || tab.id === undefined) {
    return tab;
  }
  if (!chrome.tabs.group || !chrome.tabGroups || !chrome.tabGroups.update) {
    return tab;
  }

  try {
    const groupId = await chrome.tabs.group({ tabIds: tab.id });
    await chrome.tabGroups.update(groupId, {
      title: TAKEOVER_TAB_GROUP_TITLE,
      color: TAKEOVER_TAB_GROUP_COLOR,
    });
  } catch (error) {
    console.warn("Failed to group takeover tab", error);
  }

  return tab;
}

async function createTab(params) {
  const tab = await chrome.tabs.create({
    url: params && params.url ? params.url : "about:blank",
    active:
      params && params.active !== undefined ? Boolean(params.active) : true,
  });
  return groupTakeoverTab(tab);
}

async function activateTab(params) {
  const tabId = params && params.tabId;
  if (tabId === undefined || tabId === null) {
    throw new Error("tabId required");
  }
  const tab = await chrome.tabs.update(tabId, { active: true });
  return { tabId, active: true, windowId: tab && tab.windowId };
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

async function sendBannerMessage(tabId, method, params) {
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

async function stopManagedTab(tabId) {
  if (tabId === undefined || tabId === null) {
    return;
  }

  try {
    await detachDebugger(tabId);
  } catch (error) {
    console.warn("Failed to detach tab after stop request", tabId, error);
    managedTabs.delete(tabId);
    await persistManagedTabs();
  }

  try {
    await sendBannerMessage(tabId, "banner.hide", {});
  } catch (error) {
    console.debug("Failed to hide banner after stop request", tabId, error);
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
      case "tab.activate":
        return jsonRpcResult(id, await activateTab(params));
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

chrome.webNavigation.onCompleted.addListener(async (details) => {
  if (!details || details.frameId !== 0 || !managedTabs.has(details.tabId)) {
    return;
  }
  if (!isAttachableTab({ url: details.url })) {
    return;
  }

  try {
    await ensureContentScript(details.tabId);
  } catch (error) {
    console.debug(
      "Failed to re-inject content script after navigation",
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
  if (message.method === "hitl.stopped") {
    void stopManagedTab(tabId);
  }
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

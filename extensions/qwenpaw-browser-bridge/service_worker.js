const NATIVE_HOST = "com.qwenpaw.browser";
const JSONRPC_VERSION = "2.0";
const RECONNECT_ALARM = "qwenpaw-native-reconnect";
const MAX_RECONNECT_BACKOFF_SECONDS = 300;

let nmPort = null;
let nextNotificationId = 1;
let cleanupEpoch = 0;
let reconnectAttempts = 0;
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
  return tabs.filter(isAttachableTab);
}

function createTab(params) {
  return chrome.tabs.create({
    url: params && params.url ? params.url : "about:blank",
    active:
      params && params.active !== undefined ? Boolean(params.active) : true,
  });
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

function reconnectBackoffSeconds() {
  if (reconnectAttempts <= 0) {
    return 30;
  }
  return Math.min(
    MAX_RECONNECT_BACKOFF_SECONDS,
    30 * Math.pow(2, reconnectAttempts),
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
  try {
    cleanupEpoch++;
    nmPort = chrome.runtime.connectNative(NATIVE_HOST);
    clearReconnectAlarm();
  } catch (error) {
    console.warn("Failed to connect native host", error);
    nmPort = null;
    scheduleReconnect();
    return;
  }

  nmPort.onMessage.addListener(async (message) => {
    const response = await handleMessage(message);
    postNative(response);
  });

  nmPort.onDisconnect.addListener(async () => {
    nmPort = null;
    await cleanupOrphans();
    sendEvent("bridge.disconnected", {});
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
      sendResponse({
        ok: true,
        connected: Boolean(nmPort),
        nativeHost: NATIVE_HOST,
        managedTabsCount: managedTabs.size,
        reconnectAttempts,
        version: chrome.runtime.getManifest().version,
      });
      return false;
    }
  }

  if (!message || message.source !== "qwenpaw-browser-bridge-content") {
    return false;
  }

  sendEvent(message.method, {
    ...(message.params || {}),
    tabId: sender && sender.tab ? sender.tab.id : undefined,
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

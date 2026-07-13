const NATIVE_HOST = "com.qwenpaw.browser";
const JSONRPC_VERSION = "2.0";
const RECONNECT_ALARM = "qwenpaw-native-reconnect";
const PRODUCTION_INITIAL_RECONNECT_BACKOFF_SECONDS = 30;
const PRODUCTION_MAX_RECONNECT_BACKOFF_SECONDS = 300;
const CONTROL_TAB_GROUP_TITLE = "QwenPaw";
const CONTROL_TAB_GROUP_COLOR = "blue";
const PROTECTED_BROWSER_SCHEMES = new Set([
  "brave:",
  "chrome:",
  "chrome-extension:",
  "devtools:",
  "edge:",
  "moz-extension:",
  "opera:",
  "vivaldi:",
]);
const LOCAL_QWENPAW_HOSTS = new Set([
  "127.0.0.1",
  "::1",
  "[::1]",
  "localhost",
]);
const LOCAL_QWENPAW_PORTS = new Set(["8088"]);
const TAB_OWNERSHIP_OWNED = "owned";
const TAB_OWNERSHIP_BORROWED = "borrowed";
const TAB_OWNERSHIP_PENDING_CLAIM = "pending_claim";
const TAB_OWNERSHIP_PROTECTED = "protected";
const TAB_OWNERSHIP_ORPHANED = "orphaned";
const TAB_OWNERSHIP_RELEASED = "released";
const COMMAND_RECEIPT_PREFIX = "qwenpawCommandReceipt:";
const COMMAND_EVICTIONS_KEY = "qwenpawCommandReceiptEvictions";
const COMMAND_RECEIPT_TTL_MS = 5 * 60 * 1000;
const COMMAND_RECEIPT_CAPACITY = 256;

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
const tabMetadata = new Map();
const commandInflight = new Map();
const popupEventCounts = new Map();
const MAX_POPUP_EVENTS_PER_SOURCE = 8;

async function persistManagedTabs() {
  const persistedMetadata = {};
  for (const [tabId, metadata] of tabMetadata.entries()) {
    persistedMetadata[String(tabId)] = { ...metadata };
  }
  await chrome.storage.session.set({
    managedTabs: Array.from(managedTabs),
    createdTabs: Array.from(createdTabs),
    tabMetadata: persistedMetadata,
  });
}

async function restoreManagedTabs() {
  const data = await chrome.storage.session.get([
    "managedTabs",
    "createdTabs",
    "tabMetadata",
  ]);
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
  const restoredMetadata = data.tabMetadata || {};
  for (const [rawTabId, metadata] of Object.entries(restoredMetadata)) {
    const tabId = Number(rawTabId);
    if (Number.isFinite(tabId) && metadata && typeof metadata === "object") {
      tabMetadata.set(tabId, { ...metadata, tabId });
    }
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

const BROWSER_BUILD_FINGERPRINT = "build-1";
const BROWSER_CONTRACT_FINGERPRINT = "contract-v1";
const BROWSER_PROFILE_FINGERPRINT = "profile-v1";
const BROWSER_EXTENSION_FINGERPRINT = "extension@build-1";

function hasControlInterest() {
  return managedTabs.size > 0 || createdTabs.size > 0 || tabMetadata.size > 0;
}

function tabProtocolMetadata(tabId) {
  const metadata = tabMetadata.get(Number(tabId));
  return metadata ? { ...metadata } : {};
}

async function storeTabProtocolMetadata(tabId, metadata) {
  if (tabId === undefined || tabId === null) {
    throw new Error("tabId required");
  }
  const normalized = {
    protocolVersion: Number(metadata.protocolVersion || 2),
    tabId: Number(tabId),
    ownerId: String(metadata.ownerId || ""),
    workspaceId: String(metadata.workspaceId || ""),
    ownershipState: String(metadata.ownershipState || ""),
    createdByQwenPaw: Boolean(metadata.createdByQwenPaw),
    buildFingerprint: BROWSER_BUILD_FINGERPRINT,
    contractFingerprint: BROWSER_CONTRACT_FINGERPRINT,
    profileFingerprint: BROWSER_PROFILE_FINGERPRINT,
    extensionFingerprint: BROWSER_EXTENSION_FINGERPRINT,
  };
  if (normalized.protocolVersion === 2) {
    if (!normalized.ownerId || !normalized.workspaceId) {
      throw new Error("ownerId and workspaceId are required");
    }
  }
  tabMetadata.set(Number(tabId), normalized);
  await persistManagedTabs();
  return { ...normalized };
}

async function removeTabProtocolMetadata(tabId) {
  tabMetadata.delete(Number(tabId));
  await persistManagedTabs();
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
    params.ownershipState = tabOwnershipState(tabId, tab);
    Object.assign(params, tabProtocolMetadata(tabId));
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
  const tab = await chrome.tabs.get(tabId);
  assertTabNotProtected(tab);
  if (managedTabs.has(tabId)) {
    await installSilentNewContextGuard(tabId);
    return {
      tabId,
      attached: true,
      alreadyAttached: true,
      ownershipState: TAB_OWNERSHIP_BORROWED,
    };
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
  return { tabId, attached: true, ownershipState: TAB_OWNERSHIP_BORROWED };
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
  await removeTabProtocolMetadata(tabId);
  return { tabId, detached: true, ownershipState: TAB_OWNERSHIP_RELEASED };
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
  return (
    (url.startsWith("http://") || url.startsWith("https://")) &&
    !isProtectedTabUrl(url)
  );
}

function isProtectedTabUrl(url) {
  const value = String(url || "").trim();
  if (!value) {
    return false;
  }
  let parsed = null;
  try {
    parsed = new URL(value);
  } catch (_error) {
    return false;
  }
  if (PROTECTED_BROWSER_SCHEMES.has(parsed.protocol)) {
    return true;
  }
  if (parsed.protocol === "about:" && value.toLowerCase() !== "about:blank") {
    return true;
  }
  return (
    LOCAL_QWENPAW_HOSTS.has(parsed.hostname) &&
    LOCAL_QWENPAW_PORTS.has(parsed.port)
  );
}

function assertTabNotProtected(tab) {
  if (isProtectedTabUrl(tab && tab.url)) {
    const error = new Error("PROTECTED_TAB_REQUIRES_EXPLICIT_OVERRIDE");
    error.code = "PROTECTED_TAB_REQUIRES_EXPLICIT_OVERRIDE";
    error.tabId = tab && tab.id;
    error.url = (tab && tab.url) || "";
    throw error;
  }
}

function tabOwnershipState(tabId, tab) {
  const metadata = tabProtocolMetadata(tabId);
  if (metadata.ownershipState) {
    return metadata.ownershipState;
  }
  if (createdTabs.has(tabId)) {
    return TAB_OWNERSHIP_OWNED;
  }
  if (managedTabs.has(tabId)) {
    return TAB_OWNERSHIP_BORROWED;
  }
  if (isProtectedTabUrl(tab && tab.url)) {
    return TAB_OWNERSHIP_PROTECTED;
  }
  if (tab && tab.createdByQwenPaw) {
    return TAB_OWNERSHIP_ORPHANED;
  }
  return "";
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
    visibleTabs.map(async (tab) => {
      const metadata =
        tab && tab.id !== undefined ? tabProtocolMetadata(tab.id) : {};
      return {
        ...tab,
        ...(await attachGroupInfo(tab)),
        managed:
          tab && tab.id !== undefined ? managedTabs.has(tab.id) : false,
        createdByQwenPaw:
          metadata.createdByQwenPaw !== undefined
            ? metadata.createdByQwenPaw
            : tab && tab.id !== undefined
              ? createdTabs.has(tab.id)
              : false,
        ownershipState:
          metadata.ownershipState ||
          (tab && tab.id !== undefined ? tabOwnershipState(tab.id, tab) : ""),
        ...metadata,
      };
    }),
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
  const protocolVersion = Number(params && params.protocolVersion ? params.protocolVersion : 2);
  const ownerId = String((params && params.ownerId) || "");
  const workspaceId = String(
    (params && (params.workspaceId || params.workspace)) || "",
  );
  if (protocolVersion === 2 && (!ownerId || !workspaceId)) {
    throw new Error("ownerId and workspaceId are required");
  }
  const tab = await chrome.tabs.create({
    url: params && params.url ? params.url : "about:blank",
    active:
      params && params.active !== undefined ? Boolean(params.active) : false,
  });
  const controlTab = await groupControlTab(tab);
  if (controlTab && controlTab.id !== undefined) {
    createdTabs.add(controlTab.id);
    await storeTabProtocolMetadata(controlTab.id, {
      protocolVersion,
      ownerId,
      workspaceId,
      ownershipState: TAB_OWNERSHIP_PENDING_CLAIM,
      createdByQwenPaw: true,
    });
    await persistManagedTabs();
  }
  return {
    ...controlTab,
    ...(
      controlTab && controlTab.id !== undefined
        ? tabProtocolMetadata(controlTab.id)
        : {}
    ),
    createdByQwenPaw: true,
    workspace: workspaceId,
  };
}

async function commitTabMetadata(params) {
  const tabId = params && params.tabId;
  if (tabId === undefined || tabId === null) {
    throw new Error("tabId required");
  }
  const current = tabProtocolMetadata(tabId);
  const ownerId = String((params && params.ownerId) || current.ownerId || "");
  const workspaceId = String(
    (params && params.workspaceId) || current.workspaceId || "",
  );
  if (current.ownerId && current.ownerId !== ownerId) {
    throw new Error("ownerId mismatch");
  }
  if (current.workspaceId && current.workspaceId !== workspaceId) {
    throw new Error("workspaceId mismatch");
  }
  createdTabs.add(Number(tabId));
  return storeTabProtocolMetadata(tabId, {
    protocolVersion: Number(current.protocolVersion || 2),
    ownerId,
    workspaceId,
    ownershipState: TAB_OWNERSHIP_OWNED,
    createdByQwenPaw: true,
  });
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
  assertTabNotProtected(tab);
  return {
    tabId,
    active: tab && tab.active,
    windowId: tab && tab.windowId,
    ownershipState: tabOwnershipState(tabId, tab),
  };
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
  await removeTabProtocolMetadata(tabId);
  return { tabId, closed: true, ownershipState: TAB_OWNERSHIP_RELEASED };
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

async function cleanupOrphans(reason) {
  const epoch = ++cleanupEpoch;
  const managedTabIds = Array.from(managedTabs);
  const createdTabIds = Array.from(createdTabs);

  for (const tabId of managedTabIds) {
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

  for (const tabId of createdTabIds) {
    if (epoch !== cleanupEpoch) {
      break;
    }

    try {
      await sendBannerMessage(tabId, "banner.hide", {});
    } catch (error) {
      console.debug(
        "Failed to hide banner before orphan close",
        tabId,
        error,
      );
    }

    try {
      await chrome.tabs.remove(tabId);
      sendEvent("tabs.reconciled", {
        tabId,
        ownershipState: TAB_OWNERSHIP_RELEASED,
        reconciliationReason: reason || "startup",
        closed: true,
      });
    } catch (error) {
      console.warn("Failed to close owned orphan tab", tabId, error);
    } finally {
      createdTabs.delete(tabId);
      managedTabs.delete(tabId);
      await removeTabProtocolMetadata(tabId);
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

function extensionStatusPayload() {
  return {
    ok: true,
    connected: Boolean(nmPort),
    nativeHost: NATIVE_HOST,
    managedTabsCount: managedTabs.size,
    reconnectAttempts,
    lastDisconnectReason,
    version: chrome.runtime.getManifest().version,
  };
}

function requiredCommandText(value, fieldName) {
  const normalized = String(value || "").trim();
  if (!normalized) {
    throw new Error(`command_identity_invalid:${fieldName}`);
  }
  return normalized;
}

function commandReceiptKey(sessionId, commandId) {
  return COMMAND_RECEIPT_PREFIX + encodeURIComponent(sessionId) + ":" +
    encodeURIComponent(commandId);
}

async function commandReceipt(sessionId, commandId) {
  const key = commandReceiptKey(sessionId, commandId);
  const stored = await chrome.storage.session.get([key]);
  return stored[key] || null;
}

async function persistCommandReceipt(receipt) {
  if (!["RECEIVED", "RUNNING", "COMPLETED"].includes(receipt.state)) {
    throw new Error("command_receipt_state_invalid");
  }
  const key = commandReceiptKey(receipt.sessionId, receipt.commandId);
  await chrome.storage.session.set({ [key]: receipt });
  return receipt;
}

async function recordCommandEvictions(evictions) {
  if (!evictions.length) return;
  const stored = await chrome.storage.session.get([COMMAND_EVICTIONS_KEY]);
  const prior = Array.isArray(stored[COMMAND_EVICTIONS_KEY])
    ? stored[COMMAND_EVICTIONS_KEY] : [];
  await chrome.storage.session.set({
    [COMMAND_EVICTIONS_KEY]: [...prior, ...evictions].slice(
      -COMMAND_RECEIPT_CAPACITY,
    ),
  });
}

async function sweepCommandReceipts() {
  const stored = await chrome.storage.session.get(null);
  const now = Date.now();
  const receipts = Object.entries(stored)
    .filter(([key, value]) =>
      key.startsWith(COMMAND_RECEIPT_PREFIX) && value &&
      typeof value === "object")
    .sort((left, right) =>
      Number(left[1].updatedAt || 0) - Number(right[1].updatedAt || 0));
  const expired = receipts.filter(([, receipt]) =>
    now - Number(receipt.updatedAt || 0) > COMMAND_RECEIPT_TTL_MS);
  const live = receipts.filter(([, receipt]) =>
    now - Number(receipt.updatedAt || 0) <= COMMAND_RECEIPT_TTL_MS);
  const excess = live.slice(
    0, Math.max(0, live.length - COMMAND_RECEIPT_CAPACITY),
  );
  const removed = [...expired, ...excess];
  if (!removed.length) return;
  await chrome.storage.session.remove(removed.map(([key]) => key));
  const expiredKeys = new Set(expired.map(([key]) => key));
  await recordCommandEvictions(removed.map(([key, receipt]) => ({
    sessionId: receipt.sessionId,
    commandId: receipt.commandId,
    commandFingerprint: receipt.commandFingerprint,
    reason: expiredKeys.has(key) ? "TTL" : "CAPACITY",
    observedAt: now,
  })));
}

async function runReceiptCommand(params, executor) {
  const sessionId = requiredCommandText(params.sessionId, "sessionId");
  const commandId = requiredCommandText(params.commandId, "commandId");
  const commandFingerprint = requiredCommandText(
    params.commandFingerprint, "commandFingerprint",
  );
  await sweepCommandReceipts();
  const key = commandReceiptKey(sessionId, commandId);
  const inflight = commandInflight.get(key);
  if (inflight) {
    if (inflight.commandFingerprint !== commandFingerprint) {
      throw new Error("command_fingerprint_mismatch");
    }
    return inflight.promise;
  }
  const promise = (async () => {
    const existing = await commandReceipt(sessionId, commandId);
    if (existing) {
      if (existing.commandFingerprint !== commandFingerprint) {
        throw new Error("command_fingerprint_mismatch");
      }
      return existing;
    }
    const createdAt = Date.now();
    await persistCommandReceipt({
      sessionId, commandId, commandFingerprint, state: "RECEIVED",
      result: null, createdAt, updatedAt: createdAt,
    });
    await persistCommandReceipt({
      sessionId, commandId, commandFingerprint, state: "RUNNING",
      result: null, createdAt, updatedAt: Date.now(),
    });
    const result = await executor();
    return persistCommandReceipt({
      sessionId, commandId, commandFingerprint, state: "COMPLETED",
      result, createdAt, updatedAt: Date.now(),
    });
  })();
  commandInflight.set(key, { commandFingerprint, promise });
  try {
    return await promise;
  } finally {
    commandInflight.delete(key);
  }
}

async function executeClosedCommand(params) {
  const payload = params.payload || {};
  if (params.commandType === "CDP") {
    return sendCdp(payload.tabId, payload.method, payload.params || {});
  }
  throw new Error("command_type_unsupported");
}

async function executeCommand(params) {
  const receipt = await runReceiptCommand(params, () =>
    executeClosedCommand(params));
  return { receipt };
}

async function queryCommandStatus(params) {
  const queryReceipt = await runReceiptCommand({
    sessionId: params.sessionId,
    commandId: params.queryCommandId,
    commandFingerprint: params.queryCommandFingerprint,
  }, async () => {
    const targetReceipt = await commandReceipt(
      requiredCommandText(params.sessionId, "sessionId"),
      requiredCommandText(params.targetCommandId, "targetCommandId"),
    );
    if (targetReceipt &&
        targetReceipt.commandFingerprint !== params.targetCommandFingerprint) {
      throw new Error("command_fingerprint_mismatch");
    }
    const stored = await chrome.storage.session.get([COMMAND_EVICTIONS_KEY]);
    const evictions = Array.isArray(stored[COMMAND_EVICTIONS_KEY])
      ? stored[COMMAND_EVICTIONS_KEY] : [];
    const evicted = evictions.some((item) =>
      item.sessionId === params.sessionId &&
      item.commandId === params.targetCommandId &&
      item.commandFingerprint === params.targetCommandFingerprint);
    return {
      targetReceipt,
      targetCommandFact: {
        observedState: targetReceipt ? "OBSERVED" :
          evicted ? "LOST" : "UNKNOWN",
      },
    };
  });
  return {
    queryReceipt,
    targetReceipt: queryReceipt.result.targetReceipt,
    targetCommandFact: queryReceipt.result.targetCommandFact,
  };
}

async function handleMessage(message) {
  const id = message && message.id !== undefined ? message.id : null;
  const params = message && message.params ? message.params : {};

  try {
    switch (message && message.method) {
      case "command.execute":
        return jsonRpcResult(id, await executeCommand(params));
      case "command.status":
        return jsonRpcResult(id, await queryCommandStatus(params));
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
      case "tab.metadata.commit":
        return jsonRpcResult(id, await commitTabMetadata(params));
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
            "Download artifacts are collected through Browser Bridge CDP events.",
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

  if (hasControlInterest() && lastDisconnectReason) {
    void cleanupOrphans("bridge_reconnect");
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

  const count = (popupEventCounts.get(details.sourceTabId) || 0) + 1;
  popupEventCounts.set(details.sourceTabId, count);
  if (count > MAX_POPUP_EVENTS_PER_SOURCE) {
    sendEvent("webNavigation.popupOverflow", {
      sourceTabId: details.sourceTabId,
      count,
      cap: MAX_POPUP_EVENTS_PER_SOURCE,
      outcome: "PARTIAL",
      executionTruth: "UNCERTAIN",
    });
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
    ownershipState: TAB_OWNERSHIP_RELEASED,
  });
  managedTabs.delete(tabId);
  createdTabs.delete(tabId);
  tabMetadata.delete(Number(tabId));
  popupEventCounts.delete(tabId);
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

function externalMessageOrigin(sender) {
  if (sender && sender.origin) {
    return sender.origin;
  }
  if (sender && sender.url) {
    try {
      return new URL(sender.url).origin;
    } catch (error) {
      return "";
    }
  }
  return "";
}

function isLocalQwenPawExternalOrigin(origin) {
  try {
    const parsed = new URL(origin);
    return (
      parsed.protocol === "http:" &&
      LOCAL_QWENPAW_HOSTS.has(parsed.hostname)
    );
  } catch (error) {
    return false;
  }
}

function handleExternalMessage(message, sender, sendResponse) {
  if (!isLocalQwenPawExternalOrigin(externalMessageOrigin(sender))) {
    sendResponse({ ok: false, error: "origin_not_allowed" });
    return false;
  }

  switch (message && message.method) {
    case "status.get":
      sendResponse(extensionStatusPayload());
      return false;
    case "bridge.connect":
      if (!nmPort) {
        connectNative();
      }
      sendResponse(extensionStatusPayload());
      return false;
    case "extension.reload":
      sendResponse({
        ok: true,
        reloading: true,
        version: chrome.runtime.getManifest().version,
      });
      setTimeout(() => chrome.runtime.reload(), 0);
      return false;
    default:
      sendResponse({ ok: false, error: "method_not_allowed" });
      return false;
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message && message.source === "qwenpaw-browser-bridge-popup") {
    if (message.method === "status.get") {
      if (!nmPort) {
        connectNative();
      }
      sendResponse(extensionStatusPayload());
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

chrome.runtime.onMessageExternal.addListener(handleExternalMessage);

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
  if (hasControlInterest() && !nmPort) {
    await cleanupOrphans("startup");
  }
  connectNative();
}

initialize();

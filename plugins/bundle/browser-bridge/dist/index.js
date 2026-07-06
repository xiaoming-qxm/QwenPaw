const V = {
  en: {
    routeLabel: "Browser Bridge",
    pageTitle: "Browser Bridge",
    pageSubtitle: "Connect QwenPaw to Chrome through the local browser bridge.",
    loading: "Loading browser bridge status...",
    installCws: "Prepare Local Extension",
    devMode: "I'm a developer - use local loading",
    installed: "Installed",
    connecting: "Connecting",
    connectedStep: "Connected",
    ready: "Ready",
    waitingTitle: "Waiting for Chrome to connect",
    waitingMessage: "Open or reload the QwenPaw browser extension in Chrome. This page checks the bridge every 3 seconds.",
    refreshStatus: "Refresh Status",
    stillNotConnected: "Still not connected?",
    tipEnable: "Make sure Developer mode is enabled.",
    tipClick: "Click the QwenPaw extension icon in Chrome once.",
    tipReload: "Reload the extension or reopen the target browser tab.",
    versionUnknown: "unknown",
    readyTitle: "Browser Bridge Active",
    version: "Extension version",
    connected: "Connected",
    justNow: "just now",
    minutesAgo: "{count} minutes ago",
    hoursAgo: "{count} hours ago",
    daysAgo: "{count} days ago",
    usageTitle: "What you can do next",
    example1: "Open the current browser page and summarize it.",
    example2: "Click the next actionable button on this page.",
    example3: "Collect the visible product prices into a table.",
    testConnection: "Test Connection",
    testSuccess: "Browser bridge connected",
    testFailed: "Browser bridge is not connected yet",
    developerTitle: "Developer Options",
    installMode: "Install mode",
    extensionDir: "Extension folder",
    nativeManifest: "Native manifest",
    nativeHost: "Native host",
    config: "Bridge config",
    bridgeEndpoint: "Bridge endpoint",
    regenerate: "Regenerate Files",
    reset: "Reset Config",
    unpackedTitle: "Local unpacked loading",
    stepOpen: "Open chrome://extensions and enable Developer mode.",
    stepLoad: "Choose Load unpacked and select the extension folder above.",
    stepVerify: "Return here and refresh; Connected turns green after Chrome connects.",
    installSuccess: "Extension files ready",
    installFailed: "Extension setup failed",
    copy: "Copy",
    copied: "Copied",
    diagnosticsTitle: "SDK diagnostics",
    advancedDiagnosticsTitle: "Advanced Diagnostics",
    diagnosticBackend: "Backend",
    diagnosticAvailable: "Available",
    diagnosticDegraded: "Degraded",
    diagnosticUnavailable: "Unavailable",
    selectedBackend: "Selected backend",
    nativeHostStatus: "Native host",
    buildFreshness: "Build freshness",
    reloadExtension: "Reload extension",
    openChromeExtensions: "Open Chrome Extensions",
    openExtensionFolder: "Open Extension Folder",
    copyPathFallback: "Copy Path",
    connectExtension: "Connect Extension",
    retrySetup: "Retry Setup",
    preparingAction: "Preparing...",
    repairingAction: "Repairing...",
    lifecycleStepPrepare: "Prepare",
    lifecycleStepLoad: "Load in Chrome",
    lifecyclePreparingTitle: "Preparing Browser Bridge",
    lifecyclePreparingDescription: "QwenPaw is checking the local extension files and Native Messaging setup.",
    lifecycleRepairingTitle: "Repairing Local Setup",
    lifecycleRepairingDescription: "QwenPaw is refreshing the unpacked extension and Native Messaging files.",
    lifecycleLoadUnpackedTitle: "Load the Local Extension",
    lifecycleLoadUnpackedDescription: "Open Chrome Extensions, enable Developer mode, then load the prepared extension folder.",
    lifecycleConnectTitle: "Connect the Extension",
    lifecycleConnectDescription: "The extension is loaded. Ask it to reconnect to the local QwenPaw bridge.",
    lifecycleConnectedDescription: "Browser Bridge is connected and ready for local Chrome control.",
    lifecycleFailedTitle: "Setup Needs Attention",
    lifecycleFailedDescription: "The automatic setup did not finish. Retry setup or inspect advanced diagnostics.",
    runSetup: "Run setup",
    restartQwenPaw: "Restart QwenPaw",
    rebuildFrontend: "Rebuild frontend",
    approvalRequired: "Review approval",
    approvalDenied: "Approval was denied",
    loginRequired: "Sign in to the site",
    riskControl: "Review site risk",
    noProgress: "No visible browser progress",
    cleanupComplete: "Cleanup complete",
    acceptanceTitle: "Product Acceptance",
    acceptanceSubtitle: "Run the product verifier and review scenario evidence here.",
    acceptanceRun: "Run Product Acceptance",
    acceptanceCancel: "Cancel Run",
    acceptanceStarted: "Product Acceptance started",
    acceptanceCancelled: "Product Acceptance cancellation requested",
    acceptanceStatus: "Status",
    acceptanceReportLink: "Open report",
    acceptanceTaobaoOptIn: "Include live Taobao scenario",
    acceptanceTaobaoConfirm: "This may touch a live Taobao page. Confirm before running it.",
    acceptanceTaobaoConfirmCheckbox: "I confirm live Taobao opt-in",
    acceptanceFailureCategory: "Failure category",
    acceptanceRepairAction: "Repair action",
    acceptanceRepairOpenSetup: "Open setup page",
    acceptanceRerun: "Rerun acceptance",
    browser_bridge_disconnected: "Reload the extension or reopen the target browser tab.",
    browser_backend_unavailable: "Refresh the status after the backend is available.",
    browser_bridge_action_runtime_missing: "Restart QwenPaw or reload the Browser Bridge plugin.",
    isolated_backend_unavailable: "Install or restart the isolated browser runtime."
  },
  zh: {
    routeLabel: "浏览器桥接",
    pageTitle: "浏览器桥接",
    pageSubtitle: "通过本地浏览器桥接将 QwenPaw 连接到 Chrome。",
    loading: "正在加载浏览器桥接状态...",
    installCws: "准备本地扩展",
    devMode: "我是开发者 - 使用本地加载",
    installed: "已安装",
    connecting: "连接中",
    connectedStep: "已连接",
    ready: "就绪",
    waitingTitle: "等待 Chrome 连接",
    waitingMessage: "请在 Chrome 中打开或重载 QwenPaw 浏览器扩展。本页面会每 3 秒检查一次桥接状态。",
    refreshStatus: "刷新状态",
    stillNotConnected: "仍未连接？",
    tipEnable: "请确认已开启开发者模式。",
    tipClick: "点击一次 Chrome 中的 QwenPaw 扩展图标。",
    tipReload: "重载扩展，或重新打开目标浏览器标签页。",
    versionUnknown: "未知",
    readyTitle: "浏览器桥接已启用",
    version: "扩展版本",
    connected: "连接时间",
    justNow: "刚刚",
    minutesAgo: "{count} 分钟前",
    hoursAgo: "{count} 小时前",
    daysAgo: "{count} 天前",
    usageTitle: "接下来可以做什么",
    example1: "打开当前浏览器页面并总结内容。",
    example2: "点击当前页面中下一个可操作按钮。",
    example3: "把可见的商品价格整理成表格。",
    testConnection: "测试连接",
    testSuccess: "浏览器桥接连接正常",
    testFailed: "浏览器桥接尚未连接",
    developerTitle: "开发者选项",
    installMode: "安装模式",
    extensionDir: "扩展目录",
    nativeManifest: "Native Manifest",
    nativeHost: "Native Host",
    config: "桥接配置",
    bridgeEndpoint: "桥接端点",
    regenerate: "重新生成文件",
    reset: "重置配置",
    unpackedTitle: "本地未打包加载",
    stepOpen: "打开 chrome://extensions 并启用开发者模式。",
    stepLoad: "选择“加载已解压的扩展程序”，并选择上方扩展目录。",
    stepVerify: "回到此页面并刷新；Chrome 连接后状态会变为就绪。",
    installSuccess: "扩展文件已准备好",
    installFailed: "扩展设置失败",
    copy: "复制",
    copied: "已复制",
    diagnosticsTitle: "SDK 诊断",
    advancedDiagnosticsTitle: "高级诊断",
    diagnosticBackend: "后端",
    diagnosticAvailable: "可用",
    diagnosticDegraded: "降级",
    diagnosticUnavailable: "不可用",
    selectedBackend: "选中的后端",
    nativeHostStatus: "Native Host",
    buildFreshness: "构建新鲜度",
    reloadExtension: "重载扩展",
    openChromeExtensions: "打开 Chrome 扩展管理",
    openExtensionFolder: "打开扩展文件夹",
    copyPathFallback: "复制路径",
    connectExtension: "连接扩展",
    retrySetup: "重试设置",
    preparingAction: "准备中...",
    repairingAction: "修复中...",
    lifecycleStepPrepare: "准备",
    lifecycleStepLoad: "在 Chrome 中加载",
    lifecyclePreparingTitle: "正在准备浏览器桥接",
    lifecyclePreparingDescription: "QwenPaw 正在检查本地扩展文件和 Native Messaging 设置。",
    lifecycleRepairingTitle: "正在修复本地设置",
    lifecycleRepairingDescription: "QwenPaw 正在刷新未打包扩展和 Native Messaging 文件。",
    lifecycleLoadUnpackedTitle: "加载本地扩展",
    lifecycleLoadUnpackedDescription: "打开 Chrome 扩展管理，启用开发者模式，然后加载已准备好的扩展文件夹。",
    lifecycleConnectTitle: "连接扩展",
    lifecycleConnectDescription: "扩展已经加载。请让扩展重新连接到本地 QwenPaw 桥接。",
    lifecycleConnectedDescription: "浏览器桥接已连接，可以控制本地 Chrome。",
    lifecycleFailedTitle: "设置需要处理",
    lifecycleFailedDescription: "自动设置未完成。请重试设置，或查看高级诊断。",
    runSetup: "运行设置",
    restartQwenPaw: "重启 QwenPaw",
    rebuildFrontend: "重新构建前端",
    approvalRequired: "查看审批",
    approvalDenied: "审批已拒绝",
    loginRequired: "先登录目标网站",
    riskControl: "检查网站风险控制",
    noProgress: "浏览器没有可见进展",
    cleanupComplete: "清理已完成",
    acceptanceTitle: "产品验收",
    acceptanceSubtitle: "运行产品 verifier，并在这里查看场景证据。",
    acceptanceRun: "运行产品验收",
    acceptanceCancel: "取消运行",
    acceptanceStarted: "产品验收已开始",
    acceptanceCancelled: "已请求取消产品验收",
    acceptanceStatus: "状态",
    acceptanceReportLink: "打开报告",
    acceptanceTaobaoOptIn: "包含淘宝 live 场景",
    acceptanceTaobaoConfirm: "这可能会触碰真实淘宝页面。运行前需要明确确认。",
    acceptanceTaobaoConfirmCheckbox: "我确认启用淘宝 live",
    acceptanceFailureCategory: "失败分类",
    acceptanceRepairAction: "修复动作",
    acceptanceRepairOpenSetup: "打开设置页",
    acceptanceRerun: "重新运行验收",
    browser_bridge_disconnected: "重载扩展，或重新打开目标浏览器标签页。",
    browser_backend_unavailable: "后端可用后刷新状态。",
    browser_bridge_action_runtime_missing: "重启 QwenPaw，或重新加载 Browser Bridge 插件。",
    isolated_backend_unavailable: "安装或重启隔离浏览器运行时。"
  }
};
function ae() {
  var e;
  try {
    return ((e = window.localStorage) == null ? void 0 : e.getItem("language")) ?? null;
  } catch {
    return null;
  }
}
function G(e = ae()) {
  return String(e || "").trim().split("-")[0].toLowerCase() === "zh" ? "zh" : "en";
}
function i(e, r, t) {
  let a = V[e][r] ?? V.en[r];
  if (t)
    for (const [l, s] of Object.entries(t))
      a = a.split(`{${l}}`).join(String(s));
  return a;
}
const I = window.QwenPaw.host, n = I.React, oe = I.antd, ce = I.getApiUrl, U = I.getApiToken, {
  Alert: j,
  Button: y,
  Card: z,
  Checkbox: q,
  Collapse: le,
  Space: O,
  Spin: se,
  Steps: de,
  Typography: pe,
  message: h
} = oe, { Paragraph: ue, Text: u, Title: X } = pe, p = {
  page: {
    display: "flex",
    flexDirection: "column",
    height: "100%",
    minHeight: 0,
    overflow: "hidden"
  },
  header: {
    padding: "16px 20px 12px",
    borderBottom: "1px solid rgba(0,0,0,0.06)"
  },
  headerTitleRow: {
    display: "flex",
    alignItems: "center",
    gap: 12
  },
  headerIcon: {
    width: 44,
    height: 44,
    borderRadius: 12,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
    background: "#fff",
    border: "1px solid rgba(0,0,0,0.12)",
    color: "rgba(0,0,0,0.78)"
  },
  headerText: {
    minWidth: 0
  },
  content: {
    flex: 1,
    minHeight: 0,
    overflowY: "auto",
    padding: 16,
    display: "flex",
    flexDirection: "column",
    gap: 16
  },
  centeredCard: {
    width: "min(100%, 720px)",
    margin: "0 auto",
    borderRadius: 8
  },
  iconCircle: {
    width: 64,
    height: 64,
    borderRadius: "50%",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 12,
    background: "#fff",
    border: "1px solid rgba(0,0,0,0.12)",
    color: "rgba(0,0,0,0.78)"
  },
  successCircle: {
    width: 64,
    height: 64,
    borderRadius: "50%",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 12,
    color: "#389e0d",
    background: "rgba(82, 196, 26, 0.12)",
    fontSize: 30,
    fontWeight: 700
  },
  progressBody: {
    textAlign: "center",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 8,
    margin: "22px 0"
  },
  readyMeta: {
    margin: "18px 0 20px",
    display: "flex",
    justifyContent: "center",
    gap: 16,
    flexWrap: "wrap"
  },
  acceptancePanel: {
    width: "min(100%, 720px)",
    margin: "0 auto",
    borderRadius: 8
  },
  acceptanceActions: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 8
  },
  acceptanceScenarioList: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
    gap: 10
  },
  acceptanceScenarioCard: {
    minHeight: 124,
    padding: 12,
    borderRadius: 8,
    border: "1px solid rgba(0,0,0,0.08)",
    background: "#fff",
    display: "flex",
    flexDirection: "column",
    gap: 6
  },
  acceptanceScenarioHeader: {
    display: "flex",
    justifyContent: "space-between",
    gap: 8
  },
  acceptanceReportPreview: {
    maxHeight: 180,
    overflow: "auto",
    padding: 12,
    borderRadius: 6,
    background: "rgba(0,0,0,0.04)",
    whiteSpace: "pre-wrap"
  },
  developerPanel: {
    width: "min(100%, 920px)",
    margin: "0 auto",
    borderRadius: 8,
    overflow: "hidden"
  },
  developerContent: {
    display: "flex",
    flexDirection: "column",
    gap: 16
  },
  modeRow: {
    display: "grid",
    gridTemplateColumns: "minmax(128px, 180px) minmax(0, 1fr)",
    alignItems: "center",
    gap: 8
  },
  pathList: {
    display: "flex",
    flexDirection: "column",
    gap: 10
  },
  pathRow: {
    display: "grid",
    gridTemplateColumns: "minmax(128px, 180px) minmax(0, 1fr) auto",
    alignItems: "center",
    gap: 8
  },
  pathValue: {
    minWidth: 0,
    overflowWrap: "anywhere",
    wordBreak: "break-word",
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    fontSize: 12,
    lineHeight: 1.45,
    background: "rgba(0,0,0,0.04)",
    border: "1px solid rgba(0,0,0,0.06)",
    borderRadius: 4,
    padding: "4px 8px"
  },
  developerActions: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    flexWrap: "wrap"
  },
  unpackedSteps: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
    padding: 12,
    border: "1px solid rgba(0,0,0,0.06)",
    borderRadius: 8,
    background: "rgba(0,0,0,0.02)"
  },
  diagnosticsPanel: {
    width: "min(100%, 720px)",
    margin: "0 auto",
    borderRadius: 8
  },
  diagnosticsList: {
    display: "flex",
    flexDirection: "column",
    gap: 10
  },
  diagnosticRow: {
    display: "grid",
    gridTemplateColumns: "minmax(140px, 1fr) minmax(0, 2fr)",
    gap: 10,
    padding: 10,
    border: "1px solid rgba(0,0,0,0.06)",
    borderRadius: 8,
    background: "rgba(0,0,0,0.02)"
  },
  diagnosticCode: {
    display: "inline-block",
    maxWidth: "100%",
    overflowWrap: "anywhere",
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    fontSize: 12,
    borderRadius: 4,
    padding: "2px 6px",
    background: "rgba(0,0,0,0.05)",
    color: "rgba(0,0,0,0.76)"
  },
  diagnosticMessage: {
    display: "flex",
    minWidth: 0,
    flexDirection: "column",
    gap: 4
  }
};
function ge() {
  const e = {}, r = U == null ? void 0 : U();
  return r && (e.Authorization = `Bearer ${r}`), e;
}
async function T(e, r) {
  const t = await fetch(ce(e), {
    ...r,
    headers: {
      ...(r == null ? void 0 : r.headers) || {},
      ...ge()
    }
  }), a = await t.text(), l = a ? JSON.parse(a) : null;
  if (!t.ok)
    throw new Error(
      typeof (l == null ? void 0 : l.detail) == "string" ? l.detail : t.statusText
    );
  return l;
}
function K() {
  return T("/browser-bridge/status");
}
function J(e) {
  return T("/browser-bridge/setup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(e)
  });
}
function fe() {
  return T(
    "/browser-bridge/open-chrome-extensions",
    {
      method: "POST"
    }
  );
}
function me() {
  return T(
    "/browser-bridge/open-extension-folder",
    {
      method: "POST"
    }
  );
}
function be(e) {
  const r = { live_taobao: !1 };
  return T("/browser-bridge/acceptance-runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...ve(),
      ...r,
      ...e
    })
  });
}
function he(e) {
  return T(`/browser-bridge/acceptance-runs/${e}`);
}
function ye(e) {
  return T(
    `/browser-bridge/acceptance-runs/${e}/cancel`,
    {
      method: "POST"
    }
  );
}
function we(e) {
  return T(
    `/browser-bridge/acceptance-runs/${e}/report`
  );
}
function ve() {
  const e = `${window.location.protocol}//${window.location.host}`, r = Number(window.location.port);
  return {
    base_url: e,
    ...Number.isFinite(r) && r > 0 ? { port: r } : {}
  };
}
function W() {
  return `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws/browser-bridge`;
}
function xe(e) {
  return e ? !e.installed || e.recommended_action === "setup_extension" || e.setup_phase === "setup_missing" || e.setup_phase === "native_host_repair_required" || e.setup_phase === "stale_build" : !1;
}
function _e(e) {
  var r;
  return e ? e.setup_phase === "native_host_repair_required" || ((r = e.native_host_status) == null ? void 0 : r.status) === "repair_required" : !1;
}
function Ee(e, r, t, a) {
  return e != null && e.connected ? "connected" : r != null && r.ok ? "extension_loaded_bridge_disconnected" : e != null && e.installed ? "needs_load_unpacked" : t ? "preparing" : "failed_actionable";
}
function A(e, r) {
  return !e || typeof chrome > "u" || !chrome.runtime || !chrome.runtime.sendMessage ? Promise.resolve(null) : new Promise((t) => {
    chrome.runtime.sendMessage(e, { method: r }, (a) => {
      var s, b;
      const l = (b = (s = chrome.runtime) == null ? void 0 : s.lastError) == null ? void 0 : b.message;
      if (l) {
        t({ ok: !1, error: l });
        return;
      }
      t(a || null);
    });
  });
}
const Ce = /* @__PURE__ */ new Set([
  "browser_bridge_disconnected",
  "browser_backend_unavailable",
  "browser_bridge_action_runtime_missing",
  "isolated_backend_unavailable"
]);
function ke(e) {
  var r;
  return (((r = e == null ? void 0 : e.sdk_diagnostics) == null ? void 0 : r.backends) ?? []).filter(
    (t) => t.code || t.status !== "available"
  );
}
function Se(e, r) {
  const t = e.hint_key || e.code;
  return t && Ce.has(t) ? i(r, t) : e.message_fallback || e.message || e.reason || e.code || e.backend_id;
}
function Re(e, r) {
  return e === "available" ? i(r, "diagnosticAvailable") : e === "degraded" ? i(r, "diagnosticDegraded") : i(r, "diagnosticUnavailable");
}
function Te(e) {
  return Array.isArray(e) ? e : e ? [String(e)] : [];
}
function ee({ size: e = 38 }) {
  return /* @__PURE__ */ n.createElement(
    "svg",
    {
      "aria-hidden": "true",
      fill: "none",
      focusable: "false",
      height: e,
      style: { display: "block" },
      viewBox: "0 0 38 38",
      width: e
    },
    /* @__PURE__ */ n.createElement(
      "rect",
      {
        fill: "none",
        height: "25",
        rx: "6",
        stroke: "currentColor",
        strokeWidth: "2",
        width: "30",
        x: "4",
        y: "6"
      }
    ),
    /* @__PURE__ */ n.createElement("path", { d: "M4 13H34", stroke: "currentColor", strokeWidth: "2" }),
    /* @__PURE__ */ n.createElement("circle", { cx: "9", cy: "9.5", fill: "currentColor", r: "1.2" }),
    /* @__PURE__ */ n.createElement("circle", { cx: "13", cy: "9.5", fill: "currentColor", opacity: "0.62", r: "1.2" }),
    /* @__PURE__ */ n.createElement(
      "path",
      {
        d: "M18.5 17.5L29.5 22.1L24.8 24L28 30.1L25.3 31.5L22.1 25.5L18.5 29.2V17.5Z",
        fill: "currentColor"
      }
    )
  );
}
function Pe({
  locale: e,
  status: r
}) {
  const t = ke(r);
  return t.length ? /* @__PURE__ */ n.createElement(z, { style: p.diagnosticsPanel }, /* @__PURE__ */ n.createElement(O, { direction: "vertical", size: 12, style: { width: "100%" } }, /* @__PURE__ */ n.createElement(u, { strong: !0 }, i(e, "diagnosticsTitle")), /* @__PURE__ */ n.createElement("div", { style: p.diagnosticsList }, t.map((a) => /* @__PURE__ */ n.createElement(
    "div",
    {
      key: `${a.backend_id}:${a.code || a.status}`,
      style: p.diagnosticRow
    },
    /* @__PURE__ */ n.createElement("div", null, /* @__PURE__ */ n.createElement(u, { strong: !0 }, a.backend_id), /* @__PURE__ */ n.createElement("br", null), /* @__PURE__ */ n.createElement(u, { type: "secondary" }, Re(a.status, e))),
    /* @__PURE__ */ n.createElement("div", { style: p.diagnosticMessage }, a.code ? /* @__PURE__ */ n.createElement("code", { style: p.diagnosticCode }, a.code) : null, /* @__PURE__ */ n.createElement(u, null, Se(a, e)))
  ))))) : null;
}
function Le() {
  return /* @__PURE__ */ n.createElement(
    "span",
    {
      style: {
        display: "inline-block",
        filter: "grayscale(1) contrast(1.08)",
        lineHeight: 1,
        WebkitFilter: "grayscale(1) contrast(1.08)"
      }
    },
    "🌐"
  );
}
function De(e, r) {
  if (!e)
    return i(r, "justNow");
  const t = new Date(e).getTime();
  if (Number.isNaN(t))
    return i(r, "justNow");
  const a = Math.max(0, Math.floor((Date.now() - t) / 1e3));
  if (a < 60)
    return i(r, "justNow");
  const l = Math.floor(a / 60);
  if (l < 60)
    return i(r, "minutesAgo", { count: l });
  const s = Math.floor(l / 60);
  return s < 24 ? i(r, "hoursAgo", { count: s }) : i(r, "daysAgo", { count: Math.floor(s / 24) });
}
function Ae(e) {
  return e === "preparing" ? "lifecyclePreparingTitle" : e === "repairing" ? "lifecycleRepairingTitle" : e === "needs_load_unpacked" ? "lifecycleLoadUnpackedTitle" : e === "extension_loaded_bridge_disconnected" ? "lifecycleConnectTitle" : e === "connected" ? "readyTitle" : "lifecycleFailedTitle";
}
function Be(e) {
  return e === "preparing" ? "lifecyclePreparingDescription" : e === "repairing" ? "lifecycleRepairingDescription" : e === "needs_load_unpacked" ? "lifecycleLoadUnpackedDescription" : e === "extension_loaded_bridge_disconnected" ? "lifecycleConnectDescription" : e === "connected" ? "lifecycleConnectedDescription" : "lifecycleFailedDescription";
}
function Fe(e) {
  return e === "connected" ? 2 : e === "needs_load_unpacked" || e === "extension_loaded_bridge_disconnected" ? 1 : 0;
}
function Me({
  error: e,
  locale: r,
  primaryAction: t,
  state: a,
  status: l
}) {
  const s = (l == null ? void 0 : l.version) || i(r, "versionUnknown"), b = De(l == null ? void 0 : l.connected_since, r);
  return /* @__PURE__ */ n.createElement(z, { style: p.centeredCard }, /* @__PURE__ */ n.createElement(
    de,
    {
      size: "small",
      current: Fe(a),
      items: [
        {
          title: i(r, "lifecycleStepPrepare"),
          status: a === "failed_actionable" ? "error" : "finish"
        },
        {
          title: i(r, "lifecycleStepLoad"),
          status: a === "needs_load_unpacked" || a === "extension_loaded_bridge_disconnected" ? "process" : a === "connected" ? "finish" : "wait"
        },
        {
          title: i(r, "ready"),
          status: a === "connected" ? "finish" : "wait"
        }
      ]
    }
  ), /* @__PURE__ */ n.createElement("div", { style: p.progressBody }, a === "connected" ? /* @__PURE__ */ n.createElement("div", { style: p.successCircle }, "✓") : /* @__PURE__ */ n.createElement("div", { style: p.iconCircle }, /* @__PURE__ */ n.createElement(ee, null)), /* @__PURE__ */ n.createElement(X, { level: 3 }, i(r, Ae(a))), /* @__PURE__ */ n.createElement(ue, { type: "secondary" }, i(r, Be(a))), e ? /* @__PURE__ */ n.createElement(u, { type: "danger" }, e) : null, a === "connected" ? /* @__PURE__ */ n.createElement("div", { style: p.readyMeta }, /* @__PURE__ */ n.createElement(u, null, i(r, "version"), ": ", s), /* @__PURE__ */ n.createElement(u, null, i(r, "connected"), ": ", b)) : null, /* @__PURE__ */ n.createElement(
    y,
    {
      type: "primary",
      size: "large",
      disabled: t.disabled,
      loading: t.loading,
      onClick: t.onClick
    },
    i(r, t.label)
  )), l != null && l.recovery_copy && a !== "connected" ? /* @__PURE__ */ n.createElement(
    j,
    {
      showIcon: !0,
      type: a === "failed_actionable" ? "error" : "info",
      message: l.recovery_copy
    }
  ) : null);
}
function Oe({
  locale: e,
  activeKey: r,
  loading: t,
  pathRows: a,
  setupLoading: l,
  status: s,
  onChange: b,
  onCopy: v,
  onOpenChromeExtensions: w,
  onOpenExtensionFolder: S,
  onRegenerate: x,
  onReloadExtension: _,
  onReset: E
}) {
  const R = (s == null ? void 0 : s.ws_url) || W();
  return /* @__PURE__ */ n.createElement(
    le,
    {
      activeKey: r,
      style: p.developerPanel,
      onChange: b,
      items: [
        {
          key: "developer",
          label: /* @__PURE__ */ n.createElement(O, { size: 8 }, i(e, "advancedDiagnosticsTitle")),
          children: /* @__PURE__ */ n.createElement(se, { spinning: t && !s }, /* @__PURE__ */ n.createElement("div", { style: p.developerContent }, /* @__PURE__ */ n.createElement("div", { style: p.modeRow }, /* @__PURE__ */ n.createElement(u, { type: "secondary" }, i(e, "installMode")), /* @__PURE__ */ n.createElement(u, null, (s == null ? void 0 : s.install_mode) || "-")), /* @__PURE__ */ n.createElement("div", { style: p.pathList }, a.map(({ key: g, label: C }) => {
            const P = (s == null ? void 0 : s[g]) || "-";
            return /* @__PURE__ */ n.createElement("div", { style: p.pathRow, key: g }, /* @__PURE__ */ n.createElement(u, { type: "secondary" }, C), /* @__PURE__ */ n.createElement("code", { style: p.pathValue }, P), /* @__PURE__ */ n.createElement(
              y,
              {
                disabled: !(s != null && s[g]),
                onClick: () => v(P),
                "aria-label": i(e, "copyPathFallback")
              },
              i(e, "copyPathFallback")
            ));
          }), /* @__PURE__ */ n.createElement("div", { style: p.pathRow }, /* @__PURE__ */ n.createElement(u, { type: "secondary" }, i(e, "bridgeEndpoint")), /* @__PURE__ */ n.createElement("code", { style: p.pathValue }, R), /* @__PURE__ */ n.createElement(
            y,
            {
              onClick: () => v(R),
              "aria-label": i(e, "copyPathFallback")
            },
            i(e, "copyPathFallback")
          ))), /* @__PURE__ */ n.createElement("div", { style: p.developerActions }, /* @__PURE__ */ n.createElement(y, { onClick: w }, i(e, "openChromeExtensions")), /* @__PURE__ */ n.createElement(y, { onClick: S }, i(e, "openExtensionFolder")), /* @__PURE__ */ n.createElement(y, { onClick: _ }, i(e, "reloadExtension")), /* @__PURE__ */ n.createElement(y, { loading: l, onClick: x }, i(e, "regenerate")), /* @__PURE__ */ n.createElement(y, { loading: l, onClick: E }, i(e, "reset"))), /* @__PURE__ */ n.createElement("div", { style: p.unpackedSteps }, /* @__PURE__ */ n.createElement(u, { strong: !0 }, i(e, "unpackedTitle")), /* @__PURE__ */ n.createElement("ol", null, /* @__PURE__ */ n.createElement("li", null, i(e, "stepOpen")), /* @__PURE__ */ n.createElement("li", null, i(e, "stepLoad")), /* @__PURE__ */ n.createElement("li", null, i(e, "stepVerify"))))))
        }
      ]
    }
  );
}
const Ie = /* @__PURE__ */ new Set([
  "passed",
  "failed",
  "blocked",
  "cancelled"
]);
function M(e) {
  return Ie.has(e || "");
}
function Ne(e, r) {
  return r === "open_setup_page" || r === "run_setup" ? i(e, "acceptanceRepairOpenSetup") : r === "open_chrome_extensions" ? i(e, "openChromeExtensions") : r === "open_extension_folder" ? i(e, "openExtensionFolder") : r === "connect_extension" ? i(e, "connectExtension") : r === "reload_extension" ? i(e, "reloadExtension") : r === "rerun_after_fix" || r === "rerun_acceptance" ? i(e, "acceptanceRerun") : `${i(e, "acceptanceRepairAction")}: ${r}`;
}
function Qe({
  locale: e,
  onRepairAction: r
}) {
  var B;
  const [t, a] = n.useState(null), [l, s] = n.useState(null), [b, v] = n.useState(!1), [w, S] = n.useState(!1), [x, _] = n.useState(!1), E = n.useCallback(async (c) => {
    const m = await we(c);
    s(m);
  }, []), R = n.useCallback(
    async (c) => {
      const m = await he(c);
      return a(m), M(m.status) && await E(c), m;
    },
    [E]
  ), g = n.useCallback(async () => {
    v(!0), s(null);
    try {
      const m = await be(
        w && x ? { live_taobao: !0 } : { live_taobao: !1 }
      );
      a(m), M(m.status) && await E(m.run_id), h.success(i(e, "acceptanceStarted"));
    } catch (c) {
      h.error(c instanceof Error ? c.message : String(c));
    } finally {
      v(!1);
    }
  }, [E, e, x, w]), C = n.useCallback(async () => {
    if (t) {
      v(!0);
      try {
        const c = await ye(t.run_id);
        a(c), h.success(i(e, "acceptanceCancelled"));
      } catch (c) {
        h.error(c instanceof Error ? c.message : String(c));
      } finally {
        v(!1);
      }
    }
  }, [t, e]);
  n.useEffect(() => {
    if (!(t != null && t.run_id) || M(t.status))
      return;
    const c = window.setInterval(() => {
      R(t.run_id);
    }, 2e3);
    return () => {
      window.clearInterval(c);
    };
  }, [t == null ? void 0 : t.run_id, t == null ? void 0 : t.status, R]);
  const P = (B = t == null ? void 0 : t.scenario_progress) != null && B.length ? t.scenario_progress : (l == null ? void 0 : l.json.scenario_reports) || [], L = !!(t && !M(t.status)), f = w && !x, N = (c) => {
    if (c) {
      if (c === "rerun_after_fix" || c === "rerun_acceptance") {
        g();
        return;
      }
      r(c);
    }
  };
  return /* @__PURE__ */ n.createElement(z, { style: p.acceptancePanel }, /* @__PURE__ */ n.createElement(O, { direction: "vertical", size: 14, style: { width: "100%" } }, /* @__PURE__ */ n.createElement("div", null, /* @__PURE__ */ n.createElement(u, { strong: !0 }, i(e, "acceptanceTitle")), /* @__PURE__ */ n.createElement("br", null), /* @__PURE__ */ n.createElement(u, { type: "secondary" }, i(e, "acceptanceSubtitle"))), /* @__PURE__ */ n.createElement("div", { style: p.acceptanceActions }, /* @__PURE__ */ n.createElement(
    y,
    {
      type: "primary",
      loading: b,
      disabled: f || L,
      onClick: () => void g()
    },
    i(e, "acceptanceRun")
  ), /* @__PURE__ */ n.createElement(
    y,
    {
      disabled: !L,
      loading: b && L,
      onClick: () => void C()
    },
    i(e, "acceptanceCancel")
  ), t ? /* @__PURE__ */ n.createElement(
    y,
    {
      type: "link",
      onClick: () => void E(t.run_id)
    },
    i(e, "acceptanceReportLink")
  ) : null), /* @__PURE__ */ n.createElement(O, { direction: "vertical", size: 8, style: { width: "100%" } }, /* @__PURE__ */ n.createElement(
    q,
    {
      checked: w,
      onChange: (c) => {
        S(c.target.checked), c.target.checked || _(!1);
      }
    },
    i(e, "acceptanceTaobaoOptIn")
  ), w ? /* @__PURE__ */ n.createElement(
    j,
    {
      showIcon: !0,
      type: "warning",
      message: i(e, "acceptanceTaobaoConfirm"),
      action: /* @__PURE__ */ n.createElement(
        q,
        {
          checked: x,
          onChange: (c) => _(c.target.checked)
        },
        i(e, "acceptanceTaobaoConfirmCheckbox")
      )
    }
  ) : null), t ? /* @__PURE__ */ n.createElement(u, null, i(e, "acceptanceStatus"), ": ", t.status) : null, P.length ? /* @__PURE__ */ n.createElement("div", { style: p.acceptanceScenarioList }, P.map((c) => /* @__PURE__ */ n.createElement(
    "div",
    {
      key: c.scenario,
      style: p.acceptanceScenarioCard
    },
    /* @__PURE__ */ n.createElement("div", { style: p.acceptanceScenarioHeader }, /* @__PURE__ */ n.createElement(u, { strong: !0 }, c.scenario), /* @__PURE__ */ n.createElement(u, null, c.status)),
    c.failure_category ? /* @__PURE__ */ n.createElement(u, { type: "secondary" }, i(e, "acceptanceFailureCategory"), ":", " ", c.failure_category) : null,
    c.recovery_hint ? /* @__PURE__ */ n.createElement(u, null, c.recovery_hint) : null,
    c.repair_action ? /* @__PURE__ */ n.createElement(
      y,
      {
        size: "small",
        onClick: () => N(c.repair_action)
      },
      Ne(
        e,
        c.repair_action
      )
    ) : null
  ))) : null, l != null && l.markdown ? /* @__PURE__ */ n.createElement("pre", { style: p.acceptanceReportPreview }, l.markdown) : null));
}
function He() {
  const e = G(), r = n.useRef(null), [t, a] = n.useState(null), [l, s] = n.useState(null), [b, v] = n.useState(!0), [w, S] = n.useState(!1), [x, _] = n.useState(null), [E, R] = n.useState(
    []
  ), [g, C] = n.useState("preparing"), P = n.useMemo(
    () => [
      {
        key: "extension_dir",
        label: i(e, "extensionDir")
      },
      {
        key: "native_manifest_path",
        label: i(e, "nativeManifest")
      },
      {
        key: "native_host_path",
        label: i(e, "nativeHost")
      },
      {
        key: "config_path",
        label: i(e, "config")
      }
    ],
    [e]
  ), L = n.useCallback(
    async (o) => {
      var D;
      const d = await A(
        o.extension_id,
        "status.get"
      );
      if (s(d), !(d != null && d.ok))
        return d;
      if (o.setup_phase === "stale_build" || ((D = o.build_freshness) == null ? void 0 : D.status) === "stale") {
        const k = await A(
          o.extension_id,
          "extension.reload"
        );
        return s(k || d), k || d;
      }
      if (!o.connected) {
        const k = await A(
          o.extension_id,
          "bridge.connect"
        );
        return s(k || d), k || d;
      }
      return d;
    },
    []
  ), f = n.useCallback(
    async (o = {}) => {
      v(!0), _(null), C(
        (d) => d === "connected" ? d : "preparing"
      );
      try {
        let d = await K();
        a(d), o.autoPrepare && xe(d) && (C("repairing"), S(!0), d = await J({
          install_mode: "unpacked",
          reset: _e(d),
          ws_url: W()
        }), a(d), h.success(i(e, "installSuccess")));
        const D = await L(d), k = await K();
        return a(k), C(Ee(k, D, !1, null)), k;
      } catch (d) {
        const D = d instanceof Error ? d.message : String(d);
        return _(D), C("failed_actionable"), h.error(i(e, "installFailed")), null;
      } finally {
        S(!1), v(!1);
      }
    },
    [e, L]
  );
  n.useEffect(() => {
    f({ autoPrepare: !0 });
  }, [f]), n.useEffect(() => {
    if (g !== "needs_load_unpacked" && g !== "extension_loaded_bridge_disconnected")
      return;
    const o = window.setInterval(() => {
      f();
    }, 3e3);
    return () => {
      window.clearInterval(o);
    };
  }, [g, f]);
  const N = async (o) => {
    var d;
    await ((d = navigator.clipboard) == null ? void 0 : d.writeText(o)), h.success(i(e, "copied"));
  }, B = () => {
    R(["developer"]), window.setTimeout(() => {
      var o;
      (o = r.current) == null || o.scrollIntoView({
        behavior: "smooth",
        block: "start"
      });
    }, 0);
  }, c = (o) => {
    R(Te(o));
  }, m = n.useCallback(async () => {
    const o = await fe();
    !o.opened && o.error && h.warning(o.error);
  }, []), Q = n.useCallback(async () => {
    const o = await me();
    !o.opened && o.error && h.warning(o.error);
  }, []), F = n.useCallback(async () => {
    const o = await A(t == null ? void 0 : t.extension_id, "bridge.connect");
    s(o), await f();
  }, [f, t == null ? void 0 : t.extension_id]), H = n.useCallback(async () => {
    const o = await A(
      t == null ? void 0 : t.extension_id,
      "extension.reload"
    );
    s(o), await f();
  }, [f, t == null ? void 0 : t.extension_id]), $ = n.useCallback(
    async (o) => {
      S(!0), _(null);
      try {
        const d = await J({
          install_mode: "unpacked",
          reset: o,
          ws_url: W()
        });
        a(d), h.success(i(e, "installSuccess")), await f();
      } catch (d) {
        _(d instanceof Error ? d.message : String(d)), C("failed_actionable"), h.error(i(e, "installFailed"));
      } finally {
        S(!1);
      }
    },
    [e, f]
  ), ne = n.useCallback(
    (o) => {
      if (o === "open_setup_page" || o === "setup_extension" || o === "run_setup") {
        B(), f({ autoPrepare: !0 });
        return;
      }
      if (o === "open_chrome_extensions") {
        m();
        return;
      }
      if (o === "open_extension_folder") {
        Q();
        return;
      }
      if (o === "connect_extension") {
        F();
        return;
      }
      if (o === "reload_extension") {
        H();
        return;
      }
      h.info(o);
    },
    [
      F,
      m,
      Q,
      H,
      f
    ]
  ), te = n.useMemo(() => {
    const o = b || w;
    return g === "needs_load_unpacked" ? {
      label: "openChromeExtensions",
      loading: !1,
      onClick: () => void m()
    } : g === "extension_loaded_bridge_disconnected" ? {
      label: "connectExtension",
      loading: o,
      onClick: () => void F()
    } : g === "connected" ? {
      label: "refreshStatus",
      loading: b,
      onClick: () => void f()
    } : g === "failed_actionable" ? {
      label: "retrySetup",
      loading: o,
      onClick: () => void f({ autoPrepare: !0 })
    } : {
      disabled: !0,
      label: g === "repairing" ? "repairingAction" : "preparingAction",
      loading: !0,
      onClick: () => {
      }
    };
  }, [
    F,
    m,
    g,
    b,
    f,
    w
  ]), re = /* @__PURE__ */ n.createElement(
    Me,
    {
      error: x,
      locale: e,
      primaryAction: te,
      state: g,
      status: t
    }
  ), ie = g === "connected" && (t == null ? void 0 : t.connected) === !0;
  return /* @__PURE__ */ n.createElement("div", { style: p.page }, /* @__PURE__ */ n.createElement("div", { style: p.header }, /* @__PURE__ */ n.createElement("div", { style: p.headerTitleRow }, /* @__PURE__ */ n.createElement("div", { style: p.headerIcon }, /* @__PURE__ */ n.createElement(ee, null)), /* @__PURE__ */ n.createElement("div", { style: p.headerText }, /* @__PURE__ */ n.createElement(X, { level: 3, style: { margin: 0 } }, i(e, "pageTitle")), /* @__PURE__ */ n.createElement(u, { type: "secondary" }, i(e, "pageSubtitle"))))), /* @__PURE__ */ n.createElement("div", { style: p.content }, x ? /* @__PURE__ */ n.createElement(j, { type: "error", showIcon: !0, message: x }) : null, re, ie ? /* @__PURE__ */ n.createElement(
    Qe,
    {
      locale: e,
      onRepairAction: ne
    }
  ) : null, /* @__PURE__ */ n.createElement(Pe, { locale: e, status: t }), /* @__PURE__ */ n.createElement("div", { ref: r }, /* @__PURE__ */ n.createElement(
    Oe,
    {
      activeKey: E,
      loading: b,
      locale: e,
      onChange: c,
      onCopy: (o) => void N(o),
      onOpenChromeExtensions: () => void m(),
      onOpenExtensionFolder: () => void Q(),
      onRegenerate: () => void $(!1),
      onReloadExtension: () => void H(),
      onReset: () => void $(!0),
      pathRows: P,
      setupLoading: w,
      status: t
    }
  ))));
}
const Ue = G();
var Y, Z;
(Z = (Y = window.QwenPaw).registerRoutes) == null || Z.call(Y, "browser-bridge", [
  {
    path: "/plugin/browser-bridge",
    component: He,
    label: i(Ue, "routeLabel"),
    icon: /* @__PURE__ */ n.createElement(Le, null),
    priority: 40
  }
]);

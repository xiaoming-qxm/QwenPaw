export type BrowserBridgeLocale = "zh" | "en";

const messages = {
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
    waitingMessage:
      "Open or reload the QwenPaw browser extension in Chrome. This page checks the bridge every 3 seconds.",
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
    stepVerify:
      "Return here and refresh; Connected turns green after Chrome connects.",
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
    lifecyclePreparingDescription:
      "QwenPaw is checking the local extension files and Native Messaging setup.",
    lifecycleRepairingTitle: "Repairing Local Setup",
    lifecycleRepairingDescription:
      "QwenPaw is refreshing the unpacked extension and Native Messaging files.",
    lifecycleLoadUnpackedTitle: "Load the Local Extension",
    lifecycleLoadUnpackedDescription:
      "Open Chrome Extensions, enable Developer mode, then load the prepared extension folder.",
    lifecycleConnectTitle: "Connect the Extension",
    lifecycleConnectDescription:
      "The extension is loaded. Ask it to reconnect to the local QwenPaw bridge.",
    lifecycleConnectedDescription:
      "Browser Bridge is connected and ready for local Chrome control.",
    lifecycleFailedTitle: "Setup Needs Attention",
    lifecycleFailedDescription:
      "The automatic setup did not finish. Retry setup or inspect advanced diagnostics.",
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
    acceptanceSubtitle:
      "Run the product verifier and review scenario evidence here.",
    acceptanceRun: "Run Product Acceptance",
    acceptanceCancel: "Cancel Run",
    acceptanceStarted: "Product Acceptance started",
    acceptanceCancelled: "Product Acceptance cancellation requested",
    acceptanceStatus: "Status",
    acceptanceReportLink: "Open report",
    acceptanceTaobaoOptIn: "Include live Taobao scenario",
    acceptanceTaobaoConfirm:
      "This may touch a live Taobao page. Confirm before running it.",
    acceptanceTaobaoConfirmCheckbox: "I confirm live Taobao opt-in",
    acceptanceFailureCategory: "Failure category",
    acceptanceRepairAction: "Repair action",
    acceptanceRepairOpenSetup: "Open setup page",
    acceptanceRerun: "Rerun acceptance",
    browser_bridge_disconnected:
      "Reload the extension or reopen the target browser tab.",
    browser_backend_unavailable:
      "Refresh the status after the backend is available.",
    browser_bridge_action_runtime_missing:
      "Restart QwenPaw or reload the Browser Bridge plugin.",
    isolated_backend_unavailable:
      "Install or restart the isolated browser runtime.",
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
    waitingMessage:
      "请在 Chrome 中打开或重载 QwenPaw 浏览器扩展。本页面会每 3 秒检查一次桥接状态。",
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
    lifecyclePreparingDescription:
      "QwenPaw 正在检查本地扩展文件和 Native Messaging 设置。",
    lifecycleRepairingTitle: "正在修复本地设置",
    lifecycleRepairingDescription:
      "QwenPaw 正在刷新未打包扩展和 Native Messaging 文件。",
    lifecycleLoadUnpackedTitle: "加载本地扩展",
    lifecycleLoadUnpackedDescription:
      "打开 Chrome 扩展管理，启用开发者模式，然后加载已准备好的扩展文件夹。",
    lifecycleConnectTitle: "连接扩展",
    lifecycleConnectDescription:
      "扩展已经加载。请让扩展重新连接到本地 QwenPaw 桥接。",
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
    browser_bridge_action_runtime_missing:
      "重启 QwenPaw，或重新加载 Browser Bridge 插件。",
    isolated_backend_unavailable: "安装或重启隔离浏览器运行时。",
  },
} as const;

export type MessageKey = keyof typeof messages.en;

export function readConsoleLanguage(): string | null {
  try {
    return window.localStorage?.getItem("language") ?? null;
  } catch {
    return null;
  }
}

export function resolveBrowserBridgeLocale(
  language: string | null | undefined = readConsoleLanguage(),
): BrowserBridgeLocale {
  const base = String(language || "")
    .trim()
    .split("-")[0]
    .toLowerCase();
  return base === "zh" ? "zh" : "en";
}

export function t(
  locale: BrowserBridgeLocale,
  key: MessageKey,
  params?: Record<string, string | number>,
): string {
  let text: string = messages[locale][key] ?? messages.en[key];
  if (params) {
    for (const [name, value] of Object.entries(params)) {
      text = text.split(`{${name}}`).join(String(value));
    }
  }
  return text;
}

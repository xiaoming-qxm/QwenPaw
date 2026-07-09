export type BrowserBridgeLocale = "zh" | "en";

const messages = {
  en: {
    routeLabel: "Chrome",
    pageTitle: "Chrome",
    pageSubtitle: "Connect QwenPaw to this Chrome browser.",
    loading: "Checking Chrome connection...",
    refreshStatus: "Refresh Status",
    installedRefresh: "I've installed it, refresh status",
    versionUnknown: "unknown",
    installTitle: "Install Chrome Extension",
    installDescription:
      "Load the local extension, then return here to confirm the connection.",
    readyTitle: "Chrome Connected",
    readyDescription: "Version {version}. Connected {connectedSince}.",
    openChrome: "Open Chrome",
    installMethodsTitle: "Install method",
    localMethodTitle: "Local install",
    recommendedBadge: "Recommended",
    localMethodDescription:
      "Use the extension files included with QwenPaw for this local browser.",
    chromeWebStoreTitle: "Chrome Web Store",
    chromeWebStoreDescription:
      "The store listing is not available yet. Use local install for now.",
    comingSoon: "Coming soon",
    localStepsTitle: "Local install steps",
    stepOpen: "Open chrome://extensions and enable Developer mode.",
    stepLoad: "Choose Load unpacked and select the QwenPaw extension folder.",
    stepVerify: "Return here and refresh the status.",
    directoryLabel: "QwenPaw built-in extension folder",
    directoryHint: "Path is available from copy or advanced information.",
    openExtensionFolder: "Open Folder",
    copyPath: "Copy Path",
    advancedInfo: "Advanced information",
    extensionDir: "Extension folder",
    nativeManifest: "Local connection config",
    nativeHost: "Local connection helper",
    config: "Local settings file",
    bridgeEndpoint: "Connection endpoint",
    checksTitle: "Connection checks",
    extensionLoadedCheck: "Chrome Extension",
    localConnectionCheck: "Local connection",
    checkReady: "Ready",
    version: "Extension version",
    connected: "Connected",
    justNow: "just now",
    minutesAgo: "{count} minutes ago",
    hoursAgo: "{count} hours ago",
    installSuccess: "Extension files ready",
    installFailed: "Extension setup failed",
    copied: "Copied",
    browser_bridge_disconnected:
      "Reload the extension or reopen the target browser tab.",
    browser_backend_unavailable:
      "Refresh the status after the backend is available.",
    browser_bridge_action_runtime_missing:
      "Restart QwenPaw or reload the Chrome plugin.",
    isolated_backend_unavailable:
      "Install or restart the isolated browser runtime.",
  },
  zh: {
    routeLabel: "Chrome",
    pageTitle: "Chrome",
    pageSubtitle: "将 QwenPaw 连接到此 Chrome 浏览器。",
    loading: "正在检查 Chrome 连接...",
    refreshStatus: "刷新状态",
    installedRefresh: "我已安装，刷新状态",
    versionUnknown: "未知",
    installTitle: "安装 Chrome 扩展",
    installDescription: "加载本地扩展后，回到这里确认连接状态。",
    readyTitle: "Chrome 已连接",
    readyDescription: "版本 {version}。连接于 {connectedSince}。",
    openChrome: "打开 Chrome",
    installMethodsTitle: "安装方式",
    localMethodTitle: "本地安装",
    recommendedBadge: "推荐",
    localMethodDescription: "使用 QwenPaw 自带扩展文件连接当前本地浏览器。",
    chromeWebStoreTitle: "Chrome Web Store",
    chromeWebStoreDescription: "官方商店版本尚未发布。当前请使用本地安装。",
    comingSoon: "Coming soon",
    localStepsTitle: "本地安装步骤",
    stepOpen: "打开 chrome://extensions，并启用开发者模式。",
    stepLoad: "选择“加载已解压的扩展程序”，并选择 QwenPaw 扩展目录。",
    stepVerify: "回到此页面并刷新状态。",
    directoryLabel: "QwenPaw 自带扩展目录",
    directoryHint: "完整路径可通过复制或高级信息查看。",
    openExtensionFolder: "打开目录",
    copyPath: "复制路径",
    advancedInfo: "高级信息",
    extensionDir: "扩展目录",
    nativeManifest: "本机连接配置",
    nativeHost: "本机连接助手",
    config: "本地设置文件",
    bridgeEndpoint: "连接端点",
    checksTitle: "连接检查",
    extensionLoadedCheck: "Chrome 扩展",
    localConnectionCheck: "本机连接",
    checkReady: "就绪",
    version: "扩展版本",
    connected: "连接时间",
    justNow: "刚刚",
    minutesAgo: "{count} 分钟前",
    hoursAgo: "{count} 小时前",
    installSuccess: "扩展文件已准备好",
    installFailed: "扩展设置失败",
    copied: "已复制",
    browser_bridge_disconnected: "重载扩展，或重新打开目标浏览器标签页。",
    browser_backend_unavailable: "后端可用后刷新状态。",
    browser_bridge_action_runtime_missing:
      "重启 QwenPaw，或重新加载 Chrome 插件。",
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

const k = {
  en: {
    routeLabel: "Chrome",
    pageTitle: "Chrome",
    pageSubtitle: "Connect QwenPaw to this Chrome browser.",
    loading: "Checking Chrome connection...",
    refreshStatus: "Refresh Status",
    installedRefresh: "I've installed it, refresh status",
    versionUnknown: "unknown",
    installTitle: "Install Chrome Extension",
    installDescription: "Load the local extension, then return here to confirm the connection.",
    readyTitle: "Chrome Connected",
    readyDescription: "Version {version}. Connected {connectedSince}.",
    openChrome: "Open Chrome",
    installMethodsTitle: "Install method",
    localMethodTitle: "Local install",
    recommendedBadge: "Recommended",
    localMethodDescription: "Use the extension files included with QwenPaw for this local browser.",
    chromeWebStoreTitle: "Chrome Web Store",
    chromeWebStoreDescription: "The store listing is not available yet. Use local install for now.",
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
    browser_bridge_disconnected: "Reload the extension or reopen the target browser tab.",
    browser_backend_unavailable: "Refresh the status after the backend is available.",
    browser_bridge_action_runtime_missing: "Restart QwenPaw or reload the Chrome plugin.",
    isolated_backend_unavailable: "Install or restart the isolated browser runtime."
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
    browser_bridge_action_runtime_missing: "重启 QwenPaw，或重新加载 Chrome 插件。",
    isolated_backend_unavailable: "安装或重启隔离浏览器运行时。"
  }
};
function O() {
  var t;
  try {
    return ((t = window.localStorage) == null ? void 0 : t.getItem("language")) ?? null;
  } catch {
    return null;
  }
}
function L(t = O()) {
  return String(t || "").trim().split("-")[0].toLowerCase() === "zh" ? "zh" : "en";
}
function n(t, o, i) {
  let l = k[t][o] ?? k.en[o];
  if (i)
    for (const [c, d] of Object.entries(i))
      l = l.split(`{${c}}`).join(String(d));
  return l;
}
const w = window.QwenPaw.host, e = w.React, j = w.antd, A = w.getApiUrl, v = w.getApiToken, { Alert: Q, Button: m, Collapse: N, Space: U, Spin: V, Typography: z, message: g } = j, { Text: s, Title: S } = z, a = {
  page: {
    minHeight: "100%",
    overflowY: "auto",
    padding: 24,
    background: "transparent"
  },
  shell: {
    width: "min(100%, 900px)",
    margin: "0 auto",
    display: "flex",
    flexDirection: "column",
    gap: 16
  },
  header: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 16,
    flexWrap: "wrap"
  },
  titleRow: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    minWidth: 0
  },
  chromeIcon: {
    position: "relative",
    width: 42,
    height: 42,
    flex: "0 0 42px",
    borderRadius: "50%",
    background: "radial-gradient(circle at center, #fff 0 18%, transparent 19%), radial-gradient(circle at center, #1a73e8 0 36%, transparent 37%), conic-gradient(#ea4335 0 34%, #fbbc04 0 67%, #34a853 0 100%)",
    boxShadow: "inset 0 0 0 1px rgba(0,0,0,0.10)"
  },
  panel: {
    border: "1px solid rgba(0,0,0,0.08)",
    borderRadius: 8,
    background: "#fff",
    padding: 24,
    boxShadow: "0 1px 2px rgba(0,0,0,0.03)"
  },
  statusBlock: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    gap: 20,
    alignItems: "start"
  },
  statusTitleRow: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    marginBottom: 8
  },
  statusDot: {
    width: 10,
    height: 10,
    borderRadius: 999,
    flexShrink: 0
  },
  statusCopy: {
    maxWidth: 610,
    color: "rgba(0,0,0,0.58)",
    lineHeight: 1.55
  },
  actions: {
    display: "flex",
    justifyContent: "flex-end",
    gap: 8,
    flexWrap: "wrap"
  },
  section: {
    marginTop: 22,
    display: "flex",
    flexDirection: "column",
    gap: 12
  },
  methodGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
    gap: 12
  },
  methodTile: {
    minHeight: 128,
    padding: 14,
    border: "1px solid rgba(0,0,0,0.08)",
    borderRadius: 8,
    background: "#fff",
    display: "flex",
    flexDirection: "column",
    gap: 10
  },
  disabledTile: {
    minHeight: 128,
    padding: 14,
    border: "1px dashed rgba(0,0,0,0.16)",
    borderRadius: 8,
    background: "rgba(0,0,0,0.025)",
    display: "flex",
    flexDirection: "column",
    gap: 10,
    opacity: 0.72
  },
  methodHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8
  },
  badge: {
    minHeight: 22,
    padding: "1px 8px",
    borderRadius: 999,
    border: "1px solid rgba(22,119,255,0.22)",
    color: "#0958d9",
    background: "rgba(22,119,255,0.08)",
    fontSize: 12,
    whiteSpace: "nowrap"
  },
  steps: {
    margin: 0,
    paddingLeft: 20,
    color: "rgba(0,0,0,0.72)",
    lineHeight: 1.65
  },
  directoryBox: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    flexWrap: "wrap",
    padding: 12,
    border: "1px solid rgba(0,0,0,0.08)",
    borderRadius: 8,
    background: "rgba(0,0,0,0.02)"
  },
  checkGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: 12
  },
  checkTile: {
    minHeight: 86,
    padding: 14,
    border: "1px solid rgba(0,0,0,0.08)",
    borderRadius: 8,
    background: "rgba(31,122,63,0.05)",
    display: "flex",
    flexDirection: "column",
    gap: 8
  },
  checkTitle: {
    display: "flex",
    alignItems: "center",
    gap: 8
  },
  advanced: {
    marginTop: 18,
    borderRadius: 8,
    background: "#fff"
  },
  advancedRows: {
    display: "flex",
    flexDirection: "column",
    gap: 10
  },
  advancedRow: {
    display: "grid",
    gridTemplateColumns: "minmax(128px, 180px) minmax(0, 1fr) auto",
    gap: 8,
    alignItems: "center"
  },
  advancedValue: {
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
  }
};
function G() {
  const t = {}, o = v == null ? void 0 : v();
  return o && (t.Authorization = `Bearer ${o}`), t;
}
async function x(t, o) {
  const i = await fetch(A(t), {
    ...o,
    headers: {
      ...(o == null ? void 0 : o.headers) || {},
      ...G()
    }
  }), l = await i.text(), c = l ? JSON.parse(l) : null;
  if (!i.ok)
    throw new Error(
      typeof (c == null ? void 0 : c.detail) == "string" ? c.detail : i.statusText
    );
  return c;
}
function $() {
  return x("/chrome/status");
}
function J(t) {
  return x("/chrome/setup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(t)
  });
}
function q() {
  return x(
    "/chrome/open-chrome-extensions",
    {
      method: "POST"
    }
  );
}
function Y() {
  return x(
    "/chrome/open-extension-folder",
    {
      method: "POST"
    }
  );
}
function D() {
  return `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws/chrome`;
}
function K(t, o) {
  if (!t)
    return n(o, "justNow");
  const i = new Date(t).getTime();
  if (Number.isNaN(i))
    return n(o, "justNow");
  const l = Math.max(0, Math.floor((Date.now() - i) / 6e4));
  return l < 1 ? n(o, "justNow") : l < 60 ? n(o, "minutesAgo", { count: l }) : n(o, "hoursAgo", { count: Math.floor(l / 60) });
}
function T({ ready: t }) {
  return /* @__PURE__ */ e.createElement(
    "span",
    {
      "aria-hidden": "true",
      style: {
        ...a.statusDot,
        background: t ? "#1f7a3f" : "#9a6700"
      }
    }
  );
}
function X({
  locale: t,
  onCopy: o,
  status: i
}) {
  const l = [
    { key: "extension_dir", label: "extensionDir" },
    { key: "native_manifest_path", label: "nativeManifest" },
    { key: "native_host_path", label: "nativeHost" },
    { key: "config_path", label: "config" }
  ], c = (i == null ? void 0 : i.ws_url) || D();
  return /* @__PURE__ */ e.createElement(
    N,
    {
      style: a.advanced,
      items: [
        {
          key: "advanced",
          label: n(t, "advancedInfo"),
          children: /* @__PURE__ */ e.createElement("div", { style: a.advancedRows }, l.map((d) => {
            const h = (i == null ? void 0 : i[d.key]) || "-";
            return /* @__PURE__ */ e.createElement("div", { key: d.key, style: a.advancedRow }, /* @__PURE__ */ e.createElement(s, { type: "secondary" }, n(t, d.label)), /* @__PURE__ */ e.createElement("code", { style: a.advancedValue }, h), /* @__PURE__ */ e.createElement(
              m,
              {
                disabled: !(i != null && i[d.key]),
                onClick: () => o(h)
              },
              n(t, "copyPath")
            ));
          }), /* @__PURE__ */ e.createElement("div", { style: a.advancedRow }, /* @__PURE__ */ e.createElement(s, { type: "secondary" }, n(t, "bridgeEndpoint")), /* @__PURE__ */ e.createElement("code", { style: a.advancedValue }, c), /* @__PURE__ */ e.createElement(m, { onClick: () => o(c) }, n(t, "copyPath"))))
        }
      ]
    }
  );
}
function Z() {
  const t = L(), [o, i] = e.useState(null), [l, c] = e.useState(!0), [d, h] = e.useState(!1), [C, y] = e.useState(null), f = e.useCallback(async () => {
    c(!0), y(null);
    try {
      const r = await $();
      return i(r), r;
    } catch (r) {
      const u = r instanceof Error ? r.message : String(r);
      return y(u), null;
    } finally {
      c(!1);
    }
  }, []);
  e.useEffect(() => {
    f();
  }, [f]);
  const b = e.useCallback(async () => {
    if (o != null && o.extension_dir)
      return o;
    h(!0), y(null);
    try {
      const r = await J({
        install_mode: "unpacked",
        ws_url: D()
      });
      return i(r), g.success(n(t, "installSuccess")), r;
    } catch (r) {
      const u = r instanceof Error ? r.message : String(r);
      return y(u), g.error(n(t, "installFailed")), null;
    } finally {
      h(!1);
    }
  }, [t, o]), E = e.useCallback(
    async (r) => {
      var u;
      await ((u = navigator.clipboard) == null ? void 0 : u.writeText(r)), g.success(n(t, "copied"));
    },
    [t]
  ), P = e.useCallback(async () => {
    const r = await b();
    r != null && r.extension_dir && await E(r.extension_dir);
  }, [E, b]), I = e.useCallback(async () => {
    await b();
    const r = await Y();
    !r.opened && r.error && g.warning(r.error);
  }, [b]), H = e.useCallback(async () => {
    const r = await q();
    !r.opened && r.error && g.warning(r.error);
  }, []), p = !!(o != null && o.connected), M = !p, W = (o == null ? void 0 : o.version) || n(t, "versionUnknown"), B = K(o == null ? void 0 : o.connected_since, t), F = [
    n(t, "extensionLoadedCheck"),
    n(t, "localConnectionCheck")
  ];
  return /* @__PURE__ */ e.createElement("div", { style: a.page }, /* @__PURE__ */ e.createElement("div", { style: a.shell }, /* @__PURE__ */ e.createElement("div", { style: a.panel }, /* @__PURE__ */ e.createElement("div", { style: a.statusBlock }, /* @__PURE__ */ e.createElement("div", null, /* @__PURE__ */ e.createElement("div", { style: a.header }, /* @__PURE__ */ e.createElement("div", { style: a.titleRow }, /* @__PURE__ */ e.createElement("span", { style: a.chromeIcon }), /* @__PURE__ */ e.createElement("div", null, /* @__PURE__ */ e.createElement(S, { level: 3, style: { margin: 0 } }, n(t, "pageTitle")), /* @__PURE__ */ e.createElement(s, { type: "secondary" }, n(t, "pageSubtitle"))))), /* @__PURE__ */ e.createElement("div", { style: { marginTop: 22 } }, /* @__PURE__ */ e.createElement("div", { style: a.statusTitleRow }, /* @__PURE__ */ e.createElement(T, { ready: p }), /* @__PURE__ */ e.createElement(S, { level: 4, style: { margin: 0 } }, p ? n(t, "readyTitle") : n(t, "installTitle"))), /* @__PURE__ */ e.createElement("div", { style: a.statusCopy }, p ? n(t, "readyDescription", {
    version: W,
    connectedSince: B
  }) : (o == null ? void 0 : o.recovery_copy) || n(t, "installDescription")))), /* @__PURE__ */ e.createElement("div", { style: a.actions }, p ? /* @__PURE__ */ e.createElement(e.Fragment, null, /* @__PURE__ */ e.createElement(m, { loading: l, onClick: () => void f() }, n(t, "refreshStatus")), /* @__PURE__ */ e.createElement(m, { type: "primary", onClick: () => void H() }, n(t, "openChrome"))) : /* @__PURE__ */ e.createElement(
    m,
    {
      type: "primary",
      loading: l,
      onClick: () => void f()
    },
    n(t, "installedRefresh")
  ))), C ? /* @__PURE__ */ e.createElement(
    Q,
    {
      showIcon: !0,
      type: "error",
      message: C,
      style: { marginTop: 16 }
    }
  ) : null, p ? /* @__PURE__ */ e.createElement("div", { style: a.section }, /* @__PURE__ */ e.createElement(s, { strong: !0 }, n(t, "checksTitle")), /* @__PURE__ */ e.createElement("div", { style: a.checkGrid }, F.map((r) => /* @__PURE__ */ e.createElement("div", { key: r, style: a.checkTile }, /* @__PURE__ */ e.createElement("div", { style: a.checkTitle }, /* @__PURE__ */ e.createElement(T, { ready: !0 }), /* @__PURE__ */ e.createElement(s, { strong: !0 }, r)), /* @__PURE__ */ e.createElement(s, { type: "secondary" }, n(t, "checkReady")))))) : M ? /* @__PURE__ */ e.createElement(e.Fragment, null, /* @__PURE__ */ e.createElement("div", { style: a.section }, /* @__PURE__ */ e.createElement(s, { strong: !0 }, n(t, "installMethodsTitle")), /* @__PURE__ */ e.createElement("div", { style: a.methodGrid }, /* @__PURE__ */ e.createElement("div", { style: a.methodTile }, /* @__PURE__ */ e.createElement("div", { style: a.methodHeader }, /* @__PURE__ */ e.createElement(s, { strong: !0 }, n(t, "localMethodTitle")), /* @__PURE__ */ e.createElement("span", { style: a.badge }, n(t, "recommendedBadge"))), /* @__PURE__ */ e.createElement(s, { type: "secondary" }, n(t, "localMethodDescription"))), /* @__PURE__ */ e.createElement("div", { style: a.disabledTile, "aria-disabled": "true" }, /* @__PURE__ */ e.createElement("div", { style: a.methodHeader }, /* @__PURE__ */ e.createElement(s, { strong: !0 }, n(t, "chromeWebStoreTitle")), /* @__PURE__ */ e.createElement("span", { style: a.badge }, n(t, "comingSoon"))), /* @__PURE__ */ e.createElement(s, { type: "secondary" }, n(t, "chromeWebStoreDescription")), /* @__PURE__ */ e.createElement(m, { disabled: !0 }, n(t, "comingSoon"))))), /* @__PURE__ */ e.createElement("div", { style: a.section }, /* @__PURE__ */ e.createElement(s, { strong: !0 }, n(t, "localStepsTitle")), /* @__PURE__ */ e.createElement("ol", { style: a.steps }, /* @__PURE__ */ e.createElement("li", null, n(t, "stepOpen")), /* @__PURE__ */ e.createElement("li", null, n(t, "stepLoad")), /* @__PURE__ */ e.createElement("li", null, n(t, "stepVerify"))), /* @__PURE__ */ e.createElement("div", { style: a.directoryBox }, /* @__PURE__ */ e.createElement("div", null, /* @__PURE__ */ e.createElement(s, { strong: !0 }, n(t, "directoryLabel")), /* @__PURE__ */ e.createElement("br", null), /* @__PURE__ */ e.createElement(s, { type: "secondary" }, n(t, "directoryHint"))), /* @__PURE__ */ e.createElement(U, { wrap: !0 }, /* @__PURE__ */ e.createElement(
    m,
    {
      loading: d,
      onClick: () => void I()
    },
    n(t, "openExtensionFolder")
  ), /* @__PURE__ */ e.createElement(
    m,
    {
      loading: d,
      onClick: () => void P()
    },
    n(t, "copyPath")
  ))))) : null, /* @__PURE__ */ e.createElement(
    X,
    {
      locale: t,
      onCopy: (r) => void E(r),
      status: o
    }
  )), l && !o ? /* @__PURE__ */ e.createElement(V, null) : null));
}
const ee = L();
var R, _;
(_ = (R = window.QwenPaw).registerRoutes) == null || _.call(R, "chrome", [
  {
    path: "/plugin/chrome",
    component: Z,
    label: n(ee, "routeLabel"),
    icon: /* @__PURE__ */ e.createElement("span", { style: a.chromeIcon }),
    priority: 40
  }
]);

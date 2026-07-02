const D = {
  en: {
    routeLabel: "Browser Control",
    pageTitle: "Browser Control",
    pageSubtitle: "Connect QwenPaw to Chrome through the local browser bridge.",
    loading: "Loading browser bridge status...",
    installCws: "Install from Chrome Web Store",
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
    copied: "Copied"
  },
  zh: {
    routeLabel: "浏览器控制",
    pageTitle: "浏览器控制",
    pageSubtitle: "通过本地浏览器桥接将 QwenPaw 连接到 Chrome。",
    loading: "正在加载浏览器桥接状态...",
    installCws: "从 Chrome Web Store 安装",
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
    copied: "已复制"
  }
};
function Z() {
  var e;
  try {
    return ((e = window.localStorage) == null ? void 0 : e.getItem("language")) ?? null;
  } catch {
    return null;
  }
}
function W(e = Z()) {
  return String(e || "").trim().split("-")[0].toLowerCase() === "zh" ? "zh" : "en";
}
function n(e, r, i) {
  let s = D[e][r] ?? D.en[r];
  if (i)
    for (const [c, a] of Object.entries(i))
      s = s.split(`{${c}}`).join(String(a));
  return s;
}
const T = window.QwenPaw.host, t = T.React, G = T.antd, X = T.getApiUrl, A = T.getApiToken, {
  Alert: j,
  Button: p,
  Card: R,
  Collapse: ee,
  Space: te,
  Spin: P,
  Steps: O,
  Typography: ne,
  message: x
} = G, { Paragraph: M, Text: d, Title: I } = ne, re = "https://chromewebstore.google.com/detail/qwenpaw-browser-bridge/nflcgkfjgoiipklkpenmbiificbakoch", o = {
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
  heroCard: {
    width: "min(100%, 600px)",
    margin: "0 auto",
    borderRadius: 8,
    textAlign: "center"
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
  heroActions: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
    flexWrap: "wrap"
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
  usageSection: {
    margin: "18px 0 22px",
    display: "flex",
    flexDirection: "column",
    gap: 10
  },
  usageList: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
    gap: 10,
    textAlign: "left"
  },
  usageItem: {
    minHeight: 72,
    padding: 12,
    border: "1px solid rgba(0,0,0,0.06)",
    borderRadius: 8,
    background: "rgba(0,0,0,0.02)",
    overflowWrap: "anywhere"
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
  }
};
function oe() {
  const e = {}, r = A == null ? void 0 : A();
  return r && (e.Authorization = `Bearer ${r}`), e;
}
async function V(e, r) {
  const i = await fetch(X(e), {
    ...r,
    headers: {
      ...(r == null ? void 0 : r.headers) || {},
      ...oe()
    }
  }), s = await i.text(), c = s ? JSON.parse(s) : null;
  if (!i.ok)
    throw new Error(
      typeof (c == null ? void 0 : c.detail) == "string" ? c.detail : i.statusText
    );
  return c;
}
function ie() {
  return V("/extension/status");
}
function le(e) {
  return V("/extension/setup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(e)
  });
}
function ae(e) {
  return e != null && e.connected ? "connected" : e != null && e.installed ? "installed" : "not_installed";
}
function z() {
  return `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/ws/nm-bridge`;
}
function se(e) {
  return (e == null ? void 0 : e.cws_url) || re;
}
function ce(e) {
  return Array.isArray(e) ? e : e ? [String(e)] : [];
}
function F({ size: e = 38 }) {
  return /* @__PURE__ */ t.createElement(
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
    /* @__PURE__ */ t.createElement(
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
    /* @__PURE__ */ t.createElement("path", { d: "M4 13H34", stroke: "currentColor", strokeWidth: "2" }),
    /* @__PURE__ */ t.createElement("circle", { cx: "9", cy: "9.5", fill: "currentColor", r: "1.2" }),
    /* @__PURE__ */ t.createElement("circle", { cx: "13", cy: "9.5", fill: "currentColor", opacity: "0.62", r: "1.2" }),
    /* @__PURE__ */ t.createElement(
      "path",
      {
        d: "M18.5 17.5L29.5 22.1L24.8 24L28 30.1L25.3 31.5L22.1 25.5L18.5 29.2V17.5Z",
        fill: "currentColor"
      }
    )
  );
}
function de() {
  return /* @__PURE__ */ t.createElement(
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
function pe(e, r) {
  if (!e)
    return n(r, "justNow");
  const i = new Date(e).getTime();
  if (Number.isNaN(i))
    return n(r, "justNow");
  const s = Math.max(0, Math.floor((Date.now() - i) / 1e3));
  if (s < 60)
    return n(r, "justNow");
  const c = Math.floor(s / 60);
  if (c < 60)
    return n(r, "minutesAgo", { count: c });
  const a = Math.floor(c / 60);
  return a < 24 ? n(r, "hoursAgo", { count: a }) : n(r, "daysAgo", { count: Math.floor(a / 24) });
}
function ue({
  locale: e,
  setupLoading: r,
  onDeveloperClick: i,
  onInstallCws: s
}) {
  return /* @__PURE__ */ t.createElement(R, { style: o.heroCard }, /* @__PURE__ */ t.createElement("div", { style: o.iconCircle }, /* @__PURE__ */ t.createElement(F, null)), /* @__PURE__ */ t.createElement(I, { level: 2 }, n(e, "pageTitle")), /* @__PURE__ */ t.createElement(M, { type: "secondary" }, n(e, "pageSubtitle")), /* @__PURE__ */ t.createElement("div", { style: o.heroActions }, /* @__PURE__ */ t.createElement(
    p,
    {
      type: "primary",
      size: "large",
      loading: r,
      onClick: s
    },
    n(e, "installCws")
  ), /* @__PURE__ */ t.createElement(p, { type: "link", onClick: i }, n(e, "devMode"))));
}
function me({
  locale: e,
  loading: r,
  showTips: i,
  onRefresh: s
}) {
  return /* @__PURE__ */ t.createElement(R, { style: o.centeredCard }, /* @__PURE__ */ t.createElement(
    O,
    {
      size: "small",
      current: 1,
      items: [
        {
          title: n(e, "installed"),
          status: "finish"
        },
        {
          title: n(e, "connecting"),
          status: "process"
        },
        {
          title: n(e, "ready"),
          status: "wait"
        }
      ]
    }
  ), /* @__PURE__ */ t.createElement("div", { style: o.progressBody }, /* @__PURE__ */ t.createElement(I, { level: 3 }, n(e, "waitingTitle")), /* @__PURE__ */ t.createElement(M, { type: "secondary" }, n(e, "waitingMessage")), /* @__PURE__ */ t.createElement(p, { loading: r, onClick: s }, n(e, "refreshStatus"))), i ? /* @__PURE__ */ t.createElement(
    j,
    {
      showIcon: !0,
      type: "warning",
      message: n(e, "stillNotConnected"),
      description: /* @__PURE__ */ t.createElement("ul", null, /* @__PURE__ */ t.createElement("li", null, n(e, "tipEnable")), /* @__PURE__ */ t.createElement("li", null, n(e, "tipClick")), /* @__PURE__ */ t.createElement("li", null, n(e, "tipReload")))
    }
  ) : null);
}
function ge({
  locale: e,
  status: r,
  loading: i,
  onRefresh: s
}) {
  const c = pe(r == null ? void 0 : r.connected_since, e), a = (r == null ? void 0 : r.version) || n(e, "versionUnknown");
  return /* @__PURE__ */ t.createElement(R, { style: { ...o.centeredCard, textAlign: "center" } }, /* @__PURE__ */ t.createElement("div", { style: o.successCircle }, "✓"), /* @__PURE__ */ t.createElement(I, { level: 2 }, n(e, "readyTitle")), /* @__PURE__ */ t.createElement(
    O,
    {
      size: "small",
      current: 2,
      items: [
        {
          title: n(e, "installed"),
          status: "finish"
        },
        {
          title: n(e, "connectedStep"),
          status: "finish"
        },
        {
          title: n(e, "ready"),
          status: "finish"
        }
      ]
    }
  ), /* @__PURE__ */ t.createElement("div", { style: o.readyMeta }, /* @__PURE__ */ t.createElement(d, null, n(e, "version"), ": ", a), /* @__PURE__ */ t.createElement(d, null, n(e, "connected"), ": ", c)), /* @__PURE__ */ t.createElement("div", { style: o.usageSection }, /* @__PURE__ */ t.createElement(d, { strong: !0 }, n(e, "usageTitle")), /* @__PURE__ */ t.createElement("div", { style: o.usageList }, /* @__PURE__ */ t.createElement("div", { style: o.usageItem }, n(e, "example1")), /* @__PURE__ */ t.createElement("div", { style: o.usageItem }, n(e, "example2")), /* @__PURE__ */ t.createElement("div", { style: o.usageItem }, n(e, "example3")))), /* @__PURE__ */ t.createElement(p, { loading: i, onClick: s }, n(e, "testConnection")));
}
function fe({
  locale: e,
  activeKey: r,
  loading: i,
  pathRows: s,
  setupLoading: c,
  status: a,
  onChange: v,
  onCopy: w,
  onRegenerate: b,
  onReset: m
}) {
  const E = (a == null ? void 0 : a.ws_url) || z();
  return /* @__PURE__ */ t.createElement(
    ee,
    {
      activeKey: r,
      style: o.developerPanel,
      onChange: v,
      items: [
        {
          key: "developer",
          label: /* @__PURE__ */ t.createElement(te, { size: 8 }, n(e, "developerTitle")),
          children: /* @__PURE__ */ t.createElement(P, { spinning: i && !a }, /* @__PURE__ */ t.createElement("div", { style: o.developerContent }, /* @__PURE__ */ t.createElement("div", { style: o.modeRow }, /* @__PURE__ */ t.createElement(d, { type: "secondary" }, n(e, "installMode")), /* @__PURE__ */ t.createElement(d, null, (a == null ? void 0 : a.install_mode) || "-")), /* @__PURE__ */ t.createElement("div", { style: o.pathList }, s.map(({ key: g, label: L }) => {
            const y = (a == null ? void 0 : a[g]) || "-";
            return /* @__PURE__ */ t.createElement("div", { style: o.pathRow, key: g }, /* @__PURE__ */ t.createElement(d, { type: "secondary" }, L), /* @__PURE__ */ t.createElement("code", { style: o.pathValue }, y), /* @__PURE__ */ t.createElement(
              p,
              {
                disabled: !(a != null && a[g]),
                onClick: () => w(y),
                "aria-label": n(e, "copy")
              },
              n(e, "copy")
            ));
          }), /* @__PURE__ */ t.createElement("div", { style: o.pathRow }, /* @__PURE__ */ t.createElement(d, { type: "secondary" }, n(e, "bridgeEndpoint")), /* @__PURE__ */ t.createElement("code", { style: o.pathValue }, E), /* @__PURE__ */ t.createElement(
            p,
            {
              onClick: () => w(E),
              "aria-label": n(e, "copy")
            },
            n(e, "copy")
          ))), /* @__PURE__ */ t.createElement("div", { style: o.developerActions }, /* @__PURE__ */ t.createElement(p, { loading: c, onClick: b }, n(e, "regenerate")), /* @__PURE__ */ t.createElement(p, { loading: c, onClick: m }, n(e, "reset"))), /* @__PURE__ */ t.createElement("div", { style: o.unpackedSteps }, /* @__PURE__ */ t.createElement(d, { strong: !0 }, n(e, "unpackedTitle")), /* @__PURE__ */ t.createElement("ol", null, /* @__PURE__ */ t.createElement("li", null, n(e, "stepOpen")), /* @__PURE__ */ t.createElement("li", null, n(e, "stepLoad")), /* @__PURE__ */ t.createElement("li", null, n(e, "stepVerify"))))))
        }
      ]
    }
  );
}
function he() {
  const e = W(), r = t.useRef(null), [i, s] = t.useState(null), [c, a] = t.useState(!0), [v, w] = t.useState(!1), [b, m] = t.useState(null), [E, g] = t.useState(!1), [L, y] = t.useState(
    []
  ), [B, H] = t.useState(!1), U = t.useMemo(
    () => [
      {
        key: "extension_dir",
        label: n(e, "extensionDir")
      },
      {
        key: "native_manifest_path",
        label: n(e, "nativeManifest")
      },
      {
        key: "native_host_path",
        label: n(e, "nativeHost")
      },
      {
        key: "config_path",
        label: n(e, "config")
      }
    ],
    [e]
  ), u = t.useCallback(async () => {
    a(!0), m(null);
    try {
      const l = await ie();
      return s(l), l;
    } catch (l) {
      return m(l instanceof Error ? l.message : String(l)), null;
    } finally {
      a(!1);
    }
  }, []);
  t.useEffect(() => {
    u();
  }, [u]);
  const C = t.useMemo(() => i && B && !i.connected && !i.installed ? {
    ...i,
    installed: !0,
    install_mode: "cws"
  } : i, [B, i]), S = ae(C);
  t.useEffect(() => {
    if (S !== "installed") {
      g(!1);
      return;
    }
    const l = window.setInterval(() => {
      u();
    }, 3e3), f = window.setTimeout(() => g(!0), 1e4);
    return () => {
      window.clearInterval(l), window.clearTimeout(f);
    };
  }, [u, S]);
  const k = t.useCallback(
    async (l = "unpacked", f = !0) => {
      w(!0), m(null);
      try {
        const h = await le({
          install_mode: l,
          reset: f,
          ws_url: z()
        });
        return s(h), x.success(n(e, "installSuccess")), h;
      } catch (h) {
        return m(h instanceof Error ? h.message : String(h)), x.error(n(e, "installFailed")), null;
      } finally {
        w(!1);
      }
    },
    [e]
  ), Q = t.useCallback(async () => {
    window.open(se(i), "_blank", "noopener,noreferrer");
    const l = await k("cws", !1);
    l && (H(!0), s({
      ...l,
      installed: !0,
      install_mode: "cws"
    }));
  }, [k, i]), K = async (l) => {
    var f;
    await ((f = navigator.clipboard) == null ? void 0 : f.writeText(l)), x.success(n(e, "copied"));
  }, $ = () => {
    y(["developer"]), window.setTimeout(() => {
      var l;
      (l = r.current) == null || l.scrollIntoView({
        behavior: "smooth",
        block: "start"
      });
    }, 0);
  }, q = (l) => {
    y(ce(l));
  }, J = t.useCallback(async () => {
    const l = await u();
    if (l) {
      if (l.connected) {
        x.success(n(e, "testSuccess"));
        return;
      }
      x.warning(n(e, "testFailed"));
    }
  }, [u, e]), Y = c && !C ? /* @__PURE__ */ t.createElement(R, { style: o.heroCard }, /* @__PURE__ */ t.createElement(P, null), /* @__PURE__ */ t.createElement(M, { style: { marginTop: 12 } }, n(e, "loading"))) : S === "connected" ? /* @__PURE__ */ t.createElement(
    ge,
    {
      locale: e,
      loading: c,
      onRefresh: () => void J(),
      status: C
    }
  ) : S === "installed" ? /* @__PURE__ */ t.createElement(
    me,
    {
      locale: e,
      loading: c,
      onRefresh: () => void u(),
      showTips: E
    }
  ) : /* @__PURE__ */ t.createElement(
    ue,
    {
      locale: e,
      onDeveloperClick: $,
      onInstallCws: () => void Q(),
      setupLoading: v
    }
  );
  return /* @__PURE__ */ t.createElement("div", { style: o.page }, /* @__PURE__ */ t.createElement("div", { style: o.header }, /* @__PURE__ */ t.createElement("div", { style: o.headerTitleRow }, /* @__PURE__ */ t.createElement("div", { style: o.headerIcon }, /* @__PURE__ */ t.createElement(F, null)), /* @__PURE__ */ t.createElement("div", { style: o.headerText }, /* @__PURE__ */ t.createElement(I, { level: 3, style: { margin: 0 } }, n(e, "pageTitle")), /* @__PURE__ */ t.createElement(d, { type: "secondary" }, n(e, "pageSubtitle"))))), /* @__PURE__ */ t.createElement("div", { style: o.content }, b ? /* @__PURE__ */ t.createElement(j, { type: "error", showIcon: !0, message: b }) : null, Y, /* @__PURE__ */ t.createElement("div", { ref: r }, /* @__PURE__ */ t.createElement(
    fe,
    {
      activeKey: L,
      loading: c,
      locale: e,
      onChange: q,
      onCopy: (l) => void K(l),
      onRegenerate: () => void k("unpacked", !1),
      onReset: () => void k("unpacked", !0),
      pathRows: U,
      setupLoading: v,
      status: C
    }
  ))));
}
const we = W();
var N, _;
(_ = (N = window.QwenPaw).registerRoutes) == null || _.call(N, "browser-control", [
  {
    path: "/plugin/browser-control",
    component: he,
    label: n(we, "routeLabel"),
    icon: /* @__PURE__ */ t.createElement(de, null),
    priority: 40
  }
]);

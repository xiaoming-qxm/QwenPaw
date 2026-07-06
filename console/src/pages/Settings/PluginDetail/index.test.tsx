import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import i18n from "@/i18n";
import { renderWithProviders } from "@/test/common_setup";
import PluginDetailPage from "./index";

const {
  mockFetchPluginDetail,
  mockUpdatePluginEnabled,
  mockSetup,
  mockSelfTest,
  mockOpenChromeExtensionsPage,
} = vi.hoisted(() => ({
  mockFetchPluginDetail: vi.fn(),
  mockUpdatePluginEnabled: vi.fn(),
  mockSetup: vi.fn(),
  mockSelfTest: vi.fn(),
  mockOpenChromeExtensionsPage: vi.fn(),
}));

vi.mock("@/api/modules/plugin", async () => {
  const actual = await vi.importActual<typeof import("@/api/modules/plugin")>(
    "@/api/modules/plugin",
  );
  return {
    ...actual,
    fetchPluginDetail: mockFetchPluginDetail,
    updatePluginEnabled: mockUpdatePluginEnabled,
  };
});

vi.mock("@/api/modules/extension", () => ({
  extensionApi: {
    setup: mockSetup,
    selfTest: mockSelfTest,
    openChromeExtensionsPage: mockOpenChromeExtensionsPage,
  },
}));

const runtimeStatus = {
  installed: true,
  connected: false,
  install_mode: "unpacked",
  readiness_state: "blocked",
  repair_action: "reload_extension",
  native_host_status: {
    status: "configured",
    message: "Native host manifest is configured.",
    repair_action: "none",
  },
  selected_backend_id: "user.chrome_extension",
  authorization_header: "Bearer secret-token",
  extension_id: "nflcgkfjgoiipklkpenmbiificbakoch",
  extension_dir: "/tmp/.qwenpaw/chrome-extension/qwenpaw-browser-bridge",
  native_manifest_path: "/tmp/NativeMessagingHosts/com.qwenpaw.browser.json",
  native_host_path: "/tmp/.qwenpaw/bin/qwenpaw-nm-host",
  config_path: "/tmp/.qwenpaw/nm-bridge.json",
  ws_url: "ws://127.0.0.1:8088/ws/browser-bridge",
  chrome_extensions_url: "chrome://extensions",
  version: null,
  extension_version: "0.1.0",
  connected_since: null,
  bridge_lifecycle: {
    connected: false,
    connected_since: null,
    last_connected_at: null,
    last_disconnected_at: null,
    last_disconnect_reason: "",
    reconnect_count: 0,
  },
  build_fingerprint: {
    git_commit: "abc123",
    repo_dirty: false,
    frontend_fingerprint: "main.js",
  },
  trace_summary: {
    event_count: 4,
    session_count: 2,
    latest_event: {
      event_id: "trace-1",
      session_id: "session-1",
      phase: "observe",
      action: "snapshot",
      status: "ok",
    },
  },
  last_self_test: null,
  sdk_diagnostics: {
    requested_context: "user",
    selected_backend_id: null,
    backends: [
      {
        backend_id: "user.chrome_extension",
        browser_context: "user",
        available: false,
        status: "unavailable",
        code: "browser_bridge_disconnected",
        message: "Browser bridge is not connected.",
        hint_key: "browser_bridge_disconnected",
        message_fallback:
          "Reload the extension or reopen the target browser tab.",
        features: ["snapshot", "click"],
        checks: [
          {
            name: "bridge_connection",
            status: "unavailable",
            message: "Browser bridge is not connected.",
          },
        ],
      },
    ],
  },
};

const browserBridgeDetail = {
  id: "browser-bridge",
  name: "Browser Bridge",
  version: "0.1.0",
  description:
    "Let QwenPaw inspect and operate your active Chrome tab through a local extension.",
  author: "QwenPaw",
  enabled: true,
  loaded: true,
  plugin_type: "general" as const,
  capabilities: [
    {
      id: "read-page",
      title: "Read active tab",
      description: "Read visible page text and metadata.",
    },
  ],
  setup: {
    cta: "Configure browser bridge",
    steps: [
      { id: "prepare", title: "Configure browser bridge" },
      { id: "install", title: "Install Chrome extension" },
      { id: "connect", title: "Wait for connection" },
    ],
  },
  meta: { builtin: true },
  manifest: {
    id: "browser-bridge",
    name: "Browser Bridge",
    version: "0.1.0",
    description:
      "Let QwenPaw inspect and operate your active Chrome tab through a local extension.",
    author: "QwenPaw",
    plugin_type: "general" as const,
    capabilities: [
      {
        id: "read-page",
        title: "Read active tab",
        description: "Read visible page text and metadata.",
      },
    ],
    setup: {
      cta: "Configure browser bridge",
      steps: [
        { id: "prepare", title: "Configure browser bridge" },
        { id: "install", title: "Install Chrome extension" },
        { id: "connect", title: "Wait for connection" },
      ],
    },
    meta: { builtin: true },
  },
  runtime_status: runtimeStatus,
};

function renderPluginDetail() {
  return renderWithProviders(
    <Routes>
      <Route path="/plugin-manager/:pluginId" element={<PluginDetailPage />} />
    </Routes>,
    { initialEntries: ["/plugin-manager/browser-bridge"] },
  );
}

describe("PluginDetailPage browser bridge setup", () => {
  beforeEach(() => {
    mockFetchPluginDetail.mockResolvedValue(browserBridgeDetail);
    mockUpdatePluginEnabled.mockResolvedValue({
      ...browserBridgeDetail,
      enabled: true,
    });
    mockSetup.mockResolvedValue({
      ...runtimeStatus,
      installed: true,
      connected: false,
    });
    mockSelfTest.mockResolvedValue({
      status: "passed",
      checked_at: "2026-07-05T01:00:00+00:00",
      duration_ms: 5,
      checks: [
        {
          name: "trace_store",
          passed: true,
          code: "trace_store_roundtrip",
          message: "Trace store write-read check passed.",
        },
      ],
    });
    mockOpenChromeExtensionsPage.mockResolvedValue({
      opened: true,
      url: "chrome://extensions",
    });
  });

  afterEach(async () => {
    await i18n.changeLanguage("en");
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  it("uses user-facing Chinese copy instead of the English manifest copy", async () => {
    await i18n.changeLanguage("zh");

    renderPluginDetail();

    expect(await screen.findAllByText("浏览器控制")).toHaveLength(2);
    expect(screen.getByText("等待 Chrome")).toBeInTheDocument();
    expect(screen.getByText("browser_bridge_disconnected")).toBeInTheDocument();
    expect(
      screen.getByText("重载扩展，或重新打开目标浏览器标签页。"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "打开 Chrome" }),
    ).toBeInTheDocument();
    expect(screen.getByText("高级信息")).toBeInTheDocument();
    expect(
      screen.queryByText("Chrome Extension Setup"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Configure browser bridge"),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Test Connection")).not.toBeInTheDocument();
    expect(screen.queryByText("Developer Options")).not.toBeInTheDocument();
  });

  it("keeps setup details collapsed until the user opens advanced information", async () => {
    await i18n.changeLanguage("zh");

    renderPluginDetail();

    expect(
      await screen.findByRole("button", { name: "打开 Chrome" }),
    ).toBeInTheDocument();
    expect(screen.getByText("扩展目录")).not.toBeVisible();
    expect(
      screen.getByText("/tmp/.qwenpaw/chrome-extension/qwenpaw-browser-bridge"),
    ).not.toBeVisible();

    await userEvent.click(screen.getByText("高级信息"));

    expect(screen.getByText("扩展目录")).toBeInTheDocument();
    expect(
      screen.getByText("/tmp/.qwenpaw/chrome-extension/qwenpaw-browser-bridge"),
    ).toBeInTheDocument();
  });

  it("opens the Chrome extensions page through the fixed backend action", async () => {
    await i18n.changeLanguage("zh");

    renderPluginDetail();

    await userEvent.click(
      await screen.findByRole("button", { name: "打开 Chrome" }),
    );

    expect(mockOpenChromeExtensionsPage).toHaveBeenCalledTimes(1);
  });

  it("renders shared readiness details and runs self-test", async () => {
    renderPluginDetail();

    expect(await screen.findByText("Extension version")).toBeInTheDocument();
    expect(screen.getByText("Selected backend")).toBeInTheDocument();
    expect(screen.getAllByText("user.chrome_extension").length).toBeGreaterThan(
      0,
    );
    expect(screen.getAllByText("Native host").length).toBeGreaterThan(0);
    expect(screen.getByText("configured")).toBeInTheDocument();
    expect(screen.getByText("Reload extension")).toBeInTheDocument();
    expect(screen.getByText("Trace events")).toBeInTheDocument();
    expect(screen.getByText("4 across 2 sessions")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Run Self-Test" }),
    );

    await waitFor(() => {
      expect(mockSelfTest).toHaveBeenCalledTimes(1);
    });
  });

  it("copies sanitized product diagnostics from the readiness center", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    renderPluginDetail();

    await userEvent.click(
      await screen.findByRole("button", { name: "Copy Diagnostics" }),
    );

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledTimes(1);
    });
    const copied = String(writeText.mock.calls[0][0]);
    expect(copied).toContain('"status"');
    expect(copied).toContain('"self_test"');
    expect(copied).toContain('"route_diagnostics"');
    expect(copied).toContain("user.chrome_extension");
    expect(copied).not.toContain("secret-token");
    expect(copied).not.toContain("authorization_header");
  });

  it("copies chrome://extensions when the backend cannot open Chrome", async () => {
    await i18n.changeLanguage("zh");
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    mockOpenChromeExtensionsPage.mockResolvedValue({
      opened: false,
      url: "chrome://extensions",
    });

    renderPluginDetail();

    await userEvent.click(
      await screen.findByRole("button", { name: "打开 Chrome" }),
    );

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith("chrome://extensions");
    });
  });
});

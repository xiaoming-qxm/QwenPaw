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
  mockOpenChromeExtensionsPage,
} = vi.hoisted(() => ({
  mockFetchPluginDetail: vi.fn(),
  mockUpdatePluginEnabled: vi.fn(),
  mockSetup: vi.fn(),
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
    openChromeExtensionsPage: mockOpenChromeExtensionsPage,
  },
}));

const runtimeStatus = {
  installed: true,
  connected: false,
  install_mode: "unpacked",
  extension_id: "nflcgkfjgoiipklkpenmbiificbakoch",
  extension_dir: "/tmp/.qwenpaw/chrome-extension/qwenpaw-browser-bridge",
  native_manifest_path: "/tmp/NativeMessagingHosts/com.qwenpaw.browser.json",
  native_host_path: "/tmp/.qwenpaw/bin/qwenpaw-nm-host",
  config_path: "/tmp/.qwenpaw/nm-bridge.json",
  ws_url: "ws://127.0.0.1:8088/ws/nm-bridge",
  chrome_extensions_url: "chrome://extensions",
  version: null,
  connected_since: null,
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

const browserControlDetail = {
  id: "browser-control",
  name: "Browser Control",
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
    id: "browser-control",
    name: "Browser Control",
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
    { initialEntries: ["/plugin-manager/browser-control"] },
  );
}

describe("PluginDetailPage browser control setup", () => {
  beforeEach(() => {
    mockFetchPluginDetail.mockResolvedValue(browserControlDetail);
    mockUpdatePluginEnabled.mockResolvedValue({
      ...browserControlDetail,
      enabled: true,
    });
    mockSetup.mockResolvedValue({
      ...runtimeStatus,
      installed: true,
      connected: false,
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

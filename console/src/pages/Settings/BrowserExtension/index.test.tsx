import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import BrowserExtensionPage from "./index";

const { mockGetStatus, mockSetup, mockSelfTest } = vi.hoisted(() => ({
  mockGetStatus: vi.fn(),
  mockSetup: vi.fn(),
  mockSelfTest: vi.fn(),
}));

vi.mock("@/api/modules/extension", () => ({
  extensionApi: {
    getStatus: mockGetStatus,
    setup: mockSetup,
    selfTest: mockSelfTest,
  },
}));

const baseStatus = {
  installed: false,
  connected: false,
  install_mode: null,
  extension_id: "nflcgkfjgoiipklkpenmbiificbakoch",
  extension_dir: "/tmp/.qwenpaw/chrome-extension/qwenpaw-browser-bridge",
  native_manifest_path: "/tmp/NativeMessagingHosts/com.qwenpaw.browser.json",
  native_host_path: "/tmp/.qwenpaw/bin/qwenpaw-nm-host",
  config_path: "/tmp/.qwenpaw/nm-bridge.json",
  ws_url: "ws://127.0.0.1:8088/ws/browser-bridge",
  chrome_extensions_url: "chrome://extensions",
  cws_url:
    "https://chromewebstore.google.com/detail/qwenpaw-browser-bridge/nflcgkfjgoiipklkpenmbiificbakoch",
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
    event_count: 3,
    session_count: 1,
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

describe("BrowserExtensionPage", () => {
  beforeEach(() => {
    mockGetStatus.mockResolvedValue(baseStatus);
    mockSetup.mockResolvedValue({
      ...baseStatus,
      connected: false,
      installed: true,
      install_mode: "cws",
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
    vi.spyOn(window, "open").mockImplementation(() => null);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  it("shows a focused CWS hero before installation and hides technical details by default", async () => {
    renderWithProviders(<BrowserExtensionPage />, {
      initialEntries: ["/browser-extension"],
    });

    expect(
      await screen.findByRole("heading", { name: "Browser Bridge" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Install from Chrome Web Store" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Developer Options")).toBeInTheDocument();
    expect(screen.queryByText("Extension folder")).not.toBeInTheDocument();
    expect(
      screen.queryByText("ws://127.0.0.1:8088/ws/browser-bridge"),
    ).not.toBeInTheDocument();
    expect(screen.getByText("browser_bridge_disconnected")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Reload the extension or reopen the target browser tab.",
      ),
    ).toBeInTheDocument();
  });

  it("prepares CWS native messaging and opens Chrome Web Store from the primary CTA", async () => {
    renderWithProviders(<BrowserExtensionPage />, {
      initialEntries: ["/browser-extension"],
    });

    await userEvent.click(
      await screen.findByRole("button", {
        name: "Install from Chrome Web Store",
      }),
    );

    await waitFor(() => {
      expect(mockSetup).toHaveBeenCalledWith(
        expect.objectContaining({
          install_mode: "cws",
          reset: false,
          ws_url: expect.stringMatching(/^ws:\/\/.+\/ws\/browser-bridge$/),
        }),
      );
    });
    expect(window.open).toHaveBeenCalledWith(
      "https://chromewebstore.google.com/detail/qwenpaw-browser-bridge/nflcgkfjgoiipklkpenmbiificbakoch",
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("auto-polls while installed but not connected and reveals troubleshooting tips after delay", async () => {
    vi.useFakeTimers();
    mockGetStatus.mockResolvedValue({
      ...baseStatus,
      installed: true,
      install_mode: "unpacked",
    });

    renderWithProviders(<BrowserExtensionPage />, {
      initialEntries: ["/browser-extension"],
    });

    await act(async () => {
      await Promise.resolve();
    });

    expect(
      screen.getByText("Waiting for Chrome to connect"),
    ).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(3000);
      await Promise.resolve();
    });

    expect(mockGetStatus).toHaveBeenCalledTimes(2);

    await act(async () => {
      vi.advanceTimersByTime(7000);
      await Promise.resolve();
    });

    expect(
      screen.getByText("Make sure Developer mode is enabled."),
    ).toBeInTheDocument();
  });

  it("shows a success view with usage examples when connected", async () => {
    mockGetStatus.mockResolvedValue({
      ...baseStatus,
      installed: true,
      connected: true,
      install_mode: "unpacked",
      version: "0.1.0",
      connected_since: new Date().toISOString(),
    });

    renderWithProviders(<BrowserExtensionPage />, {
      initialEntries: ["/browser-extension"],
    });

    expect(
      await screen.findByRole("heading", { name: "Browser Bridge Active" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Open the current browser page and summarize it."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Click the next actionable button on this page."),
    ).toBeInTheDocument();
    expect(screen.getByText("Extension version")).toBeInTheDocument();
    expect(screen.getByText("Trace events")).toBeInTheDocument();
    expect(screen.getByText("3 across 1 session")).toBeInTheDocument();
  });

  it("runs browser control self-test from the shared readiness panel", async () => {
    renderWithProviders(<BrowserExtensionPage />, {
      initialEntries: ["/browser-extension"],
    });

    await userEvent.click(
      await screen.findByRole("button", { name: "Run Self-Test" }),
    );

    await waitFor(() => {
      expect(mockSelfTest).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByText("Self-test passed")).toBeInTheDocument();
  });

  it("keeps paths and reset actions inside collapsed developer options", async () => {
    renderWithProviders(<BrowserExtensionPage />, {
      initialEntries: ["/browser-extension"],
    });

    await userEvent.click(await screen.findByText("Developer Options"));

    expect(screen.getByText("Extension folder")).toBeInTheDocument();
    expect(
      screen.getByText("/tmp/.qwenpaw/chrome-extension/qwenpaw-browser-bridge"),
    ).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Regenerate Files" }),
    );

    await waitFor(() => {
      expect(mockSetup).toHaveBeenCalledWith(
        expect.objectContaining({
          install_mode: "unpacked",
          reset: false,
        }),
      );
    });
  });
});

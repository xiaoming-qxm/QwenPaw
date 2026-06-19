import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import BrowserExtensionPage from "./index";

const { mockGetStatus, mockSetup } = vi.hoisted(() => ({
  mockGetStatus: vi.fn(),
  mockSetup: vi.fn(),
}));

vi.mock("@/api/modules/extension", () => ({
  extensionApi: {
    getStatus: mockGetStatus,
    setup: mockSetup,
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
  ws_url: "ws://127.0.0.1:8088/ws/nm-bridge",
  chrome_extensions_url: "chrome://extensions",
  cws_url:
    "https://chromewebstore.google.com/detail/qwenpaw-browser-bridge/nflcgkfjgoiipklkpenmbiificbakoch",
  version: null,
  connected_since: null,
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
      await screen.findByRole("heading", { name: "Browser Control" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Install from Chrome Web Store" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Developer Options")).toBeInTheDocument();
    expect(screen.queryByText("Extension folder")).not.toBeInTheDocument();
    expect(
      screen.queryByText("ws://127.0.0.1:8088/ws/nm-bridge"),
    ).not.toBeInTheDocument();
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
          ws_url: expect.stringMatching(/^ws:\/\/.+\/ws\/nm-bridge$/),
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

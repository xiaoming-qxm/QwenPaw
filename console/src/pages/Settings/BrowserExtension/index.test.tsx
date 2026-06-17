import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
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

describe("BrowserExtensionPage", () => {
  beforeEach(() => {
    mockGetStatus.mockResolvedValue({
      installed: false,
      connected: false,
      install_mode: null,
      extension_id: "nflcgkfjgoiipklkpenmbiificbakoch",
      extension_dir: "/tmp/.qwenpaw/chrome-extension/qwenpaw-browser-bridge",
      native_manifest_path:
        "/tmp/NativeMessagingHosts/com.qwenpaw.browser.json",
      native_host_path: "/tmp/.qwenpaw/bin/qwenpaw-nm-host",
      config_path: "/tmp/.qwenpaw/nm-bridge.json",
      ws_url: "ws://127.0.0.1:8088/ws/nm-bridge",
      chrome_extensions_url: "chrome://extensions",
      version: null,
      connected_since: null,
    });
    mockSetup.mockResolvedValue({
      installed: true,
      connected: false,
      install_mode: "unpacked",
      extension_id: "nflcgkfjgoiipklkpenmbiificbakoch",
      extension_dir: "/tmp/.qwenpaw/chrome-extension/qwenpaw-browser-bridge",
      native_manifest_path:
        "/tmp/NativeMessagingHosts/com.qwenpaw.browser.json",
      native_host_path: "/tmp/.qwenpaw/bin/qwenpaw-nm-host",
      config_path: "/tmp/.qwenpaw/nm-bridge.json",
      ws_url: "ws://127.0.0.1:8088/ws/nm-bridge",
      chrome_extensions_url: "chrome://extensions",
      version: null,
      connected_since: null,
    });
  });

  afterEach(() => vi.clearAllMocks());

  it("runs one-click setup and displays extension install paths", async () => {
    renderWithProviders(<BrowserExtensionPage />, {
      initialEntries: ["/browser-extension"],
    });

    expect(
      await screen.findByRole("button", { name: "Install / Refresh" }),
    ).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: "Install / Refresh" }),
    );

    await waitFor(() => {
      expect(mockSetup).toHaveBeenCalledWith(
        expect.objectContaining({
          install_mode: "unpacked",
          reset: true,
          ws_url: expect.stringMatching(/^ws:\/\/.+\/ws\/nm-bridge$/),
        }),
      );
    });
    expect(
      await screen.findByText(
        "/tmp/.qwenpaw/chrome-extension/qwenpaw-browser-bridge",
      ),
    ).toBeInTheDocument();
  });
});

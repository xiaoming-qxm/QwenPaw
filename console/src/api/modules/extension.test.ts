import { afterEach, describe, expect, it, vi } from "vitest";
import { request } from "../request";
import { extensionApi } from "./extension";

vi.mock("../request", () => ({ request: vi.fn() }));

describe("extensionApi", () => {
  afterEach(() => vi.clearAllMocks());

  it("gets Chrome extension status", async () => {
    vi.mocked(request).mockResolvedValue({
      installed: false,
      connected: false,
    });

    await extensionApi.getStatus();

    expect(request).toHaveBeenCalledWith("/browser-bridge/status");
  });

  it("runs one-click setup with install mode and reset flag", async () => {
    vi.mocked(request).mockResolvedValue({ installed: true, connected: false });

    await extensionApi.setup({ install_mode: "unpacked", reset: true });

    expect(request).toHaveBeenCalledWith("/browser-bridge/setup", {
      method: "POST",
      body: JSON.stringify({ install_mode: "unpacked", reset: true }),
    });
  });
});

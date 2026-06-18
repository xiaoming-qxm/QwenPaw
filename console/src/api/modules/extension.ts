import { request } from "../request";

export interface ExtensionStatus {
  installed: boolean;
  connected: boolean;
  install_mode: "unpacked" | "cws" | null;
  extension_id: string;
  extension_dir: string;
  native_manifest_path: string;
  native_host_path: string;
  config_path: string;
  ws_url: string;
  chrome_extensions_url: string;
  version: string | null;
  connected_since: string | null;
}

export interface ExtensionSetupRequest {
  install_mode: "unpacked" | "cws";
  ws_url?: string;
  reset?: boolean;
}

export interface OpenChromeExtensionsResult {
  opened: boolean;
  url: string;
  error?: string | null;
}

export const extensionApi = {
  getStatus: () => request<ExtensionStatus>("/extension/status"),
  setup: (payload: ExtensionSetupRequest) =>
    request<ExtensionStatus>("/extension/setup", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  openChromeExtensionsPage: () =>
    request<OpenChromeExtensionsResult>("/extension/open-chrome-extensions", {
      method: "POST",
    }),
};

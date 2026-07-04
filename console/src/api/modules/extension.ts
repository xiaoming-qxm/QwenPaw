import { request } from "../request";
import type { BrowserDiagnostics } from "./plugin";

export type ExtensionInstallMode = "unpacked" | "cws";

export interface ExtensionStatus {
  installed: boolean;
  connected: boolean;
  install_mode: ExtensionInstallMode | string | null;
  extension_id?: string;
  extension_dir?: string;
  native_manifest_path?: string;
  native_host_path?: string;
  config_path?: string;
  ws_url?: string;
  chrome_extensions_url?: string;
  cws_url?: string;
  version?: string | null;
  connected_since?: string | null;
  sdk_diagnostics?: BrowserDiagnostics;
}

export interface ExtensionSetupRequest {
  install_mode: ExtensionInstallMode;
  ws_url?: string;
  reset?: boolean;
}

export interface OpenChromeExtensionsResult {
  opened: boolean;
  url: string;
  error?: string | null;
}

export const extensionApi = {
  getStatus(): Promise<ExtensionStatus> {
    return request<ExtensionStatus>("/extension/status");
  },

  setup(payload: ExtensionSetupRequest): Promise<ExtensionStatus> {
    return request<ExtensionStatus>("/extension/setup", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  openChromeExtensionsPage(): Promise<OpenChromeExtensionsResult> {
    return request<OpenChromeExtensionsResult>(
      "/extension/open-chrome-extensions",
      {
        method: "POST",
      },
    );
  },
};

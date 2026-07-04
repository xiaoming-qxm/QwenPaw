import { request } from "../request";
import type { BrowserDiagnostics } from "./plugin";

export type ExtensionInstallMode = "unpacked" | "cws";

export interface BrowserControlBridgeLifecycle {
  connected: boolean;
  connected_since?: string | null;
  last_connected_at?: string | null;
  last_disconnected_at?: string | null;
  last_disconnect_reason?: string;
  reconnect_count?: number;
}

export interface BrowserControlBuildFingerprint {
  git_commit?: string;
  repo_dirty?: boolean;
  frontend_fingerprint?: string;
}

export interface BrowserControlTraceSummary {
  event_count: number;
  session_count: number;
  latest_event?: {
    event_id?: string;
    session_id?: string;
    phase?: string;
    action?: string;
    status?: string;
    backend_id?: string;
    domain?: string;
  } | null;
}

export interface BrowserControlSelfTestCheck {
  name: string;
  passed: boolean;
  code: string;
  message: string;
  metadata?: Record<string, unknown>;
}

export interface BrowserControlSelfTestResult {
  status: "passed" | "failed";
  checked_at: string;
  duration_ms?: number;
  checks: BrowserControlSelfTestCheck[];
}

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
  extension_version?: string | null;
  connected_since?: string | null;
  bridge_lifecycle?: BrowserControlBridgeLifecycle;
  build_fingerprint?: BrowserControlBuildFingerprint;
  trace_summary?: BrowserControlTraceSummary;
  last_self_test?: BrowserControlSelfTestResult | null;
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

  selfTest(): Promise<BrowserControlSelfTestResult> {
    return request<BrowserControlSelfTestResult>("/extension/self-test", {
      method: "POST",
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

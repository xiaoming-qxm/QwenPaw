import { request } from "../request";
import type { BrowserDiagnostics } from "./plugin";

export type ExtensionInstallMode = "unpacked" | "cws";

export interface BrowserBridgeBridgeLifecycle {
  connected?: boolean;
  connected_since?: string | null;
  last_connected_at?: string | null;
  last_disconnected_at?: string | null;
  last_disconnect_reason?: string;
  reconnect_count?: number;
}

export interface BrowserBridgeBuildFingerprint {
  git_commit?: string;
  repo_dirty?: boolean;
  frontend_fingerprint?: string;
}

export interface BrowserBridgeBuildFreshness {
  status: string;
  message?: string;
  repair_action?: BrowserBridgeRepairAction;
}

export type BrowserBridgeRepairAction =
  | "none"
  | "reload_extension"
  | "run_setup"
  | "restart_qwenpaw"
  | "rebuild_frontend"
  | "open_chrome"
  | "login_required"
  | "approval_required"
  | "approval_denied"
  | "risk_control"
  | "retry"
  | string;

export interface BrowserBridgeNativeHostStatus {
  status: string;
  message?: string;
  repair_action?: BrowserBridgeRepairAction;
}

export interface BrowserBridgeTraceSummary {
  event_count: number;
  session_count: number;
  lifecycle?: BrowserBridgeLifecycleSummary;
  ownership_summary?: {
    counts?: Record<string, number>;
    transition_count?: number;
    latest_by_tab?: Record<string, string>;
  };
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

export interface BrowserBridgeLifecycleSummary {
  controlled_tab_count?: number;
  residual_tab_count?: number;
  last_cleanup_reason?: string;
  protected_origin_status?: string;
}

export interface BrowserBridgeCurrentTab {
  tab_id?: string;
  url?: string;
  domain?: string;
  title?: string;
  ownership?: string;
}

export interface BrowserBridgeProgressState {
  status?: string;
  action?: string;
  reason?: string;
  current_step?: string;
  recovery_action?: string;
  blocked_reason?: string;
  approval_state?: string;
}

export interface BrowserBridgeCleanupResult {
  cleanup_ok?: boolean;
  cleanup_result?: string;
  last_cleanup_reason?: string;
  controlled_tab_count?: number;
  residual_tab_count?: number;
}

export interface BrowserBridgeSelfTestCheck {
  name: string;
  passed: boolean;
  code: string;
  message: string;
  status?: "passed" | "failed" | "warning" | string;
  repair_action?: BrowserBridgeRepairAction;
  metadata?: Record<string, unknown>;
}

export interface BrowserBridgeSelfTestResult {
  status: "passed" | "failed";
  checked_at: string;
  duration_ms?: number;
  checks: BrowserBridgeSelfTestCheck[];
}

export interface ExtensionStatus {
  installed: boolean;
  connected: boolean;
  install_mode: ExtensionInstallMode | string | null;
  readiness_state?: string;
  repair_action?: BrowserBridgeRepairAction;
  native_host_status?: BrowserBridgeNativeHostStatus;
  selected_backend_id?: string | null;
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
  bridge_lifecycle?: BrowserBridgeBridgeLifecycle;
  build_fingerprint?: BrowserBridgeBuildFingerprint;
  build_freshness?: BrowserBridgeBuildFreshness;
  trace_summary?: BrowserBridgeTraceSummary;
  controlled_tab_count?: number;
  residual_tab_count?: number;
  last_cleanup_reason?: string;
  protected_origin_status?: string;
  current_tab?: BrowserBridgeCurrentTab | null;
  connection_state?: string;
  browser_progress?: BrowserBridgeProgressState | null;
  cleanup_result?: BrowserBridgeCleanupResult | null;
  last_self_test?: BrowserBridgeSelfTestResult | null;
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
    return request<ExtensionStatus>("/browser-bridge/status");
  },

  setup(payload: ExtensionSetupRequest): Promise<ExtensionStatus> {
    return request<ExtensionStatus>("/browser-bridge/setup", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  selfTest(): Promise<BrowserBridgeSelfTestResult> {
    return request<BrowserBridgeSelfTestResult>(
      "/browser-bridge/self-test",
      {
        method: "POST",
      },
    );
  },

  openChromeExtensionsPage(): Promise<OpenChromeExtensionsResult> {
    return request<OpenChromeExtensionsResult>(
      "/browser-bridge/open-chrome-extensions",
      {
        method: "POST",
      },
    );
  },
};

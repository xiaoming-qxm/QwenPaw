import { request } from "../request";
import type { BrowserDiagnostics } from "./plugin";

export type ExtensionInstallMode = "unpacked" | "cws";

export interface BrowserControlBridgeLifecycle {
  connected?: boolean;
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

export interface BrowserControlBuildFreshness {
  status: string;
  message?: string;
  repair_action?: BrowserControlRepairAction;
}

export type BrowserControlRepairAction =
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

export interface BrowserControlNativeHostStatus {
  status: string;
  message?: string;
  repair_action?: BrowserControlRepairAction;
}

export interface BrowserControlTraceSummary {
  event_count: number;
  session_count: number;
  lifecycle?: BrowserControlLifecycleSummary;
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

export interface BrowserControlLifecycleSummary {
  controlled_tab_count?: number;
  residual_tab_count?: number;
  last_cleanup_reason?: string;
  protected_origin_status?: string;
}

export interface BrowserControlCurrentTab {
  tab_id?: string;
  url?: string;
  domain?: string;
  title?: string;
  ownership?: string;
}

export interface BrowserControlProgressState {
  status?: string;
  action?: string;
  reason?: string;
  current_step?: string;
  recovery_action?: string;
  blocked_reason?: string;
  approval_state?: string;
}

export interface BrowserControlCleanupResult {
  cleanup_ok?: boolean;
  cleanup_result?: string;
  last_cleanup_reason?: string;
  controlled_tab_count?: number;
  residual_tab_count?: number;
}

export interface BrowserControlSelfTestCheck {
  name: string;
  passed: boolean;
  code: string;
  message: string;
  status?: "passed" | "failed" | "warning" | string;
  repair_action?: BrowserControlRepairAction;
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
  readiness_state?: string;
  repair_action?: BrowserControlRepairAction;
  native_host_status?: BrowserControlNativeHostStatus;
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
  bridge_lifecycle?: BrowserControlBridgeLifecycle;
  build_fingerprint?: BrowserControlBuildFingerprint;
  build_freshness?: BrowserControlBuildFreshness;
  trace_summary?: BrowserControlTraceSummary;
  controlled_tab_count?: number;
  residual_tab_count?: number;
  last_cleanup_reason?: string;
  protected_origin_status?: string;
  current_tab?: BrowserControlCurrentTab | null;
  connection_state?: string;
  browser_progress?: BrowserControlProgressState | null;
  cleanup_result?: BrowserControlCleanupResult | null;
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

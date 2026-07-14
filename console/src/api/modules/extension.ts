import { request } from "../request";
import type { BrowserDiagnostics } from "./plugin";

export type ExtensionInstallMode = "unpacked" | "cws";

export interface ChromeBridgeLifecycle {
  connected?: boolean;
  connected_since?: string | null;
  last_connected_at?: string | null;
  last_disconnected_at?: string | null;
  last_disconnect_reason?: string;
  reconnect_count?: number;
}

export interface ChromeBuildFingerprint {
  git_commit?: string;
  repo_dirty?: boolean;
  frontend_fingerprint?: string;
}

export interface ChromeBuildFreshness {
  status: string;
  message?: string;
  repair_action?: ChromeRepairAction;
}

export type ChromeRepairAction =
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

export interface ChromeNativeHostStatus {
  status: string;
  message?: string;
  repair_action?: ChromeRepairAction;
}

export interface ChromeTraceSummary {
  event_count: number;
  session_count: number;
  lifecycle?: ChromeLifecycleSummary;
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

export interface ChromeLifecycleSummary {
  controlled_tab_count?: number;
  residual_tab_count?: number;
  last_cleanup_reason?: string;
  protected_origin_status?: string;
}

export interface ChromeCurrentTab {
  tab_id?: string;
  url?: string;
  domain?: string;
  title?: string;
  ownership?: string;
}

export interface ChromeProgressState {
  status?: string;
  action?: string;
  reason?: string;
  current_step?: string;
  recovery_action?: string;
  blocked_reason?: string;
  approval_state?: string;
}

export interface ChromeCleanupResult {
  cleanup_ok?: boolean;
  cleanup_result?: string;
  last_cleanup_reason?: string;
  controlled_tab_count?: number;
  residual_tab_count?: number;
}

export interface ChromeSelfTestCheck {
  name: string;
  passed: boolean;
  code: string;
  message: string;
  status?: "passed" | "failed" | "warning" | string;
  repair_action?: ChromeRepairAction;
  metadata?: Record<string, unknown>;
}

export interface ChromeSelfTestResult {
  status: "passed" | "failed";
  checked_at: string;
  duration_ms?: number;
  checks: ChromeSelfTestCheck[];
}

export interface ExtensionStatus {
  installed: boolean;
  connected: boolean;
  install_mode: ExtensionInstallMode | string | null;
  canonical_setup_url?: string;
  setup_phase?: string;
  recommended_action?: ChromeRepairAction;
  repair_actions?: ChromeRepairAction[];
  recovery_copy?: string;
  readiness_state?: string;
  repair_action?: ChromeRepairAction;
  native_host_status?: ChromeNativeHostStatus;
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
  bridge_lifecycle?: ChromeBridgeLifecycle;
  build_fingerprint?: ChromeBuildFingerprint;
  build_freshness?: ChromeBuildFreshness;
  trace_summary?: ChromeTraceSummary;
  controlled_tab_count?: number;
  residual_tab_count?: number;
  last_cleanup_reason?: string;
  protected_origin_status?: string;
  current_tab?: ChromeCurrentTab | null;
  connection_state?: string;
  browser_progress?: ChromeProgressState | null;
  cleanup_result?: ChromeCleanupResult | null;
  last_self_test?: ChromeSelfTestResult | null;
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

export interface OpenExtensionFolderResult {
  opened: boolean;
  path: string;
  error?: string | null;
}

export const extensionApi = {
  getStatus(): Promise<ExtensionStatus> {
    return request<ExtensionStatus>("/chrome/status");
  },

  setup(payload: ExtensionSetupRequest): Promise<ExtensionStatus> {
    return request<ExtensionStatus>("/chrome/setup", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  selfTest(): Promise<ChromeSelfTestResult> {
    return request<ChromeSelfTestResult>("/chrome/self-test", {
      method: "POST",
    });
  },

  openChromeExtensionsPage(): Promise<OpenChromeExtensionsResult> {
    return request<OpenChromeExtensionsResult>(
      "/chrome/open-chrome-extensions",
      {
        method: "POST",
      },
    );
  },

  openExtensionFolder(): Promise<OpenExtensionFolderResult> {
    return request<OpenExtensionFolderResult>("/chrome/open-extension-folder", {
      method: "POST",
    });
  },
};

import type { CSSProperties } from "react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "antd";
import {
  ClipboardList,
  Copy,
  ExternalLink,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import type { BrowserDiagnostics } from "@/api/modules/plugin";
import type {
  ChromeBridgeLifecycle,
  ChromeBuildFreshness,
  ChromeBuildFingerprint,
  ChromeCleanupResult,
  ChromeCurrentTab,
  ChromeNativeHostStatus,
  ChromeProgressState,
  ChromeRepairAction,
  ChromeSelfTestResult,
  ChromeTraceSummary,
  ChromeLifecycleSummary,
  ExtensionInstallMode,
} from "@/api/modules/extension";
import {
  browserDiagnosticHint,
  browserDiagnosticStatusLabel,
  browserDiagnosticsRows,
} from "./browserDiagnostics";

export interface ChromeReadinessStatus {
  installed?: boolean;
  connected?: boolean;
  install_mode?: ExtensionInstallMode | string | null;
  readiness_state?: string;
  repair_action?: ChromeRepairAction;
  native_host_status?: ChromeNativeHostStatus;
  selected_backend_id?: string | null;
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

interface ChromeReadinessProps {
  status: ChromeReadinessStatus | null;
  loading?: boolean;
  selfTestLoading?: boolean;
  onRefresh: () => void;
  onRunSelfTest: () => void;
  onOpenChrome: () => void;
  onCopyDiagnostics: () => void;
}

const panelStyle: CSSProperties = {
  border: "1px solid rgba(0,0,0,0.08)",
  borderRadius: 8,
  background: "#fff",
  padding: 20,
};

const headerStyle: CSSProperties = {
  display: "flex",
  alignItems: "flex-start",
  justifyContent: "space-between",
  gap: 16,
  flexWrap: "wrap",
};

const badgeStyle: CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  borderRadius: 999,
  padding: "4px 12px",
  fontSize: 13,
  fontWeight: 600,
  border: "1px solid",
};

const metricGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
  gap: 12,
  marginTop: 16,
};

const metricStyle: CSSProperties = {
  border: "1px solid rgba(0,0,0,0.06)",
  borderRadius: 8,
  padding: 12,
  background: "rgba(0,0,0,0.015)",
  minWidth: 0,
};

const labelStyle: CSSProperties = {
  color: "rgba(0,0,0,0.56)",
  fontSize: 12,
  marginBottom: 4,
};

const codeStyle: CSSProperties = {
  fontFamily:
    "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
  fontSize: 12,
  overflowWrap: "anywhere",
};

const actionsStyle: CSSProperties = {
  display: "flex",
  gap: 8,
  flexWrap: "wrap",
  alignItems: "center",
};

const diagnosticsStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 10,
  marginTop: 16,
};

export function ChromeReadiness({
  status,
  loading = false,
  selfTestLoading = false,
  onRefresh,
  onRunSelfTest,
  onOpenChrome,
  onCopyDiagnostics,
}: ChromeReadinessProps) {
  const { t } = useTranslation();
  const diagnostics = browserDiagnosticsRows(status?.sdk_diagnostics);
  const state = readinessState(status);
  const selfTest = status?.last_self_test;
  const extensionVersion = status?.extension_version || status?.version || "-";
  const build = status?.build_fingerprint;
  const trace = status?.trace_summary;
  const lifecycleSummary = lifecycleTabSummary(status);
  const lifecycle = status?.bridge_lifecycle;
  const currentTab = currentTabLabel(status?.current_tab, trace);
  const connectionState = status?.connection_state || state;
  const browserProgress = browserProgressLabel(status?.browser_progress);
  const cleanupResult = cleanupResultLabel(
    status?.cleanup_result,
    lifecycleSummary,
  );
  const selectedBackend =
    status?.selected_backend_id ||
    status?.sdk_diagnostics?.selected_backend_id ||
    "-";
  const nativeHostStatus =
    status?.native_host_status?.status || inferNativeHostStatus(status);
  const repairAction = repairActionLabel(
    t,
    status?.repair_action || status?.native_host_status?.repair_action,
  );
  const subtitle = useMemo(
    () => readinessSubtitle(t, state, lifecycle),
    [lifecycle, state, t],
  );

  return (
    <section aria-label="Chrome readiness" style={panelStyle}>
      <div style={headerStyle}>
        <div>
          <div
            style={{
              ...badgeStyle,
              ...badgeColor(state),
            }}
          >
            {stateLabel(t, state)}
          </div>
          <div
            style={{
              color: "rgba(0,0,0,0.62)",
              fontSize: 14,
              lineHeight: 1.5,
              marginTop: 8,
            }}
          >
            {subtitle}
          </div>
          {repairAction ? (
            <div
              style={{
                color: "rgba(0,0,0,0.74)",
                fontSize: 13,
                fontWeight: 600,
                marginTop: 6,
              }}
            >
              {repairAction}
            </div>
          ) : null}
        </div>
        <div style={actionsStyle}>
          <Button
            icon={<RefreshCw size={14} />}
            loading={loading}
            onClick={onRefresh}
          >
            {t("common.refresh", "Refresh")}
          </Button>
          <Button
            icon={<ClipboardList size={14} />}
            loading={selfTestLoading}
            onClick={onRunSelfTest}
          >
            {t("chrome.actions.runSelfTest", "Run Self-Test")}
          </Button>
          <Button icon={<ExternalLink size={14} />} onClick={onOpenChrome}>
            {t("chrome.actions.openChrome", "Open Chrome")}
          </Button>
          <Button icon={<Copy size={14} />} onClick={onCopyDiagnostics}>
            {t("chrome.actions.copyDiagnostics", "Copy Diagnostics")}
          </Button>
        </div>
      </div>

      <div style={metricGridStyle}>
        <Metric
          label={t(
            "chrome.readiness.extensionVersion",
            "Extension version",
          )}
          value={extensionVersion}
        />
        <Metric
          label={t(
            "chrome.readiness.selectedBackend",
            "Selected backend",
          )}
          value={selectedBackend}
        />
        <Metric
          label={t("chrome.readiness.currentTab", "Current tab")}
          value={currentTab}
        />
        <Metric
          label={t("chrome.readiness.connection", "Connection")}
          value={connectionState}
        />
        <Metric
          label={t("chrome.readiness.progress", "Progress")}
          value={browserProgress}
        />
        <Metric
          label={t("chrome.readiness.nativeHost", "Native host")}
          value={nativeHostStatus}
        />
        <Metric
          label={t("chrome.readiness.backendCommit", "Backend commit")}
          value={build?.git_commit || "-"}
        />
        <Metric
          label={t("chrome.readiness.traceEvents", "Trace events")}
          value={traceSummary(trace)}
        />
        <Metric
          label={t("chrome.readiness.buildFreshness", "Build freshness")}
          value={buildFreshnessLabel(t, status?.build_freshness, build)}
        />
        <Metric
          label={t("chrome.readiness.controlledTabs", "Controlled tabs")}
          value={String(lifecycleSummary.controlled_tab_count ?? 0)}
        />
        <Metric
          label={t("chrome.readiness.residualTabs", "Residual tabs")}
          value={String(lifecycleSummary.residual_tab_count ?? 0)}
        />
        <Metric
          label={t("chrome.readiness.lastCleanup", "Last cleanup")}
          value={lifecycleSummary.last_cleanup_reason || "-"}
        />
        <Metric
          label={t("chrome.readiness.cleanupResult", "Cleanup result")}
          value={cleanupResult}
        />
        <Metric
          label={t(
            "chrome.readiness.protectedOrigin",
            "Protected origin",
          )}
          value={lifecycleSummary.protected_origin_status || "clear"}
        />
      </div>

      {selfTest ? <SelfTestResult result={selfTest} /> : null}

      {diagnostics.length ? (
        <div style={diagnosticsStyle}>
          <div style={{ fontWeight: 600 }}>
            {t("chrome.diagnostics.title", "SDK diagnostics")}
          </div>
          {diagnostics.map((backend) => (
            <div
              key={`${backend.backend_id}:${backend.code || backend.status}`}
              style={{
                display: "grid",
                gridTemplateColumns: "minmax(150px, 1fr) minmax(0, 2fr)",
                gap: 10,
                alignItems: "start",
              }}
            >
              <div>
                <div style={{ fontWeight: 500 }}>{backend.backend_id}</div>
                <div style={{ color: "rgba(0,0,0,0.56)", fontSize: 12 }}>
                  {browserDiagnosticStatusLabel(t, backend)}
                </div>
              </div>
              <div>
                {backend.code ? (
                  <div style={codeStyle}>{backend.code}</div>
                ) : null}
                <div style={{ color: "rgba(0,0,0,0.68)" }}>
                  {browserDiagnosticHint(t, backend)}
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div style={metricStyle}>
      <div style={labelStyle}>{label}</div>
      <div style={codeStyle}>{value}</div>
    </div>
  );
}

function SelfTestResult({ result }: { result: ChromeSelfTestResult }) {
  const { t } = useTranslation();
  const failedChecks = result.checks.filter((check) => !check.passed);
  const passed = result.status === "passed";
  return (
    <div
      style={{
        marginTop: 16,
        border: `1px solid ${
          passed ? "rgba(82,196,26,0.32)" : "rgba(255,77,79,0.32)"
        }`,
        borderRadius: 8,
        padding: 12,
        background: passed ? "rgba(82,196,26,0.08)" : "rgba(255,77,79,0.08)",
      }}
    >
      <div style={{ color: "rgba(0,0,0,0.56)", fontSize: 12, marginBottom: 6 }}>
        {t("chrome.readiness.lastSelfTest", "Last self-test")}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <ShieldCheck size={15} />
        <strong>
          {passed
            ? t("chrome.selfTest.passed", "Self-test passed")
            : t("chrome.selfTest.failed", "Self-test failed")}
        </strong>
      </div>
      {failedChecks.length ? (
        <div style={{ ...diagnosticsStyle, marginTop: 10 }}>
          {failedChecks.map((check) => (
            <div key={check.name}>
              <div style={codeStyle}>{check.code}</div>
              <div style={{ color: "rgba(0,0,0,0.68)" }}>{check.message}</div>
              {check.repair_action ? (
                <div
                  style={{
                    color: "rgba(0,0,0,0.74)",
                    fontSize: 12,
                    fontWeight: 600,
                    marginTop: 4,
                  }}
                >
                  {repairActionLabel(t, check.repair_action)}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function readinessState(
  status: ChromeReadinessStatus | null,
): "connected" | "waiting" | "notStarted" {
  if (status?.connected) return "connected";
  if (status?.installed) return "waiting";
  return "notStarted";
}

function stateLabel(
  t: ReturnType<typeof useTranslation>["t"],
  state: "connected" | "waiting" | "notStarted",
) {
  if (state === "connected") {
    return t("chrome.status.connected", "Connected");
  }
  if (state === "waiting") {
    return t("chrome.status.waiting", "Waiting for Chrome");
  }
  return t("chrome.status.notStarted", "Setup required");
}

function readinessSubtitle(
  t: ReturnType<typeof useTranslation>["t"],
  state: "connected" | "waiting" | "notStarted",
  lifecycle?: ChromeBridgeLifecycle,
) {
  if (state === "connected") {
    return lifecycle?.connected_since
      ? t(
          "chrome.readiness.connectedSince",
          "Chrome bridge is connected since {{time}}.",
          { time: lifecycle.connected_since },
        )
      : t("chrome.readiness.connected", "Chrome bridge is connected.");
  }
  if (state === "waiting") {
    return t(
      "chrome.status.waitingDesc",
      "Open or reload the Chrome extension.",
    );
  }
  return t(
    "chrome.readiness.setupRequired",
    "Install or prepare the Chrome extension bridge.",
  );
}

function badgeColor(state: "connected" | "waiting" | "notStarted") {
  if (state === "connected") {
    return {
      color: "#237804",
      background: "rgba(82,196,26,0.12)",
      borderColor: "rgba(82,196,26,0.36)",
    };
  }
  if (state === "waiting") {
    return {
      color: "#ad6800",
      background: "rgba(250,173,20,0.12)",
      borderColor: "rgba(250,173,20,0.34)",
    };
  }
  return {
    color: "#b44d04",
    background: "rgba(255,127,22,0.1)",
    borderColor: "rgba(255,127,22,0.34)",
  };
}

function traceSummary(trace?: ChromeTraceSummary): string {
  const events = trace?.event_count ?? 0;
  const sessions = trace?.session_count ?? 0;
  return `${events} across ${sessions} ${
    sessions === 1 ? "session" : "sessions"
  }`;
}

function lifecycleTabSummary(
  status: ChromeReadinessStatus | null,
): ChromeLifecycleSummary {
  const traceLifecycle = status?.trace_summary?.lifecycle || {};
  return {
    controlled_tab_count:
      status?.controlled_tab_count ?? traceLifecycle.controlled_tab_count ?? 0,
    residual_tab_count:
      status?.residual_tab_count ?? traceLifecycle.residual_tab_count ?? 0,
    last_cleanup_reason:
      status?.last_cleanup_reason || traceLifecycle.last_cleanup_reason || "",
    protected_origin_status:
      status?.protected_origin_status ||
      traceLifecycle.protected_origin_status ||
      "clear",
  };
}

function currentTabLabel(
  currentTab?: ChromeCurrentTab | null,
  trace?: ChromeTraceSummary,
): string {
  const latest = trace?.latest_event;
  const tabId = currentTab?.tab_id || "";
  const domain = currentTab?.domain || latest?.domain || "";
  const title = currentTab?.title || "";
  const url = currentTab?.url || "";
  const ownership = currentTab?.ownership || "";
  const primary = domain || title || url || tabId;
  if (!primary) return "-";
  const suffix = [tabId, ownership].filter(Boolean).join(", ");
  return suffix ? `${primary} (${suffix})` : primary;
}

function browserProgressLabel(
  progress?: ChromeProgressState | null,
): string {
  if (!progress) return "-";
  return (
    progress.current_step ||
    progress.recovery_action ||
    progress.blocked_reason ||
    progress.reason ||
    progress.action ||
    progress.status ||
    "-"
  );
}

function cleanupResultLabel(
  cleanup?: ChromeCleanupResult | null,
  lifecycle?: ChromeLifecycleSummary,
): string {
  if (cleanup?.cleanup_result) return cleanup.cleanup_result;
  if (cleanup?.last_cleanup_reason) return cleanup.last_cleanup_reason;
  if (cleanup?.cleanup_ok === true) return "ok";
  if (cleanup?.cleanup_ok === false) return "failed";
  return lifecycle?.last_cleanup_reason || "-";
}

function buildFreshnessLabel(
  t: ReturnType<typeof useTranslation>["t"],
  freshness?: ChromeBuildFreshness,
  build?: ChromeBuildFingerprint,
): string {
  if (freshness?.status) {
    if (freshness.status === "stale") {
      return t("chrome.readiness.buildDirty", "Build has local changes");
    }
    if (freshness.status === "fresh") {
      return t("chrome.readiness.buildClean", "Clean");
    }
    return (
      freshness.message || t("chrome.readiness.buildUnknown", "Unknown")
    );
  }
  if (build?.repo_dirty) {
    return t("chrome.readiness.buildDirty", "Build has local changes");
  }
  if (!build?.git_commit) {
    return t("chrome.readiness.buildUnknown", "Unknown");
  }
  return t("chrome.readiness.buildClean", "Clean");
}

function inferNativeHostStatus(
  status: ChromeReadinessStatus | null,
): string {
  if (!status?.installed) {
    return "missing";
  }
  return status.native_host_status?.status || "configured";
}

function repairActionLabel(
  t: ReturnType<typeof useTranslation>["t"],
  action?: ChromeRepairAction | null,
): string {
  switch (action) {
    case "reload_extension":
      return t("chrome.repair.reloadExtension", "Reload extension");
    case "run_setup":
      return t("chrome.repair.runSetup", "Run setup");
    case "restart_qwenpaw":
      return t("chrome.repair.restartQwenPaw", "Restart QwenPaw");
    case "rebuild_frontend":
      return t("chrome.repair.rebuildFrontend", "Rebuild frontend");
    case "open_chrome":
      return t("chrome.repair.openChrome", "Open Chrome");
    case "login_required":
      return t("chrome.repair.loginRequired", "Sign in to the site");
    case "approval_required":
      return t("chrome.repair.approvalRequired", "Review approval");
    case "approval_denied":
      return t("chrome.repair.approvalDenied", "Approval was denied");
    case "risk_control":
      return t("chrome.repair.riskControl", "Review site risk");
    case "retry":
      return t("chrome.repair.retry", "Try again");
    default:
      return "";
  }
}

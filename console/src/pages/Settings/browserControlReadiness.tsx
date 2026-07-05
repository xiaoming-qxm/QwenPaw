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
  BrowserControlBridgeLifecycle,
  BrowserControlBuildFreshness,
  BrowserControlBuildFingerprint,
  BrowserControlNativeHostStatus,
  BrowserControlRepairAction,
  BrowserControlSelfTestResult,
  BrowserControlTraceSummary,
  ExtensionInstallMode,
} from "@/api/modules/extension";
import {
  browserDiagnosticHint,
  browserDiagnosticStatusLabel,
  browserDiagnosticsRows,
} from "./browserDiagnostics";

export interface BrowserControlReadinessStatus {
  installed?: boolean;
  connected?: boolean;
  install_mode?: ExtensionInstallMode | string | null;
  readiness_state?: string;
  repair_action?: BrowserControlRepairAction;
  native_host_status?: BrowserControlNativeHostStatus;
  selected_backend_id?: string | null;
  version?: string | null;
  extension_version?: string | null;
  connected_since?: string | null;
  bridge_lifecycle?: BrowserControlBridgeLifecycle;
  build_fingerprint?: BrowserControlBuildFingerprint;
  build_freshness?: BrowserControlBuildFreshness;
  trace_summary?: BrowserControlTraceSummary;
  last_self_test?: BrowserControlSelfTestResult | null;
  sdk_diagnostics?: BrowserDiagnostics;
}

interface BrowserControlReadinessProps {
  status: BrowserControlReadinessStatus | null;
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

export function BrowserControlReadiness({
  status,
  loading = false,
  selfTestLoading = false,
  onRefresh,
  onRunSelfTest,
  onOpenChrome,
  onCopyDiagnostics,
}: BrowserControlReadinessProps) {
  const { t } = useTranslation();
  const diagnostics = browserDiagnosticsRows(status?.sdk_diagnostics);
  const state = readinessState(status);
  const selfTest = status?.last_self_test;
  const extensionVersion = status?.extension_version || status?.version || "-";
  const build = status?.build_fingerprint;
  const trace = status?.trace_summary;
  const lifecycle = status?.bridge_lifecycle;
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
    <section aria-label="Browser Control readiness" style={panelStyle}>
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
            {t("browserControl.actions.runSelfTest", "Run Self-Test")}
          </Button>
          <Button icon={<ExternalLink size={14} />} onClick={onOpenChrome}>
            {t("browserControl.actions.openChrome", "Open Chrome")}
          </Button>
          <Button icon={<Copy size={14} />} onClick={onCopyDiagnostics}>
            {t("browserControl.actions.copyDiagnostics", "Copy Diagnostics")}
          </Button>
        </div>
      </div>

      <div style={metricGridStyle}>
        <Metric
          label={t(
            "browserControl.readiness.extensionVersion",
            "Extension version",
          )}
          value={extensionVersion}
        />
        <Metric
          label={t(
            "browserControl.readiness.selectedBackend",
            "Selected backend",
          )}
          value={selectedBackend}
        />
        <Metric
          label={t("browserControl.readiness.nativeHost", "Native host")}
          value={nativeHostStatus}
        />
        <Metric
          label={t("browserControl.readiness.backendCommit", "Backend commit")}
          value={build?.git_commit || "-"}
        />
        <Metric
          label={t("browserControl.readiness.traceEvents", "Trace events")}
          value={traceSummary(trace)}
        />
        <Metric
          label={t(
            "browserControl.readiness.buildFreshness",
            "Build freshness",
          )}
          value={buildFreshnessLabel(t, status?.build_freshness, build)}
        />
      </div>

      {selfTest ? <SelfTestResult result={selfTest} /> : null}

      {diagnostics.length ? (
        <div style={diagnosticsStyle}>
          <div style={{ fontWeight: 600 }}>
            {t("browserControl.diagnostics.title", "SDK diagnostics")}
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

function SelfTestResult({ result }: { result: BrowserControlSelfTestResult }) {
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
        {t("browserControl.readiness.lastSelfTest", "Last self-test")}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <ShieldCheck size={15} />
        <strong>
          {passed
            ? t("browserControl.selfTest.passed", "Self-test passed")
            : t("browserControl.selfTest.failed", "Self-test failed")}
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
  status: BrowserControlReadinessStatus | null,
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
    return t("browserControl.status.connected", "Connected");
  }
  if (state === "waiting") {
    return t("browserControl.status.waiting", "Waiting for Chrome");
  }
  return t("browserControl.status.notStarted", "Setup required");
}

function readinessSubtitle(
  t: ReturnType<typeof useTranslation>["t"],
  state: "connected" | "waiting" | "notStarted",
  lifecycle?: BrowserControlBridgeLifecycle,
) {
  if (state === "connected") {
    return lifecycle?.connected_since
      ? t(
          "browserControl.readiness.connectedSince",
          "Chrome bridge is connected since {{time}}.",
          { time: lifecycle.connected_since },
        )
      : t("browserControl.readiness.connected", "Chrome bridge is connected.");
  }
  if (state === "waiting") {
    return t(
      "browserControl.status.waitingDesc",
      "Open or reload the Chrome extension.",
    );
  }
  return t(
    "browserControl.readiness.setupRequired",
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

function traceSummary(trace?: BrowserControlTraceSummary): string {
  const events = trace?.event_count ?? 0;
  const sessions = trace?.session_count ?? 0;
  return `${events} across ${sessions} ${
    sessions === 1 ? "session" : "sessions"
  }`;
}

function buildFreshnessLabel(
  t: ReturnType<typeof useTranslation>["t"],
  freshness?: BrowserControlBuildFreshness,
  build?: BrowserControlBuildFingerprint,
): string {
  if (freshness?.status) {
    if (freshness.status === "stale") {
      return t(
        "browserControl.readiness.buildDirty",
        "Build has local changes",
      );
    }
    if (freshness.status === "fresh") {
      return t("browserControl.readiness.buildClean", "Clean");
    }
    return (
      freshness.message || t("browserControl.readiness.buildUnknown", "Unknown")
    );
  }
  if (build?.repo_dirty) {
    return t("browserControl.readiness.buildDirty", "Build has local changes");
  }
  if (!build?.git_commit) {
    return t("browserControl.readiness.buildUnknown", "Unknown");
  }
  return t("browserControl.readiness.buildClean", "Clean");
}

function inferNativeHostStatus(
  status: BrowserControlReadinessStatus | null,
): string {
  if (!status?.installed) {
    return "missing";
  }
  return status.native_host_status?.status || "configured";
}

function repairActionLabel(
  t: ReturnType<typeof useTranslation>["t"],
  action?: BrowserControlRepairAction | null,
): string {
  switch (action) {
    case "reload_extension":
      return t("browserControl.repair.reloadExtension", "Reload extension");
    case "run_setup":
      return t("browserControl.repair.runSetup", "Run setup");
    case "restart_qwenpaw":
      return t("browserControl.repair.restartQwenPaw", "Restart QwenPaw");
    case "rebuild_frontend":
      return t("browserControl.repair.rebuildFrontend", "Rebuild frontend");
    case "open_chrome":
      return t("browserControl.repair.openChrome", "Open Chrome");
    case "login_required":
      return t("browserControl.repair.loginRequired", "Sign in to the site");
    case "approval_required":
      return t("browserControl.repair.approvalRequired", "Review approval");
    case "approval_denied":
      return t("browserControl.repair.approvalDenied", "Approval was denied");
    case "risk_control":
      return t("browserControl.repair.riskControl", "Review site risk");
    case "retry":
      return t("browserControl.repair.retry", "Try again");
    default:
      return "";
  }
}

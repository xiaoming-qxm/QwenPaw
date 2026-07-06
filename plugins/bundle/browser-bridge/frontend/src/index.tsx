// Browser Bridge plugin UI. React and antd are provided by the QwenPaw
// console host, so this bundle only contains the plugin page itself.
import type * as ReactNS from "react";

import {
  resolveBrowserBridgeLocale,
  t as translate,
  type BrowserBridgeLocale,
  type MessageKey,
} from "./locale";

const host = window.QwenPaw.host;
const React: typeof ReactNS = host.React;
const antd = host.antd;
const getApiUrl = host.getApiUrl;
const getApiToken = host.getApiToken;

const {
  Alert,
  Button,
  Card,
  Checkbox,
  Collapse,
  Space,
  Spin,
  Steps,
  Typography,
  message,
} = antd;
const { Paragraph, Text, Title } = Typography;

type InstallMode = "unpacked" | "cws";
type LifecycleState =
  | "preparing"
  | "needs_load_unpacked"
  | "extension_loaded_bridge_disconnected"
  | "repairing"
  | "connected"
  | "failed_actionable";
type StatusKey =
  | "extension_dir"
  | "native_manifest_path"
  | "native_host_path"
  | "config_path";

interface ExtensionStatus {
  installed: boolean;
  connected: boolean;
  install_mode: InstallMode | string | null;
  extension_id?: string;
  extension_dir?: string;
  native_manifest_path?: string;
  native_host_path?: string;
  config_path?: string;
  canonical_setup_url?: string;
  setup_phase?: string;
  recommended_action?: string;
  repair_actions?: string[];
  recovery_copy?: string;
  ws_url?: string;
  chrome_extensions_url?: string;
  version?: string | null;
  connected_since?: string | null;
  build_freshness?: { status?: string; repair_action?: string };
  native_host_status?: { status?: string; repair_action?: string };
  sdk_diagnostics?: BrowserDiagnostics;
}

type BrowserDiagnosticStatus = "available" | "degraded" | "unavailable";

interface BrowserDiagnosticCheck {
  name: string;
  status: BrowserDiagnosticStatus;
  message: string;
  hint_key?: string | null;
  message_fallback?: string | null;
  metadata?: Record<string, unknown>;
}

interface BrowserBackendDiagnostic {
  backend_id: string;
  browser_context: "auto" | "isolated" | "user";
  available: boolean;
  status: BrowserDiagnosticStatus;
  code?: string | null;
  reason?: string | null;
  message: string;
  hint_key?: string | null;
  message_fallback?: string | null;
  features: string[];
  checks?: BrowserDiagnosticCheck[];
  observed_at?: string | null;
  metadata?: Record<string, unknown>;
}

interface BrowserDiagnostics {
  requested_context: "auto" | "isolated" | "user";
  selected_backend_id?: string | null;
  backends: BrowserBackendDiagnostic[];
}

interface ExtensionSetupRequest {
  install_mode: InstallMode;
  ws_url?: string;
  reset?: boolean;
}

interface OpenChromeExtensionsResult {
  opened: boolean;
  url: string;
  error?: string | null;
}

interface OpenExtensionFolderResult {
  opened: boolean;
  path: string;
  error?: string | null;
}

type AcceptanceRunStatus =
  | "queued"
  | "running"
  | "passed"
  | "failed"
  | "blocked"
  | "cancelled";

interface AcceptanceScenarioProgress {
  scenario: string;
  status: AcceptanceRunStatus | string;
  failure_category?: string;
  recovery_hint?: string;
  repair_action?: string;
}

interface AcceptanceRun {
  run_id: string;
  status: AcceptanceRunStatus | string;
  started_at: string;
  completed_at?: string | null;
  scenario_progress: AcceptanceScenarioProgress[];
  live_taobao: boolean;
  cancel_requested?: boolean;
  report_json_path?: string;
  report_markdown_path?: string;
  error?: string;
}

interface AcceptanceReportResponse {
  run_id: string;
  json: {
    status?: string;
    scenario_reports?: AcceptanceScenarioProgress[];
    [key: string]: unknown;
  };
  markdown: string;
  report_json_path?: string;
  report_markdown_path?: string;
}

interface AcceptanceRunPayload {
  base_url?: string;
  port?: number;
  live_taobao: boolean;
}

interface ExtensionProbeStatus {
  ok?: boolean;
  connected?: boolean;
  version?: string;
  nativeHost?: string;
  managedTabsCount?: number;
  reconnectAttempts?: number;
  lastDisconnectReason?: string;
  reloading?: boolean;
  error?: string;
}

interface ChromeRuntimeForProbe {
  lastError?: { message?: string };
  sendMessage?: (
    extensionId: string,
    payload: { method: string },
    callback: (response?: ExtensionProbeStatus) => void,
  ) => void;
}

declare const chrome:
  | {
      runtime?: ChromeRuntimeForProbe;
    }
  | undefined;

interface PathRow {
  key: StatusKey;
  label: string;
}

const styles: Record<string, ReactNS.CSSProperties> = {
  page: {
    display: "flex",
    flexDirection: "column",
    height: "100%",
    minHeight: 0,
    overflow: "hidden",
  },
  header: {
    padding: "16px 20px 12px",
    borderBottom: "1px solid rgba(0,0,0,0.06)",
  },
  headerTitleRow: {
    display: "flex",
    alignItems: "center",
    gap: 12,
  },
  headerIcon: {
    width: 44,
    height: 44,
    borderRadius: 12,
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    flexShrink: 0,
    background: "#fff",
    border: "1px solid rgba(0,0,0,0.12)",
    color: "rgba(0,0,0,0.78)",
  },
  headerText: {
    minWidth: 0,
  },
  content: {
    flex: 1,
    minHeight: 0,
    overflowY: "auto",
    padding: 16,
    display: "flex",
    flexDirection: "column",
    gap: 16,
  },
  centeredCard: {
    width: "min(100%, 720px)",
    margin: "0 auto",
    borderRadius: 8,
  },
  heroCard: {
    width: "min(100%, 600px)",
    margin: "0 auto",
    borderRadius: 8,
    textAlign: "center",
  },
  iconCircle: {
    width: 64,
    height: 64,
    borderRadius: "50%",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 12,
    background: "#fff",
    border: "1px solid rgba(0,0,0,0.12)",
    color: "rgba(0,0,0,0.78)",
  },
  successCircle: {
    width: 64,
    height: 64,
    borderRadius: "50%",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 12,
    color: "#389e0d",
    background: "rgba(82, 196, 26, 0.12)",
    fontSize: 30,
    fontWeight: 700,
  },
  heroActions: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
    flexWrap: "wrap",
  },
  progressBody: {
    textAlign: "center",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    gap: 8,
    margin: "22px 0",
  },
  readyMeta: {
    margin: "18px 0 20px",
    display: "flex",
    justifyContent: "center",
    gap: 16,
    flexWrap: "wrap",
  },
  usageSection: {
    margin: "18px 0 22px",
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  usageList: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
    gap: 10,
    textAlign: "left",
  },
  usageItem: {
    minHeight: 72,
    padding: 12,
    border: "1px solid rgba(0,0,0,0.06)",
    borderRadius: 8,
    background: "rgba(0,0,0,0.02)",
    overflowWrap: "anywhere",
  },
  acceptancePanel: {
    width: "min(100%, 720px)",
    margin: "0 auto",
    borderRadius: 8,
  },
  acceptanceActions: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    gap: 8,
  },
  acceptanceScenarioList: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
    gap: 10,
  },
  acceptanceScenarioCard: {
    minHeight: 124,
    padding: 12,
    borderRadius: 8,
    border: "1px solid rgba(0,0,0,0.08)",
    background: "#fff",
    display: "flex",
    flexDirection: "column",
    gap: 6,
  },
  acceptanceScenarioHeader: {
    display: "flex",
    justifyContent: "space-between",
    gap: 8,
  },
  acceptanceReportPreview: {
    maxHeight: 180,
    overflow: "auto",
    padding: 12,
    borderRadius: 6,
    background: "rgba(0,0,0,0.04)",
    whiteSpace: "pre-wrap",
  },
  developerPanel: {
    width: "min(100%, 920px)",
    margin: "0 auto",
    borderRadius: 8,
    overflow: "hidden",
  },
  developerContent: {
    display: "flex",
    flexDirection: "column",
    gap: 16,
  },
  modeRow: {
    display: "grid",
    gridTemplateColumns: "minmax(128px, 180px) minmax(0, 1fr)",
    alignItems: "center",
    gap: 8,
  },
  pathList: {
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  pathRow: {
    display: "grid",
    gridTemplateColumns: "minmax(128px, 180px) minmax(0, 1fr) auto",
    alignItems: "center",
    gap: 8,
  },
  pathValue: {
    minWidth: 0,
    overflowWrap: "anywhere",
    wordBreak: "break-word",
    fontFamily:
      "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    fontSize: 12,
    lineHeight: 1.45,
    background: "rgba(0,0,0,0.04)",
    border: "1px solid rgba(0,0,0,0.06)",
    borderRadius: 4,
    padding: "4px 8px",
  },
  developerActions: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    flexWrap: "wrap",
  },
  unpackedSteps: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
    padding: 12,
    border: "1px solid rgba(0,0,0,0.06)",
    borderRadius: 8,
    background: "rgba(0,0,0,0.02)",
  },
  diagnosticsPanel: {
    width: "min(100%, 720px)",
    margin: "0 auto",
    borderRadius: 8,
  },
  diagnosticsList: {
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  diagnosticRow: {
    display: "grid",
    gridTemplateColumns: "minmax(140px, 1fr) minmax(0, 2fr)",
    gap: 10,
    padding: 10,
    border: "1px solid rgba(0,0,0,0.06)",
    borderRadius: 8,
    background: "rgba(0,0,0,0.02)",
  },
  diagnosticCode: {
    display: "inline-block",
    maxWidth: "100%",
    overflowWrap: "anywhere",
    fontFamily:
      "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    fontSize: 12,
    borderRadius: 4,
    padding: "2px 6px",
    background: "rgba(0,0,0,0.05)",
    color: "rgba(0,0,0,0.76)",
  },
  diagnosticMessage: {
    display: "flex",
    minWidth: 0,
    flexDirection: "column",
    gap: 4,
  },
};

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  const token = getApiToken?.();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(getApiUrl(path), {
    ...init,
    headers: {
      ...(init?.headers || {}),
      ...authHeaders(),
    },
  });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new Error(
      typeof data?.detail === "string" ? data.detail : response.statusText,
    );
  }
  return data as T;
}

function getStatus(): Promise<ExtensionStatus> {
  return apiRequest<ExtensionStatus>("/browser-bridge/status");
}

function setupExtension(
  payload: ExtensionSetupRequest,
): Promise<ExtensionStatus> {
  return apiRequest<ExtensionStatus>("/browser-bridge/setup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function openChromeExtensionsPage(): Promise<OpenChromeExtensionsResult> {
  return apiRequest<OpenChromeExtensionsResult>(
    "/browser-bridge/open-chrome-extensions",
    {
      method: "POST",
    },
  );
}

function openExtensionFolder(): Promise<OpenExtensionFolderResult> {
  return apiRequest<OpenExtensionFolderResult>(
    "/browser-bridge/open-extension-folder",
    {
      method: "POST",
    },
  );
}

function startAcceptanceRun(
  payload: AcceptanceRunPayload,
): Promise<AcceptanceRun> {
  const defaultAcceptancePayload = { live_taobao: false };
  return apiRequest<AcceptanceRun>("/browser-bridge/acceptance-runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ...currentBackendTarget(),
      ...defaultAcceptancePayload,
      ...payload,
    }),
  });
}

function loadAcceptanceRun(runId: string): Promise<AcceptanceRun> {
  return apiRequest<AcceptanceRun>(`/browser-bridge/acceptance-runs/${runId}`);
}

function cancelAcceptanceRun(runId: string): Promise<AcceptanceRun> {
  return apiRequest<AcceptanceRun>(
    `/browser-bridge/acceptance-runs/${runId}/cancel`,
    {
      method: "POST",
    },
  );
}

function loadAcceptanceReport(
  runId: string,
): Promise<AcceptanceReportResponse> {
  return apiRequest<AcceptanceReportResponse>(
    `/browser-bridge/acceptance-runs/${runId}/report`,
  );
}

function currentBackendTarget(): Omit<AcceptanceRunPayload, "live_taobao"> {
  const baseUrl = `${window.location.protocol}//${window.location.host}`;
  const port = Number(window.location.port);
  return {
    base_url: baseUrl,
    ...(Number.isFinite(port) && port > 0 ? { port } : {}),
  };
}

function currentBridgeWsUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/browser-bridge`;
}

function shouldAutoPrepare(status: ExtensionStatus | null): boolean {
  if (!status) {
    return false;
  }
  return (
    !status.installed ||
    status.recommended_action === "setup_extension" ||
    status.setup_phase === "setup_missing" ||
    status.setup_phase === "native_host_repair_required" ||
    status.setup_phase === "stale_build"
  );
}

function shouldResetForRepair(status: ExtensionStatus | null): boolean {
  if (!status) {
    return false;
  }
  return (
    status.setup_phase === "native_host_repair_required" ||
    status.native_host_status?.status === "repair_required"
  );
}

function deriveLifecycleState(
  status: ExtensionStatus | null,
  probe: ExtensionProbeStatus | null,
  busy: boolean,
  error: string | null,
): LifecycleState {
  if (error) {
    return "failed_actionable";
  }
  if (busy && !status) {
    return "preparing";
  }
  if (busy && status && shouldAutoPrepare(status)) {
    return "repairing";
  }
  if (status?.connected) {
    return "connected";
  }
  if (probe?.ok) {
    return "extension_loaded_bridge_disconnected";
  }
  if (status?.installed) {
    return "needs_load_unpacked";
  }
  return busy ? "preparing" : "failed_actionable";
}

function probeExtension(
  extensionId: string | undefined,
  method: "status.get" | "bridge.connect" | "extension.reload",
): Promise<ExtensionProbeStatus | null> {
  if (
    !extensionId ||
    typeof chrome === "undefined" ||
    !chrome.runtime ||
    !chrome.runtime.sendMessage
  ) {
    return Promise.resolve(null);
  }
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(extensionId, { method }, (response) => {
      const error = chrome.runtime?.lastError?.message;
      if (error) {
        resolve({ ok: false, error });
        return;
      }
      resolve(response || null);
    });
  });
}

const diagnosticHintKeys = new Set<MessageKey>([
  "browser_bridge_disconnected",
  "browser_backend_unavailable",
  "browser_bridge_action_runtime_missing",
  "isolated_backend_unavailable",
]);

function diagnosticRows(
  status: ExtensionStatus | null,
): BrowserBackendDiagnostic[] {
  return (status?.sdk_diagnostics?.backends ?? []).filter(
    (backend) => backend.code || backend.status !== "available",
  );
}

function diagnosticHint(
  backend: BrowserBackendDiagnostic,
  locale: BrowserBridgeLocale,
) {
  const hintKey = backend.hint_key || backend.code;
  if (hintKey && diagnosticHintKeys.has(hintKey as MessageKey)) {
    return translate(locale, hintKey as MessageKey);
  }
  return (
    backend.message_fallback ||
    backend.message ||
    backend.reason ||
    backend.code ||
    backend.backend_id
  );
}

function diagnosticStatusLabel(
  status: BrowserDiagnosticStatus,
  locale: BrowserBridgeLocale,
) {
  if (status === "available") {
    return translate(locale, "diagnosticAvailable");
  }
  if (status === "degraded") {
    return translate(locale, "diagnosticDegraded");
  }
  return translate(locale, "diagnosticUnavailable");
}

function normalizeCollapseKeys(keys: unknown) {
  return Array.isArray(keys) ? keys : keys ? [String(keys)] : [];
}

function BrowserBridgeLogo({ size = 38 }: { size?: number }) {
  return (
    <svg
      aria-hidden="true"
      fill="none"
      focusable="false"
      height={size}
      style={{ display: "block" }}
      viewBox="0 0 38 38"
      width={size}
    >
      <rect
        fill="none"
        height="25"
        rx="6"
        stroke="currentColor"
        strokeWidth="2"
        width="30"
        x="4"
        y="6"
      />
      <path d="M4 13H34" stroke="currentColor" strokeWidth="2" />
      <circle cx="9" cy="9.5" fill="currentColor" r="1.2" />
      <circle cx="13" cy="9.5" fill="currentColor" opacity="0.62" r="1.2" />
      <path
        d="M18.5 17.5L29.5 22.1L24.8 24L28 30.1L25.3 31.5L22.1 25.5L18.5 29.2V17.5Z"
        fill="currentColor"
      />
    </svg>
  );
}

function DiagnosticsPanel({
  locale,
  status,
}: {
  locale: BrowserBridgeLocale;
  status: ExtensionStatus | null;
}) {
  const rows = diagnosticRows(status);

  if (!rows.length) {
    return null;
  }

  return (
    <Card style={styles.diagnosticsPanel}>
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        <Text strong>{translate(locale, "diagnosticsTitle")}</Text>
        <div style={styles.diagnosticsList}>
          {rows.map((backend) => (
            <div
              key={`${backend.backend_id}:${backend.code || backend.status}`}
              style={styles.diagnosticRow}
            >
              <div>
                <Text strong>{backend.backend_id}</Text>
                <br />
                <Text type="secondary">
                  {diagnosticStatusLabel(backend.status, locale)}
                </Text>
              </div>
              <div style={styles.diagnosticMessage}>
                {backend.code ? (
                  <code style={styles.diagnosticCode}>{backend.code}</code>
                ) : null}
                <Text>{diagnosticHint(backend, locale)}</Text>
              </div>
            </div>
          ))}
        </div>
      </Space>
    </Card>
  );
}

function BrowserBridgeRouteIcon() {
  return (
    <span
      style={{
        display: "inline-block",
        filter: "grayscale(1) contrast(1.08)",
        lineHeight: 1,
        WebkitFilter: "grayscale(1) contrast(1.08)",
      }}
    >
      🌐
    </span>
  );
}

function formatConnectedSince(
  value: string | null | undefined,
  locale: BrowserBridgeLocale,
) {
  if (!value) {
    return translate(locale, "justNow");
  }

  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) {
    return translate(locale, "justNow");
  }

  const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (seconds < 60) {
    return translate(locale, "justNow");
  }

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return translate(locale, "minutesAgo", { count: minutes });
  }

  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return translate(locale, "hoursAgo", { count: hours });
  }

  return translate(locale, "daysAgo", { count: Math.floor(hours / 24) });
}

function NotInstalledView({
  locale,
  setupLoading,
  onDeveloperClick,
  onInstallCws,
}: {
  locale: BrowserBridgeLocale;
  setupLoading: boolean;
  onDeveloperClick: () => void;
  onInstallCws: () => void;
}) {
  return (
    <Card style={styles.heroCard}>
      <div style={styles.iconCircle}>
        <BrowserBridgeLogo />
      </div>
      <Title level={2}>{translate(locale, "pageTitle")}</Title>
      <Paragraph type="secondary">
        {translate(locale, "pageSubtitle")}
      </Paragraph>
      <div style={styles.heroActions}>
        <Button
          type="primary"
          size="large"
          loading={setupLoading}
          onClick={onInstallCws}
        >
          {translate(locale, "installCws")}
        </Button>
        <Button type="link" onClick={onDeveloperClick}>
          {translate(locale, "devMode")}
        </Button>
      </div>
    </Card>
  );
}

function InstalledView({
  locale,
  loading,
  showTips,
  onRefresh,
}: {
  locale: BrowserBridgeLocale;
  loading: boolean;
  showTips: boolean;
  onRefresh: () => void;
}) {
  return (
    <Card style={styles.centeredCard}>
      <Steps
        size="small"
        current={1}
        items={[
          {
            title: translate(locale, "installed"),
            status: "finish",
          },
          {
            title: translate(locale, "connecting"),
            status: "process",
          },
          {
            title: translate(locale, "ready"),
            status: "wait",
          },
        ]}
      />
      <div style={styles.progressBody}>
        <Title level={3}>{translate(locale, "waitingTitle")}</Title>
        <Paragraph type="secondary">
          {translate(locale, "waitingMessage")}
        </Paragraph>
        <Button loading={loading} onClick={onRefresh}>
          {translate(locale, "refreshStatus")}
        </Button>
      </div>
      {showTips ? (
        <Alert
          showIcon
          type="warning"
          message={translate(locale, "stillNotConnected")}
          description={
            <ul>
              <li>{translate(locale, "tipEnable")}</li>
              <li>{translate(locale, "tipClick")}</li>
              <li>{translate(locale, "tipReload")}</li>
            </ul>
          }
        />
      ) : null}
    </Card>
  );
}

function ConnectedView({
  locale,
  status,
  loading,
  onRefresh,
}: {
  locale: BrowserBridgeLocale;
  status: ExtensionStatus | null;
  loading: boolean;
  onRefresh: () => void;
}) {
  const connectedSince = formatConnectedSince(status?.connected_since, locale);
  const version = status?.version || translate(locale, "versionUnknown");

  return (
    <Card style={{ ...styles.centeredCard, textAlign: "center" }}>
      <div style={styles.successCircle}>✓</div>
      <Title level={2}>{translate(locale, "readyTitle")}</Title>
      <Steps
        size="small"
        current={2}
        items={[
          {
            title: translate(locale, "installed"),
            status: "finish",
          },
          {
            title: translate(locale, "connectedStep"),
            status: "finish",
          },
          {
            title: translate(locale, "ready"),
            status: "finish",
          },
        ]}
      />
      <div style={styles.readyMeta}>
        <Text>
          {translate(locale, "version")}: {version}
        </Text>
        <Text>
          {translate(locale, "connected")}: {connectedSince}
        </Text>
      </div>
      <div style={styles.usageSection}>
        <Text strong>{translate(locale, "usageTitle")}</Text>
        <div style={styles.usageList}>
          <div style={styles.usageItem}>{translate(locale, "example1")}</div>
          <div style={styles.usageItem}>{translate(locale, "example2")}</div>
          <div style={styles.usageItem}>{translate(locale, "example3")}</div>
        </div>
      </div>
      <Button loading={loading} onClick={onRefresh}>
        {translate(locale, "testConnection")}
      </Button>
    </Card>
  );
}

function lifecycleTitle(state: LifecycleState): MessageKey {
  if (state === "preparing") {
    return "lifecyclePreparingTitle";
  }
  if (state === "repairing") {
    return "lifecycleRepairingTitle";
  }
  if (state === "needs_load_unpacked") {
    return "lifecycleLoadUnpackedTitle";
  }
  if (state === "extension_loaded_bridge_disconnected") {
    return "lifecycleConnectTitle";
  }
  if (state === "connected") {
    return "readyTitle";
  }
  return "lifecycleFailedTitle";
}

function lifecycleDescription(state: LifecycleState): MessageKey {
  if (state === "preparing") {
    return "lifecyclePreparingDescription";
  }
  if (state === "repairing") {
    return "lifecycleRepairingDescription";
  }
  if (state === "needs_load_unpacked") {
    return "lifecycleLoadUnpackedDescription";
  }
  if (state === "extension_loaded_bridge_disconnected") {
    return "lifecycleConnectDescription";
  }
  if (state === "connected") {
    return "lifecycleConnectedDescription";
  }
  return "lifecycleFailedDescription";
}

function lifecycleStepIndex(state: LifecycleState): number {
  if (state === "connected") {
    return 2;
  }
  if (state === "needs_load_unpacked") {
    return 1;
  }
  if (state === "extension_loaded_bridge_disconnected") {
    return 1;
  }
  return 0;
}

function LifecycleWizardView({
  error,
  locale,
  primaryAction,
  state,
  status,
}: {
  error: string | null;
  locale: BrowserBridgeLocale;
  primaryAction: {
    disabled?: boolean;
    label: MessageKey;
    loading?: boolean;
    onClick: () => void;
  };
  state: LifecycleState;
  status: ExtensionStatus | null;
}) {
  const version = status?.version || translate(locale, "versionUnknown");
  const connectedSince = formatConnectedSince(status?.connected_since, locale);

  return (
    <Card style={styles.centeredCard}>
      <Steps
        size="small"
        current={lifecycleStepIndex(state)}
        items={[
          {
            title: translate(locale, "lifecycleStepPrepare"),
            status: state === "failed_actionable" ? "error" : "finish",
          },
          {
            title: translate(locale, "lifecycleStepLoad"),
            status:
              state === "needs_load_unpacked" ||
              state === "extension_loaded_bridge_disconnected"
                ? "process"
                : state === "connected"
                ? "finish"
                : "wait",
          },
          {
            title: translate(locale, "ready"),
            status: state === "connected" ? "finish" : "wait",
          },
        ]}
      />
      <div style={styles.progressBody}>
        {state === "connected" ? (
          <div style={styles.successCircle}>✓</div>
        ) : (
          <div style={styles.iconCircle}>
            <BrowserBridgeLogo />
          </div>
        )}
        <Title level={3}>{translate(locale, lifecycleTitle(state))}</Title>
        <Paragraph type="secondary">
          {translate(locale, lifecycleDescription(state))}
        </Paragraph>
        {error ? <Text type="danger">{error}</Text> : null}
        {state === "connected" ? (
          <div style={styles.readyMeta}>
            <Text>
              {translate(locale, "version")}: {version}
            </Text>
            <Text>
              {translate(locale, "connected")}: {connectedSince}
            </Text>
          </div>
        ) : null}
        <Button
          type="primary"
          size="large"
          disabled={primaryAction.disabled}
          loading={primaryAction.loading}
          onClick={primaryAction.onClick}
        >
          {translate(locale, primaryAction.label)}
        </Button>
      </div>
      {status?.recovery_copy && state !== "connected" ? (
        <Alert
          showIcon
          type={state === "failed_actionable" ? "error" : "info"}
          message={status.recovery_copy}
        />
      ) : null}
    </Card>
  );
}

function DeveloperOptions({
  locale,
  activeKey,
  loading,
  pathRows,
  setupLoading,
  status,
  onChange,
  onCopy,
  onOpenChromeExtensions,
  onOpenExtensionFolder,
  onRegenerate,
  onReloadExtension,
  onReset,
}: {
  locale: BrowserBridgeLocale;
  activeKey: string[];
  loading: boolean;
  pathRows: PathRow[];
  setupLoading: boolean;
  status: ExtensionStatus | null;
  onChange: (keys: unknown) => void;
  onCopy: (value: string) => void;
  onOpenChromeExtensions: () => void;
  onOpenExtensionFolder: () => void;
  onRegenerate: () => void;
  onReloadExtension: () => void;
  onReset: () => void;
}) {
  const wsUrl = status?.ws_url || currentBridgeWsUrl();

  return (
    <Collapse
      activeKey={activeKey}
      style={styles.developerPanel}
      onChange={onChange}
      items={[
        {
          key: "developer",
          label: (
            <Space size={8}>
              {translate(locale, "advancedDiagnosticsTitle")}
            </Space>
          ),
          children: (
            <Spin spinning={loading && !status}>
              <div style={styles.developerContent}>
                <div style={styles.modeRow}>
                  <Text type="secondary">
                    {translate(locale, "installMode")}
                  </Text>
                  <Text>{status?.install_mode || "-"}</Text>
                </div>

                <div style={styles.pathList}>
                  {pathRows.map(({ key, label }) => {
                    const value = status?.[key] || "-";
                    return (
                      <div style={styles.pathRow} key={key}>
                        <Text type="secondary">{label}</Text>
                        <code style={styles.pathValue}>{value}</code>
                        <Button
                          disabled={!status?.[key]}
                          onClick={() => onCopy(value)}
                          aria-label={translate(locale, "copyPathFallback")}
                        >
                          {translate(locale, "copyPathFallback")}
                        </Button>
                      </div>
                    );
                  })}
                  <div style={styles.pathRow}>
                    <Text type="secondary">
                      {translate(locale, "bridgeEndpoint")}
                    </Text>
                    <code style={styles.pathValue}>{wsUrl}</code>
                    <Button
                      onClick={() => onCopy(wsUrl)}
                      aria-label={translate(locale, "copyPathFallback")}
                    >
                      {translate(locale, "copyPathFallback")}
                    </Button>
                  </div>
                </div>

                <div style={styles.developerActions}>
                  <Button onClick={onOpenChromeExtensions}>
                    {translate(locale, "openChromeExtensions")}
                  </Button>
                  <Button onClick={onOpenExtensionFolder}>
                    {translate(locale, "openExtensionFolder")}
                  </Button>
                  <Button onClick={onReloadExtension}>
                    {translate(locale, "reloadExtension")}
                  </Button>
                  <Button loading={setupLoading} onClick={onRegenerate}>
                    {translate(locale, "regenerate")}
                  </Button>
                  <Button loading={setupLoading} onClick={onReset}>
                    {translate(locale, "reset")}
                  </Button>
                </div>

                <div style={styles.unpackedSteps}>
                  <Text strong>{translate(locale, "unpackedTitle")}</Text>
                  <ol>
                    <li>{translate(locale, "stepOpen")}</li>
                    <li>{translate(locale, "stepLoad")}</li>
                    <li>{translate(locale, "stepVerify")}</li>
                  </ol>
                </div>
              </div>
            </Spin>
          ),
        },
      ]}
    />
  );
}

const acceptanceTerminalStatuses = new Set<string>([
  "passed",
  "failed",
  "blocked",
  "cancelled",
]);

function isAcceptanceTerminal(status: string | undefined): boolean {
  return acceptanceTerminalStatuses.has(status || "");
}

function acceptanceRepairActionLabel(
  locale: BrowserBridgeLocale,
  action: string,
): string {
  if (action === "open_setup_page" || action === "run_setup") {
    return translate(locale, "acceptanceRepairOpenSetup");
  }
  if (action === "open_chrome_extensions") {
    return translate(locale, "openChromeExtensions");
  }
  if (action === "open_extension_folder") {
    return translate(locale, "openExtensionFolder");
  }
  if (action === "connect_extension") {
    return translate(locale, "connectExtension");
  }
  if (action === "reload_extension") {
    return translate(locale, "reloadExtension");
  }
  if (action === "rerun_after_fix" || action === "rerun_acceptance") {
    return translate(locale, "acceptanceRerun");
  }
  return `${translate(locale, "acceptanceRepairAction")}: ${action}`;
}

function ProductAcceptancePanel({
  locale,
  onRepairAction,
}: {
  locale: BrowserBridgeLocale;
  onRepairAction: (repairAction: string) => void;
}) {
  const [acceptanceRun, setAcceptanceRun] =
    React.useState<AcceptanceRun | null>(null);
  const [acceptanceReport, setAcceptanceReport] =
    React.useState<AcceptanceReportResponse | null>(null);
  const [acceptanceLoading, setAcceptanceLoading] = React.useState(false);
  const [taobaoLiveEnabled, setTaobaoLiveEnabled] = React.useState(false);
  const [taobaoLiveConfirmed, setTaobaoLiveConfirmed] = React.useState(false);

  const loadReport = React.useCallback(async (runId: string) => {
    const report = await loadAcceptanceReport(runId);
    setAcceptanceReport(report);
  }, []);

  const loadRun = React.useCallback(
    async (runId: string) => {
      const next = await loadAcceptanceRun(runId);
      setAcceptanceRun(next);
      if (isAcceptanceTerminal(next.status)) {
        await loadReport(runId);
      }
      return next;
    },
    [loadReport],
  );

  const runAcceptance = React.useCallback(async () => {
    setAcceptanceLoading(true);
    setAcceptanceReport(null);
    try {
      const liveTaobao = taobaoLiveEnabled && taobaoLiveConfirmed;
      const next = await startAcceptanceRun(
        liveTaobao ? { live_taobao: true } : { live_taobao: false },
      );
      setAcceptanceRun(next);
      if (isAcceptanceTerminal(next.status)) {
        await loadReport(next.run_id);
      }
      message.success(translate(locale, "acceptanceStarted"));
    } catch (err) {
      message.error(err instanceof Error ? err.message : String(err));
    } finally {
      setAcceptanceLoading(false);
    }
  }, [loadReport, locale, taobaoLiveConfirmed, taobaoLiveEnabled]);

  const cancelRun = React.useCallback(async () => {
    if (!acceptanceRun) {
      return;
    }
    setAcceptanceLoading(true);
    try {
      const next = await cancelAcceptanceRun(acceptanceRun.run_id);
      setAcceptanceRun(next);
      message.success(translate(locale, "acceptanceCancelled"));
    } catch (err) {
      message.error(err instanceof Error ? err.message : String(err));
    } finally {
      setAcceptanceLoading(false);
    }
  }, [acceptanceRun, locale]);

  React.useEffect(() => {
    if (!acceptanceRun?.run_id || isAcceptanceTerminal(acceptanceRun.status)) {
      return undefined;
    }
    const pollId = window.setInterval(() => {
      void loadRun(acceptanceRun.run_id);
    }, 2000);
    return () => {
      window.clearInterval(pollId);
    };
  }, [acceptanceRun?.run_id, acceptanceRun?.status, loadRun]);

  const scenarioProgress = acceptanceRun?.scenario_progress?.length
    ? acceptanceRun.scenario_progress
    : acceptanceReport?.json.scenario_reports || [];
  const runActive = Boolean(
    acceptanceRun && !isAcceptanceTerminal(acceptanceRun.status),
  );
  const taobaoRequiresConfirmation = taobaoLiveEnabled && !taobaoLiveConfirmed;

  const handleScenarioRepairAction = (repairAction: string | undefined) => {
    if (!repairAction) {
      return;
    }
    if (
      repairAction === "rerun_after_fix" ||
      repairAction === "rerun_acceptance"
    ) {
      void runAcceptance();
      return;
    }
    onRepairAction(repairAction);
  };

  return (
    <Card style={styles.acceptancePanel}>
      <Space direction="vertical" size={14} style={{ width: "100%" }}>
        <div>
          <Text strong>{translate(locale, "acceptanceTitle")}</Text>
          <br />
          <Text type="secondary">
            {translate(locale, "acceptanceSubtitle")}
          </Text>
        </div>

        <div style={styles.acceptanceActions}>
          <Button
            type="primary"
            loading={acceptanceLoading}
            disabled={taobaoRequiresConfirmation || runActive}
            onClick={() => void runAcceptance()}
          >
            {translate(locale, "acceptanceRun")}
          </Button>
          <Button
            disabled={!runActive}
            loading={acceptanceLoading && runActive}
            onClick={() => void cancelRun()}
          >
            {translate(locale, "acceptanceCancel")}
          </Button>
          {acceptanceRun ? (
            <Button
              type="link"
              onClick={() => void loadReport(acceptanceRun.run_id)}
            >
              {translate(locale, "acceptanceReportLink")}
            </Button>
          ) : null}
        </div>

        <Space direction="vertical" size={8} style={{ width: "100%" }}>
          <Checkbox
            checked={taobaoLiveEnabled}
            onChange={(event: { target: { checked: boolean } }) => {
              setTaobaoLiveEnabled(event.target.checked);
              if (!event.target.checked) {
                setTaobaoLiveConfirmed(false);
              }
            }}
          >
            {translate(locale, "acceptanceTaobaoOptIn")}
          </Checkbox>
          {taobaoLiveEnabled ? (
            <Alert
              showIcon
              type="warning"
              message={translate(locale, "acceptanceTaobaoConfirm")}
              action={
                <Checkbox
                  checked={taobaoLiveConfirmed}
                  onChange={(event: { target: { checked: boolean } }) =>
                    setTaobaoLiveConfirmed(event.target.checked)
                  }
                >
                  {translate(locale, "acceptanceTaobaoConfirmCheckbox")}
                </Checkbox>
              }
            />
          ) : null}
        </Space>

        {acceptanceRun ? (
          <Text>
            {translate(locale, "acceptanceStatus")}: {acceptanceRun.status}
          </Text>
        ) : null}

        {scenarioProgress.length ? (
          <div style={styles.acceptanceScenarioList}>
            {scenarioProgress.map((scenario) => (
              <div
                key={scenario.scenario}
                style={styles.acceptanceScenarioCard}
              >
                <div style={styles.acceptanceScenarioHeader}>
                  <Text strong>{scenario.scenario}</Text>
                  <Text>{scenario.status}</Text>
                </div>
                {scenario.failure_category ? (
                  <Text type="secondary">
                    {translate(locale, "acceptanceFailureCategory")}:{" "}
                    {scenario.failure_category}
                  </Text>
                ) : null}
                {scenario.recovery_hint ? (
                  <Text>{scenario.recovery_hint}</Text>
                ) : null}
                {scenario.repair_action ? (
                  <Button
                    size="small"
                    onClick={() =>
                      handleScenarioRepairAction(scenario.repair_action)
                    }
                  >
                    {acceptanceRepairActionLabel(
                      locale,
                      scenario.repair_action,
                    )}
                  </Button>
                ) : null}
              </div>
            ))}
          </div>
        ) : null}

        {acceptanceReport?.markdown ? (
          <pre style={styles.acceptanceReportPreview}>
            {acceptanceReport.markdown}
          </pre>
        ) : null}
      </Space>
    </Card>
  );
}

function BrowserBridgeSetupPage() {
  const locale = resolveBrowserBridgeLocale();
  const developerRef = React.useRef<HTMLDivElement | null>(null);
  const [status, setStatus] = React.useState<ExtensionStatus | null>(null);
  const [extensionProbe, setExtensionProbe] =
    React.useState<ExtensionProbeStatus | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [setupLoading, setSetupLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [developerActiveKey, setDeveloperActiveKey] = React.useState<string[]>(
    [],
  );
  const [lifecycleState, setLifecycleState] =
    React.useState<LifecycleState>("preparing");

  const pathRows = React.useMemo(
    () => [
      {
        key: "extension_dir" as const,
        label: translate(locale, "extensionDir"),
      },
      {
        key: "native_manifest_path" as const,
        label: translate(locale, "nativeManifest"),
      },
      {
        key: "native_host_path" as const,
        label: translate(locale, "nativeHost"),
      },
      {
        key: "config_path" as const,
        label: translate(locale, "config"),
      },
    ],
    [locale],
  );

  const runExtensionProbe = React.useCallback(
    async (
      nextStatus: ExtensionStatus,
    ): Promise<ExtensionProbeStatus | null> => {
      const firstProbe = await probeExtension(
        nextStatus.extension_id,
        "status.get",
      );
      setExtensionProbe(firstProbe);

      if (!firstProbe?.ok) {
        return firstProbe;
      }

      if (nextStatus.connected) {
        return firstProbe;
      }

      if (
        nextStatus.setup_phase === "stale_build" ||
        nextStatus.build_freshness?.status === "stale"
      ) {
        const reloadProbe = await probeExtension(
          nextStatus.extension_id,
          "extension.reload",
        );
        setExtensionProbe(reloadProbe || firstProbe);
        return reloadProbe || firstProbe;
      }

      if (!nextStatus.connected) {
        const connectProbe = await probeExtension(
          nextStatus.extension_id,
          "bridge.connect",
        );
        setExtensionProbe(connectProbe || firstProbe);
        return connectProbe || firstProbe;
      }

      return firstProbe;
    },
    [],
  );

  const refreshLifecycle = React.useCallback(
    async (
      options: { autoPrepare?: boolean } = {},
    ): Promise<ExtensionStatus | null> => {
      setLoading(true);
      setError(null);
      setLifecycleState((previous) =>
        previous === "connected" ? previous : "preparing",
      );
      try {
        let next = await getStatus();
        setStatus(next);

        if (options.autoPrepare && shouldAutoPrepare(next)) {
          setLifecycleState("repairing");
          setSetupLoading(true);
          next = await setupExtension({
            install_mode: "unpacked",
            reset: shouldResetForRepair(next),
            ws_url: currentBridgeWsUrl(),
          });
          setStatus(next);
          message.success(translate(locale, "installSuccess"));
        }

        const probe = await runExtensionProbe(next);
        const latest = await getStatus();
        setStatus(latest);
        setLifecycleState(deriveLifecycleState(latest, probe, false, null));
        return latest;
      } catch (err) {
        const nextError = err instanceof Error ? err.message : String(err);
        setError(nextError);
        setLifecycleState("failed_actionable");
        message.error(translate(locale, "installFailed"));
        return null;
      } finally {
        setSetupLoading(false);
        setLoading(false);
      }
    },
    [locale, runExtensionProbe],
  );

  React.useEffect(() => {
    void refreshLifecycle({ autoPrepare: true });
  }, [refreshLifecycle]);

  React.useEffect(() => {
    if (
      lifecycleState !== "needs_load_unpacked" &&
      lifecycleState !== "extension_loaded_bridge_disconnected"
    ) {
      return undefined;
    }

    const pollId = window.setInterval(() => {
      void refreshLifecycle();
    }, 3000);

    return () => {
      window.clearInterval(pollId);
    };
  }, [lifecycleState, refreshLifecycle]);

  const copyValue = async (value: string) => {
    await navigator.clipboard?.writeText(value);
    message.success(translate(locale, "copied"));
  };

  const openDeveloperOptions = () => {
    setDeveloperActiveKey(["developer"]);
    window.setTimeout(() => {
      developerRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }, 0);
  };

  const handleDeveloperChange = (keys: unknown) => {
    setDeveloperActiveKey(normalizeCollapseKeys(keys));
  };

  const handleOpenChromeExtensions = React.useCallback(async () => {
    const result = await openChromeExtensionsPage();
    if (!result.opened && result.error) {
      message.warning(result.error);
    }
  }, []);

  const handleOpenExtensionFolder = React.useCallback(async () => {
    const result = await openExtensionFolder();
    if (!result.opened && result.error) {
      message.warning(result.error);
    }
  }, []);

  const handleConnectExtension = React.useCallback(async () => {
    const probe = await probeExtension(status?.extension_id, "bridge.connect");
    setExtensionProbe(probe);
    await refreshLifecycle();
  }, [refreshLifecycle, status?.extension_id]);

  const handleReloadExtension = React.useCallback(async () => {
    const probe = await probeExtension(
      status?.extension_id,
      "extension.reload",
    );
    setExtensionProbe(probe);
    await refreshLifecycle();
  }, [refreshLifecycle, status?.extension_id]);

  const handleManualRegenerate = React.useCallback(
    async (reset: boolean) => {
      setSetupLoading(true);
      setError(null);
      try {
        const next = await setupExtension({
          install_mode: "unpacked",
          reset,
          ws_url: currentBridgeWsUrl(),
        });
        setStatus(next);
        message.success(translate(locale, "installSuccess"));
        await refreshLifecycle();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setLifecycleState("failed_actionable");
        message.error(translate(locale, "installFailed"));
      } finally {
        setSetupLoading(false);
      }
    },
    [locale, refreshLifecycle],
  );

  const handleAcceptanceRepairAction = React.useCallback(
    (repairAction: string) => {
      if (
        repairAction === "open_setup_page" ||
        repairAction === "setup_extension" ||
        repairAction === "run_setup"
      ) {
        openDeveloperOptions();
        void refreshLifecycle({ autoPrepare: true });
        return;
      }
      if (repairAction === "open_chrome_extensions") {
        void handleOpenChromeExtensions();
        return;
      }
      if (repairAction === "open_extension_folder") {
        void handleOpenExtensionFolder();
        return;
      }
      if (repairAction === "connect_extension") {
        void handleConnectExtension();
        return;
      }
      if (repairAction === "reload_extension") {
        void handleReloadExtension();
        return;
      }
      message.info(repairAction);
    },
    [
      handleConnectExtension,
      handleOpenChromeExtensions,
      handleOpenExtensionFolder,
      handleReloadExtension,
      refreshLifecycle,
    ],
  );

  const primaryAction = React.useMemo(() => {
    const busy = loading || setupLoading;
    if (lifecycleState === "needs_load_unpacked") {
      return {
        label: "openChromeExtensions" as const,
        loading: false,
        onClick: () => void handleOpenChromeExtensions(),
      };
    }
    if (lifecycleState === "extension_loaded_bridge_disconnected") {
      return {
        label: "connectExtension" as const,
        loading: busy,
        onClick: () => void handleConnectExtension(),
      };
    }
    if (lifecycleState === "connected") {
      return {
        label: "refreshStatus" as const,
        loading,
        onClick: () => void refreshLifecycle(),
      };
    }
    if (lifecycleState === "failed_actionable") {
      return {
        label: "retrySetup" as const,
        loading: busy,
        onClick: () => void refreshLifecycle({ autoPrepare: true }),
      };
    }
    return {
      disabled: true,
      label:
        lifecycleState === "repairing"
          ? ("repairingAction" as const)
          : ("preparingAction" as const),
      loading: true,
      onClick: () => undefined,
    };
  }, [
    handleConnectExtension,
    handleOpenChromeExtensions,
    lifecycleState,
    loading,
    refreshLifecycle,
    setupLoading,
  ]);

  const currentView = (
    <LifecycleWizardView
      error={error}
      locale={locale}
      primaryAction={primaryAction}
      state={lifecycleState}
      status={status}
    />
  );
  const isAcceptanceAvailable = status?.connected === true;

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <div style={styles.headerTitleRow}>
          <div style={styles.headerIcon}>
            <BrowserBridgeLogo />
          </div>
          <div style={styles.headerText}>
            <Title level={3} style={{ margin: 0 }}>
              {translate(locale, "pageTitle")}
            </Title>
            <Text type="secondary">{translate(locale, "pageSubtitle")}</Text>
          </div>
        </div>
      </div>
      <div style={styles.content}>
        {error ? <Alert type="error" showIcon message={error} /> : null}
        {currentView}
        {isAcceptanceAvailable ? (
          <ProductAcceptancePanel
            locale={locale}
            onRepairAction={handleAcceptanceRepairAction}
          />
        ) : null}
        <DiagnosticsPanel locale={locale} status={status} />
        <div ref={developerRef}>
          <DeveloperOptions
            activeKey={developerActiveKey}
            loading={loading}
            locale={locale}
            onChange={handleDeveloperChange}
            onCopy={(value) => void copyValue(value)}
            onOpenChromeExtensions={() => void handleOpenChromeExtensions()}
            onOpenExtensionFolder={() => void handleOpenExtensionFolder()}
            onRegenerate={() => void handleManualRegenerate(false)}
            onReloadExtension={() => void handleReloadExtension()}
            onReset={() => void handleManualRegenerate(true)}
            pathRows={pathRows}
            setupLoading={setupLoading}
            status={status}
          />
        </div>
      </div>
    </div>
  );
}

const routeLocale = resolveBrowserBridgeLocale();

window.QwenPaw.registerRoutes?.("browser-bridge", [
  {
    path: "/plugin/browser-bridge",
    component: BrowserBridgeSetupPage,
    label: translate(routeLocale, "routeLabel"),
    icon: <BrowserBridgeRouteIcon />,
    priority: 40,
  },
]);

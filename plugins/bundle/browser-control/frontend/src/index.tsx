// Browser Control plugin UI. React and antd are provided by the QwenPaw
// console host, so this bundle only contains the plugin page itself.
import type * as ReactNS from "react";

import {
  resolveBrowserControlLocale,
  t as translate,
  type BrowserControlLocale,
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
  Collapse,
  Space,
  Spin,
  Steps,
  Typography,
  message,
} = antd;
const { Paragraph, Text, Title } = Typography;

const CWS_FALLBACK_URL =
  "https://chromewebstore.google.com/detail/qwenpaw-browser-bridge/nflcgkfjgoiipklkpenmbiificbakoch";

type InstallMode = "unpacked" | "cws";
type PageState = "not_installed" | "installed" | "connected";
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
  ws_url?: string;
  chrome_extensions_url?: string;
  version?: string | null;
  connected_since?: string | null;
  cws_url?: string;
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
  return apiRequest<ExtensionStatus>("/extension/status");
}

function setupExtension(
  payload: ExtensionSetupRequest,
): Promise<ExtensionStatus> {
  return apiRequest<ExtensionStatus>("/extension/setup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function getPageState(status: ExtensionStatus | null): PageState {
  if (status?.connected) {
    return "connected";
  }
  if (status?.installed) {
    return "installed";
  }
  return "not_installed";
}

function currentBridgeWsUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/nm-bridge`;
}

function getCwsUrl(status: ExtensionStatus | null) {
  return status?.cws_url || CWS_FALLBACK_URL;
}

const diagnosticHintKeys = new Set<MessageKey>([
  "browser_bridge_disconnected",
  "browser_backend_unavailable",
  "browser_control_engine_missing",
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
  locale: BrowserControlLocale,
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
  locale: BrowserControlLocale,
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

function BrowserControlLogo({ size = 38 }: { size?: number }) {
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
  locale: BrowserControlLocale;
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

function BrowserControlRouteIcon() {
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
  locale: BrowserControlLocale,
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
  locale: BrowserControlLocale;
  setupLoading: boolean;
  onDeveloperClick: () => void;
  onInstallCws: () => void;
}) {
  return (
    <Card style={styles.heroCard}>
      <div style={styles.iconCircle}>
        <BrowserControlLogo />
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
  locale: BrowserControlLocale;
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
  locale: BrowserControlLocale;
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

function DeveloperOptions({
  locale,
  activeKey,
  loading,
  pathRows,
  setupLoading,
  status,
  onChange,
  onCopy,
  onRegenerate,
  onReset,
}: {
  locale: BrowserControlLocale;
  activeKey: string[];
  loading: boolean;
  pathRows: PathRow[];
  setupLoading: boolean;
  status: ExtensionStatus | null;
  onChange: (keys: unknown) => void;
  onCopy: (value: string) => void;
  onRegenerate: () => void;
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
          label: <Space size={8}>{translate(locale, "developerTitle")}</Space>,
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
                          aria-label={translate(locale, "copy")}
                        >
                          {translate(locale, "copy")}
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
                      aria-label={translate(locale, "copy")}
                    >
                      {translate(locale, "copy")}
                    </Button>
                  </div>
                </div>

                <div style={styles.developerActions}>
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

function BrowserControlSetupPage() {
  const locale = resolveBrowserControlLocale();
  const developerRef = React.useRef<HTMLDivElement | null>(null);
  const [status, setStatus] = React.useState<ExtensionStatus | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [setupLoading, setSetupLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [showTips, setShowTips] = React.useState(false);
  const [developerActiveKey, setDeveloperActiveKey] = React.useState<string[]>(
    [],
  );
  const [cwsInstallStarted, setCwsInstallStarted] = React.useState(false);

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

  const loadStatus =
    React.useCallback(async (): Promise<ExtensionStatus | null> => {
      setLoading(true);
      setError(null);
      try {
        const next = await getStatus();
        setStatus(next);
        return next;
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        return null;
      } finally {
        setLoading(false);
      }
    }, []);

  React.useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const effectiveStatus = React.useMemo(() => {
    if (status && cwsInstallStarted && !status.connected && !status.installed) {
      return {
        ...status,
        installed: true,
        install_mode: "cws" as const,
      };
    }
    return status;
  }, [cwsInstallStarted, status]);

  const pageState = getPageState(effectiveStatus);

  React.useEffect(() => {
    if (pageState !== "installed") {
      setShowTips(false);
      return undefined;
    }

    const pollId = window.setInterval(() => {
      void loadStatus();
    }, 3000);
    const tipsId = window.setTimeout(() => setShowTips(true), 10000);

    return () => {
      window.clearInterval(pollId);
      window.clearTimeout(tipsId);
    };
  }, [loadStatus, pageState]);

  const handleSetup = React.useCallback(
    async (
      installMode: InstallMode = "unpacked",
      reset = true,
    ): Promise<ExtensionStatus | null> => {
      setSetupLoading(true);
      setError(null);
      try {
        const next = await setupExtension({
          install_mode: installMode,
          reset,
          ws_url: currentBridgeWsUrl(),
        });
        setStatus(next);
        message.success(translate(locale, "installSuccess"));
        return next;
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        message.error(translate(locale, "installFailed"));
        return null;
      } finally {
        setSetupLoading(false);
      }
    },
    [locale],
  );

  const handleInstallCws = React.useCallback(async () => {
    window.open(getCwsUrl(status), "_blank", "noopener,noreferrer");
    const next = await handleSetup("cws", false);
    if (!next) {
      return;
    }
    setCwsInstallStarted(true);
    setStatus({
      ...next,
      installed: true,
      install_mode: "cws",
    });
  }, [handleSetup, status]);

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

  const handleTestConnection = React.useCallback(async () => {
    const next = await loadStatus();
    if (!next) {
      return;
    }
    if (next.connected) {
      message.success(translate(locale, "testSuccess"));
      return;
    }
    message.warning(translate(locale, "testFailed"));
  }, [loadStatus, locale]);

  const currentView = (() => {
    if (loading && !effectiveStatus) {
      return (
        <Card style={styles.heroCard}>
          <Spin />
          <Paragraph style={{ marginTop: 12 }}>
            {translate(locale, "loading")}
          </Paragraph>
        </Card>
      );
    }

    if (pageState === "connected") {
      return (
        <ConnectedView
          locale={locale}
          loading={loading}
          onRefresh={() => void handleTestConnection()}
          status={effectiveStatus}
        />
      );
    }

    if (pageState === "installed") {
      return (
        <InstalledView
          locale={locale}
          loading={loading}
          onRefresh={() => void loadStatus()}
          showTips={showTips}
        />
      );
    }

    return (
      <NotInstalledView
        locale={locale}
        onDeveloperClick={openDeveloperOptions}
        onInstallCws={() => void handleInstallCws()}
        setupLoading={setupLoading}
      />
    );
  })();

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <div style={styles.headerTitleRow}>
          <div style={styles.headerIcon}>
            <BrowserControlLogo />
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
        <DiagnosticsPanel locale={locale} status={effectiveStatus} />
        <div ref={developerRef}>
          <DeveloperOptions
            activeKey={developerActiveKey}
            loading={loading}
            locale={locale}
            onChange={handleDeveloperChange}
            onCopy={(value) => void copyValue(value)}
            onRegenerate={() => void handleSetup("unpacked", false)}
            onReset={() => void handleSetup("unpacked", true)}
            pathRows={pathRows}
            setupLoading={setupLoading}
            status={effectiveStatus}
          />
        </div>
      </div>
    </div>
  );
}

const routeLocale = resolveBrowserControlLocale();

window.QwenPaw.registerRoutes?.("browser-control", [
  {
    path: "/plugin/browser-control",
    component: BrowserControlSetupPage,
    label: translate(routeLocale, "routeLabel"),
    icon: <BrowserControlRouteIcon />,
    priority: 40,
  },
]);

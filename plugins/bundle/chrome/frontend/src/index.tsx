// Chrome plugin UI. React and antd are provided by the QwenPaw console host.
import type * as ReactNS from "react";

import {
  resolveChromeLocale,
  t as translate,
  type ChromeLocale,
  type MessageKey,
} from "./locale";

const host = window.QwenPaw.host;
const React: typeof ReactNS = host.React;
const antd = host.antd;
const getApiUrl = host.getApiUrl;
const getApiToken = host.getApiToken;

const { Alert, Button, Collapse, Space, Spin, Typography, message } = antd;
const { Text, Title } = Typography;

type InstallMode = "unpacked" | "cws";
type ShortcutPlatform = "mac" | "windows" | "linux";
type InlineIconName = "chromeExtensions" | "copy" | "folderPlus" | "sliders";
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
  recovery_copy?: string;
  ws_url?: string;
  chrome_extensions_url?: string;
  version?: string | null;
  connected_since?: string | null;
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

interface PathRow {
  key: StatusKey;
  label: MessageKey;
}

const styles: Record<string, ReactNS.CSSProperties> = {
  page: {
    minHeight: "100%",
    overflowY: "auto",
    padding: 24,
    background: "transparent",
  },
  shell: {
    width: "min(100%, 900px)",
    margin: "0 auto",
    display: "flex",
    flexDirection: "column",
    gap: 16,
  },
  header: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 16,
    flexWrap: "wrap",
  },
  titleRow: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    minWidth: 0,
  },
  chromeIcon: {
    position: "relative",
    width: 42,
    height: 42,
    flex: "0 0 42px",
    borderRadius: "50%",
    background:
      "radial-gradient(circle at center, #fff 0 18%, transparent 19%), " +
      "radial-gradient(circle at center, #1a73e8 0 36%, transparent 37%), " +
      "conic-gradient(#ea4335 0 34%, #fbbc04 0 67%, #34a853 0 100%)",
    boxShadow: "inset 0 0 0 1px rgba(0,0,0,0.10)",
  },
  panel: {
    border: "1px solid rgba(0,0,0,0.08)",
    borderRadius: 8,
    background: "#fff",
    padding: 24,
    boxShadow: "0 1px 2px rgba(0,0,0,0.03)",
  },
  statusBlock: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    gap: 20,
    alignItems: "start",
  },
  statusTitleRow: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    marginBottom: 8,
  },
  statusDot: {
    width: 10,
    height: 10,
    borderRadius: 999,
    flexShrink: 0,
  },
  statusCopy: {
    maxWidth: 610,
    color: "rgba(0,0,0,0.58)",
    lineHeight: 1.55,
  },
  actions: {
    display: "flex",
    justifyContent: "flex-end",
    gap: 8,
    flexWrap: "wrap",
  },
  section: {
    marginTop: 22,
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  methodGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
    gap: 12,
  },
  methodTile: {
    minHeight: 128,
    padding: 14,
    border: "1px solid rgba(0,0,0,0.08)",
    borderRadius: 8,
    background: "#fff",
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  disabledTile: {
    minHeight: 128,
    padding: 14,
    border: "1px dashed rgba(0,0,0,0.16)",
    borderRadius: 8,
    background: "rgba(0,0,0,0.025)",
    display: "flex",
    flexDirection: "column",
    gap: 10,
    opacity: 0.72,
  },
  methodHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  badge: {
    minHeight: 22,
    padding: "1px 8px",
    borderRadius: 999,
    border: "1px solid rgba(22,119,255,0.22)",
    color: "#0958d9",
    background: "rgba(22,119,255,0.08)",
    fontSize: 12,
    whiteSpace: "nowrap",
  },
  installSupportGrid: {
    display: "flex",
    flexWrap: "wrap",
    gap: 16,
    alignItems: "stretch",
  },
  installBox: {
    flex: "1.55 1 520px",
    minWidth: 0,
    padding: 16,
    border: "1px solid rgba(0,0,0,0.08)",
    borderRadius: 8,
    background: "rgba(0,0,0,0.015)",
  },
  installTipsBox: {
    flex: "0.85 1 280px",
    minWidth: 0,
    padding: 16,
    border: "1px solid rgba(31,122,63,0.18)",
    borderRadius: 8,
    background: "rgba(31,122,63,0.035)",
  },
  installBoxHead: {
    display: "flex",
    alignItems: "baseline",
    justifyContent: "space-between",
    gap: 12,
    marginBottom: 14,
    flexWrap: "wrap",
  },
  installBoxNote: {
    color: "rgba(0,0,0,0.45)",
    fontSize: 12,
    lineHeight: "18px",
    whiteSpace: "nowrap",
  },
  steps: {
    margin: 0,
    padding: 0,
    listStyle: "none",
    display: "flex",
    flexDirection: "column",
    gap: 13,
  },
  stepItem: {
    display: "grid",
    gridTemplateColumns: "28px minmax(0, 1fr)",
    gap: 10,
    alignItems: "start",
  },
  stepIndex: {
    width: 28,
    height: 28,
    borderRadius: 8,
    display: "grid",
    placeItems: "center",
    color: "#246a52",
    background: "#e9f4ef",
    fontSize: 13,
    fontWeight: 700,
  },
  stepBody: {
    minWidth: 0,
  },
  stepLine: {
    marginTop: 5,
    display: "flex",
    alignItems: "center",
    gap: 6,
    flexWrap: "wrap",
    color: "rgba(0,0,0,0.58)",
    fontSize: 13,
    lineHeight: "26px",
  },
  stepControl: {
    height: 26,
    borderRadius: 7,
    border: "1px solid rgba(31,122,63,0.22)",
    background: "rgba(31,122,63,0.035)",
    color: "#1f5e48",
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "0 9px",
    cursor: "pointer",
    fontSize: 13,
    fontWeight: 700,
    boxShadow: "0 1px 0 rgba(0,0,0,0.03)",
    whiteSpace: "nowrap",
  },
  stepControlPrimary: {
    borderColor: "#155fc2",
    background: "#1677ff",
    color: "#fff",
  },
  stepControlBlue: {
    borderColor: "rgba(22,119,255,0.22)",
    background: "rgba(22,119,255,0.08)",
    color: "#0958d9",
  },
  stepControlPlaceholder: {
    cursor: "default",
    color: "#315f4e",
    background: "rgba(31,122,63,0.025)",
  },
  inlineIcon: {
    width: 14,
    height: 14,
    flex: "0 0 14px",
  },
  shortcutBox: {
    width: "100%",
    minWidth: 0,
  },
  shortcutHead: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 10,
    flexWrap: "wrap",
    marginBottom: 14,
  },
  osTabs: {
    display: "grid",
    gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
    width: "min(100%, 210px)",
    padding: 2,
    borderRadius: 8,
    border: "1px solid rgba(0,0,0,0.08)",
    background: "#fff",
    overflow: "hidden",
  },
  osTab: {
    height: 26,
    border: 0,
    borderRadius: 6,
    background: "transparent",
    color: "rgba(0,0,0,0.58)",
    padding: "0 8px",
    cursor: "pointer",
    fontSize: 12,
    lineHeight: "26px",
    whiteSpace: "nowrap",
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  osTabActive: {
    background: "#e9f4ef",
    color: "#134f3c",
    fontWeight: 700,
  },
  shortcutSteps: {
    margin: 0,
    padding: "11px 12px",
    listStyle: "none",
    display: "grid",
    gap: 8,
    border: "1px solid rgba(31,122,63,0.16)",
    borderRadius: 8,
    background: "#fff",
    color: "rgba(0,0,0,0.58)",
    fontSize: 13,
    lineHeight: "18px",
  },
  shortcutStep: {
    display: "grid",
    gridTemplateColumns: "18px minmax(0, 1fr)",
    gap: 8,
    alignItems: "start",
  },
  tipDot: {
    width: 18,
    height: 18,
    borderRadius: 999,
    display: "inline-grid",
    placeItems: "center",
    background: "#e9f4ef",
    color: "#246a52",
    fontSize: 11,
    fontWeight: 700,
    lineHeight: "18px",
  },
  checkGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: 12,
  },
  checkTile: {
    minHeight: 86,
    padding: 14,
    border: "1px solid rgba(0,0,0,0.08)",
    borderRadius: 8,
    background: "rgba(31,122,63,0.05)",
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  checkTitle: {
    display: "flex",
    alignItems: "center",
    gap: 8,
  },
  advanced: {
    marginTop: 18,
    borderRadius: 8,
    background: "#fff",
  },
  advancedRows: {
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  advancedRow: {
    display: "grid",
    gridTemplateColumns: "minmax(128px, 180px) minmax(0, 1fr) auto",
    gap: 8,
    alignItems: "center",
  },
  advancedValue: {
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
};

function ChromeSidebarIcon(): ReactNS.ReactElement {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      viewBox="0 0 24 24"
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx={12} cy={12} r={9} />
      <circle cx={12} cy={12} r={3.2} />
      <path d="M12 12h8.5" />
      <path d="M12 12 7.5 19.8" />
      <path d="M12 12 7.5 4.2" />
    </svg>
  );
}

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
  return apiRequest<ExtensionStatus>("/chrome/status");
}

function setupExtension(
  payload: ExtensionSetupRequest,
): Promise<ExtensionStatus> {
  return apiRequest<ExtensionStatus>("/chrome/setup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function openChromeExtensionsPage(): Promise<OpenChromeExtensionsResult> {
  return apiRequest<OpenChromeExtensionsResult>(
    "/chrome/open-chrome-extensions",
    {
      method: "POST",
    },
  );
}

function openExtensionFolder(): Promise<OpenExtensionFolderResult> {
  return apiRequest<OpenExtensionFolderResult>(
    "/chrome/open-extension-folder",
    {
      method: "POST",
    },
  );
}

function currentBridgeWsUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/chrome`;
}

function formatConnectedSince(
  value: string | null | undefined,
  locale: ChromeLocale,
) {
  if (!value) {
    return translate(locale, "justNow");
  }
  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) {
    return translate(locale, "justNow");
  }
  const minutes = Math.max(0, Math.floor((Date.now() - timestamp) / 60000));
  if (minutes < 1) {
    return translate(locale, "justNow");
  }
  if (minutes < 60) {
    return translate(locale, "minutesAgo", { count: minutes });
  }
  return translate(locale, "hoursAgo", { count: Math.floor(minutes / 60) });
}

function StatusDot({ ready }: { ready: boolean }) {
  return (
    <span
      aria-hidden="true"
      style={{
        ...styles.statusDot,
        background: ready ? "#1f7a3f" : "#9a6700",
      }}
    />
  );
}

function InlineIcon({ name }: { name: InlineIconName }) {
  const common = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 2,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };
  const paths: Record<InlineIconName, ReactNS.ReactNode> = {
    chromeExtensions: (
      <>
        <path d="M8 6h12v12H8z" />
        <path d="M4 10h4M4 14h4" />
      </>
    ),
    copy: (
      <>
        <rect x="9" y="9" width="11" height="11" rx="2" />
        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
      </>
    ),
    folderPlus: (
      <>
        <path d="M12 5v14" />
        <path d="M5 12h14" />
        <path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
      </>
    ),
    sliders: (
      <>
        <path d="M4 7h10" />
        <path d="M20 7h-2" />
        <circle cx="16" cy="7" r="2" />
        <path d="M20 17H10" />
        <path d="M4 17h2" />
        <circle cx="8" cy="17" r="2" />
      </>
    ),
  };

  return (
    <svg viewBox="0 0 24 24" style={styles.inlineIcon} {...common}>
      {paths[name]}
    </svg>
  );
}

function StepControl({
  icon,
  label,
  loading,
  onClick,
  tone = "default",
}: {
  icon: InlineIconName;
  label: string;
  loading?: boolean;
  onClick?: () => void;
  tone?: "blue" | "default" | "placeholder" | "primary";
}) {
  const toneStyle =
    tone === "primary"
      ? styles.stepControlPrimary
      : tone === "blue"
      ? styles.stepControlBlue
      : tone === "placeholder"
      ? styles.stepControlPlaceholder
      : null;

  return (
    <Button
      loading={loading}
      onClick={onClick}
      style={{ ...styles.stepControl, ...toneStyle }}
      type="text"
    >
      <InlineIcon name={icon} />
      {label}
    </Button>
  );
}

function detectShortcutPlatform(): ShortcutPlatform {
  const platform = window.navigator?.platform || "";
  const userAgent = window.navigator?.userAgent || "";
  const value = `${platform} ${userAgent}`.toLowerCase();
  if (value.includes("mac")) {
    return "mac";
  }
  if (value.includes("win")) {
    return "windows";
  }
  return "linux";
}

function AdvancedInfo({
  locale,
  onCopy,
  status,
}: {
  locale: ChromeLocale;
  onCopy: (value: string) => void;
  status: ExtensionStatus | null;
}) {
  const rows: PathRow[] = [
    { key: "extension_dir", label: "extensionDir" },
    { key: "native_manifest_path", label: "nativeManifest" },
    { key: "native_host_path", label: "nativeHost" },
    { key: "config_path", label: "config" },
  ];
  const wsUrl = status?.ws_url || currentBridgeWsUrl();

  return (
    <Collapse
      style={styles.advanced}
      items={[
        {
          key: "advanced",
          label: translate(locale, "advancedInfo"),
          children: (
            <div style={styles.advancedRows}>
              {rows.map((row) => {
                const value = status?.[row.key] || "-";
                return (
                  <div key={row.key} style={styles.advancedRow}>
                    <Text type="secondary">{translate(locale, row.label)}</Text>
                    <code style={styles.advancedValue}>{value}</code>
                    <Button
                      disabled={!status?.[row.key]}
                      onClick={() => onCopy(value)}
                    >
                      {translate(locale, "copyPath")}
                    </Button>
                  </div>
                );
              })}
              <div style={styles.advancedRow}>
                <Text type="secondary">
                  {translate(locale, "bridgeEndpoint")}
                </Text>
                <code style={styles.advancedValue}>{wsUrl}</code>
                <Button onClick={() => onCopy(wsUrl)}>
                  {translate(locale, "copyPath")}
                </Button>
              </div>
            </div>
          ),
        },
      ]}
    />
  );
}

function ChromeSetupPage() {
  const locale = resolveChromeLocale();
  const [status, setStatus] = React.useState<ExtensionStatus | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [setupLoading, setSetupLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [silentPrepareStarted, setSilentPrepareStarted] = React.useState(false);
  const [shortcutPlatform, setShortcutPlatform] =
    React.useState<ShortcutPlatform>(() => detectShortcutPlatform());

  const refreshStatus = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await getStatus();
      setStatus(next);
      return next;
    } catch (err) {
      const messageText = err instanceof Error ? err.message : String(err);
      setError(messageText);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  const prepareLocalFiles = React.useCallback(
    async (options?: { silent?: boolean }) => {
      if (status?.extension_dir) {
        return status;
      }
      setSetupLoading(true);
      setError(null);
      try {
        const next = await setupExtension({
          install_mode: "unpacked",
          ws_url: currentBridgeWsUrl(),
        });
        setStatus(next);
        if (!options?.silent) {
          message.success(translate(locale, "installSuccess"));
        }
        return next;
      } catch (err) {
        const messageText = err instanceof Error ? err.message : String(err);
        setError(messageText);
        if (!options?.silent) {
          message.error(translate(locale, "installFailed"));
        }
        return null;
      } finally {
        setSetupLoading(false);
      }
    },
    [locale, status],
  );

  const copyValue = React.useCallback(
    async (value: string) => {
      await navigator.clipboard?.writeText(value);
      message.success(translate(locale, "copied"));
    },
    [locale],
  );

  const handleCopyPath = React.useCallback(async () => {
    const next = await prepareLocalFiles();
    if (next?.extension_dir) {
      await copyValue(next.extension_dir);
    }
  }, [copyValue, prepareLocalFiles]);

  const handleOpenChrome = React.useCallback(async () => {
    const result = await openChromeExtensionsPage();
    if (!result.opened && result.error) {
      message.warning(result.error);
    }
  }, []);

  const isConnected = Boolean(status?.connected);
  const showInstallFlow = !isConnected;
  const version = status?.version || translate(locale, "versionUnknown");
  const connectedSince = formatConnectedSince(status?.connected_since, locale);
  const connectedChecks = [
    translate(locale, "extensionLoadedCheck"),
    translate(locale, "localConnectionCheck"),
  ];
  const shortcutTipsSteps: Record<ShortcutPlatform, [MessageKey, MessageKey]> =
    {
      mac: ["shortcutMacStep1", "shortcutMacStep2"],
      windows: ["shortcutWindowsStep1", "shortcutWindowsStep2"],
      linux: ["shortcutLinuxStep1", "shortcutLinuxStep2"],
    };

  React.useEffect(() => {
    if (
      loading ||
      isConnected ||
      silentPrepareStarted ||
      status?.extension_dir
    ) {
      return;
    }
    setSilentPrepareStarted(true);
    void prepareLocalFiles({ silent: true });
  }, [
    isConnected,
    loading,
    prepareLocalFiles,
    silentPrepareStarted,
    status?.extension_dir,
  ]);

  return (
    <div style={styles.page}>
      <div style={styles.shell}>
        <div style={styles.panel}>
          <div style={styles.statusBlock}>
            <div>
              <div style={styles.header}>
                <div style={styles.titleRow}>
                  <span style={styles.chromeIcon} />
                  <div>
                    <Title level={3} style={{ margin: 0 }}>
                      {translate(locale, "pageTitle")}
                    </Title>
                    <Text type="secondary">
                      {translate(locale, "pageSubtitle")}
                    </Text>
                  </div>
                </div>
              </div>
              <div style={{ marginTop: 22 }}>
                <div style={styles.statusTitleRow}>
                  <StatusDot ready={isConnected} />
                  <Title level={4} style={{ margin: 0 }}>
                    {isConnected
                      ? translate(locale, "readyTitle")
                      : translate(locale, "installTitle")}
                  </Title>
                </div>
                <div style={styles.statusCopy}>
                  {isConnected
                    ? translate(locale, "readyDescription", {
                        version,
                        connectedSince,
                      })
                    : status?.recovery_copy ||
                      translate(locale, "installDescription")}
                </div>
              </div>
            </div>
            <div style={styles.actions}>
              {isConnected ? (
                <>
                  <Button
                    loading={loading}
                    onClick={() => void refreshStatus()}
                  >
                    {translate(locale, "refreshStatus")}
                  </Button>
                  <Button
                    type="primary"
                    onClick={() => void handleOpenChrome()}
                  >
                    {translate(locale, "openChrome")}
                  </Button>
                </>
              ) : (
                <Button
                  type="primary"
                  loading={loading}
                  onClick={() => void refreshStatus()}
                >
                  {translate(locale, "installedRefresh")}
                </Button>
              )}
            </div>
          </div>

          {error ? (
            <Alert
              showIcon
              type="error"
              message={error}
              style={{ marginTop: 16 }}
            />
          ) : null}

          {isConnected ? (
            <div style={styles.section}>
              <Text strong>{translate(locale, "checksTitle")}</Text>
              <div style={styles.checkGrid}>
                {connectedChecks.map((label) => (
                  <div key={label} style={styles.checkTile}>
                    <div style={styles.checkTitle}>
                      <StatusDot ready />
                      <Text strong>{label}</Text>
                    </div>
                    <Text type="secondary">
                      {translate(locale, "checkReady")}
                    </Text>
                  </div>
                ))}
              </div>
            </div>
          ) : showInstallFlow ? (
            <>
              <div style={styles.section}>
                <Text strong>{translate(locale, "installMethodsTitle")}</Text>
                <div style={styles.methodGrid}>
                  <div style={styles.methodTile}>
                    <div style={styles.methodHeader}>
                      <Text strong>
                        {translate(locale, "localMethodTitle")}
                      </Text>
                      <span style={styles.badge}>
                        {translate(locale, "recommendedBadge")}
                      </span>
                    </div>
                    <Text type="secondary">
                      {translate(locale, "localMethodDescription")}
                    </Text>
                    <Button
                      type="primary"
                      onClick={() => void handleOpenChrome()}
                    >
                      <InlineIcon name="chromeExtensions" />
                      {translate(locale, "openChromeExtensionsPage")}
                    </Button>
                  </div>
                  <div style={styles.disabledTile} aria-disabled="true">
                    <div style={styles.methodHeader}>
                      <Text strong>
                        {translate(locale, "chromeWebStoreTitle")}
                      </Text>
                      <span style={styles.badge}>
                        {translate(locale, "comingSoon")}
                      </span>
                    </div>
                    <Text type="secondary">
                      {translate(locale, "chromeWebStoreDescription")}
                    </Text>
                    <Button disabled>{translate(locale, "comingSoon")}</Button>
                  </div>
                </div>
              </div>

              <div style={styles.section}>
                <div style={styles.installSupportGrid}>
                  <div style={styles.installBox}>
                    <div style={styles.installBoxHead}>
                      <Text strong>{translate(locale, "localStepsTitle")}</Text>
                      <span style={styles.installBoxNote}>
                        {translate(locale, "localStepsOnce")}
                      </span>
                    </div>
                    <ol style={styles.steps}>
                      <li style={styles.stepItem}>
                        <span style={styles.stepIndex}>1</span>
                        <div style={styles.stepBody}>
                          <Text strong>
                            {translate(locale, "openExtensionsStepTitle")}
                          </Text>
                          <div style={styles.stepLine}>
                            {translate(locale, "openExtensionsPrefix")}
                            <StepControl
                              icon="chromeExtensions"
                              label={translate(locale, "openExtensionsAction")}
                              onClick={() => void handleOpenChrome()}
                              tone="blue"
                            />
                            {translate(locale, "openExtensionsSuffix")}
                          </div>
                        </div>
                      </li>
                      <li style={styles.stepItem}>
                        <span style={styles.stepIndex}>2</span>
                        <div style={styles.stepBody}>
                          <Text strong>
                            {translate(locale, "developerModeStepTitle")}
                          </Text>
                          <div style={styles.stepLine}>
                            {translate(locale, "developerModePrefix")}
                            <StepControl
                              icon="sliders"
                              label={translate(locale, "developerModeAction")}
                              tone="placeholder"
                            />
                            {translate(locale, "developerModeSuffix")}
                          </div>
                        </div>
                      </li>
                      <li style={styles.stepItem}>
                        <span style={styles.stepIndex}>3</span>
                        <div style={styles.stepBody}>
                          <Text strong>
                            {translate(locale, "loadUnpackedStepTitle")}
                          </Text>
                          <div style={styles.stepLine}>
                            {translate(locale, "loadUnpackedPrefix")}
                            <StepControl
                              icon="folderPlus"
                              label={translate(locale, "loadUnpackedAction")}
                              tone="placeholder"
                            />
                            {translate(locale, "loadUnpackedSuffix")}
                          </div>
                        </div>
                      </li>
                      <li style={styles.stepItem}>
                        <span style={styles.stepIndex}>4</span>
                        <div style={styles.stepBody}>
                          <Text strong>
                            {translate(locale, "pastePathStepTitle")}
                          </Text>
                          <div style={styles.stepLine}>
                            {translate(locale, "pastePathPrefix")}
                            <StepControl
                              icon="copy"
                              label={translate(locale, "qwenpawExtensionPath")}
                              loading={setupLoading}
                              onClick={() => void handleCopyPath()}
                              tone="primary"
                            />
                            {translate(locale, "pastePathSuffix")}
                          </div>
                        </div>
                      </li>
                    </ol>
                  </div>

                  <aside
                    aria-label={translate(locale, "shortcutTipsTitle")}
                    style={styles.installTipsBox}
                  >
                    <div style={styles.installBoxHead}>
                      <Text strong>
                        {translate(locale, "shortcutTipsTitle")}
                      </Text>
                      <span style={styles.installBoxNote}>
                        {translate(locale, "shortcutTipsScope")}
                      </span>
                    </div>
                    <div style={styles.shortcutBox}>
                      <div style={styles.shortcutHead}>
                        <Text strong>{translate(locale, "currentSystem")}</Text>
                        <div style={styles.osTabs} role="tablist">
                          {(
                            [
                              ["mac", "macOS"],
                              ["windows", "Windows"],
                              ["linux", "Linux"],
                            ] as const
                          ).map(([platform, label]) => (
                            <button
                              key={platform}
                              onClick={() => setShortcutPlatform(platform)}
                              style={{
                                ...styles.osTab,
                                ...(shortcutPlatform === platform
                                  ? styles.osTabActive
                                  : null),
                              }}
                              type="button"
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                      </div>
                      <ol style={styles.shortcutSteps}>
                        {shortcutTipsSteps[shortcutPlatform].map(
                          (key, index) => (
                            <li key={key} style={styles.shortcutStep}>
                              <span style={styles.tipDot}>{index + 1}</span>
                              <span>{translate(locale, key)}</span>
                            </li>
                          ),
                        )}
                      </ol>
                    </div>
                  </aside>
                </div>
              </div>
            </>
          ) : null}

          <AdvancedInfo
            locale={locale}
            onCopy={(value) => void copyValue(value)}
            status={status}
          />
        </div>
        {loading && !status ? <Spin /> : null}
      </div>
    </div>
  );
}

window.QwenPaw.registerRoutes?.("chrome", [
  {
    path: "/plugin/chrome",
    component: ChromeSetupPage,
    label: "Chrome浏览器",
    icon: <ChromeSidebarIcon />,
    priority: 40,
  },
]);

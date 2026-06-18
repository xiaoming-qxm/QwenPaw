import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Collapse,
  Space,
  Spin,
  Steps,
  Typography,
} from "antd";
import type { CollapseProps } from "antd";
import {
  CheckCircle2,
  Copy,
  ExternalLink,
  Puzzle,
  RefreshCw,
  Settings2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { extensionApi, type ExtensionStatus } from "@/api/modules/extension";
import { useAppMessage } from "@/hooks/useAppMessage";
import styles from "./index.module.less";

const { Paragraph, Text, Title } = Typography;

const CWS_FALLBACK_URL =
  "https://chromewebstore.google.com/detail/qwenpaw-browser-bridge/nflcgkfjgoiipklkpenmbiificbakoch";

type PageState = "not_installed" | "installed" | "connected";
type StatusKey =
  | "extension_dir"
  | "native_manifest_path"
  | "native_host_path"
  | "config_path";
type ExtensionStatusWithCws = ExtensionStatus & { cws_url?: string };

interface PathRow {
  key: StatusKey;
  label: string;
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
  return (status as ExtensionStatusWithCws | null)?.cws_url || CWS_FALLBACK_URL;
}

function normalizeCollapseKeys(keys: string | string[]) {
  return Array.isArray(keys) ? keys : keys ? [keys] : [];
}

function formatConnectedSince(
  value: string | null,
  t: ReturnType<typeof useTranslation>["t"],
) {
  if (!value) {
    return t("browserExtension.ready.justNow", "just now");
  }

  const timestamp = new Date(value).getTime();
  if (Number.isNaN(timestamp)) {
    return t("browserExtension.ready.justNow", "just now");
  }

  const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (seconds < 60) {
    return t("browserExtension.ready.justNow", "just now");
  }

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return t("browserExtension.ready.minutesAgo", "{{count}} minutes ago", {
      count: minutes,
    });
  }

  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return t("browserExtension.ready.hoursAgo", "{{count}} hours ago", {
      count: hours,
    });
  }

  return t("browserExtension.ready.daysAgo", "{{count}} days ago", {
    count: Math.floor(hours / 24),
  });
}

interface NotInstalledViewProps {
  setupLoading: boolean;
  onDeveloperClick: () => void;
  onInstallCws: () => void;
}

function NotInstalledView({
  setupLoading,
  onDeveloperClick,
  onInstallCws,
}: NotInstalledViewProps) {
  const { t } = useTranslation();

  return (
    <Card className={styles.heroCard}>
      <div className={styles.heroIcon}>
        <Puzzle size={32} />
      </div>
      <Title level={2}>
        {t("browserExtension.hero.title", "Browser Takeover")}
      </Title>
      <Paragraph className={styles.heroSubtitle}>
        {t(
          "browserExtension.hero.subtitle",
          "Let QwenPaw read pages, click controls, and operate Chrome when a task needs the browser.",
        )}
      </Paragraph>
      <div className={styles.heroActions}>
        <Button
          type="primary"
          size="large"
          icon={<ExternalLink size={18} />}
          loading={setupLoading}
          onClick={onInstallCws}
        >
          {t(
            "browserExtension.hero.installCws",
            "Install from Chrome Web Store",
          )}
        </Button>
        <Button type="link" onClick={onDeveloperClick}>
          {t(
            "browserExtension.hero.devMode",
            "I'm a developer — use local loading",
          )}
        </Button>
      </div>
    </Card>
  );
}

interface InstalledViewProps {
  loading: boolean;
  showTips: boolean;
  onRefresh: () => void;
}

function InstalledView({ loading, showTips, onRefresh }: InstalledViewProps) {
  const { t } = useTranslation();

  return (
    <Card className={styles.progressView}>
      <Steps
        size="small"
        current={1}
        items={[
          {
            title: t("browserExtension.progress.installed", "Installed"),
            status: "finish",
          },
          {
            title: t("browserExtension.progress.connecting", "Connecting"),
            status: "process",
          },
          {
            title: t("browserExtension.progress.ready", "Ready"),
            status: "wait",
          },
        ]}
      />
      <div className={styles.progressBody}>
        <Title level={3}>
          {t(
            "browserExtension.connecting.title",
            "Waiting for Chrome to connect",
          )}
        </Title>
        <Paragraph className={styles.progressMessage}>
          {t(
            "browserExtension.connecting.message",
            "Open or reload the QwenPaw browser extension in Chrome. This page checks the bridge every 3 seconds.",
          )}
        </Paragraph>
        <Button
          icon={<RefreshCw size={16} />}
          loading={loading}
          onClick={onRefresh}
        >
          {t("browserExtension.actions.refreshStatus", "Refresh Status")}
        </Button>
      </div>
      {showTips ? (
        <Alert
          showIcon
          type="warning"
          message={t(
            "browserExtension.connecting.tipsTitle",
            "Still not connected?",
          )}
          description={
            <ul className={styles.tipList}>
              <li>
                {t(
                  "browserExtension.connecting.tips.enable",
                  "Make sure Developer mode is enabled.",
                )}
              </li>
              <li>
                {t(
                  "browserExtension.connecting.tips.click",
                  "Click the QwenPaw extension icon in Chrome once.",
                )}
              </li>
              <li>
                {t(
                  "browserExtension.connecting.tips.reload",
                  "Reload the extension or reopen the target browser tab.",
                )}
              </li>
            </ul>
          }
        />
      ) : null}
    </Card>
  );
}

interface ConnectedViewProps {
  status: ExtensionStatus | null;
  loading: boolean;
  onRefresh: () => void;
}

function ConnectedView({ status, loading, onRefresh }: ConnectedViewProps) {
  const { t } = useTranslation();
  const connectedSince = formatConnectedSince(
    status?.connected_since ?? null,
    t,
  );
  const version =
    status?.version || t("browserExtension.ready.versionUnknown", "unknown");

  return (
    <Card className={styles.connectedView}>
      <div className={styles.successIcon}>
        <CheckCircle2 size={40} />
      </div>
      <Title level={2}>
        {t("browserExtension.ready.title", "Browser Bridge Active")}
      </Title>
      <Steps
        size="small"
        current={2}
        items={[
          {
            title: t("browserExtension.progress.installed", "Installed"),
            status: "finish",
          },
          {
            title: t("browserExtension.progress.connecting", "Connecting"),
            status: "finish",
          },
          {
            title: t("browserExtension.progress.ready", "Ready"),
            status: "finish",
          },
        ]}
      />
      <div className={styles.readyMeta}>
        <Text>
          {t("browserExtension.ready.version", "Extension version")}: {version}
        </Text>
        <Text>
          {t("browserExtension.ready.connectedSince", "Connected")}:{" "}
          {connectedSince}
        </Text>
      </div>
      <div className={styles.usageSection}>
        <Text strong>
          {t("browserExtension.ready.usageTitle", "What you can do next")}
        </Text>
        <div className={styles.usageList}>
          <div>
            {t(
              "browserExtension.ready.usage.example1",
              "Open the current browser page and summarize it.",
            )}
          </div>
          <div>
            {t(
              "browserExtension.ready.usage.example2",
              "Click the next actionable button on this page.",
            )}
          </div>
          <div>
            {t(
              "browserExtension.ready.usage.example3",
              "Collect the visible product prices into a table.",
            )}
          </div>
        </div>
      </div>
      <Button
        icon={<RefreshCw size={16} />}
        loading={loading}
        onClick={onRefresh}
      >
        {t("browserExtension.ready.testConnection", "Test Connection")}
      </Button>
    </Card>
  );
}

interface DeveloperOptionsProps {
  activeKey: string[];
  loading: boolean;
  pathRows: PathRow[];
  setupLoading: boolean;
  status: ExtensionStatus | null;
  onChange: CollapseProps["onChange"];
  onCopy: (value: string) => void;
  onRegenerate: () => void;
  onReset: () => void;
}

function DeveloperOptions({
  activeKey,
  loading,
  pathRows,
  setupLoading,
  status,
  onChange,
  onCopy,
  onRegenerate,
  onReset,
}: DeveloperOptionsProps) {
  const { t } = useTranslation();
  const wsUrl = status?.ws_url || currentBridgeWsUrl();

  return (
    <Collapse
      activeKey={activeKey}
      className={styles.developerPanel}
      onChange={onChange}
      items={[
        {
          key: "developer",
          label: (
            <Space size={8}>
              <Settings2 size={16} />
              {t("browserExtension.developer.title", "Developer Options")}
            </Space>
          ),
          children: (
            <Spin spinning={loading && !status}>
              <div className={styles.developerContent}>
                <div className={styles.modeRow}>
                  <Text type="secondary">
                    {t(
                      "browserExtension.developer.installMode",
                      "Install mode",
                    )}
                  </Text>
                  <Text>{status?.install_mode || "-"}</Text>
                </div>

                <div className={styles.pathList}>
                  {pathRows.map(({ key, label }) => {
                    const value = status?.[key] || "-";
                    return (
                      <div className={styles.pathRow} key={key}>
                        <Text type="secondary" className={styles.statusLabel}>
                          {label}
                        </Text>
                        <code className={styles.pathValue}>{value}</code>
                        <Button
                          icon={<Copy size={16} />}
                          disabled={!status?.[key]}
                          onClick={() => onCopy(value)}
                          aria-label={t("common.copy")}
                        />
                      </div>
                    );
                  })}
                  <div className={styles.pathRow}>
                    <Text type="secondary" className={styles.statusLabel}>
                      {t("browserExtension.developer.wsUrl", "Bridge endpoint")}
                    </Text>
                    <code className={styles.pathValue}>{wsUrl}</code>
                    <Button
                      icon={<Copy size={16} />}
                      onClick={() => onCopy(wsUrl)}
                      aria-label={t("common.copy")}
                    />
                  </div>
                </div>

                <div className={styles.developerActions}>
                  <Button
                    icon={<RefreshCw size={16} />}
                    loading={setupLoading}
                    onClick={onRegenerate}
                  >
                    {t(
                      "browserExtension.developer.regenerate",
                      "Regenerate Files",
                    )}
                  </Button>
                  <Button loading={setupLoading} onClick={onReset}>
                    {t("browserExtension.developer.reset", "Reset Config")}
                  </Button>
                </div>

                <div className={styles.unpackedSteps}>
                  <Text strong>
                    {t(
                      "browserExtension.developer.unpackedTitle",
                      "Local unpacked loading",
                    )}
                  </Text>
                  <ol>
                    <li>
                      {t(
                        "browserExtension.steps.open",
                        "Open chrome://extensions and enable Developer mode.",
                      )}
                    </li>
                    <li>
                      {t(
                        "browserExtension.steps.load",
                        "Choose Load unpacked and select the extension folder above.",
                      )}
                    </li>
                    <li>
                      {t(
                        "browserExtension.steps.verify",
                        "Return here and refresh; Connected turns green after Chrome connects.",
                      )}
                    </li>
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

export default function BrowserExtensionPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const developerRef = useRef<HTMLDivElement | null>(null);
  const [status, setStatus] = useState<ExtensionStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [setupLoading, setSetupLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showTips, setShowTips] = useState(false);
  const [developerActiveKey, setDeveloperActiveKey] = useState<string[]>([]);
  const [cwsInstallStarted, setCwsInstallStarted] = useState(false);

  const pathRows = useMemo(
    () => [
      {
        key: "extension_dir" as const,
        label: t("browserExtension.paths.extensionDir", "Extension folder"),
      },
      {
        key: "native_manifest_path" as const,
        label: t("browserExtension.paths.nativeManifest", "Native manifest"),
      },
      {
        key: "native_host_path" as const,
        label: t("browserExtension.paths.nativeHost", "Native host"),
      },
      {
        key: "config_path" as const,
        label: t("browserExtension.paths.config", "Bridge config"),
      },
    ],
    [t],
  );

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setStatus(await extensionApi.getStatus());
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const effectiveStatus = useMemo(() => {
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

  useEffect(() => {
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

  const handleSetup = useCallback(
    async (
      installMode: "unpacked" | "cws" = "unpacked",
      reset = true,
    ): Promise<ExtensionStatus | null> => {
      setSetupLoading(true);
      setError(null);
      try {
        const next = await extensionApi.setup({
          install_mode: installMode,
          reset,
          ws_url: currentBridgeWsUrl(),
        });
        setStatus(next);
        message.success(
          t("browserExtension.actions.installSuccess", "Extension files ready"),
        );
        return next;
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
        message.error(
          t("browserExtension.actions.installFailed", "Extension setup failed"),
        );
        return null;
      } finally {
        setSetupLoading(false);
      }
    },
    [message, t],
  );

  const handleInstallCws = useCallback(async () => {
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
    message.success(t("common.copied"));
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

  const handleDeveloperChange: CollapseProps["onChange"] = (keys) => {
    setDeveloperActiveKey(normalizeCollapseKeys(keys as string | string[]));
  };

  const currentView = (() => {
    if (loading && !effectiveStatus) {
      return (
        <Card className={styles.heroCard}>
          <Spin />
        </Card>
      );
    }

    if (pageState === "connected") {
      return (
        <ConnectedView
          loading={loading}
          onRefresh={() => void loadStatus()}
          status={effectiveStatus}
        />
      );
    }

    if (pageState === "installed") {
      return (
        <InstalledView
          loading={loading}
          onRefresh={() => void loadStatus()}
          showTips={showTips}
        />
      );
    }

    return (
      <NotInstalledView
        onDeveloperClick={openDeveloperOptions}
        onInstallCws={() => void handleInstallCws()}
        setupLoading={setupLoading}
      />
    );
  })();

  return (
    <div className={styles.browserExtensionPage}>
      <PageHeader
        parent={t("nav.settings")}
        current={t("browserExtension.title", "Browser Takeover")}
      />

      <div className={styles.content}>
        {error ? <Alert type="error" showIcon message={error} /> : null}
        {currentView}
        <div ref={developerRef}>
          <DeveloperOptions
            activeKey={developerActiveKey}
            loading={loading}
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

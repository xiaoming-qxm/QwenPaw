import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Card, Space, Spin, Tag, Typography } from "antd";
import {
  CheckCircle2,
  Copy,
  ExternalLink,
  Puzzle,
  RefreshCw,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { extensionApi, type ExtensionStatus } from "@/api/modules/extension";
import { useAppMessage } from "@/hooks/useAppMessage";
import styles from "./index.module.less";

const { Text } = Typography;

type StatusKey =
  | "extension_dir"
  | "native_manifest_path"
  | "native_host_path"
  | "config_path";

function statusTag(active: boolean, activeText: string, inactiveText: string) {
  return active ? (
    <Tag color="success">{activeText}</Tag>
  ) : (
    <Tag color="warning">{inactiveText}</Tag>
  );
}

function currentBridgeWsUrl() {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/nm-bridge`;
}

export default function BrowserExtensionPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [status, setStatus] = useState<ExtensionStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [setupLoading, setSetupLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  const loadStatus = async () => {
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
  };

  useEffect(() => {
    void loadStatus();
  }, []);

  const handleSetup = async () => {
    setSetupLoading(true);
    setError(null);
    try {
      const next = await extensionApi.setup({
        install_mode: "unpacked",
        reset: true,
        ws_url: currentBridgeWsUrl(),
      });
      setStatus(next);
      message.success(
        t("browserExtension.actions.installSuccess", "Extension files ready"),
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      message.error(
        t("browserExtension.actions.installFailed", "Extension setup failed"),
      );
    } finally {
      setSetupLoading(false);
    }
  };

  const copyValue = async (value: string) => {
    await navigator.clipboard?.writeText(value);
    message.success(t("common.copied"));
  };

  const openChromeExtensions = () => {
    window.open(
      status?.chrome_extensions_url || "chrome://extensions",
      "_blank",
    );
  };

  return (
    <div className={styles.browserExtensionPage}>
      <PageHeader
        parent={t("nav.settings")}
        current={t("browserExtension.title", "Browser Extension")}
      />

      <div className={styles.content}>
        <Alert
          type="info"
          showIcon
          message={t(
            "browserExtension.desc",
            "Prepare the Chrome extension and Native Messaging bridge, then load the unpacked extension in Chrome developer mode.",
          )}
        />

        <Card
          title={
            <Space size={8}>
              <Puzzle size={18} />
              {t("browserExtension.title", "Browser Extension")}
            </Space>
          }
        >
          <div className={styles.toolbar}>
            <div className={styles.toolbarLeft}>
              {statusTag(
                Boolean(status?.installed),
                t("browserExtension.status.installed", "Installed"),
                t("browserExtension.status.notInstalled", "Not installed"),
              )}
              {statusTag(
                Boolean(status?.connected),
                t("browserExtension.status.connected", "Connected"),
                t("browserExtension.status.notConnected", "Not connected"),
              )}
              {status?.ws_url ? <Text code>{status.ws_url}</Text> : null}
            </div>
            <div className={styles.toolbarRight}>
              <Button
                icon={<RefreshCw size={16} />}
                onClick={() => void loadStatus()}
                loading={loading}
              >
                {t("common.refresh")}
              </Button>
              <Button
                type="primary"
                icon={<CheckCircle2 size={16} />}
                onClick={() => void handleSetup()}
                loading={setupLoading}
              >
                {t(
                  "browserExtension.actions.installRefresh",
                  "Install / Refresh",
                )}
              </Button>
              <Button
                icon={<ExternalLink size={16} />}
                onClick={openChromeExtensions}
              >
                {status?.chrome_extensions_url || "chrome://extensions"}
              </Button>
            </div>
          </div>
        </Card>

        {error ? <Alert type="error" showIcon message={error} /> : null}

        <Spin spinning={loading && !status}>
          <Card title={t("browserExtension.sections.paths", "Install paths")}>
            <div className={styles.pathList}>
              {pathRows.map(({ key, label }) => {
                const value = status?.[key as StatusKey] || "-";
                return (
                  <div className={styles.pathRow} key={key}>
                    <Text type="secondary" className={styles.statusLabel}>
                      {label}
                    </Text>
                    <code className={styles.pathValue}>{value}</code>
                    <Button
                      icon={<Copy size={16} />}
                      disabled={!status?.[key as StatusKey]}
                      onClick={() => void copyValue(value)}
                      aria-label={t("common.copy")}
                    />
                  </div>
                );
              })}
            </div>
          </Card>
        </Spin>

        <Card title={t("browserExtension.sections.chrome", "Chrome load")}>
          <ol className={styles.steps}>
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
        </Card>
      </div>
    </div>
  );
}

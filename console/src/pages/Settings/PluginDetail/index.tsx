import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { Button, Empty, Spin, Tooltip } from "antd";
import {
  CalendarDays,
  ChevronDown,
  Code2,
  Copy,
  Eye,
  Globe,
  Monitor,
  MousePointerClick,
  Package,
  RefreshCw,
  Settings,
  User,
} from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "@/hooks/useAppMessage";
import {
  fetchPluginDetail,
  type PluginCapability,
  type PluginSetupStep,
} from "@/api/modules/plugin";
import styles from "./index.module.less";

const capabilityIcons = [Eye, MousePointerClick, Monitor, Code2];

function stepClass(stepIndex: number, steps: PluginSetupStep[]) {
  if (stepIndex === 0) return "process";
  if (steps.length === 1) return "process";
  return "wait";
}

export default function PluginDetailPage() {
  const { pluginId = "" } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [detail, setDetail] = useState<Awaited<
    ReturnType<typeof fetchPluginDetail>
  > | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [devOpen, setDevOpen] = useState(false);

  const loadDetail = useCallback(
    async (showLoading = true) => {
      if (!pluginId) return null;
      if (showLoading) setLoading(true);
      try {
        const next = await fetchPluginDetail(pluginId);
        setDetail(next);
        return next;
      } catch (err) {
        message.error(
          err instanceof Error
            ? err.message
            : t("pluginDetail.messages.loadFailed", "Failed to load"),
        );
        return null;
      } finally {
        if (showLoading) setLoading(false);
      }
    },
    [message, pluginId, t],
  );

  useEffect(() => {
    loadDetail();
  }, [loadDetail]);

  const setupSteps = useMemo(
    () => detail?.setup?.steps ?? detail?.manifest.setup?.steps ?? [],
    [detail],
  );

  const capabilities: PluginCapability[] = useMemo(
    () =>
      detail?.capabilities?.length
        ? detail.capabilities
        : detail?.manifest.capabilities ?? [],
    [detail],
  );

  const copyValue = async (value?: string | null): Promise<boolean> => {
    if (!value) return false;
    try {
      await navigator.clipboard?.writeText(value);
      message.success(t("pluginDetail.messages.copied", "Copied"));
      return true;
    } catch {
      message.error(t("pluginDetail.messages.copyFailed", "Copy failed"));
      return false;
    }
  };

  const handleRefreshStatus = async () => {
    setRefreshing(true);
    try {
      await loadDetail(false);
    } finally {
      setRefreshing(false);
    }
  };

  if (loading) {
    return (
      <div className={styles.loading}>
        <Spin />
      </div>
    );
  }

  if (!detail) {
    return <Empty className={styles.empty} />;
  }

  const runtime = detail.runtime_status ?? {};
  const connected = Boolean(runtime.connected);
  const installed = detail.installed ?? true;
  const hasFrontendEntry = Boolean(detail.frontend_entry);
  const devRows = [
    [t("pluginDetail.dev.installMode", "Install mode"), runtime.install_mode],
    [t("pluginDetail.dev.extensionId", "Extension ID"), runtime.extension_id],
    [
      t("pluginDetail.dev.extensionDir", "Extension folder"),
      runtime.extension_dir,
    ],
    [
      t("pluginDetail.dev.nativeManifest", "Native manifest"),
      runtime.native_manifest_path,
    ],
    [t("pluginDetail.dev.nativeHost", "Native host"), runtime.native_host_path],
    [t("pluginDetail.dev.config", "Config"), runtime.config_path],
    [t("pluginDetail.dev.wsUrl", "Bridge endpoint"), runtime.ws_url],
    [
      t("pluginDetail.dev.chromeUrl", "Chrome extensions URL"),
      runtime.chrome_extensions_url,
    ],
  ].filter(([, value]) => Boolean(value));

  return (
    <div className={styles.page}>
      <PageHeader
        className={styles.pageHeader}
        items={[
          {
            title: (
              <button
                className={styles.breadcrumbButton}
                onClick={() => navigate("/plugin-manager")}
              >
                {t("pluginDetail.manager", "Plugin Manager")}
              </button>
            ),
          },
          { title: detail.name },
        ]}
        extra={
          <div className={styles.headerExtra}>
            {connected ? (
              <span className={styles.connectedBadge}>
                <span className={styles.connectedDot} />
                {t("pluginDetail.status.connected", "Connected")}
              </span>
            ) : null}
            <Button
              icon={<RefreshCw size={14} />}
              loading={refreshing}
              onClick={handleRefreshStatus}
            >
              {t("pluginDetail.actions.refresh", "Refresh")}
            </Button>
          </div>
        }
      />

      <div className={styles.detailContent}>
        <div className={styles.pluginInfoCard}>
          <div className={styles.pluginIcon}>
            <Globe size={28} />
          </div>
          <div className={styles.pluginMeta}>
            <div className={styles.pluginName}>{detail.name}</div>
            <div className={styles.pluginDesc}>{detail.description}</div>
            <div className={styles.pluginTags}>
              <span className={`${styles.tag} ${styles.tagVersion}`}>
                v{detail.version}
              </span>
              <span className={`${styles.tag} ${styles.tagVersion}`}>
                {installed
                  ? t("pluginDetail.status.installed", "Installed")
                  : t("pluginDetail.status.notInstalled", "Not installed")}
              </span>
              {connected ? (
                <span className={`${styles.tag} ${styles.tagConnected}`}>
                  {t("pluginDetail.status.connected", "Connected")}
                </span>
              ) : null}
            </div>
          </div>
        </div>

        {hasFrontendEntry ? (
          <div className={styles.setupSection}>
            <div className={styles.browserStatus}>
              <div>
                <div className={styles.browserStatusBadge}>
                  {t("pluginDetail.frontend.title", "Frontend entry")}
                </div>
                <div className={styles.browserStatusDesc}>
                  {detail.frontend_entry}
                </div>
              </div>
              <Button
                type="primary"
                onClick={() => navigate(`/plugin/${detail.id}`)}
              >
                {t("pluginDetail.frontend.open", "Open")}
              </Button>
            </div>
          </div>
        ) : null}

        {setupSteps.length ? (
          <div className={styles.setupSection}>
            <div className={styles.steps}>
              {setupSteps.map((step, index) => {
                const state = stepClass(index, setupSteps);
                return (
                  <div
                    className={`${styles.step} ${
                      state !== "wait" ? styles.active : ""
                    }`}
                    key={step.id}
                  >
                    <div className={`${styles.stepDot} ${styles[state]}`}>
                      {index + 1}
                    </div>
                    <span className={styles.stepText}>
                      <span className={styles.stepLabel}>{step.title}</span>
                      {step.description ? (
                        <span className={styles.stepDesc}>
                          {step.description}
                        </span>
                      ) : null}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        ) : null}

        <div className={styles.capabilitiesSection}>
          <div className={styles.capabilitiesTitle}>
            {t("pluginDetail.capabilities", "Capabilities")}
          </div>
          <div className={styles.capabilityList}>
            {capabilities.length ? (
              capabilities.map((capability, index) => {
                const Icon = capabilityIcons[index % capabilityIcons.length];
                return (
                  <div className={styles.capabilityItem} key={capability.id}>
                    <div className={styles.capabilityIcon}>
                      <Icon size={16} />
                    </div>
                    <div className={styles.capabilityText}>
                      <strong>{capability.title}</strong>
                      {capability.description}
                    </div>
                  </div>
                );
              })
            ) : (
              <div className={styles.capabilityItem}>
                <div className={styles.capabilityIcon}>
                  <Package size={16} />
                </div>
                <div className={styles.capabilityText}>
                  <strong>
                    {t("pluginDetail.capabilitiesNone", "No capabilities")}
                  </strong>
                  {t(
                    "pluginDetail.capabilitiesNoneDesc",
                    "This plugin does not declare capability metadata.",
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

        <div
          className={`${styles.collapsePanel} ${devOpen ? styles.open : ""}`}
        >
          <button
            className={styles.collapseHeader}
            onClick={() => setDevOpen((value) => !value)}
          >
            <Settings size={16} />
            {t("pluginDetail.advanced", "Advanced")}
            <ChevronDown className={styles.collapseArrow} size={14} />
          </button>
          <div className={styles.collapseBody}>
            <div className={styles.devContent}>
              {devRows.map(([label, value]) => (
                <div className={styles.devRow} key={String(label)}>
                  <span className={styles.devLabel}>{label}</span>
                  <span className={styles.devValue}>{String(value)}</span>
                  <Tooltip title={t("common.copy", "Copy")}>
                    <button
                      className={styles.btnIcon}
                      onClick={() => copyValue(String(value))}
                    >
                      <Copy size={14} />
                    </button>
                  </Tooltip>
                </div>
              ))}
              {!devRows.length ? (
                <div className={styles.devRow}>
                  <span className={styles.devLabel}>
                    {t("pluginDetail.dev.runtime", "Runtime")}
                  </span>
                  <span className={styles.devValue}>
                    {t("pluginDetail.dev.noRuntime", "No runtime details")}
                  </span>
                </div>
              ) : null}
            </div>
          </div>
        </div>

        <div className={styles.pluginFooter}>
          <span className={styles.footerItem}>
            <Package size={12} />
            {t("pluginDetail.footer.id", "ID")}: {detail.id}
          </span>
          <span className={styles.footerItem}>
            <User size={12} />
            {t("pluginDetail.footer.author", "Author")}:{" "}
            {detail.author || t("pluginDetail.footer.unknown", "Unknown")}
          </span>
          <span className={styles.footerItem}>
            <CalendarDays size={12} />
            {t("pluginDetail.footer.updated", "Updated")}: {detail.version}
          </span>
          <span className={styles.footerItem}>
            {t("pluginDetail.footer.type", "Type")}:{" "}
            {detail.plugin_type?.toUpperCase()}
          </span>
        </div>
      </div>
    </div>
  );
}

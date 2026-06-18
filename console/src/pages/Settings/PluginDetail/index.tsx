import { useCallback, useEffect, useMemo, useState } from "react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { Button, Empty, Spin, Switch, Tooltip } from "antd";
import {
  CalendarDays,
  Check,
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
import { extensionApi } from "@/api/modules/extension";
import {
  fetchPluginDetail,
  updatePluginEnabled,
  type PluginCapability,
  type PluginDetail,
  type PluginSetupStep,
} from "@/api/modules/plugin";
import styles from "./index.module.less";

const capabilityIcons = [Eye, MousePointerClick, Monitor, Code2];

function relativeConnectedTime(
  value: string | null | undefined,
  t: TFunction,
): string {
  if (!value) return "";
  const connectedAt = new Date(value).getTime();
  if (!Number.isFinite(connectedAt)) return "";
  const minutes = Math.max(0, Math.floor((Date.now() - connectedAt) / 60000));
  if (minutes < 1) return t("pluginDetail.time.justNow", "just now");
  if (minutes < 60) {
    return t("pluginDetail.time.minutesAgo", "{{count}} min ago", {
      count: minutes,
    });
  }
  return t("pluginDetail.time.hoursAgo", "{{count}} hr ago", {
    count: Math.floor(minutes / 60),
  });
}

function stepClass(
  stepIndex: number,
  steps: PluginSetupStep[],
  installed?: boolean,
  connected?: boolean,
) {
  if (connected) return "finish";
  if (installed && stepIndex < Math.max(steps.length - 1, 1)) return "finish";
  if (!installed && stepIndex === 0) return "process";
  if (installed && stepIndex === Math.max(steps.length - 1, 0)) {
    return "process";
  }
  return "wait";
}

export default function PluginDetailPage() {
  const { pluginId = "" } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [detail, setDetail] = useState<PluginDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [updating, setUpdating] = useState(false);
  const [setupBusy, setSetupBusy] = useState(false);
  const [openChromeBusy, setOpenChromeBusy] = useState(false);
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

  const runtime = detail?.runtime_status ?? {};
  const enabled = detail?.enabled ?? false;
  const connected = Boolean(enabled && runtime.connected);
  const installed = Boolean(runtime.installed);
  const isBrowserTakeover = detail?.id === "browser-takeover";

  const browserSteps: PluginSetupStep[] = useMemo(
    () => [
      {
        id: "prepare",
        title: t("pluginDetail.browserTakeover.steps.prepare.title", "Prepare"),
        description: t(
          "pluginDetail.browserTakeover.steps.prepare.desc",
          "QwenPaw prepares the local files Chrome needs.",
        ),
      },
      {
        id: "load",
        title: t("pluginDetail.browserTakeover.steps.load.title", "Load"),
        description: t(
          "pluginDetail.browserTakeover.steps.load.desc",
          "Load the QwenPaw extension in Chrome.",
        ),
      },
      {
        id: "connect",
        title: t("pluginDetail.browserTakeover.steps.connect.title", "Connect"),
        description: t(
          "pluginDetail.browserTakeover.steps.connect.desc",
          "Return here and confirm Chrome is connected.",
        ),
      },
    ],
    [t],
  );

  const displayName = isBrowserTakeover
    ? t("pluginDetail.browserTakeover.name", "Browser Takeover")
    : detail?.name ?? "";
  const displayDescription = isBrowserTakeover
    ? t(
        "pluginDetail.browserTakeover.description",
        "Connect QwenPaw to Chrome so it can help with the page you choose.",
      )
    : detail?.description ?? "";
  const setupSteps = useMemo(
    () =>
      isBrowserTakeover
        ? browserSteps
        : detail?.setup?.steps ?? detail?.manifest.setup?.steps ?? [],
    [browserSteps, detail, isBrowserTakeover],
  );
  const capabilities: PluginCapability[] = useMemo(() => {
    if (isBrowserTakeover) {
      return [
        {
          id: "read-page",
          title: t(
            "pluginDetail.browserTakeover.capabilities.read.title",
            "Read pages",
          ),
          description: t(
            "pluginDetail.browserTakeover.capabilities.read.desc",
            "Summarize and extract information from the current tab.",
          ),
        },
        {
          id: "act-page",
          title: t(
            "pluginDetail.browserTakeover.capabilities.act.title",
            "Act for you",
          ),
          description: t(
            "pluginDetail.browserTakeover.capabilities.act.desc",
            "Click, type, and navigate after you ask QwenPaw to help.",
          ),
        },
      ];
    }
    return detail?.capabilities?.length
      ? detail.capabilities
      : detail?.manifest.capabilities ?? [];
  }, [detail, isBrowserTakeover, t]);

  const statusKey = !enabled
    ? "disabled"
    : connected
    ? "connected"
    : installed
    ? "waiting"
    : "notStarted";
  const statusText = t(
    `pluginDetail.browserTakeover.status.${statusKey}`,
    statusKey,
  );
  const statusDescription = t(
    `pluginDetail.browserTakeover.statusDesc.${statusKey}`,
    "",
  );
  const primaryActionLabel = !installed
    ? t("pluginDetail.browserTakeover.actions.start", "Start")
    : connected
    ? t("pluginDetail.browserTakeover.actions.connected", "Connected")
    : t("pluginDetail.browserTakeover.actions.openChrome", "Open Chrome");

  const handleToggle = async (checked: boolean) => {
    if (!detail) return;
    setUpdating(true);
    try {
      const next = await updatePluginEnabled(detail.id, checked);
      setDetail({ ...detail, ...next });
      message.success(
        checked
          ? t("pluginDetail.messages.enabled", "Plugin enabled")
          : t("pluginDetail.messages.disabled", "Plugin disabled"),
      );
      await loadDetail(false);
    } catch (err) {
      message.error(
        err instanceof Error
          ? err.message
          : t("pluginDetail.messages.updateFailed", "Update failed"),
      );
    } finally {
      setUpdating(false);
    }
  };

  const copyValue = async (
    value?: string | null,
    showSuccess = true,
  ): Promise<boolean> => {
    if (!value) return false;
    try {
      await navigator.clipboard?.writeText(value);
      if (showSuccess) {
        message.success(t("pluginDetail.messages.copied", "Copied"));
      }
      return true;
    } catch {
      message.error(t("pluginDetail.messages.copyFailed", "Copy failed"));
      return false;
    }
  };

  const handleSetup = async (reset = false) => {
    setSetupBusy(true);
    try {
      await extensionApi.setup({
        install_mode: "unpacked",
        ws_url:
          typeof runtime.ws_url === "string" && runtime.ws_url
            ? runtime.ws_url
            : undefined,
        reset,
      });
      message.success(
        t("pluginDetail.browserTakeover.messages.ready", "Ready"),
      );
      await loadDetail(false);
    } catch (err) {
      message.error(
        err instanceof Error
          ? err.message
          : t("pluginDetail.messages.setupFailed", "Setup failed"),
      );
    } finally {
      setSetupBusy(false);
    }
  };

  const handleRefreshStatus = async () => {
    setRefreshing(true);
    try {
      const next = await loadDetail(false);
      const nextRuntime = next?.runtime_status ?? {};
      message.info(
        nextRuntime.connected
          ? t(
              "pluginDetail.browserTakeover.messages.connected",
              "Chrome is connected.",
            )
          : t(
              "pluginDetail.browserTakeover.messages.waiting",
              "Still waiting for Chrome.",
            ),
      );
    } finally {
      setRefreshing(false);
    }
  };

  const handleOpenChrome = async () => {
    setOpenChromeBusy(true);
    try {
      const result = await extensionApi.openChromeExtensionsPage();
      if (result.opened) {
        message.success(
          t(
            "pluginDetail.browserTakeover.messages.openedChrome",
            "Chrome opened.",
          ),
        );
        return;
      }
      const copied = await copyValue(result.url, false);
      if (copied) {
        message.warning(
          t(
            "pluginDetail.browserTakeover.messages.chromeUrlCopied",
            "Could not open Chrome. The address was copied.",
          ),
        );
      }
    } catch (err) {
      const chromeUrl =
        typeof runtime.chrome_extensions_url === "string"
          ? runtime.chrome_extensions_url
          : "chrome://extensions";
      const copied = await copyValue(chromeUrl, false);
      if (!copied) {
        message.error(
          err instanceof Error
            ? err.message
            : t(
                "pluginDetail.browserTakeover.messages.openChromeFailed",
                "Could not open Chrome.",
              ),
        );
      }
    } finally {
      setOpenChromeBusy(false);
    }
  };

  const handlePrimaryAction = () => {
    if (connected) return;
    if (!installed) {
      handleSetup(false);
      return;
    }
    handleOpenChrome();
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

  const devRows = [
    [
      t("pluginDetail.dev.installMode", "Install mode"),
      runtime.install_mode ?? (installed ? "unpacked" : ""),
    ],
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
          { title: displayName },
        ]}
        extra={
          <div className={styles.headerExtra}>
            {connected ? (
              <span className={styles.connectedBadge}>
                <span className={styles.connectedDot} />
                {t("pluginDetail.status.connected", "Connected")}
              </span>
            ) : null}
            <Switch
              checked={enabled}
              loading={updating}
              onChange={handleToggle}
            />
          </div>
        }
      />

      <div className={styles.detailContent}>
        <div className={styles.pluginInfoCard}>
          <div className={styles.pluginIcon}>
            <Globe size={28} />
          </div>
          <div className={styles.pluginMeta}>
            <div className={styles.pluginName}>{displayName}</div>
            <div className={styles.pluginDesc}>{displayDescription}</div>
            <div className={styles.pluginTags}>
              {detail.meta?.builtin ? (
                <span className={`${styles.tag} ${styles.tagBuiltin}`}>
                  {t("pluginDetail.tags.builtin", "Built-in")}
                </span>
              ) : null}
              <span className={`${styles.tag} ${styles.tagVersion}`}>
                v{detail.version}
              </span>
              {connected ? (
                <span className={`${styles.tag} ${styles.tagConnected}`}>
                  {t("pluginDetail.status.connected", "Connected")}
                </span>
              ) : null}
            </div>
          </div>
        </div>

        <div
          className={`${styles.setupSection} ${
            enabled ? "" : `${styles.disabledOverlay} ${styles.isDisabled}`
          }`}
        >
          <div className={styles.browserStatus}>
            <div>
              <div
                className={`${styles.browserStatusBadge} ${
                  styles[`status-${statusKey}`]
                }`}
              >
                {statusText}
              </div>
              {statusDescription ? (
                <div className={styles.browserStatusDesc}>
                  {statusDescription}
                </div>
              ) : null}
            </div>
            {isBrowserTakeover ? (
              <Button
                type={connected ? "default" : "primary"}
                loading={setupBusy || openChromeBusy}
                disabled={!enabled || connected}
                onClick={handlePrimaryAction}
              >
                {primaryActionLabel}
              </Button>
            ) : null}
          </div>

          <div className={styles.steps}>
            {setupSteps.map((step, index) => {
              const state = stepClass(index, setupSteps, installed, connected);
              return (
                <div
                  className={`${styles.step} ${
                    state !== "wait" ? styles.active : ""
                  }`}
                  key={step.id}
                >
                  <div className={`${styles.stepDot} ${styles[state]}`}>
                    {state === "finish" ? <Check size={13} /> : index + 1}
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

          <div className={styles.setupActions}>
            {isBrowserTakeover ? (
              <Button
                size="small"
                icon={<RefreshCw size={14} />}
                loading={refreshing}
                onClick={handleRefreshStatus}
              >
                {t("pluginDetail.browserTakeover.actions.check", "Check")}
              </Button>
            ) : (
              <>
                <Button
                  size="small"
                  icon={<RefreshCw size={14} />}
                  onClick={() => loadDetail(false)}
                >
                  {t("pluginDetail.actions.refresh", "Refresh")}
                </Button>
                <Button
                  size="small"
                  type={installed ? "default" : "primary"}
                  loading={setupBusy}
                  onClick={() => handleSetup(false)}
                >
                  {detail.setup?.cta ??
                    t("pluginDetail.actions.configure", "Configure")}
                </Button>
              </>
            )}
            <span className={styles.setupMeta}>
              {runtime.version
                ? t(
                    "pluginDetail.meta.extensionVersion",
                    "Extension v{{version}}",
                    { version: runtime.version },
                  )
                : ""}
              {runtime.connected_since
                ? ` · ${t("pluginDetail.meta.connected", "connected {{time}}", {
                    time: relativeConnectedTime(
                      String(runtime.connected_since),
                      t,
                    ),
                  })}`
                : ""}
            </span>
          </div>
        </div>

        <div
          className={`${styles.capabilitiesSection} ${
            enabled ? "" : `${styles.disabledOverlay} ${styles.isDisabled}`
          }`}
        >
          <div className={styles.capabilitiesTitle}>
            {t("pluginDetail.capabilities", "Capabilities")}
          </div>
          <div className={styles.capabilityList}>
            {capabilities.map((capability, index) => {
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
            })}
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
              <div className={styles.devActions}>
                <Button
                  size="small"
                  icon={<RefreshCw size={14} />}
                  loading={setupBusy}
                  onClick={() => handleSetup(false)}
                >
                  {t("pluginDetail.dev.regenerate", "Regenerate files")}
                </Button>
                <Button
                  size="small"
                  loading={setupBusy}
                  onClick={() => handleSetup(true)}
                >
                  {t("pluginDetail.dev.reset", "Reset config")}
                </Button>
              </div>
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

import { useCallback, useEffect, useMemo, useState } from "react";
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
  Wrench,
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

function relativeConnectedTime(value?: string | null): string {
  if (!value) return "";
  const connectedAt = new Date(value).getTime();
  if (!Number.isFinite(connectedAt)) return "";
  const minutes = Math.max(0, Math.floor((Date.now() - connectedAt) / 60000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  return `${Math.floor(minutes / 60)} hr ago`;
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
  const { message } = useAppMessage();
  const [detail, setDetail] = useState<PluginDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [setupBusy, setSetupBusy] = useState(false);
  const [devOpen, setDevOpen] = useState(false);

  const loadDetail = useCallback(async () => {
    if (!pluginId) return;
    setLoading(true);
    try {
      setDetail(await fetchPluginDetail(pluginId));
    } catch (err) {
      message.error(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [message, pluginId]);

  useEffect(() => {
    loadDetail();
  }, [loadDetail]);

  const runtime = detail?.runtime_status ?? {};
  const enabled = detail?.enabled ?? false;
  const connected = Boolean(enabled && runtime.connected);
  const installed = Boolean(runtime.installed);
  const capabilities: PluginCapability[] = detail?.capabilities?.length
    ? detail.capabilities
    : detail?.manifest.capabilities ?? [];
  const setupSteps = useMemo(
    () => detail?.setup?.steps ?? detail?.manifest.setup?.steps ?? [],
    [detail],
  );

  const handleToggle = async (checked: boolean) => {
    if (!detail) return;
    setUpdating(true);
    try {
      const next = await updatePluginEnabled(detail.id, checked);
      setDetail({ ...detail, ...next });
      message.success(checked ? "Plugin enabled" : "Plugin disabled");
      await loadDetail();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "Update failed");
    } finally {
      setUpdating(false);
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
      message.success("Extension files ready");
      await loadDetail();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "Setup failed");
    } finally {
      setSetupBusy(false);
    }
  };

  const copyValue = async (value?: string | null) => {
    if (!value) return;
    try {
      await navigator.clipboard?.writeText(value);
      message.success("Copied");
    } catch {
      message.error("Copy failed");
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

  const devRows = [
    ["Install mode", runtime.install_mode ?? "unpacked"],
    ["Extension folder", runtime.extension_dir],
    ["Native Manifest", runtime.native_manifest_path],
    ["Bridge endpoint", runtime.ws_url],
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
                Plugin Manager
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
                Connected
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
            <div className={styles.pluginName}>{detail.name}</div>
            <div className={styles.pluginDesc}>{detail.description}</div>
            <div className={styles.pluginTags}>
              {detail.meta?.builtin ? (
                <span className={`${styles.tag} ${styles.tagBuiltin}`}>
                  Built-in
                </span>
              ) : null}
              <span className={`${styles.tag} ${styles.tagVersion}`}>
                v{detail.version}
              </span>
              {connected ? (
                <span className={`${styles.tag} ${styles.tagConnected}`}>
                  Connected
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
          <div className={styles.setupSectionTitle}>
            <Wrench size={16} />
            Chrome Extension Setup
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
                  <span className={styles.stepLabel}>{step.title}</span>
                </div>
              );
            })}
          </div>
          <div className={styles.setupActions}>
            <Button
              size="small"
              icon={<RefreshCw size={14} />}
              onClick={loadDetail}
            >
              Test Connection
            </Button>
            <Button
              size="small"
              type={installed ? "default" : "primary"}
              loading={setupBusy}
              onClick={() => handleSetup(false)}
            >
              {detail.setup?.cta ?? "Configure browser bridge"}
            </Button>
            {runtime.chrome_extensions_url ? (
              <Button
                size="small"
                type="link"
                onClick={() =>
                  window.open(String(runtime.chrome_extensions_url), "_blank")
                }
              >
                chrome://extensions
              </Button>
            ) : null}
            <span className={styles.setupMeta}>
              {runtime.version ? `Extension v${runtime.version}` : ""}
              {runtime.connected_since
                ? ` · connected ${relativeConnectedTime(
                    String(runtime.connected_since),
                  )}`
                : ""}
            </span>
          </div>
        </div>

        <div
          className={`${styles.capabilitiesSection} ${
            enabled ? "" : `${styles.disabledOverlay} ${styles.isDisabled}`
          }`}
        >
          <div className={styles.capabilitiesTitle}>Capabilities</div>
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
            Developer Options
            <ChevronDown className={styles.collapseArrow} size={14} />
          </button>
          <div className={styles.collapseBody}>
            <div className={styles.devContent}>
              {devRows.map(([label, value]) => (
                <div className={styles.devRow} key={label}>
                  <span className={styles.devLabel}>{label}</span>
                  <span className={styles.devValue}>{String(value)}</span>
                  <Tooltip title="Copy">
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
                  Regenerate files
                </Button>
                <Button
                  size="small"
                  loading={setupBusy}
                  onClick={() => handleSetup(true)}
                >
                  Reset config
                </Button>
              </div>
            </div>
          </div>
        </div>

        <div className={styles.pluginFooter}>
          <span className={styles.footerItem}>
            <Package size={12} />
            ID: {detail.id}
          </span>
          <span className={styles.footerItem}>
            <User size={12} />
            Author: {detail.author || "Unknown"}
          </span>
          <span className={styles.footerItem}>
            <CalendarDays size={12} />
            Updated: {detail.version}
          </span>
          <span className={styles.footerItem}>
            Type: {detail.plugin_type?.toUpperCase()}
          </span>
        </div>
      </div>
    </div>
  );
}

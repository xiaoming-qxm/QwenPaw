import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useMemo } from "react";
import { Button, Empty, Spin, Table, Tabs } from "antd";
import { ExternalLink, Package, Plus } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { usePluginManager } from "./hooks/usePluginManager";
import { usePluginColumns } from "./hooks/usePluginColumns";
import { useInstallModal } from "./hooks/useInstallModal";
import { InstallPluginModal } from "./components/InstallPluginModal";
import { OfficialPluginList } from "./components/OfficialPluginList";
import { MarketPluginList } from "./components/MarketPluginList";
import styles from "./index.module.less";

export default function PluginManagerPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const {
    plugins,
    loading,
    refresh,
    uninstallingId,
    installingId,
    handleUninstall,
    handleInstallBundle,
  } = usePluginManager();

  const installModal = useInstallModal(refresh);
  const installedPlugins = useMemo(
    () => (plugins ?? []).filter((plugin) => plugin.installed !== false),
    [plugins],
  );

  const columns = usePluginColumns({
    uninstallingId,
    installingId,
    onUninstall: handleUninstall,
    onInstallBundle: handleInstallBundle,
  });

  const tabItems = [
    {
      key: "installed",
      label: t("pluginManager.installed"),
      children: (
        <Spin spinning={loading}>
          {!loading && installedPlugins.length === 0 ? (
            <Empty
              image={<Package size={48} strokeWidth={1} />}
              description={t("pluginManager.noPlugins")}
              style={{ marginTop: 24 }}
            />
          ) : (
            <Table
              dataSource={installedPlugins}
              columns={columns}
              rowKey="id"
              pagination={false}
              className={styles.table}
              rowClassName={styles.clickableRow}
              onRow={(record) => ({
                onClick: () => navigate(`/plugin-manager/${record.id}`),
              })}
            />
          )}
        </Spin>
      ),
    },
    {
      key: "official",
      label: t("pluginManager.officialTitle"),
      children: <OfficialPluginList onInstalled={refresh} />,
    },
    {
      key: "market",
      label: t("pluginManager.marketTitle"),
      children: <MarketPluginList onInstalled={refresh} />,
    },
  ];

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.settings")}
        current={t("nav.pluginManager")}
        extra={
          <>
            <Button
              icon={<ExternalLink size={16} />}
              onClick={() =>
                window.open("https://platform.agentscope.io/plugins", "_blank")
              }
            >
              {t("pluginManager.publishBtn")}
            </Button>
            <Button
              type="primary"
              icon={<Plus size={16} />}
              onClick={installModal.openModal}
            >
              {t("pluginManager.installBtn")}
            </Button>
          </>
        }
      />

      <div className={styles.content}>
        <Tabs items={tabItems} className={styles.tabs} />
      </div>

      <InstallPluginModal {...installModal} />
    </div>
  );
}

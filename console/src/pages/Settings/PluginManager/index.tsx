import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { Button, Empty, Spin, Table, Tabs } from "antd";
import { Package, Plus } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { usePluginManager } from "./hooks/usePluginManager";
import { usePluginColumns } from "./hooks/usePluginColumns";
import { useInstallModal } from "./hooks/useInstallModal";
import { InstallPluginModal } from "./components/InstallPluginModal";
import { OfficialPluginList } from "./components/OfficialPluginList";
import styles from "./index.module.less";

export default function PluginManagerPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const {
    plugins,
    loading,
    refresh,
    uninstallingId,
    togglingId,
    handleUninstall,
    handleToggle,
  } = usePluginManager();

  const installModal = useInstallModal(refresh);

  const columns = usePluginColumns({
    uninstallingId,
    togglingId,
    onUninstall: handleUninstall,
    onToggle: handleToggle,
  });

  const tabItems = [
    {
      key: "installed",
      label: t("pluginManager.installed"),
      children: (
        <Spin spinning={loading}>
          {!loading && (!plugins || plugins.length === 0) ? (
            <Empty
              image={<Package size={48} strokeWidth={1} />}
              description={t("pluginManager.noPlugins")}
              style={{ marginTop: 24 }}
            />
          ) : (
            <Table
              dataSource={plugins}
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
  ];

  return (
    <div className={styles.page}>
      <PageHeader
        parent={t("nav.settings")}
        current={t("nav.pluginManager")}
        extra={
          <Button
            type="primary"
            icon={<Plus size={16} />}
            onClick={installModal.openModal}
          >
            {t("pluginManager.installBtn")}
          </Button>
        }
      />

      <div className={styles.content}>
        <Tabs items={tabItems} className={styles.tabs} />
      </div>

      <InstallPluginModal {...installModal} />
    </div>
  );
}

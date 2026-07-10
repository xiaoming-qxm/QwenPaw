import React from "react";
import { useTranslation } from "react-i18next";
import { GlobalOutlined } from "@ant-design/icons";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell } from "../shared";
import { buildBrowserOperation } from "../shared/browserOperation";
import styles from "../shared/toolCards.module.less";

function actionLabel(action: string): string {
  const labels: Record<string, string> = {
    click: "Click",
    fill: "Fill",
    hover: "Hover",
    navigate: "Navigate",
    open: "Open",
    press_key: "Press key",
    reload: "Reload",
    screenshot: "Screenshot",
    scroll: "Scroll",
    snapshot: "Snapshot",
    type: "Type",
    wait_for: "Wait for",
  };
  return labels[action] || action.replace(/_/g, " ");
}

export interface BrowserCompactCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const BrowserCompactCard: React.FC<BrowserCompactCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const operation = buildBrowserOperation(content);
  const hasOperationEvidence = Boolean(
    operation.stepCount || operation.rawTrace,
  );
  const stepCountLabel =
    operation.stepCount === 1 ? "1 step" : `${operation.stepCount} steps`;
  const badges = (
    <>
      {operation.stepCount > 0 && (
        <span className={styles.lineReadBadge}>{stepCountLabel}</span>
      )}
      {operation.title !== "Browser" && (
        <span
          className={styles.browserCompactContextBadge}
          title={
            operation.backendLabel
              ? `Browser · ${operation.backendLabel}`
              : "Browser"
          }
        >
          Browser
        </span>
      )}
      {operation.backendLabel && (
        <span
          className={styles.browserCompactBackendBadge}
          title={operation.backendLabel}
        >
          {operation.backendLabel}
        </span>
      )}
    </>
  );

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<GlobalOutlined />}
      title={operation.title}
      badges={badges}
    >
      {operation.steps.length > 0 && (
        <ol
          aria-label={t("tool.browserCompact.stepsLabel", "Browser steps")}
          className={styles.browserCompactSteps}
        >
          {operation.steps.map((step, index) => (
            <li key={`${step.apiId || step.action}-${index}`}>
              <span className={styles.browserCompactAction}>
                {step.apiId || actionLabel(step.action)}
              </span>
              {step.detail && (
                <span className={styles.browserCompactDetail}>
                  {step.detail}
                </span>
              )}
              {step.status && step.status !== "ok" && (
                <span className={styles.browserCompactStatus}>
                  {step.status}
                </span>
              )}
            </li>
          ))}
        </ol>
      )}
      {hasOperationEvidence && operation.summaryRows.length > 0 && (
        <dl aria-label="Browser summary" className={styles.browserCompactRows}>
          {operation.summaryRows.map((item) => (
            <div key={item.label} className={styles.browserCompactRow}>
              <dt>{item.label}</dt>
              <dd>{item.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {hasOperationEvidence && operation.paramsRows.length > 0 && (
        <dl aria-label="Browser params" className={styles.browserCompactRows}>
          {operation.paramsRows.map((item) => (
            <div key={item.label} className={styles.browserCompactRow}>
              <dt>{item.label}</dt>
              <dd>{item.value}</dd>
            </div>
          ))}
        </dl>
      )}
      {operation.rawTrace && (
        <details className={styles.browserCompactRawTrace}>
          <summary>Raw trace</summary>
          <pre>{operation.rawTrace}</pre>
        </details>
      )}
      {!hasOperationEvidence && operation.fallbackDetail && (
        <div className={styles.browserCompactFallback}>
          {operation.fallbackDetail}
        </div>
      )}
    </ToolCardShell>
  );
};

export default BrowserCompactCard;

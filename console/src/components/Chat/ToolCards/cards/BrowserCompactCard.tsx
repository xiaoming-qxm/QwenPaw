import React from "react";
import { useTranslation } from "react-i18next";
import { ChromeOutlined } from "@ant-design/icons";
import type { ToolCallContent } from "../shared/types";
import type { BrowserTraceEventPreview } from "../shared/utils";
import { ToolCardShell } from "../shared";
import styles from "../shared/toolCards.module.less";

interface BrowserStep {
  apiId: string;
  action: string;
  status: string;
  detail: string;
}

const DEFAULT_HIDDEN_API_IDS = new Set([
  "browser.connect",
  "browser.close",
  "browser.capabilities",
  "browser.diagnostics",
  "browser.help",
]);

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function parseRecord(value: unknown): Record<string, unknown> {
  if (typeof value !== "string") return asRecord(value);
  try {
    return asRecord(JSON.parse(value));
  } catch {
    return {};
  }
}

function toText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function browserTrace(value: unknown): BrowserTraceEventPreview[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => asRecord(item) as BrowserTraceEventPreview);
}

function compactUrl(value: string): string {
  if (!value) return "";
  try {
    const url = new URL(value);
    return `${url.host}${url.pathname === "/" ? "" : url.pathname}`;
  } catch {
    return value;
  }
}

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

function isVisibleApiId(apiId: string): boolean {
  return Boolean(apiId) && !DEFAULT_HIDDEN_API_IDS.has(apiId);
}

function eventDetail(event: BrowserTraceEventPreview): string {
  const metadata = asRecord(event.metadata);
  return (
    compactUrl(toText(event.url)) ||
    toText(metadata.target_text) ||
    toText(metadata.accessible_name) ||
    toText(metadata.text) ||
    toText(event.title) ||
    toText(event.domain) ||
    toText(event.selector) ||
    ""
  );
}

function stepsFromContent(content: ToolCallContent): BrowserStep[] {
  const result = parseRecord(content.result);
  const params = asRecord(content.params);
  const rawTrace = result.browser_trace || params.browser_trace;
  const events = browserTrace(rawTrace);
  if (events.length > 0) {
    return events
      .map((event) => ({
        apiId: toText(event.api_id),
        action: toText(event.action) || toText(event.phase) || "browser",
        status: toText(event.status) || "done",
        detail: eventDetail(event),
      }))
      .filter((step) => isVisibleApiId(step.apiId));
  }

  return [
    {
      apiId: "",
      action: toText(params.action) || content.name,
      status: content.status,
      detail:
        compactUrl(toText(params.url)) ||
        toText(params.text) ||
        toText(params.selector),
    },
  ];
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
  const steps = stepsFromContent(content);
  const chromeTitle = t("tool.browserCompact.chromeTitle", "Chrome");
  const title = steps[0]?.apiId
    ? `${chromeTitle}: ${steps[0].apiId}`
    : chromeTitle;
  const stepCountLabel = `${steps.length} steps`;

  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<ChromeOutlined />}
      title={title}
      badges={<span className={styles.lineReadBadge}>{stepCountLabel}</span>}
    >
      <ol
        aria-label={t("tool.browserCompact.stepsLabel", "Browser steps")}
        className={styles.browserCompactSteps}
      >
        {steps.map((step, index) => (
          <li key={`${step.action}-${index}`}>
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
    </ToolCardShell>
  );
};

export default BrowserCompactCard;

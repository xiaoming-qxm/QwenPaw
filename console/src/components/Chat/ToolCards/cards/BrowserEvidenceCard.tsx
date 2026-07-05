import React, { useCallback } from "react";
import { Button } from "antd";
import { ChromeOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import type { ToolCallContent } from "../shared/types";
import { ToolCardShell } from "../shared";
import {
  browserBlockerSummary,
  browserDurationLabel,
  browserRouteSummary,
  extractBrowserEvidence,
  toDisplayUrl,
} from "../shared/utils";

interface BrowserEvidenceCardProps {
  content: ToolCallContent;
  isStreaming?: boolean;
}

const gridStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
  gap: 8,
  margin: "8px 0 4px 18px",
};

const fieldStyle: React.CSSProperties = {
  border: "1px solid var(--ant-color-border-secondary, rgba(0,0,0,0.06))",
  borderRadius: 8,
  padding: "8px 10px",
  minWidth: 0,
};

const labelStyle: React.CSSProperties = {
  color: "var(--ant-color-text-tertiary, rgba(0,0,0,0.45))",
  fontSize: 12,
  marginBottom: 3,
};

const valueStyle: React.CSSProperties = {
  color: "var(--ant-color-text, rgba(0,0,0,0.88))",
  fontFamily:
    "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
  fontSize: 12,
  overflowWrap: "anywhere",
};

const hintStyle: React.CSSProperties = {
  margin: "6px 0 4px 18px",
  color: "var(--ant-color-text-secondary, rgba(0,0,0,0.65))",
  fontSize: 12,
  lineHeight: 1.5,
};

const artifactStyle: React.CSSProperties = {
  margin: "6px 0 4px 18px",
  display: "flex",
  gap: 8,
  flexWrap: "wrap",
  alignItems: "center",
  fontSize: 12,
};

const BrowserEvidenceCard: React.FC<BrowserEvidenceCardProps> = ({
  content,
  isStreaming,
}) => {
  const { t } = useTranslation();
  const evidence = extractBrowserEvidence(content);
  const route = browserRouteSummary(evidence);
  const blocker = browserBlockerLabel(t, evidence);
  const duration = browserDurationLabel(evidence.durationMs);
  const eventLabel = `${evidence.eventCount} ${
    evidence.eventCount === 1 ? "event" : "events"
  }`;
  const approvalLabel = `${t(
    "tool.browserEvidence.approvalPrefix",
    "Approval",
  )}: ${evidence.approvalState}`;
  const copyDiagnostics = useCallback(async () => {
    await navigator.clipboard?.writeText(
      JSON.stringify(evidence.diagnostics, null, 2),
    );
  }, [evidence.diagnostics]);

  return (
    <ToolCardShell
      content={content}
      icon={<ChromeOutlined />}
      inlineResult={blocker === "No blocker" ? route : blocker}
      isStreaming={isStreaming}
      title={t("tool.browserEvidence.title", "Browser evidence")}
      badges={
        evidence.eventCount ? (
          <span
            style={{
              color: "var(--ant-color-text-secondary, rgba(0,0,0,0.56))",
              fontSize: 12,
              fontWeight: 500,
            }}
          >
            {eventLabel}
          </span>
        ) : null
      }
    >
      <div style={gridStyle}>
        <EvidenceField
          label={t("tool.browserEvidence.route", "Route")}
          value={route}
        />
        <EvidenceField
          label={t("tool.browserEvidence.backend", "Backend")}
          value={evidence.backendId || "-"}
        />
        <EvidenceField
          label={t("tool.browserEvidence.approval", "Approval")}
          value={approvalLabel}
        />
        <EvidenceField
          label={t("tool.browserEvidence.blocker", "Blocker")}
          value={blocker}
        />
        <EvidenceField
          label={t("tool.browserEvidence.duration", "Duration")}
          value={duration}
        />
      </div>

      {evidence.recoveryHint ? (
        <div style={hintStyle}>{evidence.recoveryHint}</div>
      ) : null}

      {evidence.artifacts.length ? (
        <div style={artifactStyle}>
          <span>{t("tool.browserEvidence.artifacts", "Artifacts")}</span>
          {evidence.artifacts.map((artifact, index) => {
            const name =
              artifact.name ||
              artifact.url?.split("/").pop() ||
              artifact.kind ||
              `artifact-${index + 1}`;
            return artifact.url ? (
              <a
                href={toDisplayUrl(artifact.url)}
                key={`${artifact.url}:${index}`}
                rel="noreferrer"
                target="_blank"
              >
                {name}
              </a>
            ) : (
              <span key={`${name}:${index}`}>{name}</span>
            );
          })}
        </div>
      ) : null}

      <div style={{ margin: "8px 0 2px 18px" }}>
        <Button onClick={copyDiagnostics} size="small">
          {t("tool.browserEvidence.copyDiagnostics", "Copy diagnostics")}
        </Button>
      </div>
    </ToolCardShell>
  );
};

function EvidenceField({ label, value }: { label: string; value: string }) {
  return (
    <div style={fieldStyle}>
      <div style={labelStyle}>{label}</div>
      <div style={valueStyle}>{value}</div>
    </div>
  );
}

function browserBlockerLabel(
  t: ReturnType<typeof useTranslation>["t"],
  evidence: ReturnType<typeof extractBrowserEvidence>,
): string {
  if (evidence.progressDecision === "no_progress" && !evidence.blockerReason) {
    return t("tool.browserEvidence.noProgress", "Blocked: no progress");
  }
  if (evidence.cleanupComplete && !evidence.blockerReason) {
    return t("tool.browserEvidence.cleanupComplete", "Cleanup complete");
  }
  return browserBlockerSummary(evidence);
}

export default BrowserEvidenceCard;

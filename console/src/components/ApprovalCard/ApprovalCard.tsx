import { useState, useEffect, useCallback, useMemo } from "react";
import { Button, Card, Tag, Typography, Space, Tooltip } from "antd";
import { Shield, Check, X, Clock, Copy, AlertCircle } from "lucide-react";
import type { ToolExecutionLevel } from "../../utils/approval";
import { useTranslation } from "react-i18next";
import { useAgentStore } from "../../stores/agentStore";
import { getAgentDisplayName } from "../../utils/agentDisplayName";
import styles from "./ApprovalCard.module.less";

const { Text } = Typography;
const REDACTED = "[REDACTED]";
const SENSITIVE_PARAM_KEYS = [
  "authorization",
  "cookie",
  "credential",
  "otp",
  "password",
  "secret",
  "token",
];
const SENSITIVE_EXACT_PARAM_KEYS = [
  "file_path",
  "file_paths",
  "files",
  "prompt_text",
  "text",
];

export interface ApprovalCardProps {
  requestId: string;
  toolName: string;
  toolSource?: string;
  severity: string;
  findingsCount: number;
  findingsSummary: string;
  toolParams: Record<string, unknown>;
  approvalBrief?: ApprovalBrief;
  createdAt: number;
  timeoutSeconds: number;
  agentId: string;
  ownerAgentId?: string;
  showInboxAgentContext?: boolean;
  sessionId?: string;
  rootSessionId?: string;
  // Approval-scope choice (console-only). When true the card renders
  // Approve Pattern + Approve Exact; when false, a single Approve button.
  isGeneralized?: boolean;
  exactTarget?: string;
  similarTarget?: string;
  executionLevel?: ToolExecutionLevel;
  onApprove: (requestId: string, scope?: "exact" | "similar") => Promise<void>;
  onDeny: (requestId: string) => Promise<void>;
  onCancel?: () => void;
  onAcknowledge?: (requestId: string) => Promise<void>;
}

export interface ApprovalBrief {
  subject?: string;
  target?: string;
  evidence?: Record<string, unknown>;
  uncertainties?: string[];
  possible_consequences?: string[];
  risk_kind?: string;
  risk_level?: string;
  confidence?: number;
  why_approval_required?: string;
  safe_alternative?: string;
}

export function ApprovalCard({
  requestId,
  toolName,
  toolSource,
  severity,
  findingsCount,
  findingsSummary,
  toolParams,
  approvalBrief,
  createdAt,
  timeoutSeconds,
  agentId,
  ownerAgentId,
  showInboxAgentContext = false,
  sessionId,
  rootSessionId,
  isGeneralized,
  exactTarget,
  similarTarget,
  executionLevel,
  onApprove,
  onDeny,
  onCancel,
  onAcknowledge,
}: ApprovalCardProps) {
  const { t } = useTranslation();
  const isStrictMode = executionLevel === "STRICT";
  const agents = useAgentStore((state) => state.agents);
  const agentsById = useMemo(
    () => new Map(agents.map((agent) => [agent.id, agent])),
    [agents],
  );
  const [loading, setLoading] = useState<
    "approve-pattern" | "approve-exact" | "deny" | "acknowledge" | null
  >(null);
  const [remaining, setRemaining] = useState<number>(timeoutSeconds);
  const [copiedField, setCopiedField] = useState<string | null>(null);
  const redactedToolParams = useMemo(
    () => redactSensitiveParams(toolParams),
    [toolParams],
  );
  const browserApproval = useMemo(
    () => browserApprovalSummary(toolParams),
    [toolParams],
  );
  const exactOnlyApproval = toolParams.scope_policy === "exact_only";
  const canApproveSimilar = Boolean(isGeneralized && !exactOnlyApproval);
  const redactedApprovalBrief = useMemo(
    () => approvalBriefSummary(approvalBrief),
    [approvalBrief],
  );

  const handleCopy = useCallback(async (text: string, field: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedField(field);
      setTimeout(() => setCopiedField(null), 1500);
    } catch {
      /* clipboard not available */
    }
  }, []);

  // Check if this is a cross-session approval
  const isCrossSession =
    sessionId && rootSessionId && sessionId !== rootSessionId;
  const isTimedOut = showInboxAgentContext && remaining <= 0;
  const executionAgentDisplayName = useMemo(() => {
    const matched = agentsById.get(agentId);
    if (matched) return getAgentDisplayName(matched, t);
    return agentId || t("common.unknown", "Unknown");
  }, [agentsById, agentId, t]);
  const ownerAgentDisplayName = useMemo(() => {
    const ownerId = ownerAgentId || agentId;
    const matched = agentsById.get(ownerId);
    if (matched) return getAgentDisplayName(matched, t);
    return ownerId || t("common.unknown", "Unknown");
  }, [agentsById, ownerAgentId, agentId, t]);
  const shouldShowExecutionAgent =
    showInboxAgentContext && Boolean(isCrossSession);
  const displayToolSource =
    toolSource && toolSource !== "builtin"
      ? toolSource
      : t("approval.builtinSource", "Built-in");

  useEffect(() => {
    const elapsed = Date.now() / 1000 - createdAt;
    const initialRemaining = Math.max(0, Math.floor(timeoutSeconds - elapsed));
    setRemaining(initialRemaining);

    const timer = setInterval(() => {
      const newElapsed = Date.now() / 1000 - createdAt;
      const newRemaining = Math.max(0, Math.floor(timeoutSeconds - newElapsed));
      setRemaining(newRemaining);

      if (newRemaining <= 0) {
        clearInterval(timer);
      }
    }, 1000);

    return () => clearInterval(timer);
  }, [createdAt, timeoutSeconds]);

  const handleApprove = async (scope?: "exact" | "similar") => {
    const loadingKey =
      scope === "similar" ? "approve-pattern" : "approve-exact";
    setLoading(loadingKey);
    try {
      await onApprove(requestId, scope);
    } catch (err) {
      console.error("[ApprovalCard] onApprove failed:", err);
    } finally {
      setLoading(null);
    }
  };

  const handleDeny = async () => {
    setLoading("deny");
    try {
      await onDeny(requestId);
    } finally {
      setLoading(null);
    }
  };

  const handleAcknowledge = async () => {
    if (!onAcknowledge) return;
    setLoading("acknowledge");
    try {
      await onAcknowledge(requestId);
    } finally {
      setLoading(null);
    }
  };

  const getSeverityColor = (sev: string) => {
    const s = sev.toLowerCase();
    if (s === "critical" || s === "high") return "error";
    if (s === "medium") return "warning";
    return "default";
  };

  return (
    <Card className={styles.approvalCard} bordered={false}>
      <div className={styles.header}>
        <Space size={8} align="center" className={styles.titleRow}>
          <Shield size={16} className={styles.icon} />
          <Text className={styles.title}>
            {t("approval.title", "Security Approval Required")}
          </Text>
        </Space>
        <Space size={6} align="center" className={styles.timer}>
          <Clock size={14} className={styles.timerIcon} />
          <Text className={styles.timerText}>
            {Math.floor(remaining / 60)}:
            {String(remaining % 60).padStart(2, "0")}
          </Text>
        </Space>
      </div>

      <div className={styles.content}>
        {showInboxAgentContext ? (
          <>
            <div className={styles.infoRow}>
              <Text className={styles.label}>
                {t("approval.ownerAgent", "Owner Agent")}:
              </Text>
              <Tag color="success" className={styles.ownerAgentTag}>
                {ownerAgentDisplayName}
              </Tag>
            </div>
            {shouldShowExecutionAgent ? (
              <div className={styles.infoRow}>
                <Text className={styles.label}>
                  {t("approval.executingAgent", "Executing Agent")}:
                </Text>
                <Tag color="blue" className={styles.crossSessionTag}>
                  {executionAgentDisplayName}
                </Tag>
              </div>
            ) : null}
          </>
        ) : null}

        <div className={styles.infoRow}>
          <Text className={styles.label}>{t("approval.tool", "Tool")}:</Text>
          <Text className={styles.value} code>
            {toolName}
          </Text>
        </div>

        <div className={styles.infoRow}>
          <Text className={styles.label}>
            {t("approval.source", "Source")}:
          </Text>
          <Text className={styles.value} code>
            {displayToolSource}
          </Text>
        </div>

        <div className={styles.infoRow}>
          <Text className={styles.label}>
            {t("approval.severity", "Severity")}:
          </Text>
          <Tag
            color={getSeverityColor(severity)}
            className={styles.severityTag}
          >
            {severity.toUpperCase()}
          </Tag>
        </div>

        <div className={styles.infoRow}>
          <Text className={styles.label}>
            {t("approval.findings", "Findings")}:
          </Text>
          <Text className={styles.value}>{findingsCount}</Text>
        </div>

        {isCrossSession && !showInboxAgentContext && (
          <div className={styles.infoRow}>
            <Text className={styles.label}>
              {t("approval.source", "Source")}:
            </Text>
            <Tag color="blue" className={styles.crossSessionTag}>
              {t("approval.subSession", "Sub-Agent")} ({sessionId?.slice(0, 8)})
            </Tag>
          </div>
        )}

        {canApproveSimilar && (exactTarget || similarTarget) && (
          <div className={styles.scopeSection}>
            <Text className={styles.scopeLabel}>
              {t("approval.approvalScope", "Approval scope")}:
            </Text>
            <div className={styles.scopeItems}>
              <div className={styles.scopeItem}>
                <Text className={styles.scopeItemLabel}>
                  {t("approval.approveExact", "Just Once")}:
                </Text>
                <code className={styles.scopeCode}>{exactTarget}</code>
              </div>
              <div className={styles.scopeItem}>
                <Text className={styles.scopeItemLabel}>
                  {t("approval.approvePattern", "Always Allow")}:
                </Text>
                <code className={styles.scopeCode}>{similarTarget}</code>
                {isStrictMode && (
                  <Tooltip
                    title={t(
                      "approval.strictModeHint",
                      "Always allow is unavailable in strict mode",
                    )}
                  >
                    <AlertCircle
                      size={14}
                      className={styles.strictModeHintIcon}
                    />
                  </Tooltip>
                )}
              </div>
            </div>
          </div>
        )}

        {findingsSummary && (
          <div className={styles.summaryBox}>
            <Text className={styles.summaryText}>{findingsSummary}</Text>
            <button
              className={`${styles.copyButton} ${
                copiedField === "summary" ? styles.copied : ""
              }`}
              onClick={() => handleCopy(findingsSummary, "summary")}
              title={t("common.copy", "Copy")}
            >
              <Copy size={12} />
            </button>
          </div>
        )}

        {redactedApprovalBrief ? (
          <div className={styles.approvalBrief}>
            <div className={styles.approvalBriefTitle}>
              {t("approval.decisionBrief", "Decision brief")}
            </div>
            <div className={styles.browserApprovalGrid}>
              <BrowserField
                label={t("approval.briefSubject", "Subject")}
                value={redactedApprovalBrief.subject}
              />
              <BrowserField
                label={t("approval.briefTarget", "Target")}
                value={redactedApprovalBrief.target}
              />
              <BrowserField
                label={t("approval.briefRisk", "Risk")}
                value={redactedApprovalBrief.risk}
              />
              <BrowserField
                label={t("approval.briefConfidence", "Confidence")}
                value={redactedApprovalBrief.confidence}
              />
            </div>
            {redactedApprovalBrief.whyApprovalRequired ? (
              <BrowserField
                label={t(
                  "approval.whyApprovalRequired",
                  "Why approval is required",
                )}
                value={redactedApprovalBrief.whyApprovalRequired}
              />
            ) : null}
            {redactedApprovalBrief.evidenceRows.length ? (
              <div className={styles.browserKwargs}>
                <div className={styles.browserKwargsTitle}>
                  {t("approval.briefEvidence", "Evidence")}
                </div>
                {redactedApprovalBrief.evidenceRows.map((row) => (
                  <BrowserField
                    key={row.path}
                    label={row.path}
                    value={row.value}
                  />
                ))}
              </div>
            ) : null}
            {redactedApprovalBrief.consequences.length ? (
              <BriefList
                title={t("approval.possibleConsequences", "Consequences")}
                items={redactedApprovalBrief.consequences}
              />
            ) : null}
            {redactedApprovalBrief.uncertainties.length ? (
              <BriefList
                title={t("approval.uncertainties", "Uncertainties")}
                items={redactedApprovalBrief.uncertainties}
              />
            ) : null}
            {redactedApprovalBrief.safeAlternative ? (
              <BrowserField
                label={t("approval.safeAlternative", "Safe alternative")}
                value={redactedApprovalBrief.safeAlternative}
              />
            ) : null}
          </div>
        ) : null}

        {browserApproval ? (
          <div className={styles.browserApproval}>
            <div className={styles.browserApprovalTitle}>
              {t("approval.browserAction", "Browser action")}
            </div>
            <div className={styles.browserApprovalGrid}>
              <BrowserField
                label={t("approval.browserDomain", "Domain")}
                value={browserApproval.domain}
              />
              <BrowserField
                label={t("approval.browserUrl", "URL")}
                value={browserApproval.url}
              />
              <BrowserField
                label={t("approval.browserActionName", "Action")}
                value={browserApproval.action}
              />
              <BrowserField
                label={t("approval.browserRisk", "Risk")}
                value={`${browserApproval.riskKind} / ${browserApproval.riskLevel}`}
              />
            </div>
            {browserApproval.title ? (
              <BrowserField
                label={t("approval.browserTitle", "Title")}
                value={browserApproval.title}
              />
            ) : null}
            {browserApproval.expectedStateChange ? (
              <BrowserField
                label={t(
                  "approval.browserExpectedStateChange",
                  "Expected state change",
                )}
                value={browserApproval.expectedStateChange}
              />
            ) : null}
            {browserApproval.kwargsRows.length ? (
              <div className={styles.browserKwargs}>
                <div className={styles.browserKwargsTitle}>
                  {t("approval.browserArguments", "Arguments")}
                </div>
                {browserApproval.kwargsRows.map((row) => (
                  <BrowserField
                    key={row.path}
                    label={row.path}
                    value={row.value}
                  />
                ))}
              </div>
            ) : null}
          </div>
        ) : null}

        {!browserApproval &&
          toolParams &&
          Object.keys(toolParams).length > 0 && (
            <details className={styles.paramsDetails}>
              <summary className={styles.paramsSummary}>
                {t("approval.parameters", "Parameters")}
              </summary>
              <div className={styles.paramsCodeWrapper}>
                <pre className={styles.paramsCode}>
                  {JSON.stringify(redactedToolParams, null, 2)}
                </pre>
                <button
                  className={`${styles.copyButton} ${
                    copiedField === "params" ? styles.copied : ""
                  }`}
                  onClick={() =>
                    handleCopy(
                      JSON.stringify(redactedToolParams, null, 2),
                      "params",
                    )
                  }
                  title={t("common.copy", "Copy")}
                >
                  <Copy size={12} />
                </button>
              </div>
            </details>
          )}
      </div>

      <div className={styles.actions}>
        {isTimedOut ? (
          <>
            <Text className={styles.timeoutHint}>
              {t("approval.timeoutAutoDenied", "Timed out, auto denied")}
            </Text>
            {onAcknowledge ? (
              <Button
                type="primary"
                onClick={handleAcknowledge}
                loading={loading === "acknowledge"}
                disabled={loading !== null}
              >
                {t("approval.acknowledge", "Got It")}
              </Button>
            ) : null}
          </>
        ) : (
          <>
            {onCancel && (
              <Button
                type="default"
                onClick={() => {
                  onCancel();
                }}
                disabled={loading !== null}
              >
                {t("approval.cancelTask", "Cancel Task")}
              </Button>
            )}
            <Button
              danger
              icon={<X size={14} />}
              onClick={handleDeny}
              loading={loading === "deny"}
              disabled={loading !== null}
              className={styles.denyButton}
            >
              {t("approval.deny", "Deny")}
            </Button>
            {exactOnlyApproval ? (
              <Button
                type="primary"
                icon={<Check size={14} />}
                onClick={() => handleApprove("exact")}
                loading={loading === "approve-exact"}
                disabled={loading !== null}
              >
                {t("approval.approveExact", "Approve Exact")}
              </Button>
            ) : canApproveSimilar ? (
              <>
                <Button
                  onClick={() => handleApprove("exact")}
                  loading={loading === "approve-exact"}
                  disabled={loading !== null}
                  className={styles.approveOnceButton}
                >
                  {t("approval.approveExact", "Just Once")}
                </Button>
                <Tooltip
                  title={
                    isStrictMode
                      ? t(
                          "approval.strictModeHint",
                          "Always allow is unavailable in strict mode",
                        )
                      : undefined
                  }
                >
                  <Button
                    type="primary"
                    icon={<Check size={14} />}
                    onClick={() => handleApprove("similar")}
                    loading={loading === "approve-pattern"}
                    disabled={isStrictMode || loading !== null}
                    className={styles.approveAlwaysButton}
                  >
                    {t("approval.approvePattern", "Always Allow")}
                  </Button>
                </Tooltip>
              </>
            ) : (
              <Button
                type="primary"
                icon={<Check size={14} />}
                onClick={() => handleApprove()}
                loading={
                  loading === "approve-exact" || loading === "approve-pattern"
                }
                disabled={loading !== null}
                className={styles.approveAlwaysButton}
              >
                {t("approval.approve", "Approve")}
              </Button>
            )}
          </>
        )}
      </div>
    </Card>
  );
}

function BrowserField({ label, value }: { label: string; value: string }) {
  return (
    <div className={styles.browserField}>
      <span className={styles.browserFieldLabel}>{label}</span>
      <span className={styles.browserFieldValue}>{value || "-"}</span>
    </div>
  );
}

function BriefList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className={styles.briefList}>
      <div className={styles.briefListTitle}>{title}</div>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

interface BrowserApprovalSummary {
  domain: string;
  url: string;
  title: string;
  action: string;
  riskKind: string;
  riskLevel: string;
  expectedStateChange: string;
  kwargsRows: { path: string; value: string }[];
}

interface ApprovalBriefSummary {
  subject: string;
  target: string;
  risk: string;
  confidence: string;
  whyApprovalRequired: string;
  safeAlternative: string;
  consequences: string[];
  uncertainties: string[];
  evidenceRows: { path: string; value: string }[];
}

function approvalBriefSummary(
  brief: ApprovalBrief | undefined,
): ApprovalBriefSummary | null {
  if (!brief || !isRecord(brief)) {
    return null;
  }
  const evidence = isRecord(brief.evidence)
    ? redactSensitiveParams(brief.evidence)
    : {};
  return {
    subject: asString(brief.subject),
    target: asString(brief.target),
    risk: `${asString(brief.risk_kind) || "unknown"} / ${
      asString(brief.risk_level) || "unknown"
    }`,
    confidence:
      typeof brief.confidence === "number"
        ? `${Math.round(brief.confidence * 100)}%`
        : "",
    whyApprovalRequired: asString(brief.why_approval_required),
    safeAlternative: asString(brief.safe_alternative),
    consequences: stringList(brief.possible_consequences),
    uncertainties: stringList(brief.uncertainties),
    evidenceRows: flattenPreviewRows(evidence),
  };
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map(asString).filter(Boolean);
}

function browserApprovalSummary(
  params: Record<string, unknown>,
): BrowserApprovalSummary | null {
  const action = asString(params.action);
  const risk = isRecord(params.risk) ? params.risk : {};
  if (!action || !Object.keys(risk).length) {
    return null;
  }
  const kwargs = isRecord(params.kwargs)
    ? redactSensitiveParams(params.kwargs)
    : {};
  return {
    domain: asString(params.domain),
    url: asString(params.url),
    title: asString(params.title),
    action,
    riskKind: asString(risk.kind) || "unknown_sensitive",
    riskLevel: asString(risk.level) || "unknown",
    expectedStateChange: asString(params.expected_state_change),
    kwargsRows: flattenPreviewRows(kwargs),
  };
}

function flattenPreviewRows(
  value: unknown,
  prefix = "",
): { path: string; value: string }[] {
  if (!isRecord(value)) {
    return prefix ? [{ path: prefix, value: previewValue(value) }] : [];
  }
  return Object.entries(value).flatMap(([key, item]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    if (isRecord(item)) {
      return flattenPreviewRows(item, path);
    }
    if (Array.isArray(item)) {
      return [{ path, value: item.map(previewValue).join(", ") }];
    }
    return [{ path, value: previewValue(item) }];
  });
}

function previewValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

function redactSensitiveParams(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(redactSensitiveParams);
  }
  if (!isRecord(value)) {
    return value;
  }
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [
      key,
      isSensitiveParamKey(key) ? REDACTED : redactSensitiveParams(item),
    ]),
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isSensitiveParamKey(key: string): boolean {
  const lowered = key.toLowerCase();
  if (SENSITIVE_EXACT_PARAM_KEYS.includes(lowered)) {
    return true;
  }
  return SENSITIVE_PARAM_KEYS.some((token) => lowered.includes(token));
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

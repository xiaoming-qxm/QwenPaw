import type { ToolCallContent } from "./types";

type BrowserRecord = Record<string, unknown>;

export const HIDDEN_BROWSER_VALUE = "[hidden]";
export const MASKED_BROWSER_VALUE = "[masked]";

export interface BrowserOperationRow {
  label: string;
  value: string;
}

export interface BrowserOperationStep {
  apiId: string;
  action: string;
  status: string;
  detail: string;
  phase: string;
  error?: string;
}

export interface BrowserOperation {
  title: string;
  backendLabel: string;
  stepCount: number;
  steps: BrowserOperationStep[];
  summaryRows: BrowserOperationRow[];
  paramsRows: BrowserOperationRow[];
  rawTrace: string;
  fallbackDetail: string;
}

const DEFAULT_HIDDEN_API_IDS = new Set([
  "browser.connect",
  "browser.close",
  "browser.capabilities",
  "browser.diagnostics",
  "browser.help",
]);

const INTERNAL_PARAM_KEYS = new Set([
  "browser_trace",
  "trace",
  "raw_trace",
  "progress_decision",
  "recovery_decision",
  "runtime_outcome",
  "cleanup_summary",
]);

function asRecord(value: unknown): BrowserRecord {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as BrowserRecord)
    : {};
}

function parseRecord(value: unknown): BrowserRecord {
  if (typeof value !== "string") return asRecord(value);
  try {
    return asRecord(JSON.parse(value));
  } catch {
    return {};
  }
}

function traceEvents(value: unknown): BrowserRecord[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => asRecord(item));
}

function pickTraceSource(
  metadata: BrowserRecord,
  result: BrowserRecord,
  params: BrowserRecord,
): BrowserRecord[] {
  if (Array.isArray(metadata.browser_trace)) {
    return traceEvents(metadata.browser_trace);
  }
  if (Array.isArray(result.browser_trace)) {
    return traceEvents(result.browser_trace);
  }
  if (Array.isArray(params.browser_trace)) {
    return traceEvents(params.browser_trace);
  }
  return [];
}

function stringValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
}

function numberValue(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return undefined;
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

function eventMetadata(event: BrowserRecord): BrowserRecord {
  return asRecord(event.metadata);
}

function eventTarget(event: BrowserRecord): string {
  const metadata = eventMetadata(event);
  return (
    stringValue(metadata.target_text) ||
    stringValue(metadata.accessible_name) ||
    stringValue(metadata.text) ||
    stringValue(event.selector) ||
    stringValue(metadata.selector)
  );
}

function eventPage(event: BrowserRecord): string {
  return (
    compactUrl(stringValue(event.url)) ||
    stringValue(event.title) ||
    stringValue(event.domain)
  );
}

function eventDetail(event: BrowserRecord): string {
  return (
    eventTarget(event) ||
    eventPage(event) ||
    stringValue(event.title) ||
    stringValue(event.domain)
  );
}

function eventError(event: BrowserRecord): string {
  return (
    stringValue(event.error) ||
    stringValue(event.error_message) ||
    stringValue(event.message)
  );
}

function isVisibleEvent(event: BrowserRecord): boolean {
  const apiId = stringValue(event.api_id);
  if (!apiId || DEFAULT_HIDDEN_API_IDS.has(apiId)) return false;

  const phase = stringValue(event.phase).toLowerCase();
  return !["connect", "cleanup", "diagnostic", "diagnostics"].includes(phase);
}

function toStep(event: BrowserRecord): BrowserOperationStep {
  return {
    apiId: stringValue(event.api_id),
    action: stringValue(event.action) || stringValue(event.phase) || "browser",
    status: stringValue(event.status) || "done",
    detail: eventDetail(event),
    phase: stringValue(event.phase),
    error: eventError(event) || undefined,
  };
}

function isActionStep(step: BrowserOperationStep): boolean {
  return (
    step.phase === "action" ||
    step.apiId.startsWith("tab.actions.") ||
    [
      "click",
      "fill",
      "hover",
      "press_key",
      "scroll",
      "type",
      "wait_for",
      "evaluate",
    ].includes(step.action)
  );
}

function isNavigationStep(step: BrowserOperationStep): boolean {
  return (
    step.phase === "navigation" ||
    step.apiId.includes("navigate") ||
    step.apiId.includes("tabs.open") ||
    ["navigate", "open", "reload"].includes(step.action)
  );
}

function isObserveStep(step: BrowserOperationStep): boolean {
  return (
    step.phase === "observe" ||
    step.apiId.includes("snapshot") ||
    step.apiId.includes("screenshot") ||
    ["snapshot", "screenshot", "observe"].includes(step.action)
  );
}

function selectPrimaryStep(
  steps: BrowserOperationStep[],
): BrowserOperationStep | undefined {
  return (
    steps.find((step) => step.error || isErrorStatus(step.status)) ||
    steps.find(isActionStep) ||
    steps.find(isNavigationStep) ||
    steps.find(isObserveStep) ||
    steps[0]
  );
}

function isErrorStatus(status: string): boolean {
  const normalized = status.toLowerCase();
  return Boolean(
    normalized &&
      !["ok", "done", "success", "completed", "complete"].includes(normalized),
  );
}

function row(label: string, value: unknown): BrowserOperationRow | null {
  const display = stringValue(value);
  return display ? { label, value: display } : null;
}

function addRow(rows: BrowserOperationRow[], label: string, value: unknown) {
  const next = row(label, value);
  if (next) rows.push(next);
}

function displayValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (value === null || value === undefined) return "";
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function codeLikeKey(key: string): boolean {
  const normalized = key.toLowerCase();
  return (
    normalized === "code" ||
    normalized === "script" ||
    normalized === "javascript" ||
    normalized === "eval" ||
    normalized.endsWith("_code") ||
    normalized.endsWith("-code")
  );
}

function credentialLikeKey(key: string): boolean {
  return /token|cookie|authorization|password|secret|credential|api[_-]?key|auth/i.test(
    key,
  );
}

function sanitizeValue(value: unknown, key = ""): unknown {
  if (key && codeLikeKey(key)) return HIDDEN_BROWSER_VALUE;
  if (key && credentialLikeKey(key)) return MASKED_BROWSER_VALUE;

  if (Array.isArray(value)) {
    return value.map((item) => sanitizeValue(item));
  }

  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as BrowserRecord).map(([childKey, childValue]) => [
        childKey,
        sanitizeValue(childValue, childKey),
      ]),
    );
  }

  return value;
}

function paramsRows(params: BrowserRecord): BrowserOperationRow[] {
  return Object.entries(params)
    .filter(([key]) => !INTERNAL_PARAM_KEYS.has(key))
    .map(([key, value]) => ({
      label: key,
      value: displayValue(sanitizeValue(value, key)),
    }))
    .filter((item) => item.value !== "");
}

function firstString(...values: unknown[]): string {
  for (const value of values) {
    const display = stringValue(value);
    if (display) return display;
  }
  return "";
}

function firstNumber(...values: unknown[]): number | undefined {
  for (const value of values) {
    const parsed = numberValue(value);
    if (parsed !== undefined) return parsed;
  }
  return undefined;
}

function traceDuration(trace: BrowserRecord[]): number | undefined {
  return trace.reduce<number | undefined>((maxDuration, event) => {
    const duration = numberValue(event.duration_ms);
    if (duration === undefined) return maxDuration;
    return Math.max(maxDuration ?? 0, duration);
  }, undefined);
}

function latestPageEvent(trace: BrowserRecord[]): BrowserRecord {
  return (
    [...trace]
      .reverse()
      .find((event) => event.url || event.title || event.domain) || {}
  );
}

function resultText(value: unknown): string {
  if (typeof value === "string") return value;

  if (Array.isArray(value)) {
    const textBlock = value
      .map((item) => asRecord(item))
      .find((item) => item.type === "text" && stringValue(item.text));
    return stringValue(textBlock?.text);
  }

  const record = asRecord(value);
  return stringValue(record.output) || stringValue(record.text);
}

function buildSummaryRows(
  content: ToolCallContent,
  metadata: BrowserRecord,
  result: BrowserRecord,
  params: BrowserRecord,
  trace: BrowserRecord[],
  primary: BrowserOperationStep | undefined,
): BrowserOperationRow[] {
  const rows: BrowserOperationRow[] = [];
  if (!primary) return rows;

  const primaryEvent =
    trace.find((event) => stringValue(event.api_id) === primary.apiId) || {};
  const pageEvent = eventPage(primaryEvent)
    ? primaryEvent
    : latestPageEvent(trace);
  const duration = firstNumber(
    metadata.duration_ms,
    result.duration_ms,
    primaryEvent.duration_ms,
    traceDuration(trace),
  );

  addRow(rows, "Operation", primary.apiId);
  addRow(rows, "Target", eventTarget(primaryEvent));
  addRow(rows, "Page", eventPage(pageEvent));
  addRow(
    rows,
    "Context",
    firstString(
      metadata.selected_context,
      metadata.context,
      result.selected_context,
      result.context,
      primaryEvent.selected_context,
      primaryEvent.context,
      params.context,
    ),
  );
  addRow(
    rows,
    "Backend",
    firstString(
      metadata.backend_id,
      metadata.backend,
      result.backend_id,
      result.backend,
      primaryEvent.backend_id,
      primaryEvent.backend,
    ),
  );
  addRow(rows, "Status", primary.status || content.status);
  if (duration !== undefined) addRow(rows, "Duration", `${duration} ms`);
  addRow(rows, "Error", primary.error || eventError(primaryEvent));
  addRow(
    rows,
    "Approval",
    firstString(
      metadata.approval_state,
      result.approval_state,
      primaryEvent.approval_state,
      params.approval_state,
    ),
  );

  return rows;
}

export function buildBrowserOperation(
  content: ToolCallContent,
): BrowserOperation {
  const metadata = parseRecord(content.metadata);
  const result = parseRecord(content.result);
  const params = asRecord(content.params);
  const trace = pickTraceSource(metadata, result, params);
  const steps = trace.filter(isVisibleEvent).map(toStep);
  const primary = selectPrimaryStep(steps);
  const title = primary?.apiId || "Browser";
  const backendLabel = firstString(
    metadata.backend_id,
    metadata.backend,
    result.backend_id,
    result.backend,
  );

  return {
    title,
    backendLabel,
    stepCount: steps.length,
    steps,
    summaryRows: buildSummaryRows(
      content,
      metadata,
      result,
      params,
      trace,
      primary,
    ),
    paramsRows: paramsRows(params),
    rawTrace: trace.length ? JSON.stringify(sanitizeValue(trace), null, 2) : "",
    fallbackDetail: trace.length ? "" : resultText(content.result),
  };
}

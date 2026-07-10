import type { ToolCallContent } from "./types";

type BrowserRecord = Record<string, unknown>;

export const HIDDEN_BROWSER_VALUE = "[hidden]";
export const MASKED_BROWSER_VALUE = "[masked]";

const MAX_BROWSER_DISPLAY_STRING_LENGTH = 160;

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
  traceIndex: number;
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

interface BrowserPrimarySelection {
  step: BrowserOperationStep;
  event: BrowserRecord;
  traceIndex: number;
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
  "request_scope_key",
  "tool_call_id",
  "session_id",
  "freshness_marker",
  "trace_event_id",
  "backend_id",
  "selected_context",
  "requested_context",
  "event_id",
]);

const MUTATING_ACTION_API_IDS = new Set([
  "tab.actions.click",
  "tab.actions.fill",
  "tab.actions.press_key",
  "tab.actions.select_option",
  "tab.actions.upload_file",
  "tab.actions.download_file",
  "tab.actions.handle_dialog",
  "tab.actions.scroll",
  "tab.actions.hover",
]);

const MUTATING_ACTIONS = new Set([
  "click",
  "fill",
  "press_key",
  "select_option",
  "upload_file",
  "download_file",
  "handle_dialog",
  "scroll",
  "hover",
]);

const NAVIGATION_API_IDS = new Set([
  "browser.tabs.open",
  "tab.actions.navigate",
  "tab.actions.back",
  "tab.actions.forward",
  "tab.actions.reload",
]);

const NAVIGATION_ACTIONS = new Set([
  "open",
  "navigate",
  "back",
  "forward",
  "reload",
]);

const OBSERVE_API_IDS = new Set([
  "tab.snapshot",
  "tab.screenshot",
  "tab.extract",
  "tab.page_info",
  "tab.wait_for",
]);

const OBSERVE_ACTIONS = new Set([
  "snapshot",
  "screenshot",
  "observe",
  "extract",
  "page_info",
  "wait_for",
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

function truncateDisplayString(value: string): string {
  if (value.length <= MAX_BROWSER_DISPLAY_STRING_LENGTH) return value;
  return `${value.slice(0, MAX_BROWSER_DISPLAY_STRING_LENGTH - 3)}...`;
}

function eventMetadata(event: BrowserRecord): BrowserRecord {
  return asRecord(event.metadata);
}

function targetRecordDisplay(value: BrowserRecord): string {
  const ref = stringValue(value.ref);
  if (ref) return `ref=${ref}`;

  const role = stringValue(value.role);
  const name = stringValue(value.name);
  if (role && name) return `${role} "${name}"`;

  const text = stringValue(value.text);
  if (text) return `"${text}"`;

  const x = numberValue(value.x);
  const y = numberValue(value.y);
  if (x !== undefined && y !== undefined) return `(${x}, ${y})`;

  return displayValue(sanitizeValue(value));
}

function targetValueDisplay(value: unknown): string {
  const display = stringValue(value);
  if (display) return display;

  const record = asRecord(value);
  return Object.keys(record).length ? targetRecordDisplay(record) : "";
}

function eventTarget(event: BrowserRecord): string {
  const metadata = eventMetadata(event);
  const kwargs = asRecord(metadata.kwargs);
  const x = numberValue(kwargs.x);
  const y = numberValue(kwargs.y);
  return (
    targetValueDisplay(kwargs.target) ||
    targetValueDisplay(metadata.target) ||
    (stringValue(kwargs.ref) ? `ref=${stringValue(kwargs.ref)}` : "") ||
    (stringValue(metadata.ref) ? `ref=${stringValue(metadata.ref)}` : "") ||
    stringValue(metadata.target_text) ||
    stringValue(metadata.accessible_name) ||
    stringValue(kwargs.text) ||
    stringValue(metadata.text) ||
    stringValue(event.selector) ||
    stringValue(metadata.selector) ||
    compactUrl(stringValue(kwargs.url)) ||
    (x !== undefined && y !== undefined ? `(${x}, ${y})` : "")
  );
}

function eventPage(event: BrowserRecord): string {
  const metadata = eventMetadata(event);
  return (
    compactUrl(stringValue(event.url)) ||
    compactUrl(stringValue(metadata.url)) ||
    stringValue(event.domain) ||
    stringValue(metadata.domain) ||
    stringValue(event.title) ||
    stringValue(metadata.title)
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
    stringValue(event.error_code) ||
    stringValue(eventMetadata(event).error_code) ||
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

function toStep(
  event: BrowserRecord,
  traceIndex: number,
): BrowserOperationStep {
  return {
    apiId: stringValue(event.api_id),
    action: stringValue(event.action) || stringValue(event.phase) || "browser",
    status: stringValue(event.status) || "done",
    detail: eventDetail(event),
    phase: stringValue(event.phase),
    traceIndex,
    error: eventError(event) || undefined,
  };
}

function isActionStep(step: BrowserOperationStep): boolean {
  return (
    MUTATING_ACTION_API_IDS.has(step.apiId) || MUTATING_ACTIONS.has(step.action)
  );
}

function isNavigationStep(step: BrowserOperationStep): boolean {
  return (
    step.phase === "navigation" ||
    NAVIGATION_API_IDS.has(step.apiId) ||
    NAVIGATION_ACTIONS.has(step.action)
  );
}

function isObserveStep(step: BrowserOperationStep): boolean {
  return (
    step.phase === "observe" ||
    OBSERVE_API_IDS.has(step.apiId) ||
    OBSERVE_ACTIONS.has(step.action)
  );
}

function selectPrimaryStep(
  candidates: BrowserPrimarySelection[],
): BrowserPrimarySelection | undefined {
  return (
    candidates.find(
      (candidate) =>
        candidate.step.error || isErrorStatus(candidate.step.status),
    ) ||
    candidates.find((candidate) => isActionStep(candidate.step)) ||
    candidates.find((candidate) => isNavigationStep(candidate.step)) ||
    candidates.find((candidate) => isObserveStep(candidate.step)) ||
    candidates[0]
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
  const display = truncateDisplayString(stringValue(value));
  return display ? { label, value: display } : null;
}

function addRow(rows: BrowserOperationRow[], label: string, value: unknown) {
  const next = row(label, value);
  if (next) rows.push(next);
}

function displayValue(value: unknown): string {
  if (typeof value === "string") return truncateDisplayString(value);
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (value === null || value === undefined) return "";
  try {
    return truncateDisplayString(JSON.stringify(value));
  } catch {
    return truncateDisplayString(String(value));
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

  if (typeof value === "string") {
    return truncateDisplayString(
      key.toLowerCase() === "url" ? compactUrl(value) : value,
    );
  }

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

function eventParamsRows(
  event: BrowserRecord | undefined,
  fallbackParams: BrowserRecord,
): BrowserOperationRow[] {
  if (!event) return paramsRows(fallbackParams);

  const metadata = eventMetadata(event);
  const kwargs = asRecord(metadata.kwargs);
  const source: BrowserRecord = { ...kwargs };
  const metadataTarget = asRecord(metadata.target);

  if (source.target === undefined && Object.keys(metadataTarget).length > 0) {
    source.target = metadata.target;
  }

  for (const key of ["selector", "url", "domain", "action"]) {
    if (source[key] === undefined && event[key] !== undefined) {
      source[key] = event[key];
    }
  }

  return paramsRows(source);
}

function firstString(...values: unknown[]): string {
  for (const value of values) {
    const display = stringValue(value);
    if (display) return display;
  }
  return "";
}

function firstMeaningfulApproval(...values: unknown[]): string {
  for (const value of values) {
    const display = stringValue(value);
    const normalized = display.toLowerCase().replace(/_/g, " ").trim();
    if (display && normalized !== "not required") return display;
  }
  return "";
}

function contextLabel(
  primaryEvent: BrowserRecord,
  metadata: BrowserRecord,
  result: BrowserRecord,
  params: BrowserRecord,
): string {
  const requested = firstString(
    primaryEvent.requested_context,
    metadata.context,
    result.context,
    params.context,
    primaryEvent.context,
  );
  const selected = firstString(
    primaryEvent.selected_context,
    metadata.selected_context,
    result.selected_context,
  );

  if (requested && selected && requested !== selected) {
    return `${requested} -> ${selected}`;
  }

  return selected || requested;
}

function eventBackendLabel(event: BrowserRecord | undefined): string {
  if (!event) return "";
  return firstString(event.backend_id, event.backend);
}

function traceBackendLabel(trace: BrowserRecord[]): string {
  for (const event of trace) {
    const backend = eventBackendLabel(event);
    if (backend) return backend;
  }
  return "";
}

function backendLabelFor(
  primary: BrowserPrimarySelection | undefined,
  trace: BrowserRecord[],
  metadata: BrowserRecord,
  result: BrowserRecord,
): string {
  return firstString(
    metadata.backend_id,
    metadata.backend,
    result.backend_id,
    result.backend,
    eventBackendLabel(primary?.event),
    traceBackendLabel(trace),
  );
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
  return [...trace].reverse().find((event) => eventPage(event)) || {};
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
  primary: BrowserPrimarySelection | undefined,
): BrowserOperationRow[] {
  const rows: BrowserOperationRow[] = [];
  if (!primary) return rows;

  const primaryEvent = primary.event;
  const primaryStep = primary.step;
  const pageEvent = eventPage(primaryEvent)
    ? primaryEvent
    : latestPageEvent(trace);
  const duration = firstNumber(
    metadata.duration_ms,
    result.duration_ms,
    primaryEvent.duration_ms,
    traceDuration(trace),
  );
  const approval = firstMeaningfulApproval(
    metadata.approval_state,
    result.approval_state,
    primaryEvent.approval_state,
    params.approval_state,
  );

  addRow(rows, "Operation", primaryStep.apiId);
  addRow(rows, "Target", eventTarget(primaryEvent));
  addRow(rows, "Page", eventPage(pageEvent));
  addRow(rows, "Context", contextLabel(primaryEvent, metadata, result, params));
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
  addRow(rows, "Status", primaryStep.status || content.status);
  if (duration !== undefined) addRow(rows, "Duration", `${duration} ms`);
  addRow(rows, "Error", primaryStep.error || eventError(primaryEvent));
  addRow(rows, "Approval", approval);

  return rows;
}

export function buildBrowserOperation(
  content: ToolCallContent,
): BrowserOperation {
  const metadata = parseRecord(content.metadata);
  const result = parseRecord(content.result);
  const params = asRecord(content.params);
  const trace = pickTraceSource(metadata, result, params);
  const primaryCandidates = trace
    .map((event, traceIndex) => ({ event, traceIndex }))
    .filter(({ event }) => isVisibleEvent(event))
    .map(({ event, traceIndex }) => ({
      step: toStep(event, traceIndex),
      event,
      traceIndex,
    }));
  const steps = primaryCandidates.map((candidate) => candidate.step);
  const primary = selectPrimaryStep(primaryCandidates);
  const title = primary?.step.apiId || "Browser";
  const backendLabel = backendLabelFor(primary, trace, metadata, result);

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
    paramsRows: eventParamsRows(primary?.event, params),
    rawTrace: trace.length ? JSON.stringify(sanitizeValue(trace), null, 2) : "",
    fallbackDetail: trace.length ? "" : resultText(content.result),
  };
}

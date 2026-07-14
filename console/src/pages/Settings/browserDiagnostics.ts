import type { TFunction } from "i18next";
import type {
  BrowserBackendDiagnostic,
  BrowserDiagnostics,
} from "@/api/modules/plugin";

export function browserDiagnosticsRows(
  diagnostics?: BrowserDiagnostics | null,
): BrowserBackendDiagnostic[] {
  return (diagnostics?.backends ?? []).filter(
    (backend) => backend.code || backend.status !== "available",
  );
}

export function browserDiagnosticHint(
  t: TFunction,
  backend: BrowserBackendDiagnostic,
): string {
  const hintKey = backend.hint_key || backend.code;
  const fallback =
    backend.message_fallback ||
    backend.message ||
    backend.reason ||
    backend.code ||
    backend.backend_id;

  if (!hintKey) {
    return fallback;
  }

  return t(`chrome.diagnostics.${hintKey}`, fallback);
}

export function browserDiagnosticStatusLabel(
  t: TFunction,
  backend: BrowserBackendDiagnostic,
): string {
  return t(
    `chrome.diagnostics.status.${backend.status}`,
    backend.status,
  );
}

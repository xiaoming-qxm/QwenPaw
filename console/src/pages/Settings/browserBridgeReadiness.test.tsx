import { describe, expect, it, vi } from "vitest";
import type { ComponentProps } from "react";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import enMessages from "@/locales/en.json";
import zhMessages from "@/locales/zh.json";
import {
  BrowserBridgeReadiness,
  type BrowserBridgeReadinessStatus,
} from "./browserBridgeReadiness";

function status(
  overrides: Partial<BrowserBridgeReadinessStatus> = {},
): BrowserBridgeReadinessStatus {
  return {
    installed: true,
    connected: false,
    install_mode: "unpacked",
    readiness_state: "blocked",
    repair_action: "reload_extension",
    native_host_status: {
      status: "configured",
      message: "Native host manifest is configured.",
      repair_action: "none",
    },
    selected_backend_id: "user.chrome_extension",
    extension_version: "0.1.0",
    version: "0.1.0",
    connected_since: null,
    build_fingerprint: {
      git_commit: "abc123",
      repo_dirty: false,
      frontend_fingerprint: "main.js",
    },
    bridge_lifecycle: {
      connected: false,
      connected_since: null,
      last_connected_at: null,
      last_disconnected_at: null,
      last_disconnect_reason: "",
      reconnect_count: 0,
    },
    trace_summary: {
      event_count: 7,
      session_count: 2,
      latest_event: {
        event_id: "trace-1",
        session_id: "session-1",
        phase: "action",
        action: "click",
        status: "ok",
      },
    },
    sdk_diagnostics: {
      requested_context: "user",
      selected_backend_id: null,
      backends: [
        {
          backend_id: "user.chrome_extension",
          browser_context: "user",
          available: false,
          status: "unavailable",
          code: "browser_bridge_disconnected",
          message: "Browser bridge is not connected.",
          hint_key: "browser_bridge_disconnected",
          message_fallback:
            "Reload the extension or reopen the target browser tab.",
          features: ["snapshot", "click"],
          checks: [],
        },
      ],
    },
    ...overrides,
  };
}

function renderReadiness(
  nextStatus: BrowserBridgeReadinessStatus | null,
  overrides: Partial<ComponentProps<typeof BrowserBridgeReadiness>> = {},
) {
  const onRefresh = vi.fn();
  const onRunSelfTest = vi.fn();
  const onOpenChrome = vi.fn();
  const onCopyDiagnostics = vi.fn();
  renderWithProviders(
    <BrowserBridgeReadiness
      loading={false}
      onCopyDiagnostics={onCopyDiagnostics}
      onOpenChrome={onOpenChrome}
      onRefresh={onRefresh}
      onRunSelfTest={onRunSelfTest}
      status={nextStatus}
      {...overrides}
    />,
  );
  return {
    onRefresh,
    onRunSelfTest,
    onOpenChrome,
    onCopyDiagnostics,
  };
}

describe("BrowserBridgeReadiness", () => {
  it("ships English and Chinese product explanation copy", () => {
    const keys = [
      "connected",
      "disconnected",
      "setupRequired",
      "staleBuild",
      "approvalRequired",
      "approvalDenied",
      "loginRequired",
      "riskControl",
      "noProgress",
      "cleanupComplete",
    ];

    for (const messages of [enMessages, zhMessages]) {
      const explain = messages.browserBridge.explain as Record<string, string>;
      for (const key of keys) {
        expect(explain[key]).toEqual(expect.any(String));
        expect(explain[key].length).toBeGreaterThan(0);
      }
    }
  });

  it("renders connected version and trace summary states", () => {
    renderReadiness(
      status({
        connected: true,
        bridge_lifecycle: {
          connected: true,
          connected_since: "2026-07-05T01:00:00+00:00",
          last_connected_at: "2026-07-05T01:00:00+00:00",
          last_disconnected_at: null,
          last_disconnect_reason: "",
          reconnect_count: 1,
        },
      }),
    );

    expect(screen.getByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("Extension version")).toBeInTheDocument();
    expect(screen.getByText("0.1.0")).toBeInTheDocument();
    expect(screen.getByText("Selected backend")).toBeInTheDocument();
    expect(screen.getAllByText("user.chrome_extension").length).toBeGreaterThan(
      0,
    );
    expect(screen.getByText("Native host")).toBeInTheDocument();
    expect(screen.getByText("configured")).toBeInTheDocument();
    expect(screen.getByText("Backend commit")).toBeInTheDocument();
    expect(screen.getByText("abc123")).toBeInTheDocument();
    expect(screen.getByText("Trace events")).toBeInTheDocument();
    expect(screen.getByText("7 across 2 sessions")).toBeInTheDocument();
  });

  it("renders waiting and disconnected repair states", () => {
    const { rerender } = renderWithProviders(
      <BrowserBridgeReadiness
        loading={false}
        onCopyDiagnostics={vi.fn()}
        onOpenChrome={vi.fn()}
        onRefresh={vi.fn()}
        onRunSelfTest={vi.fn()}
        status={status()}
      />,
    );

    expect(screen.getByText("Waiting for Chrome")).toBeInTheDocument();
    expect(screen.getByText("Reload extension")).toBeInTheDocument();
    expect(screen.getByText("browser_bridge_disconnected")).toBeInTheDocument();

    rerender(
      <BrowserBridgeReadiness
        loading={false}
        onCopyDiagnostics={vi.fn()}
        onOpenChrome={vi.fn()}
        onRefresh={vi.fn()}
        onRunSelfTest={vi.fn()}
        status={status({ installed: false, install_mode: null })}
      />,
    );

    expect(screen.getByText("Setup required")).toBeInTheDocument();
  });

  it("renders self-test failure and stale build states", () => {
    renderReadiness(
      status({
        build_fingerprint: {
          git_commit: "abc123",
          repo_dirty: true,
          frontend_fingerprint: "main.js",
        },
        last_self_test: {
          status: "failed",
          checked_at: "2026-07-05T01:00:00+00:00",
          duration_ms: 12,
          checks: [
            {
              name: "bridge",
              passed: false,
              code: "bridge_disconnected",
              message: "Native Messaging bridge is not connected.",
              repair_action: "reload_extension",
            },
          ],
        },
      }),
    );

    expect(screen.getByText("Last self-test")).toBeInTheDocument();
    expect(screen.getByText("Self-test failed")).toBeInTheDocument();
    expect(screen.getByText("bridge_disconnected")).toBeInTheDocument();
    expect(screen.getAllByText("Reload extension").length).toBeGreaterThan(0);
    expect(screen.getByText("Build has local changes")).toBeInTheDocument();
  });

  it("exposes refresh, self-test, chrome, and copy actions", async () => {
    const callbacks = renderReadiness(status());

    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await userEvent.click(
      screen.getByRole("button", { name: "Run Self-Test" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Open Chrome" }));
    await userEvent.click(
      screen.getByRole("button", { name: "Copy Diagnostics" }),
    );

    expect(callbacks.onRefresh).toHaveBeenCalledTimes(1);
    expect(callbacks.onRunSelfTest).toHaveBeenCalledTimes(1);
    expect(callbacks.onOpenChrome).toHaveBeenCalledTimes(1);
    expect(callbacks.onCopyDiagnostics).toHaveBeenCalledTimes(1);
  });
});

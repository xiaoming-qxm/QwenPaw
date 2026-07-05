import { describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import enMessages from "@/locales/en.json";
import zhMessages from "@/locales/zh.json";
import BrowserEvidenceCard from "./cards/BrowserEvidenceCard";
import { BUILTIN_CARD_REGISTRY } from "./cards";
import type { ToolCallContent } from "./shared/types";

function browserContent(): ToolCallContent {
  return {
    type: "tool_call",
    id: "tool-browser-1",
    name: "browser",
    status: "done",
    params: {
      code: "await browser.open('https://example.com')",
    },
    result: {
      context: "auto",
      selected_context: "isolated",
      backend_id: "isolated.playwright",
      approval_state: "approved",
      error_code: "browser_progress_stalled",
      error_outcome: "blocked",
      recovery_hint: "Observe the page again and retry with a stable selector.",
      progress_decision: {
        status: "no_progress",
        reason: "The DOM did not change after click.",
      },
      artifacts: [
        {
          kind: "screenshot",
          url: "/artifacts/browser/screen.png",
          name: "screen.png",
          media_type: "image/png",
        },
      ],
      browser_trace: [
        {
          phase: "context",
          status: "ok",
          requested_context: "auto",
          selected_context: "isolated",
          backend_id: "isolated.playwright",
          duration_ms: 120,
        },
        {
          phase: "approval",
          action: "click",
          status: "approved",
        },
        {
          phase: "action",
          action: "click",
          status: "blocked",
          error_code: "browser_progress_stalled",
        },
      ],
    },
  };
}

describe("BrowserEvidenceCard", () => {
  it("ships English and Chinese browser evidence copy", () => {
    const keys = [
      "title",
      "route",
      "backend",
      "approval",
      "approvalPrefix",
      "blocker",
      "duration",
      "artifacts",
      "copyDiagnostics",
      "noProgress",
      "cleanupComplete",
    ];

    for (const messages of [enMessages, zhMessages]) {
      const copy = messages.tool.browserEvidence as Record<string, string>;
      for (const key of keys) {
        expect(copy[key]).toEqual(expect.any(String));
        expect(copy[key].length).toBeGreaterThan(0);
      }
    }
  });

  it("renders browser route, blocker, trace summary, and artifacts", () => {
    renderWithProviders(<BrowserEvidenceCard content={browserContent()} />);

    expect(screen.getByText("Browser evidence")).toBeInTheDocument();
    expect(screen.getByText("auto -> isolated")).toBeInTheDocument();
    expect(screen.getByText("isolated.playwright")).toBeInTheDocument();
    expect(screen.getByText("Approval: approved")).toBeInTheDocument();
    expect(
      screen.getAllByText("Blocked: browser_progress_stalled").length,
    ).toBeGreaterThan(0);
    expect(
      screen.getByText(
        "Observe the page again and retry with a stable selector.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("3 events")).toBeInTheDocument();
    expect(screen.getByText("120 ms")).toBeInTheDocument();
    expect(screen.getByText("screen.png")).toBeInTheDocument();
    expect(screen.queryByText(/"browser_trace"/)).not.toBeInTheDocument();
  });

  it("registers browser tool calls and copies diagnostics explicitly", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    expect(BUILTIN_CARD_REGISTRY.browser).toBe(BrowserEvidenceCard);
    renderWithProviders(<BrowserEvidenceCard content={browserContent()} />);

    await userEvent.click(
      screen.getByRole("button", { name: "Copy diagnostics" }),
    );

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledTimes(1);
    });
    expect(String(writeText.mock.calls[0][0])).toContain("browser_trace");
  });
});

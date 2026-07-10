import { describe, expect, it } from "vitest";
import {
  HIDDEN_BROWSER_VALUE,
  MASKED_BROWSER_VALUE,
  buildBrowserOperation,
} from "./browserOperation";
import type { ToolCallContent } from "./types";

function browserContent(
  overrides: Partial<ToolCallContent> = {},
): ToolCallContent {
  return {
    type: "tool_call",
    id: "browser-call",
    name: "browser",
    status: "done",
    params: {},
    ...overrides,
  };
}

function rowValue(
  rows: Array<{ label: string; value: string }>,
  label: string,
): string | undefined {
  return rows.find((row) => row.label === label)?.value;
}

describe("buildBrowserOperation", () => {
  it("prefers metadata browser_trace over result and params trace", () => {
    const operation = buildBrowserOperation(
      browserContent({
        metadata: {
          browser_trace: [
            {
              phase: "connect",
              api_id: "browser.connect",
              status: "ok",
            },
            {
              phase: "action",
              api_id: "tab.actions.click",
              action: "click",
              status: "ok",
              metadata: { target_text: "Details" },
            },
          ],
        },
        result: {
          output: "browser done",
          browser_trace: [
            {
              phase: "action",
              api_id: "browser.done",
              action: "done",
              status: "ok",
            },
          ],
        },
        params: {
          browser_trace: [
            {
              phase: "navigation",
              api_id: "tab.navigate",
              status: "ok",
              url: "https://params.example/",
            },
          ],
        },
      }),
    );

    expect(operation.title).toBe("tab.actions.click");
    expect(operation.steps.map((step) => step.apiId)).toEqual([
      "tab.actions.click",
    ]);
    expect(operation.steps[0].detail).toBe("Details");
    expect(operation.rawTrace).toContain("tab.actions.click");
    expect(operation.rawTrace).not.toContain("browser.done");
    expect(operation.rawTrace).not.toContain("params.example");
  });

  it("selects an error operation before action, navigation, observe, or fallback steps", () => {
    const operation = buildBrowserOperation(
      browserContent({
        metadata: {
          browser_trace: [
            {
              phase: "navigation",
              api_id: "browser.tabs.open",
              action: "open",
              status: "ok",
              url: "https://example.com/products",
            },
            {
              phase: "action",
              api_id: "tab.actions.click",
              action: "click",
              status: "ok",
              metadata: { target_text: "Details" },
            },
            {
              phase: "observe",
              api_id: "tab.snapshot",
              action: "snapshot",
              status: "error",
              error: "Snapshot timed out",
            },
          ],
        },
      }),
    );

    expect(operation.title).toBe("tab.snapshot");
    expect(rowValue(operation.summaryRows, "Error")).toBe("Snapshot timed out");
    expect(operation.steps.map((step) => step.apiId)).toEqual([
      "browser.tabs.open",
      "tab.actions.click",
      "tab.snapshot",
    ]);
  });

  it("keeps visible steps in execution order while hiding lifecycle events", () => {
    const operation = buildBrowserOperation(
      browserContent({
        metadata: {
          browser_trace: [
            { phase: "connect", api_id: "browser.connect", status: "ok" },
            {
              phase: "navigation",
              api_id: "browser.tabs.open",
              action: "open",
              status: "ok",
              url: "https://example.com/products",
            },
            {
              phase: "action",
              api_id: "tab.actions.click",
              action: "click",
              status: "ok",
              metadata: { target_text: "Details" },
            },
            {
              phase: "observe",
              api_id: "tab.snapshot",
              action: "snapshot",
              status: "ok",
              url: "https://example.com/products/details",
            },
            {
              phase: "diagnostic",
              api_id: "browser.diagnostics",
              status: "ok",
            },
          ],
        },
      }),
    );

    expect(operation.steps.map((step) => step.apiId)).toEqual([
      "browser.tabs.open",
      "tab.actions.click",
      "tab.snapshot",
    ]);
    expect(operation.stepCount).toBe(3);
    expect(operation.rawTrace).toContain("browser.connect");
    expect(operation.rawTrace).toContain("browser.diagnostics");
  });

  it("builds summary and params rows from operation evidence", () => {
    const operation = buildBrowserOperation(
      browserContent({
        params: {
          action: "click",
          selector: "button.details",
          text: "Details",
          browser_trace: [{ api_id: "ignored" }],
        },
        metadata: {
          selected_context: "active-tab",
          backend_id: "browser-sdk",
          duration_ms: 42,
          approval_state: "approved",
          browser_trace: [
            {
              phase: "action",
              api_id: "tab.actions.click",
              action: "click",
              status: "ok",
              url: "https://example.com/products",
              title: "Products",
              metadata: { target_text: "Details" },
            },
          ],
        },
      }),
    );

    expect(rowValue(operation.summaryRows, "Operation")).toBe(
      "tab.actions.click",
    );
    expect(rowValue(operation.summaryRows, "Target")).toBe("Details");
    expect(rowValue(operation.summaryRows, "Page")).toBe(
      "example.com/products",
    );
    expect(rowValue(operation.summaryRows, "Context")).toBe("active-tab");
    expect(rowValue(operation.summaryRows, "Backend")).toBe("browser-sdk");
    expect(rowValue(operation.summaryRows, "Status")).toBe("ok");
    expect(rowValue(operation.summaryRows, "Duration")).toBe("42 ms");
    expect(rowValue(operation.summaryRows, "Approval")).toBe("approved");

    expect(rowValue(operation.paramsRows, "action")).toBe("click");
    expect(rowValue(operation.paramsRows, "selector")).toBe("button.details");
    expect(rowValue(operation.paramsRows, "text")).toBe("Details");
    expect(rowValue(operation.paramsRows, "browser_trace")).toBeUndefined();
  });

  it("sanitizes params rows and raw trace before display", () => {
    const operation = buildBrowserOperation(
      browserContent({
        params: {
          action: "evaluate",
          code: "return document.cookie",
          authToken: "secret-token",
          nested: {
            script: "window.localStorage.token",
            cookie: "session=abc",
          },
        },
        metadata: {
          browser_trace: [
            {
              phase: "action",
              api_id: "tab.actions.evaluate",
              action: "evaluate",
              status: "ok",
              metadata: {
                code: "return document.cookie",
                token: "secret-token",
                authorization: "Bearer secret-token",
                nested: { eval: "alert(document.cookie)" },
              },
            },
          ],
        },
      }),
    );

    expect(rowValue(operation.paramsRows, "code")).toBe(HIDDEN_BROWSER_VALUE);
    expect(rowValue(operation.paramsRows, "authToken")).toBe(
      MASKED_BROWSER_VALUE,
    );
    expect(rowValue(operation.paramsRows, "nested")).toContain(
      HIDDEN_BROWSER_VALUE,
    );
    expect(rowValue(operation.paramsRows, "nested")).toContain(
      MASKED_BROWSER_VALUE,
    );
    expect(operation.rawTrace).toContain(HIDDEN_BROWSER_VALUE);
    expect(operation.rawTrace).toContain(MASKED_BROWSER_VALUE);
    expect(operation.rawTrace).not.toContain("return document.cookie");
    expect(operation.rawTrace).not.toContain("secret-token");
    expect(operation.rawTrace).not.toContain("Bearer");
    expect(operation.rawTrace).not.toContain("alert(document.cookie)");
  });

  it("uses a quiet Browser fallback when no trace exists", () => {
    const operation = buildBrowserOperation(
      browserContent({
        params: {
          action: "click",
          selector: "button.details",
        },
        result: "browser done",
      }),
    );

    expect(operation.title).toBe("Browser");
    expect(operation.stepCount).toBe(0);
    expect(operation.steps).toEqual([]);
    expect(operation.fallbackDetail).toBe("browser done");
    expect(operation.fallbackDetail).not.toContain("button.details");
    expect(operation.rawTrace).toBe("");
  });
});

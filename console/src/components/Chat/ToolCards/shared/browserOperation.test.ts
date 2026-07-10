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

  it("uses the exact failed duplicate api_id event as primary evidence", () => {
    const operation = buildBrowserOperation(
      browserContent({
        metadata: {
          browser_trace: [
            {
              phase: "action",
              api_id: "tab.actions.click",
              action: "click",
              status: "ok",
              metadata: {
                kwargs: {
                  target: { ref: "first" },
                },
              },
            },
            {
              phase: "action",
              api_id: "tab.actions.click",
              action: "click",
              status: "error",
              error_code: "browser_click_failed",
              url: "https://example.com/second",
              metadata: {
                kwargs: {
                  target: { ref: "second" },
                },
              },
            },
          ],
        },
      }),
    );

    expect(operation.title).toBe("tab.actions.click");
    expect(rowValue(operation.summaryRows, "Target")).toBe("ref=second");
    expect(rowValue(operation.summaryRows, "Page")).toBe("example.com/second");
    expect(rowValue(operation.summaryRows, "Error")).toBe(
      "browser_click_failed",
    );
    expect(rowValue(operation.paramsRows, "target")).toContain("second");
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
              metadata: {
                target_text: "Details",
                kwargs: {
                  action: "click",
                  selector: "button.details",
                  text: "Details",
                },
              },
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

  it("reads summary and params from sdk action kwargs", () => {
    const operation = buildBrowserOperation(
      browserContent({
        params: {
          code: "Browser...",
          context: "auto",
        },
        metadata: {
          browser_trace: [
            {
              phase: "action",
              api_id: "tab.actions.click",
              action: "click",
              status: "ok",
              url: "https://example.com/details?token=secret",
              domain: "example.com",
              backend_id: "browser-sdk",
              selected_context: "active-tab",
              duration_ms: 55,
              approval_state: "not_required",
              metadata: {
                kwargs: {
                  target: { ref: "r1_e3", role: "button", name: "Details" },
                  text: "Details",
                  url: "https://example.com/details?token=secret",
                  allow_new_context: true,
                },
              },
            },
          ],
        },
      }),
    );

    expect(rowValue(operation.summaryRows, "Target")).toBe("ref=r1_e3");
    expect(rowValue(operation.summaryRows, "Page")).toBe("example.com/details");
    expect(rowValue(operation.summaryRows, "Approval")).toBeUndefined();
    expect(rowValue(operation.paramsRows, "target")).toContain("r1_e3");
    expect(rowValue(operation.paramsRows, "text")).toBe("Details");
    expect(rowValue(operation.paramsRows, "url")).toContain(
      "example.com/details",
    );
    expect(rowValue(operation.paramsRows, "allow_new_context")).toBe("true");
    expect(rowValue(operation.paramsRows, "code")).toBeUndefined();
    expect(rowValue(operation.paramsRows, "context")).toBeUndefined();
  });

  it("extracts sdk error page and approval fields", () => {
    const operation = buildBrowserOperation(
      browserContent({
        metadata: {
          browser_trace: [
            {
              phase: "observe",
              api_id: "tab.snapshot",
              action: "snapshot",
              status: "error",
              error_code: "browser_stale_lease",
              approval_state: "approved",
              metadata: {
                url: "https://example.org/fallback",
                title: "Fallback",
              },
            },
          ],
        },
      }),
    );

    expect(rowValue(operation.summaryRows, "Error")).toBe(
      "browser_stale_lease",
    );
    expect(rowValue(operation.summaryRows, "Page")).toBe(
      "example.org/fallback",
    );
    expect(rowValue(operation.summaryRows, "Approval")).toBe("approved");
  });

  it("truncates long non-sensitive strings and preserves sensitive markers", () => {
    const longSelector = "s".repeat(200);
    const longText = "T".repeat(200);
    const operation = buildBrowserOperation(
      browserContent({
        metadata: {
          browser_trace: [
            {
              phase: "action",
              api_id: "tab.actions.fill",
              action: "fill",
              status: "ok",
              metadata: {
                kwargs: {
                  selector: longSelector,
                  text: longText,
                  token: "super-secret-token",
                  code: "return document.cookie",
                  nested: {
                    script: "window.localStorage.token",
                  },
                },
              },
            },
          ],
        },
      }),
    );

    const selectorValue = rowValue(operation.paramsRows, "selector");
    const textValue = rowValue(operation.paramsRows, "text");
    expect(selectorValue).toBeDefined();
    expect(textValue).toBeDefined();
    expect(selectorValue?.length).toBeLessThanOrEqual(163);
    expect(textValue?.length).toBeLessThanOrEqual(163);
    expect(selectorValue).toContain("...");
    expect(textValue).toContain("...");
    expect(rowValue(operation.paramsRows, "token")).toBe(MASKED_BROWSER_VALUE);
    expect(rowValue(operation.paramsRows, "code")).toBe(HIDDEN_BROWSER_VALUE);
    expect(rowValue(operation.paramsRows, "nested")).toContain(
      HIDDEN_BROWSER_VALUE,
    );
    expect(operation.rawTrace).toContain("...");
    expect(operation.rawTrace).toContain(HIDDEN_BROWSER_VALUE);
    expect(operation.rawTrace).toContain(MASKED_BROWSER_VALUE);
    expect(operation.rawTrace).not.toContain(longSelector);
    expect(operation.rawTrace).not.toContain(longText);
    expect(operation.rawTrace).not.toContain("super-secret-token");
    expect(operation.rawTrace).not.toContain("return document.cookie");
    expect(operation.rawTrace).not.toContain("window.localStorage.token");
  });

  it("classifies navigation and observe read operations by design category", () => {
    const titleFor = (browser_trace: unknown[]) =>
      buildBrowserOperation(
        browserContent({
          metadata: {
            browser_trace,
          },
        }),
      ).title;

    expect(
      titleFor([
        {
          phase: "navigation",
          api_id: "tab.actions.back",
          action: "back",
          status: "ok",
        },
        {
          phase: "action",
          api_id: "tab.actions.fill",
          action: "fill",
          status: "ok",
        },
      ]),
    ).toBe("tab.actions.fill");
    expect(
      titleFor([
        {
          phase: "observe",
          api_id: "tab.wait_for",
          action: "wait_for",
          status: "ok",
        },
        {
          phase: "navigation",
          api_id: "tab.actions.forward",
          action: "forward",
          status: "ok",
        },
      ]),
    ).toBe("tab.actions.forward");
    expect(
      titleFor([
        {
          phase: "misc",
          api_id: "browser.misc",
          action: "noop",
          status: "ok",
        },
        {
          phase: "observe",
          api_id: "tab.extract",
          action: "extract",
          status: "ok",
        },
        {
          phase: "observe",
          api_id: "tab.page_info",
          action: "page_info",
          status: "ok",
        },
      ]),
    ).toBe("tab.extract");
    expect(
      titleFor([
        {
          phase: "action",
          api_id: "tab.actions.fill",
          action: "fill",
          status: "ok",
        },
        {
          phase: "navigation",
          api_id: "tab.actions.reload",
          action: "reload",
          status: "error",
          error_code: "browser_reload_failed",
        },
      ]),
    ).toBe("tab.actions.reload");
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
                kwargs: {
                  code: "return document.cookie",
                  authToken: "secret-token",
                  nested: {
                    script: "window.localStorage.token",
                    cookie: "session=abc",
                  },
                },
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

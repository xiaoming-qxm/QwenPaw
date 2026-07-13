import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import BrowserCompactCard from "./cards/BrowserCompactCard";
import { BUILTIN_CARD_REGISTRY } from "./cards";
import type { ToolCallContent } from "./shared/types";

function browserContent(): ToolCallContent {
  return {
    type: "tool_call",
    id: "tool-browser-1",
    name: "browser",
    status: "done",
    params: {
      action: "batch",
      selector: "button.details",
      text: "Details",
      code: "return document.cookie",
      authToken: "secret-token",
    },
    metadata: {
      selected_context: "active-tab",
      backend_id: "browser-sdk",
      duration_ms: 42,
      approval_state: "approved",
      browser_trace: [
        {
          phase: "connect",
          api_id: "browser.connect",
          action: "connect",
          status: "ok",
        },
        {
          phase: "navigation",
          api_id: "browser.tabs.open",
          action: "open",
          status: "ok",
          url: "https://example.com/products",
          title: "Products",
        },
        {
          phase: "action",
          api_id: "tab.actions.click",
          action: "click",
          status: "ok",
          metadata: {
            target_text: "Details",
            kwargs: {
              selector: "button.details",
              text: "Details",
              code: "return document.cookie",
              authToken: "secret-token",
            },
            code: "return document.cookie",
            token: "secret-token",
          },
        },
        {
          phase: "observe",
          api_id: "tab.snapshot",
          action: "snapshot",
          status: "ok",
          url: "https://example.com/products/details",
          title: "Product details",
        },
        {
          phase: "diagnostic",
          api_id: "browser.diagnostics",
          action: "diagnostics",
          status: "ok",
        },
        {
          phase: "action",
          action: "cleanup",
          status: "ok",
          metadata: {
            target_text: "Internal cleanup",
          },
        },
      ],
    },
    result: {
      ok: true,
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
  };
}

function lifecycleOnlyBrowserContent(): ToolCallContent {
  return {
    type: "tool_call",
    id: "tool-browser-2",
    name: "browser",
    status: "done",
    params: {
      action: "click",
      selector: "button.details",
    },
    result: "browser done",
  };
}

describe("BrowserCompactCard", () => {
  it("registers browser calls to the compact Browser card instead of evidence UI", () => {
    expect(BUILTIN_CARD_REGISTRY.browser).toBe(BrowserCompactCard);
  });

  it("renders neutral Browser SDK operation details from metadata trace", () => {
    renderWithProviders(<BrowserCompactCard content={browserContent()} />);

    expect(screen.getByTitle("tab.actions.click")).toBeInTheDocument();
    expect(screen.queryByText(/^Chrome/)).not.toBeInTheDocument();
    expect(screen.getByText("Browser")).toBeInTheDocument();
    expect(screen.getByTitle("browser-sdk")).toBeInTheDocument();
    expect(screen.getByText("3 steps")).toBeInTheDocument();

    const list = screen.getByRole("list", { name: "Browser steps" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("browser.tabs.open");
    expect(items[0]).toHaveTextContent("example.com/products");
    expect(items[1]).toHaveTextContent("tab.actions.click");
    expect(items[1]).toHaveTextContent("Details");
    expect(items[2]).toHaveTextContent("tab.snapshot");
    expect(items[2]).toHaveTextContent("example.com/products/details");

    const summary = screen.getByLabelText("Browser summary");
    expect(summary).toHaveTextContent("Operation");
    expect(summary).toHaveTextContent("tab.actions.click");
    expect(summary).toHaveTextContent("Target");
    expect(summary).toHaveTextContent("Details");
    expect(summary).toHaveTextContent("Context");
    expect(summary).toHaveTextContent("active-tab");
    expect(summary).toHaveTextContent("Backend");
    expect(summary).toHaveTextContent("browser-sdk");
    expect(summary).toHaveTextContent("Status");
    expect(summary).toHaveTextContent("ok");
    expect(summary).toHaveTextContent("Duration");
    expect(summary).toHaveTextContent("42 ms");
    expect(summary).toHaveTextContent("Approval");
    expect(summary).toHaveTextContent("approved");

    const params = screen.getByLabelText("Browser params");
    expect(params).toHaveTextContent("selector");
    expect(params).toHaveTextContent("button.details");
    expect(params).toHaveTextContent("text");
    expect(params).toHaveTextContent("Details");
    expect(params).toHaveTextContent("code");
    expect(params).toHaveTextContent("[hidden]");
    expect(params).toHaveTextContent("authToken");
    expect(params).toHaveTextContent("[masked]");

    const rawTrace = screen.getByText("Raw trace").closest("details");
    expect(rawTrace).not.toHaveAttribute("open");
    expect(rawTrace).toHaveTextContent("tab.actions.click");
    expect(rawTrace).toHaveTextContent("[hidden]");
    expect(rawTrace).toHaveTextContent("[masked]");
    expect(rawTrace).not.toHaveTextContent("return document.cookie");
    expect(rawTrace).not.toHaveTextContent("secret-token");
    expect(rawTrace).not.toHaveTextContent("browser.done");
  });

  it("renders singular step badge for one browser step", () => {
    renderWithProviders(
      <BrowserCompactCard
        content={{
          type: "tool_call",
          id: "tool-browser-single",
          name: "browser",
          status: "done",
          params: {},
          metadata: {
            browser_trace: [
              {
                phase: "observe",
                api_id: "tab.page_info",
                action: "page_info",
                status: "ok",
                url: "https://example.com/details",
              },
            ],
          },
        }}
      />,
    );

    expect(screen.getByText("1 step")).toBeInTheDocument();
    expect(screen.queryByText("1 steps")).not.toBeInTheDocument();
  });

  it("falls back to a quiet Browser title when no trace exists", () => {
    renderWithProviders(
      <BrowserCompactCard content={lifecycleOnlyBrowserContent()} />,
    );

    expect(screen.getByText("Browser")).toBeInTheDocument();
    expect(screen.queryByText("0 steps")).not.toBeInTheDocument();
    expect(screen.queryByText("Browser actions")).not.toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "Browser steps" })).toBeNull();
    expect(screen.getByText("browser done")).toBeInTheDocument();
    expect(screen.queryByText("button.details")).not.toBeInTheDocument();
  });
});

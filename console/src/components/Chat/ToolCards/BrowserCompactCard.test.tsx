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
    },
    result: {
      ok: true,
      browser_trace: [
        {
          phase: "connect",
          api_id: "browser.connect",
          action: "connect",
          status: "ok",
        },
        {
          phase: "tab_lifecycle",
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
  };
}

function lifecycleOnlyBrowserContent(): ToolCallContent {
  return {
    type: "tool_call",
    id: "tool-browser-2",
    name: "browser",
    status: "done",
    params: {},
    result: {
      ok: true,
      browser_trace: [
        {
          phase: "connect",
          api_id: "browser.connect",
          action: "connect",
          status: "ok",
        },
        {
          phase: "action",
          action: "cleanup",
          status: "ok",
        },
      ],
    },
  };
}

describe("BrowserCompactCard", () => {
  it("registers browser calls to the compact Browser card instead of evidence UI", () => {
    expect(BUILTIN_CARD_REGISTRY.browser).toBe(BrowserCompactCard);
  });

  it("renders only default-visible Browser public api_id trace events", () => {
    renderWithProviders(<BrowserCompactCard content={browserContent()} />);

    expect(screen.getByText("Chrome: browser.tabs.open")).toBeInTheDocument();
    expect(screen.getByText("3 steps")).toBeInTheDocument();
    expect(screen.queryByText("Browser evidence")).not.toBeInTheDocument();
    expect(screen.queryByText("Copy diagnostics")).not.toBeInTheDocument();
    expect(screen.queryByText("browser.connect")).not.toBeInTheDocument();
    expect(screen.queryByText("browser.diagnostics")).not.toBeInTheDocument();
    expect(screen.queryByText("Internal cleanup")).not.toBeInTheDocument();

    const list = screen.getByRole("list", { name: "Browser steps" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("browser.tabs.open");
    expect(items[0]).toHaveTextContent("example.com/products");
    expect(items[1]).toHaveTextContent("tab.actions.click");
    expect(items[1]).toHaveTextContent("Details");
    expect(items[2]).toHaveTextContent("tab.snapshot");
    expect(items[2]).toHaveTextContent("example.com/products/details");
  });

  it("falls back to a quiet Chrome title when no public steps are visible", () => {
    renderWithProviders(
      <BrowserCompactCard content={lifecycleOnlyBrowserContent()} />,
    );

    expect(screen.getByText("Chrome")).toBeInTheDocument();
    expect(screen.getByText("0 steps")).toBeInTheDocument();
    expect(screen.queryByText("Browser actions")).not.toBeInTheDocument();

    const list = screen.getByRole("list", { name: "Browser steps" });
    expect(within(list).queryAllByRole("listitem")).toHaveLength(0);
  });
});

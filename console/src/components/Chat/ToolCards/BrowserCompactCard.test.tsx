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
          phase: "action",
          action: "open",
          status: "ok",
          url: "https://example.com/products",
          title: "Products",
        },
        {
          phase: "action",
          action: "click",
          status: "ok",
          metadata: {
            target_text: "Details",
          },
        },
        {
          phase: "action",
          action: "wait_for",
          status: "ok",
          metadata: {
            target_text: "Product details",
          },
        },
      ],
    },
  };
}

describe("BrowserCompactCard", () => {
  it("registers browser calls to the compact Browser card instead of evidence UI", () => {
    expect(BUILTIN_CARD_REGISTRY.browser).toBe(BrowserCompactCard);
  });

  it("renders a quiet grouped summary for Browser actions", () => {
    renderWithProviders(<BrowserCompactCard content={browserContent()} />);

    expect(screen.getByText("Browser actions")).toBeInTheDocument();
    expect(screen.getByText("3 steps")).toBeInTheDocument();
    expect(screen.queryByText("Browser evidence")).not.toBeInTheDocument();
    expect(screen.queryByText("Copy diagnostics")).not.toBeInTheDocument();

    const list = screen.getByRole("list", { name: "Browser steps" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("Open");
    expect(items[0]).toHaveTextContent("example.com/products");
    expect(items[1]).toHaveTextContent("Click");
    expect(items[1]).toHaveTextContent("Details");
    expect(items[2]).toHaveTextContent("Wait for");
    expect(items[2]).toHaveTextContent("Product details");
  });
});

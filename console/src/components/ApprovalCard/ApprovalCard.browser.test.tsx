import { describe, expect, it, vi, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import { ApprovalCard, type ApprovalCardProps } from "./ApprovalCard";

function approvalProps(
  overrides: Partial<ApprovalCardProps> = {},
): ApprovalCardProps {
  return {
    requestId: "approval-1",
    toolName: "browser",
    toolSource: "builtin",
    severity: "high",
    findingsCount: 1,
    findingsSummary:
      "Browser SDK wants to run a sensitive Chrome action `purchase`.",
    toolParams: {
      tab_id: "7",
      url: "https://shop.example/cart",
      domain: "shop.example",
      title: "Checkout",
      action: "purchase",
      expected_state_change: "The current cart will place a paid order.",
      risk: {
        sensitive: true,
        level: "high",
        kind: "purchase",
        reason: "Purchase action",
        matched: ["purchase"],
      },
      kwargs: {
        target: "Buy now",
        quantity: 1,
        authorization_header: "Bearer secret-token",
        password: "hunter2",
        nested: {
          cookie: "session-cookie",
          safe_label: "visible label",
        },
      },
    },
    createdAt: Date.now() / 1000,
    timeoutSeconds: 60,
    agentId: "agent-1",
    onApprove: vi.fn().mockResolvedValue(undefined),
    onDeny: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

describe("ApprovalCard browser approvals", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders browser approval context with redacted sensitive kwargs", () => {
    renderWithProviders(<ApprovalCard {...approvalProps()} />);

    expect(screen.getByText("Browser action")).toBeInTheDocument();
    expect(screen.getByText("shop.example")).toBeInTheDocument();
    expect(screen.getByText("https://shop.example/cart")).toBeInTheDocument();
    expect(screen.getByText("purchase")).toBeInTheDocument();
    expect(screen.getByText("purchase / high")).toBeInTheDocument();
    expect(screen.getByText("Expected state change")).toBeInTheDocument();
    expect(
      screen.getByText("The current cart will place a paid order."),
    ).toBeInTheDocument();
    expect(screen.getByText("Buy now")).toBeInTheDocument();
    expect(screen.getByText("visible label")).toBeInTheDocument();
    expect(screen.getAllByText("[REDACTED]").length).toBeGreaterThanOrEqual(3);
    expect(screen.queryByText("secret-token")).not.toBeInTheDocument();
    expect(screen.queryByText("hunter2")).not.toBeInTheDocument();
    expect(screen.queryByText("session-cookie")).not.toBeInTheDocument();
    expect(screen.queryByText("Parameters")).not.toBeInTheDocument();
    expect(screen.queryByText(/"kwargs"/)).not.toBeInTheDocument();
  });

  it("does not emit debug console logs for approve or cancel actions", async () => {
    const consoleLog = vi.spyOn(console, "log").mockImplementation(() => {});
    const onApprove = vi.fn().mockResolvedValue(undefined);
    const onCancel = vi.fn();
    renderWithProviders(
      <ApprovalCard
        {...approvalProps({
          onApprove,
          onCancel,
        })}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => {
      expect(onApprove).toHaveBeenCalledWith("approval-1", undefined);
    });
    await userEvent.click(screen.getByRole("button", { name: "Cancel Task" }));

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(consoleLog).not.toHaveBeenCalled();
  });
});

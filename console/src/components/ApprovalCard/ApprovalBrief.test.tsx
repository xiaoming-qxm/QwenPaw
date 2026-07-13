import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import { ApprovalCard, type ApprovalCardProps } from "./ApprovalCard";

function approvalProps(
  overrides: Partial<ApprovalCardProps> = {},
): ApprovalCardProps {
  return {
    requestId: "approval-brief-1",
    toolName: "browser.purchase",
    toolSource: "browser",
    severity: "high",
    findingsCount: 1,
    findingsSummary: "Approval needed for purchase",
    toolParams: {},
    approvalBrief: {
      subject: "Browser purchase action",
      target: "https://shop.example/checkout",
      evidence: {
        button: "Place order",
        authorization: "Bearer secret-token",
        text: "plain-password",
        prompt_text: "plain-prompt",
        file_path: "/Users/example/private/report.pdf",
        nested: {
          cookie: "session-cookie",
          label: "Cart total",
        },
      },
      uncertainties: ["Cannot verify final price after click"],
      possible_consequences: ["A paid order may be placed"],
      risk_kind: "purchase",
      risk_level: "high",
      confidence: 0.82,
      why_approval_required: "The action may create a financial obligation.",
      safe_alternative: "Review the checkout page manually.",
    },
    createdAt: Date.now() / 1000,
    timeoutSeconds: 60,
    agentId: "agent-1",
    onApprove: vi.fn().mockResolvedValue(undefined),
    onDeny: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

describe("ApprovalBrief", () => {
  it("renders a compact redacted decision brief", () => {
    renderWithProviders(<ApprovalCard {...approvalProps()} />);

    expect(screen.getByText("Decision brief")).toBeInTheDocument();
    expect(screen.getByText("Browser purchase action")).toBeInTheDocument();
    expect(
      screen.getByText("https://shop.example/checkout"),
    ).toBeInTheDocument();
    expect(screen.getByText("Place order")).toBeInTheDocument();
    expect(screen.getByText("Cart total")).toBeInTheDocument();
    expect(screen.getByText("purchase / high")).toBeInTheDocument();
    expect(screen.getByText("A paid order may be placed")).toBeInTheDocument();
    expect(
      screen.getByText("Review the checkout page manually."),
    ).toBeInTheDocument();
    expect(screen.getAllByText("[REDACTED]").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText("secret-token")).not.toBeInTheDocument();
    expect(screen.queryByText("session-cookie")).not.toBeInTheDocument();
    expect(screen.queryByText("plain-password")).not.toBeInTheDocument();
    expect(screen.queryByText("plain-prompt")).not.toBeInTheDocument();
    expect(
      screen.queryByText("/Users/example/private/report.pdf"),
    ).not.toBeInTheDocument();
  });
});

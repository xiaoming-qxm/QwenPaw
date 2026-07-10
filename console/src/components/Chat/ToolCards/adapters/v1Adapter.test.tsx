import React from "react";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { adaptCardForV1 } from "./v1Adapter";
import type { ToolCallContent } from "../shared/types";

function renderAdaptedCard(v1Props: Record<string, unknown>) {
  let capturedContent: ToolCallContent | undefined;

  const CaptureCard = ({ content }: { content: ToolCallContent }) => {
    capturedContent = content;
    return null;
  };

  const AdaptedCard = adaptCardForV1(CaptureCard);
  render(<AdaptedCard {...v1Props} />);

  if (!capturedContent) {
    throw new Error("expected adapted card to render with content");
  }

  return capturedContent;
}

describe("adaptCardForV1", () => {
  it("preserves result item metadata without merging it into result output", () => {
    const resultMetadata = {
      browser_trace: [{ api_id: "tab.actions.click", status: "ok" }],
    };
    const dataMetadata = {
      browser_trace: [{ api_id: "browser.tabs.open", status: "ok" }],
    };
    const wrapperMetadata = {
      browser_trace: [{ api_id: "browser.connect", status: "ok" }],
    };
    const toolOutput = { ok: true, text: "browser done" };

    const content = renderAdaptedCard({
      data: {
        status: "completed",
        metadata: wrapperMetadata,
        content: [
          {
            data: {
              id: "call-1",
              name: "browser",
              arguments: JSON.stringify({ action: "batch" }),
            },
          },
          {
            metadata: resultMetadata,
            data: {
              output: toolOutput,
              metadata: dataMetadata,
            },
          },
        ],
      },
    });

    expect((content as ToolCallContent & { metadata?: unknown }).metadata).toBe(
      resultMetadata,
    );
    expect(content.result).toBe(toolOutput);
  });

  it("falls back to result data metadata before wrapper data metadata", () => {
    const dataMetadata = {
      browser_trace: [{ api_id: "tab.actions.click", status: "ok" }],
    };
    const wrapperMetadata = {
      browser_trace: [{ api_id: "browser.connect", status: "ok" }],
    };

    const content = renderAdaptedCard({
      data: {
        status: "completed",
        metadata: wrapperMetadata,
        content: [
          {
            data: {
              id: "call-2",
              name: "browser",
              arguments: {},
            },
          },
          {
            data: {
              output: "browser done",
              metadata: dataMetadata,
            },
          },
        ],
      },
    });

    expect((content as ToolCallContent & { metadata?: unknown }).metadata).toBe(
      dataMetadata,
    );
  });

  it("uses wrapper data metadata when result metadata is missing", () => {
    const wrapperMetadata = {
      browser_trace: [{ api_id: "tab.actions.click", status: "ok" }],
    };

    const content = renderAdaptedCard({
      data: {
        status: "completed",
        metadata: wrapperMetadata,
        content: [
          {
            data: {
              id: "call-3",
              name: "browser",
              arguments: {},
            },
          },
          {
            data: {
              output: "browser done",
            },
          },
        ],
      },
    });

    expect((content as ToolCallContent & { metadata?: unknown }).metadata).toBe(
      wrapperMetadata,
    );
  });
});

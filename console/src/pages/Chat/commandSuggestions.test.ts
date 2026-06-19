import { describe, expect, it } from "vitest";
import { buildCommandSuggestions } from "./commandSuggestions";

describe("buildCommandSuggestions", () => {
  it("includes takeover as a first-class chat command", () => {
    const suggestions = buildCommandSuggestions((key) => key, true);

    expect(suggestions).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          command: "/takeover",
          value: "takeover ",
          description: "chat.commands.takeover.description",
        }),
      ]),
    );
  });
});

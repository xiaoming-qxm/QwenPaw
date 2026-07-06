import { describe, expect, it } from "vitest";
import { buildCommandSuggestions } from "./commandSuggestions";

describe("buildCommandSuggestions", () => {
  it("includes browser as a first-class chat command", () => {
    const suggestions = buildCommandSuggestions((key) => key, true);

    expect(suggestions).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          command: "/browser",
          value: "browser ",
          description: "chat.commands.browserBridge.description",
        }),
      ]),
    );
    expect(suggestions.map((item) => item.command)).not.toContain("/control");
  });
});

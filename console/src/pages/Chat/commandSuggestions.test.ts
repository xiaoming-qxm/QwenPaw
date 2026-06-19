import { describe, expect, it } from "vitest";
import { buildCommandSuggestions } from "./commandSuggestions";

describe("buildCommandSuggestions", () => {
  it("includes browser-control as a first-class chat command", () => {
    const suggestions = buildCommandSuggestions((key) => key, true);

    expect(suggestions).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          command: "/browser-control",
          value: "browser-control ",
          description: "chat.commands.browserControl.description",
        }),
      ]),
    );
    expect(suggestions.map((item) => item.command)).not.toContain("/control");
  });
});

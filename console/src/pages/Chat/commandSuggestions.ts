export interface CommandSuggestion {
  command: string;
  value: string;
  description: string;
}

export function buildCommandSuggestions(
  t: (key: string) => string,
  planEnabled: boolean,
): CommandSuggestion[] {
  const suggestions: CommandSuggestion[] = [
    {
      command: "/clear",
      value: "clear",
      description: t("chat.commands.clear.description"),
    },
    {
      command: "/compact",
      value: "compact",
      description: t("chat.commands.compact.description"),
    },
    {
      command: "/browser",
      value: "browser ",
      description: t("chat.commands.browserBridge.description"),
    },
    {
      command: "/mission",
      value: "mission",
      description: t("chat.commands.mission.description"),
    },
    {
      command: "/skills",
      value: "skills",
      description: t("chat.commands.skills.description"),
    },
  ];

  if (planEnabled) {
    suggestions.push({
      command: "/plan",
      value: "plan ",
      description: t("chat.commands.plan.description"),
    });
  }

  return suggestions;
}

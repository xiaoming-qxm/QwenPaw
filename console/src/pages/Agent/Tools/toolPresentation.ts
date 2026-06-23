import type { ToolInfo } from "../../../api/modules/tools";

type ConfigurableTool = Pick<ToolInfo, "requires_config" | "config_fields">;

export function isToolConfigurable(tool: ConfigurableTool): boolean {
  return Boolean(tool.requires_config || (tool.config_fields?.length ?? 0) > 0);
}

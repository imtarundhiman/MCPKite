import { requestJson } from "./client";
import { isPaginatedPage, pageQuery } from "./pagination";
import type { ToolDefinition, ToolDefinitionPage } from "../types/server";

function isToolDefinition(value: unknown): value is ToolDefinition {
  if (typeof value !== "object" || value === null) return false;
  const tool = value as Record<string, unknown>;
  return (
    typeof tool.id === "string" &&
    typeof tool.server_id === "string" &&
    typeof tool.name === "string" &&
    typeof tool.description === "string" &&
    typeof tool.source === "string" &&
    typeof tool.input_schema === "object" &&
    tool.input_schema !== null &&
    (tool.execution_status === "disabled" || tool.execution_status === "active") &&
    typeof tool.created_at === "string" &&
    typeof tool.updated_at === "string"
  );
}

function isToolList(value: unknown): value is ToolDefinition[] {
  return Array.isArray(value) && value.every(isToolDefinition);
}

async function saveTool(
  serverId: string,
  source: string,
  toolId?: string,
): Promise<ToolDefinition> {
  const path = `/api/v1/servers/${encodeURIComponent(serverId)}/tools${
    toolId ? `/${encodeURIComponent(toolId)}` : ""
  }`;
  const result = await requestJson(
    path,
    {
      method: toolId ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source }),
    },
    "Could not save tool definition.",
  );
  if (!isToolDefinition(result)) {
    throw new Error("The server returned an invalid tool definition.");
  }
  return result;
}

export async function listTools(serverId: string): Promise<ToolDefinition[]> {
  const result = await requestJson(
    `/api/v1/servers/${encodeURIComponent(serverId)}/tools`,
    undefined,
    "Could not load tools.",
  );
  if (!isToolList(result)) {
    throw new Error("The server returned an invalid tool list.");
  }
  return result;
}

export async function listToolPage(
  serverId: string,
  page: number,
  pageSize: ToolDefinitionPage["page_size"],
): Promise<ToolDefinitionPage> {
  const result = await requestJson(
    `/api/v1/servers/${encodeURIComponent(serverId)}/tools/page?${pageQuery(page, pageSize)}`,
    undefined,
    "Could not load tools.",
  );
  if (!isPaginatedPage(result, isToolDefinition)) {
    throw new Error("The server returned an invalid tool page.");
  }
  return result;
}

export async function createTool(
  serverId: string,
  source: string,
): Promise<ToolDefinition> {
  return saveTool(serverId, source);
}

export async function updateTool(
  serverId: string,
  toolId: string,
  source: string,
): Promise<ToolDefinition> {
  return saveTool(serverId, source, toolId);
}

export async function deleteTool(serverId: string, toolId: string): Promise<void> {
  await requestJson(
    `/api/v1/servers/${encodeURIComponent(serverId)}/tools/${encodeURIComponent(toolId)}`,
    { method: "DELETE" },
    "Could not delete tool definition.",
  );
}

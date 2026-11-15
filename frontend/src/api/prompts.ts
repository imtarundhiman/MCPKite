import { requestJson } from "./client";
import { isPaginatedPage, pageQuery } from "./pagination";
import type {
  PromptArgumentDefinition,
  PromptDefinition,
  PromptDefinitionPage,
} from "../types/server";

function isPromptArgumentDefinition(value: unknown): value is PromptArgumentDefinition {
  if (typeof value !== "object" || value === null) return false;
  const argument = value as Record<string, unknown>;
  return (
    typeof argument.name === "string" &&
    typeof argument.description === "string" &&
    typeof argument.required === "boolean" &&
    (argument.default_value === null || typeof argument.default_value === "string")
  );
}

function isPromptDefinition(value: unknown): value is PromptDefinition {
  if (typeof value !== "object" || value === null) return false;
  const prompt = value as Record<string, unknown>;
  return (
    typeof prompt.id === "string" &&
    typeof prompt.server_id === "string" &&
    typeof prompt.name === "string" &&
    typeof prompt.description === "string" &&
    typeof prompt.template === "string" &&
    Array.isArray(prompt.arguments) &&
    prompt.arguments.every(isPromptArgumentDefinition) &&
    typeof prompt.created_at === "string" &&
    typeof prompt.updated_at === "string"
  );
}

function isPromptList(value: unknown): value is PromptDefinition[] {
  return Array.isArray(value) && value.every(isPromptDefinition);
}

async function savePrompt(
  serverId: string,
  definition: Omit<PromptDefinition, "id" | "server_id" | "created_at" | "updated_at">,
  promptId?: string,
): Promise<PromptDefinition> {
  const path = `/api/v1/servers/${encodeURIComponent(serverId)}/prompts${
    promptId ? `/${encodeURIComponent(promptId)}` : ""
  }`;
  const result = await requestJson(
    path,
    {
      method: promptId ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(definition),
    },
    "Could not save prompt definition.",
  );
  if (!isPromptDefinition(result)) {
    throw new Error("The server returned an invalid prompt definition.");
  }
  return result;
}

export async function listPrompts(serverId: string): Promise<PromptDefinition[]> {
  const result = await requestJson(
    `/api/v1/servers/${encodeURIComponent(serverId)}/prompts`,
    undefined,
    "Could not load prompts.",
  );
  if (!isPromptList(result)) {
    throw new Error("The server returned an invalid prompt list.");
  }
  return result;
}

export async function listPromptPage(
  serverId: string,
  page: number,
  pageSize: PromptDefinitionPage["page_size"],
): Promise<PromptDefinitionPage> {
  const result = await requestJson(
    `/api/v1/servers/${encodeURIComponent(serverId)}/prompts/page?${pageQuery(page, pageSize)}`,
    undefined,
    "Could not load prompts.",
  );
  if (!isPaginatedPage(result, isPromptDefinition)) {
    throw new Error("The server returned an invalid prompt page.");
  }
  return result;
}

export async function createPrompt(
  serverId: string,
  definition: Omit<PromptDefinition, "id" | "server_id" | "created_at" | "updated_at">,
): Promise<PromptDefinition> {
  return savePrompt(serverId, definition);
}

export async function updatePrompt(
  serverId: string,
  promptId: string,
  definition: Omit<PromptDefinition, "id" | "server_id" | "created_at" | "updated_at">,
): Promise<PromptDefinition> {
  return savePrompt(serverId, definition, promptId);
}

export async function deletePrompt(serverId: string, promptId: string): Promise<void> {
  await requestJson(
    `/api/v1/servers/${encodeURIComponent(serverId)}/prompts/${encodeURIComponent(promptId)}`,
    { method: "DELETE" },
    "Could not delete prompt definition.",
  );
}

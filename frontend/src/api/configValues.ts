import { requestJson } from "./client";
import { isPaginatedPage, pageQuery } from "./pagination";
import type {
  PageSize,
  WorkspaceConfigValue,
  WorkspaceConfigValuePage,
} from "../types/server";

function isWorkspaceConfigValue(value: unknown): value is WorkspaceConfigValue {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.id === "string" &&
    typeof record.name === "string" &&
    (record.kind === "variable" || record.kind === "secret") &&
    (typeof record.value === "string" || record.value === null) &&
    typeof record.created_at === "string" &&
    typeof record.updated_at === "string"
  );
}

export async function listWorkspaceConfigValues(): Promise<WorkspaceConfigValue[]> {
  const result = await requestJson(
    "/api/v1/config-values",
    undefined,
    "Could not load workspace values.",
  );
  if (!Array.isArray(result) || !result.every(isWorkspaceConfigValue)) {
    throw new Error("The server returned an invalid workspace value list.");
  }
  return result;
}

export async function listWorkspaceConfigValuePage(
  page: number,
  pageSize: PageSize,
): Promise<WorkspaceConfigValuePage> {
  const result = await requestJson(
    `/api/v1/config-values/registry?${pageQuery(page, pageSize)}`,
    undefined,
    "Could not load workspace values.",
  );
  if (!isPaginatedPage(result, isWorkspaceConfigValue)) {
    throw new Error("The server returned an invalid workspace value page.");
  }
  return result;
}

export async function saveWorkspaceConfigValue(
  input: { name: string; kind: "variable" | "secret"; value: string },
  id?: string,
): Promise<WorkspaceConfigValue> {
  const result = await requestJson(
    id ? `/api/v1/config-values/${encodeURIComponent(id)}` : "/api/v1/config-values",
    {
      method: id ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
    id ? "Could not update the workspace value." : "Could not save the workspace value.",
  );
  if (!isWorkspaceConfigValue(result)) {
    throw new Error("The server returned an invalid workspace value.");
  }
  return result;
}

export async function deleteWorkspaceConfigValue(valueId: string): Promise<void> {
  await requestJson(
    `/api/v1/config-values/${encodeURIComponent(valueId)}`,
    { method: "DELETE" },
    "Could not delete the workspace value.",
  );
}

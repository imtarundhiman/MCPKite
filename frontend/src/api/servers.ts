import { requestJson } from "./client";
import { isPaginatedPage, pageQuery } from "./pagination";
import type {
  Server,
  ServerDeletionResult,
  ServerDeletionSummary,
  ServerRegistryPage,
  ServerUpdateInput,
} from "../types/server";

type CreateServerInput = {
  name: string;
  description: string;
  auth_mode: "normal" | "protected";
  secret_id: string | null;
};

function isServer(value: unknown): value is Server {
  if (typeof value !== "object" || value === null) return false;
  const server = value as Record<string, unknown>;
  return (
    typeof server.id === "string" &&
    typeof server.name === "string" &&
    typeof server.description === "string" &&
    typeof server.created_at === "string" &&
    typeof server.endpoint_path === "string" &&
    (server.auth_mode === "normal" || server.auth_mode === "protected") &&
    (typeof server.secret_id === "string" || server.secret_id === null) &&
    (typeof server.secret_name === "string" || server.secret_name === null)
  );
}

function isServerList(value: unknown): value is Server[] {
  return Array.isArray(value) && value.every(isServer);
}

function isServerRegistryPage(value: unknown): value is ServerRegistryPage {
  return isPaginatedPage(value, isServer);
}

function isServerDeletionSummary(value: unknown): value is ServerDeletionSummary {
  if (typeof value !== "object" || value === null) return false;
  const summary = value as Record<string, unknown>;
  return (
    typeof summary.tool_count === "number" &&
    Number.isInteger(summary.tool_count) &&
    summary.tool_count >= 0 &&
    typeof summary.prompt_count === "number" &&
    Number.isInteger(summary.prompt_count) &&
    summary.prompt_count >= 0 &&
    typeof summary.resource_count === "number" &&
    Number.isInteger(summary.resource_count) &&
    summary.resource_count >= 0 &&
    typeof summary.file_resource_count === "number" &&
    Number.isInteger(summary.file_resource_count) &&
    summary.file_resource_count >= 0
  );
}

function isServerDeletionResult(value: unknown): value is ServerDeletionResult {
  if (typeof value !== "object" || value === null) return false;
  const result = value as Record<string, unknown>;
  return (
    typeof result.file_cleanup_failures === "number" &&
    Number.isInteger(result.file_cleanup_failures) &&
    result.file_cleanup_failures >= 0 &&
    typeof result.runtime_shutdown_failed === "boolean"
  );
}

export async function listServers(): Promise<Server[]> {
  const result = await requestJson("/api/v1/servers", undefined, "Could not load servers.");
  if (!isServerList(result)) {
    throw new Error("The server returned an invalid server list.");
  }
  return result;
}

export async function listRecentServers(): Promise<Server[]> {
  const result = await requestJson(
    "/api/v1/servers/recent",
    undefined,
    "Could not load recent servers.",
  );
  if (!isServerList(result)) {
    throw new Error("The server returned an invalid recent server list.");
  }
  return result;
}

export async function listServerRegistryPage(
  page: number,
  pageSize: ServerRegistryPage["page_size"],
): Promise<ServerRegistryPage> {
  const query = pageQuery(page, pageSize);
  const result = await requestJson(
    `/api/v1/servers/registry?${query.toString()}`,
    undefined,
    "Could not load the server registry.",
  );
  if (!isServerRegistryPage(result)) {
    throw new Error("The server returned an invalid server registry page.");
  }
  return result;
}

export async function createServer(input: CreateServerInput): Promise<Server> {
  const result = await requestJson(
    "/api/v1/servers",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
    "Could not create the server.",
  );
  if (!isServer(result)) {
    throw new Error("The server returned an invalid server definition.");
  }
  return result;
}

export async function updateServer(
  serverId: string,
  input: ServerUpdateInput,
): Promise<Server> {
  const result = await requestJson(
    `/api/v1/servers/${encodeURIComponent(serverId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
    "Could not update the server.",
  );
  if (!isServer(result)) {
    throw new Error("The server returned an invalid server definition.");
  }
  return result;
}

export async function getServerDeletionSummary(
  serverId: string,
): Promise<ServerDeletionSummary> {
  const result = await requestJson(
    `/api/v1/servers/${encodeURIComponent(serverId)}/deletion-summary`,
    undefined,
    "Could not check the server's attached content.",
  );
  if (!isServerDeletionSummary(result)) {
    throw new Error("The server returned an invalid deletion summary.");
  }
  return result;
}

export async function deleteServer(
  serverId: string,
): Promise<ServerDeletionResult> {
  const result = await requestJson(
    `/api/v1/servers/${encodeURIComponent(serverId)}`,
    { method: "DELETE" },
    "Could not delete the server.",
  );
  if (!isServerDeletionResult(result)) {
    throw new Error("The server returned an invalid deletion result.");
  }
  return result;
}

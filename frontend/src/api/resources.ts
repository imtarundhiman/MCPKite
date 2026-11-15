import { requestJson, uploadFormData } from "./client";
import { isPaginatedPage, pageQuery } from "./pagination";
import type { ResourceDefinition, ResourceDefinitionPage } from "../types/server";

function isResourceDefinition(value: unknown): value is ResourceDefinition {
  if (typeof value !== "object" || value === null) return false;
  const resource = value as Record<string, unknown>;
  return (
    typeof resource.id === "string" &&
    typeof resource.server_id === "string" &&
    typeof resource.uri === "string" &&
    typeof resource.name === "string" &&
    typeof resource.description === "string" &&
    typeof resource.mime_type === "string" &&
    (resource.content_kind === "text" || resource.content_kind === "binary") &&
    (typeof resource.content === "string" || resource.content === null) &&
    (typeof resource.file_name === "string" || resource.file_name === null) &&
    (typeof resource.size_bytes === "number" || resource.size_bytes === null) &&
    (typeof resource.sha256 === "string" || resource.sha256 === null) &&
    Array.isArray(resource.audience) &&
    resource.audience.every((entry) => entry === "user" || entry === "assistant") &&
    (typeof resource.priority === "number" || resource.priority === null) &&
    typeof resource.created_at === "string" &&
    typeof resource.updated_at === "string"
  );
}

export type ResourceMetadata = Pick<
  ResourceDefinition,
  "uri" | "name" | "description" | "mime_type" | "audience" | "priority"
>;

type TextResourceInput = ResourceMetadata & Pick<ResourceDefinition, "content">;

async function saveResource(
  serverId: string,
  definition: TextResourceInput,
  resourceId?: string,
): Promise<ResourceDefinition> {
  const path = `/api/v1/servers/${encodeURIComponent(serverId)}/resources${
    resourceId ? `/${encodeURIComponent(resourceId)}` : ""
  }`;
  const result = await requestJson(
    path,
    {
      method: resourceId ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(definition),
    },
    "Could not save resource definition.",
  );
  if (!isResourceDefinition(result)) {
    throw new Error("The server returned an invalid resource definition.");
  }
  return result;
}

export async function listResourcePage(
  serverId: string,
  page: number,
  pageSize: ResourceDefinitionPage["page_size"],
): Promise<ResourceDefinitionPage> {
  const result = await requestJson(
    `/api/v1/servers/${encodeURIComponent(serverId)}/resources/page?${pageQuery(page, pageSize)}`,
    undefined,
    "Could not load resources.",
  );
  if (!isPaginatedPage(result, isResourceDefinition)) {
    throw new Error("The server returned an invalid resource page.");
  }
  return result;
}

export async function createResource(
  serverId: string,
  definition: TextResourceInput,
): Promise<ResourceDefinition> {
  return saveResource(serverId, definition);
}

export async function updateResource(
  serverId: string,
  resourceId: string,
  definition: TextResourceInput,
): Promise<ResourceDefinition> {
  return saveResource(serverId, definition, resourceId);
}

async function saveBinaryResource(
  serverId: string,
  definition: ResourceMetadata,
  file: File | undefined,
  onProgress: (progress: number) => void,
  resourceId?: string,
): Promise<ResourceDefinition> {
  const formData = new FormData();
  formData.append(
    "metadata",
    JSON.stringify({
      ...definition,
      mime_type: definition.mime_type || null,
    }),
  );
  if (file) formData.append("file", file);

  const path = `/api/v1/servers/${encodeURIComponent(serverId)}/resources${
    resourceId ? `/${encodeURIComponent(resourceId)}` : ""
  }/binary`;
  const result = await uploadFormData(
    path,
    resourceId ? "PUT" : "POST",
    formData,
    onProgress,
    "Could not save binary resource.",
  );
  if (!isResourceDefinition(result)) {
    throw new Error("The server returned an invalid binary resource definition.");
  }
  return result;
}

export async function createBinaryResource(
  serverId: string,
  definition: ResourceMetadata,
  file: File,
  onProgress: (progress: number) => void,
): Promise<ResourceDefinition> {
  return saveBinaryResource(serverId, definition, file, onProgress);
}

export async function updateBinaryResource(
  serverId: string,
  resourceId: string,
  definition: ResourceMetadata,
  file: File | undefined,
  onProgress: (progress: number) => void,
): Promise<ResourceDefinition> {
  return saveBinaryResource(serverId, definition, file, onProgress, resourceId);
}

export async function deleteResource(serverId: string, resourceId: string): Promise<void> {
  await requestJson(
    `/api/v1/servers/${encodeURIComponent(serverId)}/resources/${encodeURIComponent(resourceId)}`,
    { method: "DELETE" },
    "Could not delete resource definition.",
  );
}

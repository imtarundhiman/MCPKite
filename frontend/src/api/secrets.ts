import { requestJson } from "./client";
import { isPaginatedPage, pageQuery } from "./pagination";
import type {
  CreatedSecret,
  PageSize,
  Secret,
  SecretRegistryPage,
} from "../types/server";

function isSecret(value: unknown): value is Secret {
  if (typeof value !== "object" || value === null) return false;
  const secret = value as Record<string, unknown>;
  return (
    typeof secret.id === "string" &&
    typeof secret.name === "string" &&
    (typeof secret.server_id === "string" || secret.server_id === null) &&
    (typeof secret.server_name === "string" || secret.server_name === null) &&
    typeof secret.created_at === "string"
  );
}

function isCreatedSecret(value: unknown): value is CreatedSecret {
  return isSecret(value) && typeof (value as Record<string, unknown>).value === "string";
}

export async function listSecrets(): Promise<Secret[]> {
  const result = await requestJson("/api/v1/secrets", undefined, "Could not load secrets.");
  if (!Array.isArray(result) || !result.every(isSecret)) {
    throw new Error("The server returned an invalid secret list.");
  }
  return result;
}

export async function listSecretPage(
  page: number,
  pageSize: PageSize,
): Promise<SecretRegistryPage> {
  const query = pageQuery(page, pageSize);
  const result = await requestJson(
    `/api/v1/secrets/registry?${query}`,
    undefined,
    "Could not load the secrets list.",
  );
  if (!isPaginatedPage(result, isSecret)) {
    throw new Error("The server returned an invalid secrets page.");
  }
  return result;
}

export async function createSecret(name: string): Promise<CreatedSecret> {
  const result = await requestJson(
    "/api/v1/secrets",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    },
    "Could not create the secret.",
  );
  if (!isCreatedSecret(result)) {
    throw new Error("The server returned an invalid secret.");
  }
  return result;
}

export async function deleteSecret(secretId: string): Promise<void> {
  await requestJson(
    `/api/v1/secrets/${encodeURIComponent(secretId)}`,
    { method: "DELETE" },
    "Could not delete the secret.",
  );
}

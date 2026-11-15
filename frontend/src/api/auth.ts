import {
  apiRequest,
  initializeCsrfToken,
  requestJson,
} from "./client";
import type { AuthUser } from "../types/server";

type AuthStatus = { workspace_initialized: boolean };
type InvitePreview = { workspace_name: string; expires_at: string };

function isAuthUser(value: unknown): value is AuthUser {
  if (typeof value !== "object" || value === null) return false;
  const user = value as Record<string, unknown>;
  return (
    typeof user.id === "string" &&
    typeof user.email === "string" &&
    typeof user.display_name === "string" &&
    typeof user.workspace_id === "string" &&
    typeof user.workspace_name === "string" &&
    (user.role === "owner" || user.role === "member")
  );
}

function isAuthStatus(value: unknown): value is AuthStatus {
  return (
    typeof value === "object" &&
    value !== null &&
    "workspace_initialized" in value &&
    typeof value.workspace_initialized === "boolean"
  );
}

function isInvitePreview(value: unknown): value is InvitePreview {
  return (
    typeof value === "object" &&
    value !== null &&
    "workspace_name" in value &&
    typeof value.workspace_name === "string" &&
    "expires_at" in value &&
    typeof value.expires_at === "string"
  );
}

async function authUserRequest(path: string, init?: RequestInit): Promise<AuthUser> {
  const result = await requestJson(path, init, "Authentication failed.", false);
  if (!isAuthUser(result)) {
    throw new Error("The server returned an invalid account record.");
  }
  return result;
}

export async function getAuthStatus(): Promise<AuthStatus> {
  const result = await requestJson(
    "/api/v1/auth/status",
    undefined,
    "Could not check workspace setup.",
    false,
  );
  if (!isAuthStatus(result)) {
    throw new Error("The server returned an invalid authentication status.");
  }
  return result;
}

export async function getCurrentUser(): Promise<AuthUser> {
  const result = await requestJson(
    "/api/v1/auth/me",
    undefined,
    "Could not load the signed-in account.",
  );
  if (!isAuthUser(result)) {
    throw new Error("The server returned an invalid account record.");
  }
  return result;
}

export async function register(input: {
  email: string;
  password: string;
  display_name: string;
  workspace_name?: string;
  invite_token?: string;
}): Promise<AuthUser> {
  await initializeCsrfToken();
  return authUserRequest("/api/v1/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function updateProfile(displayName: string): Promise<AuthUser> {
  return authUserRequest("/api/v1/auth/me", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_name: displayName }),
  });
}

export async function login(input: {
  email: string;
  password: string;
}): Promise<AuthUser> {
  await initializeCsrfToken();
  return authUserRequest("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export async function logout(): Promise<void> {
  const response = await apiRequest("/api/v1/auth/logout", { method: "POST" }, false);
  if (!response.ok) {
    const result: unknown = await response.json();
    const message =
      typeof result === "object" &&
      result !== null &&
      "detail" in result &&
      typeof result.detail === "string"
        ? result.detail
        : "Could not sign out.";
    throw new Error(message);
  }
}

export async function getInvitePreview(token: string): Promise<InvitePreview> {
  const result = await requestJson(
    `/api/v1/auth/invites/${encodeURIComponent(token)}`,
    undefined,
    "This invitation is no longer valid.",
    false,
  );
  if (!isInvitePreview(result)) {
    throw new Error("The server returned an invalid invitation.");
  }
  return result;
}

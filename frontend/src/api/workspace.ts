import { requestJson } from "./client";
import { isPaginatedPage, pageQuery } from "./pagination";
import type {
  PageSize,
  Workspace,
  WorkspaceInvite,
  WorkspaceMember,
  WorkspaceMemberPage,
  WorkspaceSummary,
} from "../types/server";

type CreatedInvite = WorkspaceInvite & { token: string };

function isWorkspace(value: unknown): value is Workspace {
  if (typeof value !== "object" || value === null) return false;
  const workspace = value as Record<string, unknown>;
  return (
    typeof workspace.id === "string" &&
    typeof workspace.name === "string" &&
    (workspace.role === "owner" || workspace.role === "member")
  );
}

function isMember(value: unknown): value is WorkspaceMember {
  if (typeof value !== "object" || value === null) return false;
  const member = value as Record<string, unknown>;
  return (
    typeof member.user_id === "string" &&
    typeof member.email === "string" &&
    (member.role === "owner" || member.role === "member") &&
    typeof member.joined_at === "string"
  );
}

function isWorkspaceSummary(value: unknown): value is WorkspaceSummary {
  if (typeof value !== "object" || value === null) return false;
  const summary = value as Record<string, unknown>;
  return (
    [
      "server_count",
      "tool_count",
      "active_tool_count",
      "prompt_count",
      "secret_count",
      "member_count",
    ].every((key) => Number.isInteger(summary[key]) && Number(summary[key]) >= 0) &&
    Number(summary.active_tool_count) <= Number(summary.tool_count)
  );
}

function isInvite(value: unknown): value is WorkspaceInvite {
  if (typeof value !== "object" || value === null) return false;
  const invite = value as Record<string, unknown>;
  return (
    typeof invite.id === "string" &&
    typeof invite.created_at === "string" &&
    typeof invite.expires_at === "string"
  );
}

function isCreatedInvite(value: unknown): value is CreatedInvite {
  return isInvite(value) && typeof (value as Record<string, unknown>).token === "string";
}

export async function getWorkspace(): Promise<Workspace> {
  const result = await requestJson("/api/v1/workspace", undefined, "Could not load workspace.");
  if (!isWorkspace(result)) throw new Error("The server returned an invalid workspace.");
  return result;
}

export async function getWorkspaceSummary(): Promise<WorkspaceSummary> {
  const result = await requestJson(
    "/api/v1/workspace/summary",
    undefined,
    "Could not load workspace totals.",
  );
  if (!isWorkspaceSummary(result)) {
    throw new Error("The server returned invalid workspace totals.");
  }
  return result;
}

export async function getMembers(): Promise<WorkspaceMember[]> {
  const result = await requestJson("/api/v1/workspace/members", undefined, "Could not load members.");
  if (!Array.isArray(result) || !result.every(isMember)) {
    throw new Error("The server returned an invalid member list.");
  }
  return result;
}

export async function getMemberPage(
  page: number,
  pageSize: PageSize,
): Promise<WorkspaceMemberPage> {
  const query = pageQuery(page, pageSize);
  const result = await requestJson(
    `/api/v1/workspace/members/registry?${query}`,
    undefined,
    "Could not load workspace members.",
  );
  if (!isPaginatedPage(result, isMember)) {
    throw new Error("The server returned an invalid members page.");
  }
  return result;
}

export async function getInvites(): Promise<WorkspaceInvite[]> {
  const result = await requestJson("/api/v1/workspace/invites", undefined, "Could not load invites.");
  if (!Array.isArray(result) || !result.every(isInvite)) {
    throw new Error("The server returned an invalid invite list.");
  }
  return result;
}

export async function createInvite(): Promise<CreatedInvite> {
  const result = await requestJson(
    "/api/v1/workspace/invites",
    { method: "POST" },
    "Could not create an invitation.",
  );
  if (!isCreatedInvite(result)) {
    throw new Error("The server returned an invalid invitation.");
  }
  return result;
}

export async function revokeInvite(inviteId: string): Promise<void> {
  await requestJson(
    `/api/v1/workspace/invites/${encodeURIComponent(inviteId)}`,
    { method: "DELETE" },
    "Could not revoke the invitation.",
  );
}

export async function removeMember(userId: string): Promise<void> {
  await requestJson(
    `/api/v1/workspace/members/${encodeURIComponent(userId)}`,
    { method: "DELETE" },
    "Could not remove the workspace member.",
  );
}

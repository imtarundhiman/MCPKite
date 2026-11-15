export type Server = {
  id: string;
  name: string;
  description: string;
  created_at: string;
  endpoint_path: string;
  auth_mode: "normal" | "protected";
  secret_id: string | null;
  secret_name: string | null;
};

export type ServerUpdateInput = {
  name: string;
  description: string;
  auth_mode: "normal" | "protected";
  secret_id: string | null;
};

export type PageSize = 10 | 12 | 25 | 50;

export type PaginatedPage<T> = {
  items: T[];
  page: number;
  page_size: PageSize;
  total: number;
  total_pages: number;
};

export type ServerRegistryPage = PaginatedPage<Server>;

export type ServerDeletionSummary = {
  tool_count: number;
  prompt_count: number;
  resource_count: number;
  file_resource_count: number;
};

export type ServerDeletionResult = {
  file_cleanup_failures: number;
  runtime_shutdown_failed: boolean;
};

export type ToolDefinition = {
  id: string;
  server_id: string;
  name: string;
  description: string;
  source: string;
  input_schema: Record<string, unknown>;
  execution_status: "disabled" | "active";
  created_at: string;
  updated_at: string;
};

export type ToolDefinitionPage = PaginatedPage<ToolDefinition>;

export type PromptArgumentDefinition = {
  name: string;
  description: string;
  required: boolean;
  default_value: string | null;
};

export type PromptDefinition = {
  id: string;
  server_id: string;
  name: string;
  description: string;
  template: string;
  arguments: PromptArgumentDefinition[];
  created_at: string;
  updated_at: string;
};

export type PromptDefinitionPage = PaginatedPage<PromptDefinition>;

export type ResourceDefinition = {
  id: string;
  server_id: string;
  uri: string;
  name: string;
  description: string;
  mime_type: string;
  content_kind: "text" | "binary";
  content: string | null;
  file_name: string | null;
  size_bytes: number | null;
  sha256: string | null;
  audience: ("user" | "assistant")[];
  priority: number | null;
  created_at: string;
  updated_at: string;
};

export type ResourceDefinitionPage = PaginatedPage<ResourceDefinition>;

export type AuthUser = {
  id: string;
  email: string;
  display_name: string;
  workspace_id: string;
  workspace_name: string;
  role: "owner" | "member";
};

export type Workspace = {
  id: string;
  name: string;
  role: "owner" | "member";
};

export type WorkspaceSummary = {
  server_count: number;
  tool_count: number;
  active_tool_count: number;
  prompt_count: number;
  secret_count: number;
  member_count: number;
};

export type WorkspaceMember = {
  user_id: string;
  email: string;
  role: "owner" | "member";
  joined_at: string;
};

export type WorkspaceInvite = {
  id: string;
  created_at: string;
  expires_at: string;
};

export type Secret = {
  id: string;
  name: string;
  server_id: string | null;
  server_name: string | null;
  created_at: string;
};

export type SecretRegistryPage = PaginatedPage<Secret>;

export type CreatedSecret = Secret & {
  value: string;
};

export type WorkspaceConfigValue = {
  id: string;
  name: string;
  kind: "variable" | "secret";
  value: string | null;
  created_at: string;
  updated_at: string;
};

export type WorkspaceConfigValuePage = PaginatedPage<WorkspaceConfigValue>;

export type WorkspaceMemberPage = PaginatedPage<WorkspaceMember>;

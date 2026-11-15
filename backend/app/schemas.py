from datetime import datetime, timezone
import keyword
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CreateServerRequest(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=80)]
    description: Annotated[str, Field(max_length=300)] = ""
    auth_mode: Literal["normal", "protected"] = "normal"
    secret_id: str | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name must contain at least one non-whitespace character.")
        return normalized

    @field_validator("description")
    @classmethod
    def trim_description(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_auth_configuration(self) -> "CreateServerRequest":
        if self.auth_mode == "protected" and self.secret_id is None:
            raise ValueError("Choose a secret before creating a protected server.")
        if self.auth_mode == "normal" and self.secret_id is not None:
            raise ValueError("Normal servers cannot be assigned a secret.")
        return self


class UpdateServerSecurityRequest(BaseModel):
    auth_mode: Literal["normal", "protected"]
    secret_id: str | None = None


class UpdateServerRequest(UpdateServerSecurityRequest):
    name: Annotated[str, Field(min_length=1, max_length=80)]
    description: Annotated[str, Field(max_length=300)]
    secret_id: str | None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name must contain at least one non-whitespace character.")
        return normalized

    @field_validator("description")
    @classmethod
    def trim_description(cls, value: str) -> str:
        return value.strip()


class ServerRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    created_at: datetime
    endpoint_path: str
    auth_mode: Literal["normal", "protected"]
    secret_id: str | None = None
    secret_name: str | None = None

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class ServerRegistryPage(BaseModel):
    items: list[ServerRecord]
    page: int
    page_size: Literal[10, 25, 50]
    total: int
    total_pages: int


class ServerDeletionSummary(BaseModel):
    tool_count: int
    prompt_count: int
    resource_count: int
    file_resource_count: int


class ServerDeletionResult(BaseModel):
    file_cleanup_failures: int
    runtime_shutdown_failed: bool


class ToolDefinitionRecord(BaseModel):
    id: str
    server_id: str
    name: str
    description: str
    source: str
    input_schema: dict[str, object]
    execution_status: Literal["disabled", "active"] = "disabled"
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class ToolDefinitionPage(BaseModel):
    items: list[ToolDefinitionRecord]
    page: int
    page_size: Literal[10, 12, 25, 50]
    total: int
    total_pages: int


class SaveToolDefinitionRequest(BaseModel):
    source: Annotated[str, Field(min_length=1)]


class PromptArgumentDefinition(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=64)]
    description: Annotated[str, Field(max_length=300)] = ""
    required: bool = True
    default_value: Annotated[str | None, Field(max_length=2_000)] = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", normalized):
            raise ValueError("Argument names must be valid identifiers.")
        if keyword.iskeyword(normalized):
            raise ValueError("Argument names cannot be Python keywords.")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_default(self) -> "PromptArgumentDefinition":
        if self.required and self.default_value is not None:
            raise ValueError("Required arguments cannot have a default value.")
        return self


_PROMPT_PLACEHOLDER = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
_WORKSPACE_VALUE_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _validate_workspace_value_placeholders(value: str) -> str:
    unmatched_value = _WORKSPACE_VALUE_PLACEHOLDER.sub("", value)
    if "${" in unmatched_value:
        raise ValueError("Use workspace values in the form ${NAME}.")
    return value


class PromptDefinitionRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    server_id: str
    name: str
    description: str
    template: str
    arguments: list[PromptArgumentDefinition]
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class PromptDefinitionPage(BaseModel):
    items: list[PromptDefinitionRecord]
    page: int
    page_size: Literal[10, 12, 25, 50]
    total: int
    total_pages: int


class ResourceDefinitionRecord(BaseModel):
    id: str
    server_id: str
    uri: str
    name: str
    description: str
    mime_type: str
    content_kind: Literal["text", "binary"]
    content: str | None
    file_name: str | None
    size_bytes: int | None
    sha256: str | None
    audience: list[Literal["user", "assistant"]]
    priority: Annotated[float | None, Field(ge=0, le=1)]
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class ResourceDefinitionPage(BaseModel):
    items: list[ResourceDefinitionRecord]
    page: int
    page_size: Literal[10, 12, 25, 50]
    total: int
    total_pages: int


class SaveResourceDefinitionRequest(BaseModel):
    uri: Annotated[str, Field(min_length=1, max_length=2048)]
    name: Annotated[str, Field(min_length=1, max_length=100)]
    description: Annotated[str, Field(max_length=300)] = ""
    mime_type: Annotated[str, Field(min_length=1, max_length=128)] = "text/plain"
    content: Annotated[str, Field(max_length=50_000)] = ""
    audience: list[Literal["user", "assistant"]] = Field(default_factory=list)
    priority: Annotated[float | None, Field(ge=0, le=1)] = None

    @field_validator("uri")
    @classmethod
    def normalize_uri(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Resource URI must not be blank.")
        return normalized

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Resource name must not be blank.")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("content")
    @classmethod
    def validate_workspace_value_placeholders(cls, value: str) -> str:
        return _validate_workspace_value_placeholders(value)

    @field_validator("audience")
    @classmethod
    def normalize_audience(
        cls, value: list[Literal["user", "assistant"]]
    ) -> list[Literal["user", "assistant"]]:
        if len(value) != len(set(value)):
            raise ValueError("Resource audiences must not contain duplicates.")
        return value


_MIME_TYPE = re.compile(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+\Z")


class SaveBinaryResourceMetadataRequest(BaseModel):
    uri: Annotated[str, Field(min_length=1, max_length=2048)]
    name: Annotated[str, Field(min_length=1, max_length=100)]
    description: Annotated[str, Field(max_length=300)] = ""
    mime_type: Annotated[str | None, Field(max_length=128)] = None
    audience: list[Literal["user", "assistant"]] = Field(default_factory=list)
    priority: Annotated[float | None, Field(ge=0, le=1)] = None

    @field_validator("uri")
    @classmethod
    def normalize_uri(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Resource URI must not be blank.")
        return normalized

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Resource name must not be blank.")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("mime_type")
    @classmethod
    def validate_mime_type(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip().lower()
        if not _MIME_TYPE.fullmatch(normalized):
            raise ValueError("MIME type must use the type/subtype format.")
        return normalized

    @field_validator("audience")
    @classmethod
    def normalize_audience(
        cls, value: list[Literal["user", "assistant"]]
    ) -> list[Literal["user", "assistant"]]:
        if len(value) != len(set(value)):
            raise ValueError("Resource audiences must not contain duplicates.")
        return value


class SavePromptDefinitionRequest(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=64)]
    description: Annotated[str, Field(max_length=300)] = ""
    template: Annotated[str, Field(min_length=1, max_length=50_000)]
    arguments: Annotated[list[PromptArgumentDefinition], Field(max_length=32)] = Field(
        default_factory=list
    )

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", normalized):
            raise ValueError("Prompt names must start with a letter and use only letters, numbers, underscores, or hyphens.")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("template")
    @classmethod
    def validate_template_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Prompt template must not be blank.")
        return _validate_workspace_value_placeholders(value)

    @model_validator(mode="after")
    def validate_arguments_and_placeholders(self) -> "SavePromptDefinitionRequest":
        argument_names = [argument.name for argument in self.arguments]
        if len(argument_names) != len(set(argument_names)):
            raise ValueError("Argument names must be unique.")

        matches = list(_PROMPT_PLACEHOLDER.finditer(self.template))
        unmatched_template = _PROMPT_PLACEHOLDER.sub("", self.template)
        if "{{" in unmatched_template or "}}" in unmatched_template:
            raise ValueError("Use placeholders in the form {{argument_name}}.")

        placeholder_names = {match.group(1) for match in matches}
        unknown_names = placeholder_names - set(argument_names)
        if unknown_names:
            raise ValueError(
                f"Define prompt arguments for these placeholders: {', '.join(sorted(unknown_names))}."
            )
        unused_names = set(argument_names) - placeholder_names
        if unused_names:
            raise ValueError(
                f"Use these prompt arguments in the template: {', '.join(sorted(unused_names))}."
            )
        return self


class SecretRecord(BaseModel):
    id: str
    name: str
    server_id: str | None
    server_name: str | None
    created_at: datetime


class SecretRegistryPage(BaseModel):
    items: list[SecretRecord]
    page: int
    page_size: Literal[10, 25, 50]
    total: int
    total_pages: int


class CreateSecretRequest(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=100)]

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Secret name must contain at least one non-whitespace character.")
        return normalized


class CreatedSecret(SecretRecord):
    value: str


class WorkspaceConfigValueRecord(BaseModel):
    id: str
    name: str
    kind: Literal["variable", "secret"]
    value: str | None
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class WorkspaceConfigValuePage(BaseModel):
    items: list[WorkspaceConfigValueRecord]
    page: int
    page_size: Literal[10, 25, 50]
    total: int
    total_pages: int


class SaveWorkspaceConfigValueRequest(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=128)]
    kind: Literal["variable", "secret"]
    value: Annotated[str, Field(min_length=1, max_length=10_000)]

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", normalized):
            raise ValueError("Names must be valid environment variable identifiers.")
        if normalized.upper() in {
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "FTP_PROXY",
            "NO_PROXY",
            "PATH",
            "HOME",
        } or normalized.upper().startswith(("PYTHON", "LD_", "DYLD_")):
            raise ValueError("This name is reserved by the tool runtime.")
        return normalized

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value must not be blank.")
        if "\x00" in value:
            raise ValueError("Value must not contain a null character.")
        return value


class RegisterRequest(BaseModel):
    email: str
    password: Annotated[str, Field(min_length=12, max_length=128)]
    display_name: Annotated[str, Field(min_length=1, max_length=100)]
    workspace_name: Annotated[str | None, Field(max_length=100)] = None
    invite_token: Annotated[str | None, Field(max_length=128)] = None

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Display name must contain at least one non-whitespace character.")
        return normalized

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        from email_validator import EmailNotValidError, validate_email

        try:
            return validate_email(value.strip(), check_deliverability=False).normalized.lower()
        except EmailNotValidError as exc:
            raise ValueError("Enter a valid email address.") from exc

    @field_validator("workspace_name")
    @classmethod
    def normalize_workspace_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Workspace name must not be blank.")
        return normalized


class LoginRequest(BaseModel):
    email: str
    password: Annotated[str, Field(min_length=1, max_length=128)]

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        from email_validator import EmailNotValidError, validate_email

        try:
            return validate_email(value.strip(), check_deliverability=False).normalized.lower()
        except EmailNotValidError as exc:
            raise ValueError("Enter a valid email address.") from exc


class UpdateProfileRequest(BaseModel):
    display_name: Annotated[str, Field(min_length=1, max_length=100)]

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Display name must contain at least one non-whitespace character.")
        return normalized


class AuthStatus(BaseModel):
    workspace_initialized: bool


class AuthUser(BaseModel):
    id: str
    email: str
    display_name: str
    workspace_id: str
    workspace_name: str
    role: Literal["owner", "member"]


class WorkspaceRecord(BaseModel):
    id: str
    name: str
    role: Literal["owner", "member"]


class WorkspaceSummary(BaseModel):
    server_count: Annotated[int, Field(ge=0)]
    tool_count: Annotated[int, Field(ge=0)]
    active_tool_count: Annotated[int, Field(ge=0)]
    prompt_count: Annotated[int, Field(ge=0)]
    secret_count: Annotated[int, Field(ge=0)]
    member_count: Annotated[int, Field(ge=0)]


class WorkspaceMemberRecord(BaseModel):
    user_id: str
    email: str
    role: Literal["owner", "member"]
    joined_at: datetime


class WorkspaceMemberPage(BaseModel):
    items: list[WorkspaceMemberRecord]
    page: int
    page_size: Literal[10, 25, 50]
    total: int
    total_pages: int


class WorkspaceInviteRecord(BaseModel):
    id: str
    created_at: datetime
    expires_at: datetime
    invite_url: str | None = None


class CreatedWorkspaceInvite(WorkspaceInviteRecord):
    token: str


class InvitePreview(BaseModel):
    workspace_name: str
    expires_at: datetime

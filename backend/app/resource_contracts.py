from dataclasses import dataclass
from datetime import datetime, timezone
import keyword
import re
from typing import Literal
from urllib.parse import urlsplit

from app.models import MCPResourceDefinition
from app.schemas import SaveResourceDefinitionRequest

_URI_PARAMETER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_CONTENT_PARAMETER = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
_URI_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*\Z")


@dataclass(frozen=True)
class ResourceContract:
    uri: str
    name: str
    description: str
    mime_type: str
    content_kind: Literal["text", "binary"]
    content: str | None
    object_key: str | None
    size_bytes: int | None
    sha256: str | None
    audience: tuple[str, ...]
    priority: float | None
    last_modified: str
    uri_parameters: tuple[str, ...]


def resource_contract_from_request(
    request: SaveResourceDefinitionRequest,
) -> ResourceContract:
    uri = request.uri
    uri_parameters = tuple(_URI_PARAMETER.findall(uri))
    normalized_uri = _URI_PARAMETER.sub("resource-value", uri)
    if "{" in normalized_uri or "}" in normalized_uri:
        raise ValueError("Use URI parameters in the form {parameter_name}.")

    scheme = urlsplit(normalized_uri).scheme
    if not _URI_SCHEME.fullmatch(scheme):
        raise ValueError("Resource URI must be absolute and include a valid scheme.")
    if any(character.isspace() or ord(character) < 0x20 for character in uri):
        raise ValueError("Resource URI cannot contain whitespace or control characters.")

    if len(uri_parameters) != len(set(uri_parameters)):
        raise ValueError("Resource URI parameter names must be unique.")
    if any(keyword.iskeyword(parameter) for parameter in uri_parameters):
        raise ValueError("Resource URI parameters cannot be Python keywords.")

    content_parameters = set(_CONTENT_PARAMETER.findall(request.content))
    uri_parameter_names = set(uri_parameters)
    if content_parameters != uri_parameter_names:
        missing = uri_parameter_names - content_parameters
        unused = content_parameters - uri_parameter_names
        details = []
        if missing:
            details.append(f"Use these URI parameters in the content: {', '.join(sorted(missing))}.")
        if unused:
            details.append(f"Remove undefined content parameters: {', '.join(sorted(unused))}.")
        raise ValueError(" ".join(details))

    return ResourceContract(
        uri=uri,
        name=request.name,
        description=request.description,
        mime_type=request.mime_type,
        content_kind="text",
        content=request.content,
        object_key=None,
        size_bytes=None,
        sha256=None,
        audience=tuple(request.audience),
        priority=request.priority,
        last_modified=datetime.now(timezone.utc).isoformat(),
        uri_parameters=uri_parameters,
    )


def resource_contract_from_record(
    definition: MCPResourceDefinition,
) -> ResourceContract:
    request = SaveResourceDefinitionRequest(
        uri=definition.uri,
        name=definition.name,
        description=definition.description,
        mime_type=definition.mime_type,
        content=definition.content or "",
        audience=definition.audience,
        priority=definition.priority,
    )
    contract = resource_contract_from_request(request)
    if definition.content_kind == "binary" and contract.uri_parameters:
        raise ValueError("Binary resources must use static URIs without parameters.")
    last_modified = definition.updated_at
    if last_modified.tzinfo is None:
        last_modified = last_modified.replace(tzinfo=timezone.utc)
    return ResourceContract(
        uri=contract.uri,
        name=contract.name,
        description=contract.description,
        mime_type=contract.mime_type,
        content_kind=definition.content_kind,
        content=definition.content,
        object_key=definition.object_key,
        size_bytes=definition.size_bytes,
        sha256=definition.sha256,
        audience=contract.audience,
        priority=contract.priority,
        last_modified=last_modified.isoformat(),
        uri_parameters=contract.uri_parameters,
    )

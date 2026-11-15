from dataclasses import dataclass

from pydantic import ValidationError

from app.models import MCPPromptDefinition
from app.schemas import PromptArgumentDefinition, SavePromptDefinitionRequest


@dataclass(frozen=True)
class PromptArgumentContract:
    name: str
    description: str
    required: bool
    default_value: str | None


@dataclass(frozen=True)
class PromptContract:
    name: str
    description: str
    template: str
    arguments: tuple[PromptArgumentContract, ...]


def prompt_contract_from_request(
    request: SavePromptDefinitionRequest,
) -> PromptContract:
    return PromptContract(
        name=request.name,
        description=request.description,
        template=request.template,
        arguments=tuple(
            PromptArgumentContract(
                name=argument.name,
                description=argument.description,
                required=argument.required,
                default_value=argument.default_value,
            )
            for argument in request.arguments
        ),
    )


def prompt_contract_from_record(
    definition: MCPPromptDefinition,
) -> PromptContract:
    try:
        request = SavePromptDefinitionRequest.model_validate(
            {
                "name": definition.name,
                "description": definition.description,
                "template": definition.template,
                "arguments": definition.arguments,
            }
        )
    except ValidationError as exc:
        raise ValueError(
            f"Stored prompt {definition.id} is invalid and cannot be restored."
        ) from exc
    return prompt_contract_from_request(request)


def prompt_arguments_as_records(
    arguments: tuple[PromptArgumentDefinition, ...] | list[PromptArgumentDefinition],
) -> list[dict[str, object]]:
    return [argument.model_dump() for argument in arguments]

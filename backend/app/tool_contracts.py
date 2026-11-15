import ast
from dataclasses import dataclass
import inspect
import re
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, create_model

MAX_TOOL_SOURCE_BYTES = 20_000
MAX_TOOL_PARAMETERS = 64
_TOOL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_ANNOTATION_TYPES: dict[str, Any] = {
    "Any": Any,
    "typing.Any": Any,
    "bool": bool,
    "dict": dict[str, Any],
    "float": float,
    "int": int,
    "list": list[Any],
    "str": str,
}


@dataclass(frozen=True)
class ToolParameter:
    name: str
    annotation: Any
    default: Any = inspect.Parameter.empty


@dataclass(frozen=True)
class ToolContract:
    name: str
    description: str
    parameters: tuple[ToolParameter, ...]
    input_schema: dict[str, Any]
    return_annotation: Any


def _annotation_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_annotation_name(node.value)}.{node.attr}"
    raise ValueError("Only built-in and typing annotations are supported.")


def _parse_annotation(node: ast.expr) -> Any:
    if isinstance(node, ast.Constant) and node.value is None:
        return type(None)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return Union[_parse_annotation(node.left), _parse_annotation(node.right)]
    if isinstance(node, ast.Subscript):
        name = _annotation_name(node.value)
        raw_args = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        if name in {"Literal", "typing.Literal"}:
            values = tuple(ast.literal_eval(item) for item in raw_args)
            if not values or not all(isinstance(item, (str, int, float, bool)) for item in values):
                raise ValueError("Literal annotations must contain scalar values.")
            return Literal[values]
        origins: dict[str, Any] = {
            "list": list,
            "List": list,
            "typing.List": list,
            "dict": dict,
            "Dict": dict,
            "typing.Dict": dict,
            "tuple": tuple,
            "Tuple": tuple,
            "typing.Tuple": tuple,
            "Union": Union,
            "typing.Union": Union,
            "Optional": Union,
            "typing.Optional": Union,
        }
        origin = origins.get(name)
        if origin is None:
            raise ValueError(f"Unsupported annotation: {name}.")
        args = tuple(_parse_annotation(item) for item in raw_args)
        if name in {"Optional", "typing.Optional"}:
            if len(args) != 1:
                raise ValueError("Optional annotations require one type.")
            args = (*args, type(None))
        elif origin is list and len(args) != 1:
            raise ValueError("List annotations require one item type.")
        elif origin is dict and len(args) != 2:
            raise ValueError("Dict annotations require key and value types.")
        elif origin is tuple and len(args) not in {1, 2}:
            raise ValueError("Tuple annotations require one or two item types.")
        elif origin is Union and len(args) < 2:
            raise ValueError("Union annotations require at least two types.")
        return origin[args]
    name = _annotation_name(node)
    if name in _ANNOTATION_TYPES:
        return _ANNOTATION_TYPES[name]
    if name in {"None", "NoneType", "type(None)"}:
        return type(None)
    raise ValueError(f"Unsupported annotation: {name}.")


def _parse_default(node: ast.expr) -> Any:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("Parameter defaults must be literal JSON values.") from exc
    if not isinstance(value, (str, int, float, bool, list, dict, type(None))):
        raise ValueError("Parameter defaults must be literal JSON values.")
    return value


def _schema_for_parameters(
    name: str,
    parameters: tuple[ToolParameter, ...],
) -> dict[str, Any]:
    fields = {
        f"argument_{index}": (
            parameter.annotation,
            Field(
                default=(
                    ...
                    if parameter.default is inspect.Parameter.empty
                    else parameter.default
                ),
                alias=parameter.name,
                title=parameter.name,
            ),
        )
        for index, parameter in enumerate(parameters)
    }
    arguments_model: type[BaseModel] = create_model(
        f"{name}Arguments",
        __config__=ConfigDict(populate_by_name=True),
        **fields,
    )
    return arguments_model.model_json_schema()


def parse_tool_source(
    source: str,
    *,
    max_source_bytes: int = MAX_TOOL_SOURCE_BYTES,
    max_parameters: int = MAX_TOOL_PARAMETERS,
) -> ToolContract:
    if not source.strip():
        raise ValueError("Enter a Python function.")
    if len(source.encode("utf-8")) > max_source_bytes:
        raise ValueError(f"Tool source must be {max_source_bytes} bytes or less.")
    try:
        module = ast.parse(source)
    except (SyntaxError, RecursionError) as exc:
        if isinstance(exc, RecursionError):
            raise ValueError("Python source is nested too deeply to validate.") from exc
        raise ValueError(f"Python syntax error on line {exc.lineno}: {exc.msg}") from exc

    functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for statement in module.body:
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(statement)
            continue
        raise ValueError(
            "Only imports and one top-level function definition are allowed."
        )
    if len(functions) != 1:
        raise ValueError("Define exactly one top-level Python function.")

    function = functions[0]
    if function.decorator_list:
        raise ValueError("Decorators are not supported.")
    if not _TOOL_NAME.fullmatch(function.name) or "__" in function.name:
        raise ValueError("Use a tool name with letters, numbers, and underscores.")
    description = ast.get_docstring(function) or ""
    if not description.strip():
        raise ValueError("Add a docstring describing what the tool does.")
    if function.args.posonlyargs or function.args.vararg or function.args.kwarg:
        raise ValueError("Use named parameters; *args and **kwargs are not supported.")
    if function.args.kwonlyargs:
        raise ValueError("Keyword-only parameters are not supported.")

    positional = function.args.args
    if len(positional) > max_parameters:
        raise ValueError(f"Tools may define at most {max_parameters} parameters.")
    defaults = [inspect.Parameter.empty] * (len(positional) - len(function.args.defaults))
    defaults.extend(_parse_default(item) for item in function.args.defaults)
    parameters: list[ToolParameter] = []
    for argument, default in zip(positional, defaults, strict=True):
        if argument.arg in {"self", "cls"} or argument.annotation is None:
            raise ValueError(f"Parameter '{argument.arg}' must have a type annotation.")
        if argument.arg.startswith("_"):
            raise ValueError("Parameter names must not start with an underscore.")
        parameters.append(
            ToolParameter(
                name=argument.arg,
                annotation=_parse_annotation(argument.annotation),
                default=default,
            )
        )
    parameter_tuple = tuple(parameters)
    for parameter in parameter_tuple:
        if parameter.default is inspect.Parameter.empty:
            continue
        try:
            TypeAdapter(parameter.annotation).validate_python(
                parameter.default,
                strict=True,
            )
        except ValidationError as exc:
            raise ValueError(
                f"Default value for '{parameter.name}' does not match its annotation."
            ) from exc
    return_annotation = (
        _parse_annotation(function.returns)
        if function.returns is not None
        else Any
    )
    schema = _schema_for_parameters(function.name, parameter_tuple)
    return ToolContract(
        name=function.name,
        description=description.strip(),
        parameters=parameter_tuple,
        input_schema=schema,
        return_annotation=return_annotation,
    )


def signature_for_tool(contract: ToolContract) -> inspect.Signature:
    return inspect.Signature(
        parameters=[
            inspect.Parameter(
                parameter.name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=parameter.default,
                annotation=parameter.annotation,
            )
            for parameter in contract.parameters
        ],
        return_annotation=contract.return_annotation,
    )

import math
import os
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class SandboxLimits:
    cpu_limit: float
    memory_mib: int
    pids_limit: int
    timeout_seconds: int
    tmpfs_mib: int
    max_concurrent_runs: int
    queue_timeout_seconds: int
    max_source_bytes: int
    max_parameters: int
    max_input_bytes: int
    max_output_bytes: int
    proxy_max_connections: int
    proxy_idle_timeout_seconds: int
    proxy_max_tunnel_bytes: int
    proxy_max_header_bytes: int

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "SandboxLimits":
        env = os.environ if environment is None else environment
        return cls(
            cpu_limit=_positive_float(env, "TOOL_SANDBOX_CPU_LIMIT", 1.0),
            memory_mib=_positive_int(env, "TOOL_SANDBOX_MEMORY_MIB", 256),
            pids_limit=_positive_int(env, "TOOL_SANDBOX_PIDS_LIMIT", 32),
            timeout_seconds=_positive_int(env, "TOOL_SANDBOX_TIMEOUT_SECONDS", 10),
            tmpfs_mib=_positive_int(env, "TOOL_SANDBOX_TMPFS_MIB", 32),
            max_concurrent_runs=_positive_int(
                env, "TOOL_SANDBOX_MAX_CONCURRENT_RUNS", 4
            ),
            queue_timeout_seconds=_positive_int(
                env, "TOOL_SANDBOX_QUEUE_TIMEOUT_SECONDS", 2
            ),
            max_source_bytes=_positive_int(
                env, "TOOL_SANDBOX_MAX_SOURCE_BYTES", 20_000
            ),
            max_parameters=_positive_int(
                env, "TOOL_SANDBOX_MAX_PARAMETERS", 64
            ),
            max_input_bytes=_positive_int(
                env, "TOOL_SANDBOX_MAX_INPUT_BYTES", 65_536
            ),
            max_output_bytes=_positive_int(
                env, "TOOL_SANDBOX_MAX_OUTPUT_BYTES", 262_144
            ),
            proxy_max_connections=_positive_int(
                env, "TOOL_SANDBOX_PROXY_MAX_CONNECTIONS", 128
            ),
            proxy_idle_timeout_seconds=_positive_int(
                env, "TOOL_SANDBOX_PROXY_IDLE_TIMEOUT_SECONDS", 15
            ),
            proxy_max_tunnel_bytes=_positive_int(
                env, "TOOL_SANDBOX_PROXY_MAX_TUNNEL_BYTES", 10_485_760
            ),
            proxy_max_header_bytes=_positive_int(
                env, "TOOL_SANDBOX_PROXY_MAX_HEADER_BYTES", 65_536
            ),
        )


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    value = env.get(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer.") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return parsed


def _positive_float(env: Mapping[str, str], name: str, default: float) -> float:
    value = env.get(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive finite number.") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be a positive finite number.")
    return parsed

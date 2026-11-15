import pytest

from app.sandbox_limits import SandboxLimits


def test_sandbox_limits_load_overrides_and_defaults():
    limits = SandboxLimits.from_environment(
        {
            "TOOL_SANDBOX_CPU_LIMIT": "1.5",
            "TOOL_SANDBOX_MEMORY_MIB": "512",
            "TOOL_SANDBOX_TIMEOUT_SECONDS": "7",
        }
    )

    assert limits.cpu_limit == 1.5
    assert limits.memory_mib == 512
    assert limits.timeout_seconds == 7
    assert limits.pids_limit == 32
    assert limits.max_output_bytes == 262_144


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("TOOL_SANDBOX_TIMEOUT_SECONDS", "0"),
        ("TOOL_SANDBOX_MEMORY_MIB", "-1"),
        ("TOOL_SANDBOX_CPU_LIMIT", "nan"),
        ("TOOL_SANDBOX_CPU_LIMIT", "inf"),
        ("TOOL_SANDBOX_MAX_OUTPUT_BYTES", "not-a-number"),
    ],
)
def test_sandbox_limits_reject_invalid_values(name, value):
    with pytest.raises(ValueError, match=name):
        SandboxLimits.from_environment({name: value})

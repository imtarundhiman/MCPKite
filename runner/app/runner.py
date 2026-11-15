import asyncio
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any


def main(path: str) -> int:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        os.environ.update(payload["environment"])
        namespace: dict[str, Any] = {"__name__": "__tool__"}
        exec(compile(payload["source"], "<mcp-tool>", "exec"), namespace, namespace)
        function = namespace[payload["function_name"]]
        result = function(**payload["arguments"])
        if inspect.isawaitable(result):
            result = asyncio.run(result)
        encoded = json.dumps(
            result,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        print(f"__MCP_TOOL_RESULT__{encoded}", flush=True)
        return 0
    except BaseException:
        print("__MCP_TOOL_ERROR__", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))

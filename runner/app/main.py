import asyncio
import hmac
import io
import json
import logging
import os
import tarfile
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

import docker
from docker.errors import DockerException, NotFound
from fastapi import FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel

from shared.sandbox_limits import SandboxLimits

logger = logging.getLogger("tool_runner")
SANDBOX_IMAGE = os.getenv("TOOL_SANDBOX_IMAGE", "webmcp-tool-sandbox:local")
PROXY_IMAGE = os.getenv("TOOL_SANDBOX_PROXY_IMAGE", "webmcp-egress-proxy:local")
EGRESS_NETWORK = os.getenv(
    "TOOL_SANDBOX_EGRESS_NETWORK", "webmcp_tool_sandbox_egress"
)
TOKEN_FILE = Path(
    os.getenv("TOOL_RUNNER_TOKEN_FILE", "/run/secrets/tool-runner/token")
)


class ExecuteRequest(BaseModel):
    source: str
    function_name: str
    arguments: dict[str, Any]
    environment: dict[str, str]


class ExecuteResponse(BaseModel):
    result: Any


def _read_token() -> str:
    try:
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError("The runner authentication token is unavailable.") from exc
    if len(token.encode("utf-8")) < 32:
        raise RuntimeError("The runner authentication token is invalid.")
    return token


def _build_input_archive(payload: bytes) -> bytes:
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as tar:
        info = tarfile.TarInfo("request.json")
        info.size = len(payload)
        info.mode = 0o444
        tar.addfile(info, io.BytesIO(payload))
    return archive.getvalue()


def _container_options(
    limits: SandboxLimits,
    *,
    proxy: bool,
) -> dict[str, Any]:
    memory_mib = max(64, min(limits.memory_mib, 128)) if proxy else limits.memory_mib
    tmpfs_mib = max(8, min(limits.tmpfs_mib, 32)) if proxy else limits.tmpfs_mib
    return {
        "user": "65532:65532",
        "read_only": True,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "pids_limit": max(16, min(limits.pids_limit, 64)) if proxy else limits.pids_limit,
        "mem_limit": f"{memory_mib}m",
        "nano_cpus": int(limits.cpu_limit * 1_000_000_000),
        "tmpfs": {
            "/tmp": f"rw,noexec,nosuid,nodev,size={tmpfs_mib}m",
        },
        "log_config": {
            "type": "local",
            "config": {"max-size": "512k", "max-file": "2"},
        },
        "detach": True,
        "remove": False,
    }


def _wait_for_proxy(proxy: docker.models.containers.Container) -> None:
    for _ in range(50):
        proxy.reload()
        if proxy.status != "running":
            raise RuntimeError("The egress proxy did not start.")
        if b"egress proxy ready" in proxy.logs(stdout=True, stderr=False, tail=10):
            return
        time.sleep(0.1)
    raise RuntimeError("The egress proxy did not become ready.")


def _removal_in_progress(error: DockerException) -> bool:
    return (
        getattr(error, "status_code", None) == 409
        and "already in progress" in str(error)
    )


def _not_running_conflict(error: DockerException) -> bool:
    return (
        getattr(error, "status_code", None) == 409
        and "is not running" in str(error)
    )


def _run_container(
    run_id: str,
    payload: bytes,
    limits: SandboxLimits,
    docker_client: docker.DockerClient,
) -> Any:
    network_name = f"tool-call-{run_id}"
    labels = {"com.webmcp.managed": "tool-sandbox", "com.webmcp.run": run_id}
    network = None
    proxy = None
    input_volume = None
    input_container = None
    sandbox = None
    try:
        network = docker_client.networks.create(
            network_name,
            driver="bridge",
            internal=True,
            labels=labels,
        )
        proxy_options = _container_options(limits, proxy=True)
        proxy_options.update(
            {
                "name": f"tool-proxy-{run_id}",
                "network": EGRESS_NETWORK,
                "environment": {
                    "PROXY_MAX_CONNECTIONS": str(limits.proxy_max_connections),
                    "PROXY_IDLE_TIMEOUT_SECONDS": str(
                        limits.proxy_idle_timeout_seconds
                    ),
                    "PROXY_MAX_TUNNEL_BYTES": str(limits.proxy_max_tunnel_bytes),
                    "PROXY_MAX_HEADER_BYTES": str(limits.proxy_max_header_bytes),
                },
                "labels": labels,
            }
        )
        proxy_options.pop("detach")
        proxy_options.pop("remove")
        proxy = docker_client.containers.create(PROXY_IMAGE, **proxy_options)
        proxy.start()
        network.connect(proxy, aliases=["sandbox-egress"])
        _wait_for_proxy(proxy)

        input_volume = docker_client.volumes.create(
            name=f"tool-input-{run_id}",
            labels=labels,
        )
        input_options = _container_options(limits, proxy=False)
        input_options.update(
            {
                "name": f"tool-input-writer-{run_id}",
                "user": "0:0",
                "read_only": False,
                "entrypoint": ["/bin/sleep"],
                "command": ["60"],
                "network_disabled": True,
                "volumes": {
                    input_volume.name: {"bind": "/input", "mode": "rw"},
                },
                "labels": labels,
            }
        )
        input_options.pop("detach")
        input_options.pop("remove")
        input_container = docker_client.containers.create(
            SANDBOX_IMAGE,
            **input_options,
        )
        input_container.start()
        if not input_container.put_archive("/input", _build_input_archive(payload)):
            raise RuntimeError("Could not provide tool input to the sandbox.")
        input_container.remove(force=True)
        input_container = None

        sandbox_options = _container_options(limits, proxy=False)
        sandbox_options.update(
            {
                "name": f"tool-sandbox-{run_id}",
                "network": network.name,
                "command": ["/run-input/request.json"],
                "volumes": {
                    input_volume.name: {"bind": "/run-input", "mode": "ro"},
                },
                "environment": {
                    "HTTP_PROXY": "http://sandbox-egress:3128",
                    "HTTPS_PROXY": "http://sandbox-egress:3128",
                    "http_proxy": "http://sandbox-egress:3128",
                    "https_proxy": "http://sandbox-egress:3128",
                    "NO_PROXY": "",
                    "no_proxy": "",
                },
                "labels": labels,
            }
        )
        sandbox_options.pop("detach")
        sandbox_options.pop("remove")
        sandbox = docker_client.containers.create(SANDBOX_IMAGE, **sandbox_options)
        sandbox.start()
        try:
            result = sandbox.wait(timeout=limits.timeout_seconds + 15)
        except Exception as exc:
            try:
                sandbox.kill()
            except DockerException:
                logger.warning("Could not stop timed-out sandbox %s", run_id)
            raise TimeoutError from exc

        logs = sandbox.logs(stdout=True, stderr=True, tail=10_000)
        if len(logs) > limits.max_output_bytes + 16_384:
            raise ValueError("The tool produced too much output.")
        if result.get("StatusCode") != 0:
            raise ValueError("The tool failed during execution.")
        marker, _, result_line = logs.rpartition(b"__MCP_TOOL_RESULT__")
        del marker
        if not result_line:
            raise ValueError("The tool did not return a result.")
        result_value = json.loads(result_line.splitlines()[0])
        encoded_result = json.dumps(
            result_value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded_result) > limits.max_output_bytes:
            raise ValueError("The tool result exceeds the output limit.")
        return result_value
    finally:
        for container in (sandbox, input_container, proxy):
            if container is not None:
                try:
                    container.remove(force=True, v=True)
                except NotFound:
                    pass
                except DockerException as exc:
                    if _removal_in_progress(exc):
                        continue
                    logger.exception("Could not remove sandbox container for run %s", run_id)
        if input_volume is not None:
            try:
                input_volume.remove(force=True)
            except NotFound:
                pass
            except DockerException:
                logger.exception("Could not remove tool input volume for run %s", run_id)
        if network is not None:
            try:
                network.remove()
            except NotFound:
                pass
            except DockerException:
                logger.exception("Could not remove sandbox network for run %s", run_id)


def _terminate_run(run_id: str, docker_client: docker.DockerClient) -> None:
    labels = {"com.webmcp.run": run_id}
    for container in docker_client.containers.list(
        all=True,
        filters={"label": [f"{key}={value}" for key, value in labels.items()]},
    ):
        try:
            if container.status == "running":
                container.kill()
        except DockerException as exc:
            if not _not_running_conflict(exc):
                logger.exception("Could not stop sandbox container for run %s", run_id)
                continue
        try:
            container.remove(force=True, v=True)
        except NotFound:
            pass
        except DockerException as exc:
            if _removal_in_progress(exc):
                continue
            logger.exception("Could not terminate sandbox container for run %s", run_id)
    for network in docker_client.networks.list(
        filters={"label": [f"{key}={value}" for key, value in labels.items()]}
    ):
        try:
            network.remove()
        except NotFound:
            pass
        except DockerException:
            logger.exception("Could not terminate sandbox network for run %s", run_id)
    for volume in docker_client.volumes.list(
        filters={
            "label": [f"{key}={value}" for key, value in labels.items()],
        }
    ):
        try:
            volume.remove(force=True)
        except NotFound:
            pass
        except DockerException:
            logger.exception("Could not terminate sandbox volume for run %s", run_id)


def _cleanup_stale_runs(docker_client: docker.DockerClient) -> None:
    for container in docker_client.containers.list(
        all=True,
        filters={"label": "com.webmcp.managed=tool-sandbox"},
    ):
        try:
            if container.status == "running":
                container.kill()
            container.remove(force=True, v=True)
        except NotFound:
            pass
        except DockerException:
            logger.exception("Could not clean up stale sandbox container.")
    for network in docker_client.networks.list(
        filters={"label": "com.webmcp.managed=tool-sandbox"}
    ):
        try:
            network.remove()
        except NotFound:
            pass
        except DockerException:
            logger.exception("Could not clean up stale sandbox network.")
    for volume in docker_client.volumes.list(
        filters={"label": "com.webmcp.managed=tool-sandbox"}
    ):
        try:
            volume.remove(force=True)
        except NotFound:
            pass
        except DockerException:
            logger.exception("Could not clean up stale sandbox volume.")


def create_app() -> FastAPI:
    limits = SandboxLimits.from_environment()
    token = _read_token()
    app = FastAPI(title="Tool Sandbox Runner")
    app.state.limits = limits
    app.state.token = token
    app.state.docker = None
    app.state.slots = asyncio.Semaphore(limits.max_concurrent_runs)

    @app.on_event("startup")
    async def open_docker() -> None:
        client = docker.from_env(timeout=max(limits.timeout_seconds + 20, 30))
        try:
            await asyncio.to_thread(client.ping)
            await asyncio.to_thread(client.images.get, SANDBOX_IMAGE)
            await asyncio.to_thread(client.images.get, PROXY_IMAGE)
            await asyncio.to_thread(client.networks.get, EGRESS_NETWORK)
            await asyncio.to_thread(_cleanup_stale_runs, client)
        except DockerException:
            client.close()
            logger.exception("Tool runner could not initialize Docker resources.")
            raise
        app.state.docker = client

    @app.on_event("shutdown")
    async def close_docker() -> None:
        if app.state.docker is not None:
            await asyncio.to_thread(app.state.docker.close)

    @app.get("/health")
    async def health() -> dict[str, str]:
        if app.state.docker is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Docker resources are not ready.",
            )
        return {"status": "ok"}

    @app.post("/execute", response_model=ExecuteResponse)
    async def execute(
        body: ExecuteRequest,
        authorization: str = Header(default=""),
    ) -> ExecuteResponse:
        scheme, separator, supplied_token = authorization.partition(" ")
        if (
            scheme.lower() != "bearer"
            or not separator
            or not hmac.compare_digest(supplied_token, app.state.token)
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Runner authentication failed.",
            )
        limits: SandboxLimits = app.state.limits
        source_bytes = body.source.encode("utf-8")
        try:
            arguments_bytes = json.dumps(
                body.arguments,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Tool arguments must be JSON values.",
            ) from exc
        environment_bytes = json.dumps(
            body.environment,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(source_bytes) > limits.max_source_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Tool source exceeds the configured limit.",
            )
        if len(arguments_bytes) > limits.max_input_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Tool arguments exceed the configured limit.",
            )
        if len(environment_bytes) > limits.max_input_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Workspace values exceed the configured limit.",
            )
        try:
            payload = json.dumps(
                {
                    "source": body.source,
                    "function_name": body.function_name,
                    "arguments": body.arguments,
                    "environment": body.environment,
                },
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Tool input must contain JSON values.",
            ) from exc
        if len(payload) > (
            limits.max_source_bytes + limits.max_input_bytes * 2 + 4096
        ):
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Tool request exceeds the configured limit.",
            )
        if app.state.docker is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The sandbox runner is not ready.",
            )

        try:
            await asyncio.wait_for(
                app.state.slots.acquire(),
                timeout=limits.queue_timeout_seconds,
            )
        except TimeoutError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="All tool sandboxes are busy.",
            ) from exc
        try:
            run_id = uuid4().hex
            execution = asyncio.create_task(
                asyncio.to_thread(
                    _run_container,
                    run_id,
                    payload,
                    limits,
                    app.state.docker,
                )
            )
            try:
                result = await asyncio.wait_for(
                    asyncio.shield(execution),
                    timeout=limits.timeout_seconds,
                )
            except TimeoutError as exc:
                await asyncio.to_thread(_terminate_run, run_id, app.state.docker)
                try:
                    await asyncio.shield(execution)
                except Exception as cleanup_error:
                    logger.warning(
                        "Timed-out sandbox worker exited with %s.",
                        type(cleanup_error).__name__,
                    )
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail="Tool execution exceeded its time limit.",
                ) from exc
            except asyncio.CancelledError:
                await asyncio.to_thread(_terminate_run, run_id, app.state.docker)
                try:
                    await asyncio.shield(execution)
                except Exception as cleanup_error:
                    logger.warning(
                        "Cancelled sandbox worker exited with %s.",
                        type(cleanup_error).__name__,
                    )
                raise
            except (DockerException, ValueError, RuntimeError, json.JSONDecodeError):
                logger.exception("Sandbox execution failed.")
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Tool execution failed. Check the function and its inputs.",
                )
            return ExecuteResponse(result=result)
        finally:
            app.state.slots.release()

    return app


app = create_app()

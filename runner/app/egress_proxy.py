import asyncio
import ipaddress
import os
import socket
from urllib.parse import urlsplit


MAX_CONNECTIONS = int(os.getenv("PROXY_MAX_CONNECTIONS", "128"))
IDLE_TIMEOUT = int(os.getenv("PROXY_IDLE_TIMEOUT_SECONDS", "15"))
MAX_TUNNEL_BYTES = int(os.getenv("PROXY_MAX_TUNNEL_BYTES", "10485760"))
MAX_HEADER_BYTES = int(os.getenv("PROXY_MAX_HEADER_BYTES", "65536"))


def _allowed_address(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_global
    except ValueError:
        return False


async def _resolve_public(host: str, port: int) -> str:
    loop = asyncio.get_running_loop()
    try:
        records = await asyncio.wait_for(
            loop.getaddrinfo(host, port, type=socket.SOCK_STREAM),
            timeout=IDLE_TIMEOUT,
        )
    except (OSError, TimeoutError) as exc:
        raise ValueError("Destination could not be resolved.") from exc
    addresses = list(dict.fromkeys(record[4][0] for record in records))
    if not addresses or any(not _allowed_address(address) for address in addresses):
        raise ValueError("Destination is not publicly routable.")
    return addresses[0]


async def _read_header(
    reader: asyncio.StreamReader,
    initial: bytes = b"",
) -> tuple[bytes, bytes]:
    data = bytearray(initial)
    while True:
        if data.startswith(b"\r\n"):
            return b"", bytes(data[2:])
        boundary = data.find(b"\r\n\r\n")
        if boundary >= 0:
            if boundary > MAX_HEADER_BYTES:
                raise ValueError("Request headers are too large.")
            return bytes(data[:boundary]), bytes(data[boundary + 4 :])
        if len(data) > MAX_HEADER_BYTES:
            raise ValueError("Request headers are too large.")
        chunk = await asyncio.wait_for(reader.read(4096), timeout=IDLE_TIMEOUT)
        if not chunk:
            raise ValueError("Incomplete HTTP request headers.")
        data.extend(chunk)


async def _copy(
    source: asyncio.StreamReader,
    destination: asyncio.StreamWriter,
    counter: list[int],
) -> None:
    while True:
        chunk = await asyncio.wait_for(source.read(16_384), timeout=IDLE_TIMEOUT)
        if not chunk:
            return
        counter[0] += len(chunk)
        if counter[0] > MAX_TUNNEL_BYTES:
            raise ValueError("Proxy transfer limit exceeded.")
        destination.write(chunk)
        await destination.drain()


async def _relay(
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
    upstream_reader: asyncio.StreamReader,
    upstream_writer: asyncio.StreamWriter,
) -> None:
    counter = [0]
    tasks = [
        asyncio.create_task(_copy(client_reader, upstream_writer, counter)),
        asyncio.create_task(_copy(upstream_reader, client_writer, counter)),
    ]
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    failure = next((task.exception() for task in done if task.exception()), None)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    if failure:
        raise failure


async def _handle_connect(
    target: str,
    initial_data: bytes,
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
) -> None:
    parsed = urlsplit(f"//{target}")
    if parsed.hostname is None or parsed.username or parsed.password:
        raise ValueError("Invalid CONNECT authority.")
    port = parsed.port or 443
    if port != 443:
        raise ValueError("Only HTTPS connections are permitted.")
    address = await _resolve_public(parsed.hostname, port)
    upstream_reader, upstream_writer = await asyncio.wait_for(
        asyncio.open_connection(address, port),
        timeout=IDLE_TIMEOUT,
    )
    client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
    await client_writer.drain()
    if initial_data:
        upstream_writer.write(initial_data)
        await upstream_writer.drain()
    try:
        await _relay(
            client_reader,
            client_writer,
            upstream_reader,
            upstream_writer,
        )
    finally:
        upstream_writer.close()
        await upstream_writer.wait_closed()


async def _handle_http(
    request_line: bytes,
    header: bytes,
    body_prefix: bytes,
    client_reader: asyncio.StreamReader,
    client_writer: asyncio.StreamWriter,
) -> None:
    try:
        method, target, version = request_line.decode("latin-1").strip().split(" ")
        parsed = urlsplit(target)
        if (
            method.upper() not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
            or parsed.scheme.lower() != "http"
            or parsed.hostname is None
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 80}
        ):
            raise ValueError("Only public HTTP and HTTPS destinations are permitted.")
        host = parsed.hostname
        port = 80
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("Invalid HTTP proxy request.") from exc

    address = await _resolve_public(host, port)
    upstream_reader, upstream_writer = await asyncio.wait_for(
        asyncio.open_connection(address, port),
        timeout=IDLE_TIMEOUT,
    )
    header_lines = header.split(b"\r\n")
    content_length = 0
    has_content_length = False
    forwarded_headers: list[bytes] = []
    for line in header_lines:
        if not line:
            continue
        name, separator, value = line.partition(b":")
        if not separator:
            raise ValueError("Malformed HTTP request header.")
        normalized = name.strip().lower()
        if normalized == b"transfer-encoding":
            raise ValueError("Chunked request bodies are not supported.")
        if normalized == b"content-length":
            if has_content_length:
                raise ValueError("Duplicate content length headers are not supported.")
            has_content_length = True
            try:
                content_length = int(value.strip())
            except ValueError as exc:
                raise ValueError("Invalid content length.") from exc
        if normalized in {b"proxy-authorization", b"proxy-connection", b"connection"}:
            continue
        if normalized == b"expect":
            raise ValueError("Expect headers are not supported.")
        forwarded_headers.append(line)
    if content_length < 0 or content_length > MAX_TUNNEL_BYTES:
        raise ValueError("HTTP request body exceeds the transfer limit.")
    forwarded_headers.append(b"Connection: close")
    upstream_writer.write(
        f"{method} {path} {version}\r\n".encode("latin-1")
        + b"\r\n".join(forwarded_headers)
        + b"\r\n\r\n"
    )
    await upstream_writer.drain()
    consumed = min(len(body_prefix), content_length)
    if consumed:
        upstream_writer.write(body_prefix[:consumed])
        await upstream_writer.drain()
    remaining = content_length - consumed
    while remaining:
        chunk = await asyncio.wait_for(
            client_reader.read(min(16_384, remaining)),
            timeout=IDLE_TIMEOUT,
        )
        if not chunk:
            raise ValueError("Incomplete HTTP request body.")
        remaining -= len(chunk)
        upstream_writer.write(chunk)
        await upstream_writer.drain()
    try:
        await _copy(upstream_reader, client_writer, [content_length])
    finally:
        upstream_writer.close()
        await upstream_writer.wait_closed()


async def handle(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    semaphore: asyncio.Semaphore,
) -> None:
    if semaphore.locked():
        writer.close()
        await writer.wait_closed()
        return
    await semaphore.acquire()
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=IDLE_TIMEOUT)
        if not request_line or len(request_line) > MAX_HEADER_BYTES:
            raise ValueError("Invalid proxy request.")
        header, body_prefix = await _read_header(reader)
        method, target, _version = (
            request_line.decode("latin-1").strip().split(" ", 2)
        )
        if method.upper() == "CONNECT":
            await _handle_connect(target, body_prefix, reader, writer)
        else:
            await _handle_http(
                request_line,
                header,
                body_prefix,
                reader,
                writer,
            )
    except (OSError, ValueError, TimeoutError, asyncio.IncompleteReadError):
        try:
            writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
        except OSError:
            pass
    finally:
        semaphore.release()
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass


async def main() -> None:
    semaphore = asyncio.Semaphore(MAX_CONNECTIONS)
    server = await asyncio.start_server(
        lambda reader, writer: handle(reader, writer, semaphore),
        host="0.0.0.0",
        port=3128,
        limit=MAX_HEADER_BYTES + 1,
        backlog=MAX_CONNECTIONS,
    )
    print("egress proxy ready", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())

"""A loopback forward proxy for the HTTP a GDAL service subprocess makes.

libcurl inside GDAL resolves host names and follows redirects itself, and no
GDAL option turns either off. Routed through this proxy, every connection the
subprocess opens, redirect hops included, is resolved once, checked by the
address policy ``validate_url_for_ssrf`` applies, and made to the address that
was checked. HTTPS arrives as ``CONNECT`` and is piped, so TLS stays end to end.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import NamedTuple
from urllib.parse import urlsplit

import structlog

from app.platform.security import SSRFError, SSRFResolutionError, _resolve_and_validate

logger = structlog.stdlib.get_logger(__name__)

_HEAD_TIMEOUT_SECONDS = 30.0
_CONNECT_TIMEOUT_SECONDS = 30.0
_CHUNK_BYTES = 64 * 1024

# Hop-by-hop headers belong to the client's connection with this proxy.
_HOP_HEADERS = frozenset(
    {
        b"connection",
        b"keep-alive",
        b"proxy-authorization",
        b"proxy-connection",
        b"te",
        b"trailer",
        b"upgrade",
    }
)


class ServiceEgress:
    """A running proxy: the address GDAL is given, and whether it refused one."""

    def __init__(self, address: str) -> None:
        self.address = address
        self.refused = False


class _Request(NamedTuple):
    host: str
    port: int
    # The origin-form request to send upstream; None for a CONNECT tunnel.
    forward: bytes | None
    body_length: int


def _reply(status: str) -> bytes:
    return (
        f"HTTP/1.1 {status}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode()
    )


def _parse_head(head: bytes) -> _Request:
    """The destination of a ``CONNECT host:port`` or absolute ``http://`` request.

    Raises ValueError for any other request.
    """
    request_line, *header_lines = head.removesuffix(b"\r\n\r\n").split(b"\r\n")
    method, target, version = request_line.decode("ascii").split(" ")
    if method == "CONNECT":
        authority = urlsplit(f"//{target}")
        if not authority.hostname or authority.port is None:
            raise ValueError("CONNECT needs host:port")
        return _Request(authority.hostname, authority.port, None, 0)

    url = urlsplit(target)
    if url.scheme != "http" or not url.hostname:
        raise ValueError("only absolute http:// requests are forwarded")
    kept: list[bytes] = []
    body_length = 0
    for line in header_lines:
        name, colon, value = line.partition(b":")
        key = name.strip().lower()
        if not colon or key == b"transfer-encoding":
            raise ValueError("unsupported request header")
        if key == b"content-length":
            body_length = int(value)
            if body_length < 0:
                raise ValueError("negative Content-Length")
        if key not in _HOP_HEADERS:
            kept.append(line)
    path = (url.path or "/") + (f"?{url.query}" if url.query else "")
    forward = b"\r\n".join(
        [f"{method} {path} {version}".encode("ascii"), *kept, b"Connection: close"]
    )
    return _Request(url.hostname, url.port or 80, forward + b"\r\n\r\n", body_length)


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(_CHUNK_BYTES):
            writer.write(data)
            await writer.drain()
    except OSError:
        pass  # A reset ends the stream the same way EOF does.
    finally:
        writer.close()


async def _serve(
    egress: ServiceEgress,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    """Relay one client connection to the one destination it names."""
    try:
        head = await asyncio.wait_for(
            reader.readuntil(b"\r\n\r\n"), _HEAD_TIMEOUT_SECONDS
        )
        request = _parse_head(head)
    except (
        ValueError,
        asyncio.IncompleteReadError,
        asyncio.LimitOverrunError,
        TimeoutError,
    ):
        writer.write(_reply("400 Bad Request"))
        return

    try:
        address = await _resolve_and_validate(request.host, request.port)
    except SSRFResolutionError:
        writer.write(_reply("502 Bad Gateway"))
        return
    except SSRFError:
        egress.refused = True
        logger.warning("service egress refused", host=request.host, port=request.port)
        writer.write(_reply("403 Forbidden"))
        return

    try:
        upstream_reader, upstream_writer = await asyncio.wait_for(
            asyncio.open_connection(address, request.port), _CONNECT_TIMEOUT_SECONDS
        )
    except (OSError, TimeoutError):
        writer.write(_reply("502 Bad Gateway"))
        return

    try:
        if request.forward is None:
            writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            await asyncio.gather(
                _pipe(reader, upstream_writer), _pipe(upstream_reader, writer)
            )
            return
        # One request per connection: libcurl reuses a proxy connection across
        # hosts, and a second request must not reach the first host's address.
        upstream_writer.write(request.forward)
        if request.body_length:
            upstream_writer.write(await reader.readexactly(request.body_length))
        await upstream_writer.drain()
        await _pipe(upstream_reader, writer)
    finally:
        upstream_writer.close()


@asynccontextmanager
async def service_egress_proxy() -> AsyncIterator[ServiceEgress]:
    """Listen on a loopback port for the block, relaying only to allowed hosts.

    Hand the yielded proxy to ``gdal_service_safe_env`` and run the subprocess
    inside the block; its connections are refused once the block exits.
    """
    handlers: set[asyncio.Task] = set()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        task = asyncio.current_task()
        handlers.add(task)
        try:
            await _serve(egress, reader, writer)
        except (OSError, asyncio.IncompleteReadError):
            pass  # The client went away mid-request; nothing is left to answer.
        finally:
            writer.close()
            handlers.discard(task)

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    egress = ServiceEgress(f"http://127.0.0.1:{port}")
    try:
        yield egress
    finally:
        server.close()
        server.close_clients()
        for task in handlers:
            task.cancel()
        await asyncio.gather(*handlers, return_exceptions=True)
        await server.wait_closed()

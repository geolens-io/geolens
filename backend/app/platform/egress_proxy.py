"""A loopback forward proxy for the HTTP a GDAL service subprocess makes.

libcurl inside GDAL resolves host names and follows redirects itself, and no
GDAL option turns either off. Routed through this proxy, every connection the
subprocess opens, redirect hops included, is resolved once, checked by the
address policy ``validate_url_for_ssrf`` applies, and made to the address that
was checked. HTTPS arrives as ``CONNECT`` and is piped, so TLS stays end to end.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import NamedTuple
from urllib.parse import urlsplit

import structlog

from app.platform.security import (
    SSRFError,
    SSRFResolutionError,
    _resolve_all_and_validate,
)

logger = structlog.stdlib.get_logger(__name__)

_HEAD_TIMEOUT_SECONDS = 30.0
_CONNECT_TIMEOUT_SECONDS = 30.0
# Per attempt while another checked address remains, so a stalled first
# answer can't spend the caller's whole deadline.
_FALLBACK_CONNECT_TIMEOUT_SECONDS = 5.0
_CHUNK_BYTES = 64 * 1024

# Headers about one side's connection with this proxy, never passed across.
# Expect is dropped too, so an upstream never answers with an interim 100.
_HOP_HEADERS = frozenset(
    {
        b"connection",
        b"expect",
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


class _Idle:
    """When either direction of one relay last moved, and how long it may rest."""

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.touch()

    def touch(self) -> None:
        self.last = time.monotonic()

    def remaining(self) -> float:
        return self.last + self.seconds - time.monotonic()


def _reply(status: str) -> bytes:
    return (
        f"HTTP/1.1 {status}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode()
    )


def _without_hop_headers(lines: list[bytes]) -> list[bytes]:
    return [
        line
        for line in lines
        if line.partition(b":")[0].strip().lower() not in _HOP_HEADERS
    ]


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
    path = (url.path or "/") + (f"?{url.query}" if url.query else "")
    forward = b"\r\n".join(
        [
            f"{method} {path} {version}".encode("ascii"),
            *_without_hop_headers(header_lines),
            b"Connection: close",
        ]
    )
    return _Request(url.hostname, url.port or 80, forward + b"\r\n\r\n", body_length)


async def _pipe(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter, idle: _Idle
) -> None:
    """Copy until EOF, or until neither direction of the relay has moved for
    ``idle.seconds``."""
    try:
        while True:
            try:
                data = await asyncio.wait_for(
                    reader.read(_CHUNK_BYTES), max(idle.remaining(), 0.0)
                )
            except TimeoutError:
                if idle.remaining() <= 0:
                    return
                continue
            if not data:
                return
            idle.touch()
            writer.write(data)
            await asyncio.wait_for(writer.drain(), idle.seconds)
    except (OSError, TimeoutError):
        pass  # A reset or a stalled reader ends the stream the same way EOF does.
    finally:
        writer.close()


async def _relay_response(
    upstream: asyncio.StreamReader, writer: asyncio.StreamWriter, idle: _Idle
) -> None:
    """Relay one response, telling libcurl not to reuse the connection: it
    would send the next request here whatever host that request is for."""
    try:
        head = await asyncio.wait_for(upstream.readuntil(b"\r\n\r\n"), idle.seconds)
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, TimeoutError):
        writer.write(_reply("502 Bad Gateway"))
        return
    status_line, *header_lines = head.removesuffix(b"\r\n\r\n").split(b"\r\n")
    writer.write(
        b"\r\n".join(
            [status_line, *_without_hop_headers(header_lines), b"Connection: close"]
        )
        + b"\r\n\r\n"
    )
    idle.touch()
    await _pipe(upstream, writer, idle)


async def _until_closed(reader: asyncio.StreamReader) -> None:
    """Wait for the client to close, dropping any request it pipelined."""
    while await reader.read(65536):
        pass


async def _connect_first(
    addresses: list[str], port: int
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter] | None:
    """A connection to the first checked address that accepts one, like a
    client falling back from an unreachable AAAA answer to its A answer."""
    for index, address in enumerate(addresses):
        last = index == len(addresses) - 1
        timeout = (
            _CONNECT_TIMEOUT_SECONDS if last else _FALLBACK_CONNECT_TIMEOUT_SECONDS
        )
        try:
            return await asyncio.wait_for(
                asyncio.open_connection(address, port), timeout
            )
        except (OSError, TimeoutError):
            continue
    return None


async def _serve(
    egress: ServiceEgress,
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    idle_seconds: float,
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
        addresses = await _resolve_all_and_validate(request.host, request.port)
    except SSRFResolutionError:
        writer.write(_reply("502 Bad Gateway"))
        return
    except SSRFError:
        egress.refused = True
        # The host comes from the remote service and may carry its credential.
        logger.warning("service connection refused", port=request.port)
        writer.write(_reply("403 Forbidden"))
        return

    upstream = await _connect_first(addresses, request.port)
    if upstream is None:
        writer.write(_reply("502 Bad Gateway"))
        return
    upstream_reader, upstream_writer = upstream

    idle = _Idle(idle_seconds)
    try:
        if request.forward is None:
            writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            await asyncio.gather(
                _pipe(reader, upstream_writer, idle),
                _pipe(upstream_reader, writer, idle),
            )
            return
        # One request per connection, so a second request on it, whatever
        # host it names, never reaches this request's address.
        upstream_writer.write(request.forward)
        if request.body_length:
            body = reader.readexactly(request.body_length)
            upstream_writer.write(await asyncio.wait_for(body, idle_seconds))
        await asyncio.wait_for(upstream_writer.drain(), idle_seconds)
        # libcurl closes its side once it has read the response, so that ends
        # the relay even when the upstream keeps its side open.
        relay = asyncio.ensure_future(_relay_response(upstream_reader, writer, idle))
        client_done = asyncio.ensure_future(_until_closed(reader))
        try:
            await asyncio.wait(
                {relay, client_done}, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            relay.cancel()
            client_done.cancel()
            await asyncio.gather(relay, client_done, return_exceptions=True)
    finally:
        upstream_writer.close()


@asynccontextmanager
async def service_egress_proxy(*, idle_seconds: float) -> AsyncIterator[ServiceEgress]:
    """Listen on a loopback port for the block, relaying only to allowed hosts.

    Hand the yielded proxy to ``gdal_service_safe_env`` and run the subprocess
    inside the block. A relay that moves no bytes for ``idle_seconds`` is
    closed, and every connection closes when the block exits.
    """
    handlers: set[asyncio.Task] = set()
    closing = False

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        task = asyncio.current_task()
        handlers.add(task)
        try:
            if not closing:
                await _serve(egress, reader, writer, idle_seconds)
        except (OSError, asyncio.IncompleteReadError, TimeoutError):
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
        # A handler that has not started yet sees `closing` and returns. The
        # others close their client when cancelled; uvloop's server has no
        # close_clients().
        closing = True
        server.close()
        for task in handlers:
            task.cancel()
        await asyncio.gather(*handlers, return_exceptions=True)
        await server.wait_closed()

"""Every redis-py client still works against a store that has no HELLO.

Redis before 6 and some managed proxies answer HELLO with an error. The fake
server here does the same and serves GET, SET and GETDEL from a dict.
"""

from __future__ import annotations

import socket
import socketserver
import threading
from collections.abc import Iterator

import pytest

from app.platform.cache.redis import RedisCacheProvider
from app.platform.cache.tile_cache import TileCacheProvider
from app.platform.ratelimit_claims import SharedClaimStore
from app.platform.refresh.credentials import RedisCredentialBackend


def _read_command(stream) -> list[bytes] | None:
    header = stream.readline()
    if not header:
        return None
    assert header.startswith(b"*"), header
    parts = []
    for _ in range(int(header[1:])):
        size = int(stream.readline()[1:])
        parts.append(stream.read(size + 2)[:-2])
    return parts


def _bulk(value: bytes | None) -> bytes:
    if value is None:
        return b"$-1\r\n"
    return b"$%d\r\n%s\r\n" % (len(value), value)


class _Resp2OnlyHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        data = self.server.data
        while (command := _read_command(self.rfile)) is not None:
            name = command[0].upper()
            if name == b"HELLO":
                reply = b"-ERR unknown command 'HELLO'\r\n"
            elif name == b"PING":
                reply = b"+PONG\r\n"
            elif name == b"GET":
                reply = _bulk(data.get(command[1]))
            elif name == b"GETDEL":
                reply = _bulk(data.pop(command[1], None))
            elif name == b"SET":
                data[command[1]] = command[2]
                reply = b"+OK\r\n"
            else:
                reply = b"+OK\r\n"
            self.wfile.write(reply)


@pytest.fixture
def resp2_url() -> Iterator[str]:
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Resp2OnlyHandler)
    server.daemon_threads = True
    server.data = {}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"redis://127.0.0.1:{server.server_address[1]}/0"
    server.shutdown()
    server.server_close()


async def test_cache_provider_reads_and_writes(resp2_url: str) -> None:
    cache = RedisCacheProvider(resp2_url)
    await cache.set("k", {"v": 1}, ttl=60)
    assert await cache.get("k") == {"v": 1}
    assert cache._failure_count == 0


async def test_tile_cache_reads_and_writes(resp2_url: str) -> None:
    tiles = TileCacheProvider(resp2_url)
    await tiles.set("tbl", 1, 2, 3, b"tile")
    assert await tiles.get("tbl", 1, 2, 3) == b"tile"


async def test_credential_backend_hands_a_token_over(resp2_url: str) -> None:
    backend = RedisCredentialBackend(resp2_url)
    await backend.put("cred", "secret", 30)
    assert await backend.take("cred") == "secret"


def test_claim_store_records_and_consumes(
    resp2_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.platform import ratelimit_claims

    monkeypatch.setattr(ratelimit_claims, "shared_storage_uri", lambda: resp2_url)
    store = ratelimit_claims._build_store()
    assert isinstance(store, SharedClaimStore)
    assert store.record(("u", "q"), "keyword") is True
    assert store.consume(("u", "q"), "semantic") is True


def test_shared_limiter_storage_speaks_resp2(resp2_url: str) -> None:
    from limits.storage import storage_from_string

    from app.platform.ratelimit import limiter

    storage = storage_from_string(resp2_url, **limiter._storage_options)
    assert storage.check()


def test_fake_server_refuses_hello(resp2_url: str) -> None:
    port = int(resp2_url.rsplit(":", 1)[1].split("/")[0])
    with socket.create_connection(("127.0.0.1", port)) as sock:
        sock.sendall(b"*2\r\n$5\r\nHELLO\r\n$1\r\n3\r\n")
        assert sock.recv(64).startswith(b"-ERR")

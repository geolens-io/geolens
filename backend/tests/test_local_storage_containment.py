"""Regression tests for SEC-026: LocalStorageProvider path-traversal containment.

Without the fix, crafted keys like ``../../etc/passwd``, ``/etc/passwd``, or
keys containing a null byte can escape ``base_dir`` — allowing reads, writes,
and deletes of arbitrary files on the host filesystem.

Each parametrized case exercises ALL SIX IO methods (put, get, get_stream,
get_to_file, delete, exists) so none can be a bypass.

These tests are purely local-filesystem; no database or network required.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.platform.storage.local import LocalStorageProvider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def provider(tmp_path: Path) -> LocalStorageProvider:
    """LocalStorageProvider backed by a fresh temporary base directory."""
    return LocalStorageProvider(base_dir=str(tmp_path))


@pytest.fixture
def sentinel_outside(tmp_path: Path) -> Path:
    """A file that exists OUTSIDE base_dir; used to verify no escape occurs."""
    # tmp_path is the base_dir; create a sibling directory with a sentinel file
    outside_dir = tmp_path.parent / f"outside_{tmp_path.name}"
    outside_dir.mkdir(parents=True, exist_ok=True)
    sentinel = outside_dir / "secret.txt"
    sentinel.write_bytes(b"sensitive data")
    return sentinel


# ---------------------------------------------------------------------------
# Malicious key parametrization
# ---------------------------------------------------------------------------

_MALICIOUS_KEYS = [
    pytest.param("../../etc/passwd", id="dotdot-traversal"),
    pytest.param("../outside/secret.txt", id="dotdot-sibling"),
    pytest.param("/etc/passwd", id="absolute-unix"),
    pytest.param("/tmp/evil", id="absolute-tmp"),
    pytest.param("foo/../../etc/passwd", id="embedded-dotdot"),
    pytest.param("foo\x00bar", id="null-byte"),
]


# ---------------------------------------------------------------------------
# Helper: async generator consumer
# ---------------------------------------------------------------------------


async def _consume_stream(gen) -> bytes:
    """Drain an async iterator into bytes."""
    chunks = []
    async for chunk in gen:
        chunks.append(chunk)
    return b"".join(chunks)


# ---------------------------------------------------------------------------
# SEC-026 regression: malicious keys raise on ALL six IO methods
# ---------------------------------------------------------------------------


class TestLocalStorageContainmentPut:
    """put() must reject traversal / absolute / null-byte keys."""

    @pytest.mark.parametrize("key", _MALICIOUS_KEYS)
    @pytest.mark.asyncio
    async def test_put_raises(self, provider: LocalStorageProvider, key: str):
        with pytest.raises((ValueError, PermissionError, OSError)):
            await provider.put(key, b"evil data")

    @pytest.mark.parametrize("key", _MALICIOUS_KEYS)
    @pytest.mark.asyncio
    async def test_put_no_file_written_outside_base(
        self,
        provider: LocalStorageProvider,
        tmp_path: Path,
        key: str,
        sentinel_outside: Path,
    ):
        """Containment: even if no error (pre-fix), no file escapes base_dir."""
        try:
            await provider.put(key, b"evil data")
        except Exception:
            pass
        # The sentinel outside base_dir must remain unchanged
        if sentinel_outside.exists():
            assert sentinel_outside.read_bytes() == b"sensitive data"


class TestLocalStorageContainmentGet:
    """get() must reject traversal / absolute / null-byte keys."""

    @pytest.mark.parametrize("key", _MALICIOUS_KEYS)
    @pytest.mark.asyncio
    async def test_get_raises(self, provider: LocalStorageProvider, key: str):
        with pytest.raises((ValueError, PermissionError, OSError)):
            await provider.get(key)


class TestLocalStorageContainmentGetStream:
    """get_stream() must reject traversal / absolute / null-byte keys."""

    @pytest.mark.parametrize("key", _MALICIOUS_KEYS)
    @pytest.mark.asyncio
    async def test_get_stream_raises(self, provider: LocalStorageProvider, key: str):
        with pytest.raises((ValueError, PermissionError, OSError)):
            await _consume_stream(provider.get_stream(key))


class TestLocalStorageContainmentGetToFile:
    """get_to_file() must reject traversal / absolute / null-byte keys."""

    @pytest.mark.parametrize("key", _MALICIOUS_KEYS)
    @pytest.mark.asyncio
    async def test_get_to_file_raises(
        self, provider: LocalStorageProvider, tmp_path: Path, key: str
    ):
        dest = tmp_path / "output.dat"
        with pytest.raises((ValueError, PermissionError, OSError)):
            await provider.get_to_file(key, dest)


class TestLocalStorageContainmentDelete:
    """delete() must reject traversal / absolute / null-byte keys."""

    @pytest.mark.parametrize("key", _MALICIOUS_KEYS)
    @pytest.mark.asyncio
    async def test_delete_raises(self, provider: LocalStorageProvider, key: str):
        with pytest.raises((ValueError, PermissionError, OSError)):
            await provider.delete(key)

    @pytest.mark.parametrize("key", _MALICIOUS_KEYS)
    @pytest.mark.asyncio
    async def test_delete_no_file_deleted_outside_base(
        self,
        provider: LocalStorageProvider,
        key: str,
        sentinel_outside: Path,
    ):
        """delete() with a traversal key must not remove files outside base_dir."""
        try:
            await provider.delete(key)
        except Exception:
            pass
        # Sentinel must still exist
        assert sentinel_outside.exists(), (
            f"delete() with key {key!r} removed a file outside base_dir"
        )


class TestLocalStorageContainmentExists:
    """exists() must reject traversal / absolute / null-byte keys."""

    @pytest.mark.parametrize("key", _MALICIOUS_KEYS)
    @pytest.mark.asyncio
    async def test_exists_raises(self, provider: LocalStorageProvider, key: str):
        with pytest.raises((ValueError, PermissionError, OSError)):
            await provider.exists(key)


# ---------------------------------------------------------------------------
# SEC-026 positive: normal in-base keys still work after the fix
# ---------------------------------------------------------------------------


class TestLocalStorageNormalKeys:
    """Normal (safe) keys must still work after the containment fix."""

    @pytest.mark.asyncio
    async def test_put_get_roundtrip(self, provider: LocalStorageProvider):
        await provider.put("datasets/file.gpkg", b"normal data")
        result = await provider.get("datasets/file.gpkg")
        assert result == b"normal data"

    @pytest.mark.asyncio
    async def test_nested_key(self, provider: LocalStorageProvider):
        await provider.put("a/b/c/d.bin", b"nested")
        assert await provider.exists("a/b/c/d.bin") is True

    @pytest.mark.asyncio
    async def test_delete_normal(self, provider: LocalStorageProvider):
        await provider.put("todel.txt", b"x")
        await provider.delete("todel.txt")
        assert await provider.exists("todel.txt") is False

    @pytest.mark.asyncio
    async def test_get_stream_normal(self, provider: LocalStorageProvider):
        data = b"stream content"
        await provider.put("stream.bin", data)
        result = await _consume_stream(provider.get_stream("stream.bin"))
        assert result == data

    @pytest.mark.asyncio
    async def test_get_to_file_normal(
        self, provider: LocalStorageProvider, tmp_path: Path
    ):
        data = b"file transfer"
        await provider.put("source.dat", data)
        dest = tmp_path / "sub" / "dest.dat"
        returned = await provider.get_to_file("source.dat", dest)
        assert returned == dest
        assert dest.read_bytes() == data

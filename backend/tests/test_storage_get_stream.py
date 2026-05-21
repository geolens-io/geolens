"""Regression test for ING-03 / P2-03: LocalStorageProvider.get_stream() must stream large files in fixed-size chunks without buffering the full payload."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.platform.storage.local import LocalStorageProvider, _STREAM_CHUNK_BYTES


# Build a deterministic 3 MiB payload: 256-byte cycle × 12288 = 3,145,728 bytes = 3 MiB exactly.
# Using the full 256-byte range ensures binary fidelity (no encoding ambiguities).
_PAYLOAD_3MIB = bytes(range(256)) * (3 * 1024 * 4)


@pytest.fixture
def local_provider(tmp_path: Path) -> LocalStorageProvider:
    return LocalStorageProvider(base_dir=str(tmp_path))


@pytest.mark.asyncio
async def test_get_stream_roundtrip(local_provider: LocalStorageProvider) -> None:
    """Stream a 3 MiB file and assert reconstructed bytes equal the source."""
    assert len(_PAYLOAD_3MIB) == 3 * 1024 * 1024, "payload must be exactly 3 MiB"
    await local_provider.put("big.bin", _PAYLOAD_3MIB)

    chunks = [chunk async for chunk in local_provider.get_stream("big.bin")]
    reconstructed = b"".join(chunks)

    assert reconstructed == _PAYLOAD_3MIB
    # Chunking proves no single-buffer impl snuck in: a 3 MiB file MUST yield
    # at least 3 chunks at 1 MiB chunk size.
    assert len(chunks) >= 3


@pytest.mark.asyncio
async def test_get_stream_chunk_size(local_provider: LocalStorageProvider) -> None:
    """Every chunk except possibly the last is exactly _STREAM_CHUNK_BYTES.

    A 3 MiB file at 1 MiB chunk size yields exactly 3 full chunks (no partial tail).
    """
    await local_provider.put("big.bin", _PAYLOAD_3MIB)

    chunks = [chunk async for chunk in local_provider.get_stream("big.bin")]

    assert len(chunks) == 3
    for chunk in chunks[:-1]:
        assert len(chunk) == _STREAM_CHUNK_BYTES
    assert len(chunks[-1]) <= _STREAM_CHUNK_BYTES


@pytest.mark.asyncio
async def test_get_stream_missing_key_raises(
    local_provider: LocalStorageProvider,
) -> None:
    """Calling get_stream on a missing key raises FileNotFoundError.

    Matches the existing get() contract so the router's `except FileNotFoundError`
    branch keeps mapping to HTTP 404.
    """
    with pytest.raises(FileNotFoundError):
        _ = [chunk async for chunk in local_provider.get_stream("nope.bin")]


@pytest.mark.asyncio
async def test_get_stream_handle_cleanup(
    local_provider: LocalStorageProvider,
) -> None:
    """Aborting mid-stream releases the file handle so a subsequent stream succeeds.

    Proves the `finally:` cleanup in the async generator closes the file even
    when the consumer abandons the iterator before exhaustion.
    """
    await local_provider.put("big.bin", _PAYLOAD_3MIB)

    # Consumer #1: pull one chunk, then abort.
    gen = local_provider.get_stream("big.bin").__aiter__()
    first_chunk = await gen.__anext__()
    assert len(first_chunk) == _STREAM_CHUNK_BYTES
    await gen.aclose()

    # Consumer #2: re-stream the same key end-to-end. If the first handle
    # leaked, this would either hang or read stale data on some platforms.
    chunks = [chunk async for chunk in local_provider.get_stream("big.bin")]
    reconstructed = b"".join(chunks)
    assert reconstructed == _PAYLOAD_3MIB

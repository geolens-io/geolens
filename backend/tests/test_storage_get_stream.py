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


# ---------------------------------------------------------------------------
# S3, fix(#1540) review P1: the same contract, and one request to honour it
# ---------------------------------------------------------------------------


@pytest.fixture
def s3_provider(monkeypatch):
    """An ``S3StorageProvider`` against a moto bucket.

    moto runs real boto3 calls, so the request COUNT below is measured rather
    than asserted about a stub.
    """
    import boto3
    from moto import mock_aws

    from app.platform.storage.s3 import S3StorageProvider

    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(var, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="stream-1540")
        yield S3StorageProvider(
            bucket="stream-1540",
            region="us-east-1",
            access_key_id="testing",
            secret_access_key="testing",
        )


@pytest.mark.asyncio
async def test_s3_get_stream_is_one_request_not_one_per_chunk(s3_provider) -> None:
    """The amplification this method exists to remove.

    fix(#1540 review P1): the COG route's stale-resume fallback streamed the
    whole object through a per-chunk ranged read, so a 5 GiB COG became 5,120
    object-store requests — selectable by any caller willing to send a stale
    validator, and billed by the rate limiter as one request. A single
    ``get_object``, read in chunks off the socket, costs what a download costs.

    Counted at the botocore layer: requests, not method calls.
    """
    calls: list[str] = []
    s3_provider.client.meta.events.register(
        "before-call.s3", lambda model, **kwargs: calls.append(model.name)
    )
    await s3_provider.put("big.bin", _PAYLOAD_3MIB)
    calls.clear()

    chunks = [chunk async for chunk in s3_provider.get_stream("big.bin")]

    assert b"".join(chunks) == _PAYLOAD_3MIB
    assert len(chunks) >= 3, (
        f"a 3 MiB object arrived in {len(chunks)} chunk(s); a single-buffer "
        f"read would put the whole object in memory at once."
    )
    assert calls == ["GetObject"], (
        f"streaming 3 MiB issued {calls}. One object, one request: a ranged "
        f"read per chunk is what turned a 5 GiB download into thousands of "
        f"them."
    )


@pytest.mark.asyncio
async def test_s3_get_stream_missing_key_raises(s3_provider) -> None:
    """Same FileNotFoundError contract every provider normalizes to (#430 BA-24).

    It is what lets the COG route answer 404 rather than 503 for an object that
    is simply gone.
    """
    with pytest.raises(FileNotFoundError):
        _ = [chunk async for chunk in s3_provider.get_stream("nope.bin")]


@pytest.mark.asyncio
async def test_s3_get_range_stream_is_one_request(s3_provider) -> None:
    """A range is one ranged GetObject, however many chunks it arrives in.

    fix(#1540 review P1), second occurrence: the COG route served ranges by
    calling ``get_range`` per 1 MiB, so ``Range: bytes=0-`` on a 5 GiB object
    became 5,120 serial requests. This is the method that makes a range cost
    one, and the count is measured at the botocore layer rather than inferred.
    """
    calls: list[str] = []
    s3_provider.client.meta.events.register(
        "before-call.s3", lambda model, **kwargs: calls.append(model.name)
    )
    await s3_provider.put("big.bin", _PAYLOAD_3MIB)
    calls.clear()

    window = 2 * 1024 * 1024 + 12345  # spans several chunks, ends mid-chunk
    chunks = [
        chunk async for chunk in s3_provider.get_range_stream("big.bin", 4096, window)
    ]

    assert b"".join(chunks) == _PAYLOAD_3MIB[4096 : 4096 + window]
    assert len(chunks) >= 2, "a multi-MiB window must not arrive as one buffer"
    assert calls == ["GetObject"], (
        f"streaming one window issued {calls}; a request per chunk is the "
        f"amplification this method exists to remove."
    )


@pytest.mark.asyncio
async def test_range_stream_contract_matches_across_providers(
    s3_provider, local_provider: LocalStorageProvider
) -> None:
    """Local and S3 answer a past-the-end window the same way: empty, not error.

    The route never asks for one — ``_parse_cog_range`` turns a first-byte-pos
    at or past the end into a 416 before any read — but a provider contract
    that holds only for the caller who happens to avoid the edge is not a
    contract. Azure needed normalizing to reach the same answer, which is what
    ``test_get_range_stream_past_the_end_is_empty`` in ``test_storage_azure.py``
    covers; this is the other two.
    """
    await local_provider.put("small.bin", b"0123456789")
    await s3_provider.put("small.bin", b"0123456789")

    local_chunks = [
        c async for c in local_provider.get_range_stream("small.bin", 50, 100)
    ]
    s3_chunks = [c async for c in s3_provider.get_range_stream("small.bin", 50, 100)]

    assert b"".join(local_chunks) == b""
    assert b"".join(s3_chunks) == b""

    for name, provider in (("local", local_provider), ("s3", s3_provider)):
        with pytest.raises(FileNotFoundError):
            _ = [c async for c in provider.get_range_stream("nope.bin", 0, 10)], name


@pytest.mark.asyncio
async def test_s3_get_stream_releases_the_body_on_abort(s3_provider) -> None:
    """A client that disconnects mid-download must not strand its connection.

    The local provider closes its file handle in a ``finally``; this one closes
    the botocore body for the same reason, and the check is the same: a second
    consumer reads the object end to end afterwards.
    """
    await s3_provider.put("big.bin", _PAYLOAD_3MIB)

    gen = s3_provider.get_stream("big.bin").__aiter__()
    first_chunk = await gen.__anext__()
    assert len(first_chunk) > 0
    await gen.aclose()

    chunks = [chunk async for chunk in s3_provider.get_stream("big.bin")]
    assert b"".join(chunks) == _PAYLOAD_3MIB

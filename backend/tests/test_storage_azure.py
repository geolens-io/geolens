"""Tests for AzureBlobStorageProvider against the Azurite emulator.

Session-scoped fixture probes Azurite on the well-known dev connection string.
When Azurite is not running the entire module is skipped cleanly so the default
local test run is unaffected.

Run against a live Azurite:
    docker compose --profile cloud-dev up -d azurite
    cd backend && uv run pytest tests/test_storage_azure.py -x -q
"""

from __future__ import annotations

import socket
from io import BytesIO

import pytest

# Azurite well-known dev connection string — these are the PUBLICLY DOCUMENTED
# default credentials shipped with every Azurite release. They are NOT secret;
# they are intentionally hardcoded in the Azure Storage Emulator specification
# and safe to commit (gitleaks:allow).
_AZURITE_CONN = (  # gitleaks:allow
    "DefaultEndpointsProtocol=http;"
    "AccountName=devstoreaccount1;"
    "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
    "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
)
_AZURITE_CONTAINER = "geolens-test"
_AZURITE_HOST = "127.0.0.1"
_AZURITE_PORT = 10000


def _azurite_reachable() -> bool:
    """Probe Azurite TCP — returns False if the emulator is not running."""
    try:
        with socket.create_connection((_AZURITE_HOST, _AZURITE_PORT), timeout=1):
            return True
    except (OSError, ConnectionRefusedError):
        return False


@pytest.fixture(scope="session")
def azurite_provider():
    """Return a live AzureBlobStorageProvider pointed at Azurite.

    Skips the entire session if Azurite is unreachable.
    """
    if not _azurite_reachable():
        pytest.skip(
            "Azurite not running (127.0.0.1:10000); skipping Azure storage tests"
        )

    from app.platform.storage.azure import AzureBlobStorageProvider
    from azure.storage.blob import BlobServiceClient

    # Create the test container if it doesn't exist
    service = BlobServiceClient.from_connection_string(_AZURITE_CONN)
    try:
        service.create_container(_AZURITE_CONTAINER)
    except Exception:
        pass  # Container may already exist

    return AzureBlobStorageProvider(
        container=_AZURITE_CONTAINER,
        connection_string=_AZURITE_CONN,
    )


# ---------------------------------------------------------------------------
# Protocol completeness (import-only, no Azurite required)
# ---------------------------------------------------------------------------


def test_import():
    """AzureBlobStorageProvider imports without error."""
    from app.platform.storage.azure import AzureBlobStorageProvider  # noqa: F401


def test_protocol_completeness():
    """Every public StorageProvider method is implemented by AzureBlobStorageProvider."""
    from app.platform.storage.azure import AzureBlobStorageProvider
    from app.platform.storage.provider import StorageProvider

    required = {n for n in dir(StorageProvider) if not n.startswith("_")}
    provided = {n for n in dir(AzureBlobStorageProvider) if not n.startswith("_")}
    missing = required - provided
    assert not missing, f"Missing StorageProvider methods: {missing}"


def test_no_vsi_literals_in_provider():
    """Provider builds no VSI prefixes — /vsis3/ and /vsiaz/ must not appear in the module."""
    import inspect

    from app.platform.storage import azure as azure_mod

    source = inspect.getsource(azure_mod)
    assert "/vsis3/" not in source, "/vsis3/ literal leaked into azure.py"
    assert "/vsiaz/" not in source, "/vsiaz/ literal leaked into azure.py"


# ---------------------------------------------------------------------------
# Round-trip tests against Azurite (skipped when emulator absent)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_bytes_and_get(azurite_provider):
    """put(bytes) then get() returns the same bytes."""
    data = b"azure-round-trip-bytes"
    key = "test/round_trip_bytes.bin"
    uri = await azurite_provider.put(key, data)
    assert uri == f"az://{_AZURITE_CONTAINER}/{key}"
    result = await azurite_provider.get(key)
    assert result == data


@pytest.mark.asyncio
async def test_put_fileobj_and_get(azurite_provider):
    """put(fileobj) then get() returns the same bytes."""
    data = b"azure-fileobj-stream"
    key = "test/round_trip_fileobj.bin"
    fileobj = BytesIO(data)
    uri = await azurite_provider.put(key, fileobj)
    assert uri.startswith("az://")
    result = await azurite_provider.get(key)
    assert result == data


@pytest.mark.asyncio
async def test_exists_true(azurite_provider):
    """exists() returns True for an uploaded blob."""
    key = "test/exists_true.bin"
    await azurite_provider.put(key, b"present")
    assert await azurite_provider.exists(key) is True


@pytest.mark.asyncio
async def test_exists_false(azurite_provider):
    """exists() returns False for a missing blob (no exception)."""
    assert await azurite_provider.exists("test/no_such_blob_xyz.bin") is False


@pytest.mark.asyncio
async def test_delete_removes_blob(azurite_provider):
    """delete() removes a blob; subsequent exists() returns False."""
    key = "test/delete_me.bin"
    await azurite_provider.put(key, b"delete-me")
    assert await azurite_provider.exists(key) is True
    await azurite_provider.delete(key)
    assert await azurite_provider.exists(key) is False


@pytest.mark.asyncio
async def test_delete_missing_is_noop(azurite_provider):
    """delete() on a missing key raises no exception."""
    await azurite_provider.delete("test/never_uploaded_xyz.bin")  # should not raise


@pytest.mark.asyncio
async def test_list_prefix(azurite_provider):
    """list() returns blob names under the given prefix."""
    prefix = "test/list_prefix/"
    keys = [f"{prefix}a.bin", f"{prefix}b.bin", f"{prefix}c.bin"]
    for k in keys:
        await azurite_provider.put(k, b"data")

    result = await azurite_provider.list(prefix)
    for k in keys:
        assert k in result


@pytest.mark.asyncio
async def test_get_to_file(azurite_provider, tmp_path):
    """get_to_file() downloads blob content to a local path, creating parent dirs."""
    key = "test/get_to_file/nested/output.bin"
    data = b"file-download-data"
    await azurite_provider.put(key, data)
    dest = tmp_path / "output" / "nested" / "output.bin"
    returned = await azurite_provider.get_to_file(key, dest)
    assert returned == dest
    assert dest.read_bytes() == data


@pytest.mark.asyncio
async def test_health_check_passes(azurite_provider):
    """health_check() succeeds against a reachable Azurite container."""
    await azurite_provider.health_check()  # should not raise


@pytest.mark.asyncio
async def test_get_range_stream_round_trip(azurite_provider):
    """A window streams back byte-exact, from one download call.

    fix(#1540 review P1): the COG route used to serve a range by calling
    ``get_range`` once per 1 MiB, which on this provider is a download call per
    chunk. Azure reaches that path by the ordinary route, not an exotic one:
    managed rasters are ``storage_backend="local"`` whatever the object store.
    """
    payload = bytes(range(256)) * 4096  # 1 MiB exactly
    key = "test/range_stream.bin"
    await azurite_provider.put(key, payload)

    chunks = [
        chunk async for chunk in azurite_provider.get_range_stream(key, 1000, 5000)
    ]

    assert b"".join(chunks) == payload[1000:6000]


@pytest.mark.asyncio
async def test_get_stream_round_trip(azurite_provider):
    """The whole blob streams back byte-exact from one download call.

    fix(#1532 review r1): this method raised ``NotImplementedError`` behind a
    docstring claiming the router always redirects Azure through a SAS URL. It
    does not — fix(#1540) established that no ingest path writes
    ``storage_backend="azure"``, so managed assets take the LOCAL branch, whose
    whole-object GET calls this — and the cached export download added a second
    caller. The raise landed while ``StreamingResponse`` was already consuming
    the iterator, so the client saw a truncated body rather than an error.
    """
    payload = bytes(range(256)) * 4096  # 1 MiB exactly
    key = "test/whole_stream.bin"
    await azurite_provider.put(key, payload)

    chunks = [chunk async for chunk in azurite_provider.get_stream(key)]

    assert b"".join(chunks) == payload


@pytest.mark.asyncio
async def test_get_stream_missing_key_raises(azurite_provider):
    """Same FileNotFoundError contract every provider normalizes to (#430 BA-24)."""
    with pytest.raises(FileNotFoundError):
        async for _ in azurite_provider.get_stream("nope.bin"):
            pass


@pytest.mark.asyncio
async def test_get_range_stream_missing_key_raises(azurite_provider):
    """Same FileNotFoundError contract every provider normalizes to (#430 BA-24)."""
    with pytest.raises(FileNotFoundError):
        async for _ in azurite_provider.get_range_stream("nope.bin", 0, 10):
            pass


@pytest.mark.asyncio
async def test_get_range_stream_past_the_end_is_empty(azurite_provider):
    """A window beyond the blob ends the stream instead of raising.

    Matches ``get_range`` and the local/POSIX seek-then-read the other
    providers give: the caller has already decided what an empty window means,
    and for the COG route that decision is the 416 it computes from the size.
    """
    key = "test/range_stream_short.bin"
    await azurite_provider.put(key, b"0123456789")

    chunks = [chunk async for chunk in azurite_provider.get_range_stream(key, 50, 100)]

    assert b"".join(chunks) == b""


def test_presigned_methods_raise_not_implemented(azurite_provider):
    """All presigned/multipart methods raise NotImplementedError."""
    with pytest.raises(NotImplementedError):
        azurite_provider.generate_presigned_put_url("k")
    with pytest.raises(NotImplementedError):
        azurite_provider.generate_presigned_get_url("k")
    with pytest.raises(NotImplementedError):
        azurite_provider.initiate_multipart_upload("k")
    with pytest.raises(NotImplementedError):
        azurite_provider.generate_presigned_part_url("k", "uid", 1)
    with pytest.raises(NotImplementedError):
        azurite_provider.complete_multipart_upload("k", "uid", [])
    with pytest.raises(NotImplementedError):
        azurite_provider.abort_multipart_upload("k", "uid")

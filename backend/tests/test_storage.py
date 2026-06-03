"""Unit tests for storage providers and factory."""

from io import BytesIO
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from app.platform.storage.local import LocalStorageProvider
from app.platform.storage.s3 import S3StorageProvider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def local_provider(tmp_path: Path) -> LocalStorageProvider:
    """Create a LocalStorageProvider backed by a temporary directory."""
    return LocalStorageProvider(base_dir=str(tmp_path))


@pytest.fixture
def aws_credentials(monkeypatch):
    """Set mock AWS credentials for moto."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def s3_provider(aws_credentials):
    """Create an S3StorageProvider with a moto-mocked bucket."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-bucket")
        provider = S3StorageProvider(
            bucket="test-bucket",
            region="us-east-1",
            access_key_id="testing",
            secret_access_key="testing",
        )
        yield provider


# ---------------------------------------------------------------------------
# LocalStorageProvider tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_put_get_bytes(local_provider: LocalStorageProvider):
    data = b"hello world"
    await local_provider.put("docs/file.txt", data)
    result = await local_provider.get("docs/file.txt")
    assert result == data


@pytest.mark.asyncio
async def test_local_put_get_fileobj(local_provider: LocalStorageProvider):
    data = b"binary stream content"
    fileobj = BytesIO(data)
    await local_provider.put("uploads/stream.bin", fileobj)
    result = await local_provider.get("uploads/stream.bin")
    assert result == data


@pytest.mark.asyncio
async def test_local_get_to_file(local_provider: LocalStorageProvider, tmp_path: Path):
    data = b"content for file download"
    await local_provider.put("source.dat", data)
    dest = tmp_path / "output" / "dest.dat"
    returned = await local_provider.get_to_file("source.dat", dest)
    assert returned == dest
    assert dest.read_bytes() == data


@pytest.mark.asyncio
async def test_local_delete(local_provider: LocalStorageProvider):
    await local_provider.put("to_delete.txt", b"temporary")
    assert await local_provider.exists("to_delete.txt") is True
    await local_provider.delete("to_delete.txt")
    assert await local_provider.exists("to_delete.txt") is False


@pytest.mark.asyncio
async def test_local_delete_missing(local_provider: LocalStorageProvider):
    # Should not raise an error
    await local_provider.delete("nonexistent_key.txt")


@pytest.mark.asyncio
async def test_local_exists(local_provider: LocalStorageProvider):
    assert await local_provider.exists("missing.txt") is False
    await local_provider.put("missing.txt", b"now exists")
    assert await local_provider.exists("missing.txt") is True


@pytest.mark.asyncio
async def test_local_list(local_provider: LocalStorageProvider):
    await local_provider.put("datasets/a.gpkg", b"a")
    await local_provider.put("datasets/b.gpkg", b"b")
    await local_provider.put("uploads/c.zip", b"c")

    # Prefix with trailing slash lists directory contents
    result = await local_provider.list("datasets/")
    assert sorted(result) == ["datasets/a.gpkg", "datasets/b.gpkg"]

    # File prefix filters by name prefix
    result = await local_provider.list("datasets/a")
    assert result == ["datasets/a.gpkg"]


# ---------------------------------------------------------------------------
# S3StorageProvider tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s3_put_get_bytes(s3_provider: S3StorageProvider):
    data = b"s3 hello world"
    await s3_provider.put("docs/file.txt", data)
    result = await s3_provider.get("docs/file.txt")
    assert result == data


@pytest.mark.asyncio
async def test_s3_put_get_fileobj(s3_provider: S3StorageProvider):
    data = b"s3 binary stream"
    fileobj = BytesIO(data)
    await s3_provider.put("uploads/stream.bin", fileobj)
    result = await s3_provider.get("uploads/stream.bin")
    assert result == data


@pytest.mark.asyncio
async def test_s3_get_to_file(s3_provider: S3StorageProvider, tmp_path: Path):
    data = b"s3 content for download"
    await s3_provider.put("source.dat", data)
    dest = tmp_path / "output" / "dest.dat"
    returned = await s3_provider.get_to_file("source.dat", dest)
    assert returned == dest
    assert dest.read_bytes() == data


@pytest.mark.asyncio
async def test_s3_delete(s3_provider: S3StorageProvider):
    await s3_provider.put("to_delete.txt", b"temporary")
    assert await s3_provider.exists("to_delete.txt") is True
    await s3_provider.delete("to_delete.txt")
    assert await s3_provider.exists("to_delete.txt") is False


@pytest.mark.asyncio
async def test_s3_delete_missing(s3_provider: S3StorageProvider):
    # S3 silently ignores deletes on missing keys
    await s3_provider.delete("nonexistent_key.txt")


@pytest.mark.asyncio
async def test_s3_exists(s3_provider: S3StorageProvider):
    assert await s3_provider.exists("missing.txt") is False
    await s3_provider.put("missing.txt", b"now exists")
    assert await s3_provider.exists("missing.txt") is True


@pytest.mark.asyncio
async def test_s3_list(s3_provider: S3StorageProvider):
    await s3_provider.put("datasets/a.gpkg", b"a")
    await s3_provider.put("datasets/b.gpkg", b"b")
    await s3_provider.put("uploads/c.zip", b"c")

    result = await s3_provider.list("datasets/")
    assert sorted(result) == ["datasets/a.gpkg", "datasets/b.gpkg"]

    result = await s3_provider.list("uploads/")
    assert result == ["uploads/c.zip"]


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_storage_not_initialized():
    """get_storage() raises RuntimeError before init_storage() is called."""
    import app.platform.storage.provider as provider_mod

    original = provider_mod._storage
    try:
        provider_mod._storage = None
        with pytest.raises(RuntimeError, match="not initialized"):
            provider_mod.get_storage()
    finally:
        provider_mod._storage = original


@pytest.mark.asyncio
async def test_init_storage_local(monkeypatch, tmp_path: Path):
    """init_storage() with storage_provider='local' creates LocalStorageProvider."""
    import app.platform.storage.provider as provider_mod

    original = provider_mod._storage
    try:
        provider_mod._storage = None

        # Monkeypatch settings to use local provider
        from app.core.config import settings

        monkeypatch.setattr(settings, "storage_provider", "local")
        monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path))

        provider_mod.init_storage()
        storage = provider_mod.get_storage()
        assert isinstance(storage, LocalStorageProvider)
    finally:
        provider_mod._storage = original

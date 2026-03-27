"""Unit tests for presigned S3 upload methods."""

import boto3
import pytest
from moto import mock_aws

from app.storage.s3 import S3StorageProvider
from app.storage.local import LocalStorageProvider
from app.ingest.schemas import (
    PresignedUploadRequest,
    PresignedUploadResponse,
    PresignedCompleteRequest,
    PresignedPartInfo,
    UploadConfigResponse,
)


@pytest.fixture
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def s3_provider(aws_credentials):
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


# --- Presigned PUT URL tests ---


def test_generate_presigned_put_url(s3_provider):
    url = s3_provider.generate_presigned_put_url("staging/test.zip")
    assert "test-bucket" in url
    assert "staging/test.zip" in url or "staging%2Ftest.zip" in url
    assert url.startswith("https://")


def test_generate_presigned_put_url_with_content_type(s3_provider):
    url = s3_provider.generate_presigned_put_url(
        "staging/test.gpkg", content_type="application/geopackage+sqlite3"
    )
    assert "test-bucket" in url


# --- Multipart upload tests ---


def test_initiate_multipart_upload(s3_provider):
    upload_id = s3_provider.initiate_multipart_upload("staging/large.zip")
    assert isinstance(upload_id, str)
    assert len(upload_id) > 0


def test_generate_presigned_part_url(s3_provider):
    upload_id = s3_provider.initiate_multipart_upload("staging/large.zip")
    url = s3_provider.generate_presigned_part_url("staging/large.zip", upload_id, 1)
    assert "test-bucket" in url
    assert url.startswith("https://")


def test_complete_multipart_upload(s3_provider):
    key = "staging/complete-test.zip"
    upload_id = s3_provider.initiate_multipart_upload(key)
    # Upload a part directly to complete
    s3_provider.client.upload_part(
        Bucket="test-bucket",
        Key=key,
        UploadId=upload_id,
        PartNumber=1,
        Body=b"x" * (5 * 1024 * 1024),  # 5MB minimum part size
    )
    parts = s3_provider.client.list_parts(
        Bucket="test-bucket", Key=key, UploadId=upload_id
    )
    etag = parts["Parts"][0]["ETag"]
    s3_provider.complete_multipart_upload(
        key, upload_id, [{"ETag": etag, "PartNumber": 1}]
    )
    # File should exist after completion
    assert s3_provider.client.head_object(Bucket="test-bucket", Key=key)


def test_abort_multipart_upload(s3_provider):
    upload_id = s3_provider.initiate_multipart_upload("staging/abort-test.zip")
    s3_provider.abort_multipart_upload("staging/abort-test.zip", upload_id)
    # Should not raise


# --- LocalStorageProvider not-supported tests ---


def test_local_presigned_raises():
    lp = LocalStorageProvider(base_dir="/tmp/test-presigned")
    with pytest.raises(NotImplementedError):
        lp.generate_presigned_put_url("key")
    with pytest.raises(NotImplementedError):
        lp.initiate_multipart_upload("key")
    with pytest.raises(NotImplementedError):
        lp.generate_presigned_part_url("key", "uid", 1)
    with pytest.raises(NotImplementedError):
        lp.complete_multipart_upload("key", "uid", [])
    with pytest.raises(NotImplementedError):
        lp.abort_multipart_upload("key", "uid")


# --- Schema validation tests ---


def test_presigned_upload_request_schema():
    req = PresignedUploadRequest(filename="test.zip", file_size=1024)
    assert req.filename == "test.zip"
    assert req.file_size == 1024
    assert req.content_type == "application/octet-stream"


def test_presigned_upload_response_simple():
    resp = PresignedUploadResponse(
        job_id="00000000-0000-0000-0000-000000000001",
        urls=["https://s3.example.com/presigned"],
        s3_key="staging/job-id/test.zip",
    )
    assert len(resp.urls) == 1
    assert resp.upload_id is None
    assert resp.part_size is None


def test_presigned_upload_response_multipart():
    resp = PresignedUploadResponse(
        job_id="00000000-0000-0000-0000-000000000001",
        urls=["https://url1", "https://url2", "https://url3"],
        s3_key="staging/job-id/large.zip",
        upload_id="abc123",
        part_size=10485760,
    )
    assert len(resp.urls) == 3
    assert resp.upload_id == "abc123"
    assert resp.part_size == 10485760


def test_presigned_complete_request():
    req = PresignedCompleteRequest(
        parts=[
            PresignedPartInfo(etag='"abc"', part_number=1),
            PresignedPartInfo(etag='"def"', part_number=2),
        ]
    )
    assert len(req.parts) == 2


def test_upload_config_response():
    config = UploadConfigResponse(
        presigned_uploads=True,
        presigned_threshold_bytes=104857600,
        max_file_size_bytes=524288000,
        allowed_extensions=".geojson,.gpkg,.shp,.csv,.xlsx,.xls,.json,.tif,.tiff,.vrt",
    )
    assert config.presigned_uploads is True

"""S3_PUBLIC_ENDPOINT: presigned URLs name the host clients reach."""

from urllib.parse import parse_qs, urlsplit

import pytest
from botocore.stub import Stubber
from pydantic import SecretStr

import app.platform.storage.provider as provider_module
from app.core.config import settings
from app.platform.storage.s3 import S3StorageProvider

_INTERNAL = "http://minio:9000"
_PUBLIC = "https://files.example.com:9443"


def _provider(public_endpoint: str | None, **kwargs) -> S3StorageProvider:
    return S3StorageProvider(
        bucket="test-bucket",
        endpoint=_INTERNAL,
        access_key_id="presign-test-key",
        secret_access_key="presign-test-secret",
        addressing_style="path",
        public_endpoint=public_endpoint,
        **kwargs,
    )


def _presigned(provider: S3StorageProvider, kind: str) -> str:
    if kind == "get":
        return provider.generate_presigned_get_url("rasters/a.tif")
    if kind == "put":
        return provider.generate_presigned_put_url("staging/a.zip")
    return provider.generate_presigned_part_url("staging/a.zip", "upload-1", 1)


@pytest.mark.parametrize("kind", ["get", "put", "part"])
def test_presigned_urls_use_the_public_host_when_one_is_set(kind: str) -> None:
    url = urlsplit(_presigned(_provider(_PUBLIC), kind))

    assert (url.scheme, url.netloc) == ("https", "files.example.com:9443")
    assert url.path.startswith("/test-bucket/")
    assert {"Signature", "X-Amz-Signature"} & parse_qs(url.query).keys()


@pytest.mark.parametrize("kind", ["get", "put", "part"])
@pytest.mark.parametrize("public_endpoint", [None, ""])
def test_presigned_urls_use_the_storage_endpoint_without_a_public_host(
    kind: str, public_endpoint: str | None
) -> None:
    url = urlsplit(_presigned(_provider(public_endpoint), kind))

    assert (url.scheme, url.netloc) == ("http", "minio:9000")


@pytest.mark.parametrize(("allow_http", "scheme"), [(False, "https"), (True, "http")])
def test_a_scheme_less_public_host_follows_allow_http(
    allow_http: bool, scheme: str
) -> None:
    provider = _provider("files.example.com:9443", allow_http=allow_http)

    url = urlsplit(_presigned(provider, "get"))

    assert (url.scheme, url.netloc) == (scheme, "files.example.com:9443")


@pytest.mark.asyncio
async def test_storage_operations_keep_using_the_storage_endpoint() -> None:
    provider = _provider("https://files.example.invalid")
    assert provider.client.meta.endpoint_url == _INTERNAL

    bucket_key = {"Bucket": "test-bucket", "Key": "rasters/a.tif"}
    with Stubber(provider.client) as stubber:
        stubber.add_response("head_object", {"ContentLength": 5}, bucket_key)
        stubber.add_response(
            "create_multipart_upload",
            {"UploadId": "upload-1"},
            {**bucket_key, "ContentType": "application/octet-stream"},
        )
        assert await provider.size("rasters/a.tif") == 5
        assert provider.initiate_multipart_upload("rasters/a.tif") == "upload-1"
        stubber.assert_no_pending_responses()


@pytest.mark.parametrize("endpoint", ["http://", "https://not a host"])
def test_a_malformed_public_endpoint_is_rejected(endpoint: str) -> None:
    with pytest.raises(ValueError):
        _provider(endpoint)


def test_init_storage_hands_the_public_endpoint_to_the_provider(monkeypatch) -> None:
    monkeypatch.setattr(provider_module, "_storage", None)
    for name, value in {
        "storage_provider": "s3",
        "s3_bucket": "test-bucket",
        "s3_endpoint": _INTERNAL,
        "s3_public_endpoint": _PUBLIC,
        "s3_access_key_id": "presign-test-key",
        "s3_secret_access_key": SecretStr("presign-test-secret"),
    }.items():
        monkeypatch.setattr(settings, name, value)

    provider_module.init_storage()

    url = urlsplit(provider_module.get_storage().generate_presigned_get_url("a.tif"))
    assert url.netloc == "files.example.com:9443"

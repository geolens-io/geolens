"""Published request schemas reject what the runtime would reject later."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.processing.ingest.manifest_schemas import ManifestSource
from app.processing.ingest.schemas import VrtCreateRequest


@pytest.mark.parametrize(
    "uri", ["gs://bucket/a.gpkg", "az://c/a.gpkg", "abfs://c/a.gpkg"]
)
def test_manifest_source_rejects_storage_schemes_the_runtime_cannot_resolve(
    uri: str,
) -> None:
    with pytest.raises(ValidationError):
        ManifestSource(type="vector", uri=uri)


def test_manifest_source_accepts_s3_uri() -> None:
    assert ManifestSource(type="vector", uri="s3://bucket/a.gpkg").uri


def test_vrt_create_request_requires_two_sources() -> None:
    fields = {"vrt_type": "mosaic", "resolution_strategy": "finest", "title": "t"}
    with pytest.raises(ValidationError):
        VrtCreateRequest(source_dataset_ids=[uuid4()], **fields)
    VrtCreateRequest(source_dataset_ids=[uuid4(), uuid4()], **fields)

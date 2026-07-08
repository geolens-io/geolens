"""Security tests for URL query credential rejection/redaction."""

import pytest
from pydantic import ValidationError

from app.core.url_redaction import (
    has_url_credentials,
    redact_query_credentials,
    redact_url_credentials,
)
from app.modules.catalog.datasets.domain.schemas import (
    DatasetMeta,
    ReuploadServicePreviewRequest,
)
from app.modules.catalog.sources.schemas import ProbeRequest, ServicePreviewRequest
from app.modules.catalog.sources.stac_router import StacConnectRequest, StacImportItem


def test_redact_url_credentials_masks_sensitive_query_values() -> None:
    redacted = redact_url_credentials(
        "https://example.com/wfs?f=json&token=secret&X-Amz-Signature=sig"
    )

    assert "secret" not in redacted
    assert "sig" not in redacted
    assert "f=json" in redacted
    assert "token=%3Credacted%3E" in redacted
    assert "X-Amz-Signature=%3Credacted%3E" in redacted


@pytest.mark.parametrize(
    "value",
    [
        "https://?token=secret",
        "https:///path?token=secret",
        "ESRIJSON:https://?token=secret",
        "ogrinfo failed for https://?token=secret and bailed",
    ],
)
def test_redact_url_credentials_empty_host_terminates_and_masks(value: str) -> None:
    # fix(#429 review): an http(s) URL with an empty host previously matched the
    # whole string in the regex fallback and recursed forever (RecursionError).
    # It must terminate and still mask the secret.
    redacted = redact_url_credentials(value)
    assert "secret" not in redacted


def test_redact_query_credentials_preserves_non_sensitive_query() -> None:
    assert redact_query_credentials("f=json&where=1%3D1") == "f=json&where=1%3D1"


def test_has_url_credentials_detects_blank_sensitive_param() -> None:
    assert has_url_credentials("https://example.com/arcgis?token=")


def test_has_url_credentials_detects_userinfo() -> None:
    assert has_url_credentials("https://user:secret@example.com/cog.tif")


def test_redact_url_credentials_masks_userinfo_and_gcs_signature() -> None:
    redacted = redact_url_credentials(
        "ESRIJSON:https://user:secret@example.com/cog.tif?"
        "X-Goog-Credential=credential&X-Goog-Signature=signature&f=json"
    )

    assert "user:secret" not in redacted
    assert "credential" not in redacted
    assert "signature" not in redacted
    assert "f=json" in redacted
    assert "redacted@example.com" in redacted
    assert "X-Goog-Credential=%3Credacted%3E" in redacted
    assert "X-Goog-Signature=%3Credacted%3E" in redacted


@pytest.mark.parametrize("model", [ProbeRequest, ServicePreviewRequest])
def test_service_requests_reject_credential_query_params(model) -> None:
    kwargs = {"url": "https://example.com/service?token=secret"}
    if model is ServicePreviewRequest:
        kwargs.update({"service_type": "WFS 2.0.0", "layer_name": "roads"})

    with pytest.raises(ValidationError):
        model(**kwargs)


def test_stac_connect_rejects_credential_query_params() -> None:
    with pytest.raises(ValidationError):
        StacConnectRequest(url="https://example.com/stac?api_key=secret")


def test_stac_connect_rejects_url_userinfo() -> None:
    with pytest.raises(ValidationError):
        StacConnectRequest(url="https://user:secret@example.com/stac")


def test_stac_import_item_rejects_signed_asset_href() -> None:
    with pytest.raises(ValidationError):
        StacImportItem(
            id="item-1",
            title="Item 1",
            data_asset_href="https://example.com/cog.tif?X-Amz-Signature=secret",
        )


def test_reupload_service_preview_rejects_credential_query_params() -> None:
    with pytest.raises(ValidationError):
        ReuploadServicePreviewRequest(
            url="https://example.com/wfs?token=secret",
            service_type="WFS 2.0.0",
            layer_name="roads",
        )


def test_dataset_meta_source_url_rejects_credentials() -> None:
    with pytest.raises(ValidationError):
        DatasetMeta(source_url="https://example.com/cog.tif?X-Goog-Signature=secret")

    with pytest.raises(ValidationError):
        DatasetMeta(source_url="https://user:secret@example.com/cog.tif")

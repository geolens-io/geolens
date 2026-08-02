"""Security tests for URL query credential rejection/redaction."""

import time

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


# fix(#1116): URL_LIKE_RE's optional scheme prefix used an unbounded `+`, which
# is ambiguous against the `https?` that follows. A long run of prefix-class
# characters that never completes a match made the engine retry every prefix
# length at every start position — O(n²). Free text reaches that fallback from
# GDAL/ogr2ogr stderr and uploaded-VRT <SourceFilename> values, so the run is
# attacker-influenced. Measured in-pytest on this commit (pytest --durations, not
# a standalone bench): the 200 KB run below takes 0.03s with the {1,64} bound and
# 33s without it, so the threshold has ~65x headroom for a slow CI runner while
# staying far out of reach for the quadratic form. Keep that figure in-pytest — a
# standalone bench reports a rosier 0.02s/~86x, which is not what governs whether
# this test flakes.
REDOS_INPUT_CHARS = 200_000
REDOS_THRESHOLD_S = 2.0


# Deliberately NOT marked @pytest.mark.perf. backend/pyproject.toml:163 sets
# addopts = "-m 'not perf' --dist loadgroup", so that marker deselects a test from
# both `make test` and CI — adding it here would ship a ReDoS guard that never
# runs. This test costs 0.03s, so it does not need the marker that the genuinely
# slow perf-suite tests carry.
def test_redact_url_credentials_stays_linear_on_hostile_alphanumeric_run() -> None:
    hostile = "a" * REDOS_INPUT_CHARS

    start = time.perf_counter()
    result = redact_url_credentials(hostile)
    elapsed = time.perf_counter() - start

    # Nothing here looks like a URL, so it must come back untouched. Asserting
    # this keeps the timing check honest: a regex that matched nothing at all
    # would be fast but would stop redacting.
    assert result == hostile
    assert elapsed < REDOS_THRESHOLD_S, (
        f"redacting {REDOS_INPUT_CHARS} non-URL characters took {elapsed:.2f}s "
        f"(threshold {REDOS_THRESHOLD_S}s) — the URL_LIKE_RE scheme prefix is "
        "backtracking quadratically again"
    )


@pytest.mark.parametrize("prefix_len", [1, 63, 64, 65, 200, 5_000])
def test_redact_url_credentials_masks_userinfo_behind_long_scheme_prefix(
    prefix_len: int,
) -> None:
    # fix(#1116): bounding the scheme prefix must not let a credential escape
    # when the GDAL-style prefix is longer than the bound. It cannot: the match
    # just starts later in the string and still covers the whole URL.
    value = "A" * prefix_len + ":https://user:secret@example.com/cog.tif"

    redacted = redact_url_credentials(value)

    assert "secret" not in redacted
    assert "redacted@example.com" in redacted


def test_redact_url_credentials_masks_url_after_long_free_text_run() -> None:
    # fix(#1116): the bounded prefix must still find a credential URL sitting
    # behind a long run of prefix-class characters (the GDAL-stderr shape).
    value = "a" * 100_000 + " https://user:secret@example.com/x?token=t0ken"

    redacted = redact_url_credentials(value)

    assert "secret" not in redacted
    assert "t0ken" not in redacted
    assert "redacted@example.com" in redacted
    assert "token=%3Credacted%3E" in redacted


def test_redact_query_credentials_preserves_non_sensitive_query() -> None:
    assert redact_query_credentials("f=json&where=1%3D1") == "f=json&where=1%3D1"


def test_has_url_credentials_detects_blank_sensitive_param() -> None:
    assert has_url_credentials("https://example.com/arcgis?token=")


def test_has_url_credentials_detects_userinfo() -> None:
    assert has_url_credentials("https://user:secret@example.com/cog.tif")


@pytest.mark.parametrize(
    "url",
    [
        "ESRIJSON:https://user:pass@evil/x",
        "WFS:https://user:pass@evil/x",
    ],
)
def test_has_url_credentials_detects_userinfo_behind_gdal_prefix(url: str) -> None:
    # fix(#430 BA-04): urlsplit sees scheme 'esrijson'/'wfs' with no netloc, so
    # .username/.password were None and the credential slipped through. The
    # validator must strip the GDAL prefix before inspecting userinfo.
    assert has_url_credentials(url)


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

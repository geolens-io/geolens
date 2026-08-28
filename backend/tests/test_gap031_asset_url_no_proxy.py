"""Regression tests for GAP-031: no unauthenticated /assets/{key} proxy URL emitted.

_proxy_url emitted /assets/{key} which:
  - Collides with the nginx SPA /assets/ location (serves bundle, not storage)
  - Has no backend route to handle the request
  - Is unauthenticated and uncontained

The fix: resolve_asset_url returns None for the dead local-storage proxy path
instead of a bare /assets/{key} URL. Since dataset_assets is never populated
(BUG-041), this changes no live output.

Fail-before / pass-after protocol: these tests MUST FAIL on unpatched code.
"""

from app.platform.assets.urls import resolve_asset_url

PUBLIC_API_URL = "http://localhost:8000"


class TestGap031NoProxyUrl:
    """GAP-031: resolve_asset_url must not emit bare /assets/{key} proxy URLs."""

    def test_local_published_data_returns_none_not_proxy(self):
        """Local storage published data asset must NOT produce /assets/{key}."""
        result = resolve_asset_url(
            "/uploads/test.tif",
            storage_backend="local",
            record_status="published",
            roles=["data"],
            public_api_url=PUBLIC_API_URL,
        )
        assert result is None or (result is not None and "/assets/" not in result), (
            f"GAP-031 FAIL: bare /assets/ proxy URL emitted for local storage: {result}"
        )

    def test_local_draft_returns_none_not_proxy(self):
        """Local storage draft asset must NOT produce /assets/{key}."""
        result = resolve_asset_url(
            "/uploads/test.tif",
            storage_backend="local",
            record_status="draft",
            roles=["data"],
            public_api_url=PUBLIC_API_URL,
        )
        assert result is None or (result is not None and "/assets/" not in result), (
            f"GAP-031 FAIL: bare /assets/ proxy URL emitted for local draft: {result}"
        )

    def test_local_thumbnail_returns_none_not_proxy(self):
        """Local storage thumbnail must NOT produce /assets/{key}."""
        result = resolve_asset_url(
            "/uploads/thumb.png",
            storage_backend="local",
            record_status="published",
            roles=["thumbnail"],
            public_api_url=PUBLIC_API_URL,
        )
        assert result is None or (result is not None and "/assets/" not in result), (
            f"GAP-031 FAIL: bare /assets/ proxy URL emitted for thumbnail: {result}"
        )

    def test_s3_published_data_still_returns_presigned_url(self):
        """S3 published data must still produce a presigned URL (not None)."""
        from unittest.mock import MagicMock

        mock_provider = MagicMock()
        mock_provider.generate_presigned_get_url.return_value = (
            "https://s3.example.com/signed"
        )
        result = resolve_asset_url(
            "/uploads/test.tif",
            storage_backend="s3",
            record_status="published",
            roles=["data"],
            public_api_url=PUBLIC_API_URL,
            storage_provider=mock_provider,
        )
        assert result == "https://s3.example.com/signed"

    def test_no_proxy_url_contains_assets_slash(self):
        """After fix, no code path through resolve_asset_url produces /assets/."""
        # local + published + data
        assert _no_assets_path(
            resolve_asset_url(
                "/uploads/a.tif",
                storage_backend="local",
                record_status="published",
                roles=["data"],
                public_api_url=PUBLIC_API_URL,
            )
        )
        # local + draft + data
        assert _no_assets_path(
            resolve_asset_url(
                "/uploads/a.tif",
                storage_backend="local",
                record_status="draft",
                roles=["data"],
                public_api_url=PUBLIC_API_URL,
            )
        )
        # local + published + thumbnail
        assert _no_assets_path(
            resolve_asset_url(
                "/uploads/t.png",
                storage_backend="local",
                record_status="published",
                roles=["thumbnail"],
                public_api_url=PUBLIC_API_URL,
            )
        )


def _no_assets_path(url: str | None) -> bool:
    """Return True when the URL does not contain '/assets/'."""
    return url is None or "/assets/" not in url


class TestRemoteHrefPassThrough:
    """feat(#1692): a by-reference origin href is served verbatim.

    A STAC import persists the publisher's absolute http(s) COG URL as a
    ``dataset_assets`` href. That URL is already public in the origin
    catalog — it is not managed storage, so neither the presign branch nor
    the GAP-031 refusal applies, on any backend and at any record status.
    """

    def test_https_href_passes_through_on_local_storage(self):
        href = "https://cogs.example.com/scenes/scene-1.tif"
        assert (
            resolve_asset_url(
                href,
                storage_backend="local",
                record_status="published",
                roles=["data"],
                public_api_url=PUBLIC_API_URL,
            )
            == href
        )

    def test_https_href_is_not_presigned_on_s3_storage(self):
        """The presign branch must never mangle a remote URL into a storage
        key — the pass-through is checked first."""
        from unittest.mock import MagicMock

        mock_provider = MagicMock()
        href = "https://cogs.example.com/scenes/scene-1.tif"
        result = resolve_asset_url(
            href,
            storage_backend="s3",
            record_status="published",
            roles=["data"],
            public_api_url=PUBLIC_API_URL,
            storage_provider=mock_provider,
        )
        assert result == href
        mock_provider.generate_presigned_get_url.assert_not_called()

    def test_https_href_survives_a_non_published_status(self):
        """Status gates protect GeoLens-held bytes; a third-party public URL
        holds none. The item endpoint's visibility filter is what gates who
        sees the record at all."""
        href = "http://cogs.example.com/scenes/scene-1.tif"
        assert (
            resolve_asset_url(
                href,
                storage_backend="local",
                record_status="draft",
                roles=["data"],
                public_api_url=PUBLIC_API_URL,
            )
            == href
        )

    def test_storage_relative_keys_still_take_the_managed_paths(self):
        """The pass-through matches only absolute http(s) hrefs — an s3://
        URI or a storage-relative key behaves exactly as before."""
        assert (
            resolve_asset_url(
                "uploads/a.tif",
                storage_backend="local",
                record_status="published",
                roles=["data"],
                public_api_url=PUBLIC_API_URL,
            )
            is None
        )
        assert (
            resolve_asset_url(
                "s3://bucket/uploads/a.tif",
                storage_backend="local",
                record_status="published",
                roles=["data"],
                public_api_url=PUBLIC_API_URL,
            )
            is None
        )

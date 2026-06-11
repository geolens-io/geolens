"""Unit tests for asset URL security rules.

Verifies:
  - Published S3 data assets get presigned URLs
  - Published thumbnails: no unsafe proxy URL (GAP-031: returns None for local storage)
  - Draft/ready/internal records: no unsafe proxy URL (GAP-031: returns None)
  - Local storage always returns None (no backend route for /assets/ — GAP-031)
  - ASSET-07: no frontend stac_assets references (confirmed)

GAP-031: resolve_asset_url no longer emits /assets/{key} proxy URLs for local
storage or non-signed paths. The nginx /assets/ location serves the SPA bundle,
not storage files, so the proxy URL was dead and a potential collision surface.
Since dataset_assets is never populated (BUG-041), this changes no live output.

# ASSET-07 CONFIRMATION: grep -r stac_assets frontend/src --include='*.ts' --include='*.tsx'
# returns zero matches. Frontend already uses 'assets' dict. No migration needed.
"""

from unittest.mock import MagicMock

from app.platform.assets.urls import _extract_storage_key, resolve_asset_url

PUBLIC_API_URL = "http://localhost:8000"


class TestResolveAssetUrl:
    def test_draft_returns_none_not_proxy(self):
        """GAP-031: draft assets return None (no dead /assets/ proxy URL)."""
        url = resolve_asset_url(
            "/uploads/test.tif",
            storage_backend="s3",
            record_status="draft",
            roles=["data"],
            public_api_url=PUBLIC_API_URL,
        )
        assert url is None, f"Expected None for draft asset, got: {url}"

    def test_ready_returns_none_not_proxy(self):
        """GAP-031: ready assets return None (no dead /assets/ proxy URL)."""
        url = resolve_asset_url(
            "/uploads/test.tif",
            storage_backend="s3",
            record_status="ready",
            roles=["data"],
            public_api_url=PUBLIC_API_URL,
        )
        assert url is None

    def test_internal_returns_none_not_proxy(self):
        """GAP-031: internal assets return None (no dead /assets/ proxy URL)."""
        url = resolve_asset_url(
            "/uploads/test.tif",
            storage_backend="s3",
            record_status="internal",
            roles=["data"],
            public_api_url=PUBLIC_API_URL,
        )
        assert url is None

    def test_s3_published_data_signed(self):
        """S3 published data assets still get a presigned URL."""
        mock_provider = MagicMock()
        mock_provider.generate_presigned_get_url.return_value = (
            "https://s3.example.com/signed"
        )
        url = resolve_asset_url(
            "/uploads/test.tif",
            storage_backend="s3",
            record_status="published",
            roles=["data"],
            public_api_url=PUBLIC_API_URL,
            storage_provider=mock_provider,
        )
        assert url == "https://s3.example.com/signed"
        mock_provider.generate_presigned_get_url.assert_called_once()

    def test_s3_published_thumbnail_returns_none_without_provider(self):
        """GAP-031: S3 thumbnail without a storage_provider returns None."""
        url = resolve_asset_url(
            "/uploads/thumb.png",
            storage_backend="s3",
            record_status="published",
            roles=["thumbnail"],
            public_api_url=PUBLIC_API_URL,
        )
        # No storage_provider → cannot produce a presigned URL → None (GAP-031)
        assert url is None

    def test_local_published_data_returns_none(self):
        """GAP-031: local storage published data returns None (no /assets/ route)."""
        url = resolve_asset_url(
            "/uploads/test.tif",
            storage_backend="local",
            record_status="published",
            roles=["data"],
            public_api_url=PUBLIC_API_URL,
        )
        assert url is None, f"Expected None for local storage asset, got: {url}"

    def test_presign_ttl_passed(self):
        """presign_ttl is forwarded to the storage provider."""
        mock_provider = MagicMock()
        mock_provider.generate_presigned_get_url.return_value = "https://signed"
        resolve_asset_url(
            "/uploads/test.tif",
            storage_backend="s3",
            record_status="published",
            roles=["data"],
            public_api_url=PUBLIC_API_URL,
            storage_provider=mock_provider,
            presign_ttl=7200,
        )
        mock_provider.generate_presigned_get_url.assert_called_once_with(
            "uploads/test.tif", expiration=7200
        )

    def test_no_assets_slash_in_any_result(self):
        """GAP-031: /assets/ prefix must never appear in resolve_asset_url output."""
        cases = [
            dict(
                storage_backend="local",
                record_status="published",
                roles=["data"],
            ),
            dict(
                storage_backend="local",
                record_status="draft",
                roles=["data"],
            ),
            dict(
                storage_backend="s3",
                record_status="draft",
                roles=["data"],
            ),
            dict(
                storage_backend="local",
                record_status="published",
                roles=["thumbnail"],
            ),
        ]
        for kwargs in cases:
            result = resolve_asset_url(
                "/uploads/test.tif",
                public_api_url=PUBLIC_API_URL,
                **kwargs,
            )
            assert result is None or "/assets/" not in result, (
                f"GAP-031: /assets/ proxy URL still emitted: {result} for {kwargs}"
            )


class TestExtractStorageKey:
    def test_leading_slash_stripped(self):
        assert _extract_storage_key("/uploads/test.tif") == "uploads/test.tif"

    def test_s3_uri_extracted(self):
        assert (
            _extract_storage_key("s3://bucket/path/to/file.tif") == "path/to/file.tif"
        )

    def test_no_leading_slash(self):
        assert _extract_storage_key("uploads/test.tif") == "uploads/test.tif"

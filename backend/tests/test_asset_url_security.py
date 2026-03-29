"""Unit tests for asset URL security rules.

Verifies:
  - Published S3 data assets get presigned URLs
  - Published thumbnails get public (proxy) URLs
  - Draft/ready/internal records always get proxy URLs
  - Local storage always gets proxy URLs
  - ASSET-07: no frontend stac_assets references (confirmed)

# ASSET-07 CONFIRMATION: grep -r stac_assets frontend/src --include='*.ts' --include='*.tsx'
# returns zero matches. Frontend already uses 'assets' dict. No migration needed.
"""

from unittest.mock import MagicMock


from app.assets.urls import resolve_asset_url, _extract_storage_key


PUBLIC_API_URL = "http://localhost:8000"


class TestResolveAssetUrl:
    def test_draft_always_proxy(self):
        url = resolve_asset_url(
            "/uploads/test.tif",
            storage_backend="s3",
            record_status="draft",
            roles=["data"],
            public_api_url=PUBLIC_API_URL,
        )
        assert "/assets/" in url
        assert "localhost:8000" in url

    def test_ready_always_proxy(self):
        url = resolve_asset_url(
            "/uploads/test.tif",
            storage_backend="s3",
            record_status="ready",
            roles=["data"],
            public_api_url=PUBLIC_API_URL,
        )
        assert "/assets/" in url

    def test_internal_always_proxy(self):
        url = resolve_asset_url(
            "/uploads/test.tif",
            storage_backend="s3",
            record_status="internal",
            roles=["data"],
            public_api_url=PUBLIC_API_URL,
        )
        assert "/assets/" in url

    def test_s3_published_data_signed(self):
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

    def test_s3_published_thumbnail_public(self):
        url = resolve_asset_url(
            "/uploads/thumb.png",
            storage_backend="s3",
            record_status="published",
            roles=["thumbnail"],
            public_api_url=PUBLIC_API_URL,
        )
        assert "/assets/" in url  # Proxy URL (public, no auth needed)

    def test_local_published_data_proxy(self):
        url = resolve_asset_url(
            "/uploads/test.tif",
            storage_backend="local",
            record_status="published",
            roles=["data"],
            public_api_url=PUBLIC_API_URL,
        )
        assert "/assets/" in url

    def test_presign_ttl_passed(self):
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


class TestExtractStorageKey:
    def test_leading_slash_stripped(self):
        assert _extract_storage_key("/uploads/test.tif") == "uploads/test.tif"

    def test_s3_uri_extracted(self):
        assert (
            _extract_storage_key("s3://bucket/path/to/file.tif") == "path/to/file.tif"
        )

    def test_no_leading_slash(self):
        assert _extract_storage_key("uploads/test.tif") == "uploads/test.tif"

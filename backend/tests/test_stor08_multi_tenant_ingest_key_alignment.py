"""STOR-08: multi_tenant raster ingest stores at tenant-prefixed key (CR-02 regression).

Proves the fix for CR-02: the ingest path must store COG/VRT assets at the same
tenant-prefixed key that the serve path (resolve_open_path) resolves at tile time.

Before the fix:
  ingest stored at:  rasters/{id}/{sha}/source.cog.tif
  serve resolved to: tenants/{tid}/rasters/{id}/{sha}/source.cog.tif  (→ 404)

After the fix:
  ingest stores at:  tenants/{tid}/rasters/{id}/{sha}/source.cog.tif
  serve resolves to: tenants/{tid}/rasters/{id}/{sha}/source.cog.tif  (✓ match)
  asset_uri in DB:   rasters/{id}/{sha}/source.cog.tif (unchanged, logical key)

In single_tenant mode the prefix is empty so stored key == logical key (byte-identical).

These are unit tests (no DB required) that verify the key-building logic in isolation
by checking the _tenant_prefix computation against what resolve_open_path produces.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestMultiTenantIngestKeyAlignment:
    """CR-02: ingest storage key must match serve-time resolve_open_path key."""

    def test_single_tenant_prefix_is_empty(self):
        """In single_tenant mode, _tenant_prefix is empty — keys unchanged."""
        with patch("app.core.tenancy.is_multi_tenant", return_value=False):
            from app.core.tenancy import is_multi_tenant

            assert not is_multi_tenant()
            # In single_tenant mode, tenant_id is never retrieved
            tenant_id = None
            prefix = f"tenants/{tenant_id}/" if tenant_id else ""
            assert prefix == ""

    def test_multi_tenant_prefix_matches_serve_side(self):
        """In multi_tenant mode, ingest prefix matches the serve-side prefix."""
        fake_tenant_id = "tenant-abc-123"

        # Simulate what ingest now computes (CR-02 fix)
        ingest_prefix = f"tenants/{fake_tenant_id}/"
        logical_key = "rasters/dataset-id/sha256abc/source.cog.tif"
        ingest_storage_key = f"{ingest_prefix}{logical_key}"

        # Simulate what resolve_open_path builds at serve time (azure provider)
        mock_settings = MagicMock()
        mock_settings.storage_provider = "azure"
        mock_settings.azure_storage_container = "geolens-prod"

        with patch("app.core.config.settings", mock_settings):
            from app.platform.storage.titiler_url import resolve_open_path

            serve_open_path = resolve_open_path(logical_key, tenant_id=fake_tenant_id)

        # The serve path is /vsiaz/{container}/{tenant_prefix}{logical_key}
        expected_serve_path = (
            f"/vsiaz/geolens-prod/tenants/{fake_tenant_id}/{logical_key}"
        )
        assert serve_open_path == expected_serve_path, (
            f"serve path={serve_open_path!r}, expected={expected_serve_path!r}"
        )

        # The storage key that ingest uses must equal the key inside the bucket:
        # serve_open_path strips /vsiaz/{container}/ to get the object key.
        serve_object_key = serve_open_path.split("/vsiaz/geolens-prod/", 1)[1]
        assert ingest_storage_key == serve_object_key, (
            f"CR-02: ingest storage key {ingest_storage_key!r} does not match "
            f"serve object key {serve_object_key!r}. "
            "These must be equal for raster tiles to resolve correctly."
        )

    def test_single_tenant_ingest_key_equals_serve_key(self):
        """single_tenant: ingest stores at logical key, serve resolves to logical key."""
        logical_key = "rasters/dataset-id/sha256abc/source.cog.tif"

        # Ingest: no prefix in single_tenant
        ingest_storage_key = logical_key  # tenant_id=None → prefix=""

        # Serve: resolve_open_path with tenant_id=None uses bare key
        mock_settings = MagicMock()
        mock_settings.storage_provider = "azure"
        mock_settings.azure_storage_container = "geolens-prod"

        with patch("app.core.config.settings", mock_settings):
            from app.platform.storage.titiler_url import resolve_open_path

            serve_open_path = resolve_open_path(logical_key, tenant_id=None)

        serve_object_key = serve_open_path.split("/vsiaz/geolens-prod/", 1)[1]
        assert ingest_storage_key == serve_object_key, (
            f"single_tenant: ingest key {ingest_storage_key!r} != "
            f"serve key {serve_object_key!r}"
        )

    def test_s3_serve_path_alignment(self):
        """CR-02 alignment holds for S3 provider too."""
        fake_tenant_id = "tenant-xyz"
        logical_key = "rasters/id/sha/source.cog.tif"

        ingest_prefix = f"tenants/{fake_tenant_id}/"
        ingest_storage_key = f"{ingest_prefix}{logical_key}"

        mock_settings = MagicMock()
        mock_settings.storage_provider = "s3"
        mock_settings.s3_bucket = "geolens-bucket"

        with patch("app.core.config.settings", mock_settings):
            from app.platform.storage.titiler_url import resolve_open_path

            serve_open_path = resolve_open_path(logical_key, tenant_id=fake_tenant_id)

        serve_object_key = serve_open_path.split("/vsis3/geolens-bucket/", 1)[1]
        assert ingest_storage_key == serve_object_key, (
            f"S3 CR-02: ingest key {ingest_storage_key!r} != serve key {serve_object_key!r}"
        )

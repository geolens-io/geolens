"""Unit tests for resolve_open_path provider + tenant dispatch matrix (STOR-02 / Phase 1210).

Pins the full dispatch table:
  - local  + tenant_id=None -> {upload_staging_dir}/{asset_uri}
  - s3     + tenant_id=None -> /vsis3/{s3_bucket}/{asset_uri}
  - azure  + tenant_id=None -> /vsiaz/{azure_storage_container}/{asset_uri}
  - s3     + tenant_id="T"  -> /vsis3/{s3_bucket}/tenants/T/{asset_uri}
  - azure  + tenant_id="T"  -> /vsiaz/{azure_storage_container}/tenants/T/{asset_uri}
  - http(s):// asset_uri    -> unchanged regardless of provider/tenant

The single_tenant byte-identical assertion (row 2, s3 + tenant_id=None) proves
STOR-02: the seam produces the exact string the pre-1210 inline block in
tiles/router.py would have produced for s3 + single_tenant.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _mock_settings(
    *,
    storage_provider: str = "local",
    upload_staging_dir: str = "/app/staging",
    s3_bucket: str | None = None,
    azure_storage_container: str | None = None,
) -> MagicMock:
    """Build a minimal settings mock for resolve_open_path tests."""
    m = MagicMock()
    m.storage_provider = storage_provider
    m.upload_staging_dir = upload_staging_dir
    m.s3_bucket = s3_bucket
    m.azure_storage_container = azure_storage_container
    return m


class TestResolveOpenPathProviderMatrix:
    """Full provider × tenant dispatch table for resolve_open_path."""

    def _call(
        self,
        asset_uri: str,
        *,
        tenant_id: str | None,
        settings_kwargs: dict,
    ) -> str:
        from app.platform.storage.titiler_url import resolve_open_path

        mock = _mock_settings(**settings_kwargs)
        with patch("app.core.config.settings", mock):
            return resolve_open_path(asset_uri, tenant_id=tenant_id)

    # --- Row 1: local + no tenant ----------------------------------------

    def test_local_no_tenant(self):
        """local + tenant_id=None -> {upload_staging_dir}/{asset_uri} (bare path)."""
        result = self._call(
            "rasters/abc/cog.tif",
            tenant_id=None,
            settings_kwargs=dict(
                storage_provider="local", upload_staging_dir="/data/staging"
            ),
        )
        assert result == "/data/staging/rasters/abc/cog.tif"

    def test_local_no_tenant_prefix(self):
        """local provider NEVER emits a tenants/ prefix even when tenant_id provided."""
        result = self._call(
            "rasters/abc/cog.tif",
            tenant_id="tenant-x",
            settings_kwargs=dict(
                storage_provider="local", upload_staging_dir="/data/staging"
            ),
        )
        # local uses bare asset_uri (not the tenant-keyed path)
        assert "tenants/" not in result
        assert result == "/data/staging/rasters/abc/cog.tif"

    # --- Row 2: s3 + no tenant (single_tenant byte-identical) --------------

    def test_s3_no_tenant_byte_identical(self):
        """s3 + tenant_id=None -> /vsis3/{s3_bucket}/{asset_uri}.

        STOR-02 byte-identical assertion: this exact string is what the
        pre-1210 inline block in tiles/router.py produced for s3 + single_tenant.
        """
        bucket = "my-geolens-bucket"
        asset = "rasters/xyz/source.cog.tif"
        result = self._call(
            asset,
            tenant_id=None,
            settings_kwargs=dict(storage_provider="s3", s3_bucket=bucket),
        )
        # Literal comparison: identical to f"/vsis3/{bucket}/{asset}"
        assert result == f"/vsis3/{bucket}/{asset}"

    # --- Row 3: azure + no tenant ----------------------------------------

    def test_azure_no_tenant(self):
        """azure + tenant_id=None -> /vsiaz/{azure_storage_container}/{asset_uri}."""
        container = "geolens-blobs"
        asset = "rasters/abc/cog.tif"
        result = self._call(
            asset,
            tenant_id=None,
            settings_kwargs=dict(
                storage_provider="azure",
                azure_storage_container=container,
            ),
        )
        assert result == f"/vsiaz/{container}/{asset}"

    # --- Row 4: s3 + tenant_id -------------------------------------------

    def test_s3_with_tenant(self):
        """s3 + tenant_id='T' -> /vsis3/{s3_bucket}/tenants/T/{asset_uri}."""
        bucket = "shared-bucket"
        asset = "rasters/img/cog.tif"
        tid = "acme-corp"
        result = self._call(
            asset,
            tenant_id=tid,
            settings_kwargs=dict(storage_provider="s3", s3_bucket=bucket),
        )
        assert result == f"/vsis3/{bucket}/tenants/{tid}/{asset}"

    def test_s3_tenant_prefix_structure(self):
        """s3 tenant key is tenants/{tenant_id}/{asset_uri} — both components present."""
        result = self._call(
            "some/file.tif",
            tenant_id="t99",
            settings_kwargs=dict(storage_provider="s3", s3_bucket="bkt"),
        )
        assert result.startswith("/vsis3/bkt/tenants/t99/")
        assert result.endswith("some/file.tif")

    # --- Row 5: azure + tenant_id ----------------------------------------

    def test_azure_with_tenant(self):
        """azure + tenant_id='T' -> /vsiaz/{azure_storage_container}/tenants/T/{asset_uri}."""
        container = "geolens-blobs"
        asset = "rasters/img/cog.tif"
        tid = "widget-co"
        result = self._call(
            asset,
            tenant_id=tid,
            settings_kwargs=dict(
                storage_provider="azure",
                azure_storage_container=container,
            ),
        )
        assert result == f"/vsiaz/{container}/tenants/{tid}/{asset}"

    # --- Row 6: remote http(s) pass-through --------------------------------

    def test_http_asset_passthrough(self):
        """http:// asset_uri is returned unchanged regardless of provider."""
        url = "http://stac.example.com/assets/cog.tif"
        result = self._call(
            url,
            tenant_id=None,
            settings_kwargs=dict(storage_provider="local"),
        )
        assert result == url

    def test_https_asset_passthrough(self):
        """https:// asset_uri is returned unchanged regardless of provider."""
        url = "https://stac.example.com/data/img.tif"
        result = self._call(
            url,
            tenant_id=None,
            settings_kwargs=dict(storage_provider="s3", s3_bucket="bkt"),
        )
        assert result == url

    def test_https_passthrough_with_tenant(self):
        """Remote URL is never prefixed even when tenant_id is provided."""
        url = "https://stac.example.com/file.tif"
        result = self._call(
            url,
            tenant_id="some-tenant",
            settings_kwargs=dict(storage_provider="azure", azure_storage_container="c"),
        )
        assert result == url

    # --- Path traversal / scheme injection guard (WR-01) -------------------

    def test_absolute_path_asset_uri_rejected(self):
        """asset_uri starting with '/' raises ValueError (WR-01 defense-in-depth).

        Previously a suspicious path like /etc/passwd was prepended with the
        provider prefix (e.g. /vsis3/bkt//etc/passwd) which GDAL may resolve
        depending on the driver. Now it is rejected before any prefix is built.
        """
        import pytest

        with pytest.raises(ValueError, match="absolute path"):
            self._call(
                "/etc/passwd",
                tenant_id=None,
                settings_kwargs=dict(storage_provider="s3", s3_bucket="bkt"),
            )

    def test_dotdot_traversal_rejected(self):
        """asset_uri containing '..' raises ValueError (WR-01 defense-in-depth)."""
        import pytest

        with pytest.raises(ValueError, match="path-traversal"):
            self._call(
                "../../etc/passwd",
                tenant_id=None,
                settings_kwargs=dict(storage_provider="s3", s3_bucket="bkt"),
            )

    def test_dotdot_cross_tenant_rejected(self):
        """asset_uri with '..' cannot escape tenant prefix (WR-01 multi-tenant guard)."""
        import pytest

        with pytest.raises(ValueError, match="path-traversal"):
            self._call(
                "../../tenants/victim/rasters/X/cog.tif",
                tenant_id="attacker",
                settings_kwargs=dict(
                    storage_provider="azure", azure_storage_container="c"
                ),
            )

    def test_embedded_vsi_scheme_rejected(self):
        """asset_uri embedding '/vsicurl/' raises ValueError (WR-01 injection guard)."""
        import pytest

        with pytest.raises(ValueError, match="disallowed pattern"):
            self._call(
                "rasters/legit/vsicurl/http://evil.example.com/cog.tif",
                tenant_id=None,
                settings_kwargs=dict(storage_provider="s3", s3_bucket="bkt"),
            )

    def test_embedded_url_scheme_rejected(self):
        """asset_uri embedding '://' raises ValueError (scheme injection guard)."""
        import pytest

        with pytest.raises(ValueError, match="disallowed pattern"):
            self._call(
                "rasters/id/sha/ftp://evil.example.com/evil.tif",
                tenant_id=None,
                settings_kwargs=dict(
                    storage_provider="azure", azure_storage_container="c"
                ),
            )

    def test_normal_relative_key_passes(self):
        """A normal relative logical key (no suspicious patterns) passes validation."""
        result = self._call(
            "rasters/abc/sha256/source.cog.tif",
            tenant_id=None,
            settings_kwargs=dict(storage_provider="s3", s3_bucket="bkt"),
        )
        assert result == "/vsis3/bkt/rasters/abc/sha256/source.cog.tif"

    # --- single_tenant symmetry: tenant_id=None always drops prefix --------

    def test_s3_none_tenant_has_no_tenants_prefix(self):
        """s3 + tenant_id=None produces NO tenants/ segment."""
        result = self._call(
            "k/file.tif",
            tenant_id=None,
            settings_kwargs=dict(storage_provider="s3", s3_bucket="b"),
        )
        assert "tenants/" not in result

    def test_azure_none_tenant_has_no_tenants_prefix(self):
        """azure + tenant_id=None produces NO tenants/ segment."""
        result = self._call(
            "k/file.tif",
            tenant_id=None,
            settings_kwargs=dict(
                storage_provider="azure",
                azure_storage_container="c",
            ),
        )
        assert "tenants/" not in result


class TestResolveOpenPathImportStructure:
    """Structural assertions: resolve_open_path lives in titiler_url.py and is importable."""

    def test_importable(self):
        """resolve_open_path is importable from the storage seam module."""
        from app.platform.storage.titiler_url import resolve_open_path  # noqa: F401

    def test_defined_in_titiler_url(self):
        """resolve_open_path.__module__ is app.platform.storage.titiler_url."""
        from app.platform.storage.titiler_url import resolve_open_path

        assert resolve_open_path.__module__ == "app.platform.storage.titiler_url"

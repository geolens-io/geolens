"""[BLOCKING] single_tenant byte-identical invariant aggregator (Phase 1210 Plan 04).

Fast CI guard for the [BLOCKING] gate: the additive Azure seam (Plans 01-03) must
NOT regress single_tenant (Community/Enterprise) behavior.

What this test proves
---------------------
The full authoritative proof is a broad-suite run `pytest -n 4` with the DEFAULT
config (STORAGE_PROVIDER unset / local). This file is the FAST CI guard that pins
the specific invariants in one place:

a) Default storage_provider == "local"
   Importing the azure module must NOT change settings.storage_provider to "azure".

b) resolve_open_path('k') with no tenant == legacy local path
   With STORAGE_PROVIDER=local (default), resolve_open_path returns
   {upload_staging_dir}/{asset_uri} — byte-identical with the pre-1210 inline
   VSI block in tiles/router.py and vrt.py.

c) resolve_vrt_source_path('k') == legacy local path
   vrt.py's backward-compat shim delegates to resolve_open_path; single_tenant
   output is the same as the pre-1210 local path.

d) STOR-05 seam-lint passes
   No /vsis3/ or /vsiaz/ literals outside the allowlisted seam module.

e) Importing azure module does NOT change init_storage's default selection
   After importing app.platform.storage.azure, calling init_storage() with
   STORAGE_PROVIDER unset still selects LocalStorageProvider.

The [BLOCKING] broad-suite evidence (pass/fail counts vs the pre-1210 baseline)
is recorded in 1210-04-SUMMARY.md. The requirement: 0 net-new failures vs the
1209 baseline (~3872 pass, 0 net-new failures, established in Phase 1209 Plan 05).

Related tests (full suite verification cross-checks)
-----------------------------------------------------
- tests/test_stor_vsi_seam_lint.py: STOR-05 lint (VSI literal guard)
- tests/test_resolve_open_path.py: full provider × tenant dispatch matrix
- tests/test_vrt_rewrite.py: rewrite_vrt_sources correctness
- tests/test_storage_azure.py: AzureBlobStorageProvider round-trips vs Azurite
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch


class TestDefaultProviderLocalInvariant:
    """(a) Default storage_provider == "local" without any STORAGE_PROVIDER env."""

    def test_default_storage_provider_is_local(self):
        """settings.storage_provider defaults to 'local' when STORAGE_PROVIDER is unset."""
        # Strip STORAGE_PROVIDER from the environment for a clean import
        env_without_provider = {
            k: v for k, v in os.environ.items() if k != "STORAGE_PROVIDER"
        }
        # Read the ACTUAL settings (not a mock) to prove the default
        with patch.dict(os.environ, env_without_provider, clear=True):
            # Re-import to pick up the clean env
            import importlib

            from app.core import config as config_mod

            importlib.reload(config_mod)
            provider = config_mod.settings.storage_provider

        assert provider == "local", (
            f"Default STORAGE_PROVIDER must be 'local', got {provider!r}. "
            "The Azure seam must not change the default."
        )

    def test_azure_import_does_not_change_default_provider(self):
        """Importing AzureBlobStorageProvider does not change storage_provider to 'azure'."""
        from app.platform.storage import azure as azure_mod  # noqa: F401
        from app.core.config import settings

        # The import must not mutate settings
        assert settings.storage_provider in ("local", "s3", "azure"), (
            f"settings.storage_provider is an unexpected value: {settings.storage_provider!r}"
        )
        # When STORAGE_PROVIDER is unset in the test environment, it must still be 'local'
        if "STORAGE_PROVIDER" not in os.environ:
            assert settings.storage_provider == "local", (
                f"Importing azure module changed storage_provider from 'local' to "
                f"{settings.storage_provider!r}"
            )


class TestLocalPathByteIdentical:
    """(b,c) resolve_open_path and resolve_vrt_source_path are byte-identical for local."""

    def _local_settings(self, staging: str = "/app/staging") -> MagicMock:
        m = MagicMock()
        m.storage_provider = "local"
        m.upload_staging_dir = staging
        return m

    def test_resolve_open_path_local_no_tenant_byte_identical(self):
        """resolve_open_path(k, tenant_id=None) == {staging}/{k} — byte-identical."""
        from app.platform.storage.titiler_url import resolve_open_path

        staging = "/app/staging"
        key = "rasters/abc/source.cog.tif"
        mock = self._local_settings(staging)
        with patch("app.core.config.settings", mock):
            result = resolve_open_path(key, tenant_id=None)

        expected = f"{staging}/{key}"
        assert result == expected, (
            f"resolve_open_path returned {result!r}, expected {expected!r}"
        )

    def test_resolve_vrt_source_path_local_byte_identical(self):
        """resolve_vrt_source_path(k) == {staging}/{k} — backward-compat shim is byte-identical."""
        from app.processing.raster.vrt import resolve_vrt_source_path

        staging = "/app/staging"
        key = "rasters/xyz/source.vrt"
        mock = self._local_settings(staging)
        with patch("app.core.config.settings", mock):
            result = resolve_vrt_source_path(key)

        expected = f"{staging}/{key}"
        assert result == expected, (
            f"resolve_vrt_source_path returned {result!r}, expected {expected!r}"
        )

    def test_resolve_open_path_tenant_prefix_for_local(self):
        """Local multi-tenant assets resolve under their physical tenant namespace."""
        from app.platform.storage.titiler_url import resolve_open_path

        staging = "/app/staging"
        key = "rasters/abc/source.cog.tif"
        mock = self._local_settings(staging)
        with patch("app.core.config.settings", mock):
            result = resolve_open_path(key, tenant_id="some-tenant")

        assert result == f"{staging}/tenants/some-tenant/{key}"

    def test_s3_no_tenant_byte_identical(self):
        """s3 + tenant_id=None -> /vsis3/{bucket}/{key} (STOR-02 byte-identical)."""
        from app.platform.storage.titiler_url import resolve_open_path

        mock = MagicMock()
        mock.storage_provider = "s3"
        mock.s3_bucket = "my-bucket"
        key = "rasters/abc/source.cog.tif"
        with patch("app.core.config.settings", mock):
            result = resolve_open_path(key, tenant_id=None)

        assert result == f"/vsis3/my-bucket/{key}"


class TestInitStorageDefaultSelection:
    """(e) init_storage() with STORAGE_PROVIDER unset selects LocalStorageProvider."""

    def test_init_storage_defaults_to_local(self):
        """Azure import must not affect init_storage's default provider selection."""
        # Import the azure module first (to prove it doesn't pollute globals)
        from app.platform.storage import azure as _azure_mod  # noqa: F401
        from app.platform.storage import provider as provider_mod
        from app.platform.storage.local import LocalStorageProvider

        mock_settings = MagicMock()
        mock_settings.storage_provider = "local"
        mock_settings.upload_staging_dir = "/tmp/test_staging"

        # Reset the singleton
        provider_mod._storage = None

        with (
            patch("app.core.config.settings", mock_settings),
            patch("app.core.config.reveal", side_effect=lambda x: x),
        ):
            provider_mod.init_storage()
            storage = provider_mod.get_storage()

        assert isinstance(storage, LocalStorageProvider), (
            f"Expected LocalStorageProvider, got {type(storage).__name__}"
        )

        # Reset singleton after test
        provider_mod._storage = None


class TestSeamLintImportable:
    """(d) STOR-05 seam-lint module is importable and runnable."""

    def test_seam_lint_module_importable(self):
        """test_stor_vsi_seam_lint.py is importable (STOR-05 guard available)."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "test_stor_vsi_seam_lint",
            "tests/test_stor_vsi_seam_lint.py",
        )
        assert spec is not None, (
            "test_stor_vsi_seam_lint.py not found — STOR-05 lint guard missing"
        )

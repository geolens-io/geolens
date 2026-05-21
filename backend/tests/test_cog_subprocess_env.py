"""KNOWN-03 (Phase 1071): GDAL CLI subprocess env overlay coverage.

v1015 Phase 1068 IA-P1-03 scoped ``_VRT_SAFE_ENV`` (with
``CPL_VSIL_CURL_ALLOWED_EXTENSIONS``, ``VRT_VIRTUAL_OVERVIEWS``,
``GDAL_HTTP_FOLLOWLOCATION``) to ``gdalbuildvrt`` only via ``_build_vrt``.
Phase 1071 extends the same clamp to the sibling raster subprocesses in
``cog.py``: ``gdaladdo`` (overview generation), ``gdalwarp`` (CRS
reprojection), and ``gdal_translate`` (COG translation).

These tests pin the captured ``env=`` kwarg for each subprocess invocation
so a future refactor cannot silently regress the overlay shape.

Mirrors ``backend/tests/test_vrt_hardening.py::TestGdalBuildVrtSafeEnv``.

Requirement: KNOWN-03
Phase: 1071
"""

from contextlib import contextmanager
from unittest import mock


# The three clamp keys/values must match _VRT_SAFE_ENV in
# backend/app/processing/raster/vrt.py:17. Re-stated here so a careless
# edit to that dict trips these tests.
EXPECTED_CLAMPS = {
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": "tif,tiff,vrt",
    "VRT_VIRTUAL_OVERVIEWS": "NO",
    "GDAL_HTTP_FOLLOWLOCATION": "NO",
}


def _assert_clamps(env: dict) -> None:
    """All three KNOWN-03 clamps must be set on the captured env."""
    assert env is not None, "subprocess.run was invoked without env="
    for key, expected in EXPECTED_CLAMPS.items():
        assert env.get(key) == expected, (
            f"clamp {key} missing/wrong: expected {expected!r}, got {env.get(key)!r}"
        )


@contextmanager
def _capture_subprocess_runs(monkeypatch):
    """Patch ``cog.subprocess.run`` to capture each (cmd, env) tuple.

    Returns a list that callers can inspect after the patched code path runs.
    Each entry is ``(cmd, env_dict_or_None)``.
    """
    captured: list[tuple[list[str], dict | None]] = []

    def _fake_run(cmd, *args, **kwargs):
        env = kwargs.get("env")
        # Copy the dict so later mutations by the system under test don't
        # affect our snapshot.
        captured.append((list(cmd), dict(env) if env is not None else None))
        return mock.Mock(returncode=0, stderr="", stdout="")

    from app.processing.raster import cog as cog_module

    monkeypatch.setattr(cog_module.subprocess, "run", _fake_run)
    yield captured


# ---------------------------------------------------------------------------
# prepare_with_overviews → gdaladdo
# ---------------------------------------------------------------------------


class TestPrepareWithOverviewsSafeEnv:
    def test_gdaladdo_subprocess_inherits_clamps(self, tmp_path, monkeypatch):
        """``prepare_with_overviews`` invokes ``gdaladdo`` with the safety clamps."""
        from app.processing.raster import cog as cog_module

        # Stub the source TIFF and the rasterio.open() probe that decides
        # whether to skip gdaladdo (we want gdaladdo to run, so report
        # "no internal overviews").
        src = tmp_path / "src.tif"
        src.write_bytes(b"\x00" * 8)

        fake_dataset = mock.MagicMock()
        fake_dataset.count = 1
        fake_dataset.overviews.return_value = []  # no internal -> gdaladdo runs

        fake_ctx = mock.MagicMock()
        fake_ctx.__enter__.return_value = fake_dataset
        fake_ctx.__exit__.return_value = False

        import rasterio

        monkeypatch.setattr(rasterio, "open", lambda *_a, **_k: fake_ctx)

        with _capture_subprocess_runs(monkeypatch) as captured:
            cog_module.prepare_with_overviews(str(src), "uint8")

        # Find the gdaladdo invocation
        gdaladdo_calls = [(cmd, env) for cmd, env in captured if cmd and cmd[0] == "gdaladdo"]
        assert gdaladdo_calls, f"gdaladdo was not invoked; captured: {[c[0] for c in captured]}"
        _, env = gdaladdo_calls[0]
        _assert_clamps(env)
        # Per-call extras (GDAL_CACHEMAX, COMPRESS_OVERVIEW) must merge in too.
        assert env.get("GDAL_CACHEMAX") == "200"
        assert env.get("COMPRESS_OVERVIEW") == "DEFLATE"

    def test_gdaladdo_inherits_clamps_with_custom_compression(
        self, tmp_path, monkeypatch
    ):
        """Custom compression flows into the extras layer without losing clamps."""
        from app.processing.raster import cog as cog_module

        src = tmp_path / "src.tif"
        src.write_bytes(b"\x00" * 8)

        fake_dataset = mock.MagicMock()
        fake_dataset.count = 1
        fake_dataset.overviews.return_value = []
        fake_ctx = mock.MagicMock()
        fake_ctx.__enter__.return_value = fake_dataset
        fake_ctx.__exit__.return_value = False

        import rasterio

        monkeypatch.setattr(rasterio, "open", lambda *_a, **_k: fake_ctx)

        with _capture_subprocess_runs(monkeypatch) as captured:
            cog_module.prepare_with_overviews(str(src), "uint8", compression="ZSTD")

        gdaladdo_calls = [(cmd, env) for cmd, env in captured if cmd and cmd[0] == "gdaladdo"]
        assert gdaladdo_calls
        _, env = gdaladdo_calls[0]
        _assert_clamps(env)
        assert env.get("COMPRESS_OVERVIEW") == "ZSTD"


# ---------------------------------------------------------------------------
# convert_to_cog (gdalwarp branch)
# ---------------------------------------------------------------------------


class TestConvertToCogGdalwarpSafeEnv:
    def test_gdalwarp_subprocess_inherits_clamps(self, tmp_path, monkeypatch):
        """``convert_to_cog(assign_crs=...)`` invokes ``gdalwarp`` with the clamps.

        Before KNOWN-03, the gdalwarp call passed no ``env=`` at all and
        inherited an unclamped ``os.environ``.
        """
        from app.processing.raster import cog as cog_module

        src = tmp_path / "src.tif"
        src.write_bytes(b"\x00" * 8)
        dst = tmp_path / "out.tif"

        # Also stub the downstream prepare_with_overviews → rasterio.open
        # path because convert_to_cog falls through to it after gdalwarp.
        fake_dataset = mock.MagicMock()
        fake_dataset.count = 1
        fake_dataset.overviews.return_value = []
        fake_ctx = mock.MagicMock()
        fake_ctx.__enter__.return_value = fake_dataset
        fake_ctx.__exit__.return_value = False

        import rasterio

        monkeypatch.setattr(rasterio, "open", lambda *_a, **_k: fake_ctx)

        with _capture_subprocess_runs(monkeypatch) as captured:
            cog_module.convert_to_cog(
                str(src), str(dst), "uint8", assign_crs=4326
            )

        gdalwarp_calls = [(cmd, env) for cmd, env in captured if cmd and cmd[0] == "gdalwarp"]
        assert gdalwarp_calls, (
            f"gdalwarp was not invoked; captured: {[c[0] for c in captured]}"
        )
        _, env = gdalwarp_calls[0]
        # Pre-KNOWN-03 this branch passed env=None — assert it's no longer None.
        assert env is not None, "gdalwarp subprocess passed env=None (KNOWN-03 regression)"
        _assert_clamps(env)


# ---------------------------------------------------------------------------
# convert_to_cog (gdal_translate branch)
# ---------------------------------------------------------------------------


class TestConvertToCogGdalTranslateSafeEnv:
    def test_gdal_translate_subprocess_inherits_clamps(self, tmp_path, monkeypatch):
        """``convert_to_cog`` invokes ``gdal_translate`` with the safety clamps."""
        from app.processing.raster import cog as cog_module

        src = tmp_path / "src.tif"
        src.write_bytes(b"\x00" * 8)
        dst = tmp_path / "out.tif"

        fake_dataset = mock.MagicMock()
        fake_dataset.count = 1
        fake_dataset.overviews.return_value = []
        fake_ctx = mock.MagicMock()
        fake_ctx.__enter__.return_value = fake_dataset
        fake_ctx.__exit__.return_value = False

        import rasterio

        monkeypatch.setattr(rasterio, "open", lambda *_a, **_k: fake_ctx)

        with _capture_subprocess_runs(monkeypatch) as captured:
            cog_module.convert_to_cog(str(src), str(dst), "uint8")

        translate_calls = [
            (cmd, env) for cmd, env in captured if cmd and cmd[0] == "gdal_translate"
        ]
        assert translate_calls, (
            f"gdal_translate was not invoked; captured: {[c[0] for c in captured]}"
        )
        _, env = translate_calls[0]
        _assert_clamps(env)
        # Per-call extras must merge in too.
        assert env.get("GDAL_CACHEMAX") == "200"


# ---------------------------------------------------------------------------
# Direct helper-level pin
# ---------------------------------------------------------------------------


class TestGdalSafeEnvHelper:
    """Pin the public contract of ``gdal_safe_env(extras=...)`` directly."""

    def test_base_clamps_present(self):
        from app.processing.raster.vrt import gdal_safe_env

        env = gdal_safe_env()
        _assert_clamps(env)

    def test_extras_merge_in_and_win(self):
        from app.processing.raster.vrt import gdal_safe_env

        env = gdal_safe_env(extras={"FOO": "bar", "GDAL_CACHEMAX": "200"})
        _assert_clamps(env)
        assert env.get("FOO") == "bar"
        assert env.get("GDAL_CACHEMAX") == "200"

    def test_extras_override_vrt_safe_env_if_collision(self):
        """CR-01 (Phase 1071 review): passing a security clamp key in extras raises ValueError.

        The old contract was "extras win" (clobber silently allowed), which is
        the wrong contract for a security-clamping helper. The new contract is
        that extras MUST NOT collide with _VRT_SAFE_ENV keys; a ValueError is
        raised on collision so no caller can accidentally disable the clamps.
        """
        import pytest
        from app.processing.raster.vrt import gdal_safe_env

        with pytest.raises(ValueError, match="security clamps"):
            gdal_safe_env(extras={"GDAL_HTTP_FOLLOWLOCATION": "YES"})

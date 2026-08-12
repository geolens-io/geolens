"""KNOWN-03 (Phase 1071): GDAL CLI subprocess env overlay coverage.

v1015 Phase 1068 IA-P1-03 scoped ``_VRT_SAFE_ENV`` (with
``CPL_VSIL_CURL_ALLOWED_EXTENSIONS`` and ``VRT_VIRTUAL_OVERVIEWS``) to
``gdalbuildvrt`` only via ``_build_vrt``. Phase 1071 extends the same clamp
to the sibling raster subprocesses in ``cog.py``: ``gdaladdo`` (overview
generation), ``gdalwarp`` (CRS reprojection), and ``gdal_translate`` (COG
translation).

fix(#937): the overlay used to also carry ``GDAL_HTTP_FOLLOWLOCATION=NO``.
That is not a GDAL configuration option and never blocked a redirect;
``_assert_clamps`` now asserts it stays ABSENT so it cannot be reintroduced
as a claimed defense.

These tests pin the captured ``env=`` kwarg for each subprocess invocation
so a future refactor cannot silently regress the overlay shape.

Mirrors ``backend/tests/test_vrt_hardening.py::TestGdalBuildVrtSafeEnv``.

Requirement: KNOWN-03
Phase: 1071
"""

from contextlib import contextmanager
from unittest import mock


# The clamp keys/values must match _VRT_SAFE_ENV in
# backend/app/processing/raster/vrt.py. Re-stated here so a careless
# edit to that dict trips these tests.
EXPECTED_CLAMPS = {
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": "tif,tiff,vrt",
    "VRT_VIRTUAL_OVERVIEWS": "NO",
}


def _assert_clamps(env: dict) -> None:
    """The KNOWN-03 clamps must be set on the captured env."""
    assert env is not None, "subprocess.run was invoked without env="
    for key, expected in EXPECTED_CLAMPS.items():
        assert env.get(key) == expected, (
            f"clamp {key} missing/wrong: expected {expected!r}, got {env.get(key)!r}"
        )
    # fix(#937): not a GDAL option, provides no redirect protection — must
    # not reappear in any GDAL subprocess env as if it did.
    assert "GDAL_HTTP_FOLLOWLOCATION" not in env


@contextmanager
def _capture_subprocess_runs(monkeypatch):
    """Patch ``vrt.subprocess.run`` to capture each (cmd, env) tuple.

    fix(#430 BA-29 / #430): cog.py no longer calls subprocess directly — its GDAL
    CLIs route through ``run_gdal`` in vrt.py (which adds the kill-on-hang
    timeout), so the patch target moved there.

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

    from app.processing.raster import vrt as vrt_module

    monkeypatch.setattr(vrt_module.subprocess, "run", _fake_run)
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
        gdaladdo_calls = [
            (cmd, env) for cmd, env in captured if cmd and cmd[0] == "gdaladdo"
        ]
        assert gdaladdo_calls, (
            f"gdaladdo was not invoked; captured: {[c[0] for c in captured]}"
        )
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

        gdaladdo_calls = [
            (cmd, env) for cmd, env in captured if cmd and cmd[0] == "gdaladdo"
        ]
        assert gdaladdo_calls
        _, env = gdaladdo_calls[0]
        _assert_clamps(env)
        assert env.get("COMPRESS_OVERVIEW") == "ZSTD"


# ---------------------------------------------------------------------------
# convert_to_cog (assign_crs branch)
# ---------------------------------------------------------------------------


class TestConvertToCogCrsAssignment:
    """fix(#1291): ``assign_crs`` ASSIGNS the CRS and does not reproject.

    This class used to pin the KNOWN-03 clamps on a ``gdalwarp`` subprocess,
    because ``convert_to_cog`` prepended one whenever an EPSG code was
    supplied. The decision on #1291 removed that step: the code now rides on
    the existing ``gdal_translate`` as ``-a_srs``, which relabels the raster
    and touches no sample. The clamp assertion survives, on the process that
    now carries the flag.
    """

    def _stub_rasterio(self, monkeypatch):
        fake_dataset = mock.MagicMock()
        fake_dataset.count = 1
        fake_dataset.overviews.return_value = []
        fake_ctx = mock.MagicMock()
        fake_ctx.__enter__.return_value = fake_dataset
        fake_ctx.__exit__.return_value = False

        import rasterio

        monkeypatch.setattr(rasterio, "open", lambda *_a, **_k: fake_ctx)

    def test_assign_crs_lands_on_the_translate_and_spawns_no_warp(
        self, tmp_path, monkeypatch
    ):
        """The whole of the #1291 behavior change, in one argv assertion.

        ``-a_srs`` writes a CRS tag while every band passes through, so the
        output carries the uploaded samples. ``gdalwarp -t_srs`` resampled them
        onto a new grid. The absence of the warp is asserted, not implied: it
        is what licenses both raster tails calling ``cog_preserves_source``
        without ``reprojected=``, i.e. what licenses deleting the upload.
        """
        from app.processing.raster import cog as cog_module

        src = tmp_path / "src.tif"
        src.write_bytes(b"\x00" * 8)
        dst = tmp_path / "out.tif"
        self._stub_rasterio(monkeypatch)

        with _capture_subprocess_runs(monkeypatch) as captured:
            cog_module.convert_to_cog(str(src), str(dst), "uint8", assign_crs=3857)

        tools = [cmd[0] for cmd, _ in captured if cmd]
        assert "gdalwarp" not in tools, (
            f"a CRS assignment must not reproject (#1291); ran {tools}"
        )

        translate_calls = [
            (cmd, env) for cmd, env in captured if cmd and cmd[0] == "gdal_translate"
        ]
        assert translate_calls, f"gdal_translate was not invoked; ran {tools}"
        cmd, env = translate_calls[0]
        assert "-a_srs" in cmd, f"-a_srs missing from the translate argv: {cmd}"
        assert cmd[cmd.index("-a_srs") + 1] == "EPSG:3857"
        assert "-t_srs" not in cmd, (
            "-t_srs on gdal_translate reprojects; the assignment flag is -a_srs"
        )
        # The flag must precede the positional input/output pair, or GDAL reads
        # it as a file name.
        assert cmd.index("-a_srs") < cmd.index(str(dst))
        # KNOWN-03: the clamps ride on whichever process carries the work.
        _assert_clamps(env)

    def test_no_assign_crs_leaves_the_argv_alone(self, tmp_path, monkeypatch):
        """The flag is conditional — an ordinary conversion must not stamp a CRS
        the source never declared."""
        from app.processing.raster import cog as cog_module

        src = tmp_path / "src.tif"
        src.write_bytes(b"\x00" * 8)
        dst = tmp_path / "out.tif"
        self._stub_rasterio(monkeypatch)

        with _capture_subprocess_runs(monkeypatch) as captured:
            cog_module.convert_to_cog(str(src), str(dst), "uint8")

        for cmd, _ in captured:
            assert "-a_srs" not in cmd, f"unrequested CRS assignment in {cmd}"

    def test_resampling_reaches_overviews_only(self, tmp_path, monkeypatch):
        """``resampling`` fed ``gdalwarp -r`` as well as ``gdaladdo -r`` before
        #1291. With the warp gone it can only shape overviews, which is what
        makes it irrelevant to whether the base samples survived."""
        from app.processing.raster import cog as cog_module

        src = tmp_path / "src.tif"
        src.write_bytes(b"\x00" * 8)
        dst = tmp_path / "out.tif"
        self._stub_rasterio(monkeypatch)

        with _capture_subprocess_runs(monkeypatch) as captured:
            cog_module.convert_to_cog(
                str(src), str(dst), "uint8", assign_crs=3857, resampling="cubic"
            )

        carriers = sorted({cmd[0] for cmd, _ in captured if "cubic" in cmd})
        assert carriers == ["gdaladdo"], (
            f"'cubic' reached {carriers}; after #1291 only overview generation "
            "may see a resampling method"
        )


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
            gdal_safe_env(extras={"CPL_VSIL_CURL_ALLOWED_EXTENSIONS": "exe"})


# ---------------------------------------------------------------------------
# fix(#430 codex r15): temp-file cleanup when run_gdal RAISES (BA-29 timeout)
# ---------------------------------------------------------------------------


class TestGdalFailureTempCleanup:
    """run_gdal raises on timeout (BA-29); the returncode-only cleanup paths
    leaked the staged temp copies. Any raise must remove them."""

    def _stub_rasterio_no_overviews(self, monkeypatch):
        fake_dataset = mock.MagicMock()
        fake_dataset.count = 1
        fake_dataset.overviews.return_value = []

        fake_ctx = mock.MagicMock()
        fake_ctx.__enter__.return_value = fake_dataset
        fake_ctx.__exit__.return_value = False

        import rasterio

        monkeypatch.setattr(rasterio, "open", lambda *_a, **_k: fake_ctx)

    def test_prepare_with_overviews_cleans_tmp_on_run_gdal_raise(
        self, tmp_path, monkeypatch
    ):
        import tempfile

        import pytest
        from app.processing.raster import cog as cog_module

        src_dir = tmp_path / "src"
        work_dir = tmp_path / "work"
        src_dir.mkdir()
        work_dir.mkdir()
        src = src_dir / "src.tif"
        src.write_bytes(b"\x00" * 8)
        monkeypatch.setattr(tempfile, "tempdir", str(work_dir))
        self._stub_rasterio_no_overviews(monkeypatch)

        def _raise(*_a, **_k):
            raise RuntimeError("gdaladdo timed out after 900s")

        monkeypatch.setattr(cog_module, "run_gdal", _raise)

        with pytest.raises(RuntimeError, match="timed out"):
            cog_module.prepare_with_overviews(str(src), "uint8")

        assert list(work_dir.iterdir()) == [], (
            "temp raster copy leaked after run_gdal raised"
        )

    def test_convert_to_cog_with_assign_crs_leaves_no_temp_behind(
        self, tmp_path, monkeypatch
    ):
        """fix(#1291): the assignment path used to stage a second temp file for
        the ``gdalwarp`` output, and that one leaked on a timeout. It no longer
        exists — ``-a_srs`` rides the translate — so what this asserts now is
        that the path adds no temp of its own: the only scratch file is the
        overview copy, and its owner still removes it on any raise.
        """
        import tempfile

        import pytest
        from app.processing.raster import cog as cog_module

        src_dir = tmp_path / "src"
        work_dir = tmp_path / "work"
        src_dir.mkdir()
        work_dir.mkdir()
        src = src_dir / "src.tif"
        src.write_bytes(b"\x00" * 8)
        monkeypatch.setattr(tempfile, "tempdir", str(work_dir))
        self._stub_rasterio_no_overviews(monkeypatch)

        def _raise(*_a, **_k):
            raise RuntimeError("gdaladdo timed out after 900s")

        monkeypatch.setattr(cog_module, "run_gdal", _raise)

        with pytest.raises(RuntimeError, match="timed out"):
            cog_module.convert_to_cog(
                str(src),
                str(tmp_path / "out.tif"),
                "uint8",
                assign_crs=4326,
            )

        assert list(work_dir.iterdir()) == [], (
            "a temp file leaked from the CRS-assignment path after run_gdal raised"
        )

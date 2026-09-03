"""Codebase audit 2026-08-30, unbounded raster reads (tracked in #1778).

Two findings about a read with no ceiling on it:

- ``generate_quicklook`` sized its read from the source dimensions rather than
  from ``size``, so one uploaded file inside the 500 MB cap could OOM the
  worker.
- The VRT task opens every ``/vsis3`` source in-thread twice, with no GDAL HTTP
  timeout, and a Python thread is not killable.
"""

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"


def _source(rel: str) -> str:
    return (APP / rel).read_text()


class _ReadProbe(Exception):
    """Raised by the fake dataset instead of allocating the array asked for."""


class _FakeSrc:
    """The narrow slice of a rasterio dataset ``generate_quicklook`` reads.

    ``read`` records the requested ``out_shape`` and raises rather than
    allocating it. Allocating is what this finding is about: on the unfixed
    code the first case below asks for a 100000 x 100000 array, and a test that
    honoured the request would reproduce the OOM rather than report it.
    """

    def __init__(self, *, width: int, height: int, overviews: list[int]) -> None:
        self.width = width
        self.height = height
        self.count = 1
        self.nodata = None
        self.units = ()
        self._overviews = overviews
        self.read_shape: tuple[int, ...] | None = None

    def overviews(self, _band: int) -> list[int]:
        return self._overviews

    def read(self, _indexes, out_shape=None, resampling=None):
        self.read_shape = out_shape
        raise _ReadProbe

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class TestQuicklookReadBound:
    def _requested_shape(self, monkeypatch, src: _FakeSrc) -> tuple[int, ...]:
        import rasterio

        from app.processing.raster import quicklook

        monkeypatch.setattr(rasterio, "open", lambda *_a, **_kw: src)
        with pytest.raises(_ReadProbe):
            quicklook.generate_quicklook("ignored.tif", 512)
        assert src.read_shape is not None
        return src.read_shape

    def test_a_ladder_that_stops_short_still_reads_at_most_2x_size(
        self, monkeypatch
    ) -> None:
        """The finding's case: a huge source whose ladder bottoms out above size.

        200000 // 2 is 100000, the only level available, and it used to be the
        shape passed to ``read`` — a ~30 GB allocation from a file inside the
        500 MB upload cap.
        """
        src = _FakeSrc(width=200_000, height=200_000, overviews=[2])
        assert max(self._requested_shape(monkeypatch, src)[-2:]) <= 1024

    def test_no_overviews_at_all_is_bounded_too(self, monkeypatch) -> None:
        src = _FakeSrc(width=40_000, height=30_000, overviews=[])
        # Aspect ratio survives the clamp.
        assert self._requested_shape(monkeypatch, src)[-2:] == (768, 1024)

    def test_a_complete_ladder_is_unchanged(self, monkeypatch) -> None:
        """The bound is what a full ladder already gives, so it must not bite.

        8192 // 16 = 512 is the smallest level reaching `size`, and that is
        exactly what the selection loop picked before this change.
        """
        src = _FakeSrc(width=8192, height=8192, overviews=[2, 4, 8, 16, 32])
        assert self._requested_shape(monkeypatch, src)[-2:] == (512, 512)


# ---------------------------------------------------------------------------
# The VRT task's in-thread source reads are bounded
# ---------------------------------------------------------------------------


class TestVrtSourceReadTimeouts:
    def test_the_safe_env_bounds_a_stalled_vsi_read(self) -> None:
        from app.processing.raster.vrt import _VRT_SAFE_ENV, gdal_safe_env

        for key in (
            "GDAL_HTTP_TIMEOUT",
            "GDAL_HTTP_CONNECTTIMEOUT",
            "GDAL_HTTP_MAX_RETRY",
        ):
            assert key in _VRT_SAFE_ENV, key
            assert gdal_safe_env()[key] == _VRT_SAFE_ENV[key]

    def test_the_open_env_carries_the_same_clamps(self) -> None:
        """The subprocess env and the in-process env cannot drift."""
        from app.processing.raster.vrt import _VRT_SAFE_ENV, gdal_safe_open_env

        env = gdal_safe_open_env()
        for key, value in _VRT_SAFE_ENV.items():
            assert env.options[key] == value

    def test_the_vrt_task_reads_sources_through_the_safe_env_wrappers(self) -> None:
        """Both steps that open every source in-thread, in both VRT tails."""
        source = _source("processing/ingest/tasks_vrt.py")
        assert "asyncio.to_thread(extract_raster_metadata, vrt_path)" not in source
        assert "asyncio.to_thread(generate_quicklook, vrt_path" not in source
        assert source.count("asyncio.to_thread(read_vrt_metadata, vrt_path)") == 2
        assert source.count("asyncio.to_thread(render_vrt_quicklook, vrt_path") == 4

    def test_the_wrappers_enter_the_env_inside_the_worker_thread(self) -> None:
        """A rasterio Env is thread-local, so the ``with`` must be in the
        function ``to_thread`` runs, not around the await."""
        tree = ast.parse(_source("processing/ingest/tasks_vrt.py"))
        for name in ("read_vrt_metadata", "render_vrt_quicklook"):
            fn = next(
                node
                for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == name
            )
            withs = [n for n in ast.walk(fn) if isinstance(n, ast.With)]
            assert any(
                isinstance(item.context_expr, ast.Call)
                and getattr(item.context_expr.func, "id", None) == "gdal_safe_open_env"
                for w in withs
                for item in w.items
            ), f"{name} does not enter gdal_safe_open_env"

    @pytest.mark.parametrize(
        "wrapper,patched",
        [
            ("read_vrt_metadata", "extract_raster_metadata"),
            ("render_vrt_quicklook", "generate_quicklook"),
        ],
    )
    def test_the_wrapper_calls_through_the_patchable_module_attribute(
        self, monkeypatch, wrapper: str, patched: str
    ) -> None:
        """fix(#1778 codex r3): the names the integration fixtures patch.

        `test_regenerate_vrt_integration`'s `quicklook_stub` does
        `monkeypatch.setattr("app.processing.ingest.tasks_vrt.generate_quicklook",
        ...)`, so the wrapper has to both keep that attribute on the module and
        resolve it at call time. A local import inside the wrapper satisfies
        neither: it removes the attribute (AttributeError at fixture setup) and,
        once restored by hand, would silently ignore the stub and run the real
        renderer against a VRT built from remote sources.
        """
        from app.processing.ingest import tasks_vrt

        seen: list[tuple] = []

        def _stub(*args):
            seen.append(args)
            return "stubbed"

        monkeypatch.setattr(tasks_vrt, patched, _stub)
        args = ("some.vrt",) if wrapper == "read_vrt_metadata" else ("some.vrt", 256)
        assert getattr(tasks_vrt, wrapper)(*args) == "stubbed"
        assert seen == [args]

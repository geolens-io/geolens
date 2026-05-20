"""Regression tests for WFS-04 (Phase 1057): constraint-free geometry column
on the service-ingest path.

Root cause: ogr2ogr was invoked with ``-nlt PROMOTE_TO_MULTI`` on the service
path (``run_ogr2ogr_service``).  For WFS sources whose schema declares an
abstract OGC geometry type (e.g. ``MultiSurface``), ogr2ogr honoured that
declaration and created the PostGIS column with that abstract subtype.  When
actual features arrived as concrete geometries (e.g. ``MultiPolygon``), the
post-ingest bounds-clip UPDATE in ``clip_to_mercator_bounds`` failed with:

    asyncpg.exceptions.InvalidParameterValueError:
        Geometry type (MultiPolygon) does not match column type (MultiSurface)

D-01 (Phase 1057) fixes this by replacing ``-nlt PROMOTE_TO_MULTI`` with
``-nlt GEOMETRY`` on the service path only.  ``-nlt GEOMETRY`` instructs
ogr2ogr to emit a generic ``geometry(Geometry, 4326)`` PostGIS column with no
subtype constraint, so any concrete geometry subtype can be stored freely.

The concrete subtype for ``Dataset.geometry_type`` is derived post-ingest via
``get_geometry_type()`` (``metadata.py:165``), which queries
``SELECT GeometryType(geom) … LIMIT 1``.  The file-ingest sibling
``run_ogr2ogr()`` is unaffected and continues to use ``PROMOTE_TO_MULTI``.

Live MCP re-verify against ``ahocevar.com/geoserver/wfs → Countries of the
World`` is deferred to the Phase 1060 close gate.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.processing.ingest.ogr import run_ogr2ogr_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_proc(returncode: int = 0) -> MagicMock:
    """Return a fake asyncio.subprocess.Process that exits cleanly."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(b"", b""))
    proc.wait = AsyncMock(return_value=returncode)
    proc.kill = MagicMock()
    return proc


_DUMMY_GDAL_SOURCE = "WFS:https://example.com/geoserver/wfs"
_DUMMY_LAYER = "topp:countries"
_DUMMY_TABLE = "countries_abc123"
_DUMMY_CONN = "PG:host=localhost dbname=geolens_test"


# ---------------------------------------------------------------------------
# TestRunOgr2ogrServiceArgv
# ---------------------------------------------------------------------------


class TestRunOgr2ogrServiceArgv:
    """Pin the ogr2ogr argv shape for the service-ingest path (D-01 regression guard)."""

    @pytest.fixture()
    def captured_argv(self) -> list[list[str]]:
        return []

    @pytest.fixture()
    def patch_subprocess(self, captured_argv: list[list[str]]):
        """Monkeypatch asyncio.create_subprocess_exec inside the ogr module.

        Captures the full argv that would be passed to ogr2ogr and returns a
        fake process that exits 0 so ``run_ogr2ogr_service`` completes normally.
        """
        fake_proc = _make_fake_proc(returncode=0)

        async def _fake_exec(*args, **kwargs):
            captured_argv.append(list(args))
            return fake_proc

        with patch(
            "app.processing.ingest.ogr.asyncio.create_subprocess_exec",
            side_effect=_fake_exec,
        ):
            yield

    # ------------------------------------------------------------------
    # D-01 regression pin
    # ------------------------------------------------------------------

    @pytest.mark.anyio
    async def test_wfs_spatial_branch_omits_promote_to_multi(
        self, patch_subprocess, captured_argv
    ):
        """PROMOTE_TO_MULTI must NOT appear in the service-path argv (D-01)."""
        await run_ogr2ogr_service(
            gdal_source=_DUMMY_GDAL_SOURCE,
            layer_name=_DUMMY_LAYER,
            table_name=_DUMMY_TABLE,
            db_conn_str=_DUMMY_CONN,
            service_type="wfs",
            is_non_spatial=False,
        )
        assert len(captured_argv) == 1
        argv = captured_argv[0]
        assert "PROMOTE_TO_MULTI" not in argv, (
            "run_ogr2ogr_service must not emit -nlt PROMOTE_TO_MULTI on the "
            "spatial branch (WFS-04 / D-01 Phase 1057)"
        )

    @pytest.mark.anyio
    async def test_wfs_spatial_branch_emits_nlt_geometry(
        self, patch_subprocess, captured_argv
    ):
        """The spatial branch must emit -nlt GEOMETRY for a constraint-free column."""
        await run_ogr2ogr_service(
            gdal_source=_DUMMY_GDAL_SOURCE,
            layer_name=_DUMMY_LAYER,
            table_name=_DUMMY_TABLE,
            db_conn_str=_DUMMY_CONN,
            service_type="wfs",
            is_non_spatial=False,
        )
        argv = captured_argv[0]
        # Verify the flag pair is present in adjacent positions
        assert "-nlt" in argv, "Expected -nlt flag in argv"
        nlt_idx = argv.index("-nlt")
        assert argv[nlt_idx + 1] == "GEOMETRY", (
            f"Expected -nlt GEOMETRY but got -nlt {argv[nlt_idx + 1]!r}"
        )

    # ------------------------------------------------------------------
    # Preserved tokens (D-01 only changes the -nlt flag)
    # ------------------------------------------------------------------

    @pytest.mark.anyio
    async def test_wfs_spatial_branch_includes_geometry_name(
        self, patch_subprocess, captured_argv
    ):
        """GEOMETRY_NAME=_geolens_geom must still be present after D-01."""
        await run_ogr2ogr_service(
            gdal_source=_DUMMY_GDAL_SOURCE,
            layer_name=_DUMMY_LAYER,
            table_name=_DUMMY_TABLE,
            db_conn_str=_DUMMY_CONN,
            service_type="wfs",
            is_non_spatial=False,
        )
        argv = captured_argv[0]
        assert "GEOMETRY_NAME=_geolens_geom" in argv, (
            "GEOMETRY_NAME=_geolens_geom must remain in service-path argv"
        )
        assert "SPATIAL_INDEX=NONE" in argv, (
            "SPATIAL_INDEX=NONE must remain in service-path argv"
        )

    @pytest.mark.anyio
    async def test_wfs_spatial_branch_includes_t_srs_4326(
        self, patch_subprocess, captured_argv
    ):
        """The -t_srs EPSG:4326 reprojection flag must still be present."""
        await run_ogr2ogr_service(
            gdal_source=_DUMMY_GDAL_SOURCE,
            layer_name=_DUMMY_LAYER,
            table_name=_DUMMY_TABLE,
            db_conn_str=_DUMMY_CONN,
            service_type="wfs",
            is_non_spatial=False,
        )
        argv = captured_argv[0]
        assert "-t_srs" in argv, "Expected -t_srs flag in argv"
        t_srs_idx = argv.index("-t_srs")
        assert argv[t_srs_idx + 1] == "EPSG:4326", (
            f"Expected -t_srs EPSG:4326, got -t_srs {argv[t_srs_idx + 1]!r}"
        )

    @pytest.mark.anyio
    async def test_wfs_spatial_branch_includes_page_size_config(
        self, patch_subprocess, captured_argv
    ):
        """OGR_WFS_PAGE_SIZE must be present when service_type='wfs'."""
        await run_ogr2ogr_service(
            gdal_source=_DUMMY_GDAL_SOURCE,
            layer_name=_DUMMY_LAYER,
            table_name=_DUMMY_TABLE,
            db_conn_str=_DUMMY_CONN,
            service_type="wfs",
            is_non_spatial=False,
        )
        argv = captured_argv[0]
        assert "OGR_WFS_PAGE_SIZE" in argv, (
            "OGR_WFS_PAGE_SIZE must appear in argv when service_type='wfs'"
        )

    @pytest.mark.anyio
    async def test_non_spatial_branch_omits_geometry_flags(
        self, patch_subprocess, captured_argv
    ):
        """When is_non_spatial=True, no geometry flags should be emitted."""
        await run_ogr2ogr_service(
            gdal_source=_DUMMY_GDAL_SOURCE,
            layer_name="",
            table_name=_DUMMY_TABLE,
            db_conn_str=_DUMMY_CONN,
            service_type="arcgis_featureserver",
            is_non_spatial=True,
        )
        argv = captured_argv[0]
        # None of the spatial-branch tokens should be present
        assert "-nlt" not in argv, "is_non_spatial=True must not emit -nlt"
        assert "GEOMETRY_NAME=_geolens_geom" not in argv
        assert "SPATIAL_INDEX=NONE" not in argv
        assert "-t_srs" not in argv
        assert "PROMOTE_TO_MULTI" not in argv
        assert "GEOMETRY" not in argv


# ---------------------------------------------------------------------------
# TestNormalizeGeometryType — Phase 1060 layer-2 fix
# ---------------------------------------------------------------------------


class TestNormalizeGeometryType:
    """Regression pins for the abstract-OGC-type → concrete-subtype mapping.

    Phase 1057's ``-nlt GEOMETRY`` fix relaxed the column-type constraint,
    but PostGIS GeometryType() still returns the abstract subtype
    (MULTISURFACE / MULTICURVE / COMPOUND…) when the WFS source stores
    abstract GML 3 geometries (e.g. GeoServer's opengeo:countries).  Without
    normalization the dataset.geometry_type insert fails the
    chk_datasets_geometry_type CHECK constraint, which only allows the 7
    concrete OGC simple-features types.

    Phase 1060 close-gate fix: map abstract → closest concrete equivalent
    before persisting Dataset.geometry_type.
    """

    def test_multisurface_normalized_to_multipolygon(self) -> None:
        from app.processing.ingest.metadata import _normalize_geometry_type

        assert _normalize_geometry_type("MULTISURFACE") == "MULTIPOLYGON"
        assert _normalize_geometry_type("MultiSurface") == "MULTIPOLYGON"
        assert _normalize_geometry_type("multisurface") == "MULTIPOLYGON"

    def test_multicurve_normalized_to_multilinestring(self) -> None:
        from app.processing.ingest.metadata import _normalize_geometry_type

        assert _normalize_geometry_type("MULTICURVE") == "MULTILINESTRING"

    def test_compound_types_normalized(self) -> None:
        from app.processing.ingest.metadata import _normalize_geometry_type

        assert _normalize_geometry_type("COMPOUNDSURFACE") == "MULTIPOLYGON"
        assert _normalize_geometry_type("COMPOUNDCURVE") == "MULTILINESTRING"

    def test_surface_curve_normalized_to_singular_concrete(self) -> None:
        from app.processing.ingest.metadata import _normalize_geometry_type

        assert _normalize_geometry_type("SURFACE") == "POLYGON"
        assert _normalize_geometry_type("CURVE") == "LINESTRING"

    def test_polyhedral_and_tin_normalized_to_multipolygon(self) -> None:
        from app.processing.ingest.metadata import _normalize_geometry_type

        assert _normalize_geometry_type("POLYHEDRALSURFACE") == "MULTIPOLYGON"
        assert _normalize_geometry_type("TIN") == "MULTIPOLYGON"
        assert _normalize_geometry_type("TRIANGLE") == "POLYGON"

    def test_concrete_types_unchanged(self) -> None:
        from app.processing.ingest.metadata import _normalize_geometry_type

        for concrete in (
            "POINT",
            "LINESTRING",
            "POLYGON",
            "MULTIPOINT",
            "MULTILINESTRING",
            "MULTIPOLYGON",
            "GEOMETRYCOLLECTION",
        ):
            assert _normalize_geometry_type(concrete) == concrete

    def test_lowercase_concrete_type_uppercased(self) -> None:
        from app.processing.ingest.metadata import _normalize_geometry_type

        assert _normalize_geometry_type("polygon") == "POLYGON"
        assert _normalize_geometry_type("multipolygon") == "MULTIPOLYGON"

    def test_none_and_empty_return_none(self) -> None:
        from app.processing.ingest.metadata import _normalize_geometry_type

        assert _normalize_geometry_type(None) is None
        assert _normalize_geometry_type("") is None

    def test_unknown_type_passes_through_uppercased(self) -> None:
        """Defensive: unknown GeometryType output is uppercased + returned as-is.

        The DB check constraint will still reject it, but the user gets a
        clearer downstream error rather than a silent rewrite to a wrong type.
        """
        from app.processing.ingest.metadata import _normalize_geometry_type

        # Hypothetical novel type (e.g. a future PostGIS extension)
        assert _normalize_geometry_type("custom_type") == "CUSTOM_TYPE"

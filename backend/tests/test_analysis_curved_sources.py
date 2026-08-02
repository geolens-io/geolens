"""Curved-geometry sources and binary property values (#1097 review, #1104).

WFS ingest admits CURVED geometries — GeoServer MultiSurface/CompoundCurve
layers load as stored, and ingest classifies the dataset by the closest
concrete linear type (metadata.py's _ABSTRACT_TO_CONCRETE_GEOMETRY_TYPE).
Verified against PostGIS 3.6: ``::geography``, ``ST_MakeValid``,
``ST_AsGeoJSON`` and ``ST_AsMVTGeom`` all RAISE on curved input. fix(#1104):
ingest therefore linearizes ``geom_4326`` itself (add_4326_column applies
ST_CurveToLine; the curved source survives in ``geom``), and the fixture
routes through that same normalizer — so every test here pins that the
ingest invariant alone keeps analysis previews, CTAS outputs, tiles and
feature reads working, with no per-read wraps left in the SQL.

The bytea test pins the OTHER preview serialization hazard from the same
review round: a transferred ``bytea`` value reaching Pydantic as raw bytes.

Requirements:
  - Docker database must be running (docker compose up db)
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.processing.analysis.tasks import _materialize

from tests.factories import get_user_id
from tests.test_analysis_materialize import _create_job
from tests.test_analysis_spatial_join import _create_layer

# fix(#1104): make the fixtures defined in test_tiles.py (especially
# _init_tile_pool_for_tests) available to this module without duplicating the
# fixture body — same pattern as test_tile_cache_cols_key.py.
pytest_plugins = ["tests.test_tiles"]

# A full circle of radius 0.5 centred on (0.5, 0), stored as the curved
# MULTISURFACE/CURVEPOLYGON type a GeoServer WFS layer ingests as.
CURVED_POLYGON = (
    "ST_GeomFromText('MULTISURFACE(CURVEPOLYGON(CIRCULARSTRING("
    "0 0,0.5 0.5,1 0,0.5 -0.5,0 0)))', 4326)"
)
# A line with a genuine arc segment, stored as COMPOUNDCURVE.
CURVED_LINE = (
    "ST_GeomFromText('COMPOUNDCURVE((0 0,1 1),CIRCULARSTRING(1 1,2 2,3 1))', 4326)"
)
LINEAR_GEOJSON_TYPES = {
    "Point",
    "MultiPoint",
    "LineString",
    "MultiLineString",
    "Polygon",
    "MultiPolygon",
    "GeometryCollection",
}


def _preview_url(dataset_id) -> str:
    return f"/datasets/{dataset_id}/analysis/preview/"


async def _create_curved_polygon_layer(session: AsyncSession, *, created_by):
    return await _create_layer(
        session,
        created_by=created_by,
        column_type="Geometry",
        # What ingest records for a MultiSurface source (metadata.py).
        geometry_type="MULTIPOLYGON",
        values_sql=f"('circle', {CURVED_POLYGON}, {CURVED_POLYGON})",
        feature_count=1,
    )


class TestCurvedSources:
    async def test_measure_preview_answers_for_a_curved_source(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """A curved dataset measures instead of 500ing, with correct numbers.

        Ground truth is PostGIS's own measure of the linearized geometry, so
        the assertion pins the plumbing rather than circle-area maths.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Geometry",
            geometry_type="MULTIPOLYGON",
            values_sql=(
                f"('circle', {CURVED_POLYGON}, {CURVED_POLYGON}),"
                f"('arc', {CURVED_LINE}, {CURVED_LINE})"
            ),
            feature_count=2,
        )

        resp = await client.post(
            _preview_url(ds.id),
            json={"operation": "measure"},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        features = resp.json()["geojson"]["features"]
        got = {
            f["properties"]["gid"]: (
                f["properties"]["area_sqm"],
                f["properties"]["length_m"],
            )
            for f in features
        }
        expected = {
            gid: (a, ln)
            for gid, a, ln in (
                await test_db_session.execute(
                    text(
                        f"SELECT gid,"  # noqa: S608
                        f" ST_Area(ST_CurveToLine(geom_4326)::geography),"
                        f" ST_Length(ST_CurveToLine(geom_4326)::geography)"
                        f" FROM data.{ds.table_name} ORDER BY gid"
                    )
                )
            ).all()
        }
        assert set(got) == set(expected) == {1, 2}
        for gid, (area, length) in got.items():
            assert area == pytest.approx(expected[gid][0], rel=1e-6)
            assert length == pytest.approx(expected[gid][1], rel=1e-6)
        # The pass-through geometry serialized as a LINEAR GeoJSON type —
        # GeoJSON has no curved types, so anything else could not have been
        # emitted at all.
        assert {f["geometry"]["type"] for f in features} <= LINEAR_GEOJSON_TYPES

    async def test_spatial_join_preview_joins_onto_a_curved_source(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """The per-source-row ST_MakeValid hoist accepts a curved source."""
        admin_id = await get_user_id(test_db_session, "admin")
        src = await _create_curved_polygon_layer(test_db_session, created_by=admin_id)
        points = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Point",
            geometry_type="POINT",
            values_sql=(
                "('inside', ST_SetSRID(ST_MakePoint(0.5, 0.2), 4326),"
                " ST_SetSRID(ST_MakePoint(0.5, 0.2), 4326)),"
                "('outside', ST_SetSRID(ST_MakePoint(5, 5), 4326),"
                " ST_SetSRID(ST_MakePoint(5, 5), 4326))"
            ),
            feature_count=2,
        )

        resp = await client.post(
            _preview_url(src.id),
            json={
                "operation": "spatial_join",
                "join_dataset_id": str(points.id),
                "join_fields": ["name"],
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        features = body["geojson"]["features"]
        assert len(features) == 1
        assert features[0]["properties"]["join_count"] == 1
        assert features[0]["properties"]["join_name"] == "inside"
        assert body["match_count"] == 1
        assert features[0]["geometry"]["type"] in LINEAR_GEOJSON_TYPES

    async def test_select_by_location_serializes_a_curved_selection(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """A drawn mask selecting a curved row must serialize that row."""
        admin_id = await get_user_id(test_db_session, "admin")
        src = await _create_curved_polygon_layer(test_db_session, created_by=admin_id)

        resp = await client.post(
            _preview_url(src.id),
            json={
                "operation": "select_by_location",
                "mask": {
                    "type": "Polygon",
                    "coordinates": [[[-1, -1], [2, -1], [2, 1], [-1, 1], [-1, -1]]],
                },
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        features = resp.json()["geojson"]["features"]
        assert [f["properties"]["gid"] for f in features] == [1]
        assert features[0]["geometry"]["type"] in LINEAR_GEOJSON_TYPES

    async def test_intersect_preview_with_curved_source_and_curved_mask(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Both intersect wrap sites at once: curved mask prep, curved source.

        The COMPOUNDCURVE source also pins the LINESTRING type check — read
        raw it would say 'COMPOUNDCURVE', silently skipping ST_LineMerge, so a
        LINEAR output type here proves the check reads the linearized form.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        src = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Geometry",
            geometry_type="MULTILINESTRING",
            values_sql=f"('arc', {CURVED_LINE}, {CURVED_LINE})",
            feature_count=1,
        )
        # Curved TYPE with a plain square ring: still MultiSurface to every
        # curve-intolerant function, which is what the mask pipeline must
        # survive.
        mask_wkt = "ST_GeomFromText('MULTISURFACE(((0 0,2 0,2 2,0 2,0 0)))', 4326)"
        mask = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Geometry",
            geometry_type="MULTIPOLYGON",
            values_sql=f"('square', {mask_wkt}, {mask_wkt})",
            feature_count=1,
        )

        resp = await client.post(
            _preview_url(src.id),
            json={"operation": "intersect", "mask_dataset_id": str(mask.id)},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        features = body["geojson"]["features"]
        assert len(features) == 1
        assert body["match_count"] == 1
        assert features[0]["geometry"]["type"] in (
            "LineString",
            "MultiLineString",
        )

    async def test_materialize_saves_linear_geometry_from_a_curved_source(
        self,
        test_db_session: AsyncSession,
    ):
        """The CTAS stores the linearized geometry, not the curved original.

        A curved geometry written into the derived table would fail that
        LAYER's tiles and feature reads later — the whole reason the
        pass-through output is linearized rather than only the casts.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_curved_polygon_layer(test_db_session, created_by=admin_id)
        job = await _create_job(test_db_session, admin_id)

        await _materialize(
            job_id=str(job.id),
            dataset_id=str(ds.id),
            user_id=str(admin_id),
            operation="measure",
            title=f"Curved measure {uuid.uuid4().hex[:6]}",
        )

        await test_db_session.refresh(job)
        assert job.status == "complete", job.error_message

        from app.modules.catalog.datasets.domain.models import Dataset

        new_ds = await test_db_session.get(Dataset, job.dataset_id)
        assert new_ds is not None
        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT GeometryType(geom), area_sqm"  # noqa: S608
                    f" FROM data.{new_ds.table_name}"
                )
            )
        ).all()
        assert len(rows) == 1
        geom_type, area = rows[0]
        assert geom_type in ("POLYGON", "MULTIPOLYGON")
        assert area > 0


class TestBinaryJoinFields:
    async def test_spatial_join_preview_encodes_a_bytea_join_field(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Transferred bytea values arrive hex-encoded, not as raw bytes.

        Raw bytes raise inside Pydantic's JSON serializer, turning a valid
        preview into a 500 — and a ``bytea[]`` column comes back as a LIST of
        bytes, so the encoder must recurse into containers, not just handle
        the scalar (round-14 review). Both encodings match ``to_jsonb``'s
        (which the features browse API serves for the same columns):
        ``\\x`` + hex, and an array of the same.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        points = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Point",
            geometry_type="POINT",
            values_sql=(
                "('probe', ST_SetSRID(ST_MakePoint(0.5, 0.5), 4326),"
                " ST_SetSRID(ST_MakePoint(0.5, 0.5), 4326))"
            ),
            feature_count=1,
        )
        polys = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Polygon",
            geometry_type="POLYGON",
            extra_columns="blob BYTEA, blobs BYTEA[],",
            values_sql=(
                "('zone', decode('deadbeef', 'hex'),"
                " ARRAY[decode('dead', 'hex'), decode('beef', 'hex')],"
                " ST_MakeEnvelope(0,0,1,1,4326), ST_MakeEnvelope(0,0,1,1,4326))"
            ),
            column_info=[
                {"name": "name", "type": "text"},
                {"name": "blob", "type": "bytea"},
                {"name": "blobs", "type": "bytea[]"},
            ],
            feature_count=1,
        )

        resp = await client.post(
            _preview_url(points.id),
            json={
                "operation": "spatial_join",
                "join_dataset_id": str(polys.id),
                "join_fields": ["blob", "blobs"],
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        features = resp.json()["geojson"]["features"]
        assert len(features) == 1
        assert features[0]["properties"]["join_blob"] == "\\xdeadbeef"
        assert features[0]["properties"]["join_blobs"] == ["\\xdead", "\\xbeef"]


class TestCurvedIngestNormalization:
    """fix(#1104): ingest stores geom_4326 LINEAR, so every surface reads it.

    The classes above pin the analysis operations. These pin the stored
    invariant itself plus the two broken surfaces with no other curved
    coverage: vector tiles (ST_AsMVTGeom raised ``lwgeom_get_basic_type:
    Invalid type (12)``) and the features browse endpoint (ST_AsGeoJSON
    raises because GeoJSON has no curved types).
    """

    async def test_ingest_stores_linear_geom_4326_and_curved_geom(
        self, test_db_session: AsyncSession
    ):
        """add_4326_column linearizes geom_4326; `geom` keeps the curved source."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_layer(
            test_db_session,
            created_by=admin_id,
            column_type="Geometry",
            geometry_type="MULTIPOLYGON",
            values_sql=(
                f"('circle', {CURVED_POLYGON}, {CURVED_POLYGON}),"
                f"('arc', {CURVED_LINE}, {CURVED_LINE})"
            ),
            feature_count=2,
        )
        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT GeometryType(geom), GeometryType(geom_4326)"  # noqa: S608
                    f" FROM data.{ds.table_name} ORDER BY gid"
                )
            )
        ).all()
        assert [r[0] for r in rows] == ["MULTISURFACE", "COMPOUNDCURVE"]
        assert [r[1] for r in rows] == ["MULTIPOLYGON", "LINESTRING"]

    async def test_register_linearizes_a_preexisting_curved_geom_4326(
        self, test_db_session: AsyncSession
    ):
        """fix(#1113 review): the register path enforces the invariant too.

        ``register_existing_table`` skips ``add_4326_column`` when the table
        already carries geom_4326, and a table created in the data schema
        AFTER migration 0034 ran is invisible to its backfill — so without
        this boundary, registration would be the one app-controlled writer
        that can re-admit curved values. Both curve shapes are pinned: an
        arc-bearing surface AND an arc-free container (``MULTISURFACE`` of a
        plain polygon), which ST_HasArc alone cannot see.
        """
        from types import SimpleNamespace

        from app.processing.ingest.schemas import RegisterRequest
        from app.processing.ingest.service import register_existing_table

        admin_id = await get_user_id(test_db_session, "admin")
        table = f"byo_curved_{uuid.uuid4().hex[:10]}"
        arc_free = "ST_GeomFromText('MULTISURFACE(((0 0,1 0,1 1,0 1,0 0)))', 4326)"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table} ("  # noqa: S608
                f"gid serial PRIMARY KEY, name text, "
                f"geom geometry(Geometry, 4326), "
                f"geom_4326 geometry(Geometry, 4326))"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table} (name, geom, geom_4326) VALUES "  # noqa: S608
                f"('circle', {CURVED_POLYGON}, {CURVED_POLYGON}), "
                f"('flat', {arc_free}, {arc_free})"
            )
        )
        await test_db_session.commit()

        await register_existing_table(
            test_db_session,
            RegisterRequest(table_name=table, title="BYO curved table"),
            SimpleNamespace(id=admin_id),
        )
        await test_db_session.commit()

        rows = (
            await test_db_session.execute(
                text(
                    f"SELECT name, GeometryType(geom), GeometryType(geom_4326) "  # noqa: S608
                    f"FROM data.{table} ORDER BY gid"
                )
            )
        ).all()
        # geom keeps the curved source; geom_4326 is linear for BOTH shapes.
        assert [(r[1], r[2]) for r in rows] == [
            ("MULTISURFACE", "MULTIPOLYGON"),
            ("MULTISURFACE", "MULTIPOLYGON"),
        ]

    async def test_features_read_survives_a_socrata_colon_column(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#1113 review): a ``:id`` property must not read as a bind param.

        Registered Socrata exports ship columns literally named ``:id``. The
        projected select-list is interpolated into ``text()``, which parses
        ``:name`` as a bind parameter even inside double quotes — unescaped,
        every feature read on such a table fails before reaching PostgreSQL.
        """
        from types import SimpleNamespace

        from app.processing.ingest.schemas import RegisterRequest
        from app.processing.ingest.service import register_existing_table

        admin_id = await get_user_id(test_db_session, "admin")
        table = f"byo_socrata_{uuid.uuid4().hex[:10]}"
        # The test's own DDL needs the same escape the fix installs: text()
        # would otherwise read ":id" here as a bind parameter too.
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table} ("  # noqa: S608
                f'gid serial PRIMARY KEY, "\\:id" text, name text, '
                f"geom geometry(Geometry, 4326), "
                f"geom_4326 geometry(Geometry, 4326))"
            )
        )
        await test_db_session.execute(
            text(
                f'INSERT INTO data.{table} ("\\:id", name, geom, geom_4326) '  # noqa: S608
                f"VALUES ('row-1', 'first', "
                f"ST_SetSRID(ST_MakePoint(1, 1), 4326), "
                f"ST_SetSRID(ST_MakePoint(1, 1), 4326))"
            )
        )
        await test_db_session.commit()

        registered = await register_existing_table(
            test_db_session,
            RegisterRequest(table_name=table, title="Socrata colon column"),
            SimpleNamespace(id=admin_id),
        )
        await test_db_session.commit()

        resp = await client.get(
            f"/datasets/{registered.id}/features/", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        props = resp.json()["features"][0]["properties"]
        assert props[":id"] == "row-1"
        assert props["name"] == "first"

    async def test_register_skips_a_generated_geom_4326(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """fix(#1113 review r7): a STORED GENERATED column must not abort.

        PostgreSQL rejects any UPDATE against a generated column at parse
        time — even one whose WHERE matches nothing — so the enforcement
        UPDATE itself would fail registration. Such a column's values are
        decided by its generation expression, so it is skipped, not repaired
        (#1114 tracks expressions that yield curves).
        """
        from types import SimpleNamespace

        from app.processing.ingest.schemas import RegisterRequest
        from app.processing.ingest.service import register_existing_table

        admin_id = await get_user_id(test_db_session, "admin")
        table = f"byo_generated_{uuid.uuid4().hex[:10]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table} ("  # noqa: S608
                f"gid serial PRIMARY KEY, name text, "
                f"geom geometry(Geometry, 4326), "
                f"geom_4326 geometry GENERATED ALWAYS AS (ST_Force2D(geom)) STORED)"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table} (name, geom) VALUES "  # noqa: S608
                f"('pt', ST_SetSRID(ST_MakePoint(2, 2), 4326))"
            )
        )
        await test_db_session.commit()

        registered = await register_existing_table(
            test_db_session,
            RegisterRequest(table_name=table, title="Generated geom_4326"),
            SimpleNamespace(id=admin_id),
        )
        await test_db_session.commit()

        resp = await client.get(
            f"/datasets/{registered.id}/features/", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["features"][0]["properties"]["name"] == "pt"

    async def test_register_refuses_a_generated_column_that_yields_curves(
        self, test_db_session: AsyncSession
    ):
        """fix(#1113 review r8): curved generated values refuse registration.

        No write of ours can repair a generated column, so admitting one whose
        rows are already curved registers a dataset broken on every surface.
        The refusal names the cause; an empty or linear generated column
        (previous test) registers fine.
        """
        from types import SimpleNamespace

        import pytest as _pytest

        from app.processing.ingest.schemas import RegisterRequest
        from app.processing.ingest.service import register_existing_table

        admin_id = await get_user_id(test_db_session, "admin")
        table = f"byo_gencurved_{uuid.uuid4().hex[:10]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table} ("  # noqa: S608
                f"gid serial PRIMARY KEY, name text, "
                f"geom geometry(Geometry, 4326), "
                f"geom_4326 geometry GENERATED ALWAYS AS (geom) STORED)"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table} (name, geom) VALUES "  # noqa: S608
                f"('circle', {CURVED_POLYGON})"
            )
        )
        await test_db_session.commit()

        with _pytest.raises(ValueError, match="generated column.*curved"):
            await register_existing_table(
                test_db_session,
                RegisterRequest(table_name=table, title="Curved generated"),
                SimpleNamespace(id=admin_id),
            )

    async def test_generated_reject_sees_nested_curves_but_not_linear_gcs(
        self, test_db_session: AsyncSession
    ):
        """fix(#1113 review r9): the reject test is 'would conversion change it'.

        A curve container nested in a GEOMETRYCOLLECTION has no arc and a
        collection top-level type, so any type-list predicate misses it; an
        all-LINEAR collection must still register. The byte-compare against
        ST_CurveToLine's output answers both with one test.
        """
        from types import SimpleNamespace

        import pytest as _pytest

        from app.processing.ingest.schemas import RegisterRequest
        from app.processing.ingest.service import register_existing_table

        admin_id = await get_user_id(test_db_session, "admin")

        nested = f"byo_gennested_{uuid.uuid4().hex[:10]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{nested} ("  # noqa: S608
                f"gid serial PRIMARY KEY, name text, "
                f"geom geometry(Geometry, 4326), "
                f"geom_4326 geometry GENERATED ALWAYS AS (geom) STORED)"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{nested} (name, geom) VALUES "  # noqa: S608
                f"('hidden', ST_GeomFromText("
                f"'GEOMETRYCOLLECTION(MULTISURFACE(((0 0,1 0,1 1,0 1,0 0))))'"
                f", 4326))"
            )
        )
        await test_db_session.commit()
        with _pytest.raises(ValueError, match="generated column.*curved"):
            await register_existing_table(
                test_db_session,
                RegisterRequest(table_name=nested, title="Nested curved"),
                SimpleNamespace(id=admin_id),
            )
        await test_db_session.rollback()

        linear_gc = f"byo_genlingc_{uuid.uuid4().hex[:10]}"
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{linear_gc} ("  # noqa: S608
                f"gid serial PRIMARY KEY, name text, "
                f"geom geometry(Geometry, 4326), "
                f"geom_4326 geometry GENERATED ALWAYS AS (geom) STORED)"
            )
        )
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{linear_gc} (name, geom) VALUES "  # noqa: S608
                f"('plain', ST_GeomFromText("
                f"'GEOMETRYCOLLECTION(POINT(1 1),LINESTRING(0 0,1 1))', 4326))"
            )
        )
        await test_db_session.commit()
        registered = await register_existing_table(
            test_db_session,
            RegisterRequest(table_name=linear_gc, title="Linear GC generated"),
            SimpleNamespace(id=admin_id),
        )
        assert registered is not None

    async def test_relationship_fetch_may_target_a_projected_out_column(
        self, test_db_session: AsyncSession
    ):
        """fix(#1113 review r10): the match runs against the base table.

        Safe-column validation accepts ``geom_4326`` as a relationship target,
        and the projection deliberately drops it — predicating on the
        projected alias made such a fetch an undefined-column error. A NULL
        probe is enough to pin the regression: it must return no rows, not
        raise.
        """
        from app.modules.catalog.datasets.domain.service_relationships import (
            _fetch_target_rows,
        )

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_curved_polygon_layer(test_db_session, created_by=admin_id)

        rows = await _fetch_target_rows(
            test_db_session, ds.table_name, "geom_4326", None, 10, 0
        )
        assert rows == []

    async def test_register_loosens_a_curved_geom_4326_typmod(
        self, test_db_session: AsyncSession
    ):
        """fix(#1113 review): a curved column TYPMOD must not abort the write.

        ``geometry(CurvePolygon, 4326)`` rejects the linear result of
        ST_CurveToLine outright, so without the retype the enforcement UPDATE
        itself fails. The column is loosened to generic geometry first, then
        linearized.
        """
        from types import SimpleNamespace

        from app.processing.ingest.schemas import RegisterRequest
        from app.processing.ingest.service import register_existing_table

        admin_id = await get_user_id(test_db_session, "admin")
        table = f"byo_typmod_{uuid.uuid4().hex[:10]}"
        curve_poly = (
            "ST_GeomFromText('CURVEPOLYGON(CIRCULARSTRING("
            "0 0,0.5 0.5,1 0,0.5 -0.5,0 0))', 4326)"
        )
        await test_db_session.execute(
            text(
                f"CREATE TABLE data.{table} ("  # noqa: S608
                f"gid serial PRIMARY KEY, name text, "
                f"geom geometry(Geometry, 4326), "
                f"geom_4326 geometry(CurvePolygon, 4326))"
            )
        )
        # geom carries the MULTISURFACE form the metadata classifier already
        # maps to a concrete linear type; the curved TYPMOD under test lives
        # on geom_4326 alone.
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table} (name, geom, geom_4326) VALUES "  # noqa: S608
                f"('circle', {CURVED_POLYGON}, {curve_poly})"
            )
        )
        await test_db_session.commit()

        await register_existing_table(
            test_db_session,
            RegisterRequest(table_name=table, title="BYO curved typmod"),
            SimpleNamespace(id=admin_id),
        )
        await test_db_session.commit()

        row = (
            await test_db_session.execute(
                text(
                    f"SELECT GeometryType(geom_4326), "  # noqa: S608
                    f"(SELECT type FROM public.geometry_columns "
                    f" WHERE f_table_schema = 'data' "
                    f"   AND f_table_name = '{table}' "
                    f"   AND f_geometry_column = 'geom_4326') "
                    f"FROM data.{table}"
                )
            )
        ).one()
        assert row[0] == "POLYGON"
        assert row[1] == "GEOMETRY"

    @pytest.mark.usefixtures("_init_tile_pool_for_tests")
    async def test_vector_tile_renders_a_curved_source(
        self,
        client: AsyncClient,
        test_db_session: AsyncSession,
    ):
        """The MVT endpoint serves bytes for a dataset ingested from curves."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_curved_polygon_layer(test_db_session, created_by=admin_id)
        # The circle is centred on (0.5, 0), so tile 0/0/0 must contain it.
        resp = await client.get(f"/tiles/data.{ds.table_name}/0/0/0.pbf")
        assert resp.status_code == 200, resp.text
        assert resp.headers["content-type"] == "application/vnd.mapbox-vector-tile"
        assert len(resp.content) > 0

    async def test_features_read_serializes_a_curved_source(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ):
        """Browse, single read, and features.geojson all answer for curves.

        Two raises used to hide here: ST_AsGeoJSON over a curved geom_4326
        (fixed by ingest linearization) and ``to_jsonb(t.*)`` serializing the
        curved SOURCE ``geom`` column before the ``- 'geom'`` subtraction
        could discard it (fixed by projecting the row first). Each response
        also proves properties survived the projection.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_curved_polygon_layer(test_db_session, created_by=admin_id)

        resp = await client.get(
            f"/datasets/{ds.id}/features/", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        features = resp.json()["features"]
        assert len(features) == 1
        assert features[0]["geometry"]["type"] in LINEAR_GEOJSON_TYPES
        assert features[0]["properties"]["name"] == "circle"

        gid = features[0]["id"]
        single = await client.get(
            f"/datasets/{ds.id}/features/{gid}", headers=admin_auth_header
        )
        assert single.status_code == 200, single.text
        assert single.json()["geometry"]["type"] in LINEAR_GEOJSON_TYPES
        assert single.json()["properties"]["name"] == "circle"

        geojson = await client.get(
            f"/datasets/{ds.id}/features.geojson", headers=admin_auth_header
        )
        assert geojson.status_code == 200, geojson.text
        gj_features = geojson.json()["features"]
        assert len(gj_features) == 1
        assert gj_features[0]["geometry"]["type"] in LINEAR_GEOJSON_TYPES

"""Source-origin and refresh-state fields on Dataset (#1218, ADR-002).

Four properties this suite exists to hold:

1. The origin-pointer columns are CLOSED to the metadata PATCH. Two URL-ish
   fields now live on `datasets` — user-editable `source_url` and
   system-managed `origin_uri` — and the whole design rests on the second
   being unreachable from a request body.
2. `origin_ref` can only ever hold the keys its kind declares, which is what
   keeps a credential out of the binding (ADR-002 invariant 4) and external
   PostGIS federation out of v1 (gate 2).
3. NULL is the only stored spelling of "never determined"; "unknown" exists
   only on the wire.
4. The migration's backfill produces the documented shapes. The DB test runs
   the migration's OWN statements rather than a copy of them.

Each refusal is paired with an admission: a guard that starts rejecting valid
input fails silently otherwise, because nothing in a refusal assertion notices
it.
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.orm import joinedload

import app.modules.catalog.datasets.domain.models  # noqa: F401
from app.core.db import Base
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    Record,
    RecordDistribution,
)
from app.modules.catalog.records.service import (
    create_distribution,
    generate_distributions,
)
from app.platform.jobs.models import IngestJob
from app.platform.dataset_origin import (
    ORIGIN_KINDS,
    ORIGIN_REF_KEYS,
    SCHEMA_DRIFT_STATUS_VALUES,
    SERVICE_SOURCE_FORMATS,
    SOURCE_HEALTH_VALUES,
    UNKNOWN,
    build_origin_ref,
    classify_origin,
    project_unknown,
    service_auth_required,
    service_layer_identity,
    set_dataset_origin,
    set_postgis_origin,
)
from tests.factories import create_dataset as _create_dataset, get_user_id

# Formats that are neither service, nor stac, nor created — every one of them
# means "GeoLens holds a copy of bytes somebody uploaded".
_UPLOAD_FORMATS = (
    "geojson",
    "shapefile",
    "shp",
    "gpkg",
    "csv",
    "kml",
    "gml",
    "fgdb",
    "geotiff",
    "parquet",
    "json",
    "xlsx",
    "xls",
)

# Key names an attacker or a careless caller would most plausibly try to smuggle
# through. None appears in any kind's allowlist, so all of them must raise.
_SECRET_SHAPED_KEYS = (
    "token",
    "password",
    "authorization",
    "api_key",
    "secret",
    "access_key",
    "credentials",
)

# The seven columns this issue adds. Named once so the PATCH test cannot
# quietly cover fewer fields than it claims.
_SOURCE_STATE_COLUMNS = (
    "origin_uri",
    "origin_ref",
    "last_refreshed_at",
    "last_checked_at",
    "source_health",
    "source_health_detail",
    "schema_drift_status",
)


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0036_dataset_source_state.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0036", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Origin classification — derived, never stored
# ---------------------------------------------------------------------------


class TestClassifyOrigin:
    @pytest.mark.parametrize("source_format", sorted(SERVICE_SOURCE_FORMATS))
    def test_service_formats_classify_as_service(self, source_format: str) -> None:
        assert classify_origin(source_format, "vector_dataset") == "service"

    @pytest.mark.parametrize("source_format", _UPLOAD_FORMATS)
    def test_upload_formats_classify_as_upload(self, source_format: str) -> None:
        assert classify_origin(source_format, "vector_dataset") == "upload"

    def test_stac_and_created_keep_their_own_names(self) -> None:
        assert classify_origin("stac", "raster_dataset") == "stac"
        assert classify_origin("created", "vector_dataset") == "created"

    @pytest.mark.parametrize("record_type", ["vector_dataset", "table"])
    def test_absent_source_format_means_referenced_in_place(
        self, record_type: str
    ) -> None:
        """Registration stores no source_format — null is postgis, not unknown.

        Both record types registration can produce are covered: create_dataset
        assigns 'table' when the source has no geometry and 'vector_dataset'
        otherwise, and register_existing_table stamps a postgis origin either
        way. Asserted rather than assumed (#1218 review).
        """
        assert classify_origin(None, record_type) == "postgis"
        assert classify_origin("", record_type) == "postgis"

    def test_record_type_defaults_to_vector_dataset(self) -> None:
        assert classify_origin("gpkg") == "upload"

    @pytest.mark.parametrize("record_type", ["collection", "vrt_dataset"])
    def test_composed_and_container_types_have_no_origin(
        self, record_type: str
    ) -> None:
        """A VRT is built from other datasets; a collection has no dataset row."""
        assert classify_origin(None, record_type) is None
        assert classify_origin("geotiff", record_type) is None

    def test_raster_record_type_does_not_suppress_its_origin(self) -> None:
        """The other direction: only collection/vrt are origin-less."""
        assert classify_origin("geotiff", "raster_dataset") == "upload"
        assert classify_origin("gpkg", "table") == "upload"

    def test_every_classification_is_a_declared_kind(self) -> None:
        formats = [None, "created", "stac", *SERVICE_SOURCE_FORMATS, *_UPLOAD_FORMATS]
        for source_format in formats:
            assert classify_origin(source_format, "vector_dataset") in ORIGIN_KINDS


# ---------------------------------------------------------------------------
# origin_ref allowlist — invariant 4 and gate 2
# ---------------------------------------------------------------------------


class TestOriginRefAllowlist:
    @pytest.mark.parametrize("kind", sorted(ORIGIN_REF_KEYS))
    @pytest.mark.parametrize("key", _SECRET_SHAPED_KEYS)
    def test_secret_shaped_keys_are_rejected_for_every_kind(
        self, kind: str, key: str
    ) -> None:
        with pytest.raises(ValueError, match="rejects key"):
            build_origin_ref(kind, **{key: "hunter2"})

    @pytest.mark.parametrize("kind", sorted(ORIGIN_REF_KEYS))
    def test_declared_keys_are_still_accepted(self, kind: str) -> None:
        """The admission half: a rejection rule that over-fires is silent."""
        fields = {key: f"value-{key}" for key in ORIGIN_REF_KEYS[kind]}
        ref = build_origin_ref(kind, **fields)
        if not fields:
            # `created` declares no keys and therefore has no payload at all.
            assert ref is None
            return
        assert ref is not None
        assert ref["kind"] == kind
        assert set(ref) == {"kind", *fields}

    @pytest.mark.parametrize(
        "key", ["host", "port", "dsn", "username", "connection_string", "database"]
    )
    def test_postgis_ref_admits_no_connection_detail(self, key: str) -> None:
        """Gate 2: federation needs a new origin kind, not a wider blob."""
        with pytest.raises(ValueError, match="rejects key"):
            build_origin_ref("postgis", **{key: "db.internal"})

    def test_postgis_ref_holds_the_table_name_and_who_owns_it(self) -> None:
        """fix(#1452): `managed` joined `table_name`, and nothing else did.

        It says whether GeoLens created the table the pointer already names,
        which is what delete needs to know before it drops one. That is an
        ownership fact about the same relation, not a second address, so gate
        2 is untouched — the connection-detail rejections above still hold.
        """
        assert ORIGIN_REF_KEYS["postgis"] == frozenset({"table_name", "managed"})
        assert build_origin_ref("postgis", table_name="data.parcels") == {
            "kind": "postgis",
            "table_name": "data.parcels",
        }
        assert build_origin_ref("postgis", table_name="data.buf", managed=True) == {
            "kind": "postgis",
            "table_name": "data.buf",
            "managed": True,
        }

    def test_absent_values_are_omitted_not_stored_as_null(self) -> None:
        """A file ingested before hashing existed simply has no file_hash key."""
        assert build_origin_ref("upload", filename="parcels.gpkg", file_hash=None) == {
            "kind": "upload",
            "filename": "parcels.gpkg",
        }

    def test_created_carries_no_payload(self) -> None:
        assert build_origin_ref("created") is None

    def test_unknown_kind_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown origin kind"):
            build_origin_ref("federated_postgis", table_name="x")

    def test_service_ref_keeps_url_and_layer_id_separate(self) -> None:
        ref = build_origin_ref(
            "service",
            service_type="arcgis_featureserver",
            url="https://example.test/arcgis/rest/services/Parcels/FeatureServer",
            layer_id="0",
        )
        assert ref == {
            "kind": "service",
            "layer_id": "0",
            "service_type": "arcgis_featureserver",
            "url": "https://example.test/arcgis/rest/services/Parcels/FeatureServer",
        }


class TestSetDatasetOrigin:
    def test_writes_both_columns(self) -> None:
        dataset = Dataset(record_id=uuid.uuid4(), table_name="ds_x")
        set_dataset_origin(
            dataset, "stac", uri="https://example.test/a.tif", asset_href="https://e/a"
        )
        assert dataset.origin_uri == "https://example.test/a.tif"
        assert dataset.origin_ref == {"kind": "stac", "asset_href": "https://e/a"}

    def test_upload_has_no_uri(self) -> None:
        dataset = Dataset(record_id=uuid.uuid4(), table_name="ds_x")
        set_dataset_origin(dataset, "upload", filename="parcels.gpkg")
        assert dataset.origin_uri is None
        assert dataset.origin_ref == {"kind": "upload", "filename": "parcels.gpkg"}

    def test_unknown_kind_raises_before_touching_the_row(self) -> None:
        dataset = Dataset(record_id=uuid.uuid4(), table_name="ds_x")
        with pytest.raises(ValueError, match="unknown origin kind"):
            set_dataset_origin(dataset, "sftp", uri="sftp://host/x")
        assert dataset.origin_uri is None
        assert dataset.origin_ref is None

    def test_rebinding_to_a_different_origin_clears_probe_state(self) -> None:
        """fix(#1271 review): the stored probe verdict describes the origin
        the binding names. A service marked missing and then reuploaded from
        a local file would otherwise serve missing/not_found forever, since
        the probe endpoint 409s on uploads and nothing could correct it."""
        dataset = Dataset(record_id=uuid.uuid4(), table_name="ds_x")
        set_dataset_origin(
            dataset,
            "service",
            uri="https://svc.test/wfs/roads",
            service_type="wfs",
            url="https://svc.test/wfs",
            layer_id="roads",
        )
        dataset.source_health = "missing"
        dataset.source_health_detail = "not_found"
        dataset.last_checked_at = datetime(2026, 8, 1, tzinfo=timezone.utc)

        set_dataset_origin(dataset, "upload", filename="roads.gpkg")

        assert dataset.source_health is None
        assert dataset.source_health_detail is None
        assert dataset.last_checked_at is None

    def test_identical_restamp_also_clears_probe_state(self) -> None:
        """fix(#1271 review): every caller is a successful-ingest commit, so
        an identical restamp means the SAME origin was just exercised — a
        pre-swap ``missing`` verdict is stale in the other direction (the
        origin demonstrably answered). NULL-means-unknown is the honest
        state either way; a recovered origin must not keep reporting the
        failure the swap just disproved."""
        dataset = Dataset(record_id=uuid.uuid4(), table_name="ds_x")
        set_dataset_origin(
            dataset,
            "service",
            uri="https://svc.test/wfs/roads",
            service_type="wfs",
            url="https://svc.test/wfs",
            layer_id="roads",
        )
        dataset.source_health = "missing"
        dataset.source_health_detail = "not_found"
        dataset.last_checked_at = datetime(2026, 8, 1, tzinfo=timezone.utc)

        set_dataset_origin(
            dataset,
            "service",
            uri="https://svc.test/wfs/roads",
            service_type="wfs",
            url="https://svc.test/wfs",
            layer_id="roads",
        )

        assert dataset.source_health is None
        assert dataset.source_health_detail is None
        assert dataset.last_checked_at is None

    def test_postgis_pointer_and_ref_name_the_same_table(self) -> None:
        """Two spellings of one fact; set_postgis_origin owns keeping them equal."""
        dataset = Dataset(record_id=uuid.uuid4(), table_name="parcels")
        set_postgis_origin(dataset, "parcels", schema="data")
        assert dataset.origin_uri == "postgis://data.parcels"
        assert dataset.origin_ref == {"kind": "postgis", "table_name": "data.parcels"}
        assert dataset.origin_uri == f"postgis://{dataset.origin_ref['table_name']}"

    def test_postgis_origin_names_the_schema_it_is_given(self) -> None:
        """A tenant's table lives in its own schema and the pointer must say so.

        The schema is a required keyword rather than something derived from
        the dataset row, because dataset.tenant_id is NULL on the ORM instance
        in multi-tenant mode: the insert trigger fills it in the database
        (#1218 review r2). Callers hand over the schema they actually used.
        """
        tenant_schema = "data_t_aaaaaaaa_bbbb_cccc_dddd_eeeeeeeeeeee"
        dataset = Dataset(record_id=uuid.uuid4(), table_name="parcels")
        set_postgis_origin(dataset, "parcels", schema=tenant_schema)
        assert dataset.origin_uri == f"postgis://{tenant_schema}.parcels"
        assert dataset.origin_ref["table_name"] == f"{tenant_schema}.parcels"

    def test_postgis_origin_cannot_be_stamped_without_a_schema(self) -> None:
        """Keyword-only and required: no positional tenant_id can slip back in."""
        dataset = Dataset(record_id=uuid.uuid4(), table_name="parcels")
        with pytest.raises(TypeError):
            set_postgis_origin(dataset, "parcels")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# NULL is the only stored spelling of "never determined"
# ---------------------------------------------------------------------------


class TestUnknownProjection:
    def test_unknown_is_not_storable(self) -> None:
        assert UNKNOWN not in SOURCE_HEALTH_VALUES
        assert UNKNOWN not in SCHEMA_DRIFT_STATUS_VALUES

    def test_check_constraints_exclude_unknown(self) -> None:
        table = Base.metadata.tables["catalog.datasets"]
        constraints = {
            c.name: str(c.sqltext)
            for c in table.constraints
            if isinstance(c, sa.CheckConstraint) and c.name
        }
        for name in ("chk_datasets_source_health", "chk_datasets_schema_drift_status"):
            assert f"'{UNKNOWN}'" not in constraints[name]

    def test_null_projects_to_unknown_and_values_pass_through(self) -> None:
        assert project_unknown(None) == UNKNOWN
        for value in (*SOURCE_HEALTH_VALUES, *SCHEMA_DRIFT_STATUS_VALUES):
            assert project_unknown(value) == value


# ---------------------------------------------------------------------------
# ORM shape and migration structure — no database required
# ---------------------------------------------------------------------------


class TestOrmAndMigrationShape:
    def test_orm_declares_every_source_state_column_as_nullable(self) -> None:
        table = Base.metadata.tables["catalog.datasets"]
        for name in _SOURCE_STATE_COLUMNS:
            assert name in table.columns, f"missing column {name}"
            assert table.columns[name].nullable is True

    def test_health_and_drift_check_constraints_match_the_adr(self) -> None:
        table = Base.metadata.tables["catalog.datasets"]
        constraints = {
            c.name: " ".join(str(c.sqltext).split())
            for c in table.constraints
            if isinstance(c, sa.CheckConstraint) and c.name
        }
        assert constraints["chk_datasets_source_health"] == (
            "source_health IS NULL OR source_health IN "
            "('healthy', 'missing', 'inaccessible')"
        )
        assert constraints["chk_datasets_schema_drift_status"] == (
            "schema_drift_status IS NULL OR schema_drift_status IN ('none', 'drifted')"
        )

    def test_origin_uri_partial_index_exists(self) -> None:
        table = Base.metadata.tables["catalog.datasets"]
        matches = [i for i in table.indexes if i.name == "ix_datasets_origin_uri"]
        assert len(matches) == 1
        index = matches[0]
        assert [c.name for c in index.columns] == ["origin_uri"]
        predicate = index.dialect_options["postgresql"]["where"]
        assert str(predicate) == "origin_uri IS NOT NULL"

    def test_migration_chains_onto_the_quality_score_drop(self) -> None:
        module = _load_migration()
        assert module.revision == "0036_dataset_source_state"
        assert module.down_revision == "0035_drop_quality_score_numeric"

    def test_downgrade_drops_every_column_the_upgrade_adds(self) -> None:
        module = _load_migration()
        source = (
            Path(__file__).resolve().parents[1]
            / "alembic"
            / "versions"
            / "0036_dataset_source_state.py"
        ).read_text(encoding="utf-8")
        for name in _SOURCE_STATE_COLUMNS:
            assert f'sa.Column("{name}"' in source, f"upgrade never adds {name}"
            assert f'"{name}",' in source, f"downgrade never drops {name}"
        assert len(module.backfill_statements()) == 5


# ---------------------------------------------------------------------------
# The PATCH write path stays closed
# ---------------------------------------------------------------------------


_SENTINEL_STATE = {
    "origin_uri": "https://origin.test/services/Parcels/FeatureServer/0",
    "origin_ref": {"kind": "service", "service_type": "wfs", "url": "https://o.test"},
    "last_refreshed_at": datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    "last_checked_at": datetime(2026, 1, 2, 3, 4, 6, tzinfo=timezone.utc),
    "source_health": "healthy",
    "source_health_detail": "probe ok",
    "schema_drift_status": "none",
}

_ATTACKER_BODY = {
    "origin_uri": "https://attacker.test/evil",
    "origin_ref": {"kind": "service", "token": "leaked"},
    "last_refreshed_at": "2030-01-01T00:00:00Z",
    "last_checked_at": "2030-01-01T00:00:00Z",
    "source_health": "missing",
    "source_health_detail": "attacker supplied",
    "schema_drift_status": "drifted",
    "origin": "postgis",
}


class TestPatchCannotReachSourceState:
    async def test_patch_ignores_every_source_state_field(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ) -> None:
        """Refusal AND admission in one request: the editable field must land."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Origin PATCH Guard",
            source_format="wfs",
        )
        for attr, value in _SENTINEL_STATE.items():
            setattr(ds, attr, value)
        ds.source_url = "https://origin.test/describe"
        await test_db_session.commit()

        resp = await client.patch(
            f"/datasets/{ds.id}",
            json={
                **_ATTACKER_BODY,
                # The control: a field that IS in _DATASET_FIELD_MAP. Without
                # it, a PATCH rejected wholesale would pass this test.
                "source_url": "https://edited.test/describe",
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["source_url"] == "https://edited.test/describe"

        await test_db_session.refresh(ds)
        for attr, value in _SENTINEL_STATE.items():
            assert getattr(ds, attr) == value, f"PATCH mutated {attr}"

    async def test_dataset_meta_schema_declares_no_source_state_field(self) -> None:
        """Structural half: the fields are absent from the request model too.

        The runtime test above proves today's handler ignores them. This one
        keeps a future field from being added to DatasetMeta and silently
        wired through _apply_simple_field_assignments.
        """
        from app.modules.catalog.datasets.domain.schemas import DatasetMeta

        for name in (*_SOURCE_STATE_COLUMNS, "origin"):
            assert name not in DatasetMeta.model_fields


class TestResponseExposure:
    async def test_never_probed_dataset_reports_unknown(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Never Probed",
            source_format="gpkg",
        )
        await test_db_session.commit()

        resp = await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)
        assert resp.status_code == 200
        body = resp.json()
        assert body["source_health"] == UNKNOWN
        assert body["schema_drift_status"] == UNKNOWN
        assert body["last_refreshed_at"] is None
        assert body["origin_uri"] is None
        # Computed, not stored — the column does not exist.
        assert body["origin"] == "upload"

    @pytest.mark.parametrize("record_type", ["vector_dataset", "table"])
    async def test_registered_table_reports_postgis_origin(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        record_type: str,
    ) -> None:
        """A registered table serves origin=postgis whether or not it has geometry.

        The non-spatial half is the one worth pinning: create_dataset gives a
        geometry-less registration record_type='table', and nothing else in
        the suite would notice if that started classifying as an upload.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name=f"Registered {record_type}",
            source_format=None,
        )
        ds.record.record_type = record_type
        await test_db_session.commit()

        resp = await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)
        assert resp.status_code == 200
        assert resp.json()["origin"] == "postgis"

    async def test_stored_state_reaches_the_response(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Probed Service",
            source_format="arcgis_featureserver",
        )
        for attr, value in _SENTINEL_STATE.items():
            setattr(ds, attr, value)
        await test_db_session.commit()

        resp = await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)
        assert resp.status_code == 200
        body = resp.json()
        assert body["origin"] == "service"
        assert body["origin_uri"] == _SENTINEL_STATE["origin_uri"]
        assert body["origin_ref"] == _SENTINEL_STATE["origin_ref"]
        assert body["source_health"] == "healthy"
        assert body["schema_drift_status"] == "none"
        assert body["source_health_detail"] == "probe ok"
        assert body["last_refreshed_at"].startswith("2026-01-02T03:04:05")


# ---------------------------------------------------------------------------
# Backfill, against pre-migration-shaped rows
# ---------------------------------------------------------------------------


async def _pre_migration_dataset(session, *, created_by, **kwargs) -> Dataset:
    """A dataset row as it looked before 0036 ran: source columns, no origin."""
    ds = await _create_dataset(session, created_by=created_by, **kwargs)
    for name in _SOURCE_STATE_COLUMNS:
        setattr(ds, name, None)
    await session.flush()
    return ds


class TestBackfill:
    async def test_backfill_derives_each_origin_shape(self, test_db_session) -> None:
        """Runs migration 0036's OWN statements, then rolls them back.

        The statements are unscoped UPDATEs over catalog.datasets — that is
        what a migration is — so they run inside a savepoint that is discarded.
        Leaving them committed would rewrite every other test's rows on this
        shared per-worker database.
        """
        module = _load_migration()
        admin_id = await get_user_id(test_db_session, "admin")

        arcgis = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Backfill ArcGIS",
            source_format="arcgis_featureserver",
        )
        arcgis.source_url = (
            "https://gis.test/arcgis/rest/services/Parcels/FeatureServer/7"
        )

        wfs = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Backfill WFS",
            source_format="wfs",
        )
        # fix(#1218 review r4): the ENRICHED form ingest actually persists.
        # The probe puts the layer name in layer_id for WFS, so
        # tasks_vector composes <base>/<typename> into datasets.source_url.
        wfs.source_url = "https://gis.test/geoserver/wfs/topp:parcels"
        # fix(#1218 review r3): a WFS layer is identified by its typename,
        # which lives on the ingest job. The retention sweep exempts each
        # dataset's newest complete job precisely so this hint survives, and
        # r4 takes the un-enriched base from the same row.
        test_db_session.add(
            IngestJob(
                dataset_id=wfs.id,
                status="complete",
                source_url="https://gis.test/geoserver/wfs",
                source_filename="Parcels (2024)",
                source_layer="topp:parcels",
                created_by=admin_id,
            )
        )

        # Same shape, no surviving job row: the layer identity is simply gone.
        # source_filename holds `layer_title or layer_name` and nothing says
        # which, so it must NOT be used as a fallback.
        wfs_orphan = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Backfill WFS No Job",
            source_format="wfs",
            source_filename="Human Readable Title",
        )
        wfs_orphan.source_url = "https://gis.test/geoserver/wfs2/Human Readable Title"

        # A user PATCHed source_url to prose before the migration ran. A
        # pointer that does not parse must stay NULL rather than be
        # backfilled into a refresh that can never work.
        prose = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Backfill Prose",
            source_format="wfs",
        )
        prose.source_url = "Downloaded from the county GIS portal in March"

        stac = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Backfill STAC",
            source_format="stac",
        )
        stac.source_url = "https://stac.test/items/abc/asset.tif"

        registered = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Backfill Registered",
            source_format=None,
            table_name="backfill_registered_tbl",
        )

        # A geometry-less registration: create_dataset gives it
        # record_type='table'. Covered because register_existing_table stamps
        # the origin either way, so a backfill restricted to 'vector_dataset'
        # would leave these permanently different from post-migration
        # registrations (#1218 review).
        nonspatial = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Backfill Registered Nonspatial",
            source_format=None,
            table_name="backfill_nonspatial_tbl",
        )
        nonspatial.record.record_type = "table"

        upload = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Backfill Upload",
            source_format="gpkg",
            source_filename="parcels.gpkg",
        )

        created = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Backfill Created",
            source_format="created",
        )

        # Registered-shaped catalog row whose physical table is gone. A
        # pointer at a table that does not exist is worse than none, because
        # NULL at least reads as "unknown".
        orphan = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Backfill Orphan",
            source_format=None,
            table_name="backfill_orphan_tbl_absent",
        )
        await test_db_session.flush()

        savepoint = await test_db_session.begin_nested()
        try:
            # The postgis backfill reads the physical table's schema out of
            # pg_class rather than computing one from tenant_id, so the table
            # has to exist. DDL is transactional, so the savepoint rollback
            # takes it away again.
            await test_db_session.execute(
                sa.text("CREATE TABLE data.backfill_registered_tbl (id integer)")
            )
            await test_db_session.execute(
                sa.text("CREATE TABLE data.backfill_nonspatial_tbl (id integer)")
            )
            for statement in module.backfill_statements():
                await test_db_session.execute(statement)
            # upgrade() runs the authority pass right after the SQL, so every
            # backfill test runs it too or it asserts on a half-built state.
            await test_db_session.run_sync(
                lambda sync_session: module.purge_credential_bearing_pointers(
                    sync_session.connection()
                )
            )

            rows = {
                row.id: row
                for row in (
                    await test_db_session.execute(
                        sa.text(
                            "SELECT id, origin_uri, origin_ref, last_refreshed_at "
                            "FROM catalog.datasets WHERE id = ANY(:ids)"
                        ).bindparams(
                            sa.bindparam(
                                "ids",
                                value=[
                                    arcgis.id,
                                    wfs.id,
                                    wfs_orphan.id,
                                    prose.id,
                                    stac.id,
                                    registered.id,
                                    nonspatial.id,
                                    upload.id,
                                    created.id,
                                    orphan.id,
                                ],
                            )
                        )
                    )
                ).all()
            }

            arcgis_row = rows[arcgis.id]
            assert arcgis_row.origin_uri == arcgis.source_url
            assert arcgis_row.origin_ref == {
                "kind": "service",
                "service_type": "arcgis_featureserver",
                "url": "https://gis.test/arcgis/rest/services/Parcels/FeatureServer",
                "layer_id": "7",
            }

            wfs_row = rows[wfs.id]
            # origin_uri keeps the enriched form as provenance...
            assert wfs_row.origin_uri == "https://gis.test/geoserver/wfs/topp:parcels"
            # ...while the ref carries the BASE plus the layer separately.
            assert wfs_row.origin_ref == {
                "kind": "service",
                "service_type": "wfs",
                "url": "https://gis.test/geoserver/wfs",
                "layer_id": "topp:parcels",
            }
            assert not wfs_row.origin_ref["url"].endswith("topp:parcels"), (
                "the invariant: origin_ref.url is the base and never embeds "
                "the layer, or a refresh addresses the wrong endpoint"
            )

            orphan_wfs_row = rows[wfs_orphan.id]
            # No surviving job, so neither the base nor the layer is
            # derivable. A wrong base would break the invariant, so the ref
            # carries neither and origin_uri keeps the full URL for a human.
            assert orphan_wfs_row.origin_ref == {
                "kind": "service",
                "service_type": "wfs",
            }, "a human title must never be backfilled as the layer identifier"
            assert "layer_id" not in orphan_wfs_row.origin_ref
            assert "url" not in orphan_wfs_row.origin_ref
            assert orphan_wfs_row.origin_uri == (
                "https://gis.test/geoserver/wfs2/Human Readable Title"
            )

            prose_row = rows[prose.id]
            assert prose_row.origin_uri is None
            assert prose_row.origin_ref is None

            stac_row = rows[stac.id]
            assert stac_row.origin_uri == stac.source_url
            assert stac_row.origin_ref == {
                "kind": "stac",
                "asset_href": "https://stac.test/items/abc/asset.tif",
            }

            registered_row = rows[registered.id]
            assert registered_row.origin_uri == (
                "postgis://data.backfill_registered_tbl"
            )
            assert registered_row.origin_ref == {
                "kind": "postgis",
                "table_name": "data.backfill_registered_tbl",
            }

            nonspatial_row = rows[nonspatial.id]
            assert nonspatial_row.origin_uri == (
                "postgis://data.backfill_nonspatial_tbl"
            )
            assert nonspatial_row.origin_ref == {
                "kind": "postgis",
                "table_name": "data.backfill_nonspatial_tbl",
            }

            upload_row = rows[upload.id]
            assert upload_row.origin_uri is None, "an upload has no remote origin"
            assert upload_row.origin_ref == {
                "kind": "upload",
                "filename": "parcels.gpkg",
            }

            created_row = rows[created.id]
            assert created_row.origin_uri is None
            assert created_row.origin_ref is None

            orphan_row = rows[orphan.id]
            assert orphan_row.origin_uri is None
            assert orphan_row.origin_ref is None

            # Every row gets a last_refreshed_at floor from its record.
            for row in rows.values():
                assert row.last_refreshed_at is not None
        finally:
            await savepoint.rollback()

    async def test_backfill_prefers_the_newest_version_upload(
        self, test_db_session
    ) -> None:
        """Version history beats records.created_at — a re-upload IS a refresh."""
        from app.modules.catalog.collections.models import DatasetVersion

        module = _load_migration()
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Backfill Versioned",
            source_format="gpkg",
            source_filename="v.gpkg",
        )
        newest = datetime.now(timezone.utc) + timedelta(days=1)
        test_db_session.add_all(
            [
                DatasetVersion(
                    dataset_id=ds.id,
                    version_number=1,
                    uploaded_at=newest - timedelta(days=2),
                    file_hash="older-hash",
                ),
                DatasetVersion(
                    dataset_id=ds.id,
                    version_number=2,
                    uploaded_at=newest,
                    file_hash="newest-hash",
                ),
            ]
        )
        await test_db_session.flush()

        savepoint = await test_db_session.begin_nested()
        try:
            for statement in module.backfill_statements():
                await test_db_session.execute(statement)
            # upgrade() runs the authority pass right after the SQL, so every
            # backfill test runs it too or it asserts on a half-built state.
            await test_db_session.run_sync(
                lambda sync_session: module.purge_credential_bearing_pointers(
                    sync_session.connection()
                )
            )
            row = (
                await test_db_session.execute(
                    sa.text(
                        "SELECT origin_ref, last_refreshed_at "
                        "FROM catalog.datasets WHERE id = :id"
                    ).bindparams(sa.bindparam("id", value=ds.id))
                )
            ).one()
            assert row.origin_ref["file_hash"] == "newest-hash"
            assert row.last_refreshed_at == newest
        finally:
            await savepoint.rollback()

    async def test_backfill_leaves_vrt_datasets_alone(self, test_db_session) -> None:
        """A VRT stores a null source_format too; record_type is what excludes it."""
        module = _load_migration()
        admin_id = await get_user_id(test_db_session, "admin")
        record = Record(
            title="Backfill VRT",
            record_type="vrt_dataset",
            visibility="private",
            record_status="published",
            created_by=admin_id,
        )
        test_db_session.add(record)
        await test_db_session.flush()
        vrt = Dataset(
            record_id=record.id,
            table_name=f"vrt_{uuid.uuid4().hex[:12]}",
            source_format=None,
        )
        test_db_session.add(vrt)
        await test_db_session.flush()

        savepoint = await test_db_session.begin_nested()
        try:
            for statement in module.backfill_statements():
                await test_db_session.execute(statement)
            # upgrade() runs the authority pass right after the SQL, so every
            # backfill test runs it too or it asserts on a half-built state.
            await test_db_session.run_sync(
                lambda sync_session: module.purge_credential_bearing_pointers(
                    sync_session.connection()
                )
            )
            row = (
                await test_db_session.execute(
                    sa.text(
                        "SELECT origin_uri, origin_ref FROM catalog.datasets "
                        "WHERE id = :id"
                    ).bindparams(sa.bindparam("id", value=vrt.id))
                )
            ).one()
            assert row.origin_uri is None
            assert row.origin_ref is None
        finally:
            await savepoint.rollback()

    async def test_same_table_name_in_two_tenant_schemas_stays_null(
        self, test_db_session
    ) -> None:
        """Cross-tenant collisions resolve to NULL, never to the wrong tenant.

        fix(#1218 review, P1): table names are unique per tenant but not
        across tenants, so two tenants can both own a `parcels` table. The
        schema lookup keys on `d.table_name` alone and cannot tell the two
        catalog rows apart, so per-row resolution is not expressible here —
        both rows staying NULL is the only answer that cannot be wrong. An
        unconstrained LIMIT 1 would instead hand one dataset a pointer into
        the other tenant's schema, permanently and silently.
        """
        module = _load_migration()
        admin_id = await get_user_id(test_db_session, "admin")
        shared_name = f"collide_{uuid.uuid4().hex[:10]}"
        # The shared-schema row keeps tenant_id NULL; the tenant row carries
        # one. That is what makes the name collision legal in the first place:
        # uq_datasets_table_name_global is partial on tenant_id IS NULL, and
        # uq_datasets_table_name_tenant keys on (tenant_id, table_name).
        tenant_id = uuid.uuid4()
        tenant_schema = f"data_t_{str(tenant_id).replace('-', '_')}"

        first = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Collision Shared Schema",
            source_format=None,
            table_name=shared_name,
        )
        # Built directly rather than through the factory: tenant_id has to be
        # set at INSERT time, or the partial unique index on tenant_id IS NULL
        # rejects the row before it can become the tenant-owned twin.
        tenant_record = Record(
            title="Collision Tenant Schema",
            record_type="vector_dataset",
            visibility="private",
            record_status="published",
            created_by=admin_id,
        )
        test_db_session.add(tenant_record)
        await test_db_session.flush()
        second = Dataset(
            record_id=tenant_record.id,
            table_name=shared_name,
            source_format=None,
            tenant_id=tenant_id,
        )
        test_db_session.add(second)
        await test_db_session.flush()

        savepoint = await test_db_session.begin_nested()
        try:
            await test_db_session.execute(sa.text(f'CREATE SCHEMA "{tenant_schema}"'))
            await test_db_session.execute(
                sa.text(f"CREATE TABLE data.{shared_name} (id integer)")
            )
            await test_db_session.execute(
                sa.text(f'CREATE TABLE "{tenant_schema}".{shared_name} (id integer)')
            )
            for statement in module.backfill_statements():
                await test_db_session.execute(statement)
            # upgrade() runs the authority pass right after the SQL, so every
            # backfill test runs it too or it asserts on a half-built state.
            await test_db_session.run_sync(
                lambda sync_session: module.purge_credential_bearing_pointers(
                    sync_session.connection()
                )
            )

            rows = (
                await test_db_session.execute(
                    sa.text(
                        "SELECT id, origin_uri, origin_ref FROM catalog.datasets "
                        "WHERE id = ANY(:ids)"
                    ).bindparams(sa.bindparam("ids", value=[first.id, second.id]))
                )
            ).all()
            assert len(rows) == 2
            for row in rows:
                assert row.origin_uri is None, "ambiguous schema must not resolve"
                assert row.origin_ref is None
        finally:
            await savepoint.rollback()

    async def test_two_claimants_on_one_surviving_table_stay_null(
        self, test_db_session
    ) -> None:
        """The catalog half of the ambiguity guard (#1218 review r2).

        Two tenants both registered `parcels` and one tenant's physical table
        was later dropped. The physical count is then a clean 1, so the
        relation guard is satisfied and BOTH catalog rows would bind to the
        surviving tenant's schema — leaving one of them an orphan pointing
        into another tenant's data.

        Resolution requires exactly one physical relation AND exactly one
        catalog claimant. This pins the second half; the sibling test above
        pins the first, and neither subsumes the other.
        """
        module = _load_migration()
        admin_id = await get_user_id(test_db_session, "admin")
        shared_name = f"orphan_{uuid.uuid4().hex[:10]}"
        tenant_id = uuid.uuid4()

        survivor = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Claimant With Table",
            source_format=None,
            table_name=shared_name,
        )
        orphan_record = Record(
            title="Claimant Whose Table Was Dropped",
            record_type="vector_dataset",
            visibility="private",
            record_status="published",
            created_by=admin_id,
        )
        test_db_session.add(orphan_record)
        await test_db_session.flush()
        orphaned = Dataset(
            record_id=orphan_record.id,
            table_name=shared_name,
            source_format=None,
            tenant_id=tenant_id,
        )
        test_db_session.add(orphaned)
        await test_db_session.flush()

        savepoint = await test_db_session.begin_nested()
        try:
            # Exactly ONE physical relation: the other tenant's table is gone.
            await test_db_session.execute(
                sa.text(f"CREATE TABLE data.{shared_name} (id integer)")
            )
            for statement in module.backfill_statements():
                await test_db_session.execute(statement)
            # upgrade() runs the authority pass right after the SQL, so every
            # backfill test runs it too or it asserts on a half-built state.
            await test_db_session.run_sync(
                lambda sync_session: module.purge_credential_bearing_pointers(
                    sync_session.connection()
                )
            )

            rows = (
                await test_db_session.execute(
                    sa.text(
                        "SELECT id, origin_uri, origin_ref FROM catalog.datasets "
                        "WHERE id = ANY(:ids)"
                    ).bindparams(sa.bindparam("ids", value=[survivor.id, orphaned.id]))
                )
            ).all()
            assert len(rows) == 2
            for row in rows:
                assert row.origin_uri is None, (
                    "one physical table with two catalog claimants must not "
                    "resolve for either of them"
                )
                assert row.origin_ref is None
        finally:
            await savepoint.rollback()

    async def test_credential_bearing_urls_are_never_frozen_into_the_pointer(
        self, test_db_session
    ) -> None:
        """A legacy secret must not be copied into a read-only column.

        fix(#1218 review r5): source_url is PATCHable, so an operator who
        spots a credential in it can edit it away. origin_uri and origin_ref
        are read-only on DatasetResponse, so a secret copied there is stuck.
        New ingests cannot produce one — _validate_service_url refuses both
        shapes at submission (sources/schemas.py:91) — but rows predating that
        gate still hold them.
        """
        module = _load_migration()
        admin_id = await get_user_id(test_db_session, "admin")

        userinfo = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Cred Userinfo",
            source_format="wfs",
        )
        userinfo.source_url = "https://bob:hunter2@gis.test/geoserver/wfs"

        token_param = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Cred Token Param",
            source_format="arcgis_featureserver",
        )
        token_param.source_url = (
            "https://gis.test/rest/services/P/FeatureServer/3?token=hunter2"
        )

        # The admission half: a benign query param must still backfill, or the
        # guard has quietly stopped every legacy service row from resolving.
        benign = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Cred Benign Query",
            source_format="wfs",
        )
        benign.source_url = "https://gis.test/geoserver/wfs?service=WFS&version=2.0.0"
        test_db_session.add(
            IngestJob(
                dataset_id=benign.id,
                status="complete",
                source_url="https://gis.test/geoserver/wfs?service=WFS&version=2.0.0",
                source_layer="topp:benign",
                created_by=admin_id,
            )
        )

        # A clean dataset URL whose recovered JOB url carries the secret: the
        # guard has to cover that second source too, not just the first.
        dirty_job = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Cred Dirty Job",
            source_format="wfs",
        )
        dirty_job.source_url = "https://gis.test/geoserver/wfs/topp:secret"
        test_db_session.add(
            IngestJob(
                dataset_id=dirty_job.id,
                status="complete",
                source_url="https://svc:pw@gis.test/geoserver/wfs",
                source_layer="topp:secret",
                created_by=admin_id,
            )
        )

        # fix(#1218 review r6): parse_qsl decodes a parameter NAME before
        # judging it, so this reads as ?token= in Python. The SQL refuses any
        # encoded NAME outright rather than decoding, closing the class.
        encoded_name = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Cred Encoded Name",
            source_format="wfs",
        )
        encoded_name.source_url = "https://gis.test/geoserver/wfs?%74oken=hunter2"

        encoded_name_stac = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Cred Encoded Name STAC",
            source_format="stac",
        )
        encoded_name_stac.source_url = "https://bucket.test/s.tif?%73ig=deadbeef"

        # fix(#1218 review r7): parse_qsl decodes + to a space and
        # _is_sensitive_query_param strips whitespace, so this reads as
        # ?token= in Python. Same class as the encoded name above, third
        # spelling; the guard is derived from the transforms, not the
        # spellings, so literal whitespace is covered by the same arm.
        plus_name = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Cred Plus Name",
            source_format="wfs",
        )
        plus_name.source_url = "https://gis.test/geoserver/wfs?+token+=hunter2"

        plus_name_stac = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Cred Plus Name STAC",
            source_format="stac",
        )
        plus_name_stac.source_url = "https://bucket.test/s.tif?+sig+=deadbeef"

        space_name = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Cred Space Name",
            source_format="wfs",
        )
        space_name.source_url = "https://gis.test/geoserver/wfs? token =hunter2"

        # The admission half for r6: a percent-encoded VALUE is ordinary in a
        # WFS typename and must still backfill. The name segment ends at the
        # first '=' of its pair, which is what keeps these apart.
        encoded_value = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Cred Encoded Value",
            source_format="wfs",
        )
        # r7 admission: a + in a VALUE is ordinary too and must not trip the
        # name arm, so this URL carries both an encoded value and a plus one.
        encoded_value.source_url = (
            "https://gis.test/geoserver/wfs?typename=ns%3Aroads&q=a+b"
        )
        test_db_session.add(
            IngestJob(
                dataset_id=encoded_value.id,
                status="complete",
                source_url=("https://gis.test/geoserver/wfs?typename=ns%3Aroads&q=a+b"),
                source_layer="ns:roads",
                created_by=admin_id,
            )
        )

        # fix(#1218 review r7): shapes the SQL pre-filter CANNOT express, so
        # the Python authority pass is the only thing that catches them.
        # has_url_credentials returns True whenever urlsplit REFUSES an
        # authority, and both of these make it refuse.
        fullwidth_at = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Cred Fullwidth At",
            source_format="wfs",
        )
        fullwidth_at.source_url = "https://bob:hunter2＠gis.test/geoserver/wfs"

        malformed_authority = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Cred Malformed Authority",
            source_format="stac",
        )
        malformed_authority.source_url = "https://[::1/scene.tif"

        stac_cred = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Cred STAC Presigned",
            source_format="stac",
        )
        stac_cred.source_url = "https://bucket.test/scene.tif?X-Amz-Signature=deadbeef"
        await test_db_session.flush()

        savepoint = await test_db_session.begin_nested()
        try:
            for statement in module.backfill_statements():
                await test_db_session.execute(statement)
            # upgrade() runs the authority pass right after the SQL, so every
            # backfill test runs it too or it asserts on a half-built state.
            await test_db_session.run_sync(
                lambda sync_session: module.purge_credential_bearing_pointers(
                    sync_session.connection()
                )
            )
            rows = {
                r.id: r
                for r in (
                    await test_db_session.execute(
                        sa.text(
                            "SELECT id, source_url, origin_uri, origin_ref "
                            "FROM catalog.datasets WHERE id = ANY(:ids)"
                        ).bindparams(
                            sa.bindparam(
                                "ids",
                                value=[
                                    userinfo.id,
                                    token_param.id,
                                    benign.id,
                                    dirty_job.id,
                                    stac_cred.id,
                                    encoded_name.id,
                                    encoded_name_stac.id,
                                    encoded_value.id,
                                    plus_name.id,
                                    plus_name_stac.id,
                                    space_name.id,
                                    fullwidth_at.id,
                                    malformed_authority.id,
                                ],
                            )
                        )
                    )
                ).all()
            }

            for unsafe in (
                userinfo,
                token_param,
                stac_cred,
                encoded_name,
                encoded_name_stac,
                plus_name,
                plus_name_stac,
                space_name,
                fullwidth_at,
                malformed_authority,
            ):
                row = rows[unsafe.id]
                assert row.origin_uri is None, f"{row.source_url} was frozen in"
                assert row.origin_ref is None
                # The secret stays only where the operator can still edit it.
                assert row.source_url == unsafe.source_url

            encoded_value_row = rows[encoded_value.id]
            assert encoded_value_row.origin_uri == encoded_value.source_url, (
                "an encoded or plus-bearing VALUE is ordinary; only NAMES "
                "carrying %, + or whitespace are refused"
            )
            assert encoded_value_row.origin_ref["layer_id"] == "ns:roads"

            benign_row = rows[benign.id]
            assert benign_row.origin_uri == benign.source_url, (
                "the guard must not refuse an ordinary WFS query string"
            )
            assert benign_row.origin_ref["layer_id"] == "topp:benign"

            dirty_job_row = rows[dirty_job.id]
            assert "svc:pw@" not in (dirty_job_row.origin_uri or "")
            assert "svc:pw@" not in str(dirty_job_row.origin_ref)
            # The job's layer survives; only its credential-bearing url is dropped.
            assert dirty_job_row.origin_ref["layer_id"] == "topp:secret"
            assert "url" not in dirty_job_row.origin_ref
        finally:
            await savepoint.rollback()

    async def test_an_upload_claiming_the_name_blocks_resolution(
        self, test_db_session
    ) -> None:
        """A claimant of ANY origin counts, not just registered ones.

        fix(#1218 review r8): the claimant guard used to look only at rows
        this backfill targets (null source_format, vector_dataset/table).
        Uploads, service imports and created datasets own physical tables with
        tenant-local names too, so tenant A's dropped registered `roads`
        beside tenant B's surviving UPLOADED `roads` is one physical relation
        with a claimant the narrow filter could not see, and B's schema would
        have been stamped onto A's orphan.
        """
        module = _load_migration()
        admin_id = await get_user_id(test_db_session, "admin")
        shared_name = f"anyclaim_{uuid.uuid4().hex[:10]}"

        # The registered row whose own physical table is gone.
        orphan = await _pre_migration_dataset(
            test_db_session,
            created_by=admin_id,
            name="Registered Orphan",
            source_format=None,
            table_name=shared_name,
        )
        # A different tenant's UPLOAD owning the same table name. Outside the
        # backfill population, so the narrow filter did not see it at all.
        upload_claimant_record = Record(
            title="Uploaded Same Name",
            record_type="vector_dataset",
            visibility="private",
            record_status="published",
            created_by=admin_id,
        )
        test_db_session.add(upload_claimant_record)
        await test_db_session.flush()
        upload_claimant = Dataset(
            record_id=upload_claimant_record.id,
            table_name=shared_name,
            source_format="gpkg",
            source_filename="roads.gpkg",
            tenant_id=uuid.uuid4(),
        )
        test_db_session.add(upload_claimant)
        await test_db_session.flush()

        savepoint = await test_db_session.begin_nested()
        try:
            # Exactly ONE physical relation, owned by the upload.
            await test_db_session.execute(
                sa.text(f"CREATE TABLE data.{shared_name} (id integer)")
            )
            for statement in module.backfill_statements():
                await test_db_session.execute(statement)
            await test_db_session.run_sync(
                lambda sync_session: module.purge_credential_bearing_pointers(
                    sync_session.connection()
                )
            )
            row = (
                await test_db_session.execute(
                    sa.text(
                        "SELECT origin_uri, origin_ref FROM catalog.datasets "
                        "WHERE id = :id"
                    ).bindparams(sa.bindparam("id", value=orphan.id))
                )
            ).one()
            assert row.origin_uri is None, (
                "a same-named dataset of any origin must block resolution"
            )
            assert row.origin_ref is None
        finally:
            await savepoint.rollback()


# ---------------------------------------------------------------------------
# The binding follows the current bytes
# ---------------------------------------------------------------------------


_SWAP_METADATA = {
    "srid": 4326,
    "geometry_type": "POINT",
    "feature_count": 3,
    "extent_wkt": "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
    "column_info": [
        {"name": "name", "type": "character varying", "ordinal_position": 1},
    ],
}


async def _run_reupload_swap(
    session,
    dataset,
    *,
    admin_id,
    metadata: dict | None = None,
    staging_has_geometry: bool = True,
    staging_geometry_type: str = "Point",
    **kwargs,
) -> None:
    """Drive _apply_reupload_swap against a real staging table.

    ``metadata`` overrides the spatial default, for the callers that need the
    swap to install a measurement of a DIFFERENT modality than the one the
    dataset was created with (#1314).

    ``staging_has_geometry`` builds the staging relation WITHOUT geometry
    columns, which is what ingesting a CSV with no geometry produces. It is
    separate from ``metadata`` on purpose: the pair (measurement says
    non-spatial, relation still has a geom column) is exactly the empty-spatial
    reupload the demote must not act on.

    ``staging_geometry_type`` is what the geom column is DECLARED as, which is
    the evidence the sampled rows cannot supply (#1373). ``"Geometry"`` stages
    the untyped column that establishes only that the relation is spatial.
    """
    from unittest.mock import AsyncMock, patch

    from app.processing.ingest.tasks import _apply_reupload_swap

    staging_table = f"{dataset.table_name}_staging"
    geometry_columns = (
        f"geom geometry({staging_geometry_type}, 4326), "
        "geom_4326 geometry(Geometry, 4326), "
        if staging_has_geometry
        else ""
    )
    await session.execute(
        sa.text(
            f"CREATE TABLE data.{staging_table} ("
            "gid SERIAL PRIMARY KEY, "
            f"{geometry_columns}"
            "name TEXT)"
        )
    )
    with (
        patch(
            "app.processing.ingest.metadata.refresh_attribute_metadata",
            new_callable=AsyncMock,
        ) as mock_refresh,
        patch(
            "app.processing.ingest.metadata.compute_quality_score",
            new_callable=AsyncMock,
        ) as mock_quality,
    ):
        mock_refresh.return_value = None
        # A COMPLETE QualityDetail. These tests commit, and the row outlives
        # them on the shared per-worker database, so a partial dict here does
        # not just fail this test — it makes every later GET /datasets/ that
        # includes the row raise a 500 on response validation. Costed 9
        # failures across test_datasets.py before it was caught.
        mock_quality.return_value = {
            "overall": 90.0,
            "metadata_completeness": 90.0,
            "geometry_validity": 100.0,
            "attribute_completeness": 90.0,
            "crs_defined": 100.0,
        }
        await _apply_reupload_swap(
            session,
            dataset=dataset,
            staging_table=staging_table,
            metadata=_SWAP_METADATA if metadata is None else metadata,
            sample_values={"name": ["A"]},
            user_id=str(admin_id),
            original_srid=4326,
            **kwargs,
        )


class TestReuploadRestampsTheBinding:
    async def test_file_reupload_of_a_postgis_dataset_becomes_an_upload(
        self, test_db_session
    ) -> None:
        """The binding must describe where the CURRENT bytes came from.

        Without the restamp the API serves a computed origin of `upload`
        (source_format is now a file suffix) beside a stored ref still
        claiming `postgis`, and a later refresh would follow the stale
        pointer at a table these bytes no longer came from.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Reupload Was Postgis",
            # Private: these rows outlive the test on the shared
            # per-worker DB, so keep them out of public-list assertions.
            visibility="private",
            source_format=None,
        )
        set_postgis_origin(ds, ds.table_name, schema="data")
        ds.source_url = "https://descriptive.test/about-this-layer"
        stale = datetime(2020, 1, 1, tzinfo=timezone.utc)
        ds.last_refreshed_at = stale
        await test_db_session.commit()
        assert ds.origin_ref["kind"] == "postgis"

        await _run_reupload_swap(
            test_db_session,
            ds,
            admin_id=admin_id,
            source_filename="parcels.geojson",
            source_format="geojson",
            file_hash="sha256:abc123",
            origin_ref={"filename": "parcels.geojson", "file_hash": "sha256:abc123"},
        )
        await test_db_session.commit()
        await test_db_session.refresh(ds)

        assert ds.origin_ref == {
            "kind": "upload",
            "filename": "parcels.geojson",
            "file_hash": "sha256:abc123",
        }
        assert ds.origin_uri is None, "an upload has no remote pointer"
        assert classify_origin(ds.source_format) == "upload"
        # The user-editable prose field is NOT collateral damage.
        assert ds.source_url == "https://descriptive.test/about-this-layer"
        assert ds.last_refreshed_at is not None and ds.last_refreshed_at > stale

    async def test_service_reupload_stays_a_service_origin(
        self, test_db_session
    ) -> None:
        """Kind is derived, not hardcoded to upload.

        _apply_reupload_swap serves the service re-pull path too, so stamping
        `upload` unconditionally would flatten a service dataset's binding and
        drop the pointer a refresh needs.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Reupload Service",
            # Private: these rows outlive the test on the shared
            # per-worker DB, so keep them out of public-list assertions.
            visibility="private",
            source_format="wfs",
        )
        await test_db_session.commit()

        await _run_reupload_swap(
            test_db_session,
            ds,
            admin_id=admin_id,
            source_filename="parcels",
            source_format="wfs",
            source_url="https://gis.test/geoserver/wfs",
            origin_ref={
                "service_type": "wfs",
                "url": "https://gis.test/geoserver/wfs",
                "layer_id": None,
            },
        )
        await test_db_session.commit()
        await test_db_session.refresh(ds)

        assert ds.origin_ref == {
            "kind": "service",
            "service_type": "wfs",
            "url": "https://gis.test/geoserver/wfs",
        }
        assert ds.origin_uri == "https://gis.test/geoserver/wfs"

    async def test_reupload_ref_still_goes_through_the_allowlist(
        self, test_db_session
    ) -> None:
        """The reupload path is not a side door around the key allowlist."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await _create_dataset(
            test_db_session,
            created_by=admin_id,
            name="Reupload Allowlist",
            # Private: these rows outlive the test on the shared
            # per-worker DB, so keep them out of public-list assertions.
            visibility="private",
            source_format="geojson",
        )
        await test_db_session.commit()

        with pytest.raises(ValueError, match="rejects key"):
            await _run_reupload_swap(
                test_db_session,
                ds,
                admin_id=admin_id,
                source_filename="parcels.geojson",
                source_format="geojson",
                origin_ref={"filename": "parcels.geojson", "token": "leaked"},
            )
        await test_db_session.rollback()


class TestReuploadReconcilesDistributions:
    """fix(#1314): a reupload can change modality, and the rows must follow.

    Same gap as the registered-PostGIS refresh had, reached a different way:
    ``_apply_reupload_swap`` writes the new ``geometry_type`` onto the dataset
    and nothing re-derives the distribution rows generated at creation.
    """

    async def _pairs(self, session, record_id) -> set[tuple[str, str]]:
        rows = (
            await session.execute(
                sa.select(
                    RecordDistribution.distribution_type,
                    RecordDistribution.format,
                ).where(RecordDistribution.record_id == record_id)
            )
        ).all()
        return {(row[0], row[1]) for row in rows}

    async def _seed(self, session, *, admin_id, geometry_type):
        ds = await _create_dataset(
            session,
            created_by=admin_id,
            name="Reupload Distributions",
            # Private: these rows outlive the test on the shared
            # per-worker DB, so keep them out of public-list assertions.
            visibility="private",
            source_format="geojson",
            geometry_type=geometry_type,
        )
        await generate_distributions(
            session, ds.id, ds.record_id, ds.table_name, geometry_type=geometry_type
        )
        await session.commit()
        return ds

    async def test_a_reupload_that_removes_geometry_drops_the_spatial_rows(
        self, test_db_session
    ) -> None:
        """A CSV over a shapefile leaves a relation with nothing to tile."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await self._seed(test_db_session, admin_id=admin_id, geometry_type="POINT")
        record_id = ds.record_id
        mine = await create_distribution(
            test_db_session,
            record_id,
            distribution_type="download",
            format="gpkg",
            url="https://example.org/mine.gpkg",
        )
        mine_id = mine.id
        await test_db_session.commit()

        await _run_reupload_swap(
            test_db_session,
            ds,
            admin_id=admin_id,
            metadata={**_SWAP_METADATA, "geometry_type": None, "extent_wkt": None},
            # A CSV with no geometry stages a relation with no geom column,
            # which is what makes this a demote rather than an empty spatial
            # reupload.
            staging_has_geometry=False,
            source_filename="rows.csv",
            source_format="csv",
            origin_ref={"filename": "rows.csv"},
        )
        await test_db_session.commit()

        assert await self._pairs(test_db_session, record_id) == {
            ("download", "csv"),
            ("ogc_features", "geojson"),
            # The user's own row, on a pair the demote otherwise removes.
            ("download", "gpkg"),
        }
        assert (
            await test_db_session.scalar(
                sa.select(RecordDistribution.id).where(RecordDistribution.id == mine_id)
            )
            is not None
        )

    async def test_a_reupload_that_adds_geometry_advertises_the_spatial_rows(
        self, test_db_session
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await self._seed(test_db_session, admin_id=admin_id, geometry_type=None)
        record_id = ds.record_id

        await _run_reupload_swap(
            test_db_session,
            ds,
            admin_id=admin_id,
            source_filename="points.geojson",
            source_format="geojson",
            origin_ref={"filename": "points.geojson"},
        )
        await test_db_session.commit()

        assert await self._pairs(test_db_session, record_id) == {
            ("download", "gpkg"),
            ("download", "geojson"),
            ("download", "shp"),
            ("download", "parquet"),
            ("download", "csv"),
            ("download", "fgb"),
            ("download", "pmtiles"),
            ("ogc_features", "geojson"),
            ("vector_tiles", "pbf"),
        }

    async def test_an_empty_spatial_reupload_is_not_a_demote(
        self, test_db_session
    ) -> None:
        """fix(#1314 review round 2): a measurement of zero rows is not evidence.

        ``extract_metadata`` derives the geometry type by sampling a row, so a
        spatial file carrying no features reports None even though the relation
        it stages still has its geometry column. Treating that as a demote
        would delete the spatial rows of a dataset that is still spatial —
        the destructive direction, on the weakest possible evidence.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await self._seed(test_db_session, admin_id=admin_id, geometry_type="POINT")
        record_id = ds.record_id
        before = await self._pairs(test_db_session, record_id)

        await _run_reupload_swap(
            test_db_session,
            ds,
            admin_id=admin_id,
            # No sampled geometry (no rows), but the staged relation keeps its
            # geom column — the pair that makes this an empty reupload rather
            # than a de-spatialization.
            metadata={
                **_SWAP_METADATA,
                "geometry_type": None,
                "extent_wkt": None,
                "feature_count": 0,
            },
            source_filename="empty.geojson",
            source_format="geojson",
            origin_ref={"filename": "empty.geojson"},
        )
        await test_db_session.commit()

        assert await self._pairs(test_db_session, record_id) == before


class TestReuploadDerivesTheEffectiveModality:
    """fix(#1373) / fix(#1361): the swap writes what the RELATION is.

    ``extract_metadata`` derives the geometry type by sampling a row, so an
    empty spatial file measures None against a relation whose geom column is
    right there. The registered-PostGIS refresh resolved that first (#1313);
    these pin that the reupload path resolves it the same way, and that
    ``record_type`` — which ``build_assets`` branches on live — follows the
    resolved value rather than the sampled one.
    """

    async def _seed(self, session, *, admin_id, geometry_type, record_type):
        ds = await _create_dataset(
            session,
            created_by=admin_id,
            name="Reupload Modality",
            # Private: these rows outlive the test on the shared per-worker
            # DB, so keep them out of public-list assertions.
            visibility="private",
            source_format="geojson",
            geometry_type=geometry_type,
        )
        ds.record.record_type = record_type
        await session.commit()
        return ds

    async def _reload(self, session, dataset_id) -> Dataset:
        """Read the pair back past the identity map, with the record joined."""
        session.expire_all()
        return (
            await session.execute(
                sa.select(Dataset)
                .options(joinedload(Dataset.record))
                .where(Dataset.id == dataset_id)
            )
        ).scalar_one()

    async def test_an_empty_spatial_reupload_keeps_the_dataset_spatial(
        self, test_db_session
    ) -> None:
        """fix(#1373): zero rows is not evidence that the column is gone.

        Writing the sampled None reclassified a still-spatial dataset as
        tabular, and the consequences are not cosmetic: feature writes are
        refused, so the API could never repopulate the table it just emptied,
        and the builder drops its layers as unsupported.
        """
        from app.modules.catalog.features.router import _require_feature_table

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await self._seed(
            test_db_session,
            admin_id=admin_id,
            geometry_type="POINT",
            record_type="vector_dataset",
        )

        await _run_reupload_swap(
            test_db_session,
            ds,
            admin_id=admin_id,
            metadata={
                **_SWAP_METADATA,
                "geometry_type": None,
                "extent_wkt": None,
                "feature_count": 0,
            },
            source_filename="empty.geojson",
            source_format="geojson",
            origin_ref={"filename": "empty.geojson"},
        )
        await test_db_session.commit()

        reloaded = await self._reload(test_db_session, ds.id)
        assert reloaded.geometry_type == "POINT", "the declared column type"
        assert reloaded.record.record_type == "vector_dataset"
        # The lockout the issue is actually about, asserted against the guard
        # itself rather than a restatement of it.
        _require_feature_table(reloaded)

    async def test_an_empty_generic_column_keeps_what_was_already_known(
        self, test_db_session
    ) -> None:
        """The branch where neither the rows nor the column say anything.

        An untyped ``geometry`` column carrying no rows establishes only that
        the relation is spatial, so the catalog keeps the type it last
        measured — which is the PRE-swap value, and reading it after the write
        would silently resolve to None.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await self._seed(
            test_db_session,
            admin_id=admin_id,
            geometry_type="MULTIPOLYGON",
            record_type="vector_dataset",
        )

        await _run_reupload_swap(
            test_db_session,
            ds,
            admin_id=admin_id,
            metadata={
                **_SWAP_METADATA,
                "geometry_type": None,
                "extent_wkt": None,
                "feature_count": 0,
            },
            staging_geometry_type="Geometry",
            source_filename="empty.gpkg",
            source_format="gpkg",
            origin_ref={"filename": "empty.gpkg"},
        )
        await test_db_session.commit()

        reloaded = await self._reload(test_db_session, ds.id)
        assert reloaded.geometry_type == "MULTIPOLYGON"
        assert reloaded.record.record_type == "vector_dataset"

    async def test_a_non_spatial_reupload_demotes_the_record_type(
        self, test_db_session
    ) -> None:
        """fix(#1361): a CSV over a shapefile leaves nothing to tile.

        Without the re-derivation the record stays a ``vector_dataset``, and
        ``build_assets`` goes on advertising vector-tile and OGC-Features
        hrefs against a relation with no geometry column.
        """
        from app.modules.catalog.search.service_records import build_assets

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await self._seed(
            test_db_session,
            admin_id=admin_id,
            geometry_type="POINT",
            record_type="vector_dataset",
        )
        assert "vector_tiles" in build_assets(ds, "https://api.test")

        await _run_reupload_swap(
            test_db_session,
            ds,
            admin_id=admin_id,
            metadata={**_SWAP_METADATA, "geometry_type": None, "extent_wkt": None},
            staging_has_geometry=False,
            source_filename="rows.csv",
            source_format="csv",
            origin_ref={"filename": "rows.csv"},
        )
        await test_db_session.commit()

        reloaded = await self._reload(test_db_session, ds.id)
        assert reloaded.geometry_type is None
        assert reloaded.record.record_type == "table"
        assets = build_assets(reloaded, "https://api.test")
        assert "vector_tiles" not in assets
        assert "ogc_features" not in assets

    async def test_a_reupload_that_adds_geometry_promotes_the_record_type(
        self, test_db_session
    ) -> None:
        """The inverse: a tabular dataset that gains a geometry column."""
        from app.modules.catalog.search.service_records import build_assets

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await self._seed(
            test_db_session,
            admin_id=admin_id,
            geometry_type=None,
            record_type="table",
        )

        await _run_reupload_swap(
            test_db_session,
            ds,
            admin_id=admin_id,
            source_filename="points.geojson",
            source_format="geojson",
            origin_ref={"filename": "points.geojson"},
        )
        await test_db_session.commit()

        reloaded = await self._reload(test_db_session, ds.id)
        assert reloaded.geometry_type == "POINT"
        assert reloaded.record.record_type == "vector_dataset"
        assert "vector_tiles" in build_assets(reloaded, "https://api.test")

    async def test_an_empty_spatial_file_over_a_table_promotes_it_too(
        self, test_db_session
    ) -> None:
        """Where #1373 deliberately widens what #1314 let fall through.

        #1314 left this case alone because nothing measured a type, so
        ``geometry_type`` stayed None either way. It no longer does — a
        specific declared column type is now written — so the record type and
        the distribution rows have to follow it rather than describe a
        dataset the catalog no longer claims to hold.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await self._seed(
            test_db_session,
            admin_id=admin_id,
            geometry_type=None,
            record_type="table",
        )
        record_id = ds.record_id
        await generate_distributions(
            test_db_session, ds.id, record_id, ds.table_name, geometry_type=None
        )
        await test_db_session.commit()

        await _run_reupload_swap(
            test_db_session,
            ds,
            admin_id=admin_id,
            metadata={
                **_SWAP_METADATA,
                "geometry_type": None,
                "extent_wkt": None,
                "feature_count": 0,
            },
            source_filename="empty.geojson",
            source_format="geojson",
            origin_ref={"filename": "empty.geojson"},
        )
        await test_db_session.commit()

        reloaded = await self._reload(test_db_session, ds.id)
        assert reloaded.geometry_type == "POINT"
        assert reloaded.record.record_type == "vector_dataset"
        pairs = {
            (row[0], row[1])
            for row in (
                await test_db_session.execute(
                    sa.select(
                        RecordDistribution.distribution_type,
                        RecordDistribution.format,
                    ).where(RecordDistribution.record_id == record_id)
                )
            ).all()
        }
        assert ("vector_tiles", "pbf") in pairs

    @pytest.mark.parametrize("record_type", ["raster_dataset", "vrt_dataset"])
    async def test_the_raster_family_is_never_re_derived(
        self, test_db_session, record_type: str
    ) -> None:
        """Only the two record types the create path derives are derivable.

        A raster or VRT record carries its own modality, and re-deriving it
        from a geometry column it never had would reclassify it. Pinned at the
        derivation rather than through the API, which refuses the combination
        a layer earlier (``_assert_compatible_record_type`` in
        ``router_reupload``, covered by ``test_reupload_record_type_guard``):
        the guard here is what keeps a future caller of this swap — the raster
        tails already build their own version rows beside it — from inheriting
        a derivation that has no business running on them.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await self._seed(
            test_db_session,
            admin_id=admin_id,
            geometry_type="POINT",
            record_type=record_type,
        )

        await _run_reupload_swap(
            test_db_session,
            ds,
            admin_id=admin_id,
            metadata={**_SWAP_METADATA, "geometry_type": None, "extent_wkt": None},
            staging_has_geometry=False,
            source_filename="rows.csv",
            source_format="csv",
            origin_ref={"filename": "rows.csv"},
        )
        await test_db_session.commit()

        reloaded = await self._reload(test_db_session, ds.id)
        assert reloaded.record.record_type == record_type

    async def test_an_empty_generic_column_over_a_table_is_still_spatial(
        self, test_db_session
    ) -> None:
        """fix(#1382 review r1): the case where nothing has ever been measured.

        A generic column with no rows and no stored type used to resolve to
        None, which classified a relation that plainly has a geometry column
        as tabular and left feature writes refused — so the dataset could
        never be given the first row that would have named its type. The
        generic sentinel is what this codebase spells that state as, and it
        survives write validation (#430 BA-32) and the builder (#430 r23).
        """
        from app.modules.catalog.features.router import _require_feature_table

        admin_id = await get_user_id(test_db_session, "admin")
        ds = await self._seed(
            test_db_session,
            admin_id=admin_id,
            geometry_type=None,
            record_type="table",
        )

        await _run_reupload_swap(
            test_db_session,
            ds,
            admin_id=admin_id,
            metadata={
                **_SWAP_METADATA,
                "geometry_type": None,
                "extent_wkt": None,
                "feature_count": 0,
            },
            staging_geometry_type="Geometry",
            source_filename="empty-mixed.gpkg",
            source_format="gpkg",
            origin_ref={"filename": "empty-mixed.gpkg"},
        )
        await test_db_session.commit()

        reloaded = await self._reload(test_db_session, ds.id)
        assert reloaded.geometry_type == "GEOMETRY"
        assert reloaded.record.record_type == "vector_dataset"
        _require_feature_table(reloaded)

    @pytest.mark.parametrize(
        ("measured", "declared", "stored", "expected"),
        [
            # A sampled row wins over everything else.
            ("POINT", "GEOMETRY", "MULTIPOLYGON", "POINT"),
            ("POINT", None, None, "POINT"),
            # No rows, but the column says what it accepts.
            (None, "MULTIPOLYGON", "POINT", "MULTIPOLYGON"),
            # Generic column, no rows: keep the last measurement...
            (None, "GEOMETRY", "POINT", "POINT"),
            # ...or say "spatial, subtype unknown" when there is none.
            (None, "GEOMETRY", None, "GEOMETRY"),
            # No geom column at all is the only genuinely non-spatial case.
            (None, None, "POINT", None),
            (None, None, None, None),
        ],
    )
    def test_the_precedence_in_full(
        self,
        measured: str | None,
        declared: str | None,
        stored: str | None,
        expected: str | None,
    ) -> None:
        """The whole truth table, since both paths now resolve through it."""
        from app.processing.ingest.tasks_common import _effective_geometry_type

        assert (
            _effective_geometry_type(
                measured=measured, declared=declared, stored=stored
            )
            == expected
        )

    def test_both_paths_share_one_derivation(self) -> None:
        """The acceptance criterion of both issues, pinned by identity.

        A second spelling of this precedence is how the reupload swap and the
        registered-PostGIS refresh end up describing the same dataset
        differently. Identity rather than a file path, so moving the helpers
        again is a refactor rather than a test failure.
        """
        from app.processing.ingest import tasks_common, tasks_postgis_refresh

        assert (
            tasks_postgis_refresh._effective_geometry_type
            is tasks_common._effective_geometry_type
        )
        assert (
            tasks_postgis_refresh._declared_geometry_type
            is tasks_common._declared_geometry_type
        )
        assert (
            tasks_postgis_refresh._derived_record_type
            is tasks_common._derived_record_type
        )


class TestReuploadRetiresTheGeometryAttributeRow:
    """fix(#1380): the attribute row follows the relation.

    ``refresh_attribute_metadata`` touches the synthetic ``geom`` row only
    when it is handed a non-null geometry type, and excludes ``geom`` from its
    removed-column sweep by name — so a CSV reupload over a shapefile left the
    row at ``is_current = true`` and the attributes API went on advertising a
    geometry field the relation no longer has. The registered-PostGIS refresh
    retired it from #1313 review round 7; this path did not.
    """

    async def _seed(self, session, *, admin_id, geometry_type, record_type):
        ds = await _create_dataset(
            session,
            created_by=admin_id,
            name="Reupload Geom Attribute",
            # Private: these rows outlive the test on the shared per-worker
            # DB, so keep them out of public-list assertions.
            visibility="private",
            source_format="geojson",
            geometry_type=geometry_type,
        )
        ds.record.record_type = record_type
        # The synthetic row as `refresh_attribute_metadata` writes it, seeded
        # rather than measured: the swap harness mocks that helper out, so
        # without this the assertions below would pass against a dataset that
        # simply never had a geometry row.
        await session.execute(
            sa.text(
                "INSERT INTO catalog.attribute_metadata "
                "(dataset_id, field_name, title, data_type, "
                "semantic_role, domain_type) "
                "VALUES (:did, 'geom', 'Geometry', :dtype, "
                "'geometry', 'geometry')"
            ),
            {"did": ds.id, "dtype": geometry_type or "geometry"},
        )
        await session.commit()
        assert await self._geom_is_current(session, ds.id) is True
        return ds

    async def _geom_is_current(self, session, dataset_id) -> bool | None:
        """Read the stored flag straight from the row, past the identity map."""
        return await session.scalar(
            sa.text(
                "SELECT is_current FROM catalog.attribute_metadata "
                "WHERE dataset_id = :did AND field_name = 'geom'"
            ),
            {"did": dataset_id},
        )

    async def test_a_non_spatial_reupload_retires_the_row(
        self, test_db_session
    ) -> None:
        """A CSV over a shapefile: the geometry field is gone, so say so."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await self._seed(
            test_db_session,
            admin_id=admin_id,
            geometry_type="POINT",
            record_type="vector_dataset",
        )

        await _run_reupload_swap(
            test_db_session,
            ds,
            admin_id=admin_id,
            metadata={**_SWAP_METADATA, "geometry_type": None, "extent_wkt": None},
            staging_has_geometry=False,
            source_filename="rows.csv",
            source_format="csv",
            origin_ref={"filename": "rows.csv"},
        )
        await test_db_session.commit()

        assert await self._geom_is_current(test_db_session, ds.id) is False

    async def test_a_spatial_reupload_leaves_the_row_current(
        self, test_db_session
    ) -> None:
        """The dataset still has geometry, so the row still describes it."""
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await self._seed(
            test_db_session,
            admin_id=admin_id,
            geometry_type="POINT",
            record_type="vector_dataset",
        )

        await _run_reupload_swap(
            test_db_session,
            ds,
            admin_id=admin_id,
            source_filename="points.geojson",
            source_format="geojson",
            origin_ref={"filename": "points.geojson"},
        )
        await test_db_session.commit()

        assert await self._geom_is_current(test_db_session, ds.id) is True

    async def test_an_empty_spatial_reupload_leaves_the_row_current(
        self, test_db_session
    ) -> None:
        """The trap #1373 named, on the row this one retires.

        An empty spatial file measures None against a relation whose geom
        column is right there, so retiring on the SAMPLED type would strike
        the attribute row of a dataset that is still spatial — and nothing
        would restore it, since ``refresh_attribute_metadata`` only ever sets
        ``is_current`` back to True for a field it is handed. The retirement
        reads the EFFECTIVE type for exactly that reason.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await self._seed(
            test_db_session,
            admin_id=admin_id,
            geometry_type="POINT",
            record_type="vector_dataset",
        )

        await _run_reupload_swap(
            test_db_session,
            ds,
            admin_id=admin_id,
            metadata={
                **_SWAP_METADATA,
                "geometry_type": None,
                "extent_wkt": None,
                "feature_count": 0,
            },
            source_filename="empty.geojson",
            source_format="geojson",
            origin_ref={"filename": "empty.geojson"},
        )
        await test_db_session.commit()

        assert await self._geom_is_current(test_db_session, ds.id) is True

    async def test_a_reupload_that_gains_geometry_leaves_the_row_current(
        self, test_db_session
    ) -> None:
        """The promote, where the stored type is the stale half.

        A tabular dataset reuploaded from a spatial file: the swap resolves a
        geometry type where the catalog held None, so nothing may be retired
        on the strength of the value the dataset carried on the way in.
        """
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await self._seed(
            test_db_session,
            admin_id=admin_id,
            geometry_type=None,
            record_type="table",
        )

        await _run_reupload_swap(
            test_db_session,
            ds,
            admin_id=admin_id,
            source_filename="points.geojson",
            source_format="geojson",
            origin_ref={"filename": "points.geojson"},
        )
        await test_db_session.commit()

        assert await self._geom_is_current(test_db_session, ds.id) is True

    def test_both_paths_share_one_retirement(self) -> None:
        """#1380's acceptance criterion, pinned the way #1382 pinned its own.

        A second copy of this UPDATE is how the two paths came to disagree
        about the same row in the first place. Identity rather than a file
        path, so moving the helper again is a refactor rather than a failure.
        """
        from app.processing.ingest import tasks_common, tasks_postgis_refresh

        assert (
            tasks_postgis_refresh._retire_geometry_attribute_row
            is tasks_common._retire_geometry_attribute_row
        )


class TestFirstIngestStampsLastRefreshed:
    async def test_created_dataset_carries_its_creation_instant(
        self, test_db_session
    ) -> None:
        """Runtime and backfill must agree on the floor.

        Migration 0036 gives a pre-existing dataset records.created_at when it
        has no version history; a dataset created after the migration must
        land on effectively the same instant rather than reporting null
        forever.

        Compared with a tolerance rather than for equality: the stamp is a
        Python datetime while records.created_at comes from the database's own
        server_default, so the two clocks agree to well within a second but
        not to the microsecond. A SQL func.now() would make them identical and
        is deliberately not used — it leaves the attribute expired after
        flush, so dataset_to_response's read of it lazy-loads against a closed
        session (9 suite failures before that was tracked down).
        """
        from app.modules.catalog.datasets.domain.service import create_dataset

        admin_id = await get_user_id(test_db_session, "admin")
        dataset = await create_dataset(
            test_db_session,
            f"lr_{uuid.uuid4().hex[:12]}",
            "Last Refreshed At Creation",
            admin_id,
            source_format="geojson",
            source_filename="x.geojson",
            geometry_type="Point",
            srid=4326,
        )
        # Captured pre-commit: attributes expire on commit, and a bare attribute
        # read would then lazy-load outside the greenlet context.
        dataset_id = dataset.id
        await test_db_session.commit()

        row = (
            await test_db_session.execute(
                sa.text(
                    "SELECT d.last_refreshed_at, r.created_at "
                    "FROM catalog.datasets d "
                    "JOIN catalog.records r ON r.id = d.record_id "
                    "WHERE d.id = :id"
                ).bindparams(sa.bindparam("id", value=dataset_id))
            )
        ).one()

        assert row.last_refreshed_at is not None
        assert abs(row.last_refreshed_at - row.created_at) < timedelta(seconds=30)

    async def test_creation_endpoint_serializes_without_a_lazy_load(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
    ) -> None:
        """The freshly-created row must serialize on the spot.

        POST /datasets/create/ builds a DatasetResponse from the instance it
        just made. Stamping last_refreshed_at with a SQL expression leaves the
        attribute expired, so dataset_to_response's read of it fires a lazy
        SELECT and the endpoint 500s. That regression showed up only in
        unrelated files (test_audit, test_features_crud), so it is pinned here
        where the field lives.
        """
        resp = await client.post(
            "/datasets/create/",
            json={
                "title": f"Lazy Load Guard {uuid.uuid4().hex[:8]}",
                "columns": [{"name": "label", "type": "text"}],
            },
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["last_refreshed_at"] is not None
        assert body["origin"] == "created"
        assert body["source_health"] == UNKNOWN


# ---------------------------------------------------------------------------
# The service binding names the layer, per service type
# ---------------------------------------------------------------------------


class TestServiceLayerIdentity:
    """`layer_id` holds whichever field the service actually addresses by.

    `build_gdal_source` (catalog/sources/preview.py) is the authority and it
    makes the two mutually exclusive: its ArcGIS branch requires the numeric
    layer id and returns an EMPTY layer name, while its WFS and OGC API
    branches pass the layer name through and never look at layer_id. So one
    key can carry the identity for all three without ambiguity, which is why
    the allowlist is not widened with a second name field (#1218 review r3).
    """

    @pytest.mark.parametrize(
        ("service_type", "gdal_prefix"),
        [("wfs", "WFS"), ("ogcapi_features", "OGC API")],
    )
    def test_name_addressed_services_carry_the_layer_name(
        self, service_type: str, gdal_prefix: str
    ) -> None:
        """Pin the premise itself: these drivers address by NAME, not id."""
        from app.modules.catalog.sources.preview import build_gdal_source

        _source, layer = build_gdal_source(
            gdal_prefix, "https://gis.test/svc", "topp:parcels", layer_id=None
        )
        assert layer == "topp:parcels", "driver addresses the layer by name"

        ref = build_origin_ref(
            "service",
            service_type=service_type,
            url="https://gis.test/svc",
            layer_id="topp:parcels",
        )
        assert ref == {
            "kind": "service",
            "service_type": service_type,
            "url": "https://gis.test/svc",
            "layer_id": "topp:parcels",
        }

    def test_arcgis_addresses_by_numeric_id_and_ignores_the_name(self) -> None:
        """The other half of the premise, which is why one key suffices."""
        from app.modules.catalog.sources.preview import build_gdal_source

        source, layer = build_gdal_source(
            "ArcGIS FeatureServer",
            "https://gis.test/rest/services/Parcels/FeatureServer",
            "a human layer name",
            layer_id=7,
        )
        assert layer == "", "the layer name is discarded for ArcGIS"
        assert "/7/query?" in source, "the numeric id addresses the layer"

        with pytest.raises(ValueError, match="requires a layer ID"):
            build_gdal_source("ArcGIS FeatureServer", "https://x", "name", None)

    @pytest.mark.parametrize("service_type", ["wfs", "ogcapi_features"])
    def test_write_sites_record_the_layer_name_for_name_addressed_services(
        self, service_type: str
    ) -> None:
        """The rule both ingest write sites actually call.

        Covers the write-site half: previously they stored only layer_id,
        which is None for these services, so the ref named no layer at all and
        a refresh had nothing to fetch once the ingest job aged out.
        """
        assert (
            service_layer_identity(
                service_type, layer_id=None, layer_name="topp:parcels"
            )
            == "topp:parcels"
        )

    def test_write_sites_record_the_numeric_id_for_arcgis(self) -> None:
        """ArcGIS keeps the id and discards the name, matching the driver."""
        assert (
            service_layer_identity(
                "arcgis_featureserver", layer_id=7, layer_name="a display name"
            )
            == "7"
        )
        assert (
            service_layer_identity(
                "arcgis_featureserver", layer_id=None, layer_name="a display name"
            )
            is None
        ), "no id means no identity; a display name is not a substitute"

    def test_a_second_name_key_is_still_refused(self) -> None:
        """Unification means one key; the allowlist must not have grown."""
        # fix(#1746): `auth_required` joined the set. It is not a second layer
        # key — it says the last successful pull needed a service token — so
        # the "one key addresses the layer" rule this test guards is intact.
        assert ORIGIN_REF_KEYS["service"] == frozenset(
            {"service_type", "url", "layer_id", "auth_required"}
        )
        for key in ("layer_name", "source_layer", "typename", "collection_id"):
            with pytest.raises(ValueError, match="rejects key"):
                build_origin_ref("service", **{key: "topp:parcels"})

    def test_auth_required_is_true_or_absent_never_false(self) -> None:
        """fix(#1746): a token-less pull stores the pre-marker ref shape."""
        ref = build_origin_ref(
            "service",
            service_type="arcgis_featureserver",
            url="https://example.test/FeatureServer",
            layer_id="3",
            auth_required=None,
        )
        assert ref is not None
        assert "auth_required" not in ref
        assert not service_auth_required(ref)

        marked = build_origin_ref(
            "service",
            service_type="arcgis_featureserver",
            url="https://example.test/FeatureServer",
            layer_id="3",
            auth_required=True,
        )
        assert marked is not None
        assert marked["auth_required"] is True
        assert service_auth_required(marked)

    def test_service_auth_required_reads_only_a_real_true(self) -> None:
        """A stored 1 or "yes" is not a claim worth refusing a request on."""
        assert not service_auth_required(None)
        assert not service_auth_required("auth_required")
        assert not service_auth_required({})
        assert not service_auth_required({"auth_required": 1})
        assert not service_auth_required({"auth_required": "yes"})
        assert not service_auth_required({"auth_required": False})

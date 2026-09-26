"""fix(#1778): a single-feature edit must not seq-scan the whole layer.

`_refresh_count_and_extent` runs one unqualified COUNT(*) + ST_Extent over the
entire table, inside the request transaction, on every insert, replace, delete
and geometry-bearing patch. A dataset wider than 180 degrees pays a second scan
over `ST_ShiftLongitude(geom_4326)`, and a created dataset a third
`SELECT DISTINCT GeometryType(...)`. There is no bulk feature endpoint, so a
client digitizing 200 points issued 200 requests and paid it 200 times.

When the caller can say how many rows the write added or removed and where the
geometry it touched sits, and every touched envelope is strictly inside the
stored extent, the extent provably did not change and no aggregate runs.

Requires the Docker test database.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text, update

from app.modules.catalog.features import service as features_service
from app.modules.catalog.datasets.domain.models import Dataset, Record

from tests.factories import get_user_id

pytestmark = pytest.mark.anyio

# Extent of the seeded rows: (-74.00, 40.70) .. (-73.90, 40.80).
SEED_POINTS = [(-74.00, 40.70), (-73.90, 40.80), (-73.95, 40.75)]
INSIDE = {"type": "Point", "coordinates": [-73.96, 40.74]}
OUTSIDE = {"type": "Point", "coordinates": [-73.80, 40.90]}
INSIDE_POLYGON = {
    "type": "Polygon",
    "coordinates": [
        [
            [-73.96, 40.74],
            [-73.95, 40.74],
            [-73.95, 40.75],
            [-73.96, 40.74],
        ]
    ],
}


async def _create_sketch_dataset(
    session, *, created_by: uuid.UUID, source_format: str = "geojson"
) -> Dataset:
    table_name = f"test_im_{uuid.uuid4().hex[:8]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table_name} ("
            "gid SERIAL PRIMARY KEY, "
            "geom geometry(Geometry, 4326), "
            "geom_4326 geometry(Geometry, 4326), "
            "name TEXT)"
        )
    )
    await session.execute(text(f"GRANT SELECT ON data.{table_name} TO geolens_reader"))
    for lng, lat in SEED_POINTS:
        await session.execute(
            text(
                f"INSERT INTO data.{table_name} (geom, geom_4326, name) VALUES ("
                "ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), "
                "ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), 'seed')"
            ).bindparams(lng=lng, lat=lat)
        )

    record = Record(
        title=f"Incremental metadata {table_name}",
        summary="Sketch layer",
        theme_category=["test"],
        visibility="private",
        record_status="published",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="GEOMETRY" if source_format == "created" else "POINT",
        feature_count=0,
        column_info=[{"name": "name", "type": "text"}],
        source_format=source_format,
    )
    session.add(dataset)
    await session.flush()
    # Seed feature_count, spatial_extent and geometry_type the honest way.
    await features_service.refresh_dataset_metadata(session, dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


@pytest.fixture
async def sketch_dataset(client: AsyncClient, test_db_session):
    """An ordinary ingested layer: its display geometry_type never re-derives."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_sketch_dataset(test_db_session, created_by=admin_id)
    yield dataset
    await test_db_session.execute(
        text(f"DROP TABLE IF EXISTS data.{dataset.table_name}")
    )
    await test_db_session.commit()


@pytest.fixture
async def created_dataset(client: AsyncClient, test_db_session):
    """A created layer on a generic geometry column, where the type re-derives."""
    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await _create_sketch_dataset(
        test_db_session, created_by=admin_id, source_format="created"
    )
    yield dataset
    await test_db_session.execute(
        text(f"DROP TABLE IF EXISTS data.{dataset.table_name}")
    )
    await test_db_session.commit()


@pytest.fixture
def aggregate_calls(monkeypatch):
    """Record every full-table COUNT(*) + ST_Extent the request runs."""
    calls: list[str] = []
    original = features_service._refresh_count_and_extent

    async def _spy(session, table_name):
        calls.append(table_name)
        return await original(session, table_name)

    monkeypatch.setattr(features_service, "_refresh_count_and_extent", _spy)
    return calls


async def _state(session, dataset: Dataset) -> tuple[int, str | None]:
    row = (
        await session.execute(
            select(Dataset.feature_count, func.ST_AsText(Record.spatial_extent))
            .join(Record, Record.id == Dataset.record_id)
            .where(Dataset.id == dataset.id)
        )
    ).one()
    return int(row[0]), row[1]


async def test_an_insert_inside_the_extent_runs_no_aggregate(
    client: AsyncClient,
    sketch_dataset: Dataset,
    admin_auth_header,
    test_db_session,
    aggregate_calls,
):
    before_count, before_extent = await _state(test_db_session, sketch_dataset)

    resp = await client.post(
        f"/datasets/{sketch_dataset.id}/features/",
        json={"geometry": INSIDE, "properties": {"name": "inside"}},
        headers=admin_auth_header,
    )

    assert resp.status_code == 201, resp.text
    assert aggregate_calls == []
    after_count, after_extent = await _state(test_db_session, sketch_dataset)
    assert after_count == before_count + 1
    assert after_extent == before_extent


async def test_an_insert_outside_the_extent_still_recomputes(
    client: AsyncClient,
    sketch_dataset: Dataset,
    admin_auth_header,
    test_db_session,
    aggregate_calls,
):
    _before_count, before_extent = await _state(test_db_session, sketch_dataset)

    resp = await client.post(
        f"/datasets/{sketch_dataset.id}/features/",
        json={"geometry": OUTSIDE, "properties": {"name": "outside"}},
        headers=admin_auth_header,
    )

    assert resp.status_code == 201, resp.text
    assert aggregate_calls == [sketch_dataset.table_name]
    _after_count, after_extent = await _state(test_db_session, sketch_dataset)
    assert after_extent != before_extent


async def test_an_insert_that_widens_the_geometry_type_recomputes(
    client: AsyncClient,
    created_dataset: Dataset,
    admin_auth_header,
    test_db_session,
    aggregate_calls,
):
    """A created generic layer's display type can change; only a scan can say."""
    resp = await client.post(
        f"/datasets/{created_dataset.id}/features/",
        json={"geometry": INSIDE_POLYGON, "properties": {"name": "poly"}},
        headers=admin_auth_header,
    )

    assert resp.status_code == 201, resp.text
    assert aggregate_calls == [created_dataset.table_name]
    row = (
        await test_db_session.execute(
            select(Dataset.geometry_type).where(Dataset.id == created_dataset.id)
        )
    ).scalar_one()
    assert row == "GEOMETRY"


async def test_an_insert_of_the_same_type_into_a_created_layer_runs_no_aggregate(
    client: AsyncClient,
    created_dataset: Dataset,
    admin_auth_header,
    test_db_session,
    aggregate_calls,
):
    """The merge answers what the DISTINCT scan would have, without the scan."""
    before_count, before_extent = await _state(test_db_session, created_dataset)

    resp = await client.post(
        f"/datasets/{created_dataset.id}/features/",
        json={"geometry": INSIDE, "properties": {"name": "inside"}},
        headers=admin_auth_header,
    )

    assert resp.status_code == 201, resp.text
    assert aggregate_calls == []
    after_count, after_extent = await _state(test_db_session, created_dataset)
    assert after_count == before_count + 1
    assert after_extent == before_extent


async def test_a_delete_from_a_created_layer_still_recomputes(
    client: AsyncClient,
    created_dataset: Dataset,
    admin_auth_header,
    test_db_session,
    aggregate_calls,
):
    """A removed row can NARROW the derived display type, and only a scan sees that.

    The deliberate limit of the fast path: on a created generic layer it covers
    inserts only.
    """
    gid = (
        await test_db_session.execute(
            text(
                f"SELECT gid FROM data.{created_dataset.table_name} "
                "WHERE ST_X(geom_4326) = -73.95"
            )
        )
    ).scalar_one()

    resp = await client.delete(
        f"/datasets/{created_dataset.id}/features/{gid}", headers=admin_auth_header
    )

    assert resp.status_code == 204, resp.text
    assert aggregate_calls == [created_dataset.table_name]


async def test_deleting_an_interior_row_runs_no_aggregate(
    client: AsyncClient,
    sketch_dataset: Dataset,
    admin_auth_header,
    test_db_session,
    aggregate_calls,
):
    """The interior seed point defines no side of the extent."""
    gid = (
        await test_db_session.execute(
            text(
                f"SELECT gid FROM data.{sketch_dataset.table_name} "
                "WHERE ST_X(geom_4326) = -73.95"
            )
        )
    ).scalar_one()
    before_count, before_extent = await _state(test_db_session, sketch_dataset)

    resp = await client.delete(
        f"/datasets/{sketch_dataset.id}/features/{gid}", headers=admin_auth_header
    )

    assert resp.status_code == 204, resp.text
    assert aggregate_calls == []
    after_count, after_extent = await _state(test_db_session, sketch_dataset)
    assert after_count == before_count - 1
    assert after_extent == before_extent


async def test_deleting_a_corner_row_shrinks_the_extent(
    client: AsyncClient,
    sketch_dataset: Dataset,
    admin_auth_header,
    test_db_session,
    aggregate_calls,
):
    """A row on the boundary may be the row that defines it, so it recomputes."""
    gid = (
        await test_db_session.execute(
            text(
                f"SELECT gid FROM data.{sketch_dataset.table_name} "
                "WHERE ST_X(geom_4326) = -74.0"
            )
        )
    ).scalar_one()
    _before_count, before_extent = await _state(test_db_session, sketch_dataset)

    resp = await client.delete(
        f"/datasets/{sketch_dataset.id}/features/{gid}", headers=admin_auth_header
    )

    assert resp.status_code == 204, resp.text
    assert aggregate_calls == [sketch_dataset.table_name]
    _after_count, after_extent = await _state(test_db_session, sketch_dataset)
    assert after_extent != before_extent


async def test_moving_a_feature_within_the_extent_runs_no_aggregate(
    client: AsyncClient,
    sketch_dataset: Dataset,
    admin_auth_header,
    test_db_session,
    aggregate_calls,
):
    gid = (
        await test_db_session.execute(
            text(
                f"SELECT gid FROM data.{sketch_dataset.table_name} "
                "WHERE ST_X(geom_4326) = -73.95"
            )
        )
    ).scalar_one()
    before_count, before_extent = await _state(test_db_session, sketch_dataset)

    resp = await client.patch(
        f"/datasets/{sketch_dataset.id}/features/{gid}",
        json={"geometry": INSIDE},
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    assert aggregate_calls == []
    after_count, after_extent = await _state(test_db_session, sketch_dataset)
    assert after_count == before_count
    assert after_extent == before_extent


async def test_moving_a_feature_out_of_the_extent_recomputes(
    client: AsyncClient,
    sketch_dataset: Dataset,
    admin_auth_header,
    test_db_session,
    aggregate_calls,
):
    gid = (
        await test_db_session.execute(
            text(
                f"SELECT gid FROM data.{sketch_dataset.table_name} "
                "WHERE ST_X(geom_4326) = -73.95"
            )
        )
    ).scalar_one()
    _before_count, before_extent = await _state(test_db_session, sketch_dataset)

    resp = await client.patch(
        f"/datasets/{sketch_dataset.id}/features/{gid}",
        json={"geometry": OUTSIDE},
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    assert aggregate_calls == [sketch_dataset.table_name]
    _after_count, after_extent = await _state(test_db_session, sketch_dataset)
    assert after_extent != before_extent


async def test_replacing_a_feature_within_the_extent_runs_no_aggregate(
    client: AsyncClient,
    sketch_dataset: Dataset,
    admin_auth_header,
    test_db_session,
    aggregate_calls,
):
    """PUT is wired the same way as PATCH-with-geometry."""
    gid = (
        await test_db_session.execute(
            text(
                f"SELECT gid FROM data.{sketch_dataset.table_name} "
                "WHERE ST_X(geom_4326) = -73.95"
            )
        )
    ).scalar_one()
    before_count, before_extent = await _state(test_db_session, sketch_dataset)

    resp = await client.put(
        f"/datasets/{sketch_dataset.id}/features/{gid}",
        json={"geometry": INSIDE, "properties": {"name": "moved"}},
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    assert aggregate_calls == []
    after_count, after_extent = await _state(test_db_session, sketch_dataset)
    assert after_count == before_count
    assert after_extent == before_extent


async def test_a_property_only_patch_still_touches_no_metadata(
    client: AsyncClient,
    sketch_dataset: Dataset,
    admin_auth_header,
    test_db_session,
    aggregate_calls,
):
    """The pre-existing short-circuit is unchanged, and reads no prior bounds."""
    gid = (
        await test_db_session.execute(
            text(f"SELECT MIN(gid) FROM data.{sketch_dataset.table_name}")
        )
    ).scalar_one()

    resp = await client.patch(
        f"/datasets/{sketch_dataset.id}/features/{gid}",
        json={"properties": {"name": "renamed"}},
        headers=admin_auth_header,
    )

    assert resp.status_code == 200, resp.text
    assert aggregate_calls == []


async def test_a_seam_extent_always_recomputes(
    sketch_dataset: Dataset, test_db_session, aggregate_calls
):
    """A two-ring antimeridian extent cannot be reasoned about as a box.

    ST_XMin/ST_XMax of the MULTIPOLYGON `seam_extent_wkt_for_table` produces are
    -180/180, so a longitude in the gap would test as inside a box the dataset
    never occupies.
    """
    await test_db_session.execute(
        update(Record)
        .where(Record.id == sketch_dataset.record_id)
        .values(
            spatial_extent=func.ST_GeomFromText(
                "MULTIPOLYGON(((150 -10, 180 -10, 180 10, 150 10, 150 -10)), "
                "((-180 -10, -110 -10, -110 10, -180 10, -180 -10)))",
                4326,
            )
        )
    )
    await test_db_session.flush()

    await features_service.refresh_dataset_metadata(
        test_db_session,
        sketch_dataset,
        count_delta=1,
        touched_bounds=[(0.0, 0.0, 0.0, 0.0)],
        added_geometry_type="Point",
    )

    assert aggregate_calls == [sketch_dataset.table_name]


async def test_a_stale_feature_count_is_recounted_not_adjusted(
    sketch_dataset: Dataset, test_db_session, aggregate_calls
):
    """The increment only applies to a count that is currently a number."""
    sketch_dataset.feature_count = None

    await features_service.refresh_dataset_metadata(
        test_db_session,
        sketch_dataset,
        count_delta=1,
        touched_bounds=[(-73.96, 40.74, -73.96, 40.74)],
        added_geometry_type="Point",
    )

    assert aggregate_calls == [sketch_dataset.table_name]


@pytest.mark.parametrize(
    ("current", "added", "expected"),
    [
        ("POINT", "Point", "POINT"),
        ("POINT", "MultiPoint", "MULTIPOINT"),
        ("MULTIPOINT", "Point", "MULTIPOINT"),
        ("POINT", "Polygon", "GEOMETRY"),
        ("GEOMETRY", "Point", "GEOMETRY"),
        ("GEOMETRYCOLLECTION", "GeometryCollection", "GEOMETRYCOLLECTION"),
        ("GEOMETRYCOLLECTION", "Point", "GEOMETRY"),
        ("POINT", None, None),
        (None, "Point", None),
    ],
)
def test_the_geometry_type_merge_matches_the_scan_it_replaces(current, added, expected):
    assert features_service._merged_created_geometry_type(current, added) == expected


# ---------------------------------------------------------------------------
# fix(#1778 review r1): the prior envelope must come from the mutation itself.
# ---------------------------------------------------------------------------

# Far outside the seeded extent, so an extent computed with this row present
# differs from one computed without it.
FAR_AWAY = (-71.0, 44.0)


async def _stale_read(session, table_name: str, gid: int):
    """The shape the fast path used to rely on: an unlocked SELECT of its own.

    Kept in the test rather than in the service, because demonstrating that
    this read goes stale is the whole point.
    """
    row = (
        await session.execute(
            text(
                f"SELECT ST_XMin(geom_4326), ST_YMin(geom_4326), "
                f"ST_XMax(geom_4326), ST_YMax(geom_4326) "
                f"FROM data.{table_name} WHERE gid = :gid"
            ).bindparams(gid=gid)
        )
    ).first()
    return None if row is None else tuple(float(v) for v in row)


async def _move_far_away_in_another_session(table_name: str, gid: int) -> None:
    """A second connection moves the feature out of the extent and commits."""
    import app.core.db as db_module

    async with db_module.async_session() as other:
        await other.execute(
            text(
                f"UPDATE data.{table_name} SET "
                "geom = ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), "
                "geom_4326 = ST_SetSRID(ST_MakePoint(:lng, :lat), 4326) "
                "WHERE gid = :gid"
            ).bindparams(lng=FAR_AWAY[0], lat=FAR_AWAY[1], gid=gid)
        )
        await other.commit()


async def _interior_gid(session, table_name: str) -> int:
    return (
        await session.execute(
            text(f"SELECT gid FROM data.{table_name} WHERE ST_X(geom_4326) = -73.95")
        )
    ).scalar_one()


async def test_delete_captures_the_version_it_actually_removed(
    sketch_dataset: Dataset, test_db_session, aggregate_calls
):
    """A concurrent move committed after the old pre-read cannot be missed.

    Session A looks at the row, session B moves it outside the extent and
    commits, session A deletes. The envelope the DELETE returns is B's, so the
    fast path is refused and the extent recomputes. Reading the bounds in a
    statement of its own would have handed A the pre-move envelope, which is
    strictly inside the extent, and A would have skipped the aggregate and left
    the expanded extent behind.
    """
    table = sketch_dataset.table_name
    gid = await _interior_gid(test_db_session, table)
    stale = await _stale_read(test_db_session, table, gid)

    await _move_far_away_in_another_session(table, gid)

    removed = await features_service.delete_feature(test_db_session, table, gid)

    assert stale is not None
    assert removed == (FAR_AWAY[0], FAR_AWAY[1], FAR_AWAY[0], FAR_AWAY[1])
    assert removed != stale, "the separate read was the stale one"

    await features_service.refresh_dataset_metadata(
        test_db_session,
        sketch_dataset,
        count_delta=-1,
        touched_bounds=[removed],
    )
    assert aggregate_calls == [table]


async def test_replace_captures_the_version_it_actually_overwrote(
    sketch_dataset: Dataset, test_db_session, aggregate_calls
):
    """Same race on the update path, closed by the locking CTE."""
    table = sketch_dataset.table_name
    gid = await _interior_gid(test_db_session, table)
    stale = await _stale_read(test_db_session, table, gid)

    await _move_far_away_in_another_session(table, gid)

    written = await features_service.replace_feature(
        test_db_session,
        table,
        gid,
        INSIDE,
        {"name": "moved back"},
        [{"name": "name", "type": "text"}],
        "POINT",
        dataset_srid=4326,
    )

    assert written.prior_bounds == (
        FAR_AWAY[0],
        FAR_AWAY[1],
        FAR_AWAY[0],
        FAR_AWAY[1],
    )
    assert written.prior_bounds != stale

    await features_service.refresh_dataset_metadata(
        test_db_session,
        sketch_dataset,
        count_delta=0,
        touched_bounds=[written.prior_bounds, features_service.geojson_bounds(INSIDE)],
    )
    assert aggregate_calls == [table]


async def test_a_deleted_row_without_geometry_reports_no_bounds(
    sketch_dataset: Dataset, test_db_session
):
    """A NULL geometry is not an envelope of zero size, and must not read as one."""
    table = sketch_dataset.table_name
    gid = (
        await test_db_session.execute(
            text(
                f"INSERT INTO data.{table} (geom, geom_4326, name) "
                "VALUES (NULL, NULL, 'no geometry') RETURNING gid"
            )
        )
    ).scalar_one()

    assert await features_service.delete_feature(test_db_session, table, gid) is None


async def test_deleting_a_missing_feature_still_raises(
    sketch_dataset: Dataset, test_db_session
):
    with pytest.raises(ValueError, match="not found"):
        await features_service.delete_feature(
            test_db_session, sketch_dataset.table_name, 987654321
        )


async def test_replacing_a_missing_feature_still_raises(
    sketch_dataset: Dataset, test_db_session
):
    with pytest.raises(ValueError, match="not found"):
        await features_service.replace_feature(
            test_db_session,
            sketch_dataset.table_name,
            987654321,
            INSIDE,
            {"name": "nobody"},
            [{"name": "name", "type": "text"}],
            "POINT",
            dataset_srid=4326,
        )

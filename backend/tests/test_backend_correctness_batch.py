"""Timezone-independent date filters, bounded generated maps, relationship
column validation and clearing an optional user email."""

import uuid
from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.search.service_candidates import _apply_search_only_filters
from app.modules.catalog.search.service_filters import SearchFilters
from app.processing.ai.schemas import LLMMapSpec
from app.standards.ogc.filtering import apply_cql2_filter, compile_feature_cql2


from app.standards.stac.router import _apply_datetime_filter
from tests.factories import create_dataset, get_user_id


def _stored_extent(match, **options):
    return match(Record.spatial_extent)


@pytest.mark.anyio
async def test_stac_instant_filter_ignores_session_timezone(test_db_session):
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(
        test_db_session,
        created_by=admin_id,
        name="TZ Day",
        record_type="raster_dataset",
    )
    await test_db_session.execute(
        text(
            "UPDATE catalog.records SET created_at = '2026-03-10 00:30:00+00' "
            "WHERE id = :rid"
        ),
        {"rid": ds.record_id},
    )
    await test_db_session.commit()
    # A New York session would read 2026-03-10 as 04:00 UTC and drop this record.
    await test_db_session.execute(text("SET TIME ZONE 'America/New_York'"))
    stmt = _apply_datetime_filter(
        select(Record.id).where(Record.id == ds.record_id), "2026-03-10T00:30:00Z"
    )
    assert (await test_db_session.execute(stmt)).scalar_one_or_none() == ds.record_id


# One zone behind UTC and one ahead: a bare date read in the session zone
# starts the day late in the first and early in the second.
_NON_UTC_ZONES = ["America/New_York", "Pacific/Auckland"]

# created_at values around 2026-03-10 UTC; only the two "inside" rows belong to it.
_DAY_EDGES = {
    "before": datetime(2026, 3, 9, 23, 59, tzinfo=timezone.utc),
    "start": datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc),
    "end": datetime(2026, 3, 10, 23, 59, tzinfo=timezone.utc),
    "after": datetime(2026, 3, 11, 0, 0, tzinfo=timezone.utc),
}


async def _records_created_at_the_day_edges(session) -> dict[uuid.UUID, str]:
    admin_id = await get_user_id(session, "admin")
    named: dict[uuid.UUID, str] = {}
    for label, created_at in _DAY_EDGES.items():
        ds = await create_dataset(
            session, created_by=admin_id, name=f"Edge {label} {uuid.uuid4().hex[:6]}"
        )
        await session.execute(
            text("UPDATE catalog.records SET created_at = :at WHERE id = :rid"),
            {"at": created_at, "rid": ds.record_id},
        )
        named[ds.record_id] = label
    await session.commit()
    return named


async def _labels(session, stmt, named: dict[uuid.UUID, str]) -> list[str]:
    ids = (await session.execute(stmt.where(Record.id.in_(named)))).scalars()
    return sorted(named[i] for i in ids)


@pytest.mark.anyio
@pytest.mark.parametrize("zone", _NON_UTC_ZONES)
async def test_search_date_range_ignores_session_timezone(test_db_session, zone):
    named = await _records_created_at_the_day_edges(test_db_session)
    await test_db_session.execute(text(f"SET TIME ZONE '{zone}'"))
    filters = SearchFilters(date_from=date(2026, 3, 10), date_to=date(2026, 3, 10))
    stmt = _apply_search_only_filters(
        select(Record.id).join(Dataset, Dataset.record_id == Record.id),
        filters,
        None,
        set(),
    )
    assert await _labels(test_db_session, stmt, named) == ["end", "start"]


@pytest.mark.anyio
@pytest.mark.parametrize("zone", _NON_UTC_ZONES)
@pytest.mark.parametrize(
    "expression",
    [
        "created >= DATE('2026-03-10') AND created < DATE('2026-03-11')",
        "created >= TIMESTAMP('2026-03-10T00:00:00') "
        "AND created < TIMESTAMP('2026-03-11T00:00:00')",
        "created >= TIMESTAMP('2026-03-10T00:00:00Z') "
        "AND created < TIMESTAMP('2026-03-11T00:00:00Z')",
        "created T_AFTER TIMESTAMP('2026-03-09T23:59:30') "
        "AND created T_BEFORE TIMESTAMP('2026-03-10T23:59:30')",
        "created T_DURING INTERVAL('2026-03-09T23:59:30Z', '2026-03-10T23:59:30Z')",
        "created BETWEEN TIMESTAMP('2026-03-10T00:00:00') "
        "AND TIMESTAMP('2026-03-10T23:59:30')",
        "TIMESTAMP('2026-03-10T00:00:00') <= created AND DATE('2026-03-11') > created",
    ],
)
async def test_records_cql2_temporal_filter_ignores_session_timezone(
    test_db_session, zone, expression
):
    named = await _records_created_at_the_day_edges(test_db_session)
    await test_db_session.execute(text(f"SET TIME ZONE '{zone}'"))
    stmt = apply_cql2_filter(
        select(Record.id), expression, "cql2-text", extent_match=_stored_extent
    )
    assert await _labels(test_db_session, stmt, named) == ["end", "start"]


def test_records_cql2_filter_nested_to_the_length_cap_is_a_400_not_a_crash():
    from fastapi import HTTPException

    expression = " OR ".join(["srid = 1"] * 999)
    with pytest.raises(HTTPException) as refused:
        apply_cql2_filter(
            select(Record.id), expression, "cql2-text", extent_match=_stored_extent
        )
    assert refused.value.status_code == 400


@pytest.mark.anyio
@pytest.mark.parametrize("zone", _NON_UTC_ZONES)
@pytest.mark.parametrize(
    "expression",
    [
        "seen_at >= DATE('2026-03-10') AND seen_at < DATE('2026-03-11')",
        "seen_at >= TIMESTAMP('2026-03-10T00:00:00') "
        "AND seen_at < TIMESTAMP('2026-03-11T00:00:00')",
        "seen_at >= TIMESTAMP('2026-03-10T00:00:00Z') "
        "AND seen_at < TIMESTAMP('2026-03-11T00:00:00Z')",
    ],
)
async def test_feature_cql2_timestamptz_filter_ignores_session_timezone(
    test_db_session, zone, expression
):
    table = f"tz_cql2_{uuid.uuid4().hex[:10]}"
    await test_db_session.execute(
        text(f"CREATE TABLE data.{table} (label text, seen_at timestamptz)")
    )
    for label, seen_at in _DAY_EDGES.items():
        await test_db_session.execute(
            text(f"INSERT INTO data.{table} VALUES (:label, :at)"),
            {"label": label, "at": seen_at},
        )
    await test_db_session.commit()
    try:
        await test_db_session.execute(text(f"SET TIME ZONE '{zone}'"))
        where, binds = compile_feature_cql2(
            expression, "cql2-text", {"seen_at": "timestamp with time zone"}
        )
        rows = await test_db_session.execute(
            text(f"SELECT label FROM data.{table} WHERE {where}").bindparams(*binds)
        )
        assert sorted(r[0] for r in rows) == ["end", "start"]
    finally:
        await test_db_session.rollback()
        await test_db_session.execute(text("RESET TIME ZONE"))
        await test_db_session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
        await test_db_session.commit()


def test_generated_map_spec_is_clamped_to_save_bounds():
    spec = LLMMapSpec(
        name="x" * 400,
        zoom=99,
        center_lat=120,
        layers=[{"dataset_id": str(uuid.uuid4()), "opacity": 2, "sort_order": -1}],
    )
    assert len(spec.name) == 255
    assert spec.zoom == 24
    assert spec.center_lat == 90
    assert spec.layers[0].opacity == 1.0
    assert spec.layers[0].sort_order == 0


@pytest.mark.anyio
async def test_relationship_with_unknown_column_is_rejected(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    admin_id = await get_user_id(test_db_session, "admin")
    columns = [{"name": "k", "type": "integer"}]
    source = await create_dataset(
        test_db_session, created_by=admin_id, name="Rel Src", column_info=columns
    )
    target = await create_dataset(
        test_db_session, created_by=admin_id, name="Rel Tgt", column_info=columns
    )

    async def post(source_column: str, target_column: str):
        return await client.post(
            f"/datasets/{source.id}/relationships/",
            json={
                "target_dataset_id": str(target.record_id),
                "source_column": source_column,
                "target_column": target_column,
            },
            headers=admin_auth_header,
        )

    assert (await post("nope", "k")).status_code == 422
    assert (await post("k", "nope")).status_code == 422
    assert (await post("k", "gid")).status_code == 201

    empty = await create_dataset(
        test_db_session, created_by=admin_id, name="Rel Empty", column_info=[]
    )
    resp = await client.post(
        f"/datasets/{empty.id}/relationships/",
        json={
            "target_dataset_id": str(target.record_id),
            "source_column": "missing",
            "target_column": "k",
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 422

    raster = await create_dataset(
        test_db_session, created_by=admin_id, name="Rel Raster", column_info=None
    )
    assert (
        await client.post(
            f"/datasets/{raster.id}/relationships/",
            json={
                "target_dataset_id": str(target.record_id),
                "source_column": "k",
                "target_column": "k",
            },
            headers=admin_auth_header,
        )
    ).status_code == 422


@pytest.mark.anyio
@pytest.mark.parametrize("clear", [None, ""])
async def test_admin_can_clear_user_email(
    client: AsyncClient, admin_auth_header: dict, clear
):
    email = f"clear_{uuid.uuid4().hex[:8]}@example.com"
    created = await client.post(
        "/admin/users/",
        json={
            "username": f"clear_{uuid.uuid4().hex[:8]}",
            "password": "TestPass1234!",
            "role": "viewer",
            "email": email,
        },
        headers=admin_auth_header,
    )
    assert created.status_code == 201, created.text
    user_id = created.json()["id"]

    omitted = await client.patch(
        f"/admin/users/{user_id}", json={}, headers=admin_auth_header
    )
    assert omitted.json()["email"] == email

    resp = await client.patch(
        f"/admin/users/{user_id}", json={"email": clear}, headers=admin_auth_header
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["email"] is None


@pytest.mark.anyio
async def test_date_to_includes_the_whole_utc_day(client: AsyncClient, test_db_session):
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await create_dataset(test_db_session, created_by=admin_id, name="Date To")
    await test_db_session.execute(
        text(
            "UPDATE catalog.records SET created_at = '2026-03-10 15:00:00+00' "
            "WHERE id = :rid"
        ),
        {"rid": ds.record_id},
    )
    await test_db_session.commit()
    resp = await client.get(
        "/search/datasets/",
        params={"date_to": "2026-03-10", "date_from": "2026-03-10", "limit": 100},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["numberMatched"] >= 1


def test_utc_midnight_saturates_at_the_maximum_date():
    from app.modules.catalog.search.service_filters import utc_midnight

    assert utc_midnight(date.max, 1).year == 9999

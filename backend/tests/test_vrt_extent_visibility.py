"""A VRT's extent covers only the members the requester can read, on every surface.

The stored VRT extent spans every member, so serving it as-is shows a reader
where a member they cannot read lies, which the member lists already hide.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

import pytest
from httpx import AsyncClient
from shapely import wkt as shapely_wkt
from shapely.geometry import shape
from sqlalchemy import text

from tests.test_vrt_source_authz_1172 import (
    _create_raster_dataset,
    _create_vrt_dataset,
    _get_admin_id,
    _link_source,
    _make_editor,
)

READABLE = (10.0, 10.0, 11.0, 11.0)
HIDDEN = (50.0, 50.0, 51.0, 51.0)
FULL = (10.0, 10.0, 51.0, 51.0)


@pytest.fixture(autouse=True)
def _configured_dcat_contact(monkeypatch):
    """DCAT-US export needs a contact mailbox to serve a record at all."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "dcat_contact_email", "catalog@example.gov")


async def _set_extent(session, dataset_id: uuid.UUID, bounds) -> None:
    await session.execute(
        text(
            "UPDATE catalog.records SET spatial_extent = "
            "ST_MakeEnvelope(:w, :s, :e, :n, 4326) "
            "WHERE id = (SELECT record_id FROM catalog.datasets WHERE id = :id)"
        ),
        {
            "id": str(dataset_id),
            "w": bounds[0],
            "s": bounds[1],
            "e": bounds[2],
            "n": bounds[3],
        },
    )
    await session.commit()


async def _vrt_with_members(session, members) -> uuid.UUID:
    """A public, admin-owned VRT over ``members`` (visibility, bounds) pairs."""
    admin_id = await _get_admin_id(session)
    vrt_id = await _create_vrt_dataset(
        session, created_by=admin_id, visibility="public"
    )
    await _set_extent(session, vrt_id, FULL)
    for position, (visibility, bounds) in enumerate(members):
        member = await _create_raster_dataset(
            session, created_by=admin_id, visibility=visibility
        )
        await _set_extent(session, member, bounds)
        await _link_source(session, vrt_id, member, position)
    return vrt_id


def _rounded(bounds):
    return None if bounds is None else tuple(round(v, 6) for v in bounds)


def _wkt_bounds(value: str | None):
    if value is None:
        return None
    return shapely_wkt.loads(value.split("> ")[-1]).bounds


async def _surface_extents(client: AsyncClient, vrt_id: uuid.UUID, headers) -> dict:
    """The extent each surface shows ``headers`` for the VRT, as (w, s, e, n) or None."""
    vid = str(vrt_id)

    async def get(path, **params):
        resp = await client.get(path, params=params, headers=headers)
        assert resp.status_code == 200, f"{path}: {resp.text}"
        return resp.json()

    title_token = (await get(f"/datasets/{vid}"))["title"].split(" ")[3]
    item = await get(f"/collections/datasets/items/{vid}")
    search = await get("/search/datasets/", q=title_token)
    hits = [f for f in search["features"] if f["id"] == vid]
    assert len(hits) == 1, search
    listed = await get("/datasets/", limit=200)
    rows = [d for d in listed["datasets"] if d["id"] == vid]
    assert len(rows) == 1
    collections = await get("/collections", limit=200)
    coll_rows = [c for c in collections["collections"] if c["id"] == vid]
    assert len(coll_rows) == 1
    collection = await get(f"/collections/{vid}")
    stac_item = await get(f"/stac/items/{vid}")
    stac_search = await get("/stac/search", ids=vid)
    assert len(stac_search["features"]) == 1, stac_search
    dcat = await get(f"/datasets/{vid}/dcat/")
    dcat_us = await get(f"/datasets/{vid}/dcat-us/3.0/")
    geodcat = await get(f"/datasets/{vid}/geodcat-ap/")
    feed = await get("/datasets/dcat/", limit=200)
    feed_rows = [d for d in feed["dcat:dataset"] if d["@id"].endswith(vid)]
    assert len(feed_rows) == 1

    def spatial(collection):
        return (
            (collection.get("extent") or {}).get("spatial", {}).get("bbox", [None])[0]
        )

    return {
        "detail": (await get(f"/datasets/{vid}"))["extent_bbox"],
        "list": rows[0]["extent_bbox"],
        "ogc_item_bbox": item.get("bbox"),
        "ogc_item_geometry": item["geometry"] and shape(item["geometry"]).bounds,
        "search_bbox": hits[0].get("bbox"),
        "search_geometry": hits[0]["geometry"] and shape(hits[0]["geometry"]).bounds,
        "collections": spatial(coll_rows[0]),
        "collection": spatial(collection),
        "stac_bbox": stac_item.get("bbox"),
        "stac_geometry": stac_item["geometry"] and shape(stac_item["geometry"]).bounds,
        "stac_search": stac_search["features"][0].get("bbox"),
        "dcat": _wkt_bounds(dcat.get("dcterms:spatial", {}).get("dcat:bbox")),
        "dcat_us": _wkt_bounds(dcat_us.get("spatial", {}).get("bbox")),
        "geodcat": _wkt_bounds(
            geodcat.get("dcterms:spatial", {}).get("dcat:bbox", {}).get("@value")
        ),
        "dcat_feed": _wkt_bounds(
            feed_rows[0].get("dcterms:spatial", {}).get("dcat:bbox")
        ),
    }


async def test_vrt_extent_covers_only_readable_members(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    viewer_headers, _ = await _make_editor(client, admin_auth_header)
    vrt_id = await _vrt_with_members(
        test_db_session, [("public", READABLE), ("private", HIDDEN)]
    )

    viewer = await _surface_extents(client, vrt_id, viewer_headers)
    assert {k: _rounded(v) for k, v in viewer.items()} == dict.fromkeys(
        viewer, READABLE
    )
    admin = await _surface_extents(client, vrt_id, admin_auth_header)
    assert {k: _rounded(v) for k, v in admin.items()} == dict.fromkeys(admin, FULL)


async def test_vrt_with_no_readable_member_shows_no_extent(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    viewer_headers, _ = await _make_editor(client, admin_auth_header)
    vrt_id = await _vrt_with_members(test_db_session, [("private", HIDDEN)])

    viewer = await _surface_extents(client, vrt_id, viewer_headers)
    assert viewer == dict.fromkeys(viewer, None)
    admin = await _surface_extents(client, vrt_id, admin_auth_header)
    assert {k: _rounded(v) for k, v in admin.items()} == dict.fromkeys(admin, FULL)


async def _tile_token_bounds(client: AsyncClient, vrt_id: uuid.UUID, headers):
    single = await client.get(f"/tiles/token/{vrt_id}/", headers=headers)
    assert single.status_code == 200, single.text
    batch = await client.post(
        "/tiles/tokens/", json={"dataset_ids": [str(vrt_id)]}, headers=headers
    )
    assert batch.status_code == 200, batch.text
    return single.json()["bounds"], batch.json()["tokens"][str(vrt_id)]["bounds"]


async def test_tile_token_withholds_bounds_while_the_mosaic_is_refused(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """A member another user narrowed makes the mosaic's tiles 409; the token
    then carries no bounds that would locate it."""
    admin_id = await _get_admin_id(test_db_session)
    editor_headers, editor_id = await _make_editor(client, admin_auth_header)
    vrt_id = await _create_vrt_dataset(
        test_db_session, created_by=admin_id, visibility="public"
    )
    await _set_extent(test_db_session, vrt_id, FULL)
    member = await _create_raster_dataset(
        test_db_session, created_by=editor_id, visibility="public"
    )
    await _link_source(test_db_session, vrt_id, member, 0)
    narrow = await client.patch(
        f"/datasets/{member}", json={"visibility": "private"}, headers=editor_headers
    )
    assert narrow.status_code == 200, narrow.text

    tiles = await client.get(
        "/tiles/raster-auth-check/", params={"dataset_id": str(vrt_id)}
    )
    assert tiles.status_code == 409, tiles.text
    assert await _tile_token_bounds(client, vrt_id, admin_auth_header) == (None, None)


async def test_tile_token_keeps_bounds_for_a_mosaic_that_serves(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    vrt_id = await _vrt_with_members(test_db_session, [("public", READABLE)])

    single, batch = await _tile_token_bounds(client, vrt_id, admin_auth_header)
    assert _rounded(single) == _rounded(batch) == FULL


async def test_batch_tile_tokens_ask_about_every_mosaic_at_once(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    from app.platform.extensions import get_processing_port

    admin_id = await _get_admin_id(test_db_session)
    editor_headers, editor_id = await _make_editor(client, admin_auth_header)
    serving = [
        await _vrt_with_members(test_db_session, [("public", READABLE)])
        for _ in range(2)
    ]
    refused = await _create_vrt_dataset(
        test_db_session, created_by=admin_id, visibility="public"
    )
    await _set_extent(test_db_session, refused, FULL)
    member = await _create_raster_dataset(
        test_db_session, created_by=editor_id, visibility="public"
    )
    await _link_source(test_db_session, refused, member, 0)
    narrow = await client.patch(
        f"/datasets/{member}", json={"visibility": "private"}, headers=editor_headers
    )
    assert narrow.status_code == 200, narrow.text

    # Without a registered overlay each call builds a new default port.
    port_cls = type(get_processing_port())
    calls: list[int] = []
    bulk = port_cls.vrts_beyond_member_audience
    single = port_cls.vrt_members_beyond_audience

    async def counted_bulk(self, session, vrts):
        calls.append(len(vrts))
        return await bulk(self, session, vrts)

    async def counted_single(self, session, member_ids, vrt):
        calls.append(-1)
        return await single(self, session, member_ids, vrt)

    monkeypatch.setattr(port_cls, "vrts_beyond_member_audience", counted_bulk)
    monkeypatch.setattr(port_cls, "vrt_members_beyond_audience", counted_single)
    ids = [str(vrt_id) for vrt_id in [*serving, refused]]
    batch = await client.post(
        "/tiles/tokens/", json={"dataset_ids": ids}, headers=admin_auth_header
    )

    assert batch.status_code == 200, batch.text
    assert calls == [3]
    bounds = {k: _rounded(v["bounds"]) for k, v in batch.json()["tokens"].items()}
    assert bounds == {ids[0]: FULL, ids[1]: FULL, ids[2]: None}


async def test_batch_tile_tokens_bound_the_audience_statements(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Eleven 500-member mosaics would bind 44,000 parameters in one statement."""
    admin_id = await _get_admin_id(test_db_session)
    vrt_ids = [
        await _create_vrt_dataset(
            test_db_session, created_by=admin_id, visibility="public"
        )
        for _ in range(11)
    ]
    await test_db_session.execute(
        text(
            """
            WITH recs AS (
                INSERT INTO catalog.records (title, visibility, record_status, created_by)
                SELECT 'VRT batch member ' || g, 'public', 'published', :owner
                FROM generate_series(1, :n) AS g
                RETURNING id
            ), members AS (
                INSERT INTO catalog.datasets (record_id, table_name)
                SELECT id, 'vrt_batch_' || replace(id::text, '-', '') FROM recs
                RETURNING id
            ), numbered AS (
                SELECT id, row_number() OVER () - 1 AS n FROM members
            )
            INSERT INTO catalog.vrt_source_links
                (vrt_dataset_id, source_dataset_id, position)
            SELECT (CAST(:vrts AS uuid[]))[1 + n / 500], id, n % 500 FROM numbered
            """
        ),
        {"owner": admin_id, "n": 11 * 500, "vrts": vrt_ids},
    )
    await test_db_session.commit()
    try:
        batch = await client.post(
            "/tiles/tokens/",
            json={"dataset_ids": [str(vrt_id) for vrt_id in vrt_ids]},
            headers=admin_auth_header,
        )
        assert batch.status_code == 200, batch.text
        tokens = batch.json()["tokens"]
        assert all("tile_url" in tokens[str(vrt_id)] for vrt_id in vrt_ids)
    finally:
        await test_db_session.rollback()
        await test_db_session.execute(
            text(
                """
                WITH links AS (
                    DELETE FROM catalog.vrt_source_links
                    WHERE vrt_dataset_id = ANY(CAST(:vrts AS uuid[]))
                    RETURNING source_dataset_id
                ), members AS (
                    DELETE FROM catalog.datasets
                    WHERE id IN (SELECT source_dataset_id FROM links)
                    RETURNING record_id
                )
                DELETE FROM catalog.records WHERE id IN (SELECT record_id FROM members)
                """
            ),
            {"vrts": vrt_ids},
        )
        await test_db_session.commit()


async def test_tile_token_withholds_bounds_for_a_refused_mosaic_without_an_asset(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """The refusal is decided from the VRT's members, not from its asset row."""
    admin_id = await _get_admin_id(test_db_session)
    viewer_headers, _ = await _make_editor(client, admin_auth_header)
    _, member_owner = await _make_editor(client, admin_auth_header)
    vrt_id = await _create_vrt_dataset(
        test_db_session, created_by=admin_id, visibility="public"
    )
    await _set_extent(test_db_session, vrt_id, FULL)
    member = await _create_raster_dataset(
        test_db_session, created_by=member_owner, visibility="private"
    )
    await _link_source(test_db_session, vrt_id, member, 0)
    await test_db_session.execute(
        text("DELETE FROM catalog.raster_assets WHERE dataset_id = :id"),
        {"id": str(vrt_id)},
    )
    await test_db_session.commit()

    single = await client.get(f"/tiles/token/{vrt_id}/", headers=viewer_headers)
    batch = await client.post(
        "/tiles/tokens/", json={"dataset_ids": [str(vrt_id)]}, headers=viewer_headers
    )

    assert single.status_code == 200, single.text
    assert batch.status_code == 200, batch.text
    assert single.json()["bounds"] is None
    assert batch.json()["tokens"][str(vrt_id)]["bounds"] is None

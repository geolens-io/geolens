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

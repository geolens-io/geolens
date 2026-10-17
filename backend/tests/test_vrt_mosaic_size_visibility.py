"""A VRT's full-mosaic size is shown only to requesters who can read every member.

The mosaic's width and height span every member, so with the pixel size they
locate a hidden member as surely as the stored extent does.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import text

from tests.test_vrt_extent_visibility import (
    _create_raster_dataset,
    _create_vrt_dataset,
    _get_admin_id,
    _link_source,
    _make_editor,
    _set_extent,
)

READABLE = (0.0, 0.0, 1.0, 1.0)
RES = 0.01


async def _set_mosaic_size(session, dataset_id: uuid.UUID, bounds) -> None:
    """Store the size a mosaic build over ``bounds`` at ``RES`` records."""
    west, south, east, north = bounds
    await session.execute(
        text(
            "UPDATE catalog.raster_assets SET width = :w, height = :h, "
            "res_x = :res, res_y = :neg, size_bytes = 4096 WHERE dataset_id = :id"
        ),
        {
            "id": str(dataset_id),
            "w": round((east - west) / RES),
            "h": round((north - south) / RES),
            "res": RES,
            "neg": -RES,
        },
    )
    await session.commit()


async def _mosaic(session, hidden_west: float | None) -> uuid.UUID:
    """A public VRT over a public member and, unless None, a hidden one."""
    admin_id = await _get_admin_id(session)
    members = [("public", READABLE)]
    if hidden_west is not None:
        members.append(("private", (hidden_west, 0.0, hidden_west + 1.0, 1.0)))
    east = max(bounds[2] for _, bounds in members)
    vrt_id = await _create_vrt_dataset(
        session, created_by=admin_id, visibility="public"
    )
    await _set_extent(session, vrt_id, (0.0, 0.0, east, 1.0))
    await _set_mosaic_size(session, vrt_id, (0.0, 0.0, east, 1.0))
    for position, (visibility, bounds) in enumerate(members):
        member = await _create_raster_dataset(
            session, created_by=admin_id, visibility=visibility
        )
        await _set_extent(session, member, bounds)
        await _set_mosaic_size(session, member, bounds)
        await _link_source(session, vrt_id, member, position)
    return vrt_id


_SPATIAL_PROPERTIES = ("gsd", "res_x", "res_y", "source_count")


def _spatial(feature: dict) -> dict:
    properties = feature.get("properties", {})
    return {
        "bbox": feature.get("bbox"),
        "geometry": feature.get("geometry"),
        **{
            key: value
            for key, value in properties.items()
            if key.startswith("proj:") or key in _SPATIAL_PROPERTIES
        },
    }


async def _disclosed(client: AsyncClient, vrt_id: uuid.UUID, headers: dict) -> dict:
    """Every size or position field the surfaces disclose for the VRT."""
    vid = str(vrt_id)

    async def get(path, **params):
        resp = await client.get(path, params=params, headers=headers)
        assert resp.status_code == 200, f"{path}: {resp.text}"
        return resp.json()

    detail = await get(f"/datasets/{vid}")
    raster = {
        key: value
        for key, value in (detail["raster"] or {}).items()
        if key not in ("tile_url", "connect")
    }
    token = detail["title"].split(" ")[3]
    search = await get("/search/datasets/", q=token)
    (hit,) = [f for f in search["features"] if f["id"] == vid]
    return {
        "extent_bbox": detail["extent_bbox"],
        "raster": raster,
        "search": _spatial(hit),
        "ogc_item": _spatial(await get(f"/collections/datasets/items/{vid}")),
        "stac_item": _spatial(await get(f"/stac/items/{vid}")),
    }


async def test_moving_a_hidden_member_changes_no_disclosed_field(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    viewer_headers, _ = await _make_editor(client, admin_auth_header)
    near = await _mosaic(test_db_session, hidden_west=10.0)
    far = await _mosaic(test_db_session, hidden_west=20.0)

    for headers in ({}, viewer_headers):
        shown = await _disclosed(client, near, headers)
        assert shown == await _disclosed(client, far, headers)
        assert shown["raster"]["width"] is None
        assert shown["raster"]["height"] is None
        assert "proj:shape" not in shown["stac_item"]


async def test_readers_of_every_member_see_the_full_mosaic_size(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    viewer_headers, _ = await _make_editor(client, admin_auth_header)
    hidden = await _mosaic(test_db_session, hidden_west=10.0)
    readable = await _mosaic(test_db_session, hidden_west=None)

    admin = await _disclosed(client, hidden, admin_auth_header)
    assert (admin["raster"]["width"], admin["raster"]["height"]) == (1100, 100)
    assert admin["stac_item"]["proj:shape"] == [100, 1100]
    assert admin["ogc_item"]["proj:shape"] == [100, 1100]
    viewer = await _disclosed(client, readable, viewer_headers)
    assert (viewer["raster"]["width"], viewer["raster"]["height"]) == (100, 100)
    assert viewer["search"]["proj:shape"] == [100, 100]

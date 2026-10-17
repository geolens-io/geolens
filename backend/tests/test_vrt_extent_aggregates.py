"""Extent rollups and map layers show a VRT's extent as the requester sees it.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import json
import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.core.geo import rollup_bbox, rollup_bbox_columns
from app.modules.catalog.authorization import get_user_roles, visible_extent_column
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.auth.models import User
from tests.factories import create_collection_via_api
from tests.test_vrt_extent_visibility import (
    FULL,
    HIDDEN,
    READABLE,
    _make_editor,
    _rounded,
    _vrt_with_members,
)


async def _collection_with(client, admin_auth_header, dataset_id) -> str:
    collection = await create_collection_via_api(client, admin_auth_header)
    added = await client.post(
        f"/catalog/collections/{collection['id']}/datasets/",
        json={"dataset_ids": [str(dataset_id)]},
        headers=admin_auth_header,
    )
    assert added.status_code == 200, added.text
    return collection["id"]


async def _collection_extents(client, collection_id, headers) -> dict:
    catalog = await client.get(f"/catalog/collections/{collection_id}", headers=headers)
    assert catalog.status_code == 200, catalog.text
    stac = await client.get(f"/stac/collections/{collection_id}", headers=headers)
    assert stac.status_code == 200, stac.text
    stac_list = await client.get("/stac/collections", headers=headers)
    assert stac_list.status_code == 200, stac_list.text
    listed = [c for c in stac_list.json()["collections"] if c["id"] == collection_id]
    assert len(listed) == 1
    return {
        "catalog": catalog.json()["extent_bbox"],
        "stac": stac.json()["extent"]["spatial"]["bbox"][0],
        "stac_list": listed[0]["extent"]["spatial"]["bbox"][0],
    }


async def test_collection_extents_cover_only_readable_members(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    viewer_headers, _ = await _make_editor(client, admin_auth_header)
    vrt_id = await _vrt_with_members(
        test_db_session, [("public", READABLE), ("private", HIDDEN)]
    )
    collection_id = await _collection_with(client, admin_auth_header, vrt_id)

    viewer = await _collection_extents(client, collection_id, viewer_headers)
    assert {k: _rounded(v) for k, v in viewer.items()} == dict.fromkeys(
        viewer, READABLE
    )
    admin = await _collection_extents(client, collection_id, admin_auth_header)
    assert {k: _rounded(v) for k, v in admin.items()} == dict.fromkeys(admin, FULL)


async def test_visible_extent_column_rolls_up_readable_members(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """The column behind the catalog-wide search extent, rolled up over one VRT."""
    _, viewer_id = await _make_editor(client, admin_auth_header)
    viewer = await test_db_session.get(User, viewer_id)
    roles = await get_user_roles(test_db_session, viewer)
    partly = await _vrt_with_members(
        test_db_session, [("public", READABLE), ("private", HIDDEN)]
    )
    hidden = await _vrt_with_members(test_db_session, [("private", HIDDEN)])

    async def rollup(vrt_id):
        row = (
            await test_db_session.execute(
                select(*rollup_bbox_columns(visible_extent_column(viewer, roles)))
                .select_from(Dataset)
                .join(Record, Dataset.record_id == Record.id)
                .where(Dataset.id == vrt_id)
            )
        ).one()
        return _rounded(rollup_bbox(row))

    assert await rollup(partly) == READABLE
    assert await rollup(hidden) is None


async def test_map_layer_extent_covers_only_readable_members(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    viewer_headers, _ = await _make_editor(client, admin_auth_header)
    vrt_id = await _vrt_with_members(
        test_db_session, [("public", READABLE), ("private", HIDDEN)]
    )

    async def layer_extents(headers) -> dict:
        created = await client.post(
            "/maps/",
            json={"name": f"vrt extent {uuid.uuid4().hex[:6]}"},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        map_id = created.json()["id"]
        added = await client.post(
            f"/maps/{map_id}/layers/", json={"dataset_id": str(vrt_id)}, headers=headers
        )
        assert added.status_code in (200, 201), added.text
        fetched = await client.get(f"/maps/{map_id}", headers=headers)
        assert fetched.status_code == 200, fetched.text
        updated = await client.put(
            f"/maps/{map_id}", json={"description": "x"}, headers=headers
        )
        assert updated.status_code == 200, updated.text
        return {
            "add_layer": added.json()["dataset_extent_bbox"],
            "get_map": fetched.json()["layers"][0]["dataset_extent_bbox"],
            "update_map": updated.json()["layers"][0]["dataset_extent_bbox"],
        }

    viewer = await layer_extents(viewer_headers)
    assert {k: _rounded(v) for k, v in viewer.items()} == dict.fromkeys(
        viewer, READABLE
    )
    admin = await layer_extents(admin_auth_header)
    assert {k: _rounded(v) for k, v in admin.items()} == dict.fromkeys(admin, FULL)


def _box(bounds) -> dict:
    w, s, e, n = bounds
    return {
        "type": "Polygon",
        "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]],
    }


def _wkt(bounds) -> str:
    w, s, e, n = bounds
    return f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"


async def _spatial_hits(client, vrt_id, headers, collection_id, bounds) -> dict:
    """Whether each spatial filter over ``bounds`` returns the VRT."""
    vid = str(vrt_id)
    token = (await client.get(f"/datasets/{vid}", headers=headers)).json()["title"]
    token = token.split(" ")[3]
    box = ",".join(str(v) for v in bounds)
    geometry = json.dumps(_box(bounds))

    async def found(path, ids_key="id", method="get", **kwargs):
        resp = await getattr(client, method)(path, headers=headers, **kwargs)
        assert resp.status_code == 200, f"{path}: {resp.text}"
        return any(f[ids_key] == vid for f in resp.json()["features"])

    return {
        "search_bbox": await found(
            "/search/datasets/", params={"q": token, "bbox": box}
        ),
        "search_geometry": await found(
            "/search/datasets/", params={"q": token, "geometry": geometry}
        ),
        "search_within": await found(
            "/search/datasets/",
            params={"q": token, "bbox": box, "spatial_predicate": "within"},
        ),
        "cql2_intersects": await found(
            "/collections/datasets/items",
            params={"q": token, "filter": f"S_INTERSECTS(geometry, {_wkt(bounds)})"},
        ),
        "cql2_not_disjoint": await found(
            "/collections/datasets/items",
            params={"q": token, "filter": f"NOT S_DISJOINT(geometry, {_wkt(bounds)})"},
        ),
        "stac_bbox": await found("/stac/search", params={"ids": vid, "bbox": box}),
        "stac_intersects": await found(
            "/stac/search",
            method="post",
            json={"ids": [vid], "intersects": _box(bounds)},
        ),
        "stac_collection_bbox": await found(
            f"/stac/collections/{collection_id}/items", params={"bbox": box}
        ),
    }


async def test_spatial_filters_match_a_vrt_by_its_readable_members(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    viewer_headers, _ = await _make_editor(client, admin_auth_header)
    vrt_id = await _vrt_with_members(
        test_db_session, [("public", READABLE), ("private", HIDDEN)]
    )
    collection_id = await _collection_with(client, admin_auth_header, vrt_id)

    async def hits(headers, bounds):
        return await _spatial_hits(client, vrt_id, headers, collection_id, bounds)

    over_hidden = await hits(viewer_headers, HIDDEN)
    assert over_hidden == dict.fromkeys(over_hidden, False)
    over_readable = await hits(viewer_headers, READABLE)
    assert over_readable == dict.fromkeys(over_readable, True)
    admin = await hits(admin_auth_header, HIDDEN)
    assert admin == {**dict.fromkeys(admin, True), "search_within": False}


async def test_cql2_disjoint_matches_a_vrt_by_its_readable_members(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """A negative predicate must not exclude a VRT for its hidden member."""
    viewer_headers, _ = await _make_editor(client, admin_auth_header)
    vrt_id = await _vrt_with_members(
        test_db_session, [("public", READABLE), ("private", HIDDEN)]
    )
    token = (
        (await client.get(f"/datasets/{vrt_id}", headers=admin_auth_header))
        .json()["title"]
        .split(" ")[3]
    )

    async def disjoint(headers) -> bool:
        resp = await client.get(
            "/collections/datasets/items",
            params={"q": token, "filter": f"S_DISJOINT(geometry, {_wkt(HIDDEN)})"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        return any(f["id"] == str(vrt_id) for f in resp.json()["features"])

    assert await disjoint(viewer_headers) is True
    assert await disjoint(admin_auth_header) is False


async def _records_filter_hit(client, headers, token, vrt_id, expr, lang="cql2-text"):
    params = {"q": token, "filter": expr, "filter-lang": lang}
    resp = await client.get(
        "/collections/datasets/items", params=params, headers=headers
    )
    assert resp.status_code == 200, f"{expr}: {resp.text}"
    return any(f["id"] == str(vrt_id) for f in resp.json()["features"])


async def test_negated_predicates_treat_a_fully_hidden_vrt_as_empty(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Probes inside and outside the stored extent give the same answer."""
    viewer_headers, _ = await _make_editor(client, admin_auth_header)
    vrt_id = await _vrt_with_members(test_db_session, [("private", HIDDEN)])
    token = (
        (await client.get(f"/datasets/{vrt_id}", headers=admin_auth_header))
        .json()["title"]
        .split(" ")[3]
    )
    inside, outside = (50.5, 50.5), (-100.0, -50.0)

    def text_probes(x, y):
        point = f"POINT({x} {y})"
        box = f"BBOX(geometry, {x - 0.1}, {y - 0.1}, {x + 0.1}, {y + 0.1})"
        return [
            f"NOT S_INTERSECTS(geometry, {point})",
            f"NOT S_WITHIN(geometry, {_wkt((x - 1, y - 1, x + 1, y + 1))})",
            f"NOT S_CONTAINS(geometry, {point})",
            f"NOT {box}",
            f"NOT S_INTERSECTS(geometry, {point}) AND title LIKE '%{token}%'",
            f"NOT S_INTERSECTS(geometry, {point}) OR title = 'no such title'",
        ]

    def json_probe(x, y):
        return json.dumps(
            {
                "op": "not",
                "args": [
                    {
                        "op": "s_intersects",
                        "args": [
                            {"property": "geometry"},
                            {"type": "Point", "coordinates": [x, y]},
                        ],
                    }
                ],
            }
        )

    for x, y in (inside, outside):
        for expr in text_probes(x, y):
            assert await _records_filter_hit(
                client, viewer_headers, token, vrt_id, expr
            ), expr
        assert await _records_filter_hit(
            client, viewer_headers, token, vrt_id, json_probe(x, y), "cql2-json"
        )
    assert not await _records_filter_hit(
        client, admin_auth_header, token, vrt_id, text_probes(*inside)[0]
    )


async def test_cql2_geometry_against_itself_uses_the_visible_extent(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    viewer_headers, _ = await _make_editor(client, admin_auth_header)
    vrt_id = await _vrt_with_members(
        test_db_session, [("public", READABLE), ("private", HIDDEN)]
    )
    token = (
        (await client.get(f"/datasets/{vrt_id}", headers=admin_auth_header))
        .json()["title"]
        .split(" ")[3]
    )
    for expr in ("S_EQUALS(geometry, geometry)", "S_CONTAINS(geometry, geometry)"):
        assert await _records_filter_hit(client, viewer_headers, token, vrt_id, expr)


async def test_cql2_geometry_outside_a_spatial_predicate_is_refused(
    client: AsyncClient, admin_auth_header: dict
):
    point = {"type": "Point", "coordinates": [1, 2]}
    refused = [
        ("geometry = POINT(1 2)", "cql2-text"),
        ("POINT(1 2) <> geometry", "cql2-text"),
        ("geometry IN (POINT(1 2))", "cql2-text"),
        ("geometry BETWEEN 1 AND 2", "cql2-text"),
        ("geometry LIKE 'x%'", "cql2-text"),
    ]
    refused += [
        (json.dumps({"op": op, "args": [{"property": "geometry"}, point]}), "cql2-json")
        for op in ("=", "<>", "<", "<=", ">", ">=")
    ]
    for expr, lang in refused:
        resp = await client.get(
            "/collections/datasets/items",
            params={"filter": expr, "filter-lang": lang},
            headers=admin_auth_header,
        )
        assert resp.status_code == 400, f"{expr}: {resp.status_code} {resp.text}"


async def test_cql2_geometry_is_null_follows_the_visible_extent(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    viewer_headers, _ = await _make_editor(client, admin_auth_header)
    vrt_id = await _vrt_with_members(test_db_session, [("private", HIDDEN)])
    token = (
        (await client.get(f"/datasets/{vrt_id}", headers=admin_auth_header))
        .json()["title"]
        .split(" ")[3]
    )

    async def hit(headers, expr):
        return await _records_filter_hit(client, headers, token, vrt_id, expr)

    assert await hit(viewer_headers, "geometry IS NULL")
    assert not await hit(viewer_headers, "geometry IS NOT NULL")
    assert not await hit(admin_auth_header, "geometry IS NULL")


async def test_filters_and_responses_share_the_readable_envelope(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Two separate readable members: a box in the gap between them finds the VRT."""
    viewer_headers, _ = await _make_editor(client, admin_auth_header)
    vrt_id = await _vrt_with_members(
        test_db_session,
        [
            ("public", READABLE),
            ("public", (20.0, 20.0, 21.0, 21.0)),
            ("private", HIDDEN),
        ],
    )
    token = (
        (await client.get(f"/datasets/{vrt_id}", headers=viewer_headers))
        .json()["title"]
        .split(" ")[3]
    )
    detail = await client.get(f"/datasets/{vrt_id}", headers=viewer_headers)
    assert _rounded(detail.json()["extent_bbox"]) == (10.0, 10.0, 21.0, 21.0)

    search = await client.get(
        "/search/datasets/",
        params={"q": token, "bbox": "15,15,16,16"},
        headers=viewer_headers,
    )
    assert search.status_code == 200, search.text
    assert any(f["id"] == str(vrt_id) for f in search.json()["features"])


async def _vrt_over(session, stored, members) -> uuid.UUID:
    """An admin-owned public VRT with ``stored`` extent over ``members``."""
    from tests.test_vrt_extent_visibility import (
        _create_raster_dataset,
        _create_vrt_dataset,
        _get_admin_id,
        _link_source,
        _set_extent,
    )

    admin_id = await _get_admin_id(session)
    vrt_id = await _create_vrt_dataset(
        session, created_by=admin_id, visibility="public"
    )
    await _set_extent(session, vrt_id, stored)
    for position, (visibility, bounds) in enumerate(members):
        member = await _create_raster_dataset(
            session, created_by=admin_id, visibility=visibility
        )
        await _set_extent(session, member, bounds)
        await _link_source(session, vrt_id, member, position)
    return vrt_id


async def test_hidden_member_bounds_change_nothing_across_the_antimeridian(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """Moving only a hidden member's eastern edge changes no answer the viewer gets."""
    viewer_headers, _ = await _make_editor(client, admin_auth_header)
    readable = [
        ("public", (160.0, 10.0, 170.0, 11.0)),
        ("public", (-170.0, 10.0, -160.0, 11.0)),
    ]
    point = {"type": "Point", "coordinates": [176.0, 10.5]}

    async def answers(east: float) -> dict:
        vrt_id = await _vrt_over(
            test_db_session,
            (-170.0, 10.0, east, 11.0),
            [*readable, ("private", (-150.0, 10.0, east, 11.0))],
        )
        collection_id = await _collection_with(client, admin_auth_header, vrt_id)
        detail = await client.get(f"/datasets/{vrt_id}", headers=viewer_headers)
        token = detail.json()["title"].split(" ")[3]
        stac = await client.get(
            "/stac/search",
            params={"ids": str(vrt_id), "bbox": "175.9,10.4,176.1,10.6"},
            headers=viewer_headers,
        )
        search = await client.get(
            "/search/datasets/",
            params={"q": token, "bbox": "175.9,10.4,176.1,10.6"},
            headers=viewer_headers,
        )
        collection = await client.get(
            f"/catalog/collections/{collection_id}", headers=viewer_headers
        )
        cql2_json = json.dumps(
            {"op": "s_intersects", "args": [{"property": "geometry"}, point]}
        )
        return {
            "detail": _rounded(detail.json()["extent_bbox"]),
            "search_bbox": any(
                f["id"] == str(vrt_id) for f in search.json()["features"]
            ),
            "cql2_text": await _records_filter_hit(
                client,
                viewer_headers,
                token,
                vrt_id,
                "S_INTERSECTS(geometry, POINT(176 10.5))",
            ),
            "cql2_json": await _records_filter_hit(
                client, viewer_headers, token, vrt_id, cql2_json, "cql2-json"
            ),
            "stac_bbox": len(stac.json()["features"]) == 1,
            "collection": _rounded(collection.json()["extent_bbox"]),
        }

    near, far = await answers(175.0), await answers(178.0)
    assert near == far
    assert all(near[k] for k in ("search_bbox", "cql2_text", "cql2_json", "stac_bbox"))
    assert near["detail"] == (160.0, 10.0, -160.0, 11.0)
    assert near["collection"] == (160.0, 10.0, -160.0, 11.0)


async def test_a_fully_hidden_vrt_equals_an_empty_geometry(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    viewer_headers, _ = await _make_editor(client, admin_auth_header)
    vrt_id = await _vrt_with_members(test_db_session, [("private", HIDDEN)])
    token = (
        (await client.get(f"/datasets/{vrt_id}", headers=admin_auth_header))
        .json()["title"]
        .split(" ")[3]
    )
    equals_empty = {
        "op": "s_equals",
        "args": [{"property": "geometry"}, {"type": "Polygon", "coordinates": []}],
    }

    async def hit(expr) -> bool:
        return await _records_filter_hit(
            client, viewer_headers, token, vrt_id, json.dumps(expr), "cql2-json"
        )

    assert await hit(equals_empty)
    assert not await hit({"op": "not", "args": [equals_empty]})

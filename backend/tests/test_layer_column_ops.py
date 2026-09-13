"""Integration tests for layer column rename and type alter endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def _create_layer(client: AsyncClient, headers: dict, *, title: str) -> str:
    resp = await client.post(
        "/layers/",
        json={
            "title": title,
            "geometry_type": "Point",
            "columns": [
                {"name": "name", "type": "text"},
                {"name": "value", "type": "text"},
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.mark.anyio
async def test_rename_column_success(client: AsyncClient, admin_auth_header: dict):
    """PATCH .../columns/{name}/name renames the column and returns the new column list."""
    dataset_id = await _create_layer(client, admin_auth_header, title="Rename Test")

    resp = await client.patch(
        f"/layers/{dataset_id}/columns/value/name",
        json={"new_name": "amount"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    names = {c["name"] for c in resp.json()["columns"]}
    assert "amount" in names
    assert "value" not in names


@pytest.mark.anyio
async def test_rename_column_to_existing_name_fails(
    client: AsyncClient, admin_auth_header: dict
):
    """Renaming to an existing column name returns 400."""
    dataset_id = await _create_layer(client, admin_auth_header, title="Rename Conflict")

    resp = await client.patch(
        f"/layers/{dataset_id}/columns/value/name",
        json={"new_name": "name"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_rename_column_preserves_a_dropped_names_metadata(
    client: AsyncClient, admin_auth_header: dict
):
    """A retained name is rejected clearly without losing either column's metadata."""
    dataset_id = await _create_layer(
        client, admin_auth_header, title="Reuse Dropped Column Name"
    )
    inserted = await client.post(
        f"/datasets/{dataset_id}/features/",
        json={
            "geometry": {"type": "Point", "coordinates": [1, 2]},
            "properties": {"name": "preserved", "value": "removed"},
        },
        headers=admin_auth_header,
    )
    assert inserted.status_code == 201, inserted.text
    gid = inserted.json()["id"]

    dropped = await client.delete(
        f"/layers/{dataset_id}/columns/value", headers=admin_auth_header
    )
    assert dropped.status_code == 200, dropped.text
    before = await client.get(
        f"/datasets/{dataset_id}/attributes/",
        params={"include_removed": True},
        headers=admin_auth_header,
    )
    assert before.status_code == 200, before.text
    attributes = {a["field_name"]: a for a in before.json()["attributes"]}
    assert attributes["name"]["is_current"] is True
    assert attributes["value"]["is_current"] is False

    renamed = await client.patch(
        f"/layers/{dataset_id}/columns/name/name",
        json={"new_name": "value"},
        headers=admin_auth_header,
    )
    assert renamed.status_code == 400, renamed.text
    assert "retained metadata" in renamed.json()["detail"]
    assert "different name" in renamed.json()["detail"]

    persisted = await client.get(
        f"/datasets/{dataset_id}/features/{gid}", headers=admin_auth_header
    )
    assert persisted.status_code == 200, persisted.text
    assert persisted.json()["properties"] == {"name": "preserved"}
    after = await client.get(
        f"/datasets/{dataset_id}/attributes/",
        params={"include_removed": True},
        headers=admin_auth_header,
    )
    assert after.status_code == 200, after.text
    assert after.json() == before.json()


@pytest.mark.anyio
async def test_rename_column_reserved_rejected(
    client: AsyncClient, admin_auth_header: dict
):
    """Renaming to a reserved column name returns 422 (Pydantic validation)."""
    dataset_id = await _create_layer(client, admin_auth_header, title="Reserved Test")

    resp = await client.patch(
        f"/layers/{dataset_id}/columns/value/name",
        json={"new_name": "geom"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_alter_column_type_success(client: AsyncClient, admin_auth_header: dict):
    """PATCH .../columns/{name}/type changes the type when no rows exist."""
    dataset_id = await _create_layer(client, admin_auth_header, title="Type Alter Test")

    resp = await client.patch(
        f"/layers/{dataset_id}/columns/value/type",
        json={"new_type": "integer"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    cols = {c["name"]: c for c in resp.json()["columns"]}
    assert cols["value"]["type"].lower().startswith("int")


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("column_type", "value", "next_value"),
    [
        ("date", "2026-09-12", "2026-09-13"),
        ("timestamp", "2026-09-12T10:30:00+00:00", "2026-09-13T11:45:00+00:00"),
    ],
)
async def test_feature_temporal_column_round_trips(
    client: AsyncClient,
    admin_auth_header: dict,
    column_type: str,
    value: str,
    next_value: str,
):
    """JSON temporal values must remain writable after a supported column cast."""
    dataset_id = await _create_layer(
        client, admin_auth_header, title=f"Temporal Edit {column_type}"
    )
    changed = await client.patch(
        f"/layers/{dataset_id}/columns/value/type",
        json={"new_type": column_type},
        headers=admin_auth_header,
    )
    assert changed.status_code == 200, changed.text
    inserted = await client.post(
        f"/datasets/{dataset_id}/features/",
        json={
            "geometry": {"type": "Point", "coordinates": [1, 2]},
            "properties": {"value": value},
        },
        headers=admin_auth_header,
    )
    assert inserted.status_code == 201, inserted.text
    assert inserted.json()["properties"]["value"] == value
    feature_url = f"/datasets/{dataset_id}/features/{inserted.json()['id']}"
    for method in ("PATCH", "PUT"):
        updated = await client.request(
            method,
            feature_url,
            json={
                "geometry": {"type": "Point", "coordinates": [2, 3]},
                "properties": {"value": next_value},
            },
            headers=admin_auth_header,
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["properties"]["value"] == next_value

    invalid = await client.patch(
        feature_url,
        json={"properties": {"name": "partial", "value": "not-a-date"}},
        headers=admin_auth_header,
    )
    assert invalid.status_code == 400, invalid.text
    persisted = await client.get(feature_url, headers=admin_auth_header)
    assert persisted.json()["properties"] == {"name": None, "value": next_value}

    cleared = await client.patch(
        feature_url, json={"properties": {"value": None}}, headers=admin_auth_header
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["properties"]["value"] is None


@pytest.mark.anyio
async def test_alter_column_type_invalid_type(
    client: AsyncClient, admin_auth_header: dict
):
    """Unknown type returns 422 (Pydantic validation)."""
    dataset_id = await _create_layer(client, admin_auth_header, title="Bad Type")

    resp = await client.patch(
        f"/layers/{dataset_id}/columns/value/type",
        json={"new_type": "bytea"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_rename_column_viewer_forbidden(
    client: AsyncClient, admin_auth_header: dict, viewer_auth_header: dict
):
    """Viewer cannot rename columns (403)."""
    dataset_id = await _create_layer(
        client, admin_auth_header, title="Viewer Rename Block"
    )

    resp = await client.patch(
        f"/layers/{dataset_id}/columns/value/name",
        json={"new_name": "amount"},
        headers=viewer_auth_header,
    )
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_column_ddl_invalidates_tile_cache(
    client: AsyncClient, admin_auth_header: dict, monkeypatch
):
    """fix(#458 E-05): every column DDL op purges the layer's cached tiles."""
    from unittest.mock import AsyncMock, MagicMock

    import app.modules.catalog.layers.router as layers_router

    mock_cache = MagicMock()
    mock_cache.invalidate_table = AsyncMock()
    monkeypatch.setattr(layers_router, "get_tile_cache", lambda: mock_cache)

    dataset_id = await _create_layer(client, admin_auth_header, title="Tile Purge Test")

    ops = [
        client.post(
            f"/layers/{dataset_id}/columns/",
            json={"column": {"name": "extra", "type": "text"}},
            headers=admin_auth_header,
        ),
        client.patch(
            f"/layers/{dataset_id}/columns/extra/name",
            json={"new_name": "extra2"},
            headers=admin_auth_header,
        ),
        client.patch(
            f"/layers/{dataset_id}/columns/value/type",
            json={"new_type": "integer"},
            headers=admin_auth_header,
        ),
        client.delete(
            f"/layers/{dataset_id}/columns/extra2",
            headers=admin_auth_header,
        ),
    ]
    for op in ops:
        resp = await op
        assert resp.status_code in (200, 201, 204), resp.text

    assert mock_cache.invalidate_table.await_count == 4


@pytest.mark.anyio
async def test_drop_readd_drop_same_column(
    client: AsyncClient, admin_auth_header: dict
):
    """fix(#458 E-12): dropping a re-added column must not 500 on the
    historical AttributeMetadata row left by the first drop."""
    dataset_id = await _create_layer(client, admin_auth_header, title="Drop Readd Test")

    for step in range(2):
        resp = await client.post(
            f"/layers/{dataset_id}/columns/",
            json={"column": {"name": "flaky", "type": "text"}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 201, f"add #{step}: {resp.text}"
        resp = await client.delete(
            f"/layers/{dataset_id}/columns/flaky",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, f"drop #{step}: {resp.text}"


@pytest.mark.anyio
async def test_column_references_counts_saved_maps(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    """fix(#458 E-06): the references probe counts maps whose layer config
    mentions the column, so the schema editor can warn before rename/drop."""
    import uuid as _uuid

    from app.modules.catalog.datasets.domain.models import Dataset
    from app.modules.catalog.maps.models import Map, MapLayer
    from tests.factories import get_user_id

    dataset_id = await _create_layer(client, admin_auth_header, title="Refs Test")

    admin_id = await get_user_id(test_db_session, "admin")
    dataset = await test_db_session.get(Dataset, _uuid.UUID(dataset_id))
    map_obj = Map(
        name=f"Refs Map {_uuid.uuid4().hex[:6]}",
        visibility="private",
        created_by=admin_id,
    )
    test_db_session.add(map_obj)
    await test_db_session.flush()
    test_db_session.add(
        MapLayer(
            map_id=map_obj.id,
            dataset_id=dataset.id,
            sort_order=0,
            style_config={"column": "value", "type": "categorical"},
        )
    )
    await test_db_session.commit()

    referenced = await client.get(
        f"/layers/{dataset_id}/columns/value/references",
        headers=admin_auth_header,
    )
    assert referenced.status_code == 200, referenced.text
    assert referenced.json()["map_count"] == 1

    unreferenced = await client.get(
        f"/layers/{dataset_id}/columns/name/references",
        headers=admin_auth_header,
    )
    assert unreferenced.status_code == 200
    assert unreferenced.json()["map_count"] == 0


@pytest.mark.anyio
async def test_reserved_word_column_full_ddl_lifecycle(
    client: AsyncClient, admin_auth_header: dict
):
    """fix(#458 E-33): SQL reserved words as column names (desc, order — routine
    ogr2ogr output from DBF fields) must survive every DDL op and the
    distinct-values probe; unquoted interpolation used to raise syntax errors."""
    dataset_id = await _create_layer(
        client, admin_auth_header, title="Reserved Word DDL"
    )

    resp = await client.post(
        f"/layers/{dataset_id}/columns/",
        json={"column": {"name": "desc", "type": "text"}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 201, resp.text
    assert "desc" in {c["name"] for c in resp.json()["columns"]}

    resp = await client.get(
        f"/datasets/{dataset_id}/columns/desc/values/",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text

    resp = await client.patch(
        f"/layers/{dataset_id}/columns/desc/type",
        json={"new_type": "integer"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text

    resp = await client.patch(
        f"/layers/{dataset_id}/columns/desc/name",
        json={"new_name": "order"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    assert "order" in {c["name"] for c in resp.json()["columns"]}

    resp = await client.delete(
        f"/layers/{dataset_id}/columns/order",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    assert "order" not in {c["name"] for c in resp.json()["columns"]}


@pytest.mark.anyio
async def test_column_ddl_recomputes_quality_detail(
    client: AsyncClient, admin_auth_header: dict
):
    """fix(#458 E-34): column DDL recomputes the stored quality score like
    reupload does; it used to stay stale until the next reupload."""
    dataset_id = await _create_layer(client, admin_auth_header, title="Quality Refresh")

    before = await client.get(f"/datasets/{dataset_id}", headers=admin_auth_header)
    assert before.status_code == 200
    computed_before = before.json()["quality_detail"]["computed_at"]

    resp = await client.post(
        f"/layers/{dataset_id}/columns/",
        json={"column": {"name": "extra", "type": "text"}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 201, resp.text

    after = await client.get(f"/datasets/{dataset_id}", headers=admin_auth_header)
    assert after.status_code == 200
    computed_after = after.json()["quality_detail"]["computed_at"]
    assert computed_after > computed_before


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH"])
async def test_timestamp_writes_preserve_offsets_and_reject_ambiguous_local_time(
    client: AsyncClient, admin_auth_header: dict, method: str
):
    dataset_id = await _create_layer(
        client, admin_auth_header, title=f"Offset {method}"
    )
    changed = await client.patch(
        f"/layers/{dataset_id}/columns/value/type",
        json={"new_type": "timestamp"},
        headers=admin_auth_header,
    )
    assert changed.status_code == 200, changed.text
    collection_url = f"/datasets/{dataset_id}/features/"
    body = {
        "geometry": {"type": "Point", "coordinates": [1, 2]},
        "properties": {"value": "2026-09-12T10:30:00-04:00"},
    }
    created = await client.post(collection_url, json=body, headers=admin_auth_header)
    assert created.status_code == 201, created.text
    feature_url = f"{collection_url}{created.json()['id']}"
    url = collection_url if method == "POST" else feature_url
    accepted = await client.request(method, url, json=body, headers=admin_auth_header)
    assert accepted.status_code == (201 if method == "POST" else 200), accepted.text
    assert accepted.json()["properties"]["value"] == "2026-09-12T14:30:00+00:00"

    body["properties"] = {"name": "must not persist", "value": "2026-09-12T10:30"}
    denied = await client.request(method, url, json=body, headers=admin_auth_header)
    assert denied.status_code == 400, denied.text
    assert "timezone offset" in denied.json()["detail"]
    persisted = await client.get(feature_url, headers=admin_auth_header)
    assert persisted.json()["properties"]["value"] == "2026-09-12T14:30:00+00:00"
    assert persisted.json()["properties"]["name"] is None

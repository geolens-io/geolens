"""A style's vector tile URL must fit the request line the bundled proxy accepts.

The URL names every column the source's layers read. Up to the proxy's limit it
keeps them all; past it the export leaves the list out, since a refused tile
draws nothing, and the tile server's zoom defaults then decide what a tile
carries.
"""

import re
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.config import settings
from app.modules.catalog.maps import style_json
from app.modules.catalog.maps.models import Map, MapLayer
from app.modules.catalog.maps.style_json import build_maplibre_style
from app.processing.tiles.service import _DEFAULT_NO_ATTR_BELOW_ZOOM
from app.processing.tiles.signing import verify_tile_signature
from tests.factories import create_dataset, get_user_id, set_tile_columns
from tests.repo_paths import repo_root
from tests.test_maps_style_json import _layer, _map
from tests.test_tile_cols_only import _decode_features
from tests.test_tiles import _cleanup_data_table, _create_data_table

LOW_ZOOM_TILE = "2/2/2"
HIGH_ZOOM_TILE = "12/2048/2048"
assert int(LOW_ZOOM_TILE.split("/")[0]) < _DEFAULT_NO_ATTR_BELOW_ZOOM
assert int(HIGH_ZOOM_TILE.split("/")[0]) >= _DEFAULT_NO_ATTR_BELOW_ZOOM


def _proxy_request_line_limit() -> int:
    """The longest request line frontend/nginx.conf accepts, in bytes."""
    conf = (repo_root(__file__) / "frontend" / "nginx.conf").read_text()
    [size] = re.findall(r"^large_client_header_buffers\s+\d+\s+(\d+)k;", conf, re.M)
    return int(size) * 1024


def _longest_request_line(tile_url: str) -> int:
    parts = urlsplit(tile_url)
    target = (
        f"{parts.path}?{parts.query}".replace("{z}", "22")
        .replace("{x}", "4194303")
        .replace("{y}", "4194303")
    )
    return len(f"GET {target} HTTP/1.1\r\n".encode())


def _long_column_names(count: int) -> list[str]:
    names = [f"c{i:03d}_{'x' * 48}" for i in range(count)]
    assert {len(name) for name in names} == {53}
    return names


def _exported_tile_url(names: list[str], per_layer: int = 8) -> str:
    """The tile URL of one dataset whose symbol layers each read `per_layer` columns."""
    dataset_id = uuid.uuid4()
    column_info = [{"name": name, "type": "text"} for name in names]
    layers = [
        _layer(
            dataset_id=dataset_id,
            sort_order=order,
            filter=None,
            label_config=None,
            dataset_column_info=column_info,
            style_config={"render_mode": "symbol"},
            paint={},
            layout={
                "text-field": [
                    "concat",
                    *(["get", name] for name in names[start : start + per_layer]),
                ]
            },
        )
        for order, start in enumerate(range(0, len(names), per_layer))
    ]
    style = build_maplibre_style(_map(), layers, api_url="https://maps.example.org/api")
    [url] = style["sources"][f"geolens-{dataset_id}"]["tiles"]
    return url


def _cols(tile_url: str) -> list[str] | None:
    value = parse_qs(urlsplit(tile_url).query).get("cols")
    return value[0].split(",") if value else None


def test_the_export_budget_is_below_the_request_line_the_bundled_proxy_accepts():
    assert style_json._TILE_REQUEST_LINE_BUDGET < _proxy_request_line_limit()


def test_twenty_layers_reading_eight_long_columns_each_keep_every_column():
    names = _long_column_names(160)

    url = _exported_tile_url(names)

    assert _cols(url) == names
    # Longer than nginx's 8k default, which is why the bundled proxy raises it.
    assert 8 * 1024 < _longest_request_line(url) <= _proxy_request_line_limit()


def test_a_column_list_too_long_for_a_request_line_is_left_out_of_the_url():
    url = _exported_tile_url(_long_column_names(320))

    assert _cols(url) is None
    assert _longest_request_line(url) <= _proxy_request_line_limit()
    query = parse_qs(urlsplit(url).query)
    assert verify_tile_signature(
        query["scope"][0], int(query["exp"][0]), query["sig"][0]
    )


def test_a_small_style_keeps_its_sorted_column_list():
    url = _exported_tile_url(["name", "category"], per_layer=1)

    assert url.endswith("&cols=category%2Cname")


async def _map_reading_name_and_value(
    session, *, tile_columns: list[str] | None = None
) -> tuple[Map, str]:
    """A private map whose one layer reads `name` and `value` from a private dataset."""
    admin_id = await get_user_id(session, settings.geolens_admin_username)
    table = f"tile_url_{uuid.uuid4().hex[:8]}"
    dataset = await create_dataset(
        session,
        created_by=admin_id,
        table_name=table,
        visibility="private",
        geometry_type="Point",
        feature_count=1,
        column_info=[
            {"name": "gid", "type": "integer"},
            {"name": "name", "type": "text"},
            {"name": "value", "type": "integer"},
            {"name": "geom", "type": "geometry"},
            {"name": "geom_4326", "type": "geometry"},
        ],
    )
    await _create_data_table(session, table)
    # Off the tile corner, so exactly one tile per zoom holds the point.
    await session.execute(
        text(
            f"UPDATE data.{table} SET "
            "geom_4326 = ST_SetSRID(ST_MakePoint(0.02, -0.02), 4326), "
            "geom = ST_Transform(ST_SetSRID(ST_MakePoint(0.02, -0.02), 4326), 3857)"
        )
    )
    map_obj = Map(
        name=f"Tile URL {uuid.uuid4().hex[:6]}",
        visibility="private",
        created_by=admin_id,
    )
    session.add(map_obj)
    await session.flush()
    session.add(
        MapLayer(
            map_id=map_obj.id,
            dataset_id=dataset.id,
            sort_order=0,
            paint={
                "circle-color": ["match", ["get", "value"], 42, "#111111", "#222222"]
            },
            label_config={"column": "name"},
        )
    )
    await session.commit()
    if tile_columns is not None:
        await set_tile_columns(session, dataset.id, tile_columns)
    return map_obj, table


async def _exported_tile_path(client, headers, map_obj: Map, table: str) -> str:
    """The exported tile URL's path and query, as the test client routes them."""
    resp = await client.get(f"/maps/{map_obj.id}/style.json", headers=headers)
    assert resp.status_code == 200, resp.text
    [url] = [
        source["tiles"][0]
        for source in resp.json()["sources"].values()
        if table in source["tiles"][0]
    ]
    parts = urlsplit(url)
    return f"{parts.path[parts.path.index('/tiles/') :]}?{parts.query}"


async def _attributes(client, tile_path: str, tile: str, headers=None) -> set[str]:
    """The attribute names on the one feature of an anonymous tile request."""
    resp = await client.get(
        tile_path.replace("{z}/{x}/{y}", tile), headers=headers or {}
    )
    assert resp.status_code == 200, resp.text
    [attributes] = _decode_features(resp.content).values()
    return attributes


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
async def test_the_signed_url_without_a_column_list_serves_tiles_with_the_zoom_defaults(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
):
    map_obj, table = await _map_reading_name_and_value(test_db_session)
    try:
        with_cols = await _exported_tile_path(client, admin_auth_header, map_obj, table)
        monkeypatch.setattr(style_json, "_TILE_REQUEST_LINE_BUDGET", 0)
        without_cols = await _exported_tile_path(
            client, admin_auth_header, map_obj, table
        )

        assert _cols(with_cols) == ["name", "value"]
        assert _cols(without_cols) is None
        assert await _attributes(client, with_cols, LOW_ZOOM_TILE) >= {"name", "value"}
        # The dataset is private, so the signature alone admits these requests.
        assert await _attributes(client, without_cols, HIGH_ZOOM_TILE) >= {
            "name",
            "value",
        }
        assert not await _attributes(client, without_cols, LOW_ZOOM_TILE) & {
            "name",
            "value",
        }
    finally:
        await _cleanup_data_table(test_db_session, table)


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
@pytest.mark.parametrize("tile", [LOW_ZOOM_TILE, HIGH_ZOOM_TILE])
async def test_the_url_without_a_column_list_stays_inside_the_tile_column_allowlist(
    client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch, tile
):
    map_obj, table = await _map_reading_name_and_value(
        test_db_session, tile_columns=["name"]
    )
    try:
        embed = await client.post(
            f"/maps/{map_obj.id}/embed-tokens/", json={}, headers=admin_auth_header
        )
        assert embed.status_code == 201, embed.text
        embed_header = {"X-Embed-Token": embed.json()["raw_token"]}
        monkeypatch.setattr(style_json, "_TILE_REQUEST_LINE_BUDGET", 0)
        signed = await _exported_tile_path(client, admin_auth_header, map_obj, table)
        unsigned = signed.split("?")[0] + "?"

        assert _cols(signed) is None
        assert await _attributes(client, signed, tile) == {"name"}
        assert await _attributes(client, unsigned, tile, embed_header) == {"name"}
    finally:
        await _cleanup_data_table(test_db_session, table)

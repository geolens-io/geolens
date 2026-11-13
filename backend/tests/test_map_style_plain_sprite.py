"""`GET /maps/{id}/style.json?sprite=url` writes the string sprite form.

Clients that know only the style spec's string `sprite` (Esri's vector tile
layer) fail on the array form. With `sprite=url` the document names a second
sprite whose entries carry the `geolens:` prefix, so every image name stays
as the default export writes it.
"""

import copy
import time
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.modules.catalog.maps.models import Map
from app.modules.catalog.maps.style_json import (
    build_maplibre_style,
    parse_maplibre_style_import,
)

from tests.factories import create_dataset, get_user_id
from tests.test_maps_style_json import _layer, _map

pytestmark = pytest.mark.anyio

_SYMBOL = {
    "render_mode": "symbol",
    "symbol": {
        "iconImage": "marker",
        "categoryColumn": "kind",
        "categories": [
            {"value": "stop", "icon": "circle-dot"},
            {"value": "station", "icon": "arrow-right"},
        ],
    },
}
_STEP_SYMBOL = {
    "render_mode": "symbol",
    "symbol": {
        "iconImage": ["step", ["zoom"], "geolens:marker", 10, "geolens:circle-dot"]
    },
}
_ARROW = {"render_mode": "arrow", "builder": {"arrowSize": 14}}


@pytest.fixture(autouse=True)
def _one_signing_window(monkeypatch):
    """Two exports compared for equality sign their tile URLs with one expiry,
    whichever side of a signing-window boundary each is built on."""
    expiry = (int(time.time()) // 900 + 2) * 900
    monkeypatch.setattr(
        "app.processing.tiles.signing.round_expiry", lambda *args, **kwargs: expiry
    )


def _icon_names(icon_image) -> list[str]:
    """The icon names an `icon-image` value can resolve to: a literal, or a
    `match` expression's outputs (its labels are feature values)."""
    if isinstance(icon_image, str):
        return [icon_image]
    assert icon_image[0] == "match", icon_image
    outputs = icon_image[3:-1:2] + [icon_image[-1]]
    return [name for output in outputs for name in _icon_names(output)]


def _icon_images(style: dict) -> list:
    return [
        layer["layout"]["icon-image"]
        for layer in style["layers"]
        if "icon-image" in layer.get("layout", {})
    ]


def _without_sprite(style: dict) -> dict:
    return {key: value for key, value in style.items() if key != "sprite"}


def _layers():
    return [
        _layer(style_config=_SYMBOL, label_config=None),
        _layer(style_config=_STEP_SYMBOL, label_config=None),
        _layer(
            dataset_geometry_type="LineString",
            paint={"line-color": "#2255aa", "line-width": 3},
            label_config=None,
            style_config=_ARROW,
        ),
        _layer(
            dataset_geometry_type="MultiPolygon",
            paint={"fill-pattern": "geolens:marker", "fill-color": "#2255aa"},
            label_config=None,
        ),
    ]


def test_default_export_keeps_the_array_form_and_prefixed_icons():
    style = build_maplibre_style(_map(), _layers())

    assert style["sprite"] == [{"id": "geolens", "url": "/maps/sprites/geolens"}]
    names = [n for icon in _icon_images(style)[:1] for n in _icon_names(icon)]
    assert sorted(names) == [
        "geolens:arrow-right",
        "geolens:circle-dot",
        "geolens:marker",
    ]


def test_plain_sprite_export_changes_only_the_sprite():
    layers, map_obj = _layers(), _map()
    default = build_maplibre_style(map_obj, layers)
    plain = build_maplibre_style(map_obj, layers, plain_sprite=True)

    assert plain["sprite"] == "/maps/sprites/geolens-prefixed"
    assert _without_sprite(plain) == _without_sprite(default)


@pytest.mark.parametrize("keep_metadata", [True, False])
def test_plain_sprite_export_imports_like_the_array_form(keep_metadata: bool):
    layers, map_obj = _layers(), _map()
    documents = [
        copy.deepcopy(build_maplibre_style(map_obj, layers, plain_sprite=plain))
        for plain in (False, True)
    ]
    if not keep_metadata:
        # Without GeoLens metadata the importer reads the layer properties.
        for document in documents:
            for layer in document["layers"]:
                layer.get("metadata", {}).get("geolens", {}).pop("style_config", None)

    array_layers, plain_layers = (
        [layer.model_dump() for layer in parse_maplibre_style_import(doc).layers]
        for doc in documents
    )

    assert plain_layers == array_layers
    assert len(plain_layers) == len(layers)


async def _map_of(
    client: AsyncClient,
    headers: dict,
    session,
    layers: list[tuple[str, dict]],
    visibility: str = "public",
) -> str:
    """A map with one layer per (geometry, layer patch), set through the API."""
    admin_id = await get_user_id(session, "admin")
    created = await client.post(
        "/maps/", json={"name": f"Sprite {uuid.uuid4().hex[:6]}"}, headers=headers
    )
    assert created.status_code == 201, created.text
    map_id = created.json()["id"]
    for geometry, patch in layers:
        dataset = await create_dataset(
            session, created_by=admin_id, geometry_type=geometry, visibility="public"
        )
        added = await client.post(
            f"/maps/{map_id}/layers",
            json={"dataset_id": str(dataset.id)},
            headers=headers,
        )
        assert added.status_code == 201, added.text
        patched = await client.patch(
            f"/maps/{map_id}/layers",
            json={"updated": [{"id": added.json()["id"], **patch}]},
            headers=headers,
        )
        assert patched.status_code == 200, patched.text
    await session.execute(
        update(Map).where(Map.id == uuid.UUID(map_id)).values(visibility=visibility)
    )
    await session.commit()
    return map_id


class TestStyleJsonSpriteParameter:
    async def _map_with_icons(
        self, client: AsyncClient, headers: dict, session, visibility: str
    ) -> str:
        return await _map_of(
            client,
            headers,
            session,
            [
                ("Point", {"style_config": _SYMBOL, "label_config": None}),
                ("Point", {"style_config": _STEP_SYMBOL, "label_config": None}),
                ("LineString", {"style_config": _ARROW}),
            ],
            visibility=visibility,
        )

    async def test_url_form_changes_only_the_sprite(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        map_id = await self._map_with_icons(
            client, admin_auth_header, test_db_session, "public"
        )

        default = await client.get(f"/maps/{map_id}/style.json")
        plain = await client.get(f"/maps/{map_id}/style.json", params={"sprite": "url"})
        head = await client.head(f"/maps/{map_id}/style.json", params={"sprite": "url"})

        assert default.status_code == plain.status_code == head.status_code == 200
        assert default.json()["sprite"][0]["id"] == "geolens"
        assert plain.json()["sprite"].endswith("/maps/sprites/geolens-prefixed")
        assert _without_sprite(plain.json()) == _without_sprite(default.json())

    async def test_url_form_icon_names_are_entries_of_its_sprite(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        map_id = await self._map_with_icons(
            client, admin_auth_header, test_db_session, "public"
        )

        style = (
            await client.get(f"/maps/{map_id}/style.json", params={"sprite": "url"})
        ).json()
        sprite_path = style["sprite"][style["sprite"].index("/maps/sprites/") :]
        index = (await client.get(f"{sprite_path}.json")).json()

        icons = _icon_images(style)
        names = {n for icon in icons if icon[0] != "step" for n in _icon_names(icon)}
        names |= {"geolens:marker", "geolens:circle-dot"}  # the step outputs
        assert ["step", ["zoom"], "geolens:marker", 10, "geolens:circle-dot"] in icons
        assert names == {"geolens:marker", "geolens:circle-dot", "geolens:arrow-right"}
        assert names <= set(index)

    async def test_url_form_imports_to_the_layers_the_array_form_does(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        map_id = await self._map_with_icons(
            client, admin_auth_header, test_db_session, "public"
        )
        stored = []
        for params in ({}, {"sprite": "url"}):
            style = await client.get(f"/maps/{map_id}/style.json", params=params)
            imported = await client.post(
                "/maps/import", json=style.json(), headers=admin_auth_header
            )
            assert imported.status_code == 201, imported.text
            stored.append(
                [
                    {k: layer[k] for k in ("paint", "layout", "style_config")}
                    for layer in imported.json()["map"]["layers"]
                ]
            )

        assert stored[0] == stored[1]
        assert len(stored[0]) == 3

    @pytest.mark.parametrize("value", ["array", "", "URL"])
    async def test_an_unknown_form_is_refused(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, value
    ):
        map_id = await self._map_with_icons(
            client, admin_auth_header, test_db_session, "public"
        )

        resp = await client.get(f"/maps/{map_id}/style.json", params={"sprite": value})

        assert resp.status_code == 422, resp.text
        assert "sprite" in resp.json()["detail"]

    async def test_url_form_keeps_the_access_check(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        map_id = await self._map_with_icons(
            client, admin_auth_header, test_db_session, "private"
        )

        anonymous = await client.get(
            f"/maps/{map_id}/style.json", params={"sprite": "url"}
        )
        owner = await client.get(
            f"/maps/{map_id}/style.json",
            params={"sprite": "url"},
            headers=admin_auth_header,
        )

        assert anonymous.status_code == 404
        assert owner.status_code == 200, owner.text
        assert isinstance(owner.json()["sprite"], str)


@pytest.mark.parametrize("scale", ["", "@2x"])
async def test_prefixed_index_is_the_plain_index_with_prefixed_names(
    client: AsyncClient, scale: str
):
    plain = await client.get(f"/maps/sprites/geolens{scale}.json")
    prefixed = await client.get(f"/maps/sprites/geolens-prefixed{scale}.json")

    assert plain.status_code == prefixed.status_code == 200
    assert prefixed.json() == {
        f"geolens:{name}": entry for name, entry in plain.json().items()
    }


@pytest.mark.parametrize("name", ["", "@2x"])
@pytest.mark.parametrize("ext", ["json", "png"])
async def test_prefixed_sprite_routes_answer_like_the_plain_ones(
    client: AsyncClient, name: str, ext: str
):
    plain = await client.get(f"/maps/sprites/geolens{name}.{ext}")
    prefixed = await client.get(f"/maps/sprites/geolens-prefixed{name}.{ext}")

    assert prefixed.status_code == plain.status_code == 200
    for header in ("content-type", "cache-control"):
        assert prefixed.headers.get(header) == plain.headers.get(header), header
    if ext == "png":
        assert prefixed.content == plain.content

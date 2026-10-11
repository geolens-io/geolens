"""Pins the vocabulary desktop GIS plugins send when publishing a map.

Plugins write ``MapLayerInput`` rows through ``POST /maps/`` and
``PUT /maps/{id}``, so the keys that survive the style sanitizers are a public
contract. ``fixtures/publish_contract_v1.json`` is the frozen list. Changing it
is a contract version bump: bump ``contract_version`` and update the
"Publishing maps from a desktop GIS" page in the same change.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.maps import schemas
from app.modules.catalog.maps import publish_vocabulary as vocabulary
from app.modules.catalog.maps import style_sanitizers as sanitizers
from tests.factories import create_dataset, get_user_id

FIXTURE = Path(__file__).parent / "fixtures" / "publish_contract_v1.json"


def _snapshot() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _layer_type_pattern() -> str | None:
    for meta in schemas.MapLayerInput.model_fields["layer_type"].metadata:
        pattern = getattr(meta, "pattern", None)
        if pattern:
            return pattern
    return None


def _live() -> dict[str, object]:
    return {
        "style_config_keys": sorted(vocabulary.STYLE_METADATA_KEYS),
        "label_config_keys": sorted(vocabulary.LABEL_METADATA_KEYS),
        "symbol_keys": sorted(vocabulary.SYMBOL_METADATA_KEYS),
        "label_config_fields": sorted(schemas.LabelConfig.model_fields),
        "popup_config_fields": sorted(schemas.PopupConfig.model_fields),
        "map_layer_input_fields": sorted(schemas.MapLayerInput.model_fields),
        "layer_type_pattern": _layer_type_pattern(),
        "builder_keys": sorted(vocabulary.BUILDER_STYLE_KEYS),
        "builder_keys_accepted_camel_case": sorted(
            schemas._BUILDER_CAMEL_TO_SNAKE_KEYS
        ),
    }


@pytest.mark.parametrize("name", sorted(_live()))
def test_vocabulary_matches_frozen_snapshot(name: str) -> None:
    frozen = _snapshot()[name]
    live = _live()[name]
    assert live == frozen, (
        f"{name} drifted from publish_contract_v1.json. Desktop GIS plugins "
        "depend on this vocabulary: bump contract_version, update the "
        "snapshot and the publishing docs page together."
    )


def test_builder_vocabulary_covers_every_alias_and_legacy_target() -> None:
    known = set(vocabulary.BUILDER_STYLE_KEYS)
    assert set(schemas._BUILDER_CAMEL_TO_SNAKE_KEYS.values()) <= known
    assert set(schemas.LEGACY_BUILDER_PAINT_KEYS.values()) <= known


def test_builder_keys_survive_style_export() -> None:
    builder = {key: 1 for key in vocabulary.BUILDER_STYLE_KEYS}
    builder["lineGradient"] = {
        "stops": [{"position": 0, "color": "#000000"}, {"position": 1, "color": "#fff"}]
    }
    builder["symbol"] = {"iconImage": "marker"}
    builder["cluster_color_ramp"] = [{"count": 10, "color": "#123456"}]
    exported = sanitizers.clean_style_metadata({"builder": builder})["builder"]
    camel = schemas.BUILDER_SNAKE_TO_CAMEL_KEYS
    assert set(exported) == {camel.get(key, key) for key in builder}
    assert exported["lineGradient"] == builder["lineGradient"]
    assert exported["clusterColorRamp"] == builder["cluster_color_ramp"]


def test_openapi_descriptions_list_the_accepted_keys() -> None:
    props = schemas.MapLayerInput.model_json_schema()["properties"]
    style = props["style_config"]["description"]
    label = props["label_config"]["description"]
    for key in vocabulary.STYLE_METADATA_KEYS | vocabulary.BUILDER_STYLE_KEYS:
        assert key in style
    for key in vocabulary.LABEL_METADATA_KEYS:
        assert key in label
    assert vocabulary.PUBLISHING_GUIDE_URL in style
    assert vocabulary.PUBLISHING_GUIDE_URL in label


# Shapes exactly as 04-style-mapping prescribes for a QGIS categorized layer.
_CATEGORIES = [
    {"value": "residential", "label": "Residential", "color": "#e41a1c"},
    {"value": "commercial", "label": "Commercial", "color": "#377eb8"},
    {"value": "industrial", "label": "Industrial", "color": "#4daf4a"},
]


def _categorized_layer(dataset_id: str) -> dict:
    match = ["match", ["get", "landuse"]]
    for cat in _CATEGORIES:
        match += [cat["value"], cat["color"]]
    match.append("#999999")
    return {
        "dataset_id": dataset_id,
        "display_name": "Land use",
        "sort_order": 0,
        "visible": True,
        "opacity": 1.0,
        "layer_type": "vector_geolens",
        "paint": {"fill-color": match, "fill-opacity": 0.8},
        "layout": {"_minzoom": 4, "_maxzoom": 18},
        "style_config": {
            "mode": "categorical",
            "column": "landuse",
            "categories": _CATEGORIES,
            "legendLabel": "Land use",
            "builder": {"outlineColor": "#222222", "outlineWidth": 1},
        },
        "label_config": {
            "column": "landuse",
            "fontSize": 12,
            "textColor": "#111111",
            "haloColor": "#ffffff",
            "haloWidth": 1.5,
            "minZoom": 8,
            "placement": "point",
        },
        "popup_config": {"enabled": True, "visible_fields": ["landuse", "name"]},
        "show_in_legend": True,
    }


class TestPublishRoundTrip:
    async def test_post_then_put_keeps_legend_facts(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session: AsyncSession,
    ) -> None:
        admin_id = await get_user_id(test_db_session, "admin")
        ds = await create_dataset(
            test_db_session,
            created_by=admin_id,
            geometry_type="MultiPolygon",
            column_info=[
                {"name": "landuse", "type": "text"},
                {"name": "name", "type": "text"},
            ],
        )
        layer = _categorized_layer(str(ds.id))

        created = await client.post(
            "/maps/",
            json={"name": f"Publish contract {uuid.uuid4().hex[:6]}"},
            headers=admin_auth_header,
        )
        assert created.status_code == 201, created.text
        map_id = created.json()["id"]

        # A republish sends the same PUT again and replaces every layer.
        for _ in range(2):
            put = await client.put(
                f"/maps/{map_id}",
                json={"visibility": "private", "layers": [layer]},
                headers=admin_auth_header,
            )
            assert put.status_code == 200, put.text

        got = await client.get(f"/maps/{map_id}", headers=admin_auth_header)
        assert got.status_code == 200, got.text
        layers = got.json()["layers"]
        assert len(layers) == 1
        stored = layers[0]
        assert stored["layer_type"] == "vector_geolens"
        assert stored["style_config"]["mode"] == "categorical"
        assert stored["style_config"]["column"] == "landuse"
        assert stored["style_config"]["categories"] == _CATEGORIES
        assert stored["style_config"]["builder"]["outline_color"] == "#222222"
        assert stored["label_config"]["column"] == "landuse"
        assert stored["popup_config"]["visible_fields"] == ["landuse", "name"]

        style = await client.get(
            f"/maps/{map_id}/style.json", headers=admin_auth_header
        )
        assert style.status_code == 200, style.text
        meta = next(
            lyr["metadata"]["geolens"]
            for lyr in style.json()["layers"]
            if "geolens" in (lyr.get("metadata") or {})
        )
        exported = meta["style_config"]["categories"]
        assert [c["label"] for c in exported] == [c["label"] for c in _CATEGORIES]
        assert meta["label_config"]["column"] == "landuse"
        assert meta["popup_config"]["visible_fields"] == ["landuse", "name"]
        assert meta["show_in_legend"] is True

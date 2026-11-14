"""Layer bodies the Python SDK builds pass a map_author key; one non-default refused field does not."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient

from tests import test_api_key_dataset_scope as _dataset_scope
from tests.test_api_key_map_author_scope import (
    PAINT,
    _authored_map,
    _key_header,
    _mint,
)

_SDK_PY_PATH = Path(__file__).resolve().parents[2] / "sdks" / "python"
# The api container mounts backend/ only; host and CI checkouts have the SDK.
if not (_SDK_PY_PATH / "geolens" / "auth.py").is_file():
    pytest.skip("geolens SDK source tree not present", allow_module_level=True)
if str(_SDK_PY_PATH) not in sys.path:
    sys.path.insert(0, str(_SDK_PY_PATH))

from geolens.models.map_layer_diff_request import MapLayerDiffRequest  # noqa: E402
from geolens.models.map_layer_input import MapLayerInput  # noqa: E402
from geolens.models.map_layer_input_paint_type_0 import (  # noqa: E402
    MapLayerInputPaintType0,
)
from geolens.models.map_layer_patch import MapLayerPatch  # noqa: E402
from geolens.models.map_layer_patch_paint_type_0 import (  # noqa: E402
    MapLayerPatchPaintType0,
)

owner = _dataset_scope.owner
datasets = _dataset_scope.datasets
_remove_keys_minted_by_the_test = _dataset_scope._remove_keys_minted_by_the_test


def _new_layer(dataset_id, **extra) -> MapLayerInput:
    return MapLayerInput(
        dataset_id=dataset_id,
        paint=MapLayerInputPaintType0.from_dict(PAINT),
        **extra,
    )


def _style_update(layer_id) -> MapLayerPatch:
    return MapLayerPatch(
        id=uuid.UUID(layer_id),
        paint=MapLayerPatchPaintType0.from_dict({"circle-color": "#aa3300"}),
    )


def test_the_sdk_sends_defaults_nobody_asked_for():
    sent = _new_layer(uuid.uuid4()).to_dict()
    assert {"sort_order", "visible", "opacity", "show_in_legend"} <= set(sent)
    assert "fallback_full_replace" in MapLayerDiffRequest().to_dict()
    assert set(_style_update(str(uuid.uuid4())).to_dict()) == {"id", "paint"}


@pytest.mark.anyio
async def test_sdk_layer_bodies_pass_and_a_non_default_field_is_refused(
    client: AsyncClient, owner, datasets
):
    headers, _ = owner
    key = await _mint(client, headers, "map_author")
    author = _key_header(key)
    map_id, layer_id = await _authored_map(client, key, datasets[0])
    layers_url = f"/maps/{map_id}/layers"
    dataset_id = datasets[1].id

    accepted = [
        ("POST", _new_layer(dataset_id).to_dict()),
        ("PATCH", MapLayerDiffRequest(added=[_new_layer(dataset_id)]).to_dict()),
        ("PATCH", MapLayerDiffRequest(updated=[_style_update(layer_id)]).to_dict()),
    ]
    for method, body in accepted:
        resp = await client.request(method, layers_url, json=body, headers=author)
        assert resp.status_code in (200, 201), (method, body, resp.text)

    refused = [
        ("POST", _new_layer(dataset_id, visible=False).to_dict(), "visible"),
        (
            "PATCH",
            MapLayerDiffRequest(added=[_new_layer(dataset_id, opacity=0.5)]).to_dict(),
            "opacity",
        ),
        (
            "PATCH",
            MapLayerDiffRequest(
                updated=[_style_update(layer_id)], fallback_full_replace=True
            ).to_dict(),
            "fallback_full_replace",
        ),
    ]
    for method, body, field in refused:
        resp = await client.request(method, layers_url, json=body, headers=author)
        assert resp.status_code == 403, (method, body, resp.text)
        assert resp.json()["detail"]["message"] == f"A map_author key can't set {field}"

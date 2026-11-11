"""The showcase 3D Tiles root refines from a distance and keeps its children."""

import importlib.util
import math
import pytest

from tests.repo_paths import repo_root

_PATH = repo_root(__file__) / "scripts" / "prepare-showcase-tiles3d.py"
_SPEC = importlib.util.spec_from_file_location("prepare_showcase_tiles3d", _PATH)
prepare = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(prepare)

_CHILDREN = [{"geometricError": 0.0, "content": {"uri": "t/9/428/600.glb"}}]


def _tile(volume: dict) -> dict:
    return {"boundingVolume": volume, "geometricError": 33.41, "children": _CHILDREN}


def test_root_and_tileset_error_equal_the_box_bounding_radius():
    box = [100.0, 200.0, 300.0, 3.0, 0.0, 0.0, 0.0, 4.0, 0.0, 0.0, 0.0, 12.0]
    source = {"asset": {"version": "1.1"}}

    result = prepare.rooted_tileset(source, _tile({"box": box}))

    radius = round(math.sqrt(9 + 16 + 144), 2)
    assert result["geometricError"] == radius == 13.0
    assert result["root"]["geometricError"] == radius
    assert result["root"]["children"] == _CHILDREN
    assert result["root"]["boundingVolume"] == {"box": box}
    assert result["asset"] == source["asset"]


def test_a_root_without_a_box_is_refused():
    with pytest.raises(ValueError, match="box"):
        prepare.rooted_tileset({"asset": {}}, _tile({"sphere": [0, 0, 0, 5]}))

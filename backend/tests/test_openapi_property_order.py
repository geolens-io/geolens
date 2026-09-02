"""fix(#1257): schema property order must follow Pydantic declaration order.

openapi-python-client derives generated constructor argument order from each
schema's ``properties`` insertion order. ``sort_keys=True`` alphabetized it,
so adding an optional field silently reordered positional arguments for SDK
consumers (v1.10.0: ``bbox`` displaced ``distance_meters`` in
``AnalysisPreviewRequest``). These tests pin the serializer contract for both
snapshot writers.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from app.api.main import app
from app.modules.catalog.datasets.domain.schemas import AnalysisPreviewRequest
from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)
BACKEND_ROOT = REPO_ROOT / "backend"


def _load_by_path(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dump_openapi = _load_by_path(
    "dump_openapi_under_test", BACKEND_ROOT / "scripts" / "dump_openapi.py"
)
flatten_defs = _load_by_path(
    "flatten_defs_under_test", REPO_ROOT / "scripts" / "flatten_openapi_defs.py"
)

SAMPLE = {
    "zeta": 1,
    "components": {
        "schemas": {
            "Thing": {
                "type": "object",
                "title": "Thing",
                "properties": {
                    "operation": {"type": "string"},
                    "distance_meters": {"type": "number", "title": "Zz"},
                    "bbox": {
                        "type": "object",
                        # a property's own schema is still sorted...
                        "title": "BBox",
                        "properties": {
                            # ...but nested properties maps are preserved too
                            "xmax": {"type": "number"},
                            "xmin": {"type": "number"},
                        },
                    },
                },
            }
        }
    },
    "alpha": [{"b": 1, "a": 2}],
}


def test_ordered_for_snapshot_preserves_properties_and_sorts_the_rest():
    ordered = dump_openapi.ordered_for_snapshot(SAMPLE)

    assert list(ordered) == ["alpha", "components", "zeta"]
    thing = ordered["components"]["schemas"]["Thing"]
    assert list(thing) == ["properties", "title", "type"]
    assert list(thing["properties"]) == ["operation", "distance_meters", "bbox"]
    bbox = thing["properties"]["bbox"]
    assert list(bbox) == ["properties", "title", "type"]
    assert list(bbox["properties"]) == ["xmax", "xmin"]
    assert list(ordered["alpha"][0]) == ["a", "b"]


def test_flatten_serializer_mirrors_dump_openapi():
    assert flatten_defs._ordered_for_snapshot(
        SAMPLE
    ) == dump_openapi.ordered_for_snapshot(SAMPLE)


def test_dumped_spec_property_order_matches_pydantic_declaration():
    app.openapi_schema = None
    spec = json.loads(dump_openapi._dump(app.openapi()))

    schema = spec["components"]["schemas"]["AnalysisPreviewRequest"]
    declared = list(AnalysisPreviewRequest.model_fields)
    assert list(schema["properties"]) == declared
    # The v1.10.0 regression shape: alphabetization pulled `bbox` ahead of
    # `distance_meters`; declaration order keeps it where the model says.
    assert declared.index("bbox") > declared.index("distance_meters")

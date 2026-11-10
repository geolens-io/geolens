"""The generated Python SDK reads what the dashboard widget schemas write."""

import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from app.modules.catalog.widgets.schemas import DashboardWidgets

_SDK_PATH = Path(__file__).resolve().parents[2] / "sdks" / "python"
if not _SDK_PATH.is_dir():
    pytest.skip("sdks/python is not available", allow_module_level=True)
if str(_SDK_PATH) not in sys.path:
    sys.path.insert(0, str(_SDK_PATH))

from geolens.models.dashboard_config import DashboardConfig  # noqa: E402

LAYER = str(uuid.uuid4())


def _rendered(config_type: str, config: dict[str, Any]) -> dict[str, Any]:
    widget = {
        "id": str(uuid.uuid4()),
        "type": config_type,
        "v": 1,
        "layer_id": LAYER,
        "config": config,
    }
    (parsed,) = TypeAdapter(DashboardWidgets).validate_python([widget])
    return {
        "version": 1,
        "panel": "right",
        "map_hidden": False,
        "theme": "follow",
        "widgets": [parsed.model_dump(mode="json")],
    }


@pytest.mark.parametrize("sort_by", [None, 0, 1, 2, 3, 4])
def test_a_table_sort_by_round_trips(sort_by: int | None) -> None:
    body = _rendered(
        "table",
        {"group_column": "g", "stats": [{"stat": "count"}] * 5, "sort_by": sort_by},
    )
    out = DashboardConfig.from_dict(body).to_dict()["widgets"][0]
    assert out["config"]["sort_by"] == sort_by


def test_a_v2_bar_chart_round_trips() -> None:
    body = _rendered("bar_chart", {"mode": "by_fields", "fields": ["a", "b"]})
    out = DashboardConfig.from_dict(body).to_dict()["widgets"][0]
    assert out["v"] == 2
    assert out["config"]["mode"] == "by_fields"
    assert out["config"]["fields"] == ["a", "b"]

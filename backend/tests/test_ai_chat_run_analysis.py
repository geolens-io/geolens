"""Tests for the AI-chat ``run_analysis`` tool (M4 Phase 5).

The tool lets the chat model run a parameterized PostGIS preview on a map
layer, reusing the catalog analysis service through ProcessingPort. Two things
matter most and are pinned here:

1. Access control — the layer list is CLIENT-supplied, so a caller must not be
   able to analyze a dataset they cannot read by naming it in ``layers``.
2. Tool-set scoping — ``run_analysis`` is read-only (belongs in the view-only
   toolbox) but map-only (must not reach the map-less dataset-chat surface).

Requirements:
  - Docker database must be running (docker compose up db)
"""

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.auth.models import User
from app.processing.ai.chat_actions import _collect_chat_action
from app.processing.ai.chat_analysis import handle_run_analysis as _handle_run_analysis
from app.processing.ai.schemas import ChatAction, ChatMapLayer
from app.processing.ai.tools import (
    CHAT_TOOLS_ANTHROPIC,
    CHAT_TOOLS_READONLY,
    select_chat_tools,
)
from app.platform.ai_tool_payloads import model_safe_tool_result
from app.platform.extensions.defaults import DefaultProcessingPort

from tests.factories import create_dataset

SQUARE = "POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))"

_default_port = DefaultProcessingPort()


async def _get_admin(session: AsyncSession) -> User:
    result = await session.execute(
        select(User).where(User.username == settings.geolens_admin_username)
    )
    return result.scalar_one()


async def _create_other_user(session: AsyncSession) -> User:
    """A second, non-admin user with no grants on the admin's datasets."""
    other = User(
        username=f"analysis_chat_{uuid.uuid4().hex[:8]}",
        password_hash="unused",
        is_active=True,
    )
    session.add(other)
    await session.flush()
    await session.commit()
    await session.refresh(other)
    return other


async def _create_polygon_dataset(
    session: AsyncSession,
    *,
    created_by: uuid.UUID,
    visibility: str = "public",
):
    """Create a real data table with one polygon + its catalog rows."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table_name} ("
            f"  gid SERIAL PRIMARY KEY,"
            f"  geom geometry(Polygon, 4326),"
            f"  geom_4326 geometry(Polygon, 4326)"
            f")"
        )
    )
    await session.execute(
        text(
            f"INSERT INTO data.{table_name} (geom, geom_4326) VALUES "
            f"(ST_GeomFromText('{SQUARE}', 4326),"
            f" ST_GeomFromText('{SQUARE}', 4326))"
        )
    )
    await session.commit()
    return await create_dataset(
        session,
        created_by=created_by,
        table_name=table_name,
        geometry_type="POLYGON",
        feature_count=1,
        visibility=visibility,
    )


def _layer_for(dataset, layer_id: str = "layer-1") -> ChatMapLayer:
    return ChatMapLayer(
        id=layer_id,
        name="Squares",
        dataset_id=str(dataset.id),
        dataset_table_name=dataset.table_name,
        geometry_type=dataset.geometry_type,
    )


# ---------------------------------------------------------------------------
# Tool-set scoping (pure)
# ---------------------------------------------------------------------------


class TestRunAnalysisToolSelection:
    def test_run_analysis_is_advertised(self) -> None:
        names = {t["name"] for t in CHAT_TOOLS_ANTHROPIC}
        assert "run_analysis" in names

    def test_view_only_callers_keep_run_analysis(self) -> None:
        """It only SELECTs through the sandbox — a viewer may run it."""
        names = {t["name"] for t in CHAT_TOOLS_READONLY}
        assert names == {"query_data", "run_analysis"}

    def test_map_less_surfaces_drop_run_analysis(self) -> None:
        """Dataset chat has no map — offering an overlay-only tool would let
        the model promise a preview that can never render."""
        names = {t["name"] for t in select_chat_tools(False, has_map=False)}
        assert names == {"query_data"}
        edit_names = {t["name"] for t in select_chat_tools(True, has_map=False)}
        assert "run_analysis" not in edit_names
        assert "set_style" in edit_names

    def test_clip_and_dissolve_are_not_offered(self) -> None:
        """clip needs a drawn mask and dissolve is materialize-only; neither
        can be driven from chat, so the enum must not tempt the model."""
        tool = next(t for t in CHAT_TOOLS_ANTHROPIC if t["name"] == "run_analysis")
        ops = tool["input_schema"]["properties"]["operation"]["enum"]
        assert sorted(ops) == ["buffer", "centroid"]


# ---------------------------------------------------------------------------
# Action collection (pure)
# ---------------------------------------------------------------------------


class TestRunAnalysisActionCollection:
    def test_emits_overlay_only_show_query_result(self) -> None:
        """The action carries geojson+bbox and NO rows/columns, so every chat
        surface draws the overlay and skips the inline data table."""
        result = {
            "operation": "centroid",
            "feature_count": 1,
            "truncated": False,
            "geojson": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [0.5, 0.5]},
                        "properties": {"gid": 1},
                    }
                ],
            },
            "bbox": [0.5, 0.5, 0.5, 0.5],
        }
        action = _collect_chat_action("run_analysis", {"layer_id": "l1"}, result)
        assert action is not None
        assert action["type"] == "show_query_result"
        assert action["bbox"] == [0.5, 0.5, 0.5, 0.5]
        assert "rows" not in action
        assert "columns" not in action
        # Must survive ChatAction validation on the wire.
        assert ChatAction(**action).geojson is not None

    def test_truncated_result_carries_the_disclosure_pair(self) -> None:
        """fix(#674 audit): a capped preview must not be presented as the whole
        result — EphemeralBadge renders "N of TOTAL" when both ride along."""
        action = _collect_chat_action(
            "run_analysis",
            {"layer_id": "l1"},
            {
                "feature_count": 500,
                "truncated": True,
                "source_feature_count": 10651,
                "geojson": {"type": "FeatureCollection", "features": []},
                "bbox": [0, 0, 1, 1],
            },
        )
        assert action is not None
        assert action["truncated"] is True
        assert action["row_count"] == 10651
        # Still no table payload — the badge reads these, the card does not.
        assert "rows" not in action

    def test_untruncated_result_omits_the_disclosure_pair(self) -> None:
        action = _collect_chat_action(
            "run_analysis",
            {"layer_id": "l1"},
            {
                "feature_count": 12,
                "truncated": False,
                "source_feature_count": 12,
                "geojson": {"type": "FeatureCollection", "features": []},
                "bbox": [0, 0, 1, 1],
            },
        )
        assert action is not None
        assert "truncated" not in action
        assert "row_count" not in action

    def test_truncated_with_unknown_total_omits_the_pair(self) -> None:
        """A dataset with no feature_count must not yield "500 of None"."""
        action = _collect_chat_action(
            "run_analysis",
            {"layer_id": "l1"},
            {
                "feature_count": 500,
                "truncated": True,
                "source_feature_count": None,
                "geojson": {"type": "FeatureCollection", "features": []},
                "bbox": [0, 0, 1, 1],
            },
        )
        assert action is not None
        assert "truncated" not in action
        assert "row_count" not in action

    def test_error_result_emits_no_action(self) -> None:
        action = _collect_chat_action(
            "run_analysis", {"layer_id": "l1"}, {"error": "nope"}
        )
        assert action is None

    def test_empty_result_emits_no_action(self) -> None:
        """No features => no bbox => nothing to fly the map to."""
        action = _collect_chat_action(
            "run_analysis",
            {"layer_id": "l1"},
            {"feature_count": 0, "truncated": False, "note": "no geometry"},
        )
        assert action is None


# ---------------------------------------------------------------------------
# Handler (DB-backed)
# ---------------------------------------------------------------------------


class TestRunAnalysisHandler:
    async def test_buffer_preview(self, test_db_session: AsyncSession):
        admin = await _get_admin(test_db_session)
        ds = await _create_polygon_dataset(test_db_session, created_by=admin.id)
        result = await _handle_run_analysis(
            {"layer_id": "layer-1", "operation": "buffer", "distance_meters": 1000},
            test_db_session,
            admin,
            await _default_port.get_user_roles(test_db_session, admin),
            [_layer_for(ds)],
            port=_default_port,
        )
        assert "error" not in result, result
        assert result["feature_count"] == 1
        assert result["geojson"]["features"][0]["geometry"]["type"] in (
            "Polygon",
            "MultiPolygon",
        )
        assert len(result["bbox"]) == 4

    async def test_centroid_preview(self, test_db_session: AsyncSession):
        admin = await _get_admin(test_db_session)
        ds = await _create_polygon_dataset(test_db_session, created_by=admin.id)
        result = await _handle_run_analysis(
            {"layer_id": "layer-1", "operation": "centroid"},
            test_db_session,
            admin,
            await _default_port.get_user_roles(test_db_session, admin),
            [_layer_for(ds)],
            port=_default_port,
        )
        assert "error" not in result, result
        assert result["geojson"]["features"][0]["geometry"]["type"] == "Point"

    async def test_unknown_layer_is_rejected(self, test_db_session: AsyncSession):
        admin = await _get_admin(test_db_session)
        result = await _handle_run_analysis(
            {"layer_id": "not-on-this-map", "operation": "centroid"},
            test_db_session,
            admin,
            await _default_port.get_user_roles(test_db_session, admin),
            [],
            port=_default_port,
        )
        assert "error" in result
        assert "geojson" not in result

    async def test_private_dataset_of_another_user_is_denied(
        self, test_db_session: AsyncSession
    ):
        """IDOR pin: the layers list is client-supplied, so naming someone
        else's private dataset must NOT run the analysis."""
        admin = await _get_admin(test_db_session)
        other = await _create_other_user(test_db_session)
        ds = await _create_polygon_dataset(
            test_db_session, created_by=admin.id, visibility="private"
        )
        result = await _handle_run_analysis(
            {"layer_id": "layer-1", "operation": "centroid"},
            test_db_session,
            other,
            await _default_port.get_user_roles(test_db_session, other),
            [_layer_for(ds)],
            port=_default_port,
        )
        assert "error" in result
        assert "geojson" not in result

    @pytest.mark.parametrize("distance", [0, -5, 1_000_000, 500])
    async def test_centroid_ignores_any_distance_meters(
        self, test_db_session: AsyncSession, distance
    ):
        """fix(#674 review P2): the tool schema calls distance_meters "ignored
        otherwise", so a model may send a placeholder on a centroid call. Those
        values must not reach AnalysisPreviewRequest's gt=0 / le=100000 bounds
        and fail an otherwise valid preview."""
        admin = await _get_admin(test_db_session)
        ds = await _create_polygon_dataset(test_db_session, created_by=admin.id)
        result = await _handle_run_analysis(
            {
                "layer_id": "layer-1",
                "operation": "centroid",
                "distance_meters": distance,
            },
            test_db_session,
            admin,
            await _default_port.get_user_roles(test_db_session, admin),
            [_layer_for(ds)],
            port=_default_port,
        )
        assert "error" not in result, result
        assert result["geojson"]["features"][0]["geometry"]["type"] == "Point"

    @pytest.mark.parametrize(
        "params",
        [
            {"operation": "buffer"},  # distance required
            {"operation": "buffer", "distance_meters": 0},  # gt=0
            {"operation": "buffer", "distance_meters": 500_000},  # le=100_000
            {"operation": "buffer", "distance_meters": -5},
            {"operation": "drop_table"},  # not in the enum
        ],
    )
    async def test_bad_params_return_an_error_not_an_exception(
        self, test_db_session: AsyncSession, params
    ):
        """Hostile / hallucinated params are rejected by the same Pydantic
        validator the HTTP endpoint uses, and surface as a retryable tool
        error rather than breaking the chat turn."""
        admin = await _get_admin(test_db_session)
        ds = await _create_polygon_dataset(test_db_session, created_by=admin.id)
        result = await _handle_run_analysis(
            {"layer_id": "layer-1", **params},
            test_db_session,
            admin,
            await _default_port.get_user_roles(test_db_session, admin),
            [_layer_for(ds)],
            port=_default_port,
        )
        assert "error" in result, result
        assert "geojson" not in result


# ---------------------------------------------------------------------------
# Model-bound payload trimming (pure)
# ---------------------------------------------------------------------------


class TestModelSafeToolResult:
    """The tool result is echoed back into the model's context verbatim
    (streaming.py / defaults.py json.dumps sites). A run_analysis preview of a
    few hundred buffered polygons is ~1.3 MB of coordinates the model cannot
    use — it must never reach the provider."""

    def test_geojson_is_stripped(self) -> None:
        result = {
            "feature_count": 2,
            "bbox": [0, 0, 1, 1],
            "geojson": {"type": "FeatureCollection", "features": [{"big": "payload"}]},
        }
        trimmed = model_safe_tool_result(result)
        assert "geojson" not in trimmed
        # bbox is 4 numbers of useful spatial context — it stays.
        assert trimmed["bbox"] == [0, 0, 1, 1]
        assert trimmed["feature_count"] == 2
        # The caller's dict is untouched: the action collector still needs it.
        assert "geojson" in result

    def test_result_without_geojson_is_passed_through_unchanged(self) -> None:
        result = {"columns": ["n"], "rows": [[1]], "row_count": 1}
        assert model_safe_tool_result(result) is result

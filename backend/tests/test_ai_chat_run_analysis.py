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

import ast
import uuid
from collections import Counter
from pathlib import Path
from unittest.mock import patch

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
# Overlaps SQUARE's lower-left quarter only.
MASK_QUARTER = "POLYGON((-0.5 -0.5, -0.5 0.5, 0.5 0.5, 0.5 -0.5, -0.5 -0.5))"

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


async def _create_mask_dataset(
    session: AsyncSession,
    *,
    created_by: uuid.UUID,
    visibility: str = "public",
):
    """feat(#683): a polygon layer usable as a clip mask.

    Covers SQUARE's lower-left quarter, so a clip against it survives with a
    genuinely smaller geometry rather than passing the whole input through.
    """
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
            f"(ST_GeomFromText('{MASK_QUARTER}', 4326),"
            f" ST_GeomFromText('{MASK_QUARTER}', 4326))"
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

    def test_clip_is_offered_and_dissolve_is_not(self) -> None:
        """feat(#683): clip joined the enum once #682 shipped the layer mask.
        dissolve stays out on its own merits — materialize-only, an aggregate
        with no preview shape — so the enum must not tempt the model with it."""
        tool = next(t for t in CHAT_TOOLS_ANTHROPIC if t["name"] == "run_analysis")
        props = tool["input_schema"]["properties"]
        assert sorted(props["operation"]["enum"]) == ["buffer", "centroid", "clip"]
        # The mask is a LAYER, never a drawn polygon: the chat surface has no
        # way to draw one, and the schema must not suggest otherwise.
        assert "mask_layer_id" in props
        assert "mask" not in props
        # Optional, because the other two operations do not take one.
        assert sorted(tool["input_schema"]["required"]) == ["layer_id", "operation"]


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

    def test_truncated_with_unknown_total_omits_the_count_not_the_flag(self) -> None:
        """A result with no known total must not yield "500 of None".

        fix(#683 codex P2): it must still say it was capped, though. This used
        to drop the flag along with the count, which reads as a complete result
        — fine while every chat operation reported a total, wrong the moment
        clip (which filters rows, so it reports none) joined them.
        """
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
        assert action["truncated"] is True
        assert "row_count" not in action

    def test_truncated_clip_discloses_the_cap_without_a_total(self) -> None:
        """fix(#683 codex P2): clip filters rows, so the preview returns no
        source_feature_count — the clipped total is genuinely unknown. Requiring
        one dropped the disclosure entirely, presenting a capped clip preview as
        the whole result. The flag rides alone; row_count stays absent."""
        action = _collect_chat_action(
            "run_analysis",
            {"layer_id": "l1"},
            {
                "operation": "clip",
                "layer_id": "l1",
                "feature_count": 500,
                "truncated": True,
                "source_feature_count": None,
                "geojson": {"type": "FeatureCollection", "features": []},
                "bbox": [0, 0, 1, 1],
            },
        )
        assert action is not None
        assert action["truncated"] is True
        assert "row_count" not in action
        ChatAction(**action)

    def test_error_result_emits_no_action(self) -> None:
        action = _collect_chat_action(
            "run_analysis", {"layer_id": "l1"}, {"error": "nope"}
        )
        assert action is None

    def test_action_carries_the_analysis_handoff_params(self) -> None:
        """feat(#675): operation/layer_id/distance ride the action so the
        builder can prefill the Analysis panel ("Save as dataset") from the
        chat preview instead of making the user re-enter everything."""
        action = _collect_chat_action(
            "run_analysis",
            {"layer_id": "l1"},
            {
                "operation": "buffer",
                "layer_id": "l1",
                "distance_meters": 500.0,
                "feature_count": 3,
                "truncated": False,
                "geojson": {"type": "FeatureCollection", "features": []},
                "bbox": [0, 0, 1, 1],
            },
        )
        assert action is not None
        assert action["operation"] == "buffer"
        assert action["layer_id"] == "l1"
        assert action["distance_meters"] == 500.0

    def test_centroid_handoff_omits_distance(self) -> None:
        action = _collect_chat_action(
            "run_analysis",
            {"layer_id": "l1"},
            {
                "operation": "centroid",
                "layer_id": "l1",
                "feature_count": 3,
                "truncated": False,
                "geojson": {"type": "FeatureCollection", "features": []},
                "bbox": [0, 0, 1, 1],
            },
        )
        assert action is not None
        assert action["operation"] == "centroid"
        assert "distance_meters" not in action

    def test_chat_action_round_trip_preserves_the_handoff_params(self) -> None:
        """Regression guard (the builder-audit #338 B-001 trap): fields the
        collector emits but the ChatAction model lacks are silently dropped by
        ``ChatAction(**a).model_dump(exclude_none=True)`` on the wire."""
        action = {
            "type": "show_query_result",
            "operation": "buffer",
            "layer_id": "l1",
            "distance_meters": 500.0,
            "geojson": {"type": "FeatureCollection", "features": []},
            "bbox": [0, 0, 1, 1],
        }
        dumped = ChatAction(**action).model_dump(exclude_none=True)
        assert dumped["operation"] == "buffer"
        assert dumped["layer_id"] == "l1"
        assert dumped["distance_meters"] == 500.0

    def test_empty_result_emits_a_geometry_less_marker(self) -> None:
        """fix(#676): no features still emits a geometry-less action — the
        frontend uses it to clear a stale overlay from an earlier turn.
        Previously None was returned and the previous overlay (plus its
        feature-count badge) stayed on the map beside a "nothing found" reply."""
        action = _collect_chat_action(
            "run_analysis",
            {"layer_id": "l1"},
            {"feature_count": 0, "truncated": False, "note": "no geometry"},
        )
        assert action == {"type": "show_query_result", "row_count": 0}
        # Must survive ChatAction validation on the wire.
        ChatAction(**action)


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
        # feat(#675): the sanitized buffer distance rides along for the
        # Analysis-panel handoff.
        assert result["distance_meters"] == 1000

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
        # feat(#675): only buffer consumes a distance, so none rides along here.
        assert "distance_meters" not in result

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


class TestRunAnalysisClipByLayer:
    """feat(#683): the two-layer operation. What matters is that the SECOND
    dataset gets its own Rule-1 check — seeing the source buys no claim on the
    mask — and that a mask that cannot clip is refused with something the model
    can act on rather than an empty result reported as an answer."""

    async def test_clip_by_layer_preview(self, test_db_session: AsyncSession):
        admin = await _get_admin(test_db_session)
        source = await _create_polygon_dataset(test_db_session, created_by=admin.id)
        mask = await _create_mask_dataset(test_db_session, created_by=admin.id)
        result = await _handle_run_analysis(
            {
                "layer_id": "layer-1",
                "operation": "clip",
                "mask_layer_id": "layer-2",
            },
            test_db_session,
            admin,
            await _default_port.get_user_roles(test_db_session, admin),
            [_layer_for(source), _layer_for(mask, "layer-2")],
            port=_default_port,
        )
        assert "error" not in result, result
        assert result["operation"] == "clip"
        # The mask covers the source square's lower-left quarter, so the
        # survivor is a real clipped polygon rather than the whole input.
        assert result["feature_count"] == 1
        geometry = result["geojson"]["features"][0]["geometry"]
        assert geometry["type"] in ("Polygon", "MultiPolygon")
        assert len(result["bbox"]) == 4
        assert result["bbox"][2] < 1.0

    async def test_mask_layer_not_on_the_map_is_rejected(
        self, test_db_session: AsyncSession
    ):
        admin = await _get_admin(test_db_session)
        source = await _create_polygon_dataset(test_db_session, created_by=admin.id)
        result = await _handle_run_analysis(
            {
                "layer_id": "layer-1",
                "operation": "clip",
                "mask_layer_id": "not-on-this-map",
            },
            test_db_session,
            admin,
            await _default_port.get_user_roles(test_db_session, admin),
            [_layer_for(source)],
            port=_default_port,
        )
        assert "error" in result, result
        assert "mask_layer_id" in result["error"]
        assert "geojson" not in result

    async def test_clip_without_a_mask_layer_is_rejected(
        self, test_db_session: AsyncSession
    ):
        """The schema marks mask_layer_id optional (the other operations do not
        take one), so a model can omit it. That must read as a fixable mistake,
        not as an empty result."""
        admin = await _get_admin(test_db_session)
        source = await _create_polygon_dataset(test_db_session, created_by=admin.id)
        result = await _handle_run_analysis(
            {"layer_id": "layer-1", "operation": "clip"},
            test_db_session,
            admin,
            await _default_port.get_user_roles(test_db_session, admin),
            [_layer_for(source)],
            port=_default_port,
        )
        assert "error" in result, result
        assert "mask_layer_id" in result["error"]

    async def test_clipping_a_layer_by_itself_is_rejected(
        self, test_db_session: AsyncSession
    ):
        admin = await _get_admin(test_db_session)
        source = await _create_polygon_dataset(test_db_session, created_by=admin.id)
        result = await _handle_run_analysis(
            {
                "layer_id": "layer-1",
                "operation": "clip",
                "mask_layer_id": "layer-1",
            },
            test_db_session,
            admin,
            await _default_port.get_user_roles(test_db_session, admin),
            [_layer_for(source)],
            port=_default_port,
        )
        assert "error" in result, result
        assert "different layer" in result["error"]

    async def test_two_layers_over_one_dataset_are_refused(
        self, test_db_session: AsyncSession
    ):
        """fix(#683 codex P2): a duplicated rendering is two layer ids over one
        dataset, so comparing layer ids alone lets that pair through — and
        clipping a table by itself is an expensive way to return the input."""
        admin = await _get_admin(test_db_session)
        source = await _create_polygon_dataset(test_db_session, created_by=admin.id)
        result = await _handle_run_analysis(
            {
                "layer_id": "layer-1",
                "operation": "clip",
                "mask_layer_id": "layer-2",
            },
            test_db_session,
            admin,
            await _default_port.get_user_roles(test_db_session, admin),
            # Same dataset, two renderings — distinct ids, identical data.
            [_layer_for(source), _layer_for(source, "layer-2")],
            port=_default_port,
        )
        assert "error" in result, result
        assert "same dataset" in result["error"]
        assert "geojson" not in result

    async def test_mask_layer_is_access_checked_independently(
        self, test_db_session: AsyncSession
    ):
        """AGENTS.md Rule 1 applies to BOTH datasets. A caller who can read the
        source but not the mask gets a refusal, not a preview — the layer list
        is client-supplied, so naming a private dataset as the mask must not
        read it."""
        admin = await _get_admin(test_db_session)
        other = await _create_other_user(test_db_session)
        source = await _create_polygon_dataset(
            test_db_session, created_by=admin.id, visibility="public"
        )
        private_mask = await _create_mask_dataset(
            test_db_session, created_by=admin.id, visibility="private"
        )
        result = await _handle_run_analysis(
            {
                "layer_id": "layer-1",
                "operation": "clip",
                "mask_layer_id": "layer-2",
            },
            test_db_session,
            other,
            await _default_port.get_user_roles(test_db_session, other),
            [_layer_for(source), _layer_for(private_mask, "layer-2")],
            port=_default_port,
        )
        assert "error" in result, result
        assert "access" in result["error"].lower()
        assert "mask" in result["error"].lower()
        assert "geojson" not in result

    async def test_non_polygonal_mask_layer_is_refused(
        self, test_db_session: AsyncSession
    ):
        """Unioning points or lines yields a mask that clips nothing
        meaningful. Refused with the shape named, matching what the REST route
        does in _load_mask_dataset — otherwise the model reports an empty
        result as a real answer."""
        admin = await _get_admin(test_db_session)
        source = await _create_polygon_dataset(test_db_session, created_by=admin.id)
        # No physical table needed: the shape check refuses it before any SQL
        # is built, which is the point — a bad mask must cost nothing.
        point_mask = await create_dataset(
            test_db_session,
            created_by=admin.id,
            geometry_type="POINT",
        )
        result = await _handle_run_analysis(
            {
                "layer_id": "layer-1",
                "operation": "clip",
                "mask_layer_id": "layer-2",
            },
            test_db_session,
            admin,
            await _default_port.get_user_roles(test_db_session, admin),
            [_layer_for(source), _layer_for(point_mask, "layer-2")],
            port=_default_port,
        )
        assert "error" in result, result
        assert "polygon" in result["error"].lower()
        assert "POINT" in result["error"]

    async def test_oversized_mask_layer_is_refused(self, test_db_session: AsyncSession):
        """fix(#683 codex P1): a resource rail, not a correctness one. The
        preview's _mask_pieces CTE materializes and subdivides every mask row
        before the row cap can bite, so the work scales with the whole mask
        however small the source is. The REST route rejects this in
        _load_mask_dataset; exposing clip through chat without the same gate
        would let one sentence tie up the shared database until timeout."""
        admin = await _get_admin(test_db_session)
        source = await _create_polygon_dataset(test_db_session, created_by=admin.id)
        mask = await _create_mask_dataset(test_db_session, created_by=admin.id)
        mask.feature_count = 1_001
        await test_db_session.commit()

        result = await _handle_run_analysis(
            {
                "layer_id": "layer-1",
                "operation": "clip",
                "mask_layer_id": "layer-2",
            },
            test_db_session,
            admin,
            await _default_port.get_user_roles(test_db_session, admin),
            [_layer_for(source), _layer_for(mask, "layer-2")],
            port=_default_port,
        )
        assert "error" in result, result
        assert "too many features" in result["error"]
        assert "geojson" not in result

    async def test_unknown_mask_size_is_counted_live(
        self, test_db_session: AsyncSession
    ):
        """fix(#701 review) parity: a NULL feature_count must not read as zero,
        or the gate admits exactly the unknown-size layers it exists for. The
        one-row mask table is counted live against a patched cap."""
        admin = await _get_admin(test_db_session)
        source = await _create_polygon_dataset(test_db_session, created_by=admin.id)
        mask = await _create_mask_dataset(test_db_session, created_by=admin.id)
        mask.feature_count = None
        await test_db_session.commit()

        with patch(
            "app.platform.analysis_sql.MAX_MASK_LAYER_FEATURES",
            0,
        ):
            result = await _handle_run_analysis(
                {
                    "layer_id": "layer-1",
                    "operation": "clip",
                    "mask_layer_id": "layer-2",
                },
                test_db_session,
                admin,
                await _default_port.get_user_roles(test_db_session, admin),
                [_layer_for(source), _layer_for(mask, "layer-2")],
                port=_default_port,
            )
        assert "error" in result, result
        assert "too many features" in result["error"]

    async def test_a_legacy_port_still_serves_buffer_and_centroid(
        self, test_db_session: AsyncSession
    ):
        """fix(#683 codex P1): a separately distributed overlay implementing the
        PRE-clip ProcessingPort rejects an unknown `mask_dataset` keyword. If
        the caller passed it unconditionally, every chat analysis against such
        an overlay would break rather than only the new operation — so it rides
        along only when set, the same shape router_analysis._defer uses for the
        materialize task. An overlay that declares its version fails loudly at
        load instead; this is for the legacy undeclared ones, which only warn.
        """

        class LegacyPort:
            """The port as it was before this change: no mask_dataset."""

            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                return getattr(self._inner, name)

            async def run_analysis_preview(
                self,
                session,
                dataset,
                operation,
                *,
                user_id,
                distance_meters=None,
                mask=None,
            ):
                return await self._inner.run_analysis_preview(
                    session,
                    dataset,
                    operation,
                    user_id=user_id,
                    distance_meters=distance_meters,
                    mask=mask,
                )

        admin = await _get_admin(test_db_session)
        source = await _create_polygon_dataset(test_db_session, created_by=admin.id)
        legacy = LegacyPort(_default_port)

        result = await _handle_run_analysis(
            {"layer_id": "layer-1", "operation": "centroid"},
            test_db_session,
            admin,
            await _default_port.get_user_roles(test_db_session, admin),
            [_layer_for(source)],
            port=legacy,
        )
        assert "error" not in result, result
        assert result["geojson"]["features"][0]["geometry"]["type"] == "Point"

    async def test_user_id_is_still_readable_after_the_tool_returns(
        self, test_db_session: AsyncSession
    ):
        """fix(#716): chat must NOT pass release_session=True. The rollback
        that returns the pooled connection expires every ORM instance on the
        session, the authenticated User included, so the next `user.id` read
        would raise MissingGreenlet. Both chat paths do exactly that read after
        the tool returns, which is why this is a test and not a comment."""
        admin = await _get_admin(test_db_session)
        source = await _create_polygon_dataset(test_db_session, created_by=admin.id)
        mask = await _create_mask_dataset(test_db_session, created_by=admin.id)
        result = await _handle_run_analysis(
            {
                "layer_id": "layer-1",
                "operation": "clip",
                "mask_layer_id": "layer-2",
            },
            test_db_session,
            admin,
            await _default_port.get_user_roles(test_db_session, admin),
            [_layer_for(source), _layer_for(mask, "layer-2")],
            port=_default_port,
        )
        assert "error" not in result, result
        # Would raise MissingGreenlet on an expired instance.
        assert admin.id is not None
        assert admin.username is not None


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


class TestToolResultSerializationSites:
    """The pure function above is not the guarantee that matters.

    fix(#699): what protects the model's context is that EVERY provider call
    site routes its tool result through ``model_safe_tool_result`` before
    ``json.dumps``. A site that drops the wrapper passes every test in the
    class above, and ``test_extensions.py`` only asserts the extension
    *binding name* exists, which is a different claim again. So assert the
    property structurally, over the AST.

    The rule: any dict literal carrying a provider tool-result id
    (``tool_use_id`` for Anthropic, ``tool_call_id`` for OpenAI) alongside a
    ``content`` key must set that content to ``tool_result_content(...)``.

    fix(#1778 round 2): that used to read ``json.dumps(model_safe_tool_result
    (...), ...)``, spelled out at each site. The sites now share one helper,
    which trims the map-only payload AND wraps the result in the untrusted
    trust fence, so the property this gate protects got strictly stronger and
    the shape it matches got simpler: one name, called once, at every site.
    Hand-rolling the old two-call form no longer passes, which is the point:
    a site that built its own JSON would be trimmed but unfenced.

    fix(#699 codex P2): the walk covers all of ``backend/app/``, not a fixed
    list of the modules that happen to build these messages today, following
    ``test_rule2_structural.py``. A fourth provider adapter added in a new
    module is exactly the case this is for, and an allowlist would have let it
    through while the assertion still read as if it were covered.

    The known sites below are an anti-vacuity anchor, not the scan's scope:
    without them, renaming the id keys would make the walk find nothing at all
    and pass for the wrong reason.
    """

    # fix(#699 codex P2): counted PER MODULE, not merely present. streaming.py
    # builds two of these messages (the Anthropic tool_result block and the
    # OpenAI tool message), and a set of module names collapses them — so if
    # one changed its key spelling and stopped matching, the other would keep
    # this anchor satisfied while the unmatched site quietly serialized an
    # untrimmed payload.
    KNOWN_SITE_COUNTS = {
        "processing/ai/streaming.py": 2,
        "platform/extensions/defaults_ai_anthropic.py": 1,
        "platform/extensions/defaults_ai_openai.py": 1,
    }

    # The two ids that mark a message as carrying a tool RESULT rather than
    # anything else a provider payload contains.
    RESULT_ID_KEYS = ("tool_use_id", "tool_call_id")

    @classmethod
    def _content_value(cls, node: ast.AST) -> ast.expr | None:
        """Return the ``content`` of a tool-result message, however it is built.

        fix(#699 codex P2): a dict LITERAL is only the shape these happen to
        take today. `dict(tool_call_id=..., content=...)`, or any provider's
        own message class constructed with the same keywords, is the identical
        payload and was invisible to a literal-only walk — so a fourth adapter
        written in either style would have serialized an untrimmed result while
        all three known-module counts stayed satisfied.

        Matching on the key names rather than the construction style is what
        makes this robust: the names are what the provider APIs fix, and they
        are the same whether they arrive as strings or as keywords.
        """
        if isinstance(node, ast.Dict):
            named = {
                key.value: value
                for key, value in zip(node.keys, node.values)
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            }
        elif isinstance(node, ast.Call):
            named = {kw.arg: kw.value for kw in node.keywords if kw.arg is not None}
        else:
            return None
        if not set(named) & set(cls.RESULT_ID_KEYS):
            return None
        return named.get("content")

    @staticmethod
    def _is_trimmed_dumps(value: ast.expr) -> bool:
        """True when the content comes from the one shared serializer."""
        return (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "tool_result_content"
            and bool(value.args)
        )

    def test_every_provider_tool_result_is_trimmed_before_serialization(self) -> None:
        app_root = Path(__file__).resolve().parent.parent / "app"
        sites: list[tuple[str, int, ast.expr]] = []
        for path in sorted(app_root.rglob("*.py")):
            rel = path.relative_to(app_root).as_posix()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not isinstance(node, (ast.Dict, ast.Call)):
                    continue
                value = self._content_value(node)
                if value is not None:
                    sites.append((rel, node.lineno, value))

        found_per_module = Counter(rel for rel, _, _ in sites)
        undercounted = {
            rel: (found_per_module[rel], expected)
            for rel, expected in self.KNOWN_SITE_COUNTS.items()
            if found_per_module[rel] < expected
        }
        assert not undercounted, (
            "the walk no longer recognizes every known tool-result message "
            f"(module: found vs expected) {undercounted} — the key names it "
            "matches on must have changed, so this gate is passing without "
            "checking the sites it lost."
        )

        unwrapped = [
            f"{rel}:{line}"
            for rel, line, value in sites
            if not self._is_trimmed_dumps(value)
        ]
        assert not unwrapped, (
            "these tool-result sites do not go through tool_result_content, so "
            "the whole GeoJSON payload reaches the model and the result is not "
            f"inside the untrusted-content fence: {unwrapped}"
        )

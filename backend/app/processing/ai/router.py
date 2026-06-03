"""AI map generation and metadata assistance endpoints."""

import json
import uuid as uuid_mod
from collections.abc import Awaitable
from typing import TypeVar

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy.ext.asyncio import AsyncSession

# Provider-SDK exception classes (anthropic / openai) are imported lazily
# inside `_call_llm_endpoint` so `processing/` carries zero top-level
# provider-SDK imports (oc-audit 2026-05-02 §5).

from app.processing.ai.chat_service import chat_edit_map
from app.processing.ai.llm_loop import ToolLoopExhaustedError
from app.processing.ai.schemas import (
    ChatMapLayer,
    ChatRequest,
    ChatResponse,
    MapGenerateRequest,
    MapGenerateResponse,
)
from app.processing.ai.streaming import stream_chat_edit
from app.processing.ai.metadata_schemas import (
    KeywordSuggestionsResponse,
    LineageDraftResponse,
    MetadataAssistRequest,
    QualityStatementDraftResponse,
    SummaryDraftResponse,
)
from app.processing.ai.metadata_service import (
    generate_keyword_suggestions,
    generate_lineage_draft,
    generate_quality_statement_draft,
    generate_summary_draft,
)
from app.processing.ai.service import generate_map_from_prompt, stream_generate_map
from typing import TYPE_CHECKING

from app.core.identity import Identity
from app.platform.extensions import get_processing_port
from app.modules.auth.dependencies import require_permission
from app.core.config import settings
from app.core.dependencies import get_db
from app.core.persistent_config import AI_ENABLED, LLM_PROVIDER
from app.modules.auth.router import limiter
from app.platform.sandbox.validator import build_table_allowlist
from app.standards.ogc.errors import ERROR_RESPONSES_AUTH

if TYPE_CHECKING:
    from app.core.processing_port import ProcessingPort

_T = TypeVar("_T")

logger = structlog.stdlib.get_logger(__name__)

router = APIRouter(prefix="/ai", tags=["Maps"], responses=ERROR_RESPONSES_AUTH)

# AI endpoints call external LLM APIs — rate limit to prevent quota exhaustion.
# Map generation/chat: 10/min (heavy, multi-step tool loops)
# Metadata assist: 20/min (lighter, single LLM call)
_AI_GENERATE_LIMIT = "10/minute"
_AI_METADATA_LIMIT = "20/minute"


async def _check_ai_available(db: AsyncSession) -> None:
    """Raise if AI is not configured or has been disabled at runtime.

    Validates that the admin-selected LLM provider has an API key configured.
    Returns 403 when admin has disabled the feature (policy decision),
    503 when the service is unavailable (missing API key).
    """
    if not await AI_ENABLED.get(db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="AI features are disabled by administrator",
        )
    provider = await LLM_PROVIDER.get(db)
    keys = {
        "anthropic": settings.anthropic_api_key,
        "openai_compatible": settings.openai_api_key,
    }
    if not keys.get(provider):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Selected LLM provider API key not configured",
        )


async def _validate_chat_layers(
    db: AsyncSession,
    user: Identity,
    map_id: str,
    layers: list[ChatMapLayer],
    *,
    port: "ProcessingPort",
) -> tuple[list[ChatMapLayer], str | None]:
    """Validate map ownership and overwrite layer metadata with authoritative DB values.

    - Verifies the map exists and is owned by the current user.
    - Resolves each layer's dataset_table_name from the DB by dataset_id.
    - Rejects layers whose datasets the user cannot access.

    **Visibility decision (Pitfall #5 — v1030 Phase 1135 AI-04):** This function
    does NOT filter layers by their ``visible`` state, even if the frontend
    sends a ``visible`` field on the ChatMapLayer model. AI chat analysis sees
    every layer present in the map regardless of visibility. Rationale:
    visibility is a viewer-only decluttering signal (users hide layers to
    reduce visual noise, not to say "do not analyze these"). When a user asks
    "summarize this layer" or "which counties are in the AOI", the AI must
    have the full layer manifest to answer correctly; filtering by visibility
    would silently exclude data the user expects to be analyzed.

    If a future requirement DOES want to scope analysis to visible layers
    only, add an explicit ``include_hidden: bool`` parameter rather than
    silently changing the contract here.

    Returns (validated_layers, basemap_style).
    """
    from app.modules.catalog.maps.models import Map as MapORM

    # Verify map ownership
    try:
        map_uuid = uuid_mod.UUID(map_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid map_id"
        )

    map_obj = await db.execute(select(MapORM).where(MapORM.id == map_uuid))
    map_row = map_obj.scalar_one_or_none()
    if not map_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
        )
    if map_row.created_by != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You do not own this map"
        )
    basemap_style = getattr(map_row, "basemap_style", None)

    if not layers:
        return layers, basemap_style

    # Build the user's allowed table set
    allowed_tables = await build_table_allowlist(db, user)

    # Look up authoritative dataset metadata for all referenced dataset_ids
    dataset_ids = list({layer.dataset_id for layer in layers})
    try:
        dataset_uuids = [uuid_mod.UUID(did) for did in dataset_ids]
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid dataset_id in layers",
        )

    rows = await port.get_datasets_meta_by_ids(db, dataset_uuids)
    # rows is list[tuple[UUID, str, str | None]] — (id, table_name, geometry_type)
    dataset_meta: dict[str, dict] = {
        str(row[0]): {"table_name": row[1], "geometry_type": row[2]} for row in rows
    }

    validated: list[ChatMapLayer] = []
    for layer in layers:
        ds = dataset_meta.get(layer.dataset_id)
        if not ds:
            logger.warning(
                "Chat layer references unknown dataset", dataset_id=layer.dataset_id
            )
            continue
        if ds["table_name"] not in allowed_tables:
            logger.warning(
                "Chat layer references inaccessible dataset",
                dataset_id=layer.dataset_id,
                table_name=ds["table_name"],
            )
            continue
        # Overwrite client-supplied metadata with authoritative values
        layer.dataset_table_name = ds["table_name"]
        if ds["geometry_type"]:
            layer.geometry_type = ds["geometry_type"]
        validated.append(layer)

    return validated, basemap_style


@router.post("/generate-map/", response_model=MapGenerateResponse)
@limiter.limit(_AI_GENERATE_LIMIT)
async def generate_map_endpoint(
    request: Request,
    body: MapGenerateRequest,
    user: Identity = Depends(require_permission("use_ai_chat")),
    db: AsyncSession = Depends(get_db),
    port: "ProcessingPort" = Depends(get_processing_port),
) -> MapGenerateResponse:
    """Generate a map from a natural language prompt using an LLM."""
    await _check_ai_available(db)

    user_roles = await port.get_user_roles(db, user)

    result = await _call_llm_endpoint(
        generate_map_from_prompt(
            db, user, user_roles, body.prompt, language=body.language, port=port
        ),
        error_prefix="AI map generation",
        tool_loop_message="Map generation required too many steps. Try a simpler prompt.",
        unexpected_message="AI map generation failed unexpectedly",
    )

    await db.commit()
    return MapGenerateResponse(**result)


@router.post(
    "/generate-map/stream/",
    responses={
        200: {
            "description": "Server-Sent Events stream",
            "content": {"text/event-stream": {}},
        }
    },
)
@limiter.limit(_AI_GENERATE_LIMIT)
async def generate_map_stream_endpoint(
    request: Request,
    body: MapGenerateRequest,
    user: Identity = Depends(require_permission("use_ai_chat")),
    db: AsyncSession = Depends(get_db),
    port: "ProcessingPort" = Depends(get_processing_port),
) -> EventSourceResponse:
    """Generate a map from a natural language prompt with streaming progress events."""

    async def event_generator():
        # Validation runs inside the generator so failures yield a graceful
        # streaming error event rather than a raw HTTP 500 the SSE client
        # cannot decode.
        try:
            await _check_ai_available(db)
            user_roles = await port.get_user_roles(db, user)
        except HTTPException as exc:
            yield ServerSentEvent(
                data=json.dumps({"type": "error", "message": exc.detail}),
                event="error",
            )
            return
        except (
            Exception
        ):  # broad: pre-flight validation can fail unpredictably in async SSE context
            logger.exception("Map generation pre-flight error")
            yield ServerSentEvent(
                data=json.dumps(
                    {"type": "error", "message": "An unexpected error occurred"}
                ),
                event="error",
            )
            return

        try:
            async for event in stream_generate_map(
                db, user, user_roles, body.prompt, language=body.language, port=port
            ):
                if await request.is_disconnected():
                    break
                yield ServerSentEvent(data=json.dumps(event), event=event["type"])
        except Exception:  # broad: SSE stream generator — any unhandled error must yield a graceful error event
            logger.exception("Map generation stream error")
            yield ServerSentEvent(
                data=json.dumps(
                    {"type": "error", "message": "An unexpected error occurred"}
                ),
                event="error",
            )

    return EventSourceResponse(event_generator())


@router.post("/chat/", response_model=ChatResponse)
@limiter.limit(_AI_GENERATE_LIMIT)
async def chat_endpoint(
    request: Request,
    body: ChatRequest,
    user: Identity = Depends(require_permission("use_ai_chat")),
    db: AsyncSession = Depends(get_db),
    port: "ProcessingPort" = Depends(get_processing_port),
) -> ChatResponse:
    """Chat-based map editing: send a message and get back edit actions."""
    await _check_ai_available(db)

    validated_layers, basemap_style = await _validate_chat_layers(
        db, user, body.map_id, body.layers, port=port
    )
    user_roles = await port.get_user_roles(db, user)

    return await _call_llm_endpoint(
        chat_edit_map(
            db,
            user,
            user_roles,
            body.message,
            validated_layers,
            language=body.language,
            history=body.history or None,
            basemap_style=basemap_style,
            port=port,
            map_id=body.map_id,
        ),
        error_prefix="Chat map editing",
        tool_loop_message="Request required too many steps. Try a simpler instruction.",
        unexpected_message="Chat map editing failed unexpectedly",
    )


@router.post(
    "/chat/stream/",
    responses={
        200: {
            "description": "Server-Sent Events stream",
            "content": {"text/event-stream": {}},
        }
    },
)
@limiter.limit(_AI_GENERATE_LIMIT)
async def chat_stream_endpoint(
    request: Request,
    body: ChatRequest,
    user: Identity = Depends(require_permission("use_ai_chat")),
    db: AsyncSession = Depends(get_db),
    port: "ProcessingPort" = Depends(get_processing_port),
) -> EventSourceResponse:
    """Chat-based map editing with server-sent event streaming."""

    async def event_generator():
        # Validation runs inside the generator so failures yield a graceful
        # streaming error event rather than a raw HTTP 500 the SSE client
        # cannot decode.
        try:
            await _check_ai_available(db)
            validated_layers, basemap_style = await _validate_chat_layers(
                db, user, body.map_id, body.layers, port=port
            )
            user_roles = await port.get_user_roles(db, user)
        except HTTPException as exc:
            yield ServerSentEvent(
                data=json.dumps({"type": "error", "message": exc.detail}),
                event="error",
            )
            return
        except (
            Exception
        ):  # broad: pre-flight validation can fail unpredictably in async SSE context
            logger.exception("Chat pre-flight error")
            yield ServerSentEvent(
                data=json.dumps(
                    {"type": "error", "message": "An unexpected error occurred"}
                ),
                event="error",
            )
            return

        try:
            async for event in stream_chat_edit(
                db,
                user,
                user_roles,
                body.message,
                validated_layers,
                language=body.language,
                history=body.history or None,
                basemap_style=basemap_style,
                port=port,
                map_id=body.map_id,
            ):
                if await request.is_disconnected():
                    break
                yield ServerSentEvent(data=json.dumps(event), event=event["type"])
        except Exception:  # broad: SSE stream generator — any unhandled error must yield a graceful error event
            logger.exception("Chat stream error")
            yield ServerSentEvent(
                data=json.dumps(
                    {"type": "error", "message": "An unexpected error occurred"}
                ),
                event="error",
            )

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# Metadata AI endpoints
# ---------------------------------------------------------------------------


async def _call_llm_endpoint(
    coro: Awaitable[_T],
    *,
    error_prefix: str,
    tool_loop_message: str | None = None,
    unexpected_message: str = "AI metadata generation failed unexpectedly",
) -> _T:
    """Shared error handler for AI endpoints (chat, generate-map, metadata).

    Maps the standard LLM exception taxonomy to HTTP errors:
      - ValueError                      → 422 (caller-supplied detail)
      - ToolLoopExhaustedError          → 422 (when tool_loop_message is set)
      - APIConnectionError (provider)   → 502 "Could not connect to LLM provider"
      - APIError (provider)             → 502 "LLM provider returned an error"
      - Anything else                   → 500 with caller-supplied message

    Pass ``tool_loop_message`` for endpoints that run multi-step tool loops
    (chat, generate-map). Metadata endpoints don't tool-loop, so leave it None.
    """
    # Deferred imports — provider SDKs must not load at module import time
    # within `processing/` (oc-audit 2026-05-02 §5). Used only for the
    # `except` clauses below.
    import anthropic
    import openai

    try:
        return await coro
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(e),
        )
    except ToolLoopExhaustedError:
        if tool_loop_message is None:
            # Should not happen for metadata endpoints, but degrade gracefully.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Request required too many steps. Try a simpler instruction.",
            )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=tool_loop_message,
        )
    except (anthropic.APIConnectionError, openai.APIConnectionError) as e:
        logger.warning(f"{error_prefix} connection error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not connect to LLM provider",
        )
    except (anthropic.APIError, openai.APIError) as e:
        logger.warning(f"{error_prefix} API error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM provider returned an error",
        )
    except (
        Exception
    ):  # broad: LLM service can throw arbitrary errors beyond APIError subtypes
        logger.exception(f"{error_prefix.lower().replace(' ', '_')}_failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=unexpected_message,
        )


# Backward-compat alias — older callers import _call_metadata_ai by name.
async def _call_metadata_ai(coro: Awaitable[_T], error_prefix: str) -> _T:
    return await _call_llm_endpoint(coro, error_prefix=error_prefix)


@router.post("/metadata/summary/", response_model=SummaryDraftResponse)
@limiter.limit(_AI_METADATA_LIMIT)
async def generate_metadata_summary(
    request: Request,
    body: MetadataAssistRequest,
    user: Identity = Depends(require_permission("use_ai_chat")),
    db: AsyncSession = Depends(get_db),
    port: "ProcessingPort" = Depends(get_processing_port),
) -> SummaryDraftResponse:
    """Generate an AI-drafted summary for a dataset."""
    await _check_ai_available(db)
    return await _call_metadata_ai(
        generate_summary_draft(db, body.dataset_id, port=port),
        "AI metadata summary generation",
    )


@router.post("/metadata/keywords/", response_model=KeywordSuggestionsResponse)
@limiter.limit(_AI_METADATA_LIMIT)
async def generate_metadata_keywords(
    request: Request,
    body: MetadataAssistRequest,
    user: Identity = Depends(require_permission("use_ai_chat")),
    db: AsyncSession = Depends(get_db),
    port: "ProcessingPort" = Depends(get_processing_port),
) -> KeywordSuggestionsResponse:
    """Generate AI-suggested keywords for a dataset."""
    await _check_ai_available(db)
    return await _call_metadata_ai(
        generate_keyword_suggestions(db, body.dataset_id, port=port),
        "AI metadata keyword generation",
    )


@router.post("/metadata/lineage/", response_model=LineageDraftResponse)
@limiter.limit(_AI_METADATA_LIMIT)
async def generate_metadata_lineage(
    request: Request,
    body: MetadataAssistRequest,
    user: Identity = Depends(require_permission("use_ai_chat")),
    db: AsyncSession = Depends(get_db),
    port: "ProcessingPort" = Depends(get_processing_port),
) -> LineageDraftResponse:
    """Generate an AI-drafted lineage summary for a dataset."""
    await _check_ai_available(db)
    return await _call_metadata_ai(
        generate_lineage_draft(db, body.dataset_id, port=port),
        "AI metadata lineage generation",
    )


@router.post(
    "/metadata/quality-statement/", response_model=QualityStatementDraftResponse
)
@limiter.limit(_AI_METADATA_LIMIT)
async def generate_metadata_quality_statement(
    request: Request,
    body: MetadataAssistRequest,
    user: Identity = Depends(require_permission("use_ai_chat")),
    db: AsyncSession = Depends(get_db),
    port: "ProcessingPort" = Depends(get_processing_port),
) -> QualityStatementDraftResponse:
    """Generate an AI-drafted quality statement for a dataset."""
    await _check_ai_available(db)
    return await _call_metadata_ai(
        generate_quality_statement_draft(db, body.dataset_id, port=port),
        "AI metadata quality statement generation",
    )

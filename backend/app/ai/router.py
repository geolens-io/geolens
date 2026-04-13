"""AI map generation and metadata assistance endpoints."""

import json
import uuid as uuid_mod

import anthropic
import openai
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.chat_service import chat_edit_map
from app.ai.llm_loop import ToolLoopExhaustedError
from app.ai.schemas import (
    ChatMapLayer,
    ChatRequest,
    ChatResponse,
    MapGenerateRequest,
    MapGenerateResponse,
)
from app.ai.streaming import stream_chat_edit
from app.ai.metadata_schemas import (
    KeywordSuggestionsResponse,
    LineageDraftResponse,
    MetadataAssistRequest,
    QualityStatementDraftResponse,
    SummaryDraftResponse,
)
from app.ai.metadata_service import (
    generate_keyword_suggestions,
    generate_lineage_draft,
    generate_quality_statement_draft,
    generate_summary_draft,
)
from app.ai.service import generate_map_from_prompt, stream_generate_map
from app.auth.dependencies import require_permission
from app.auth.models import User
from app.auth.visibility import get_user_roles
from app.config import settings
from app.datasets.models import Dataset
from app.dependencies import get_db
from app.maps.models import Map
from app.persistent_config import AI_ENABLED, LLM_PROVIDER
from app.auth.router import limiter
from app.sandbox.validator import build_table_allowlist

logger = structlog.stdlib.get_logger(__name__)

router = APIRouter(prefix="/ai", tags=["Maps"])

# AI endpoints call external LLM APIs — rate limit to prevent quota exhaustion.
# Map generation/chat: 10/min (heavy, multi-step tool loops)
# Metadata assist: 20/min (lighter, single LLM call)
_AI_GENERATE_LIMIT = "10/minute"
_AI_METADATA_LIMIT = "20/minute"


async def _check_ai_available(
    db: AsyncSession, *, status_code: int = status.HTTP_403_FORBIDDEN
) -> None:
    """Raise if AI is not configured or has been disabled at runtime.

    Validates that the admin-selected LLM provider has an API key configured.
    Uses 403 by default (policy toggle), callers may override.
    """
    if not await AI_ENABLED.get(db):
        raise HTTPException(
            status_code=status_code,
            detail="AI features are disabled by administrator",
        )
    provider = await LLM_PROVIDER.get(db)
    if provider == "anthropic" and not settings.anthropic_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Selected LLM provider API key not configured",
        )
    if provider == "openai_compatible" and not settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Selected LLM provider API key not configured",
        )
    if not settings.anthropic_api_key and not settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI is not configured (missing API key)",
        )


async def _validate_chat_layers(
    db: AsyncSession,
    user: User,
    map_id: str,
    layers: list[ChatMapLayer],
) -> list[ChatMapLayer]:
    """Validate map ownership and overwrite layer metadata with authoritative DB values.

    - Verifies the map exists and is owned by the current user.
    - Resolves each layer's dataset_table_name from the DB by dataset_id.
    - Rejects layers whose datasets the user cannot access.
    """
    # Verify map ownership
    try:
        map_uuid = uuid_mod.UUID(map_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid map_id"
        )

    map_obj = await db.execute(select(Map).where(Map.id == map_uuid))
    map_row = map_obj.scalar_one_or_none()
    if not map_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Map not found"
        )
    if map_row.created_by != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You do not own this map"
        )

    if not layers:
        return layers

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

    result = await db.execute(
        select(Dataset.id, Dataset.table_name, Dataset.geometry_type).where(
            Dataset.id.in_(dataset_uuids)
        )
    )
    dataset_map = {str(row.id): row for row in result.all()}

    validated: list[ChatMapLayer] = []
    for layer in layers:
        ds = dataset_map.get(layer.dataset_id)
        if not ds:
            logger.warning(
                "Chat layer references unknown dataset", dataset_id=layer.dataset_id
            )
            continue
        if ds.table_name not in allowed_tables:
            logger.warning(
                "Chat layer references inaccessible dataset",
                dataset_id=layer.dataset_id,
                table_name=ds.table_name,
            )
            continue
        # Overwrite client-supplied metadata with authoritative values
        layer.dataset_table_name = ds.table_name
        if ds.geometry_type:
            layer.geometry_type = ds.geometry_type
        validated.append(layer)

    return validated


@router.post("/generate-map/", response_model=MapGenerateResponse)
@limiter.limit(_AI_GENERATE_LIMIT)
async def generate_map_endpoint(
    request: Request,
    body: MapGenerateRequest,
    user: User = Depends(require_permission("use_ai_chat")),
    db: AsyncSession = Depends(get_db),
) -> MapGenerateResponse:
    """Generate a map from a natural language prompt using an LLM."""
    await _check_ai_available(db)

    user_roles = await get_user_roles(db, user)

    try:
        result = await generate_map_from_prompt(
            db, user, user_roles, body.prompt, language=body.language
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(e),
        )
    except ToolLoopExhaustedError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Map generation required too many steps. Try a simpler prompt.",
        )
    except (anthropic.APIConnectionError, openai.APIConnectionError) as e:
        logger.warning("LLM connection error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not connect to LLM provider",
        )
    except (anthropic.APIError, openai.APIError) as e:
        logger.warning("LLM API error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM provider returned an error",
        )
    except Exception:
        logger.exception("AI map generation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI map generation failed unexpectedly",
        )

    await db.commit()
    return MapGenerateResponse(**result)


@router.post("/generate-map/stream/")
@limiter.limit(_AI_GENERATE_LIMIT)
async def generate_map_stream_endpoint(
    request: Request,
    body: MapGenerateRequest,
    user: User = Depends(require_permission("use_ai_chat")),
    db: AsyncSession = Depends(get_db),
):
    """Generate a map from a natural language prompt with streaming progress events."""

    async def event_generator():
        # Validation runs inside the generator so failures yield a graceful
        # streaming error event rather than a raw HTTP 500 the SSE client
        # cannot decode.
        try:
            await _check_ai_available(db)
            user_roles = await get_user_roles(db, user)
        except HTTPException as exc:
            yield ServerSentEvent(
                data=json.dumps({"type": "error", "message": exc.detail}),
                event="error",
            )
            return
        except Exception as exc:
            logger.exception("Map generation pre-flight error")
            yield ServerSentEvent(
                data=json.dumps({"type": "error", "message": str(exc)}),
                event="error",
            )
            return

        try:
            async for event in stream_generate_map(
                db, user, user_roles, body.prompt, language=body.language
            ):
                yield ServerSentEvent(data=json.dumps(event), event=event["type"])
        except Exception as e:
            logger.exception("Map generation stream error")
            yield ServerSentEvent(
                data=json.dumps({"type": "error", "message": str(e)}), event="error"
            )

    return EventSourceResponse(event_generator())


@router.post("/chat/", response_model=ChatResponse)
@limiter.limit(_AI_GENERATE_LIMIT)
async def chat_endpoint(
    request: Request,
    body: ChatRequest,
    user: User = Depends(require_permission("use_ai_chat")),
    db: AsyncSession = Depends(get_db),
) -> ChatResponse:
    """Chat-based map editing: send a message and get back edit actions."""
    await _check_ai_available(db)

    validated_layers = await _validate_chat_layers(db, user, body.map_id, body.layers)
    user_roles = await get_user_roles(db, user)

    try:
        return await chat_edit_map(
            db,
            user,
            user_roles,
            body.message,
            validated_layers,
            language=body.language,
            history=body.history or None,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(e),
        )
    except ToolLoopExhaustedError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Request required too many steps. Try a simpler instruction.",
        )
    except (anthropic.APIConnectionError, openai.APIConnectionError) as e:
        logger.warning("Chat LLM connection error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not connect to LLM provider",
        )
    except (anthropic.APIError, openai.APIError) as e:
        logger.warning("Chat LLM API error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM provider returned an error",
        )
    except Exception:
        logger.exception("Chat map editing failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Chat map editing failed unexpectedly",
        )


@router.post("/chat/stream/")
@limiter.limit(_AI_GENERATE_LIMIT)
async def chat_stream_endpoint(
    request: Request,
    body: ChatRequest,
    user: User = Depends(require_permission("use_ai_chat")),
    db: AsyncSession = Depends(get_db),
):
    """Chat-based map editing with server-sent event streaming."""

    async def event_generator():
        # Validation runs inside the generator so failures yield a graceful
        # streaming error event rather than a raw HTTP 500 the SSE client
        # cannot decode.
        try:
            await _check_ai_available(db)
            validated_layers = await _validate_chat_layers(
                db, user, body.map_id, body.layers
            )
            user_roles = await get_user_roles(db, user)
        except HTTPException as exc:
            yield ServerSentEvent(
                data=json.dumps({"type": "error", "message": exc.detail}),
                event="error",
            )
            return
        except Exception as exc:
            logger.exception("Chat pre-flight error")
            yield ServerSentEvent(
                data=json.dumps({"type": "error", "message": str(exc)}),
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
            ):
                yield ServerSentEvent(data=json.dumps(event), event=event["type"])
        except Exception as e:
            logger.exception("Chat stream error")
            yield ServerSentEvent(
                data=json.dumps({"type": "error", "message": str(e)}), event="error"
            )

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# Metadata AI endpoints
# ---------------------------------------------------------------------------


@router.post("/metadata/summary/", response_model=SummaryDraftResponse)
@limiter.limit(_AI_METADATA_LIMIT)
async def generate_metadata_summary(
    request: Request,
    body: MetadataAssistRequest,
    user: User = Depends(require_permission("use_ai_chat")),
    db: AsyncSession = Depends(get_db),
) -> SummaryDraftResponse:
    """Generate an AI-drafted summary for a dataset."""
    await _check_ai_available(db)

    try:
        return await generate_summary_draft(db, body.dataset_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(e),
        )
    except (anthropic.APIConnectionError, openai.APIConnectionError) as e:
        logger.warning("AI metadata connection error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not connect to LLM provider",
        )
    except (anthropic.APIError, openai.APIError) as e:
        logger.warning("AI metadata API error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM provider returned an error",
        )
    except Exception:
        logger.exception("AI metadata summary generation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI metadata generation failed unexpectedly",
        )


@router.post("/metadata/keywords/", response_model=KeywordSuggestionsResponse)
@limiter.limit(_AI_METADATA_LIMIT)
async def generate_metadata_keywords(
    request: Request,
    body: MetadataAssistRequest,
    user: User = Depends(require_permission("use_ai_chat")),
    db: AsyncSession = Depends(get_db),
) -> KeywordSuggestionsResponse:
    """Generate AI-suggested keywords for a dataset."""
    await _check_ai_available(db)

    try:
        return await generate_keyword_suggestions(db, body.dataset_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(e),
        )
    except (anthropic.APIConnectionError, openai.APIConnectionError) as e:
        logger.warning("AI metadata connection error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not connect to LLM provider",
        )
    except (anthropic.APIError, openai.APIError) as e:
        logger.warning("AI metadata API error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM provider returned an error",
        )
    except Exception:
        logger.exception("AI metadata keyword generation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI metadata generation failed unexpectedly",
        )


@router.post("/metadata/lineage/", response_model=LineageDraftResponse)
@limiter.limit(_AI_METADATA_LIMIT)
async def generate_metadata_lineage(
    request: Request,
    body: MetadataAssistRequest,
    user: User = Depends(require_permission("use_ai_chat")),
    db: AsyncSession = Depends(get_db),
) -> LineageDraftResponse:
    """Generate an AI-drafted lineage summary for a dataset."""
    await _check_ai_available(db)

    try:
        return await generate_lineage_draft(db, body.dataset_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(e),
        )
    except (anthropic.APIConnectionError, openai.APIConnectionError) as e:
        logger.warning("AI metadata connection error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not connect to LLM provider",
        )
    except (anthropic.APIError, openai.APIError) as e:
        logger.warning("AI metadata API error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM provider returned an error",
        )
    except Exception:
        logger.exception("AI metadata lineage generation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI metadata generation failed unexpectedly",
        )


@router.post(
    "/metadata/quality-statement/", response_model=QualityStatementDraftResponse
)
@limiter.limit(_AI_METADATA_LIMIT)
async def generate_metadata_quality_statement(
    request: Request,
    body: MetadataAssistRequest,
    user: User = Depends(require_permission("use_ai_chat")),
    db: AsyncSession = Depends(get_db),
) -> QualityStatementDraftResponse:
    """Generate an AI-drafted quality statement for a dataset."""
    await _check_ai_available(db)

    try:
        return await generate_quality_statement_draft(db, body.dataset_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(e),
        )
    except (anthropic.APIConnectionError, openai.APIConnectionError) as e:
        logger.warning("AI metadata connection error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not connect to LLM provider",
        )
    except (anthropic.APIError, openai.APIError) as e:
        logger.warning("AI metadata API error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="LLM provider returned an error",
        )
    except Exception:
        logger.exception("AI metadata quality statement generation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="AI metadata generation failed unexpectedly",
        )

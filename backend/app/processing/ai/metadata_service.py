"""Metadata generation service with dual-provider (Anthropic/OpenAI) support.

Builds rich prompts from dataset context and generates structured drafts
for summaries, keywords, and lineage using LLM providers.
"""

import json
import time
from typing import TYPE_CHECKING

import structlog
from geoalchemy2.shape import to_shape
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.processing.ai.metadata_schemas import (
    KeywordSuggestionsResponse,
    LineageDraftResponse,
    QualityStatementDraftResponse,
    SummaryDraftResponse,
)
from app.processing.ai.llm_loop import get_anthropic_client, get_openai_client
from app.core.config import settings
from app.processing.embeddings.helpers import get_nearest_record_ids
from app.core.persistent_config import LLM_MODEL_LIGHT, LLM_PROVIDER, OPENAI_BASE_URL

if TYPE_CHECKING:
    from app.core.processing_port import ProcessingPort

logger = structlog.stdlib.get_logger(__name__)

# In-memory TTL caches for metadata AI (avoids redundant DB queries when
# a user clicks Summary, Keywords, Lineage in quick succession).
_CACHE_TTL = 60.0  # seconds
_dataset_context_cache: dict[str, tuple[float, str]] = {}
_vocabulary_cache: tuple[float, list[str]] | None = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _build_dataset_context(
    session: AsyncSession,
    dataset_id: str,
    *,
    port: "ProcessingPort",
) -> str:
    """Load dataset with relationships and build a context string for prompts."""
    import uuid as _uuid

    # Check TTL cache
    now = time.monotonic()
    cached = _dataset_context_cache.get(dataset_id)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]

    dataset = await port.get_dataset_with_attributes(
        session, _uuid.UUID(dataset_id)
    )

    if dataset is None:
        raise ValueError("Dataset not found")

    record = dataset.record
    parts: list[str] = []

    parts.append(f"Title: {record.title}")

    if record.summary:
        parts.append(f"Current summary: {record.summary}")

    if dataset.geometry_type:
        parts.append(f"Geometry type: {dataset.geometry_type}")

    if dataset.feature_count is not None:
        parts.append(f"Feature count: {dataset.feature_count}")

    if dataset.srid is not None:
        parts.append(f"Coordinate system (SRID): {dataset.srid}")

    if dataset.source_format:
        parts.append(f"Source format: {dataset.source_format}")

    if dataset.source_filename:
        parts.append(f"Source filename: {dataset.source_filename}")

    if dataset.source_url:
        parts.append(f"Source URL: {dataset.source_url}")

    if dataset.original_srid is not None:
        parts.append(f"Original SRID: {dataset.original_srid}")

    if record.lineage_summary:
        parts.append(f"Current lineage: {record.lineage_summary}")

    if record.source_organization:
        parts.append(f"Source organization: {record.source_organization}")

    if record.spatial_extent is not None:
        try:
            bounds = to_shape(record.spatial_extent).bounds
            parts.append(
                f"Bounding box (W, S, E, N): {bounds[0]:.4f}, {bounds[1]:.4f}, "
                f"{bounds[2]:.4f}, {bounds[3]:.4f}"
            )
        except Exception:
            logger.debug("Failed to parse spatial bounds for AI context", exc_info=True)

    if record.access_constraints:
        parts.append(f"Access constraints: {record.access_constraints}")

    # Column info
    if dataset.column_info:
        col_strs = []
        for col in dataset.column_info[:30]:
            col_strs.append(f"  - {col.get('name', '?')}: {col.get('type', '?')}")
        parts.append("Columns:\n" + "\n".join(col_strs))

    # Sample values (truncated at value level to avoid mid-JSON cuts)
    if dataset.sample_values:
        truncated_samples = {}
        for col, vals in list(dataset.sample_values.items())[:10]:
            truncated_samples[col] = vals[:5] if isinstance(vals, list) else vals
        sample_str = json.dumps(truncated_samples, default=str)
        parts.append(f"Sample values: {sample_str}")

    # Existing keywords
    if record.keywords:
        kw_list = [kw.keyword for kw in record.keywords]
        parts.append(f"Existing keywords: {', '.join(kw_list)}")

    # Attribute metadata (current only, max 20)
    current_attrs = [a for a in dataset.attributes if a.is_current][:20]
    if current_attrs:
        attr_strs = []
        for attr in current_attrs:
            desc = f" - {attr.description}" if attr.description else ""
            attr_strs.append(f"  - {attr.field_name} ({attr.data_type or '?'}){desc}")
        parts.append("Attribute metadata:\n" + "\n".join(attr_strs))

    # Quality metrics (computed)
    if hasattr(dataset, "quality_detail") and dataset.quality_detail:
        qd = json.dumps(dataset.quality_detail, default=str)
        if len(qd) > 1000:
            qd = qd[:1000] + "..."
        parts.append(f"Quality metrics (computed): {qd}")

    if hasattr(dataset, "quality_statement") and dataset.quality_statement:
        parts.append(f"Current quality statement: {dataset.quality_statement}")

    # Temporal extent
    if record.temporal_start:
        parts.append(f"Temporal start: {record.temporal_start}")
    if record.temporal_end:
        parts.append(f"Temporal end: {record.temporal_end}")

    # Record type
    if hasattr(record, "record_type") and record.record_type:
        parts.append(f"Record type: {record.record_type}")

    result = "\n".join(parts)
    # Store in cache (cap at 20 entries)
    if len(_dataset_context_cache) >= 20:
        oldest_key = min(
            _dataset_context_cache, key=lambda k: _dataset_context_cache[k][0]
        )
        del _dataset_context_cache[oldest_key]
    _dataset_context_cache[dataset_id] = (now, result)
    return result


async def _get_catalog_vocabulary(
    session: AsyncSession,
    *,
    port: "ProcessingPort",
) -> list[str]:
    """Return up to 200 distinct keywords from the catalog (cached 60s)."""
    global _vocabulary_cache
    now = time.monotonic()
    if _vocabulary_cache and (now - _vocabulary_cache[0]) < _CACHE_TTL:
        return _vocabulary_cache[1]

    vocab = await port.get_catalog_vocabulary(session)
    _vocabulary_cache = (now, vocab)
    return vocab


async def _get_related_keywords_from_embeddings(
    session: AsyncSession,
    dataset_id: str,
    limit: int = 5,
    *,
    port: "ProcessingPort",
) -> list[str]:
    """Return keywords from the top-N nearest datasets by embedding similarity.

    Falls back to empty list if dataset has no embedding or on any error.

    Phase 225 review fix (B-02 / W-01): both the dataset lookup and the
    keyword aggregation route through the Port surface so processing/* keeps
    no module-load-time OR deferred ``app.modules.catalog`` ORM imports here.
    Enterprise overlays (Phase 226) can intercept both calls.
    """
    import uuid as _uuid

    try:
        dataset = await port.get_dataset(session, _uuid.UUID(dataset_id))
        if dataset is None or dataset.record_id is None:
            return []

        neighbor_ids = await get_nearest_record_ids(
            session, dataset.record_id, limit=limit
        )
        if not neighbor_ids:
            return []

        return await port.get_keywords_for_records(session, neighbor_ids)
    except Exception:
        logger.debug("Embedding neighbor keyword lookup failed", exc_info=True)
        return []


async def _generate_structured(
    system: str,
    prompt: str,
    response_model: type[BaseModel],
    db: AsyncSession | None = None,
) -> BaseModel:
    """Generate structured output using Anthropic or OpenAI provider.

    Uses tool-use pattern for Anthropic, structured output for OpenAI.
    """
    # Build JSON schema from the Pydantic model for tool definition
    model_schema = response_model.model_json_schema()
    # Remove unnecessary schema metadata keys
    model_schema.pop("title", None)
    model_schema.pop("description", None)

    # Resolve provider and model from PersistentConfig
    provider = (
        await LLM_PROVIDER.get(db)
        if db is not None
        else ("anthropic" if settings.anthropic_api_key else "openai_compatible")
    )
    model = (
        await LLM_MODEL_LIGHT.get(db)
        if db is not None
        else (
            settings.llm_model if settings.anthropic_api_key else settings.openai_model
        )
    )

    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError("Anthropic API key not configured")
        client = get_anthropic_client()

        # Define the response model as a tool
        tool = {
            "name": "output",
            "description": "Output the structured result",
            "input_schema": model_schema,
        }

        logger.info(
            "AI metadata request",
            provider="anthropic",
            model=model,
            response_model=response_model.__name__,
        )

        response = await client.messages.create(
            model=model,
            max_tokens=1024,
            temperature=0.3,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            tools=[tool],
            tool_choice={"type": "tool", "name": "output"},
        )

        # Extract tool_use block
        for block in response.content:
            if block.type == "tool_use":
                return response_model.model_validate(block.input)

        raise ValueError("No tool_use block in Anthropic response")

    elif provider == "openai_compatible":
        if not settings.openai_api_key:
            raise ValueError("OpenAI-compatible API key not configured")
        base_url = await OPENAI_BASE_URL.get(db) if db is not None else None
        if not base_url:
            base_url = settings.openai_base_url or "https://api.openai.com/v1"
        client = get_openai_client(base_url)

        logger.info(
            "AI metadata request",
            provider="openai",
            model=model,
            response_model=response_model.__name__,
        )

        response = await client.beta.chat.completions.parse(
            model=model,
            max_tokens=1024,
            temperature=0.3,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            response_format=response_model,
        )

        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("OpenAI returned no parsed response")
        return parsed

    else:
        raise ValueError(f"Unknown LLM provider: {provider}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


SUMMARY_SYSTEM = (
    "You are a geospatial metadata specialist following ISO 19115 conventions. "
    "Generate a concise, informative abstract for this dataset. The summary should "
    "describe what the dataset contains, its geographic scope (use the bounding box "
    "to describe the coverage area in human terms if you can confidently identify "
    "the region; otherwise describe it using the coordinate values directly), "
    "temporal scope if apparent, intended audience, and potential uses. "
    "Write 2-4 sentences.\n\n"
    "Example:\n"
    "Input: Municipal boundaries, 42,000 features, bounding box: -124.8, 24.4, -66.9, 49.4.\n"
    "Output: Municipal boundary polygons covering the contiguous United States with "
    "approximately 42,000 features. Contains administrative boundaries suitable for "
    "jurisdiction-based analysis, service area delineation, and regional planning."
)

KEYWORD_SYSTEM = (
    "You are a geospatial metadata specialist following FGDC CSDGM conventions. "
    "Suggest 5-10 descriptive keywords for this dataset. Classify each keyword as "
    "one of: theme (topical subject), place (geographic location), or temporal "
    "(time period). Prefer ISO 19115 Topic Categories for theme keywords when "
    "applicable (e.g., transportation, boundaries, elevation, environment, "
    "inlandWaters, structure, planningCadastre, society, biota, climatologyMeteorologyAtmosphere). "
    "Return lowercase keywords for free-text terms. Use the exact ISO 19115 "
    "camelCase spelling for topic categories (e.g., planningCadastre, inlandWaters, "
    "transportation).\n\n"
    "Example:\n"
    "Input: National Parks polygons, US extent, established dates, acreage.\n"
    'Output: [{"keyword": "environment", "keyword_type": "theme"}, '
    '{"keyword": "planningCadastre", "keyword_type": "theme"}, '
    '{"keyword": "protected areas", "keyword_type": "theme"}, '
    '{"keyword": "national parks", "keyword_type": "theme"}, '
    '{"keyword": "united states", "keyword_type": "place"}, '
    '{"keyword": "2024", "keyword_type": "temporal"}]'
)

LINEAGE_SYSTEM = (
    "You are a geospatial metadata specialist following ISO 19115 conventions. "
    "Generate a lineage summary describing the origin of this dataset. "
    "ONLY describe processing steps that can be directly inferred from the metadata: "
    "if the original SRID differs from the current SRID (4326), note the reprojection; "
    "if the source format differs from PostGIS, note the format conversion. "
    "Do NOT speculate about cleaning, filtering, validation, or other processing steps "
    "unless explicitly stated in the source metadata. "
    "Write 1-3 sentences.\n\n"
    "Example:\n"
    "Input: Source format: Shapefile, Original SRID: 2263, Current SRID: 4326.\n"
    "Output: Data originally provided as ESRI Shapefile in NAD83 / New York Long Island "
    "(EPSG:2263). Reprojected to WGS 84 (EPSG:4326) and converted to PostGIS format "
    "during ingestion."
)

QUALITY_STATEMENT_SYSTEM = (
    "You are a geospatial metadata specialist following ISO 19115 conventions. "
    "Generate a quality statement for this dataset. If computed quality metrics "
    "are provided, reference them directly (e.g., null percentages, geometry "
    "validity rates). If no quality metrics are available, state that quality "
    "has not been formally assessed rather than speculating. "
    "Address: completeness (feature count, attribute population), logical "
    "consistency (if geometry validity data is provided), and coordinate "
    "reference system. Do NOT claim specific accuracy levels without evidence. "
    "Write 2-4 sentences.\n\n"
    "Example:\n"
    "Input: 12,500 features, 98.2% geometry validity, CRS: EPSG:4326, "
    "attribute completeness: 94%.\n"
    "Output: Dataset contains 12,500 features with 98.2% valid geometries and 94% "
    "attribute completeness. Data is stored in WGS 84 (EPSG:4326). A small number "
    "of geometries (1.8%) have validity issues that may affect spatial operations."
)


async def generate_summary_draft(
    session: AsyncSession,
    dataset_id: str,
    *,
    language: str | None = None,
    port: "ProcessingPort",
) -> SummaryDraftResponse:
    """Generate an AI-drafted summary for a dataset."""
    from app.processing.ai.chat_service import lang_name

    context = await _build_dataset_context(session, dataset_id, port=port)
    system = SUMMARY_SYSTEM
    if language:
        system += f"\n\nRespond in {lang_name(language)}."
    return await _generate_structured(system, context, SummaryDraftResponse, db=session)


async def generate_keyword_suggestions(
    session: AsyncSession,
    dataset_id: str,
    *,
    language: str | None = None,
    port: "ProcessingPort",
) -> KeywordSuggestionsResponse:
    """Generate AI-suggested keywords for a dataset."""
    from app.processing.ai.chat_service import lang_name

    context = await _build_dataset_context(session, dataset_id, port=port)
    vocab = await _get_catalog_vocabulary(session, port=port)
    related_kws = await _get_related_keywords_from_embeddings(session, dataset_id, port=port)

    prompt = context
    if vocab:
        prompt += (
            "\n\nExisting catalog vocabulary (prefer these when appropriate): "
            + ", ".join(vocab)
        )
    if related_kws:
        prompt += f"\n\nKeywords from similar datasets: {', '.join(related_kws)}"

    system = KEYWORD_SYSTEM
    if language:
        system += f"\n\nRespond in {lang_name(language)}."
    return await _generate_structured(
        system, prompt, KeywordSuggestionsResponse, db=session
    )


async def generate_lineage_draft(
    session: AsyncSession,
    dataset_id: str,
    *,
    language: str | None = None,
    port: "ProcessingPort",
) -> LineageDraftResponse:
    """Generate an AI-drafted lineage summary for a dataset."""
    from app.processing.ai.chat_service import lang_name

    context = await _build_dataset_context(session, dataset_id, port=port)
    system = LINEAGE_SYSTEM
    if language:
        system += f"\n\nRespond in {lang_name(language)}."
    return await _generate_structured(system, context, LineageDraftResponse, db=session)


async def generate_quality_statement_draft(
    session: AsyncSession,
    dataset_id: str,
    *,
    language: str | None = None,
    port: "ProcessingPort",
) -> QualityStatementDraftResponse:
    """Generate an AI-drafted quality statement for a dataset."""
    from app.processing.ai.chat_service import lang_name

    context = await _build_dataset_context(session, dataset_id, port=port)
    # Strip existing quality statement to force derivation from metrics, not paraphrasing
    context_lines = [
        line
        for line in context.split("\n")
        if not line.startswith("Current quality statement:")
    ]
    context = "\n".join(context_lines)
    system = QUALITY_STATEMENT_SYSTEM
    if language:
        system += f"\n\nRespond in {lang_name(language)}."
    return await _generate_structured(
        system, context, QualityStatementDraftResponse, db=session
    )

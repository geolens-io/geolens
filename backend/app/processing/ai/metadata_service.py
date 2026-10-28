"""Metadata generation service with dual-provider (Anthropic/OpenAI) support.

Builds rich prompts from dataset context and generates structured drafts
for summaries, keywords, and lineage using LLM providers.
"""

import json
import time
import uuid
from typing import TYPE_CHECKING

import structlog
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.processing.ai.metadata_schemas import (
    KeywordSuggestionsResponse,
    LineageDraftResponse,
    QualityStatementDraftResponse,
    SummaryDraftResponse,
)
from app.core.ai_credentials import anthropic_configured
from app.core.db import release_connection
from app.core.geo import extent_to_bbox
from app.core.identity import Identity
from app.platform.cache import tenant_cache_key
from app.platform.extensions import get_ai_provider
from app.processing.embeddings.helpers import get_nearest_record_ids
from app.core.persistent_config import (
    LLM_MODEL_LIGHT,
    LLM_PROVIDER,
    llm_model_default,
)
from app.processing.ai.service import _should_send_sample_values
from app.processing.ai.token_usage import record_token_usage, usage_accounting

if TYPE_CHECKING:
    from app.core.processing_port import ProcessingPort

logger = structlog.stdlib.get_logger(__name__)

# In-memory TTL cache for metadata AI, so a user clicking Summary, Keywords and
# Lineage in quick succession doesn't repeat the DB queries.
_CACHE_TTL = 60.0  # seconds
_dataset_context_cache: dict[str, tuple[float, str]] = {}


def _describe_extent(bounds: tuple[float, float, float, float]) -> str:
    """Describe a west, south, east, north bbox as signed longitude and latitude ranges.

    Bare W/S/E/N labels beside positive numbers read as hemisphere letters to some
    models. A seam-crossing extent keeps west > east instead of a global footprint,
    and says so, because west > east alone reads as a typo.
    """
    west, south, east, north = bounds
    crossing = " (crosses the antimeridian)" if west > east else ""
    return (
        "Extent in signed decimal degrees (negative longitude is west, negative "
        f"latitude is south): longitude {west:.4f} to {east:.4f}{crossing}, "
        f"latitude {south:.4f} to {north:.4f}"
    )


async def _build_dataset_context(
    session: AsyncSession,
    dataset_id: str,
    *,
    port: "ProcessingPort",
) -> str:
    """Load dataset with relationships and build a context string for prompts."""
    import uuid as _uuid

    send_samples = await _should_send_sample_values(session)
    now = time.monotonic()
    cache_key = tenant_cache_key(f"{dataset_id}:samples={send_samples}")
    cached = _dataset_context_cache.get(cache_key)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]

    dataset = await port.get_dataset_with_attributes(session, _uuid.UUID(dataset_id))

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

    # Left out for a VRT: its stored extent covers members a requester may not
    # read, and this context is cached for every requester.
    if record.spatial_extent is not None and record.record_type != "vrt_dataset":
        bounds = extent_to_bbox(record.spatial_extent)
        if bounds is None:
            logger.debug("Failed to parse spatial bounds for AI context")
        else:
            parts.append(_describe_extent(bounds))

    if record.access_constraints:
        parts.append(f"Access constraints: {record.access_constraints}")

    if dataset.column_info:
        col_strs = []
        for col in dataset.column_info[:30]:
            col_strs.append(f"  - {col.get('name', '?')}: {col.get('type', '?')}")
        parts.append("Columns:\n" + "\n".join(col_strs))

    # Null and cardinality stats for up to 20 non-geometry columns. A missing
    # or erroring table degrades to a less-grounded summary, not a failure.
    if dataset.column_info and dataset.table_name:
        non_geom_cols = [
            c.get("name", "")
            for c in dataset.column_info[:30]
            if c.get("name") and "geometry" not in c.get("type", "").lower()
        ]
        if non_geom_cols:
            try:
                stats = await port.get_column_null_cardinality(
                    session,
                    dataset.table_name,
                    non_geom_cols,
                    max_columns=20,
                )
            except Exception:  # broad: stats lookup is non-fatal context enrichment
                logger.debug("Column null/cardinality lookup failed", exc_info=True)
                stats = {}
            if stats:
                lines = []
                for col_name, s in stats.items():
                    total = s.get("total_count") or 0
                    null_count = s.get("null_count") or 0
                    distinct_count = s.get("distinct_count") or 0
                    null_pct = (null_count / total * 100) if total else 0
                    approx = " (approximate)" if s.get("approximate") else ""
                    lines.append(
                        f"  - {col_name}: {null_pct:.1f}% null, "
                        f"{distinct_count} distinct{approx}"
                    )
                parts.append("Column statistics:\n" + "\n".join(lines))

    # Capped at 10 columns x 5 values before json.dumps, so JSON is never cut.
    if send_samples and dataset.sample_values:
        truncated_samples = {}
        for col, vals in list(dataset.sample_values.items())[:10]:
            truncated_samples[col] = vals[:5] if isinstance(vals, list) else vals
        sample_str = json.dumps(truncated_samples, default=str)
        parts.append(f"Sample values: {sample_str}")

    if record.keywords:
        kw_list = [kw.keyword for kw in record.keywords]
        parts.append(f"Existing keywords: {', '.join(kw_list)}")

    current_attrs = [a for a in dataset.attributes if a.is_current][:20]
    if current_attrs:
        attr_strs = []
        for attr in current_attrs:
            desc = f" - {attr.description}" if attr.description else ""
            attr_strs.append(f"  - {attr.field_name} ({attr.data_type or '?'}){desc}")
        parts.append("Attribute metadata:\n" + "\n".join(attr_strs))

    if hasattr(dataset, "quality_detail") and dataset.quality_detail:
        qd = json.dumps(dataset.quality_detail, default=str)
        if len(qd) > 1000:
            qd = qd[:1000] + "..."
        parts.append(f"Quality metrics (computed): {qd}")

    if hasattr(dataset, "quality_statement") and dataset.quality_statement:
        parts.append(f"Current quality statement: {dataset.quality_statement}")

    if record.temporal_start:
        parts.append(f"Temporal start: {record.temporal_start}")
    if record.temporal_end:
        parts.append(f"Temporal end: {record.temporal_end}")

    if hasattr(record, "record_type") and record.record_type:
        parts.append(f"Record type: {record.record_type}")

    result = "\n".join(parts)
    # Cache holds at most 20 entries; evict the oldest.
    if len(_dataset_context_cache) >= 20:
        oldest_key = min(
            _dataset_context_cache, key=lambda k: _dataset_context_cache[k][0]
        )
        del _dataset_context_cache[oldest_key]
    _dataset_context_cache[cache_key] = (now, result)
    return result


async def _get_related_keywords_from_embeddings(
    session: AsyncSession,
    dataset_id: str,
    limit: int = 5,
    *,
    port: "ProcessingPort",
    user: Identity,
    user_roles: set[str],
) -> list[str]:
    """Return keywords from the top-N nearest datasets by embedding similarity.

    Only neighbors ``user`` may read contribute keywords. Falls back to an
    empty list on no embedding or any error. Not cached, because the result
    depends on the caller's visibility.

    The dataset lookup and keyword aggregation go through the Port, so
    processing/* carries no ``app.modules.catalog`` ORM import and overlays
    can intercept both calls.
    """
    import uuid as _uuid

    try:
        dataset = await port.get_dataset(session, _uuid.UUID(dataset_id))
        if dataset is None or dataset.record_id is None:
            return []

        neighbor_ids = await get_nearest_record_ids(
            session,
            dataset.record_id,
            limit=limit,
            restrict=lambda stmt: port.apply_visibility_filter(
                stmt,
                user,
                user_roles,
                port.get_record_orm_class(),
                port.get_grant_orm_class(),
            ),
        )
        if not neighbor_ids:
            return []

        return await port.get_keywords_for_records(
            session, neighbor_ids, user=user, user_roles=user_roles
        )
    except Exception:  # broad: embedding neighbor lookup is non-fatal context-builder; degrade to empty list
        logger.debug("Embedding neighbor keyword lookup failed", exc_info=True)
        return []


async def _generate_structured(
    system: str,
    prompt: str,
    response_model: type[BaseModel],
    db: AsyncSession | None = None,
    user_id: uuid.UUID | None = None,
) -> BaseModel:
    """Generate structured output through the configured AI provider.

    Records token usage (subsystem ``metadata``) so metadata-assist calls count
    toward the per-user daily budget; otherwise the cap is bypassable through
    the four ``/ai/metadata/*`` endpoints.
    """
    provider = (
        await LLM_PROVIDER.get(db)
        if db is not None
        else ("anthropic" if anthropic_configured() else "openai_compatible")
    )
    provider_ext = get_ai_provider(provider)
    runtime_config = (
        await provider_ext.resolve_runtime_config(db) if db is not None else {}
    )
    model = (
        await LLM_MODEL_LIGHT.for_provider(db, provider, runtime_config)
        if db is not None
        else llm_model_default(provider, light=True)
    )
    if db is not None:
        await release_connection(db)
    async with usage_accounting(db, user_id=user_id, subsystem="metadata", model=model):
        result, input_tokens, output_tokens = await provider_ext.structured_complete(
            model=model,
            system_prompt=system,
            user_message=prompt,
            response_model=response_model,
            base_url=runtime_config.get("base_url"),
            max_tokens=1024,
            temperature=0.3,
        )
    await record_token_usage(
        user_id=user_id,
        subsystem="metadata",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    return result


SUMMARY_SYSTEM = (
    "You are a geospatial metadata specialist following ISO 19115 conventions. "
    "Write a concise abstract for this dataset in 2-4 sentences, using only what "
    "the metadata below supports: the title, filename, geometry type, feature "
    "count, columns, column statistics, sample values, extent and temporal "
    "fields.\n\n"
    "- Describe what the features are and the attributes they carry.\n"
    "- Describe the geographic scope from the extent. Name the area in human "
    "terms when the coordinates or sample values clearly identify it; otherwise "
    "give the coordinate ranges.\n"
    "- State a time period only when temporal fields, date columns or sample "
    "values show one. Otherwise say nothing about time.\n"
    "- Do not name a publisher, maintainer or source agency, or describe an "
    "intended audience, unless the metadata states it.\n"
    "- You may add one sentence on likely uses. End that sentence with "
    '"(inferred)" so a reviewer can tell it from the facts. If you respond in '
    "another language, translate the marker.\n\n"
    "Example:\n"
    "Input: Title: Municipal Boundaries. Geometry type: MultiPolygon. Feature "
    "count: 42000. Columns: name, state_fips, population. Extent: longitude "
    "-124.8 to -66.9, latitude 24.4 to 49.4.\n"
    "Output: Municipal boundary polygons covering the contiguous United States, "
    "with about 42,000 features carrying a name, a state FIPS code and a "
    "population count. Likely uses include jurisdiction-based analysis and "
    "regional planning (inferred)."
)

KEYWORD_SYSTEM = (
    "You are a geospatial metadata specialist following FGDC CSDGM conventions. "
    "Suggest 5-10 descriptive keywords for this dataset. Classify each keyword as "
    "one of: theme (topical subject), place (geographic location), or temporal "
    "(time period). For theme keywords, prefer ISO 19115 Topic Categories when "
    "applicable. The full topic category list: farming, biota, boundaries, "
    "climatologyMeteorologyAtmosphere, economy, elevation, environment, "
    "geoscientificInformation, health, imageryBaseMapsEarthCover, "
    "intelligenceMilitary, inlandWaters, location, oceans, planningCadastre, "
    "society, structure, transportation, utilitiesCommunication.\n\n"
    "## Case rules (these are NOT the same)\n"
    "- ISO 19115 topic categories: return in exact camelCase as listed above "
    "(e.g., 'planningCadastre', NOT 'planning_cadastre', 'planning cadastre', "
    "or 'planningcadastre').\n"
    "- All other free-text keywords (themes not in the ISO list, places, "
    "temporal): return in lowercase (e.g., 'national parks', 'united states', "
    "'2024').\n\n"
    "## Grounding\n"
    "- Place keywords: only places the extent, title, filename or sample values "
    "identify.\n"
    "- Temporal keywords: only a period that temporal fields, date columns or "
    "sample values show. With no such evidence, suggest none.\n\n"
    "Example:\n"
    "Input: National Parks polygons, US extent, acreage, no date columns.\n"
    'Output: [{"keyword": "environment", "keyword_type": "theme"}, '
    '{"keyword": "planningCadastre", "keyword_type": "theme"}, '
    '{"keyword": "protected areas", "keyword_type": "theme"}, '
    '{"keyword": "national parks", "keyword_type": "theme"}, '
    '{"keyword": "united states", "keyword_type": "place"}]'
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
    "Example 1 (with metrics):\n"
    "Input: 12,500 features, 98.2% geometry validity, CRS: EPSG:4326, "
    "attribute completeness: 94%.\n"
    "Output: Dataset contains 12,500 features with 98.2% valid geometries and 94% "
    "attribute completeness. Data is stored in WGS 84 (EPSG:4326). A small number "
    "of geometries (1.8%) have validity issues that may affect spatial operations.\n\n"
    "Example 2 (no metrics available):\n"
    "Input: 8,400 features, CRS: EPSG:4326, no computed quality metrics.\n"
    "Output: Dataset contains 8,400 features stored in WGS 84 (EPSG:4326). "
    "Quality has not been formally assessed; geometry validity, attribute "
    "completeness, and positional accuracy are unknown. Users should validate "
    "the data for their intended use before relying on it for analysis."
)


async def generate_summary_draft(
    session: AsyncSession,
    dataset_id: str,
    *,
    language: str | None = None,
    port: "ProcessingPort",
    user_id: uuid.UUID | None = None,
) -> SummaryDraftResponse:
    """Generate an AI-drafted summary for a dataset."""
    from app.processing.ai.chat_service import lang_name

    context = await _build_dataset_context(session, dataset_id, port=port)
    # Strip the existing summary so the LLM derives from data instead of
    # paraphrasing it.
    context = "\n".join(
        line for line in context.split("\n") if not line.startswith("Current summary:")
    )
    system = SUMMARY_SYSTEM
    if language:
        system += f"\n\nRespond in {lang_name(language)}."
    return await _generate_structured(
        system, context, SummaryDraftResponse, db=session, user_id=user_id
    )


async def generate_keyword_suggestions(
    session: AsyncSession,
    dataset_id: str,
    *,
    language: str | None = None,
    port: "ProcessingPort",
    user: Identity,
    user_roles: set[str],
) -> KeywordSuggestionsResponse:
    """Generate AI-suggested keywords for a dataset.

    The vocabulary and similar-dataset keywords added to the prompt come only
    from records ``user`` may read.
    """
    from app.processing.ai.chat_service import lang_name

    context = await _build_dataset_context(session, dataset_id, port=port)
    vocab = await port.get_catalog_vocabulary(session, user=user, user_roles=user_roles)
    related_kws = await _get_related_keywords_from_embeddings(
        session, dataset_id, port=port, user=user, user_roles=user_roles
    )

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
        system, prompt, KeywordSuggestionsResponse, db=session, user_id=user.id
    )


async def generate_lineage_draft(
    session: AsyncSession,
    dataset_id: str,
    *,
    language: str | None = None,
    port: "ProcessingPort",
    user_id: uuid.UUID | None = None,
) -> LineageDraftResponse:
    """Generate an AI-drafted lineage summary for a dataset."""
    from app.processing.ai.chat_service import lang_name

    context = await _build_dataset_context(session, dataset_id, port=port)
    # Strip the existing lineage so the LLM derives from SRID/format deltas
    # instead of paraphrasing it.
    context = "\n".join(
        line for line in context.split("\n") if not line.startswith("Current lineage:")
    )
    system = LINEAGE_SYSTEM
    if language:
        system += f"\n\nRespond in {lang_name(language)}."
    return await _generate_structured(
        system, context, LineageDraftResponse, db=session, user_id=user_id
    )


async def generate_quality_statement_draft(
    session: AsyncSession,
    dataset_id: str,
    *,
    language: str | None = None,
    port: "ProcessingPort",
    user_id: uuid.UUID | None = None,
) -> QualityStatementDraftResponse:
    """Generate an AI-drafted quality statement for a dataset."""
    from app.processing.ai.chat_service import lang_name

    context = await _build_dataset_context(session, dataset_id, port=port)
    # Strip the existing statement so it derives from metrics, not paraphrase.
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
        system, context, QualityStatementDraftResponse, db=session, user_id=user_id
    )

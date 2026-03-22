"""Metadata generation service with dual-provider (Anthropic/OpenAI) support.

Builds rich prompts from dataset context and generates structured drafts
for summaries, keywords, and lineage using LLM providers.
"""

import json

import structlog
from anthropic import AsyncAnthropic
from geoalchemy2.shape import to_shape
from openai import AsyncOpenAI
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.ai.metadata_schemas import (
    KeywordSuggestionsResponse,
    LineageDraftResponse,
    QualityStatementDraftResponse,
    SummaryDraftResponse,
)
from app.config import settings
from app.datasets.models import (
    Dataset,
    Record,
    RecordKeyword,
)
from app.embeddings.helpers import get_nearest_record_ids
from app.persistent_config import LLM_MODEL, LLM_PROVIDER, OPENAI_BASE_URL

logger = structlog.stdlib.get_logger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _build_dataset_context(session: AsyncSession, dataset_id: str) -> str:
    """Load dataset with relationships and build a context string for prompts."""
    stmt = (
        select(Dataset)
        .options(
            joinedload(Dataset.record).joinedload(Record.keywords),
            joinedload(Dataset.attributes),
        )
        .where(Dataset.id == dataset_id)
    )
    result = await session.execute(stmt)
    dataset = result.unique().scalar_one_or_none()

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
            pass

    if record.access_constraints:
        parts.append(f"Access constraints: {record.access_constraints}")

    # Column info
    if dataset.column_info:
        col_strs = []
        for col in dataset.column_info[:30]:
            col_strs.append(f"  - {col.get('name', '?')}: {col.get('type', '?')}")
        parts.append("Columns:\n" + "\n".join(col_strs))

    # Sample values (truncated)
    if dataset.sample_values:
        sample_str = json.dumps(dataset.sample_values, default=str)
        if len(sample_str) > 2000:
            sample_str = sample_str[:2000] + "..."
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

    return "\n".join(parts)


async def _get_catalog_vocabulary(session: AsyncSession) -> list[str]:
    """Return up to 200 distinct keywords from the catalog."""
    stmt = select(RecordKeyword.keyword).distinct().limit(200)
    result = await session.execute(stmt)
    return [row[0] for row in result.all()]


async def _get_related_keywords_from_embeddings(
    session: AsyncSession, dataset_id: str, limit: int = 5
) -> list[str]:
    """Return keywords from the top-N nearest datasets by embedding similarity.

    Falls back to empty list if dataset has no embedding or on any error.
    """
    try:
        # Get the dataset's record_id
        ds_stmt = select(Dataset.record_id).where(Dataset.id == dataset_id)
        ds_result = await session.execute(ds_stmt)
        record_id = ds_result.scalar_one_or_none()
        if not record_id:
            return []

        neighbor_ids = await get_nearest_record_ids(session, record_id, limit=limit)
        if not neighbor_ids:
            return []

        # Get keywords from those records
        kw_stmt = (
            select(RecordKeyword.keyword)
            .where(RecordKeyword.record_id.in_(neighbor_ids))
            .distinct()
        )
        kw_result = await session.execute(kw_stmt)
        return [row[0] for row in kw_result.all()]
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
        await LLM_MODEL.get(db)
        if db is not None
        else (
            settings.llm_model if settings.anthropic_api_key else settings.openai_model
        )
    )

    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError("Anthropic API key not configured")
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)

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
        client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=base_url,
        )

        logger.info(
            "AI metadata request",
            provider="openai",
            model=model,
            response_model=response_model.__name__,
        )

        response = await client.beta.chat.completions.parse(
            model=model,
            max_tokens=1024,
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
    "You are a geospatial metadata specialist following FGDC CSDGM conventions. "
    "Generate a concise, informative abstract for this dataset. The summary should "
    "describe what the dataset contains, its geographic scope (use the bounding box "
    "to describe the coverage area in human terms, e.g., 'continental United States'), "
    "temporal scope if apparent, intended audience, and potential uses. "
    "Write 2-4 sentences."
)

KEYWORD_SYSTEM = (
    "You are a geospatial metadata specialist following FGDC CSDGM conventions. "
    "Suggest 5-10 descriptive keywords for this dataset. Classify each keyword as "
    "one of: theme (topical subject), place (geographic location), or temporal "
    "(time period). Prefer ISO 19115 Topic Categories for theme keywords when "
    "applicable (e.g., transportation, boundaries, elevation, environment, "
    "inlandWaters, structure, planningCadastre, society, biota, climatologyMeteorologyAtmosphere). "
    "Also prefer keywords from the existing catalog vocabulary when appropriate. "
    "Return lowercase keywords."
)

LINEAGE_SYSTEM = (
    "You are a geospatial metadata specialist following FGDC CSDGM conventions. "
    "Generate a lineage summary describing the origin and processing history of "
    "this dataset, following the FGDC Data Quality Lineage model. Include: the "
    "source data (format, organization, original CRS), any processing steps "
    "(coordinate transformations, format conversions, filtering), and data "
    "provenance. Write 1-3 sentences."
)

QUALITY_STATEMENT_SYSTEM = (
    "You are a geospatial metadata specialist following FGDC CSDGM conventions. "
    "Generate a quality statement describing the overall data quality of this "
    "dataset. Address these FGDC Data Quality elements where evidence is available: "
    "positional accuracy, attribute accuracy, logical consistency (geometry validity, "
    "topological correctness), and completeness (feature count, attribute population). "
    "Note the coordinate reference system definition and any known limitations. "
    "Write 2-4 sentences."
)


async def generate_summary_draft(
    session: AsyncSession, dataset_id: str
) -> SummaryDraftResponse:
    """Generate an AI-drafted summary for a dataset."""
    context = await _build_dataset_context(session, dataset_id)
    return await _generate_structured(
        SUMMARY_SYSTEM, context, SummaryDraftResponse, db=session
    )


async def generate_keyword_suggestions(
    session: AsyncSession, dataset_id: str
) -> KeywordSuggestionsResponse:
    """Generate AI-suggested keywords for a dataset."""
    context = await _build_dataset_context(session, dataset_id)
    vocab = await _get_catalog_vocabulary(session)
    related_kws = await _get_related_keywords_from_embeddings(session, dataset_id)

    prompt = context
    if vocab:
        prompt += f"\n\nExisting catalog vocabulary: {', '.join(vocab)}"
    if related_kws:
        prompt += f"\n\nKeywords from similar datasets: {', '.join(related_kws)}"

    return await _generate_structured(
        KEYWORD_SYSTEM, prompt, KeywordSuggestionsResponse, db=session
    )


async def generate_lineage_draft(
    session: AsyncSession, dataset_id: str
) -> LineageDraftResponse:
    """Generate an AI-drafted lineage summary for a dataset."""
    context = await _build_dataset_context(session, dataset_id)
    return await _generate_structured(
        LINEAGE_SYSTEM, context, LineageDraftResponse, db=session
    )


async def generate_quality_statement_draft(
    session: AsyncSession, dataset_id: str
) -> QualityStatementDraftResponse:
    """Generate an AI-drafted quality statement for a dataset."""
    context = await _build_dataset_context(session, dataset_id)
    return await _generate_structured(
        QUALITY_STATEMENT_SYSTEM, context, QualityStatementDraftResponse, db=session
    )

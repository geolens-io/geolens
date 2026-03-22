"""AI map generation service: LLM orchestration with tool calling."""

import json
import re
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from collections.abc import AsyncGenerator

from app.ai.constants import tool_label
from app.ai.llm_loop import ToolLoopExhaustedError, resolve_provider, run_tool_loop
from app.ai.schemas import LLMMapSpec, validate_paint_for_geometry
from app.ai.tools import (
    _GET_DATASET_DETAILS_DESC,
    _GET_DATASET_DETAILS_SCHEMA,
    _SEARCH_DATASETS_DESC,
    _SEARCH_DATASETS_SCHEMA,
)
from app.auth.models import User
from app.config import settings
from app.auth.visibility import apply_visibility_filter
from app.datasets.models import Dataset, DatasetGrant, Record
from app.datasets.utils import extract_bbox
from app.maps.service import create_map, update_map
from app.search.service import search_datasets

logger = structlog.stdlib.get_logger(__name__)

SYSTEM_PROMPT = """\
You are a GIS map designer. The user will describe what map they want, and you \
must search the dataset catalog, select appropriate datasets, and design a map.

## Workflow
1. Search the catalog using the search_datasets tool. Try multiple search \
   strategies if the first doesn't find what you need:
   - Start with short, broad terms (e.g. "preserved lands" instead of \
     "New Jersey Highlands Preserved Lands")
   - Drop geographic qualifiers — dataset titles often omit region names
   - Try synonyms (e.g. "conservation" for "preserved", "parcels" for "lands")
   - Search for each major concept separately if a combined query fails
2. Select the best-matching datasets. If you plan data-driven styling, call \
   get_dataset_details to see column info and sample values.
3. Design the map with proper layer ordering, distinct styling, and an \
   appropriate viewport.

## Layer ordering
- Polygons/fills at the bottom (lowest sort_order)
- Lines in the middle
- Points on top (highest sort_order)

## Styling
Use distinct colors for each layer. Suggested palette:
- #3b82f6 (blue), #ef4444 (red), #22c55e (green), #f59e0b (amber),
  #8b5cf6 (purple), #ec4899 (pink), #06b6d4 (cyan), #f97316 (orange)

For polygons: use fill-opacity 0.2-0.4 with a darker fill-outline-color.
For lines: use line-width 1.5-3.
For points: use circle-radius 4-6 with a stroke.

IMPORTANT: Use the correct paint properties for each geometry type:
- Polygon/MultiPolygon: fill-color, fill-opacity, fill-outline-color
- LineString/MultiLineString: line-color, line-width, line-opacity
- Point/MultiPoint: circle-color, circle-radius, circle-stroke-color, circle-stroke-width
Do NOT mix properties across geometry types (e.g. no fill-color on a point layer).

## Data-Driven Styling
When a dataset has a column that is well-suited for thematic visualization, use data-driven paint expressions:

- **Categorical** (text/string columns like land_use, type, status):
  Use a "match" expression: ["match", ["get", "column_name"], "value1", "#color1", "value2", "#color2", ..., "#cccccc"]
  First call get_dataset_details to see sample values for the column.

- **Graduated** (numeric columns like population, area, elevation):
  Use a "step" expression: ["step", ["get", "column_name"], "#color1", break1, "#color2", break2, "#color3", ...]
  First call get_dataset_details to understand the value range.

- **Continuous** (numeric columns where smooth transitions make sense):
  Use an "interpolate" expression: ["interpolate", ["linear"], ["get", "column_name"], min, "#startColor", max, "#endColor"]

Available color ramps (use these hex values):
- YlOrRd: #ffffb2, #fecc5c, #fd8d3c, #f03b20, #bd0026
- Viridis: #440154, #3b528b, #21918c, #5ec962, #fde725
- Blues: #eff3ff, #bdd7e7, #6baed6, #3182bd, #08519c
- Cividis (colorblind-safe): #002051, #3b4f6b, #6d7e53, #b4a436, #fdca26
- PuOr (colorblind-safe diverging): #e66101, #fdb863, #f7f7f7, #b2abd2, #5e3c99

When to apply data-driven styling:
- The user asks for thematic or choropleth maps (e.g., "show population density")
- A dataset has an obvious thematic column (e.g., "land_use", "category", "status")
- The user mentions coloring by a specific attribute

When NOT to apply:
- Simple display maps where the user just wants to see features
- The user specifically asks for a single color

## Viewport
Set center_lng, center_lat, and zoom based on dataset extents. If datasets \
cover a whole country, zoom 4-6. If they cover a city, zoom 10-13.

## Basemap
{basemap_instruction}

## Output
After gathering datasets, output your map specification as JSON inside \
<map_spec> tags:

<map_spec>
{{
  "name": "Map title",
  "description": "Brief description",
  "center_lng": -98.5,
  "center_lat": 39.8,
  "zoom": 4,
  "basemap_style": "positron",
  "layers": [
    {{
      "dataset_id": "uuid-here",
      "sort_order": 0,
      "visible": true,
      "opacity": 1.0,
      "paint": {{"fill-color": "#3b82f6", "fill-opacity": 0.3, "fill-outline-color": "#1d4ed8"}},
      "layout": {{}}
    }}
  ],
  "explanation": "I selected X and Y datasets because..."
}}
</map_spec>

If no matching datasets exist, output:
<map_spec>
{{"error": "No matching datasets found. The catalog does not contain datasets for: ..."}}
</map_spec>

"""

_DEFAULT_BASEMAP_INSTRUCTION = (
    "Choose from: positron (light, default), dark_matter (dark), voyager (colorful)."
)


def _build_basemap_instruction(basemap_ids: list[str] | None) -> str:
    """Build basemap instruction from available basemap IDs."""
    if basemap_ids:
        choices = ", ".join(basemap_ids)
        return f"Choose from: {choices}. Use 'positron' if unsure."
    return _DEFAULT_BASEMAP_INSTRUCTION


async def _get_available_basemaps(session: AsyncSession) -> list[str] | None:
    """Fetch available basemap IDs from admin settings."""
    try:
        from app.persistent_config import BASEMAPS

        basemaps = await BASEMAPS.get(session)
        if basemaps and isinstance(basemaps, list):
            return [
                b.get("id") or b.get("key", "") for b in basemaps if isinstance(b, dict)
            ]
    except Exception:
        pass
    return None


def _build_map_system_prompt(
    language: str | None = None,
    basemap_ids: list[str] | None = None,
) -> str:
    """Build map generation system prompt with language directive and dynamic basemaps."""
    from app.ai.chat_service import _lang_name

    basemap_instruction = _build_basemap_instruction(basemap_ids)
    prompt = SYSTEM_PROMPT.format(basemap_instruction=basemap_instruction)

    lang = _lang_name(language)
    prompt += f"""
## Language
Always respond in {lang}. The explanation field and any text must be in {lang}. Never switch to another language.
"""
    return prompt


# Anthropic tool format (schema sourced from tools.py)
ANTHROPIC_TOOLS = [
    {
        "name": "search_datasets",
        "description": _SEARCH_DATASETS_DESC,
        "input_schema": _SEARCH_DATASETS_SCHEMA,
    },
    {
        "name": "get_dataset_details",
        "description": _GET_DATASET_DETAILS_DESC,
        "input_schema": _GET_DATASET_DETAILS_SCHEMA,
    },
]

# OpenAI tool format (schema sourced from tools.py)
OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_datasets",
            "description": _SEARCH_DATASETS_DESC,
            "parameters": _SEARCH_DATASETS_SCHEMA,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dataset_details",
            "description": _GET_DATASET_DETAILS_DESC,
            "parameters": _GET_DATASET_DETAILS_SCHEMA,
        },
    },
]


async def _execute_search_tool(
    session: AsyncSession,
    user: User,
    user_roles: set[str],
    tool_input: dict,
) -> list[dict]:
    """Execute the search_datasets tool and return results as dicts."""
    q = tool_input.get("q")
    geometry_type = tool_input.get("geometry_type")
    keywords = tool_input.get("keywords")
    limit = min(tool_input.get("limit", 10), 25)
    bbox = tool_input.get("bbox")

    datasets, _total = await search_datasets(
        session,
        user,
        user_roles,
        q=q,
        geometry_type=geometry_type,
        keywords=keywords,
        bbox=bbox,
        limit=limit,
    )

    results = []
    for ds in datasets:
        # Limit sample_values to 5 columns, 5 values each
        sample = {}
        if ds.sample_values:
            for k, v in list(ds.sample_values.items())[:5]:
                sample[k] = v[:5] if isinstance(v, list) else v

        results.append(
            {
                "id": str(ds.id),
                "title": ds.record.title,
                "summary": ds.record.summary,
                "geometry_type": ds.geometry_type,
                "keywords": [kw.keyword for kw in ds.record.keywords]
                if ds.record.keywords
                else None,
                "extent_bbox": extract_bbox(ds),
                "feature_count": ds.feature_count,
                "column_info": ds.column_info[:20] if ds.column_info else None,
                "sample_values": sample or None,
            }
        )

    return results


async def _execute_get_dataset_details(
    session: AsyncSession,
    user: User,
    user_roles: set[str],
    tool_input: dict,
) -> dict:
    """Return full column info, sample values, and feature count for a dataset."""
    dataset_id = tool_input.get("dataset_id")

    # Validate UUID format
    try:
        uuid.UUID(str(dataset_id))
    except (ValueError, AttributeError):
        return {"error": "Invalid dataset_id format"}

    # Apply RBAC visibility filter
    stmt = (
        select(Dataset)
        .options(joinedload(Dataset.record))
        .join(Record, Dataset.record_id == Record.id)
        .where(Dataset.id == dataset_id)
    )
    stmt = apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)
    result = await session.execute(stmt)
    ds = result.unique().scalar_one_or_none()
    if ds is None:
        return {"error": "Dataset not found"}

    # Cap column_info to 50 columns to bound token usage
    column_info = ds.column_info[:50] if ds.column_info else None

    # Limit sample_values to 5 values per column (all columns)
    sample = {}
    if ds.sample_values:
        for k, v in ds.sample_values.items():
            sample[k] = v[:5] if isinstance(v, list) else v

    return {
        "id": str(ds.id),
        "title": ds.record.title,
        "geometry_type": ds.geometry_type,
        "feature_count": ds.feature_count,
        "column_info": column_info,
        "sample_values": sample or None,
    }


def _parse_map_spec(text: str) -> dict:
    """Extract JSON from <map_spec> tags in LLM response."""
    match = re.search(r"<map_spec>\s*(.*?)\s*</map_spec>", text, re.DOTALL)
    if not match:
        raise ValueError("No <map_spec> block found in LLM response")
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed JSON in LLM map spec: {e}") from e


async def _retry_parse_map_spec(
    raw_text: str, provider: str, model: str, base_url: str | None
) -> dict:
    """Lightweight retry: ask the LLM to fix its JSON output without re-running tools."""
    extraction_prompt = (
        "The following text should contain a JSON map specification inside "
        "<map_spec> tags, but parsing failed. Output ONLY the corrected JSON "
        "inside <map_spec>...</map_spec> tags. Do not call any tools.\n\n"
        f"{raw_text}"
    )

    if provider == "anthropic":
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": extraction_prompt}],
        )
        retry_text = response.content[0].text
    else:
        from openai import AsyncOpenAI

        base = base_url or settings.openai_base_url or "https://api.openai.com/v1"
        client = AsyncOpenAI(api_key=settings.openai_api_key, base_url=base)
        response = await client.chat.completions.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": extraction_prompt}],
        )
        retry_text = response.choices[0].message.content or ""

    return _parse_map_spec(retry_text)


async def generate_map_from_prompt(
    session: AsyncSession,
    user: User,
    user_roles: set[str],
    prompt: str,
    language: str | None = None,
) -> dict:
    """Orchestrate LLM tool-calling loop to generate a map from a prompt.

    Provider and model are resolved from PersistentConfig (admin-overridable).
    Returns dict with map_id, map_name, explanation, datasets_used.
    """
    provider, model, base_url = await resolve_provider(session)

    # Fetch available basemaps for dynamic prompt injection
    basemap_ids = await _get_available_basemaps(session)
    system_prompt = _build_map_system_prompt(language, basemap_ids=basemap_ids)

    # Build tool executor bound to this session/user
    async def tool_executor(tool_name: str, tool_input: dict) -> dict:
        if tool_name == "search_datasets":
            return {
                "results": await _execute_search_tool(
                    session, user, user_roles, tool_input
                )
            }
        elif tool_name == "get_dataset_details":
            return await _execute_get_dataset_details(
                session, user, user_roles, tool_input
            )
        return {"error": f"Unknown tool: {tool_name}"}

    result = await run_tool_loop(
        provider=provider,
        model=model,
        system_prompt=system_prompt,
        user_message=prompt,
        tools_anthropic=ANTHROPIC_TOOLS,
        tools_openai=OPENAI_TOOLS,
        tool_executor=tool_executor,
        base_url=base_url,
    )

    logger.info(
        "Map generation complete",
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )

    # Parse the map spec from LLM output, with one lightweight retry
    try:
        spec_dict = _parse_map_spec(result.text)
    except ValueError:
        logger.warning("Map spec parse failed, retrying extraction only")
        spec_dict = await _retry_parse_map_spec(result.text, provider, model, base_url)

    # Check for error response
    if "error" in spec_dict:
        raise ValueError(spec_dict["error"])

    # Validate with pydantic
    spec = LLMMapSpec(**spec_dict)

    if not spec.layers:
        raise ValueError("LLM produced a map with no layers")

    # Look up geometry types for paint validation
    dataset_ids = [uuid.UUID(layer.dataset_id) for layer in spec.layers]
    ds_result = await session.execute(
        select(Dataset.id, Dataset.geometry_type, Record.title)
        .join(Record, Dataset.record_id == Record.id)
        .where(Dataset.id.in_(dataset_ids))
    )
    ds_info = {
        str(row[0]): {"geometry_type": row[1], "title": row[2]}
        for row in ds_result.all()
    }

    # Create the map using existing service functions
    map_obj = await create_map(
        session,
        name=spec.name,
        description=spec.description,
        created_by=user.id,
    )

    # Build layer dicts for update_map with paint validation
    layer_dicts = []
    for layer in spec.layers:
        info = ds_info.get(layer.dataset_id, {})
        validated_paint = validate_paint_for_geometry(
            layer.paint, info.get("geometry_type")
        )
        layer_dicts.append(
            {
                "dataset_id": uuid.UUID(layer.dataset_id),
                "sort_order": layer.sort_order,
                "visible": layer.visible,
                "opacity": layer.opacity,
                "paint": validated_paint,
                "layout": layer.layout,
            }
        )

    await update_map(
        session,
        map_obj.id,
        center_lng=spec.center_lng,
        center_lat=spec.center_lat,
        zoom=spec.zoom,
        basemap_style=spec.basemap_style,
        layers=layer_dicts,
    )

    dataset_names = [info.get("title", "") for info in ds_info.values()]

    return {
        "map_id": str(map_obj.id),
        "map_name": spec.name,
        "explanation": spec.explanation,
        "datasets_used": dataset_names,
    }


async def stream_generate_map(
    session: AsyncSession,
    user: User,
    user_roles: set[str],
    prompt: str,
    language: str | None = None,
) -> AsyncGenerator[dict, None]:
    """Streaming variant of generate_map_from_prompt.

    Yields progress events during the tool-calling loop, then the final result
    or error as a done/error event.
    """
    try:
        provider, model, base_url = await resolve_provider(session)
        basemap_ids = await _get_available_basemaps(session)
        system_prompt = _build_map_system_prompt(language, basemap_ids=basemap_ids)

        # Collect progress events via a wrapper around the tool executor
        async def tool_executor(tool_name: str, tool_input: dict) -> dict:
            if tool_name == "search_datasets":
                return {
                    "results": await _execute_search_tool(
                        session, user, user_roles, tool_input
                    )
                }
            elif tool_name == "get_dataset_details":
                return await _execute_get_dataset_details(
                    session, user, user_roles, tool_input
                )
            return {"error": f"Unknown tool: {tool_name}"}

        # We need to collect tool events during the loop. Use an action_collector
        # that also records tool names for progress events.
        tool_events: list[dict] = []

        original_executor = tool_executor

        async def tracking_executor(tool_name: str, tool_input: dict) -> dict:
            tool_events.append(
                {
                    "type": "tool_start",
                    "tool": tool_name,
                    "label": tool_label(tool_name),
                }
            )
            result = await original_executor(tool_name, tool_input)
            tool_events.append(
                {
                    "type": "tool_result",
                    "tool": tool_name,
                    "success": "error" not in result,
                }
            )
            return result

        result = await run_tool_loop(
            provider=provider,
            model=model,
            system_prompt=system_prompt,
            user_message=prompt,
            tools_anthropic=ANTHROPIC_TOOLS,
            tools_openai=OPENAI_TOOLS,
            tool_executor=tracking_executor,
            base_url=base_url,
        )

        # Yield all collected tool events
        for evt in tool_events:
            yield evt

        logger.info(
            "Map generation complete (streaming)",
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )

        # Build the map
        yield {"type": "tool_start", "tool": "create_map", "label": "Building map..."}

        try:
            spec_dict = _parse_map_spec(result.text)
        except ValueError:
            logger.warning("Map spec parse failed, retrying extraction only")
            spec_dict = await _retry_parse_map_spec(
                result.text, provider, model, base_url
            )

        if "error" in spec_dict:
            yield {"type": "error", "message": spec_dict["error"]}
            return

        spec = LLMMapSpec(**spec_dict)
        if not spec.layers:
            yield {"type": "error", "message": "LLM produced a map with no layers"}
            return

        dataset_ids = [uuid.UUID(layer.dataset_id) for layer in spec.layers]
        ds_result = await session.execute(
            select(Dataset.id, Dataset.geometry_type, Record.title)
            .join(Record, Dataset.record_id == Record.id)
            .where(Dataset.id.in_(dataset_ids))
        )
        ds_info = {
            str(row[0]): {"geometry_type": row[1], "title": row[2]}
            for row in ds_result.all()
        }

        map_obj = await create_map(
            session,
            name=spec.name,
            description=spec.description,
            created_by=user.id,
        )

        layer_dicts = []
        for layer in spec.layers:
            info = ds_info.get(layer.dataset_id, {})
            validated_paint = validate_paint_for_geometry(
                layer.paint, info.get("geometry_type")
            )
            layer_dicts.append(
                {
                    "dataset_id": uuid.UUID(layer.dataset_id),
                    "sort_order": layer.sort_order,
                    "visible": layer.visible,
                    "opacity": layer.opacity,
                    "paint": validated_paint,
                    "layout": layer.layout,
                }
            )

        await update_map(
            session,
            map_obj.id,
            center_lng=spec.center_lng,
            center_lat=spec.center_lat,
            zoom=spec.zoom,
            basemap_style=spec.basemap_style,
            layers=layer_dicts,
        )

        dataset_names = [info.get("title", "") for info in ds_info.values()]

        yield {
            "type": "done",
            "map_id": str(map_obj.id),
            "map_name": spec.name,
            "explanation": spec.explanation,
            "datasets_used": dataset_names,
        }

    except ToolLoopExhaustedError:
        yield {
            "type": "error",
            "message": "Map generation required too many steps. Try a simpler prompt.",
        }
    except Exception as e:
        logger.exception("Streaming map generation failed")
        yield {"type": "error", "message": str(e)}

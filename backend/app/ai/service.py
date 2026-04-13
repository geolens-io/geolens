"""AI map generation service: LLM orchestration with tool calling."""

import json
import re
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from collections.abc import AsyncGenerator, Awaitable, Callable

from app.ai.constants import tool_label
from app.ai.llm_loop import (
    ToolLoopExhaustedError,
    get_anthropic_client,
    get_openai_client,
    resolve_provider,
    run_tool_loop,
)
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

For polygons: use fill-opacity 0.2-0.4 with a darker _outline-color.
For lines: use line-width 1.5-3.
For points: use circle-radius 4-6 with a stroke.

IMPORTANT: Use the correct paint properties for each geometry type:
- Polygon/MultiPolygon: fill-color, fill-opacity, _outline-color
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
<map_spec> tags. Here is a complete example with multiple layers:

<map_spec>
{{
  "name": "Parks and Trails",
  "description": "National parks with nearby hiking trails",
  "center_lng": -105.3,
  "center_lat": 39.7,
  "zoom": 8,
  "basemap_style": "openfreemap-positron",
  "layers": [
    {{
      "dataset_id": "a1b2c3d4-0000-0000-0000-000000000001",
      "sort_order": 0,
      "visible": true,
      "opacity": 1.0,
      "paint": {{"fill-color": "#22c55e", "fill-opacity": 0.3, "_outline-color": "#15803d"}},
      "layout": {{}}
    }},
    {{
      "dataset_id": "a1b2c3d4-0000-0000-0000-000000000002",
      "sort_order": 1,
      "visible": true,
      "opacity": 1.0,
      "paint": {{"line-color": "#f59e0b", "line-width": 2}},
      "layout": {{}}
    }}
  ],
  "explanation": "I found national parks (polygons) and hiking trails (lines). Parks are shown in green with trails overlaid in amber."
}}
</map_spec>

All fields shown above are required. Use `dataset_id` values returned by search_datasets.

If no matching datasets exist after trying multiple search strategies, output:
<map_spec>
{{"error": "No matching datasets found. The catalog does not contain datasets for: ..."}}
</map_spec>

## Important
- Do NOT invent or hallucinate dataset IDs. Only use IDs returned by search_datasets.
- If you are unsure which dataset best matches, explain your reasoning in the explanation field.
- If no datasets match, suggest alternative search terms the user could try in the error message.

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


async def _should_send_sample_values(session: AsyncSession) -> bool:
    """Check admin toggle for sending sample values to the LLM."""
    try:
        from app.persistent_config import AI_SEND_SAMPLE_VALUES

        return await AI_SEND_SAMPLE_VALUES.get(session)
    except Exception:
        logger.warning(
            "Failed to read AI_SEND_SAMPLE_VALUES, defaulting to True", exc_info=True
        )
        return True


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
        logger.warning("Failed to fetch basemap config, using defaults", exc_info=True)
    return None


def _build_map_system_prompt(
    language: str | None = None,
    basemap_ids: list[str] | None = None,
) -> str:
    """Build map generation system prompt with language directive and dynamic basemaps."""
    from app.ai.chat_service import lang_name

    basemap_instruction = _build_basemap_instruction(basemap_ids)
    prompt = SYSTEM_PROMPT.format(basemap_instruction=basemap_instruction)

    lang = lang_name(language)
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
    *,
    send_sample_values: bool = True,
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
        sample = None
        if send_sample_values and ds.sample_values:
            sample = {}
            for k, v in list(ds.sample_values.items())[:5]:
                sample[k] = v[:5] if isinstance(v, list) else v
            sample = sample or None

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
                "sample_values": sample,
            }
        )

    return results


async def _execute_get_dataset_details(
    session: AsyncSession,
    user: User,
    user_roles: set[str],
    tool_input: dict,
    *,
    send_sample_values: bool = True,
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

    sample = None
    if send_sample_values and ds.sample_values:
        sample = {}
        for k, v in ds.sample_values.items():
            sample[k] = v[:5] if isinstance(v, list) else v
        sample = sample or None

    return {
        "id": str(ds.id),
        "title": ds.record.title,
        "geometry_type": ds.geometry_type,
        "feature_count": ds.feature_count,
        "column_info": column_info,
        "sample_values": sample,
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
        client = get_anthropic_client()
        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": extraction_prompt}],
        )
        block = response.content[0] if response.content else None
        retry_text = getattr(block, "text", "") if block else ""
    else:
        base = base_url or settings.openai_base_url or "https://api.openai.com/v1"
        client = get_openai_client(base)
        response = await client.chat.completions.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": extraction_prompt}],
        )
        retry_text = response.choices[0].message.content or ""

    return _parse_map_spec(retry_text)


async def _validate_and_persist_map(
    session: AsyncSession,
    user: User,
    user_roles: set[str],
    spec: LLMMapSpec,
    basemap_ids: list[str] | None = None,
) -> dict:
    """Validate dataset visibility, create map, and persist layers atomically.

    Returns dict with map_id, map_name, explanation, datasets_used.
    Raises ValueError if any referenced dataset is not visible to the user.
    """
    # Validate basemap_style against configured basemaps
    if basemap_ids and spec.basemap_style not in basemap_ids:
        logger.warning(
            "LLM chose invalid basemap, falling back",
            chosen=spec.basemap_style,
            available=basemap_ids,
        )
        spec.basemap_style = basemap_ids[0]

    # Validate all layer dataset IDs with RBAC visibility filter
    dataset_ids = [uuid.UUID(layer.dataset_id) for layer in spec.layers]
    stmt = (
        select(Dataset.id, Dataset.geometry_type, Record.title)
        .join(Record, Dataset.record_id == Record.id)
        .where(Dataset.id.in_(dataset_ids))
    )
    stmt = apply_visibility_filter(stmt, user, user_roles, Record, DatasetGrant)
    ds_result = await session.execute(stmt)
    ds_info = {
        str(row[0]): {"geometry_type": row[1], "title": row[2]}
        for row in ds_result.all()
    }

    # Reject if any dataset is missing or unauthorized
    requested_ids = [layer.dataset_id for layer in spec.layers]
    missing = [did for did in requested_ids if did not in ds_info]
    if missing:
        raise ValueError(f"Datasets not found or not accessible: {', '.join(missing)}")

    # Build validated layer dicts before touching the DB
    layer_dicts = []
    for layer in spec.layers:
        info = ds_info[layer.dataset_id]
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

    # Persist map + layers atomically via nested savepoint
    async with session.begin_nested():
        map_obj = await create_map(
            session,
            name=spec.name,
            description=spec.description,
            created_by=user.id,
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

    # Derive dataset_names in spec.layers order (preserving duplicates)
    dataset_names = [ds_info[layer.dataset_id]["title"] for layer in spec.layers]

    return {
        "map_id": str(map_obj.id),
        "map_name": spec.name,
        "explanation": spec.explanation,
        "datasets_used": dataset_names,
    }


def _build_tool_executor(
    session: AsyncSession,
    user: User,
    user_roles: set[str],
    send_sample_values: bool,
) -> "Callable[[str, dict], Awaitable[dict]]":
    """Build a tool executor closure bound to the given session/user."""

    async def tool_executor(tool_name: str, tool_input: dict) -> dict:
        """Dispatch an AI tool call to the appropriate handler and return the result."""
        if tool_name == "search_datasets":
            return {
                "results": await _execute_search_tool(
                    session,
                    user,
                    user_roles,
                    tool_input,
                    send_sample_values=send_sample_values,
                )
            }
        elif tool_name == "get_dataset_details":
            return await _execute_get_dataset_details(
                session,
                user,
                user_roles,
                tool_input,
                send_sample_values=send_sample_values,
            )
        return {"error": f"Unknown tool: {tool_name}"}

    return tool_executor


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
    basemap_ids = await _get_available_basemaps(session)
    send_samples = await _should_send_sample_values(session)

    system_prompt = _build_map_system_prompt(language, basemap_ids=basemap_ids)
    tool_executor = _build_tool_executor(session, user, user_roles, send_samples)

    try:
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
    except ToolLoopExhaustedError:
        raise ValueError(
            "Map generation required too many steps. Try a simpler prompt."
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

    return await _validate_and_persist_map(
        session, user, user_roles, spec, basemap_ids=basemap_ids
    )


async def stream_generate_map(
    session: AsyncSession,
    user: User,
    user_roles: set[str],
    prompt: str,
    language: str | None = None,
) -> AsyncGenerator[dict, None]:
    """Semi-streaming variant of generate_map_from_prompt.

    Tool progress events are collected during the LLM tool loop and replayed
    before the final result. True incremental streaming would require callback
    support in run_tool_loop.

    Yields progress events, then the final result or error as a done/error event.
    """
    try:
        provider, model, base_url = await resolve_provider(session)
        basemap_ids = await _get_available_basemaps(session)
        send_samples = await _should_send_sample_values(session)
        system_prompt = _build_map_system_prompt(language, basemap_ids=basemap_ids)
        tool_executor = _build_tool_executor(session, user, user_roles, send_samples)

        tool_events: list[dict] = []

        async def tracking_executor(tool_name: str, tool_input: dict) -> dict:
            """Wrap tool_executor to emit SSE progress events for each tool call."""
            tool_events.append(
                {
                    "type": "tool_start",
                    "tool": tool_name,
                    "label": tool_label(tool_name),
                }
            )
            result = await tool_executor(tool_name, tool_input)
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

        map_result = await _validate_and_persist_map(
            session, user, user_roles, spec, basemap_ids=basemap_ids
        )
        await session.commit()
        yield {"type": "done", **map_result}

    except ToolLoopExhaustedError:
        yield {
            "type": "error",
            "message": "Map generation required too many steps. Try a simpler prompt.",
        }
    except Exception as e:
        logger.exception("Streaming map generation failed")
        yield {"type": "error", "message": str(e)}

"""SQL generation engine: schema context builder and LLM-based SQL generation.

Builds DDL schema context from ChatMapLayer metadata and generates PostGIS SQL
via a dedicated LLM call. The sandbox (app.sandbox) handles validation and execution.
"""

from __future__ import annotations

import re

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm_loop import get_anthropic_client, get_openai_client
from app.ai.schemas import ChatMapLayer
from app.config import settings
from app.persistent_config import LLM_MODEL_LIGHT, LLM_PROVIDER, OPENAI_BASE_URL

logger = structlog.stdlib.get_logger(__name__)

# Maximum columns to include in DDL before truncating
_MAX_COLUMNS = 50


def build_sql_schema_context(layers: list[ChatMapLayer]) -> str:
    """Build DDL schema context from map layers for the SQL generation LLM.

    For each layer, generates a CREATE TABLE statement with column definitions
    and metadata comments about geometry type and the geometry column.

    Args:
        layers: List of ChatMapLayer objects from the frontend.

    Returns:
        DDL string with all table definitions separated by blank lines.
    """
    parts: list[str] = []

    for layer in layers:
        cols = layer.column_info or []
        col_defs: list[str] = []

        for c in cols[:_MAX_COLUMNS]:
            col_defs.append(f"  {c['name']} {c['type']}")

        if len(cols) > _MAX_COLUMNS:
            col_defs.append(f"  -- ... and {len(cols) - _MAX_COLUMNS} more columns")

        # Add geom_4326 column if the layer has geometry
        if layer.geometry_type:
            geom_type_spec = (
                layer.geometry_type.replace("Multi", "Multi")
                if layer.geometry_type
                else "Geometry"
            )
            col_defs.append(f"  geom_4326 geometry({geom_type_spec}, 4326)")

        table_name = layer.dataset_table_name
        if col_defs:
            ddl = f"CREATE TABLE data.{table_name} (\n"
            ddl += ",\n".join(col_defs)
            ddl += "\n);"
        else:
            ddl = f"CREATE TABLE data.{table_name} ();"

        # Metadata comment
        if layer.geometry_type:
            comment = (
                f"-- Geometry: {layer.geometry_type}, "
                f"Geometry column: geom_4326 (SRID 4326)"
            )
        else:
            comment = "-- No geometry column"

        # Sample values for key columns
        sample_comments = ""
        if layer.sample_values:
            sample_lines = []
            for col_name, values in list(layer.sample_values.items())[:5]:
                vals = values[:5] if isinstance(values, list) else [values]
                sample_lines.append(f"-- Sample {col_name}: {vals}")
            if sample_lines:
                sample_comments = "\n" + "\n".join(sample_lines)

        parts.append(f"{ddl}\n{comment}{sample_comments}")

    return "\n\n".join(parts)


def build_sql_generation_prompt(
    question: str, schema_context: str, layer_descriptions: str | None = None
) -> str:
    """Build the complete system prompt for the SQL generation LLM call.

    Includes schema context, PostGIS function reference, geography cast
    templates, example queries, and constraints.

    Args:
        question: The user's natural language question.
        schema_context: DDL schema context from build_sql_schema_context().

    Returns:
        Complete prompt string for the SQL generation LLM.
    """
    layer_context = ""
    if layer_descriptions:
        layer_context = f"""
## Layer Context

{layer_descriptions}
"""

    return f"""\
You are a PostgreSQL/PostGIS SQL expert. Generate a single SELECT query to answer the user's question using the provided database schema.

## Available Tables

{schema_context}
{layer_context}
## PostGIS Spatial Functions

ST_Intersects(geomA, geomB) -> boolean    -- True if geometries share any space
ST_Contains(geomA, geomB) -> boolean      -- True if A fully contains B
ST_Within(geomA, geomB) -> boolean        -- True if A is fully within B
ST_DWithin(geogA, geogB, meters) -> bool  -- True if within distance (uses spatial index!)
ST_Buffer(geom, radius) -> geometry       -- Buffer around geometry
ST_Area(geom) -> float                    -- Area of polygon
ST_Length(geom) -> float                  -- Length of a linestring
ST_Distance(geomA, geomB) -> float        -- Distance between geometries
ST_Union(geomA, geomB) -> geometry        -- Merge geometries
ST_Centroid(geom) -> geometry             -- Center point of geometry
ST_MakePoint(lon, lat) -> geometry        -- Create a point from coordinates
ST_SetSRID(geom, srid) -> geometry        -- Set SRID on geometry
ST_Collect(geom) -> geometry             -- Aggregate geometries into a collection
ST_AsGeoJSON(geom) -> text               -- Convert geometry to GeoJSON string
ST_Transform(geom, srid) -> geometry     -- Reproject geometry to target SRID

## IMPORTANT: Geography Casts for Meter-Based Results

For distance in meters:  ST_Distance(a.geom_4326::geography, b.geom_4326::geography)
For buffer in meters:    ST_Buffer(a.geom_4326::geography, 1000)::geometry
For area in sq meters:   ST_Area(a.geom_4326::geography)

Without ::geography, distance/buffer/area use DEGREES (not meters)!

## Unit Conversions (apply in SQL, not after)

- Square meters to acres:        ST_Area(geom_4326::geography) / 4046.8564224
- Square meters to hectares:     ST_Area(geom_4326::geography) / 10000.0
- Square meters to square miles: ST_Area(geom_4326::geography) / 2589988.11
- Square meters to square km:    ST_Area(geom_4326::geography) / 1000000.0
- Meters to miles:               ST_Distance(...::geography, ...::geography) / 1609.344
- Meters to feet:                ST_Distance(...::geography, ...::geography) * 3.28084

Always convert to human-friendly units in the SQL. Default to acres for area and miles for distance in the US.

## Text Search

For case-insensitive matching: column ILIKE '%pattern%'
For fuzzy matching (requires pg_trgm): similarity(column, 'text') returns 0.0-1.0
For pattern matching: column ~ 'regex_pattern' (case-sensitive), column ~* 'regex_pattern' (case-insensitive)

## NULL Handling

- Use IS NULL or IS NOT NULL (never = NULL or != NULL)
- COALESCE(column, default_value) to replace NULLs
- COUNT(*) includes NULLs; COUNT(column) does not
- NULLs sort last by default; use NULLS FIRST/LAST to control

## Aggregation & Grouping

All non-aggregated columns MUST appear in GROUP BY.
Common aggregates: COUNT(*), SUM(col), AVG(col), MIN(col), MAX(col), ARRAY_AGG(col)
For spatial aggregation: ST_Collect(geom_4326) to merge geometries, ST_Union(geom_4326) to dissolve boundaries.

## Date & Time Functions

- EXTRACT(YEAR FROM date_col), EXTRACT(MONTH FROM date_col)
- DATE_TRUNC('month', timestamp_col) for grouping by time period
- AGE(date1, date2) for intervals
- NOW() for current timestamp

## Example Queries

-- Distance query (miles):
SELECT c.name, c.state,
  ST_Distance(c.geom_4326::geography, p.geom_4326::geography) / 1609.344 AS distance_miles
FROM data.us_state_capitals c, data.airports p
WHERE p.name = 'JFK'
ORDER BY distance_miles
LIMIT 10;

-- Spatial join with aggregation:
SELECT co.name AS country, COUNT(ci.ogc_fid) AS city_count
FROM data.countries co
JOIN data.cities ci ON ST_Intersects(co.geom_4326, ci.geom_4326)
GROUP BY co.name
ORDER BY city_count DESC;

-- Area calculation (acres):
SELECT SUM(ST_Area(p.geom_4326::geography) / 4046.8564224) AS total_acres
FROM data.parcels p
WHERE p.zone_type = 'agricultural';

-- Buffer + intersect:
SELECT p.name AS park_name
FROM data.national_parks p
WHERE ST_Intersects(
  p.geom_4326,
  ST_Buffer(
    (SELECT geom_4326 FROM data.us_state_capitals WHERE name = 'Denver')::geography,
    50000  -- 50km radius
  )::geometry
);

-- Proximity by coordinates (within 5 miles of a point):
SELECT p.name,
  ST_Distance(p.geom_4326::geography, ST_SetSRID(ST_MakePoint(-74.006, 40.7128), 4326)::geography) / 1609.344 AS distance_miles
FROM data.parks p
WHERE ST_DWithin(p.geom_4326::geography, ST_SetSRID(ST_MakePoint(-74.006, 40.7128), 4326)::geography, 8046.72)
ORDER BY distance_miles
LIMIT 20;

-- Aggregation with GROUP BY:
SELECT p.zone_type, COUNT(*) AS count, AVG(ST_Area(p.geom_4326::geography) / 4046.8564224) AS avg_acres
FROM data.parcels p
GROUP BY p.zone_type
ORDER BY count DESC;

-- Case-insensitive text search:
SELECT name, population
FROM data.cities c
WHERE c.name ILIKE '%spring%'
ORDER BY population DESC
LIMIT 20;

-- Common Mistakes to Avoid:
-- WRONG: ST_Distance(a.geom_4326, b.geom_4326) → returns DEGREES, not meters
-- CORRECT: ST_Distance(a.geom_4326::geography, b.geom_4326::geography) → meters
-- WRONG: WHERE column = NULL → always false; use WHERE column IS NULL
-- WRONG: SELECT name, COUNT(*) FROM data.t → missing GROUP BY name

## Constraints

- Generate a single SELECT statement only. No INSERT, UPDATE, DELETE, CREATE, DROP, or ALTER.
- Always use the `data.` schema prefix for table names (e.g., `data.cities`, not just `cities`).
- The geometry column is always `geom_4326` (SRID 4326).
- When querying multiple tables, always qualify column names with table alias to avoid ambiguity.
- Use ::geography casts for distance, buffer, and area operations to get results in meters.
- Always convert area/distance to human-friendly units (acres, miles, etc.) in the SQL using the conversion factors above.
- For proximity filters ("within X miles/km of Y"), prefer ST_DWithin over ST_Distance < threshold — ST_DWithin uses the spatial index.
- For ad-hoc coordinate queries, create points with: ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
- For case-insensitive text matching, use ILIKE (e.g., WHERE name ILIKE 'california').
- Always include LIMIT 1000 unless the query is an aggregation (GROUP BY, COUNT, SUM, etc.).
- Use ONLY the tables and columns shown in the schema above. Do not invent names.
- Use ONLY the PostGIS functions listed above. Do not use functions not in this reference.
- Queries are limited to 30 seconds. Prefer indexed operations (ST_DWithin) over unindexed scans (ST_Distance < X).
- You may use CTEs (WITH clauses) and subqueries. All referenced tables must be from the schema above.
- If the question cannot be answered with the available schema, respond with: -- ERROR: Cannot answer this question with the available data.
- If the question asks to modify, delete, or insert data, respond with: -- ERROR: Only SELECT queries are supported.

## Question

{question}

Respond with ONLY the SQL query (or an -- ERROR comment if the query cannot be generated). No explanation, no markdown, no code fences."""


async def generate_sql(
    db: AsyncSession,
    question: str,
    schema_context: str,
    *,
    layer_descriptions: str | None = None,
) -> str:
    """Generate SQL from a natural language question using the configured LLM.

    Makes a single LLM API call with the SQL generation prompt and extracts
    the raw SQL from the response. Strips markdown code fences if present.

    Args:
        db: Database session for reading persistent config.
        question: The user's natural language question.
        schema_context: DDL schema context from build_sql_schema_context().

    Returns:
        Raw SQL string ready for sandbox validation and execution.

    Raises:
        ValueError: If the LLM provider is not configured or unknown.
        Exception: LLM API errors propagate to the caller.
    """
    provider = await LLM_PROVIDER.get(db)
    model = await LLM_MODEL_LIGHT.get(db)
    prompt = build_sql_generation_prompt(
        question, schema_context, layer_descriptions=layer_descriptions
    )

    logger.info(
        "Generating SQL",
        provider=provider,
        model=model,
        question=question,
    )

    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError("Anthropic API key not configured")
        sql = await _call_anthropic(prompt, question, model)
    elif provider == "openai_compatible":
        if not settings.openai_api_key:
            raise ValueError("OpenAI-compatible API key not configured")
        base_url = await OPENAI_BASE_URL.get(db) or "https://api.openai.com/v1"
        sql = await _call_openai(prompt, question, model, base_url)
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")

    # Strip markdown code fences if the LLM wrapped the SQL
    sql = _strip_code_fences(sql.strip())

    # Strip trailing semicolons (executor wraps SQL in a subquery)
    sql = sql.rstrip(";").strip()

    # Strip leaked special tokens from local LLMs (e.g., <|im_start|>, <|im_end|>)
    sql = re.sub(r"<\|[^|]+\|>", "", sql).strip()

    logger.info(
        "SQL generated",
        provider=provider,
        model=model,
        sql_length=len(sql),
    )

    return sql


async def _call_anthropic(prompt: str, question: str, model: str) -> str:
    """Call Anthropic API for SQL generation (async)."""
    client = get_anthropic_client()
    response = await client.messages.create(
        model=model,
        max_tokens=2048,
        temperature=0.0,
        system=prompt,
        messages=[{"role": "user", "content": question}],
    )

    if hasattr(response, "usage") and response.usage:
        logger.info(
            "SQL generation tokens",
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

    return response.content[0].text


async def _call_openai(prompt: str, question: str, model: str, base_url: str) -> str:
    """Call OpenAI-compatible API for SQL generation (async)."""
    client = get_openai_client(base_url)
    response = await client.chat.completions.create(
        model=model,
        max_tokens=2048,
        temperature=0.0,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": question},
        ],
    )

    if response.usage:
        logger.info(
            "SQL generation tokens",
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
        )

    return response.choices[0].message.content or ""


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from LLM output.

    Handles ```sql ... ``` and ``` ... ``` patterns.
    """
    pattern = r"^```(?:sql)?\s*\n?(.*?)\n?```$"
    match = re.match(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text

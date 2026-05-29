"""SQL generation engine: schema context builder and LLM-based SQL generation.

Builds DDL schema context from ChatMapLayer metadata and generates PostGIS SQL
via a dedicated LLM call. The sandbox (app.sandbox) handles validation and execution.
"""

from __future__ import annotations

import hashlib
import re
import time
import uuid as _uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.extensions import get_ai_provider
from app.processing.ai.schemas import ChatMapLayer
from app.processing.ai.token_usage import record_token_usage
from app.core.persistent_config import LLM_MODEL_LIGHT, LLM_PROVIDER

logger = structlog.stdlib.get_logger(__name__)

# Maximum columns to include in DDL before truncating
_MAX_COLUMNS = 50

# Simple TTL cache for schema context (avoids rebuilding identical DDL across
# consecutive chat turns when layers haven't changed).
#
# PERF-04 (Phase 274) + Pitfall #5 anchor (v1030 Phase 1135 AI-04): the cache
# key is partitioned by (map_id, content_hash) so two different maps that
# share an identical layer signature (e.g. both referencing the same Natural
# Earth dataset) get independent cache entries. Without the map_id partition,
# one map's prompt-context edits could be served back to a different map on
# the next chat turn. Do NOT shortcut to a dataset_id-only key — the
# (map_id, content_hash) tuple is load-bearing across multi-map chat sessions
# and must NOT be relaxed without a Future Requirement entry first.
_schema_cache: dict[tuple[str, str], tuple[float, str]] = {}
_SCHEMA_CACHE_TTL = 60.0  # seconds
_SCHEMA_CACHE_MAX = 64  # bounded so unbounded map_ids don't grow memory


def _schema_cache_key(
    layers: list["ChatMapLayer"], map_id: str | None
) -> tuple[str, str]:
    """Build a deterministic cache key partitioned by (map_id, content_hash).

    PERF-04 (Phase 274) + Pitfall #5 (v1030 Phase 1135 AI-04): adding map_id
    prevents cross-map cache pollution when two different maps reference the
    same dataset. The (map_id, content_hash) tuple shape is load-bearing —
    do NOT shortcut to (dataset_id,) only. Cache entries evict on either the
    60s TTL or when len(_schema_cache) >= _SCHEMA_CACHE_MAX.
    """
    parts = []
    for layer in layers:
        col_sig = ""
        if layer.column_info:
            col_sig = ",".join(
                f"{c.get('name', '')}:{c.get('type', '')}"
                for c in layer.column_info[:_MAX_COLUMNS]
            )
        parts.append(f"{layer.dataset_table_name}|{layer.geometry_type}|{col_sig}")
    raw = "\n".join(sorted(parts))
    content_hash = hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()
    map_key = str(map_id) if map_id is not None else "__no_map__"
    return (map_key, content_hash)


def build_sql_schema_context(
    layers: list[ChatMapLayer], map_id: str | None = None
) -> str:
    """Build DDL schema context from map layers for the SQL generation LLM.

    For each layer, generates a CREATE TABLE statement with column definitions
    and metadata comments about geometry type and the geometry column.
    Results are cached for 60s per (map_id, schema_content_hash) to avoid
    rebuilding identical DDL across consecutive chat turns.

    Args:
        layers: List of ChatMapLayer objects from the frontend.
        map_id: Active map identifier (PERF-04 partition key). When omitted
            (e.g. unit tests / scripts), a sentinel partition is used.

    Returns:
        DDL string with all table definitions separated by blank lines.
    """
    # Check cache
    cache_key = _schema_cache_key(layers, map_id)
    now = time.monotonic()
    cached = _schema_cache.get(cache_key)
    if cached and (now - cached[0]) < _SCHEMA_CACHE_TTL:
        return cached[1]

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
            geom_type_spec = layer.geometry_type
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

    result = "\n\n".join(parts)

    # Store in cache (evict oldest if full)
    if len(_schema_cache) >= _SCHEMA_CACHE_MAX:
        oldest_key = min(_schema_cache, key=lambda k: _schema_cache[k][0])
        del _schema_cache[oldest_key]
    _schema_cache[cache_key] = (now, result)

    return result


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
ST_Collect(geom) -> geometry             -- Aggregate geometries into a collection (preserves structure)
ST_AsGeoJSON(geom) -> text               -- Convert geometry to GeoJSON string
ST_Transform(geom, srid) -> geometry     -- Reproject geometry to target SRID
ST_X(point) -> float                     -- X coordinate (longitude) of a point
ST_Y(point) -> float                     -- Y coordinate (latitude) of a point

## Text Search Functions (requires pg_trgm extension)

similarity(text, text) -> float          -- Returns 0.0-1.0 similarity score
word_similarity(text, text) -> float     -- Word-level similarity score
text % text -> boolean                   -- True when similarity > pg_trgm.similarity_threshold (default 0.3)

## Vector Similarity Operators (requires pgvector extension)

Use these when a column has type vector(N) (commonly named `embedding` or
`embedding_1536`). Lower values = more similar.

  embedding <-> '[...]'::vector   -- L2 (Euclidean) distance
  embedding <=> '[...]'::vector   -- cosine distance
  embedding <#> '[...]'::vector   -- negative inner product

To find the K most similar rows to a reference row's embedding:
  SELECT name, embedding <=> (SELECT embedding FROM data.t WHERE id = '<id>') AS distance
  FROM data.t
  WHERE id <> '<id>'
  ORDER BY distance
  LIMIT 10;

Vector NN scans are O(N) without an HNSW/IVFFlat index — always include LIMIT.
Vector columns are queried with these operators, NOT with similarity() or ILIKE
(those are for TEXT columns).

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
For fuzzy matching: use the similarity() function listed above (requires pg_trgm)
For threshold-based fuzzy matching: column % 'pattern' (returns true when similar enough)
For pattern matching: column ~ 'regex_pattern' (case-sensitive), column ~* 'regex_pattern' (case-insensitive)

## NULL Handling

- Use IS NULL or IS NOT NULL (never = NULL or != NULL)
- COALESCE(column, default_value) to replace NULLs
- COUNT(*) includes NULLs; COUNT(column) does not
- NULLs sort last by default; use NULLS FIRST/LAST to control

## Aggregation & Grouping

All non-aggregated columns MUST appear in GROUP BY.
Common aggregates: COUNT(*), SUM(col), AVG(col), MIN(col), MAX(col), ARRAY_AGG(col)
For spatial aggregation: ST_Collect(geom_4326) to group geometries (preserves structure), ST_Union(geom_4326) to dissolve boundaries into one geometry.

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

-- CTE (WITH clause) for multi-step analysis:
WITH big_cities AS (
  SELECT geom_4326, name, population
  FROM data.cities
  WHERE population > 500000
),
park_buffers AS (
  SELECT name, ST_Buffer(geom_4326::geography, 10000)::geometry AS buf
  FROM data.national_parks
)
SELECT pb.name AS park, COUNT(bc.name) AS nearby_big_city_count
FROM park_buffers pb
LEFT JOIN big_cities bc ON ST_Intersects(pb.buf, bc.geom_4326)
GROUP BY pb.name
ORDER BY nearby_big_city_count DESC
LIMIT 20;

-- Vector similarity (when an embedding column is available):
SELECT name, embedding <=> (SELECT embedding FROM data.records WHERE id = '<id>') AS distance
FROM data.records
WHERE id <> '<id>'
ORDER BY distance
LIMIT 10;

-- Common Mistakes to Avoid:
-- WRONG: ST_Distance(a.geom_4326, b.geom_4326) → returns DEGREES, not meters
-- CORRECT: ST_Distance(a.geom_4326::geography, b.geom_4326::geography) → meters
-- WRONG: WHERE column = NULL → always false; use WHERE column IS NULL
-- WRONG: SELECT name, COUNT(*) FROM data.t → missing GROUP BY name
-- WRONG: WHERE similarity(embedding, '[...]') > 0.5 → similarity() is for text
-- CORRECT: ORDER BY embedding <=> '[...]'::vector LIMIT 10 → vector NN

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
- Use ONLY the functions and operators listed in the PostGIS, Text Search, and Vector Similarity sections above. Do not use functions not in this reference.
- Vector columns (type vector(N)) are queried with the <->/<=>/<#> operators, NOT with similarity() or ILIKE.
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
    user_id: _uuid.UUID | None = None,
) -> str:
    """Generate SQL from a natural language question using the configured LLM.

    Makes a single LLM API call with the SQL generation prompt and extracts
    the raw SQL from the response. Strips markdown code fences if present.

    Args:
        db: Database session for reading persistent config.
        question: The user's natural language question.
        schema_context: DDL schema context from build_sql_schema_context().
        layer_descriptions: Optional one-line-per-layer summary appended to
            the prompt for additional context.
        user_id: Optional user UUID — when provided, the per-call input/output
            token counts are persisted with subsystem="sql_gen" so SQL
            generation cost can be attributed separately from the parent
            chat loop's "chat" / "chat_stream" rows.

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

    # Pull base_url from the provider's own runtime config (REVIEW.md WR-02)
    # so future overlays receive provider-correct values instead of an
    # OpenAI-shaped URL leaking into Anthropic-keyed providers.
    provider_ext = get_ai_provider(provider)
    runtime_config = await provider_ext.resolve_runtime_config(db)
    base_url = runtime_config.get("base_url")

    async def _noop_executor(name: str, args: dict) -> dict:
        # max_rounds=1 exits before any tool call; executor never runs.
        return {}

    result = await provider_ext.complete(
        model=model,
        system_prompt=prompt,
        user_message=question,
        tools=[],
        tool_executor=_noop_executor,
        max_rounds=1,
        max_tokens=2048,
        temperature=0.0,
        base_url=base_url,
    )
    sql = result.text

    # Attribute SQL generation cost separately from the parent chat loop
    # (which records "chat" / "chat_stream"). Best-effort — failures are
    # logged inside record_token_usage and never break the caller.
    if user_id is not None:
        await record_token_usage(
            db,
            user_id=user_id,
            subsystem="sql_gen",
            model=model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )

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


def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from LLM output.

    Handles ```sql ... ``` and ``` ... ``` patterns.
    """
    pattern = r"^```(?:sql)?\s*\n(.*?)\n?\s*```\s*$"
    match = re.match(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text

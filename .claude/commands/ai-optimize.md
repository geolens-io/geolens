# /ai-optimize — AI Capability Audit & Optimization

Audit and optimize GeoLens's three AI subsystems: metadata autocomplete, map generation, and map chat (natural language → SQL + MapLibre style). Priority order: output quality → safety → latency/cost → prompt engineering. This command discovers the AI architecture first, then dispatches targeted subagents.

**Usage:** `/ai-optimize` (full audit) or `/ai-optimize <subsystem>` where subsystem is `metadata`, `mapgen`, or `chat`

---

## PHASE 0: DISCOVERY (Serial — must complete before dispatch)

The AI backend supports multiple configurable providers and may use function calling, freeform parsing, or both. Discover everything before optimizing anything.

### Step 1: Map the AI module structure

```bash
# Full AI module tree
find backend/app/processing/ai -type f -name "*.py" 2>/dev/null | sort

# Read every file in the AI module
find backend/app/processing/ai -type f -name "*.py" 2>/dev/null | while read f; do
  echo "=== $f ==="
  cat "$f"
done

# AI-adjacent modules (embeddings, search, settings)
find backend/app/processing/embeddings -type f -name "*.py" 2>/dev/null | while read f; do
  echo "=== $f ==="
  cat "$f"
done

# AI-related settings and configuration
grep -rn "ai\|llm\|openai\|anthropic\|claude\|gpt\|model\|provider\|chat\|completion" backend/app/modules/settings/ --include="*.py" 2>/dev/null | grep -v __pycache__

# Environment variables for AI
grep -i "ai\|llm\|openai\|anthropic\|claude\|gpt\|model\|provider\|embedding" .env.example 2>/dev/null
```

### Step 2: Identify the LLM integration pattern

```bash
# Provider clients and SDKs
grep -rn "import openai\|from openai\|import anthropic\|from anthropic\|import litellm\|from litellm\|import langchain\|from langchain\|ChatCompletion\|messages\.create\|client\.chat" backend/app/ --include="*.py" | grep -v __pycache__

# Function calling / tool use
grep -rn "tools\|functions\|function_call\|tool_use\|tool_choice\|tool_result" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__

# Freeform output parsing
grep -rn "regex\|re\.search\|re\.match\|parse\|extract\|json\.loads\|```sql\|```json\|```" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__

# Streaming
grep -rn "stream\|SSE\|ServerSentEvent\|yield\|async.*generator\|iter\|chunk" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__

# Provider abstraction / routing
grep -rn "provider\|model.*select\|model.*route\|switch.*model\|factory\|registry" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__
```

### Step 3: Identify the three subsystems

```bash
# Metadata autocomplete
grep -rn "metadata\|auto.complete\|suggest\|enrich\|description.*generat\|keyword.*generat\|abstract.*generat\|lineage" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__

# Map generation
grep -rn "map.*generat\|create.*map\|build.*map\|map.*tool\|layer.*generat\|style.*generat" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__

# Map chat / natural language to SQL + style
grep -rn "sql\|SQL\|query.*generat\|natural.*language\|text.to\|chat\|maplibre\|style.*spec\|paint\|layout\|filter.*express" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__
```

### Step 4: Read system prompts and few-shot examples

```bash
# System prompts — might be inline strings, separate files, or template files
grep -rn "system.*prompt\|system.*message\|SYSTEM\|system_prompt\|instructions" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__

# Prompt templates or files
find backend/app/processing/ai -name "*.txt" -o -name "*.md" -o -name "*.jinja" -o -name "*.j2" -o -name "*prompt*" -o -name "*template*" 2>/dev/null

# Few-shot examples
grep -rn "example\|few.shot\|sample\|demonstration" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__

# Read all prompt content
find backend/app/processing/ai -name "*prompt*" -o -name "*template*" -o -name "*.txt" -o -name "*.md" 2>/dev/null | while read f; do
  echo "=== $f ==="
  cat "$f"
done
```

### Step 5: Read the frontend AI integration

```bash
# AI-related frontend components
find frontend/src -path "*ai*" -o -path "*chat*" -o -path "*assist*" 2>/dev/null | grep -E "\.(tsx|ts)$" | grep -v node_modules

# AI chat UI
grep -rn "chat\|message\|prompt\|ai\|assist\|copilot\|generate" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | grep -i "component\|page\|hook\|context" | head -30

# How does the frontend call AI endpoints?
grep -rn "/ai/\|/chat/\|/generate/\|/suggest/\|/complete/" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules
```

### Step 6: Catalog the database schema available to AI

```bash
# What schema info is passed to the LLM for SQL generation?
grep -rn "schema\|table.*name\|column.*name\|information_schema\|pg_catalog\|describe\|introspect" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__

# How does AI know about available datasets/layers/columns?
grep -rn "dataset\|layer\|column\|field\|attribute" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__ | grep -iv "import\|__pycache__"

# PostGIS functions referenced in AI context
grep -rn "ST_\|geometry\|geography\|spatial" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__
```

### Build discovery summary

Before dispatching subagents, produce a structured summary:

```markdown
## AI Architecture Discovery

### Provider Integration
- Client library: [openai / anthropic / litellm / langchain / custom]
- Provider routing: [single / configurable / abstraction layer]
- Models used: [list specific models and where each is used]

### Integration Pattern
- Function calling / tool use: [yes / no / partial]
- Freeform parsing: [yes / no / partial]
- Streaming: [yes / no]

### Subsystems Identified
- Metadata autocomplete: [file paths, entry points]
- Map generation: [file paths, entry points]
- Map chat: [file paths, entry points]

### Prompt Architecture
- System prompts: [inline / file-based / templated]
- Few-shot examples: [present / absent]
- Schema injection: [how DB schema reaches the LLM]
```

This summary feeds all subagents. Rediscover only if a subagent needs deeper detail in its domain.

---

## SUBAGENT DISPATCH (Parallel)

Run these 6 subagents in parallel. Each subagent receives the discovery summary as context.

### Subagent 1: SQL Generation Quality & Safety

**Goal:** Audit the natural-language-to-SQL pipeline for output correctness, PostGIS/pgvector/pg_trgm compatibility, and injection safety. This is the highest-risk AI subsystem.

**Process:**

#### 1a. SQL generation pipeline analysis

Read the complete SQL generation code path — from user message to executed query.

Map the pipeline stages:
1. How is the user's natural language message received?
2. What context is injected (schema, dataset metadata, spatial info)?
3. How is the SQL generated (function call, freeform, chain)?
4. How is the generated SQL validated before execution?
5. How is the SQL executed (raw execute, ORM, parameterized)?
6. How are results returned to the user?

#### 1b. Schema context quality

The LLM can only generate correct SQL if it has accurate schema context.

```bash
# How is schema information gathered?
grep -rn "information_schema\|pg_catalog\|inspector\|reflect\|get_columns\|get_table_names\|schema_context\|table_schema\|column_info" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__
```

Check:
- Does the schema context include column types (especially geometry types and SRIDs)?
- Does it include available PostGIS functions?
- Does it include pgvector operators (`<->`, `<=>`, `<#>`)?
- Does it include pg_trgm functions (`similarity()`, `%`)?
- Does it include spatial relationship functions (`ST_Intersects`, `ST_DWithin`, etc.)?
- Does it include sample values or value ranges to help the LLM choose correct filters?
- Is the schema context truncated for large datasets? If so, how?

**Recommend improvements:**
- If schema context is missing geometry types → add them (critical for correct `ST_*` function selection)
- If schema context is flat (just column names) → add types, constraints, and spatial metadata
- If no PostGIS function reference → add a curated list of available spatial functions with signatures
- If no sample values → add distinct value counts for categorical columns, bbox for spatial columns

#### 1c. SQL output quality

Read the system prompt(s) and few-shot examples for SQL generation.

Check the system prompt for:
- **Explicit SQL dialect specification** — Does it say "PostgreSQL" and "PostGIS"? Generic SQL prompts produce MySQL/SQLite syntax.
- **Available functions** — Does it list the PostGIS/pgvector/pg_trgm functions the DB supports?
- **Output format specification** — Does it request `SELECT` only? Does it forbid `DROP`, `DELETE`, `INSERT`, `UPDATE`, `ALTER`?
- **Column qualification** — Does it instruct the LLM to use table-qualified column names (`table.column`) to avoid ambiguity?
- **Geometry handling** — Does it instruct the LLM to use `ST_AsGeoJSON()` for geometry output? To use `ST_Transform()` for CRS conversion?
- **Null handling** — Does it instruct the LLM to handle NULLs in spatial columns?
- **Limit clauses** — Does it enforce `LIMIT` to prevent unbounded result sets?
- **EXPLAIN awareness** — Can the user ask "why is this slow?" and get an `EXPLAIN ANALYZE`?

Check few-shot examples for:
- Coverage of spatial queries (point-in-polygon, distance, buffer, intersection)
- Coverage of vector similarity search
- Coverage of text search (trigram, full-text)
- Coverage of joins across datasets
- Coverage of aggregation (count, sum, spatial union)
- Edge cases (empty results, NULL geometries, mixed SRIDs)

**Recommend specific prompt improvements** with before/after examples.

#### 1d. SQL safety audit

```bash
# How is generated SQL validated?
grep -rn "sanitize\|validate\|whitelist\|blacklist\|allow\|deny\|forbid\|readonly\|read.only\|EXPLAIN\|parse\|sqlparse\|ast\|sqlglot\|check.*sql\|sql.*check" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__

# How is SQL executed?
grep -rn "execute\|raw\|text(\|exec\|cursor\|session\.exec\|connection\.exec" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__

# Is there a read-only connection or role?
grep -rn "readonly\|read.only\|SET TRANSACTION READ ONLY\|pg_read_all_data\|GRANT SELECT" backend/app/ --include="*.py" --include="*.sql" | grep -v __pycache__
```

**SQL injection vectors to check:**
- Is the LLM output passed directly to `execute()` without parameterization?
- Can the LLM be tricked into generating `DROP TABLE`, `DELETE`, `UPDATE`, or `INSERT` via prompt injection?
- Is there a SQL parser/validator between LLM output and execution?
- Does the execution use a read-only database connection/role?
- Are CTEs, subqueries, and `UNION` allowed? (Can be used for data exfiltration)
- Can `COPY TO` or `pg_read_file()` be used to read server files?
- Are query timeouts enforced? (Prevent `pg_sleep()` or cartesian joins)
- Can `SET` statements change session config?

**Recommend concrete safety layers:**
- **If no SQL parser exists:** Recommend adding `sqlglot` or `sqlparse` to validate the AST before execution — reject anything that isn't a `SELECT`
- **If no read-only connection:** Recommend creating a `geolens_readonly` PostgreSQL role with `SELECT`-only grants
- **If no query timeout:** Recommend `SET statement_timeout = '30s'` on the AI query connection
- **If no result limit:** Recommend injecting `LIMIT 1000` if the LLM omits it
- **If parameterization is possible:** Recommend extracting literals from the LLM's SQL and converting to parameterized queries

**Output:** SQL pipeline diagram, safety layer inventory, and specific quality + safety recommendations with code examples.

---

### Subagent 2: MapLibre Style Generation Quality

**Goal:** Audit the MapLibre GL Style Spec generation for correctness, visual quality, and spec compliance.

**Process:**

#### 2a. Style generation pipeline

Read the complete style generation code path.

```bash
# MapLibre style references
grep -rn "maplibre\|mapbox\|style.*spec\|paint\|layout\|layer.*type\|fill.*color\|line.*color\|circle.*radius\|text.*field\|filter\|interpolate\|match\|case\|step\|heatmap\|raster\|symbol\|expression" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__

# How does AI modify existing styles vs create new ones?
grep -rn "merge\|patch\|update.*style\|modify.*style\|adjust\|current.*style\|existing.*style" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__
```

Map the pipeline:
1. How does the user request a style change? (chat message, UI action, map generation)
2. What context does the LLM receive? (current style, available layers, data schema, map viewport)
3. How is the style output structured? (complete style JSON, partial patch, individual property)
4. How is the output validated before applying to the map?
5. How does the frontend apply the style? (full replacement, merge, property-level update)

#### 2b. Style spec knowledge audit

Read the system prompt and any style-related context injected into the LLM.

Check if the prompt includes or references:
- **MapLibre layer types**: `fill`, `line`, `circle`, `symbol`, `heatmap`, `raster`, `fill-extrusion`, `hillshade`, `background`
- **Paint properties** by layer type (e.g., `fill-color`, `fill-opacity`, `line-width`, `circle-radius`)
- **Layout properties** (e.g., `visibility`, `text-field`, `icon-image`, `symbol-placement`)
- **Expression syntax**: `["match", ...]`, `["case", ...]`, `["interpolate", ...]`, `["step", ...]`, `["get", "property"]`
- **Data-driven styling**: property-based color ramps, categorical coloring, zoom-dependent values
- **Filter expressions**: `["==", "property", "value"]`, `["all", ...]`, `["any", ...]`, `["has", ...]`
- **Source references**: Does it know which sources exist and their properties?

**Common LLM style errors to look for in prompts/examples:**
- Mapbox GL JS syntax vs MapLibre GL JS syntax (mostly compatible but some divergences)
- Invalid expression nesting (missing `["literal", [...]]` for array values)
- Wrong property for layer type (`fill-color` on a `line` layer)
- Missing `source` or `source-layer` on generated layers
- `text-field` without `["get", "propertyName"]` expression syntax (bare strings deprecated)
- Color values in wrong format (MapLibre prefers `"rgba(r,g,b,a)"` or hex)
- Zoom-dependent expressions with wrong stop values
- Heatmap without `heatmap-weight` or `heatmap-intensity`

#### 2c. Style validation

```bash
# Is generated style validated before delivery?
grep -rn "validate\|schema\|jsonschema\|style.*check\|spec.*check\|layer.*type.*check" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__

# Is there a style spec schema file?
find . -name "*style*" -name "*.json" -not -path "*/node_modules/*" 2>/dev/null
```

**Recommend:**
- If no validation: recommend JSON Schema validation against the MapLibre style spec before returning to frontend
- If no current-style context: recommend injecting the current map style so the LLM can make incremental changes without breaking existing layers
- If no layer type awareness: recommend including available layer types and their valid paint/layout properties in the system prompt

#### 2d. Visual quality recommendations

Analyze the prompts and examples for visual design quality:
- Does the system prompt guide color palette choices? (Accessible palettes, colorblind-safe, sequential vs. diverging vs. categorical)
- Does it handle label placement quality? (`symbol-placement`, `text-max-width`, `text-overlap`)
- Does it set reasonable defaults for stroke widths, opacities, font sizes?
- Does it handle dark/light basemap adaptation?
- Does it handle high-density data gracefully? (clustering, heatmaps, opacity reduction)

**Output:** Style pipeline diagram, spec compliance gaps, and specific prompt + validation recommendations.

---

### Subagent 3: Metadata Autocomplete Quality

**Goal:** Audit the metadata generation system for completeness, accuracy, and compliance with geospatial metadata standards.

**Process:**

#### 3a. Metadata generation pipeline

```bash
# Metadata-specific AI code
grep -rn "metadata\|abstract\|description\|keyword\|tag\|lineage\|provenance\|title.*generat\|summary.*generat" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__

# What triggers metadata generation?
grep -rn "auto.*complete\|suggest\|enrich\|populate\|fill\|generate.*meta" backend/app/ --include="*.py" | grep -v __pycache__ | grep -iv "alembic\|migration"
```

Map the pipeline:
1. When is metadata generation triggered? (upload, manual request, batch)
2. What input does the LLM receive? (column names, sample data, file name, existing partial metadata)
3. What metadata fields does it generate? (title, description, keywords, theme, spatial extent, temporal extent, lineage)
4. How is output structured and validated?
5. Does it overwrite existing metadata or merge/suggest?

#### 3b. Metadata quality assessment

Read the system prompt for metadata generation.

Check if it produces metadata that aligns with:
- **ISO 19115** (geographic information metadata standard)
- **Dublin Core** elements (title, creator, subject, description, publisher, date, type, format, identifier, source, language, coverage, rights)
- **DCAT vocabulary** (as used in GeoLens's DCAT endpoint)
- **STAC item properties** (datetime, start/end datetime, providers, license)
- **FAIR principles** (Findable, Accessible, Interoperable, Reusable)

**Common metadata generation problems:**
- Generic descriptions ("This dataset contains geographic data") — useless for discovery
- Keywords that parrot column names instead of domain concepts
- Missing spatial extent derivation (should come from actual geometry bounds, not LLM guess)
- Missing temporal extent derivation (should come from date columns, not LLM guess)
- Lineage that's fabricated instead of derived from actual provenance (file source, transformation steps)
- Language/locale not detected or assumed English

#### 3c. Context quality

What does the LLM actually see when generating metadata?

```bash
# Sample data extraction for metadata context
grep -rn "sample\|preview\|head\|first.*rows\|random.*rows" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__

# Schema information for metadata
grep -rn "column.*name\|column.*type\|field.*name\|dtype\|schema" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__

# File-level metadata (filename, format, size, CRS)
grep -rn "filename\|file.*name\|format\|crs\|srid\|projection\|file.*size\|mime" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__
```

**Recommend improvements:**
- If only column names → add column types, null counts, unique counts, sample values
- If no sample rows → add 3-5 representative rows (not just head — sample across the dataset)
- If no spatial summary → add bounding box, geometry type distribution, CRS
- If no temporal summary → add date range from date/datetime columns
- If no file provenance → add original filename, upload timestamp, file format, size
- If generating keywords → recommend extracting from both column names AND sample values
- If generating descriptions → recommend grounding in actual data statistics, not LLM imagination

#### 3d. Standard compliance mapping

For each metadata field GeoLens generates, map it to the standard(s) it serves:

| Field | ISO 19115 | Dublin Core | DCAT | STAC |
|-------|-----------|-------------|------|------|
| title | ✅ | ✅ | dct:title | ✅ |
| description | ✅ | ✅ | dct:description | ✅ |
| keywords | ✅ | dc:subject | dcat:keyword | ✅ |
| ... | ... | ... | ... | ... |

Flag any fields required by the standards endpoints (DCAT, STAC, OGC Records) that the metadata generator doesn't produce.

**Output:** Metadata pipeline analysis, standard coverage matrix, and specific recommendations for improving generation quality and grounding.

---

### Subagent 4: Prompt Engineering Audit

**Goal:** Audit all system prompts, few-shot examples, and context injection across all three subsystems for quality, consistency, and best practices.

**Process:**

#### 4a. Collect all prompts

```bash
# Every string that looks like a system prompt
grep -rn "system\|System\|SYSTEM" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__ | grep -i "message\|prompt\|content\|role"

# Every multi-line string in AI module (likely prompt templates)
find backend/app/processing/ai -name "*.py" 2>/dev/null | while read f; do
  echo "=== $f ==="
  # Find triple-quoted strings
  python3 -c "
import ast, sys
with open('$f') as fh:
    tree = ast.parse(fh.read())
for node in ast.walk(tree):
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) > 100:
        print(f'Line {node.lineno}: ({len(node.value)} chars)')
        print(node.value[:500])
        print('---')
  " 2>/dev/null
done

# External prompt files
find backend/app/processing/ai -name "*.txt" -o -name "*.md" -o -name "*.jinja*" -o -name "*.j2" -o -name "*prompt*" 2>/dev/null | while read f; do
  echo "=== $f ==="
  cat "$f"
done
```

#### 4b. Prompt quality checklist

For EACH system prompt, evaluate:

**Structure:**
- [ ] Clear role definition ("You are a geospatial data assistant...")
- [ ] Explicit output format specification (JSON, SQL, MapLibre style, etc.)
- [ ] Explicit constraints (what NOT to do, boundaries, limitations)
- [ ] Error handling instructions (what to do when uncertain, what to say when query is impossible)

**Context injection:**
- [ ] Dynamic context is clearly delimited (XML tags, markdown headers, JSON blocks)
- [ ] Schema/data context is structured, not dumped as a blob
- [ ] Context includes types, not just names
- [ ] Context size is managed (truncation strategy for large schemas)

**Output control:**
- [ ] Output format is unambiguous (the LLM knows exactly what structure to return)
- [ ] Examples of correct output are included (few-shot)
- [ ] Examples of incorrect output are included (negative examples)
- [ ] Edge case handling is specified (empty results, null values, unsupported operations)

**Provider compatibility:**
- [ ] Prompt works across configured providers (Claude, GPT-4, etc.)
- [ ] No provider-specific syntax (e.g., XML tags that only Claude handles well, function calling schemas that differ between providers)
- [ ] Token budget is appropriate for the model (context window limits)

#### 4c. Few-shot example audit

For each subsystem's few-shot examples:
- Are they representative of real user queries?
- Do they cover the most common query patterns?
- Do they cover edge cases (spatial queries, vector search, text search)?
- Are they correct? (Manually verify each SQL example, each style output, each metadata example)
- Are they minimal? (Bloated examples waste tokens)

**Recommend additions:**
- If no spatial SQL examples → provide PostGIS few-shots
- If no vector search examples → provide pgvector few-shots
- If no style expression examples → provide MapLibre expression few-shots
- If no error handling examples → provide "I can't do that because..." few-shots

#### 4d. Prompt consistency audit

Across all three subsystems:
- Is the persona/voice consistent?
- Is the output format strategy consistent (JSON vs. markdown vs. raw)?
- Are the same patterns used for context injection?
- Is error messaging consistent?

**Output:** Per-prompt analysis with specific rewrite recommendations. Before/after examples for the most impactful improvements.

---

### Subagent 5: Latency, Cost & Caching

**Goal:** Audit token usage, identify caching opportunities, and recommend cost/latency optimizations.

**Process:**

#### 5a. Token usage analysis

```bash
# Model selection per subsystem
grep -rn "model\|gpt\|claude\|sonnet\|haiku\|opus\|turbo\|4o\|o1\|o3" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__

# Max tokens / temperature settings
grep -rn "max_tokens\|temperature\|top_p\|top_k\|max_completion\|stop" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__

# Token counting or cost tracking
grep -rn "token\|usage\|cost\|billing\|count.*token\|tiktoken\|encode" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__
```

For each subsystem, estimate token usage:
- **System prompt size** (count characters, estimate tokens at ~4 chars/token)
- **Schema context size** (can grow large with many datasets/columns)
- **Few-shot example size**
- **User message size** (typically small)
- **Expected output size**
- **Total per-request estimate**

Flag subsystems where prompt context is disproportionately large relative to output.

#### 5b. Model selection optimization

For each subsystem, assess whether the model is right-sized:

| Subsystem | Needs | Recommended model class |
|-----------|-------|------------------------|
| Metadata autocomplete | Low reasoning, structured output, high throughput | Small/fast (Haiku, GPT-4o-mini, Sonnet) |
| SQL generation | High reasoning, schema understanding, safety-critical | Large (Sonnet, GPT-4o, Opus for complex joins) |
| Style generation | Medium reasoning, structured JSON output | Medium (Sonnet, GPT-4o) |
| Simple style tweaks | Low reasoning ("make it blue") | Small/fast (Haiku, GPT-4o-mini) |

**Recommend:**
- If a single large model is used for everything → recommend model routing by complexity
- If schema context is huge → recommend context compression (only include relevant tables/columns)
- If temperature is high for SQL → recommend lowering (SQL needs determinism, not creativity)
- If temperature is low for metadata descriptions → recommend raising slightly (descriptions benefit from variety)

#### 5c. Caching opportunities

```bash
# Existing caching
grep -rn "cache\|Cache\|redis\|lru_cache\|functools\|memoize\|ttl" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__

# Schema context construction — is this rebuilt per request?
grep -rn "def.*schema\|def.*context\|def.*prompt\|build.*context\|get.*schema" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__
```

Cacheable elements:
- **Schema context** — Changes only when datasets/columns change. Cache per dataset, invalidate on schema change.
- **Metadata generation for the same dataset** — Cache results, invalidate on data change.
- **SQL for identical natural language queries on the same dataset** — Short TTL cache (schema-dependent).
- **Style spec for common requests** — "Color by category" patterns can be cached per column type.
- **Embedding lookups** — If metadata autocomplete uses semantic search, cache embedding vectors.

Non-cacheable:
- SQL for queries with user-specific context (viewport, filters)
- Streaming chat responses
- Style adjustments that depend on current map state

#### 5d. Streaming optimization

```bash
# How is streaming implemented?
grep -rn "stream\|SSE\|EventSource\|yield\|chunk\|async.*for\|iter" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__
grep -rn "EventSource\|ReadableStream\|onmessage\|stream" frontend/src/ --include="*.ts" --include="*.tsx" | grep -v node_modules
```

- Is streaming used for chat? (Should be — improves perceived latency)
- Is streaming used for SQL generation? (May not be needed — result is atomic)
- Is streaming used for metadata? (Should not be — result is a complete JSON object)
- Are partial results usable? (e.g., can the frontend start rendering a style change before the full response arrives?)

**Output:** Token usage estimates per subsystem, model sizing recommendations, caching strategy with implementation approach, streaming assessment.

---

### Subagent 6: Hallucination & Grounding Audit

**Goal:** Identify where LLM outputs could hallucinate non-existent tables, columns, functions, or spatial relationships, and recommend grounding improvements.

**Process:**

#### 6a. SQL hallucination vectors

```bash
# How does the LLM know what tables/columns exist?
# (Re-examine from a hallucination perspective)
grep -rn "schema\|table\|column\|available\|exist" backend/app/processing/ai/ --include="*.py" | grep -v __pycache__ | grep -iv "alembic\|migration"
```

SQL hallucination categories:
- **Non-existent tables** — LLM invents table names not in the schema
- **Non-existent columns** — LLM invents column names (especially common with similar-sounding columns)
- **Non-existent PostGIS functions** — LLM generates `ST_NearestNeighbor` (doesn't exist) instead of `ST_DWithin` + `ORDER BY ST_Distance`
- **Wrong function signatures** — `ST_Distance(geom, geom)` is correct, `ST_Distance(geom, geom, 'meters')` is not (needs geography cast)
- **Wrong JOIN paths** — LLM invents foreign keys between unrelated tables
- **Wrong SRID assumptions** — LLM assumes EPSG:4326 when data is in a projected CRS
- **Invented aggregations** — LLM uses `ST_Union` when `ST_Collect` is appropriate, or vice versa

**Check for grounding mechanisms:**
- Is the exact list of tables passed to the LLM? (Not "you have access to geographic data" but "Tables: parks (id int, name text, geom geometry(Polygon, 4326))...")
- Is the exact list of columns with types passed?
- Is the exact list of available PostGIS functions passed (or does the LLM rely on training data)?
- Can the LLM say "I don't know" or "that column doesn't exist"?

#### 6b. Style hallucination vectors

- **Non-existent properties** — LLM references data properties that don't exist in the source
- **Invalid expression syntax** — Plausible-looking but invalid MapLibre expressions
- **Non-existent layer IDs** — LLM references layers that don't exist in the current style
- **Wrong layer type / paint property combinations** — `circle-color` on a `fill` layer

**Check:**
- Is the current style JSON passed to the LLM for modification requests?
- Are available source layer properties passed?
- Is the output validated against the MapLibre style spec before applying?

#### 6c. Metadata hallucination vectors

- **Fabricated descriptions** — LLM generates plausible but inaccurate descriptions of the data
- **Invented keywords** — Keywords that don't relate to actual data content
- **Wrong spatial extent** — LLM guesses a bounding box instead of computing from geometry
- **Wrong temporal extent** — LLM invents date ranges instead of extracting from data
- **Fabricated lineage** — LLM creates a provenance story that isn't true

**Check:**
- Are computed facts (bbox, date range, row count) derived from actual data or LLM-generated?
- Does the prompt clearly distinguish "generate a description" (creative) from "extract the bounding box" (factual)?
- Is the user informed which metadata fields are AI-generated vs. data-derived?

#### 6d. Grounding improvement recommendations

For each hallucination vector, recommend a specific mitigation:
- **Schema grounding** — Exact schema in prompt, with instruction to only use listed tables/columns
- **Function grounding** — Curated function list with signatures, not "use PostGIS functions"
- **Style grounding** — Current style + source properties in context
- **Metadata grounding** — Data-derived facts injected as fixed context, LLM generates only prose fields
- **Validation layer** — Post-LLM validation (SQL parse, style schema check, metadata completeness check)
- **Confidence signaling** — Let the LLM say "I'm not sure" rather than hallucinate

**Output:** Hallucination risk matrix per subsystem, current grounding mechanisms, and specific grounding improvements with implementation approach.

---

## SYNTHESIS (Serial — after all subagents complete)

### Scoring

| Dimension | What it measures |
|-----------|-----------------|
| **SQL Quality** | Correct PostGIS/pgvector/pg_trgm SQL generation, schema grounding |
| **SQL Safety** | Injection prevention, read-only enforcement, query sandboxing |
| **Style Quality** | Correct MapLibre spec, visual design quality, incremental update handling |
| **Metadata Quality** | Standard compliance, grounding in actual data, description usefulness |
| **Prompt Engineering** | Prompt structure, context injection, few-shot coverage, provider compatibility |
| **Efficiency** | Model sizing, token usage, caching, latency |
| **Grounding** | Hallucination resistance across all subsystems |

Grade each A–F:
- **A** — Production-ready. Best practices followed, comprehensive coverage.
- **B** — Good. Minor gaps in coverage or grounding. Works well for common cases.
- **C** — Functional. Significant quality or safety gaps. Works but produces errors on edge cases.
- **D** — Risky. Major safety or quality issues. Will produce incorrect output regularly.
- **F** — Broken or missing. Subsystem doesn't function as intended.

### Optimization Roadmap

Produce a prioritized improvement list. Each item:

| Field | Description |
|-------|-------------|
| Priority | P0 (safety risk — fix before launch), P1 (quality issue — users will hit this), P2 (optimization — improves cost/speed/quality) |
| Subsystem | SQL / Style / Metadata / Cross-cutting |
| Category | Quality / Safety / Efficiency / Grounding / Prompts |
| Action | Specific, implementable task with file path |
| Effort | Hours estimate |
| Impact | What improves (with specifics) |

Sort by: priority → impact → effort.

### Deliverables

For the top 5 highest-impact recommendations, provide ready-to-use implementations:
- **Revised system prompts** — Complete rewritten prompts, not just suggestions
- **New few-shot examples** — Ready to insert, covering identified gaps
- **Validation code** — SQL parser, style schema validator, or metadata completeness checker
- **Caching implementation** — Cache key strategy and invalidation logic
- **Grounding context builders** — Functions that assemble schema/style/metadata context for the LLM

---

## DELIVERY

### Output format

Write the report to: `docs-internal/audits/ai-optimize-{YYYYMMDD}.md`

Write any deliverable code to: `backend/app/processing/ai/` as clearly named files (e.g., `sql_validator.py`, `prompts_v2.py`)

### Report structure

```markdown
# AI Optimization Audit — {YYYY-MM-DD}

## Scorecard
<!-- Grades per dimension -->

## Executive Summary
<!-- 3-5 sentences: current AI quality posture, biggest risks, top recommendation -->

## Architecture Discovery
<!-- Phase 0 summary — provider integration, patterns, subsystem map -->

## 1. SQL Generation
### 1a. Pipeline Analysis
### 1b. Schema Context Quality
### 1c. Output Quality
### 1d. Safety Audit

## 2. MapLibre Style Generation
### 2a. Pipeline Analysis
### 2b. Spec Compliance
### 2c. Visual Quality
### 2d. Validation

## 3. Metadata Autocomplete
### 3a. Pipeline Analysis
### 3b. Standard Compliance
### 3c. Grounding Quality

## 4. Prompt Engineering
### 4a. Per-Prompt Analysis
### 4b. Few-Shot Coverage
### 4c. Consistency Audit

## 5. Latency, Cost & Caching
### 5a. Token Usage
### 5b. Model Sizing
### 5c. Caching Strategy
### 5d. Streaming

## 6. Hallucination & Grounding
### 6a. SQL Hallucination Vectors
### 6b. Style Hallucination Vectors
### 6c. Metadata Hallucination Vectors
### 6d. Grounding Recommendations

## 7. Optimization Roadmap
<!-- Prioritized action items -->

## 8. Ready-to-Use Deliverables
<!-- Revised prompts, few-shots, validation code, caching logic -->

## 9. Comparison to Prior Audit
<!-- If a previous ai-optimize audit exists, diff findings -->
```

### Post-delivery

1. If `lessons.md` exists, append reusable insights about LLM integration patterns for geospatial applications.
2. Print summary: overall grade + count of P0 safety issues + top 3 quality wins.

---

## WHAT NOT TO FLAG

- **LLM generating imperfect but functional SQL** — Minor style issues (extra parentheses, verbose CTEs) are not failures if the query executes correctly and returns right results. Focus on correctness and safety, not SQL aesthetics.
- **Missing support for exotic PostGIS functions** — The LLM doesn't need to know `ST_DelaunayTriangles`. Focus on the top 20 spatial functions that cover 95% of user queries.
- **Temperature settings that are "not optimal"** — Unless temperature is clearly wrong (1.0 for SQL, 0.0 for descriptions), don't prescribe exact values. Note them as tuning opportunities.
- **Not using the latest model** — Model choice is a cost/quality tradeoff. Recommend but don't require the most expensive model.
- **Metadata not perfectly ISO 19115 compliant** — Full ISO 19115 is massive. Focus on the fields that DCAT, STAC, and OGC Records endpoints actually need.
- **No AI governance features** — AI governance (policies, model routing per role) is an enterprise tier feature. Don't flag its absence.
- **Prompt engineering style preferences** — Don't flag "this prompt should use XML tags instead of markdown headers" unless there's a measurable quality difference. Focus on content, not formatting preference.
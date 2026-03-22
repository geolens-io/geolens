# LLM-Enhanced Data Features (Prioritized)

On-prem deployment with PostGIS as the system of record. Features below target the dataset catalog, metadata, and search experience.

## Implementation Status

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 1 | Auto Metadata Summaries | Not started | See `todo.md` "populate metadata using LLM". |
| 2 | Semantic Tagging | Not started | |
| 3 | NL Search & Query Assist | **Partially shipped (v1.9)** | The AI chat's `search_datasets` tool uses full-text catalog search, and `set_filter` generates MapLibre filter expressions from natural language. Standalone NL search on the catalog page is not yet built. |
| 4 | Similarity Search | Not started | |
| 5 | Data Q&A (RAG) | Not started | |
| 6 | Provenance Narratives | Not started | |
| 7 | Version Diff Summaries | Not started | Schema diffs already computed for re-upload flow (`SchemaDiff` type). |
| 8 | Quality Insights | Not started | `quality_score` JSON already computed and stored per dataset. |
| 9 | Content Summaries | Not started | |
| 10 | Field Definition Generation | Not started | |
| 11 | GeoQuery Translation | **Partially shipped (v1.9)** | Chat `set_filter` translates NL to MapLibre filter expressions. Full PostGIS SQL/CQL translation not built. |
| 12 | User Recommendation | Not started | |

## Existing Infrastructure to Build On

The v1.9 AI infrastructure (phases 52-53) provides reusable building blocks for all features below:

- **LLM provider abstraction** (`app.ai.service`, `app.ai.chat_service`): Supports Anthropic (native tool_use) and any OpenAI-compatible API (Ollama, Groq, Together, etc.). Provider selection, connection handling, and error mapping are already implemented.
- **Tool-calling pipeline**: Up to 5 LLM round-trips with structured tool schemas (Anthropic and OpenAI formats in `app.ai.tools`). Easy to add new tools.
- **Column stats helpers** (`app.datasets.column_stats`): `get_column_stats()` returns min/max/mean/quantiles, `get_distinct_values()` returns unique values. Already used by the chat `set_data_driven_style` tool.
- **Dataset search** (`app.search.service`): Full-text search with geometry_type and tag filters. Used by AI map generation and chat.
- **Quality scores**: Computed on ingest -- `quality_score` JSON with `metadata_completeness`, `geometry_validity`, `attribute_completeness`, `crs_defined`.
- **Schema diffs**: Computed during re-upload (`SchemaDiff` with columns_added/removed, type_changes, row_count_delta).
- **Runtime AI toggle** (`app.settings.service`): `AppSettingsService` with DB-backed on/off switch and 30s TTL cache. New AI features should check `is_ai_enabled()`.
- **Audit logging** (`app.audit`): Action logging infrastructure exists for tracking LLM interactions.

## Remaining Features

### 1. Auto Metadata Summaries
*Description:* Auto-generate human-readable titles and descriptions for datasets with sparse metadata.

**Implementation approach:** Use existing LLM provider abstraction. Prompt with table name, column_info, sample rows (query via `get_distinct_values`), existing tags. Return structured JSON. Present for human review before committing.

**Key files:** `app.ai.service` (provider abstraction), `app.datasets.models` (Dataset.description, Dataset.tags), `app.datasets.column_stats` (sample data).

**No pgvector needed** for the basic version -- few-shot prompting with the dataset's own metadata is sufficient. Embeddings only needed if doing cross-dataset example retrieval.

**Effort:** S-M (3-4 weeks). Simpler than originally estimated since LLM infra exists.

### 2. Semantic Tagging
*Description:* Suggest relevant keywords/tags for datasets using NLP.

**Implementation approach:** Similar to auto metadata -- prompt LLM with column names, sample values, existing tags. Return suggested tags from a controlled vocabulary. Could batch-run across all datasets.

**Effort:** S (2 weeks). Can share the same prompt/review UI as Auto Metadata Summaries.

### 3. NL Search (Catalog Page)
*Description:* Accept natural-language queries on the catalog search page and return matching datasets.

**What already exists:** `search_datasets` in `app.search.service` does full-text search with tag/geometry filters. The AI chat uses this via tool calling. What's missing is a standalone NL-to-search-params translation on the catalog page.

**Implementation approach:** Add an LLM step that translates NL query into search params (q, geometry_type, tags), then calls existing search. Frontend: detect NL intent (or add a toggle) on the search page.

**Effort:** S (2-3 weeks).

### 4. Similarity Search
*Description:* "Related datasets" suggestions via semantic similarity.

**Implementation approach:** Requires pgvector extension. Precompute embeddings of dataset name + description + tags. On dataset view, query nearest neighbors. Filter by user access.

**Prerequisites:** pgvector extension installed, embedding model (could use Ollama embeddings endpoint).

**Effort:** M (3-4 weeks).

### 5. Data Q&A (RAG)
*Description:* Answer questions about catalog data ("Which datasets have population columns?").

**Implementation approach:** RAG pipeline: embed dataset metadata into pgvector, retrieve relevant context on query, prompt LLM with context. More complex than other features -- needs retrieval pipeline, context windowing, and hallucination guardrails.

**Prerequisites:** pgvector, embedding pipeline from Similarity Search.

**Effort:** L (6-8 weeks). Best tackled after Similarity Search provides the embedding infrastructure.

### 6. Provenance Narratives
*Description:* Human-friendly summaries of dataset lineage.

**What already exists:** `ingest_jobs` table tracks source_filename, status, timestamps, user. `dataset_versions` tracks version history. `audit_logs` tracks user actions.

**Implementation approach:** Query lineage data, prompt LLM to summarize. Straightforward.

**Effort:** S (1-2 weeks).

### 7. Version Diff Summaries
*Description:* LLM-summarized changes between dataset versions.

**What already exists:** `SchemaDiff` type (columns_added/removed, type_changes, row_count_delta) already computed during re-upload. `dataset_versions` table exists.

**Implementation approach:** Feed existing `SchemaDiff` JSON to LLM for plain-language summary. Most of the hard work (diff computation) is done.

**Effort:** S (1-2 weeks).

### 8. Quality Insights
*Description:* LLM-generated plain-language reports on data issues.

**What already exists:** `quality_score` JSON already computed per dataset with `metadata_completeness`, `geometry_validity`, `attribute_completeness`, `crs_defined` scores. Column stats available via `get_column_stats`.

**Implementation approach:** Prompt LLM with quality_score + column stats. Return actionable tips. Could display as a banner on the dataset detail page.

**Effort:** S (1-2 weeks). Very low effort since all inputs already exist.

### 9-12. Lower Priority
- **Content Summaries** (S, 1-2w): Similar to Auto Metadata -- prompt with row count, columns, extent.
- **Field Definition Generation** (M, 3-4w): Prompt with column name + sample values to generate data dictionary entries.
- **GeoQuery Translation** (L, 6-8w): Full NL-to-PostGIS/CQL. The chat `set_filter` handles MapLibre expressions; extending to SQL WHERE clauses for the catalog would be a separate effort.
- **User Recommendation** (S, 2w): Match dataset keywords to user roles. Requires a richer user profile model.

## Recommended Build Order

Given existing infrastructure, prioritize by effort-to-value ratio:

1. **Quality Insights** (1-2w) -- all inputs exist, high user value
2. **Version Diff Summaries** (1-2w) -- SchemaDiff already computed
3. **Provenance Narratives** (1-2w) -- lineage data exists
4. **Auto Metadata Summaries** (3-4w) -- highest rated feature, LLM infra ready
5. **NL Search** (2-3w) -- extends existing search + AI chat patterns
6. **Similarity Search** (3-4w) -- requires pgvector setup, unlocks Data Q&A
7. **Data Q&A** (6-8w) -- depends on Similarity Search embeddings

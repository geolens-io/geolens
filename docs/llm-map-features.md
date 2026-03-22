# LLM-Enabled Map Features

On-prem friendly, small team, PostGIS-native. Prioritized LLM capabilities for the Maps feature.

## Implementation Status

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 1 | Natural-Language Map Builder | **Shipped (v1.9)** | Phase 52. Full tool-calling pipeline with catalog search. |
| 2 | Layer/Content Recommendation | Not started | Chat can already `add_layer` via search; embedding-based recs are the next step. |
| 3 | Auto-Style & Theming | **Partially shipped (v1.9)** | Chat `set_data_driven_style` generates categorical/graduated styles with Brewer ramps. Manual UI also supports data-driven styling. Full "auto-suggest on add" not yet wired. |
| 4 | Map Caption/Narration | Not started | |
| 5 | Accessibility Alt-Text | Not started | |
| 6 | Pattern/Anomaly Description | Not started | |
| 7 | Map Version Commentary | Not started | |

## What Was Built (v1.9 / Phase 52-53)

### AI Map Generation (`POST /ai/generate-map/`)
- User provides a natural-language prompt (e.g. "Show major roads and country boundaries").
- LLM uses `search_datasets` tool (up to 5 rounds) to find matching catalog datasets.
- LLM returns a structured `LLMMapSpec` JSON: map name, description, viewport, basemap, layer list with paint/layout.
- Backend creates the map + layers via `maps.service`, returns `map_id` and explanation.
- Frontend: "AI Generate" tab in MapCreateDialog triggers the flow and navigates to the new map.

### AI Chat Map Editing (`POST /ai/chat/`)
- Conversational editing of an existing map. Frontend sends current layer state + user message.
- LLM has tool-calling access to 8 actions:
  - `search_datasets` -- find datasets in catalog
  - `set_filter` -- MapLibre filter expressions (e.g. `["all", [">", "population", 1000000]]`)
  - `set_style` -- flat paint properties (fill-color, line-width, etc.)
  - `set_data_driven_style` -- categorical/graduated `style_config` with Brewer ramps, column stats lookup (`get_column_stats`, `get_distinct_values`)
  - `set_label` -- text labels with font, halo, placement
  - `toggle_visibility` -- show/hide layers
  - `add_layer` / `remove_layer` -- add from catalog or remove existing
- Frontend ChatPanel applies returned actions live to the map (no save required until user confirms).

### Provider Support
- **Anthropic** (Claude) -- primary, uses native tool_use
- **OpenAI-compatible** -- fallback, supports any OpenAI-API-compatible provider (Ollama, Groq, Together, etc.) via `OPENAI_BASE_URL`
- Provider/model configured via env vars: `ANTHROPIC_API_KEY`, `LLM_MODEL`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL`

### Admin AI Toggle (Phase 53)
- `catalog.app_settings` table stores runtime config (key/value JSONB).
- `GET /admin/ai-status/` returns provider, model, enabled, configured (any authenticated user).
- `PATCH /admin/ai-status/` toggles AI on/off at runtime (admin only), with 30s TTL cache.
- Frontend: AI Status card on admin Overview tab with Switch. Chat button and AI Generate tab conditionally rendered based on toggle + configured state.

## Remaining Features

### 2. Layer/Content Recommendation
*Description:* Smart suggestions for additional layers based on what's already on the map (e.g. adding neighborhood boundaries when viewing crime data). *Inputs:* Current map layers, dataset metadata (tags, descriptions), user context. *Privacy:* On-prem; ensure access rights for suggested layers.

**Implementation notes:** The chat `add_layer` action already lets the LLM suggest and add datasets. A non-LLM approach using pgvector embeddings of dataset metadata would provide instant recommendations without an LLM round-trip. Could surface as a "Suggested Layers" section in the map builder sidebar.

**Prerequisites:** pgvector extension, embedding model (or precomputed embeddings via batch job).
**Effort:** M (3-4 weeks given existing infrastructure).

### 4. Map Caption/Narration
*Description:* Auto-generate a textual summary/caption of the map for sharing contexts. *Inputs:* Map layers, title, filters, spatial extent.

**Implementation notes:** Straightforward LLM prompt with map metadata. Could be triggered on share/export. The AI chat infrastructure (`app.ai`) already handles provider abstraction and tool calling -- a simple non-tool prompt would be simpler. Consider adding to the share/export flow.

**Effort:** S (1-2 weeks).

### 5. Accessibility Alt-Text
*Description:* Auto-generated descriptions of the map for screen readers. *Inputs:* Map layers, legend items, visible features.

**Implementation notes:** Similar to caption generation but focused on spatial description. Could reuse the same LLM prompt pathway. Would need to be triggered on map render/change and injected into the `<canvas>` aria attributes.

**Effort:** S (1-2 weeks).

### 6. Pattern/Anomaly Description
*Description:* Alerts on notable spatial patterns (e.g. "High congestion cluster in downtown"). *Inputs:* Layer data summary (clusters, outliers from DB stats).

**Implementation notes:** Requires PostGIS spatial analysis (ST_ClusterDBSCAN, hotspot detection) run as a backend task, then LLM summarization of findings. More complex than other features -- needs new SQL analysis pipeline.

**Effort:** M (4-6 weeks).

### 7. Map Version Commentary
*Description:* Explain differences between map saves/versions. *Inputs:* Layer version metadata, change logs.

**Implementation notes:** Maps already have `updated_at` and layers track `sort_order`, `paint`, `filter`, etc. A diff could be computed between saves. Currently maps don't have a version history table -- would need one first.

**Prerequisites:** Map version/history tracking.
**Effort:** S (2-3 weeks after version tracking exists).

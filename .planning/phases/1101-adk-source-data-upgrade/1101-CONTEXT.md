# Phase 1101: ADK Source Data Upgrade - Context

**Gathered:** 2026-05-24
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Replace or explicitly improve the ADK marketing source-data inputs before map composition.
</domain>

<decisions>
## Implementation Decisions

### the agent's Discretion
Use the 260524-o57 dogfooding draft as the source of truth. Query TNM for NAIP first and record exact evidence. If TNM returns no NAIP products for the AOI, implement a higher-fidelity documented fallback instead of silently retaining the original soft 3.5 MB aerial. Add NHD hydrography and complete official 46er peak generation without requiring manual host GDAL.
</decisions>

<code_context>
## Existing Code Insights

- `scripts/marketing-data/adk-high-peaks/fetch_aerial.py` previously used a single NY orthos export.
- `build_aerial_cog.sh` builds the aerial COG inside `geolens-api-1`.
- `fetch_vectors.py` already downloads APA and NYSDEC vector layers.
- `compose_marketing_maps.py` ingests files and composes maps via the GeoLens API.
</code_context>

<specifics>
## Specific Ideas

- Persist `.scratch/adk-data/aerial/tnm_naip_query.json`.
- Use a 4x4 grid of 4096px NY orthos fallback tiles when TNM NAIP is unavailable.
- Fetch USGS NHD large-scale flowlines and waterbodies from `https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer`.
- Generate all 46 official 46er peaks from APA Summits layers 0, 1, and 2.
</specifics>

<deferred>
## Deferred Ideas

Native NYS DHSES county-tile downloads remain manual UI/email workflow and are out of scope for this automated pipeline.
</deferred>

---
phase: quick-260324-qln
plan: 01
type: execute
wave: 1
depends_on: []
files_modified: [FEATURES.md]
autonomous: true
requirements: [FEATURES-ONE-PAGER]

must_haves:
  truths:
    - "Reader understands what GeoLens is in the first sentence"
    - "Reader can identify all major capability areas (search, ingest, maps, AI, standards, admin, deployment)"
    - "Document fits on one printed page (~600-800 words)"
  artifacts:
    - path: "FEATURES.md"
      provides: "Comprehensive one-pager of GeoLens capabilities"
      contains: "GeoLens"
  key_links: []
---

<objective>
Write a comprehensive but succinct one-pager documenting the current capabilities and features of GeoLens.

Purpose: Provide a polished summary document suitable for stakeholders, potential users, or README linking that covers every major capability area without reading like a changelog.
Output: FEATURES.md at project root
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Write FEATURES.md one-pager</name>
  <files>FEATURES.md</files>
  <action>
Create FEATURES.md at the project root. The document should be a polished, scannable one-pager (~600-800 words) organized by capability area, NOT by version or milestone. Use concise prose with bullet points where appropriate.

Structure the document with these sections:

1. **Opening paragraph** (2-3 sentences) — what GeoLens is, who it's for, core value prop ("find any dataset in seconds — search, preview on a map, understand it, export it"). Mention on-premises, PostGIS-native, Docker Compose deployment.

2. **Search and Discovery** — full-text search + pgvector semantic search, faceted filtering (record type, keywords, CRS, source organization, temporal), type toggle badges with live counts (vector/raster/VRT/collection), saved searches, search ranking boosts, related dataset discovery, OGC Records Part 1 conformance.

3. **Data Ingestion** — file upload (Shapefile, GeoJSON, GeoPackage, CSV, Excel), service URL import (WFS, ArcGIS Feature Service with auth), raster COG ingestion with auto-conversion, VRT mosaic creation from compatible rasters, non-spatial table support (CSV/XLSX), bulk upload, pre-import preview with schema/CRS/sample rows, re-upload with schema diff and atomic swap, dataset version history. Natural Earth seed script for demo data.

4. **Map Visualization** — vector tiles via ST_AsMVT, raster tiles via Titiler, feature popups, basemap management (admin presets, custom XYZ/TMS, dark/light auto-switch), zoom-to-extent, configurable default center/zoom.

5. **Map Builder** — create and save interactive maps, layer styling (fill/stroke/circle with color picker), data-driven styling (categorical/graduated with Brewer ramps), layer filters (visual builder), labels (attribute picker, font/color/halo), drag-and-drop reordering, layer rename, opacity control, raster layers, VRT layers, map copy/fork with lineage, legend control, resizable sidebar.

6. **AI Assistant** — natural-language map generation from prompt, conversational chat for map editing (styles, filters, labels, add/remove layers), @mention layers and slash commands, text-to-SQL spatial queries with ephemeral result layers, multi-provider LLM support (Anthropic, OpenAI-compatible for Ollama/Groq/Together), admin enable/disable toggle.

7. **Layer Editing** — create empty layers by geometry type, draw features (point/line/polygon/rectangle/circle/freehand), move/edit vertices/delete, attribute editing, schema modification (add/remove columns), undo, vertex snapping.

8. **Standards and Interop** — OGC API Records Part 1, OGC API Features (bbox/property filtering, paginated GeoJSON), CQL2 text+JSON filtering, STAC 1.1 export (catalog/items/collections/search), DCAT metadata, queryables/schema introspection.

9. **Collections and Organization** — flat multi-membership collections, collection browse with cards and search, collection landing pages, publication lifecycle (draft/ready/internal/published), foreign key relationship detection with related records panel.

10. **Export** — GeoJSON, Shapefile, GeoPackage, CSV, COG download for raster. Secure share links with expiration. Embeddable map viewer with domain restrictions.

11. **Administration** — user management (create/edit/delete, approval flow), RBAC (viewer/editor/admin) with granular per-role permission toggles, API key management, OAuth/OIDC (Google, Microsoft, generic) with PKCE and group-to-role mapping, audit logging with change history, config export/import with dry-run diff, admin dashboard (storage, jobs, infrastructure health).

12. **Security and Operations** — JWT + refresh token auth, magic byte file validation, zip bomb detection, SSRF protection, signed tile URLs, SQL sandbox with AST validation, rate limiting, Prometheus metrics, automated S3 backups with retention, Redis circuit breaker, structured JSON logging with correlation IDs, Trivy CI scanning.

13. **Deployment** — single `docker compose up` deployment, 4 services (API, worker, PostGIS, Titiler), provider-agnostic storage (local/S3), caching (in-memory/Redis), presigned uploads, dark/light theme, i18n support, route-based code splitting, WCAG AA accessibility (touch targets, keyboard navigation, screen reader support).

Tone: professional, factual, no marketing fluff. Write for a technical audience (GIS analysts, data engineers, IT admins evaluating the product). Do not mention version numbers — present capabilities as the current state.
  </action>
  <verify>
    <automated>wc -w FEATURES.md | awk '{if ($1 >= 400 && $1 <= 1000) print "PASS: " $1 " words"; else print "FAIL: " $1 " words (expected 400-1000)"}'</automated>
  </verify>
  <done>FEATURES.md exists at project root, covers all major capability areas, reads as a cohesive one-pager under 1000 words</done>
</task>

</tasks>

<verification>
- FEATURES.md exists at project root
- Document covers search, ingestion, maps, AI, standards, admin, deployment
- Word count between 400-1000 (one-pager territory)
- No version numbers or changelog-style entries
</verification>

<success_criteria>
A reader unfamiliar with GeoLens can read FEATURES.md and understand every major capability area in under 3 minutes.
</success_criteria>

<output>
After completion, create `.planning/quick/260324-qln-write-a-comprehensive-but-succinct-one-p/260324-qln-SUMMARY.md`
</output>

# Requirements: GeoLens — v1031 Builder Render-Mode & Share Polish

**Defined:** 2026-05-28
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

Milestone v1031 closes the v1030 builder carry-forward backlog: four new render-mode editor controls (999.18 render-mode sub-group), shared-link social cards (999.17 / SHARE-08), and SharePanel font-weight hygiene (999.19 / F2), proven on the live builder via intensive Playwright MCP smoke.

## v1 Requirements

### Render-Mode Controls

New per-render-mode editor controls extending the v1026 owned-property contracts and v1010/v1030 per-mode editor split. Each adds an authoring control; behavior preservation for existing controls is the default.

- [ ] **EDITOR-FILL-01**: User can apply a fill-pattern to a fill-render-mode layer via the editor (pattern selection flow; sprite-backed). Plan-time sizing call: a curated built-in pattern set vs arbitrary user sprite upload — prefer built-in selection first and defer custom-upload backend (sprite storage/serving) to Future if it balloons.
- [ ] **EDITOR-DEM-04**: User can enable and configure a contour-line overlay on a DEM/terrain layer (toggle + line styling).
- [ ] **EDITOR-DEM-05**: User can apply a hypsometric (elevation) tint color ramp to a terrain/DEM layer from a preset ramp set.
- [ ] **EDITOR-RASTER-COLORMAP**: User can apply a single-band stretch + colormap to a raster layer via the editor. Depends on backend single-band colormap render-path scoping (Titiler) — researched at plan-phase.

### Sharing & Social Cards

- [ ] **SHARE-08**: Shared map links emit OG-image / social-card meta (`og:image`, `twitter:card`) backed by a 1200×630 map preview. Path A (nullable `og_image_uri` column + `PUT`/`GET /maps/{id}/og-image/` routes + frontend dual `doCapture`) vs Path B (backend resize from the native canvas capture) decided in a planning audit. Do NOT add `@vercel/og` or `satori` (STACK do-not-add list). Carried from v1030 Phase 1133 WALK-05 disposition.
- [ ] **SHARE-10**: SharePanel renders ≤2 font weights (UI-SPEC max-2 conformance), reduced from the current 3 weights across 5 sites. Cosmetic. (v1030 milestone-audit finding F2.)

### Quality & Close-Gate

- [ ] **QA-01**: Builder verified via intensive live Playwright MCP smoke against `http://localhost:8080/maps/8dd6a129-8eb0-4ba9-b421-716c83b160dd`, exercising each new render-mode control and the share/OG flow, with a committed evidence file. Orchestrator drives MCP directly (subagents lack `mcp__playwright__*`).
- [ ] **QA-02**: Touched-surface gates green — frontend typecheck + lint + vitest, focused backend pytest, `e2e:smoke:builder`, and i18n parity (en/de/es/fr).
- [ ] **QA-03**: CHANGELOG updated for v1031; OpenAPI + Python/TypeScript SDK regenerated where backend routes/schema changed (e.g., OG-image routes under Path A, raster colormap params).

## Future Requirements (v1032+)

Parked in the 999.18 backlog register — explicitly OUT of v1031 per milestone scoping (2026-05-28).

### Editor convenience (999.18 sub-group)

- **EDITOR-SYMBOL-04**: Categorical icon mapping for symbol layers with a real distinct-value query (`useColumnDistinctValues` exists post-WALK-01).
- **EDITOR-BASEMAP-06**: Custom basemap style URL override (architecture-shaped).

### Layer-type expansion (999.18 sub-group)

- **LAYER-TEXT-01**: Text/annotation layer ("Render as Text"). Feature-milestone-sized.
- **LAYER-DRAW-01**: Draw/annotation layer (text + shapes). Feature-milestone-sized.
- **LAYER-LIDAR-01**: LiDAR point-cloud support. Feature-milestone-sized.

## Out of Scope

Explicitly excluded from v1031. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| `@vercel/og`, `satori` | On STACK explicit do-NOT-add list; OG-image generation uses the existing canvas-capture pipeline (Path A/B), not an HTML-to-image renderer. |
| 999.18 editor-convenience + layer-type expansion | Scoped OUT 2026-05-28 — render-mode sub-group only this milestone; rest stays parked in 999.18. |
| Builder architecture rewrites | v1031 is feature-add on the v1026/v1027 substrate; no new files >500 LOC, no rename of >3 exported symbols, no controller/action-boundary widening without a Future Requirement entry first. |
| New LLM provider integrations | Out of milestone theme; AI chat substrate unchanged. |
| Marketing / docs-site work | Lives in the `getgeolens.com` sibling repo. |
| New connector backends | Open-core/Enterprise backlog (999.13), not this milestone. |
| Enterprise edition changes | Open-core boundary frozen for this milestone. |
| Open-core / Cloud backlog (999.6 / 999.13-16) | Tenant scoping, connector registry, Helm/AMI, SBOM, schemas package — separate larger initiatives. |
| CI-01 GH Actions billing | Ops task (operator must resolve org billing), not a code phase. Tracked as a standing blocker. |

## Traceability

Which phases cover which requirements. Populated during roadmap creation (continues phase numbering from 1140).

| Requirement | Phase | Status |
|-------------|-------|--------|
| EDITOR-DEM-04 | Phase 1140 | Pending |
| EDITOR-DEM-05 | Phase 1140 | Pending |
| EDITOR-RASTER-COLORMAP | Phase 1140 | Pending |
| EDITOR-FILL-01 | Phase 1141 | Pending |
| SHARE-08 | Phase 1142 | Pending |
| SHARE-10 | Phase 1142 | Pending |
| QA-01 | Phase 1143 | Pending |
| QA-02 | Phase 1143 | Pending |
| QA-03 | Phase 1143 | Pending |

**Coverage:**
- v1 requirements: 9 total
- Mapped to phases: 9 ✓
- Unmapped: 0 ✓

---
*Requirements defined: 2026-05-28*
*Last updated: 2026-05-28 — traceability populated (roadmap v1031, phases 1140-1143)*

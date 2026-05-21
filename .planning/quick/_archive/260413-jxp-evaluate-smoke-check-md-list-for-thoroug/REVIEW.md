# Smoke-Check.md Review (Corrected)

**Date:** 2026-04-13
**Method:** Cross-referenced smoke-check.md against all frontend routes (30+), backend API endpoints (201), existing Playwright specs (48 smoke + 6 additional), and verified claims against source code.

---

## Overall Assessment

The checklist is **solid for a manual walkthrough** — it covers the critical path well and the priority tiers (P0/P1/P2) are sensible. The main weakness is **coverage gaps in features that exist in the codebase but aren't represented**, and structural issues that hurt maintainability.

**Score: ~70% coverage** of the actual app surface area.

---

## A. Coverage Gaps — Features That Exist But Aren't Tested

### P0-Level Gaps

| # | Missing Item | Evidence | Notes |
|---|-------------|----------|-------|
| 1 | **Search typeahead / prefix search** | `SearchTypeahead.tsx`, tested in `search.spec.ts` | Type ≥2 chars → dropdown with keyboard nav (↑↓ Enter Esc). Core discovery UX |
| 2 | **Search query param handling** | Tested in `search.spec.ts` (`/?q=Zoning`) | URL-driven search for bookmarks/sharing — not mentioned |
| 3 | **MapViewerGate routing** | `MapViewerGate.tsx` — checks `isEditor()` (admin\|editor → builder, else → public viewer) | `/maps/:id` silently routes by role. Could send editors to wrong view if broken |
| 4 | **Tile auth verification** | `tiles/router.py` — multi-priority: embed token → JWT user → public (published only) | Security gap: tiles leaking without auth is a real vulnerability. Spot-check that unpublished dataset tiles return 401/403 for anonymous |
| 5 | **Context guard (unsaved changes)** | Tested (skipped) in `dataset-detail.spec.ts` | Switching tabs with unsaved edits → Save & switch / Discard dialog. Not in checklist |
| 6 | **Permissions API endpoint** | Tested in `permissions.spec.ts` | `GET /api/auth/me/permissions/` returns 8 capabilities — not in checklist |
| 7 | **Role-gated nav items** | Tested in `permissions.spec.ts` | Admin sees Admin link in user menu, editor sees Import in Create menu — not verified |

### P1-Level Gaps

| # | Missing Item | Evidence | Notes |
|---|-------------|----------|-------|
| 8 | **Quality Score Card** | `QualityScoreCard.tsx` | Weighted scoring (metadata 30%, geometry 30%, attributes 25%, CRS 15%) + freshness badges |
| 9 | **Validation Status + Troubleshoot Panel** | `ValidationStatus.tsx`, `ValidationTroubleshootPanel.tsx` | Blocks publishing — groups errors by cause with remediation hints |
| 10 | **Change History** | `ChangeHistory.tsx` | Shows who changed what, when — audit/governance |
| 11 | **Version History** | `VersionHistory.tsx` | Shows all previous uploads with version number, format, feature count |
| 12 | **Used in Maps card** | `UsedInMaps.tsx` | Shows which maps reference a dataset — dependency tracking |
| 13 | **Public viewer query params** | `PublicViewerPage.tsx` | `?zoom=&center=&legend=&embed=&et=&api_key=` — deep-linking and embed mode |
| 14 | **Maps page: view toggle** | `MapsPage.tsx` — List/Grid with localStorage persistence | Not mentioned at all |
| 15 | **Maps page: visibility filter** | `MapsPage.tsx` — all/private/internal/public | Not mentioned |
| 16 | **Maps page: sort options** | `MapsPage.tsx` — updated_at, created_at, name | Not mentioned |
| 17 | **Sidebar collapsed state persistence** | Tested in `builder.spec.ts`, uses localStorage | Survives reload — regression risk |
| 18 | **Sidebar width persistence** | Tested in `builder.spec.ts` — drag handle resize persists via localStorage | Related but distinct from collapse |
| 19 | **Raster tile 404 toast suppression** | Tested in `builder.spec.ts` | Tile 404s must NOT surface as error toasts |
| 20 | **Style persistence after collapse/re-expand** | Tested in `builder-styling.spec.ts` | Categorical colors must survive layer collapse |
| 21 | **Filter/label icon badges** | Tested in `builder-styling.spec.ts` | Funnel icon when filter active, T icon when labels enabled |
| 22 | **Zoom to layer** | Tested in `builder.spec.ts` | Per-layer action that changes viewport — not in checklist |
| 23 | **Map Info dialog** | Tested in `builder.spec.ts` | More actions → Map info → dialog with metadata |
| 24 | **Spatial Extent Card** | `SpatialExtentCard.tsx` | Bbox map preview on dataset overview |
| 25 | **Temporal Extent Card** | `TemporalExtentCard.tsx` | Date range for temporal datasets |
| 26 | **Contacts Editor CRUD** | `ContactsEditor.tsx` | ISO 19115 contact roles (pointOfContact, author, publisher, etc.) |
| 27 | **AI generate-map streaming** | `POST /ai/generate-map/stream/` — separate from chat | Item 29 covers chat but not map generation SSE |
| 28 | **Basemap switch preserves layers** | Tested in `builder.spec.ts` | Switching basemap must not drop overlay layers |

### P2-Level Gaps

| # | Missing Item | Evidence | Notes |
|---|-------------|----------|-------|
| 29 | **Legacy admin redirects** | 13 Navigate redirects in App.tsx (e.g., `/admin/basemaps` → `/admin/settings/map`) | Old bookmarks should still work. Zero coverage |
| 30 | **Negative/destructive tests** | Only 4 error-state items (section 50) | Missing: invalid file upload, oversized file, empty required fields, expired token, insufficient permissions, duplicate name |
| 31 | **Performance baselines** | None mentioned | Even rough thresholds catch regressions: search < 3s, detail < 2s, builder paint < 5s |
| 32 | **CQL2 conformance gap** | OGC router declares CQL2 conformance but only implements simple property filters | Not a checklist gap per se — but the checklist shouldn't test CQL2 since it's not implemented |

---

## B. Structural Issues

### 1. No Test Data Prerequisites
The checklist assumes fixture data exists but never specifies it. Should add at top.

### 2. No Spec-File Mapping
Header says "keep in sync" but there's no traceability between checklist sections and owning spec files.

### 3. Compound Checkboxes
Several items test 3-5 things in one box. Worst offenders:
- Line 75: "Geometry type, feature count, CRS display" (3 data points)
- Line 109: "Drawing toolbar appears with 6 modes (Point, Line, Polygon, Rectangle, Circle, Freehand)"
- Line 431: "map name, creator, status, expiration, dates display" (5 assertions)

### 4. Vague "Works" Assertions
Many items say "works" without defining success:
- "Zoom controls work" → "Zoom in increases zoom level; zoom out decreases it"
- "Fullscreen button expands map" → "Map fills viewport; Esc exits fullscreen"
- "Fill color picker works" → "Change fill → features re-render with new color"
- "Clear measurements button works" → "All measurement overlays removed from map"

### 5. Missing Automated Suites Reference
The suites section only lists 3 smoke buckets. Missing: `e2e:export` (API export validation), accessibility spec, demo-smoke specs.

---

## C. Priority Tier Adjustments

| Item | Current | Suggested | Reason |
|------|---------|-----------|--------|
| Tile auth (new) | — | P0 | Security: unpublished tiles must not leak |
| Config Ops (#45) | P2 | P1 | Breaking config import/export is a deployment blocker |
| Responsive (#49) | P2 | P1 | 768px affects real laptop users |
| Registration (#16) | P1 | P2 | Only relevant if registration enabled |

---

## D. What's Done Well

- Priority tiers (P0/P1/P2) with clear definitions
- Admin settings coverage is thorough (every tab)
- OGC/STAC/DCAT standards coverage
- Feature editing workflow detail (draw → edit → discard)
- Section numbering for cross-referencing
- Automated suite section linking to npm commands

---

## E. Corrections from QA Pass

Items from the first draft that were **wrong or misleading**:

| Original Claim | Correction |
|----------------|------------|
| "Bulk delete — P0, should be smoke-tested" | API-only (`POST /datasets/bulk-delete/`), no frontend UI. Not user-facing |
| "Password change — `PUT /auth/password/`" | Actual: `POST /auth/change-password/`. No frontend UI exists — backend-only |
| "Presigned upload — `POST /ingest/presigned-url/`" | Actual: `POST /ingest/upload/presigned` |
| "11 legacy admin redirect routes" | Actually 13 admin redirects + 1 non-admin |
| "CQL2 filtering not tested" | CQL2 declared but not implemented — property filters only |
| "~75% coverage" | Revised to ~70% after finding more UI component gaps |

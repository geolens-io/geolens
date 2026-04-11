# Requirements: getgeolens.com Marketing Site

**Defined:** 2026-04-04
**Core Value:** Users can find any dataset in the catalog in seconds — search, see it on a map, understand what it is, and get it out in the format they need.

## v14.0 Requirements

Requirements for the getgeolens.com marketing site launch. Each maps to roadmap phases.

### Site Foundation

- [x] **SITE-01**: Separate repo initialized with Astro 6 + Tailwind CSS 4, GeoLens brand tokens (emerald accent, Inter font, OKLCH color space)
- [x] **SITE-02**: Site deploys to Cloudflare Pages with git-push auto-deploy and PR preview deploys
- [ ] **SITE-03**: Shared nav with logo, page links (Home, Features, Quickstart), and GitHub link
- [ ] **SITE-04**: Footer with project links, license badge, and "Powered by GeoLens" attribution
- [ ] **SITE-05**: Responsive layout works across phone (375px), tablet (768px), and desktop (1280px+)

### Homepage

- [ ] **HOME-01**: Hero section with outcome-focused headline, subtitle, and primary "Get Started" CTA
- [ ] **HOME-02**: Trust signal bar visible near hero — Apache 2.0, OGC API Compliant, Self-Hosted badges
- [ ] **HOME-03**: Feature highlights section showcasing 3-4 key capabilities with icons and short descriptions
- [ ] **HOME-04**: Stylized product preview showing the GeoLens search UI in a browser frame
- [ ] **HOME-05**: Quickstart teaser section linking to the quickstart page

### Features Page

- [ ] **FEAT-01**: Capability sections covering search, map builder, data ingestion, raster/VRT, AI chat, and RBAC
- [ ] **FEAT-02**: Each capability section includes a description, key points, and a stylized product preview
- [ ] **FEAT-03**: OGC API compliance and standards section with supported conformance classes

### Quickstart Page

- [ ] **QUICK-01**: Step-by-step guide from zero to running GeoLens via docker compose
- [ ] **QUICK-02**: Copyable code blocks with environment setup, docker compose commands, and first-login instructions
- [ ] **QUICK-03**: Expected outcome description (what the user sees after completing the quickstart)

### Visual Assets

- [ ] **ASSET-01**: Stylized product preview for search/catalog UI (CSS-rendered browser frame)
- [ ] **ASSET-02**: Stylized product preview for map builder UI
- [ ] **ASSET-03**: Stylized product preview for dataset detail page

### SEO

- [ ] **SEO-01**: Unique title and meta description on every page
- [ ] **SEO-02**: OG images generated per page via Satori at build time
- [ ] **SEO-03**: sitemap.xml and robots.txt generated automatically
- [ ] **SEO-04**: JSON-LD structured data (SoftwareApplication + Organization)

### Accessibility

- [x] **A11Y-01**: All text meets WCAG 2.1 AA contrast ratios (emerald-700 minimum for accent on white)
- [ ] **A11Y-02**: Full keyboard navigation across all pages and interactive elements
- [ ] **A11Y-03**: Semantic HTML landmarks (nav, main, footer, headings hierarchy)
- [ ] **A11Y-04**: Axe accessibility scan passes with zero critical/serious violations

### Backend Ingest Quality

Requirements covering ingest-side data-quality correctness observed in post-impl audits and regression-tested in dedicated phases.

- [ ] **INGEST-N6-01**: `get_sample_values()` default `sample_size` is bumped to 10000 so that the CTE pre-scan is wide enough to fill the per-column `LIMIT 10` display cap on columns up to ~99.9% null. Docstring documents the base-scan-width / RAM trade-off so operators understand the cost on multi-million-row tables.
- [ ] **INGEST-N6-02**: A regression test constructs a synthetic table with a column that is ≥99% NULL (≥1 non-null in a 2000-row insert) and asserts that `get_sample_values` returns at least 1 sample value for that column. A paired dense-column control assertion ensures the existing `LIMIT 10` display cap behavior is unchanged by the bump.
- [ ] **INGEST-K6-01**: `CommitRequest` is split into `BaseCommitRequest` + three discriminated subclasses (`VectorCommitRequest`, `RasterCommitRequest`, `ServiceCommitRequest`) so field applicability rules live in the type system. The `POST /ingest/commit/{job_id}` handler dispatches server-side from `job.source_url` + `job.user_metadata.file_type` with zero wire format change.
- [ ] **INGEST-K6-02**: Direct router test coverage for `POST /ingest/commit/{job_id}` is established — prior to Phase 220 the endpoint had **zero** direct router tests (only indirect coverage via orphan-guard mocks). New tests assert 202 + `queue_ingest_job` invocation for each file type, plus a negative test confirming kitchen-sink bodies still commit.
- [ ] **RASTER-VRT-FIX-01**: Integration test `backend/tests/test_regenerate_vrt_integration.py` provides a behavioral anchor for `regenerate_vrt` (`backend/app/ingest/tasks.py:2093`). Generates 2 real 64x64 GeoTIFFs, creates all DB rows (source + VRT Records/Datasets/RasterAssets, `vrt_source_links`, `IngestJob`), wires a `LocalStorageProvider` at `tmp_path`, invokes `await regenerate_vrt.func(...)` directly, and asserts on 15 state mutations (storage write + 11 `RasterAsset` fields + `IngestJob.status/dataset_id` + `VrtGeneration` completion + `Record.spatial_extent`). Prerequisite for Phase 219's 3-helper refactor — any drift in behavior will fail the test.
- [x] **INGEST-K4-01**: `regenerate_vrt` (`backend/app/ingest/tasks.py`) is refactored into three private helpers — `_build_vrt_to_temp(ordered_assets, vrt_type, resolution_strategy, tmp_dir) -> Path`, `_validate_and_extract_vrt_metadata(vrt_path) -> dict`, and `async _update_vrt_dataset_geometry(session, vrt_id, metadata) -> Dataset | None`. Behavior is byte-identical: the Phase 223 integration test (`backend/tests/test_regenerate_vrt_integration.py::test_regenerate_vrt_happy_path_end_to_end`) passes without modification, and the 6 existing mocked tests in `test_vrt_source_management_174.py::TestRegenerateVrtTask` stay green. All ValueError messages and raise points preserved per CONTEXT.md D-04. `regenerate_vrt` body shortens from 231 lines to ~225 lines; the 3 helpers collectively replace 30 lines of inline code with 3 named call sites that map 1:1 to steps 4b-5, 6-8, and 13 of the documented 15-step pipeline.

### Backend Config Hardening

Requirements covering runtime validation at the persistent_config JSONB read boundary (post-impl-20260410-HANDOFF-REMAINING.md §Type-5).

- [ ] **CONFIG-T5-01**: `PersistentConfig[T]` runtime-validates JSONB-unwrapped values via `TypeAdapter[T]` at the DB read boundary. On `pydantic.ValidationError`: logs a structured warning including `key` + `errors` payload, returns `env_default`, does not write to cache, does not raise, does not audit. The same validation path applies to the batch loader (`get_all_registry_values`).
- [ ] **CONFIG-T5-02**: All 30 `PersistentConfig[X]` / `_LogLevelConfig` instantiations in `backend/app/persistent_config.py` pass a runtime `type_=X` argument matching their static `[X]` subscript. The `_LogLevelConfig` subclass passes `type_=str` via `super().__init__`.

## Future Requirements

Deferred to future milestone. Tracked but not in current roadmap.

### Enterprise Conversion

- **ENT-01**: Editions comparison page (Community vs Enterprise feature matrix)
- **ENT-02**: Enterprise contact form with email delivery (Resend or Formspree)
- **ENT-03**: Demo request CTA and workflow

### Content Expansion

- **CONT-01**: Competitor positioning page (vs GeoServer/GeoNode/CARTO)
- **CONT-02**: Documentation site at docs.getgeolens.com (Starlight/Astro docs)
- **CONT-03**: Case studies or testimonial section

### Technical

- **TECH-01**: Dark/light mode theme toggle matching GeoLens brand
- **TECH-02**: Privacy-first analytics (Plausible or Fathom) with CTA tracking
- **TECH-03**: VPAT accessibility conformance report for federal procurement

## Out of Scope

| Feature | Reason |
|---------|--------|
| Live interactive demo | Scope explosion — quickstart + screenshots covers the need at 5% of the cost |
| CMS integration | All copy is hardcoded; migrate to content collections when a non-developer needs to edit |
| Blog | No content pipeline yet; add when there are regular posts to publish |
| Pricing page | No paid tier pricing finalized; editions comparison deferred |
| i18n / multi-language | English-only for launch; localize based on adoption geography |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| SITE-01 | Phase 212 | Complete |
| SITE-02 | Phase 212 | Complete |
| SITE-03 | Phase 212 | Pending |
| SITE-04 | Phase 212 | Pending |
| SITE-05 | Phase 212 | Pending |
| A11Y-01 | Phase 212 | Complete |
| A11Y-03 | Phase 212 | Pending |
| SEO-01 | Phase 213 | Pending |
| SEO-02 | Phase 213 | Pending |
| SEO-03 | Phase 213 | Pending |
| SEO-04 | Phase 213 | Pending |
| ASSET-01 | Phase 214 | Pending |
| ASSET-02 | Phase 214 | Pending |
| ASSET-03 | Phase 214 | Pending |
| HOME-01 | Phase 215 | Pending |
| HOME-02 | Phase 215 | Pending |
| HOME-03 | Phase 215 | Pending |
| HOME-04 | Phase 215 | Pending |
| HOME-05 | Phase 215 | Pending |
| FEAT-01 | Phase 216 | Pending |
| FEAT-02 | Phase 216 | Pending |
| FEAT-03 | Phase 216 | Pending |
| QUICK-01 | Phase 216 | Pending |
| QUICK-02 | Phase 216 | Pending |
| QUICK-03 | Phase 216 | Pending |
| A11Y-02 | Phase 217 | Pending |
| A11Y-04 | Phase 217 | Pending |
| INGEST-N6-01 | Phase 221 | Pending |
| INGEST-N6-02 | Phase 221 | Pending |
| INGEST-K6-01 | Phase 220 | Pending |
| INGEST-K6-02 | Phase 220 | Pending |
| CONFIG-T5-01 | Phase 222 | Pending |
| CONFIG-T5-02 | Phase 222 | Pending |
| RASTER-VRT-FIX-01 | Phase 223 | Pending |
| INGEST-K4-01 | Phase 219 | Complete |

**Coverage:**
- v14.0 requirements: 27 total
- Mapped to phases: 27
- Unmapped: 0 ✓
- Backend Ingest Quality: 6 total (INGEST-N6-01, INGEST-N6-02 — Phase 221; INGEST-K6-01, INGEST-K6-02 — Phase 220; RASTER-VRT-FIX-01 — Phase 223; INGEST-K4-01 — Phase 219)
- Backend Config Hardening: 2 total (CONFIG-T5-01, CONFIG-T5-02 — Phase 222)

---
*Requirements defined: 2026-04-04*
*Last updated: 2026-04-04 — traceability populated after roadmap creation*

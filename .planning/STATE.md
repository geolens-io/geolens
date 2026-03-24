---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
stopped_at: Completed quick-260323-r43
last_updated: "2026-03-23T23:56:06.001Z"
last_activity: "2026-03-23 - Completed quick task 260323-lik: Thorough QA pass on map layer configuration"
progress:
  total_phases: 61
  completed_phases: 60
  total_plans: 118
  completed_plans: 118
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-20)

**Core value:** Users can find any dataset in the catalog in seconds -- search, see it on a map, understand what it is, and get it out in the format they need.
**Current focus:** Phase 205 — builder-test-i18n-fixes

## Current Position

Phase: 205
Plan: Not started

## Performance Metrics

**Velocity:**

- Total plans completed: 0
- Average duration: -
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**

- Last 5 plans: -
- Trend: -

*Updated after each plan completion*
| - | - | - | - |
| Phase 0200 P01 | 2min | 3 tasks | 2 files |
| Phase 0202 P01 | 5min | 2 tasks | 8 files |
| Phase 0202 P02 | 3min | 1 tasks | 5 files |
| Phase 0203 P01 | 4min | 2 tasks | 5 files |
| Phase 0203 P02 | 8min | 2 tasks | 5 files |
| Phase 204 P01 | 3min | 2 tasks | 4 files |
| Phase 204 P02 | 10min | 1 tasks | 2 files |
| Phase 205 P02 | 2min | 2 tasks | 2 files |
| Phase 205 P01 | 2min | 3 tasks | 3 files |

## Accumulated Context

### Decisions

- [v12.3 Audit]: This milestone targets tablet and desktop builder workflows; phone-specific optimization is explicitly out of scope
- [v12.3 Audit]: Basemap switching on the audited map preserved overlay layers without console or network failures
- [v12.3 Audit]: Sidebar collapse currently relies on width-zero hiding and leaves hidden focusable controls in the keyboard path
- [v12.3 Audit]: Add Data and Map Info dialogs currently lack dialog descriptions and emit Radix accessibility warnings
- [v12.3 Follow-up]: Header tray should separate primary authoring actions from secondary share/export/duplicate actions, with a labeled save affordance and explicit unsaved-state feedback
- [v12.3 Follow-up]: Layer style/filter/label actions should not depend on hover-only discovery for tablet workflows, and type cues should make vector/raster/VRT rows easier to scan
- [v12.3 Follow-up]: VRT layers on the audited map are returned as vector_geolens, so the layer list shows vector controls while the runtime treats them as raster via tile tokens
- [v12.3 Follow-up]: Compact-width AI chat should not remain a fixed secondary rail when it would consume too much map workspace
- [v12.3 Follow-up]: Builder classification logic should converge on one shared capability model across API, sidebar, and runtime
- [v12.3 Roadmap]: Sequence shell/layout first, then accessibility semantics, then workflow polish, then architecture extraction, then regression coverage
- [v12.2 Roadmap]: A11y and Collection Shell first (easy wins), then Responsive Headers and Preview Resilience (higher effort)
- [v12.2 Roadmap]: 4 phases matching 4 requirement categories — natural delivery boundaries for stabilization
- [v12.0]: Record type taxonomy: collection, vector_dataset, raster_dataset, vrt_dataset
- [v12.1]: All icon-only buttons use aria-label={t()} matching their title prop
- [Phase 195-01]: Gradient fade always rendered (CSS-only, no JS scroll detection)
- [Phase 195-02]: focus-visible:ring-ring for theme-aware table focus rings
- [Phase 195-02]: VRT badges use variant=outline with semantic color classes
- [Phase 196-01]: Hardcoded aria-label on dl since i18n key does not exist
- [Phase 196-01]: break-words applied globally to PageHeader h1 (safe for all pages)
- [Phase 197]: flex-col md:flex-row for mobile stacking on DatasetDetailHeader
- [Phase 197]: Replace flex-shrink-0 with flex-wrap on action containers to prevent overflow
- [Phase 198-01]: Tile error threshold: 3 consecutive or >50% failure rate with 4+ total
- [Phase 198-01]: Error overlay uses key prop remount for clean retry
- [Phase 198-01]: 10s timeout from mount triggers error state if map never loads
- [Phase 198]: Badge gated on heroState=loaded to avoid visual clutter during skeleton/error states
- [Phase 199]: Place no-tile useEffect after id-reset useEffect for correct effect ordering
- [Phase quick-260319-qu1]: Map container uses role=region with aria-label for screen reader landmark
- [Phase 260320-m42]: Check geom_4326 not geom for promotion tests -- typed columns auto-promote but generic do not
- [Phase 0200]: Suppress Sheet built-in close button since header has explicit close
- [Phase 0200]: Use onTransitionEnd for map resize instead of ResizeObserver for CSS-transition sidebar
- [Phase 0202]: Consolidated three layer expand states into single expandedLayerId + activeEditorTab
- [Phase 0202]: VRT layers use Layers icon to distinguish from single-raster Grid3x3
- [Phase 0202]: Tab UI defaults to Style tab on first expand for discoverability
- [Phase 0202]: Secondary actions (Share, Info, Export, Duplicate) grouped in MoreHorizontal dropdown; Save button uses variant toggle for unsaved state
- [Phase 0203]: Use { current: Set<string> } ref type in map-sync.ts instead of React.MutableRefObject to keep module React-free
- [Phase 0203]: Imperative MapLibre sync logic extracted to map-sync.ts as pure-function module separate from React component
- [Phase 0203]: Keep localName/localDescription in MapBuilderPage since they are tightly coupled to JSX input bindings and save logic
- [Phase 0203]: useBuilderSave accepts SaveState interface to group related state, avoiding long parameter lists
- [Phase 204]: Use customRenderHook for hooks with context deps, plain renderHook for stateless hooks
- [Phase 204]: createMockMap factory pattern for MapLibre unit tests with all sync-relevant methods
- [Phase 204]: Fixed React 19 inert prop: use boolean true instead of empty string to correctly set HTML inert attribute
- [Phase 205]: Non-fatal alembic migration: warn but do not exit on failure so container can start even if DB is not yet ready
- [Phase 205]: Task 3 (i18n): tooltips.moreActions already existed in all 4 locale files -- no changes needed
- [Phase quick-260322-hv0]: Non-spatial CSV detection via geometry_type=None from ogrinfo, gates clip/4326/quicklook steps
- [Phase quick-260322-hv0]: DatasetRelationship FK model references catalog.records.id for FK joins between datasets
- [Phase quick-260322-irw]: Used get_dataset + check_dataset_access pattern for visibility on FK read endpoints
- [Phase quick-260322-kec]: FK candidates filtered by _id suffix excluding PK names; read-only click uses effectiveGid merge pattern
- [Phase quick-260322-l97]: Use useTranslation ready flag instead of try/catch for i18n fallback in error boundaries
- [Phase quick-260322-mb0]: Multi-layer detection returns all_layers list only when >1 layer and no specific layer requested
- [Phase quick-260322-mb0]: OOXML magic byte validation includes .zip and .docx since puremagic detects OOXML as ZIP container
- [Phase quick-260322-ndc]: Post-import SQL (ST_MakePoint/ST_GeomFromText) for XLSX geometry construction over VRT wrapper
- [Phase quick-260322-qg3]: Keep all infra directories in monorepo -- coupling cost exceeds organizational benefit at single-developer scale
- [Phase quick-260322-t3j]: Amber badge styling (border-amber-500/50 text-amber-600 dark:text-amber-400) for experimental indicator, matching SettingsAITab pattern
- [Phase quick-260324]: Search cards split long source organization text from compact spec metadata, using clamped source copy plus spec pills for faster scanning
- [Phase quick-260324]: Search landing and browse states now share a framed shell language across hero, sticky search, filters, and saved searches
- [Phase quick-260323-dxj]: Use location.state.from for login redirect and sessionStorage for OAuth redirect persistence; reject absolute URLs to prevent open redirects
- [Phase quick-260323-ees]: Use pydantic model_serializer decorator for null exclusion in OGCLink rather than model_config exclude_none
- [Phase quick-260323-jqk]: update_map uses flush() so begin_nested() savepoints in AI service work correctly; callers own commit lifecycle
- [Phase quick-260323-lik]: Always set opacity explicitly on initial layer creation regardless of value to prevent stale state on basemap reload
- [Phase quick-260323-r43]: Enforce validate_public_visibility as pre-update gate in update_map_endpoint; parse dataset names from 400 error detail for frontend display
- [Phase quick-260324-jni]: nginx proxy_read_timeout 600s for /api/; httpx client timeout 660s (10% above nginx); seed script default concurrency=1; poll_job timeout 1200s; retry 5xx with exponential backoff + jitter

### Pending Todos

- **v1.7 completion deferred**: Phases 40-42 to be resumed later
- **User settings: password change** — add change-password form to /settings (USET-01)
- **User settings: email management** — add email field to /settings (USET-02)
- **Collections sort/ordering** — sort by name/date/dataset count on browse page (COLL-02)

### Blockers/Concerns

- Export latency p95=9s under load — flagged for future optimization (ogr2ogr conversion overhead)
- ~~Investigate whether expected no-data raster tile responses are surfacing as noisy MapLibre AJAX errors in some builder sessions~~ — **RESOLVED** in 260322-mb0: nginx proxy_intercept_errors converts Titiler 404→204, BuilderMap error listener suppresses expected tile errors

### Quick Tasks Completed

| # | Description | Date | Commit | Status | Directory |
|---|-------------|------|--------|--------|-----------|
| 260319-o89 | Fix missing TooltipProvider causing blank search page crash | 2026-03-19 | da6ec575 | Verified | [260319-o89-fix-missing-tooltipprovider-causing-blan](./quick/260319-o89-fix-missing-tooltipprovider-causing-blan/) |
| 260319-q8j | Fix Review issues button navigating to wrong tab | 2026-03-19 | a4641c42 | Verified | [260319-q8j-fix-review-issues-button-navigating-to-u](./quick/260319-q8j-fix-review-issues-button-navigating-to-u/) |
| 260319-qu1 | Review the detail data page map for completeness and correctness | 2026-03-19 | b8c5e322 | Verified | [260319-qu1-review-the-detail-data-page-map-for-comp](./quick/260319-qu1-review-the-detail-data-page-map-for-comp/) |
| 260319-r4t | Review test coverage and create a plan to improve e2e coverage, unit tests and code quality checks | 2026-03-19 | 0daff224 | Verified | [260319-r4t-review-test-coverage-and-create-a-plan-t](./quick/260319-r4t-review-test-coverage-and-create-a-plan-t/) |
| 260320-c41 | Fix VRT/raster map 10s loading delay (circular hero state machine) | 2026-03-20 | 9d48b81f | Verified | [260320-c41-review-vrt-map-loading-delay-with-playwr](./quick/260320-c41-review-vrt-map-loading-delay-with-playwr/) |
| 260320-e6i | Fix vector detail page map controls (zoom-to-extent always visible) | 2026-03-20 | c24e455b | Verified | [260320-e6i-fix-vector-detail-page-map-controls-and-](./quick/260320-e6i-fix-vector-detail-page-map-controls-and-/) |
| 260320-gsh | QA assessment of vector detail page map editing capabilities | 2026-03-20 | 63583b65 | Verified | [260320-gsh-qa-assessment-of-vector-detail-page-map-](./quick/260320-gsh-qa-assessment-of-vector-detail-page-map-/) |
| 260320-m42 | Fix multi-part geometry data loss, frontend guard, Playwright selectors | 2026-03-20 | 0120c80e | Verified | [260320-m42-review-the-findings-report-of-the-vector](./quick/260320-m42-review-the-findings-report-of-the-vector/) |
| 260322 | review the vector detail page map, specifically the editing capabilities. Identify any gaps, issues or concerns. Be 100% confident the maps visualization capabilities are correct, complete and following best engineering practices. | 2026-03-20 | f6796601 | Verified | [260322-review-the-vector-detail-page-map-specif](./quick/260322-review-the-vector-detail-page-map-specif/) |
| 260320-m42 | Fix multi-part geometry editing safety (ST_Multi promotion, editing guard, Playwright fix) | 2026-03-20 | 01f6a349 | Verified | [260320-m42-review-the-findings-report-of-the-vector](./quick/260320-m42-review-the-findings-report-of-the-vector/) |
| 260321-f13 | Create and implement a 404 page for the site | 2026-03-21 | c5c63c51 | Verified | [260321-f13-create-and-implement-a-404-page-for-the-](./quick/260321-f13-create-and-implement-a-404-page-for-the-/) |
| 260321-f9l | Implement 5 error boundaries with i18n fallback UIs | 2026-03-21 | 171700df | Verified | [260321-f9l-implement-all-5-error-boundaries-with-i1](./quick/260321-f9l-implement-all-5-error-boundaries-with-i1/) |
| 260321-hks | Add unsaved changes navigation guard to map builder | 2026-03-21 | ecfa4c34 | Verified | [260321-hks-warning-before-leaving-map-with-unsaved-](./quick/260321-hks-warning-before-leaving-map-with-unsaved-/) |
| 260321-prh | Evaluate AWS AMI Marketplace readiness | 2026-03-21 | dd3905b3 | Verified | [260321-prh-evaluate-aws-ami-marketplace-readiness-i](./quick/260321-prh-evaluate-aws-ami-marketplace-readiness-i/) |
| 260322-c9b | Fix 10 OGC API Records Part 1 conformance gaps | 2026-03-22 | a3d08fb4 | Verified | [260322-c9b-assess-and-fix-geolens-ogc-records-confo](./quick/260322-c9b-assess-and-fix-geolens-ogc-records-confo/) |
| 260322-gzi | Fix ArcGIS auth header, JSON error detection, dynamic objectIdField, UX help text | 2026-03-22 | e57e796c | Verified | [260322-gzi-review-arcgis-online-portal-authenticate](./quick/260322-gzi-review-arcgis-online-portal-authenticate/) |
| 260322-hv0 | Non-spatial CSV ingestion, table detail layout, FK relationship model and related records panel | 2026-03-22 | fcd49732 | Verified | [260322-hv0-review-and-implement-non-spatial-table-s](./quick/260322-hv0-review-and-implement-non-spatial-table-s/) |
| 260322-irw | Fix FK endpoint NameError, add visibility checks, i18n, error states, tests | 2026-03-22 | 4b95f4f9 | Verified | [260322-irw-polishing-what-s-shipped-review-all-the-](./quick/260322-irw-polishing-what-s-shipped-review-all-the-/) |
| 260322-kec | FK auto-detection, read-only panel activation, table guard fix | 2026-03-22 | 8ee8eaf6 | Verified | [260322-kec-address-all-follow-up-items-from-shipped](./quick/260322-kec-address-all-follow-up-items-from-shipped/) |
| 260322-l97 | AppErrorBoundary hooks fix, CSV upload test, RelatedRecordsPanel + NotFoundPage tests | 2026-03-22 | 7f60a789 | Verified | [260322-l97-test-coverage-and-error-handling-fixes-c](./quick/260322-l97-test-coverage-and-error-handling-fixes-c/) |
| 260322-ljk | Resolve outstanding audit gaps (260322 + 260319-qu1 verification) | 2026-03-22 | 1a46daaf | Verified | [260322-ljk-resolve-outstanding-audit-gaps-260322-ve](./quick/260322-ljk-resolve-outstanding-audit-gaps-260322-ve/) |
| 260322-lv3 | E2e seed script, m42/f9l verification, non-spatial CSV pipeline test | 2026-03-22 | 0c3970f9 | Verified | [260322-lv3-test-quality-follow-ups-e2e-seed-data-sc](./quick/260322-lv3-test-quality-follow-ups-e2e-seed-data-sc/) |
| 260322-mb0 | Excel (.xlsx/.xls) non-spatial ingestion, multi-sheet support, format detection | 2026-03-22 | c5c18bc7 | Verified | [260322-mb0-excel-json-non-spatial-ingestion-support](./quick/260322-mb0-excel-json-non-spatial-ingestion-support/) |
| 260322-mb0 | Fix noisy MapLibre AJAX errors: nginx proxy_intercept_errors + BuilderMap error handler | 2026-03-22 | 47886433 | Verified | [260322-mb0-investigate-and-fix-noisy-maplibre-ajax-](./quick/260322-mb0-investigate-and-fix-noisy-maplibre-ajax-/) |
| 260322-ndc | Non-spatial table support, CSV/XLSX with geometry columns | 2026-03-22 | 1931de83 | Gaps | [260322-ndc-for-non-spatial-table-support-support-im](./quick/260322-ndc-for-non-spatial-table-support-support-im/) |
| 260322-qg3 | Evaluate whether helm/, packer/, ami/ directories should move to separate repos | 2026-03-22 | 8534fa38 | Verified | [260322-qg3-evaluate-whether-helm-packer-ami-directo](./quick/260322-qg3-evaluate-whether-helm-packer-ami-directo/) |
| 260322-t3j | AI functionality gaps: set_opacity tool, metadata error toasts, experimental badges | 2026-03-23 | c0070076 | Verified | [260322-t3j-review-ai-functionality-admin-toggle-met](./quick/260322-t3j-review-ai-functionality-admin-toggle-met/) |
| 260323-7cr | Fix ingest pipeline geometry column naming bug and improve seed script robustness | 2026-03-23 | 061e72c4 | Verified | [260323-7cr-review-and-fix-seed-ago-data-py-fix-geom](./quick/260323-7cr-review-and-fix-seed-ago-data-py-fix-geom/) |
| 260324 | inspect the search page with Playwright and modernize the search UI/UX, with special attention to result cards | 2026-03-23 | d5846915 | Verified | [260324-inspect-the-search-page-with-playwright-](./quick/260324-inspect-the-search-page-with-playwright-/) |
| 260323-dxj | redirect to deep link after login | 2026-03-23 | e05f54e0 | Verified | [260323-dxj-redirect-to-deep-link-after-login](./quick/260323-dxj-redirect-to-deep-link-after-login/) |
| 260323-ees | Fix OGC API Features endpoints for QGIS compatibility | 2026-03-23 | 9fb0b26c | Verified | [260323-ees-verify-ogc-api-features-endpoints-workin](./quick/260323-ees-verify-ogc-api-features-endpoints-workin/) |
| 260323-jqk | Fix closed transaction error in AI map generate | 2026-03-23 | 8dd86717 | Verified | [260323-jqk-fix-closed-transaction-error-in-ai-map-c](./quick/260323-jqk-fix-closed-transaction-error-in-ai-map-c/) |
| 260323-lik | Thorough QA pass on map layer configuration — correctness, best practices, KISS | 2026-03-23 | c4f7f3db | Verified | [260323-lik-thorough-qa-pass-on-map-layer-configurat](./quick/260323-lik-thorough-qa-pass-on-map-layer-configurat/) |
| 260323-r43 | Audit sharing/access/embed: hard-block non-public datasets, findings report | 2026-03-23 | 757280ce | Verified | [260323-r43-audit-sharing-access-embed-functionality](./quick/260323-r43-audit-sharing-access-embed-functionality/) |
| 260324-cn5 | Map chat @mention layers, slash commands, smart suggestions, message enrichment | 2026-03-24 | 06c6ed11 | Verified | [260324-cn5-map-chat-mention-layers-slash-commands-a](./quick/260324-cn5-map-chat-mention-layers-slash-commands-a/) |
| 260324-jni | Fix seed-ago-data.py 502 errors: nginx proxy timeouts, retry with backoff, configurable timeout | 2026-03-24 | 9995d4c0 | Verified | [260324-jni-investigate-and-fix-seed-ago-data-py-imp](./quick/260324-jni-investigate-and-fix-seed-ago-data-py-imp/) |

## Session Continuity

Last activity: 2026-03-24 - Completed quick task 260324-jni: Fix seed-ago-data.py 502 errors and poll timeouts
Last session: 2026-03-24T18:24:01.000Z
Stopped at: Completed quick-260324-jni
Resume file: None

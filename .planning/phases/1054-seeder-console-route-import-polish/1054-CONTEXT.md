# Phase 1054: Seeder + Console + Route + Import Polish - Context

**Gathered:** 2026-05-19
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss=true)

<domain>
## Phase Boundary

Running GeoLens as a new user produces no unexplained console noise, no silent route failures, and no UI affordances that intercept clicks or emit React warnings.

**13 requirements:** SEED-02, SEED-03, SEED-04, UX-01, CONSOLE-01, ROUTE-01, ROUTE-02, ROUTE-03, ROUTE-04, IMPORT-02, IMPORT-03, IMPORT-05, EW-05.

**Source-of-truth:** `.planning/M001-7n8vpc-dry-run-audit.md` — read sections `## SEED-02..04`, `## UX-01`, `## CONSOLE-01`, `## ROUTE-01..04`, `## IMPORT-02..05`, `## EW-05` for full Where / Documented / Actual / Recommendation per finding.

**Public tag:** Still v1.3.0 (Phase 1054 adds polish, no new features that warrant a tag bump beyond what Phase 1055 IMPORT-04 already triggers).

</domain>

<decisions>
## Implementation Decisions

### Surface split (3 surfaces, ~9-10 plans)

**Backend Python (3 reqs, 1 file):**
- **SEED-02/03/04** — all touch `scripts/seed-ago-data.py`. Likely bundleable into 1-2 plans:
  - SEED-02: configurable ogr2ogr timeout (env var `OGR2OGR_TIMEOUT_SECONDS` OR `--timeout` flag) + per-layer retry-once
  - SEED-03: summarize AGO data-quality noise (collect malformed-feature counts, print summary not verbatim lines)
  - SEED-04: strip `ogr2ogr` driver-list dump from error output — surface only the actionable error message

**Frontend hooks gating (1 req):**
- **CONSOLE-01** — Anonymous Search page (`/`) and `/login` fire 12× 401s. Audit shows the offenders:
  - `/api/auth/refresh/` ×2 — auth store refresh attempt on mount before token check
  - `/api/auth/me/` ×2 — me probe (likely `useUser` or similar)
  - `/api/auth/me/permissions/` ×3 — `usePermissions` hook
  - `/api/admin/ai-status/` ×3 — admin probe leaking to non-admin/anonymous

  Pattern: gate each hook on `!!token` (v1010.2 SF-06 pattern). The `useAIStatus` + `useEmbeddingStats` are already gated post-v1010.2 — find the remaining sibling hooks (`usePermissions`, `useUser`, refresh probe, ai-status's admin-page consumers). Likely 4-6 file touches.

**Frontend routes (4 reqs):**
- **ROUTE-01** `/admin/saml` — render "Enterprise Feature" placeholder (option a from audit) instead of silent redirect to `/admin/overview`. Need: a new `EnterpriseFeatureNotice` component OR an inline rewrite of `AdminSamlPage` to return that placeholder when SAML extension is not loaded.
- **ROUTE-02** `NotFoundPage` `<title>` — single-line `document.title` update or `<Helmet>` (whatever the project uses).
- **ROUTE-03** `/register` redirect → visible banner. Need: detect authenticated user inside `RegisterPage` and render an info banner with redirect, instead of silent redirect.
- **ROUTE-04** `/m/{invalid-token}` — replace API-404 console leak with clean "Map not found" view. Likely needs an error-boundary or explicit 404-state handling in the share-token route component.

**Frontend forms (3 reqs):**
- **IMPORT-02** decorative span intercepting clicks — `pointer-events: none` on the offending decorative span (Tailwind: `pointer-events-none`). One-line CSS-class change.
- **IMPORT-03** React `setState during render` warning — root-cause the offending callsite (likely a parent component setting state synchronously in response to a child render-time event). Route through `useEffect` or `queueMicrotask` per React 19 rules.
- **IMPORT-05** Register Table "no tables found" → success framing ("All tables are registered"). Conditional empty-state copy based on backend response (is there a separate "unregistered tables" count?).

**Frontend wizard (1 req):**
- **EW-05** STAC import wizard size estimate before commit. Need: backend `HEAD` requests to STAC items (or capture `size` from STAC item assets if available), aggregate, show in a "You're about to download N items totaling X MB" confirmation step. Likely the largest of the polish plans.

**UX discovery (1 req):**
- **UX-01** API Keys workflow discoverability. Choice space:
  - (a) Add a sidebar nav item or settings-top-bar link to surface API Keys (1-2 clicks from anywhere instead of 3-clicks-from-Settings).
  - (b) Sign-post from seeder docs (Phase 1053 already did this via DOC-02 in cross-repo docs).
  - **CONTEXT recommendation: (b) is already satisfied by Phase 1053 DOC-02.** UX-01 may be auto-resolved. Planner should verify by reading the Phase 1053 DOC-02 SUMMARY and decide whether UX-01 needs additional work or is closeable as "satisfied by Phase 1053".

### EW-05 STAC size estimate — decision space

Two implementation paths:
- **(a) Eager pre-flight HEAD requests** — for each selected STAC item, fire HEAD against its assets URLs, sum content-length, display total. Accurate but slow (N HTTP roundtrips). May be blocked by CORS on third-party STAC sources.
- **(b) Best-effort estimate from STAC manifest** — parse `assets.{key}.file:size` or `assets.{key}.alternate.size` from the STAC item JSON. Display the sum where available, with a "(estimate based on STAC manifest)" qualifier. Falls back to "Total: N items (size unavailable)" when manifest doesn't include size.

Recommended: **(b)** — cheaper, no CORS issues, honest about source. STAC 1.0+ does include `file:size` for many catalogs (USGS Landsat, NASA CMR).

### UI-SPEC decision

**Skip UI-SPEC for this phase.** Most work is polish/bug fixes, not new components. ROUTE-01 adds an "Enterprise Feature" notice which is a tiny placeholder component, and EW-05 adds a wizard step that is a confirmation modal/screen — both can be built without a full UI-SPEC contract. Planner should produce the actual visual treatment inline in each plan.

If during execution the planner decides UI-SPEC is needed for EW-05 (size-estimate screen is a non-trivial new UI), they can request it as a sub-plan. Default: no UI-SPEC.

### Verification approach

- Backend SEED changes: pytest if existing tests cover seeder paths; manual `scripts/seed-ago-data.py --help` to verify new flags + small AGO layer run if reasonable
- Frontend CONSOLE-01: live Playwright MCP test — open `/login` and `/` as anonymous, assert zero 401-error console entries
- Frontend ROUTE: live Playwright MCP for each route — navigate, assert correct UI
- Frontend IMPORT-02/03/05: live MCP — navigate to /import, click Choose File (assert no interception), commit file (assert no setState warning), open Register Table (assert correct empty-state)
- Frontend EW-05: live MCP — start STAC import, assert size-estimate appears before commit
- Vitest for any new components added (ROUTE-01 notice, IMPORT-05 message variant)

### Cross-cutting smoke

After all plans land, run smoke gate (`typecheck`, `vitest`, `e2e:smoke:builder`, i18n parity). Don't aggregate this into Phase 1054 — let Phase 1056 CTRL-01 handle the milestone-level smoke gate.

</decisions>

<code_context>
## Existing Code Insights

**Files most likely to touch (frontend):**

- `frontend/src/components/auth/*` and `frontend/src/store/auth.ts` — CONSOLE-01 hook gating
- `frontend/src/hooks/use-user.ts`, `use-permissions.ts`, `use-saved-searches.ts`, `use-ai-status.ts`, `use-embedding-stats.ts` — auth-gated hooks; v1010.2 SF-06 closed `useSavedSearches` + `useAIStatus` + `useEmbeddingStats`, need to find remaining offenders
- `frontend/src/pages/admin/AdminSamlPage.tsx` — ROUTE-01 Enterprise Feature notice
- `frontend/src/pages/NotFoundPage.tsx` — ROUTE-02 title
- `frontend/src/pages/RegisterPage.tsx` — ROUTE-03 banner
- `frontend/src/pages/SharedMapPage.tsx` or `embed/EmbedMapPage.tsx` — ROUTE-04 invalid-token handling
- `frontend/src/components/import/UploadFileForm.tsx` (or similar) — IMPORT-02 (decorative span pointer-events), IMPORT-03 (setState warning)
- `frontend/src/components/import/RegisterTableTab.tsx` (or similar) — IMPORT-05 empty state
- `frontend/src/components/import/STACImportWizard.tsx` (or similar) — EW-05 size estimate

**Files most likely to touch (backend):**

- `scripts/seed-ago-data.py` — all SEED-02/03/04 changes; uses `ogr2ogr` via `subprocess`

**Reference patterns:**

- `frontend/src/hooks/use-ai-status.ts` (v1010.2 commit `aca42c99` + `d6b0b9c6`) — gating pattern: `{ enabled: !!token && isAdmin() }` — same shape applies to CONSOLE-01 fixes
- `scripts/seed-natural-earth.py:272,317` — was the SEED-01 fix; `seed-ago-data.py` is the analog file (similar `--username/--password` pattern is candidate for DOC-02 path but that's docs-only per Phase 1053)
- Cross-repo Phase 1053 `~/Code/getgeolens.com` commit `30e9361` — establishes the "Create your first API key" subsection. UX-01 verification should compare against that.

</code_context>

<specifics>
## Specific Ideas

Per requirement, source-of-truth in audit:

- **SEED-02** → `## SEED-02` (audit) — 120s default + retry strategy
- **SEED-03** → `## SEED-03` (audit) — summarize approach
- **SEED-04** → `## SEED-04` (audit) — strip driver list
- **UX-01** → `## UX-01` (audit) — 3-click path documented; check Phase 1053 DOC-02 SUMMARY to see if cross-repo doc signposting suffices
- **CONSOLE-01** → `## CONSOLE-01` (audit) — exact 12 errors listed with paths + counts
- **ROUTE-01** → `## ROUTE-01` (audit) — option (a) Enterprise Feature placeholder recommended
- **ROUTE-02..04** → `## ROUTE-02`, `## ROUTE-03`, `## ROUTE-04` (audit)
- **IMPORT-02** → `## IMPORT-02` (audit) — span selector identified
- **IMPORT-03** → `## IMPORT-03` (audit) — setState during render verbatim
- **IMPORT-05** → `## IMPORT-05` (audit) — empty-state message verbatim
- **EW-05** → `## EW-05` (audit) — stage-and-confirm flow

</specifics>

<deferred>
## Deferred Ideas

- **UX-01 nav surface addition** — if Phase 1053 cross-repo doc signposting is judged sufficient, no in-app navigation change is needed. Planner decides.
- **Backend `seed-ago-data.py` rewrite to use GeoLens SDK** — out of scope per REQUIREMENTS.md "Out of Scope" table.
- **EW-05 eager HEAD pre-flight** — deferred in favor of STAC-manifest size parsing (locked decision (b)).
- **Live MCP verification at phase level** — deferred to Phase 1056 close gate. Phase 1054 verification can use vitest + headless e2e:smoke. Live MCP fires at CTRL-01.

</deferred>

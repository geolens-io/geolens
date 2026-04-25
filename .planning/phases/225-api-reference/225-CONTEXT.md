# Phase 225: API Reference - Context

**Gathered:** 2026-04-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Ship auto-generated API reference pages under `/guides/api/` (rendered from a committed `openapi.json` snapshot via `starlight-openapi@0.25.0`), plus hand-authored Authentication and OGC sections, plus a snapshot-freshness README — so developers can use the docs as their primary API integration reference without leaving the site. Scope is exclusively the API Reference vertical (REQUIREMENTS API-01..05 + CI-01); Quickstart/Install belong to Phase 226 and User/Admin guides to Phase 227.

</domain>

<carryover_from_prior_phases>
## Locked from Phases 223 & 224 (do not re-decide)

### From Phase 223 (Bootstrap)
- **D-11 / D-13 (224):** `/guides/api/index.mdx` placeholder already exists from Phase 224's sidebar autogenerate setup. Phase 225 replaces it with a curated landing page.
- **D-04 (223):** `docs/wrangler.toml` + CF Pages `rootDirectory: docs` already wired. No infra changes here.
- **D-07 / D-08 (223):** Site-wide `noindex` + `robots.txt Disallow:/` still in effect through Phase 228. New API content does NOT alter this.
- **D-14 / D-15 / D-16 (223):** `_redirects` covers `/install`, `/admin`, `/api` → `/guides/...`. The legacy `/api` → `/guides/api` 301 is already in place. Do NOT touch.
- **D-18 (223):** `@astrojs/sitemap` autogenerates sitemap. New `/guides/api/*` pages auto-included.

### From Phase 224 (Brand, Shell & Search)
- **D-13 (224):** Sidebar group label is **"API Reference"** with `autogenerate: { directory: 'guides/api' }`. New pages added under `docs/src/content/docs/guides/api/` will appear automatically. Do NOT change the sidebar config approach in Phase 225.
- **D-17 (224):** Custom `<Breadcrumbs.astro>` is the `PageTitle` override. New API pages get breadcrumbs for free.
- **D-18 (224):** Edit-this-page baseUrl is `https://github.com/geolens-io/getgeolens.com/edit/main/docs/`. All new MDX/auto-rendered pages get edit links automatically.
- **D-19 (224):** `lastUpdated: true` works from git history. New API pages get last-updated stamps automatically.
- **D-27 / D-28 (224):** Pagefind is enabled by default; the Expressive Code plugin (`pluginPagefindWeight`) injects `data-pagefind-weight="0.1"` on every `<pre>` block. Phase 225 layers an additional exclusion on top for auto-generated reference pages — the global weight=0.1 stays.
- **D-29 / D-30 (224):** Cmd+K and `/` open the search dialog. No keyboard work needed in 225.
- **D-31 / D-33 (224):** `llms.txt` already lists the four sidebar groups including API Reference. The current entry is a stub URL. Phase 225 may extend it (one new line for `/guides/api/auth` and one for `/guides/api/ogc`); Phase 228 finalizes.
- **D-34 (224) — CI step order:** `check-token-sync.sh` → `astro check` → `npm run build` → `verify-build.sh` → deploy. Phase 225 adds the `starlight-links-validator` step (CI-01) and a snapshot presence assertion in `verify-build.sh`.

### From REQUIREMENTS.md
- **API-01 literal:** `docs/src/content/openapi/geolens.json` is the snapshot path. `scripts/fetch-openapi.ts` is the documented refresh tool. Manual run, NOT CI-fetched at build time.
- **API-02 literal:** `starlight-openapi@0.25.0` is the locked plugin. Scalar / Redoc / Mintlify rejected.
- **OASDIFF-01 / TRY-IT-01:** Drift CI and interactive console explicitly deferred. Do NOT introduce in Phase 225.
- **Versioning:** Single "latest" version only. URL prefix `/guides/` chosen for future versioning retrofit.

</carryover_from_prior_phases>

<decisions>
## Implementation Decisions

### Snapshot Fetch Script (API-01, API-05)
- **D-01:** Ship `docs/scripts/fetch-openapi.ts` — TypeScript script run inside the docs subtree. Reads `process.env.GEOLENS_API_URL` with default `http://localhost:8000/api/openapi.json`. HTTP-fetches the spec from a running geolens API instance, validates the JSON parses and contains `openapi`, `info.version`, and at least one path, then writes pretty-printed (2-space indent) output to `docs/src/content/openapi/geolens.json`. **Reasoning:** matches REQUIREMENTS API-01 verbatim ("from a running geolens instance via a documented `scripts/fetch-openapi.ts` script"); zero geolens-repo coupling; works against local dev, staging, or any reachable instance.
- **D-02:** Add an npm script `fetch-openapi` in `docs/package.json` that runs the TS file via `tsx` (already used by other docs scripts? — researcher confirms; otherwise `node --import tsx docs/scripts/fetch-openapi.ts`). Document the env-var override path in the `docs/src/content/openapi/README.md` (API-05).
- **D-03:** Operator workflow documented in README: (1) `cd backend && docker compose up api`, (2) wait for healthy, (3) `cd ../getgeolens.com/docs && npm run fetch-openapi`, (4) git diff to review the spec change, (5) commit. NO CI automation of this in Phase 225.
- **D-04:** The committed snapshot is the SOURCE OF TRUTH for the docs build. CI must NOT re-fetch at build time — `verify-build.sh` asserts `dist/.../openapi/geolens.json` is present and non-empty (or the rendered API pages exist), but does not call `fetch-openapi.ts`.
- **D-05:** Snapshot file contains stable, sorted-or-pretty-printed JSON (deterministic) so git diffs are reviewable. The fetch script must produce identical output for identical input — no timestamps, no random ordering.

### URL Layout (API-02, API-03, API-04)
- **D-06:** Flat siblings under `/guides/api/`. Hand-authored pages: `/guides/api/` (curated landing), `/guides/api/auth`, `/guides/api/ogc`. Auto-generated pages: `/guides/api/{tag}/` per FastAPI tag. Reasoning: matches REQUIREMENTS literal `/guides/api/`; minimum URL depth; integrators share short URLs.
- **D-07 — Tag-name slug collision:** The FastAPI app has a tag named `Auth` (for login/registration/api-keys/profile endpoints). Its auto-generated slug `/guides/api/auth/` would collide with the hand-authored `/guides/api/auth` page. **Resolution:** prefer the hand-authored page at the canonical URL; rename the auto-generated tag slug to `/guides/api/auth-endpoints/` (or `/guides/api/reference-auth/`). The exact mechanism depends on `starlight-openapi@0.25.0` capabilities — researcher MUST confirm whether the plugin supports per-tag slug overrides; if not, fall back to renaming the FastAPI tag in `backend/app/api/main.py` (`"Auth"` → `"User Authentication"`) and re-snapshotting. **Researcher deliverable:** report which mechanism the plugin supports; planner picks the cleaner option.
- **D-08:** No `/guides/api/reference/` nesting. The auto-generated tag pages live as direct siblings of `/guides/api/auth` and `/guides/api/ogc`. Sidebar order (top-to-bottom): Authentication, OGC Endpoints, then auto-generated tag pages alphabetized.
- **D-09:** `/guides/api/index.mdx` is a curated landing page with: 1-paragraph orientation, three top-level cards/links (Authentication, OGC Endpoints, Endpoints by Tag), and a "Spec snapshot" callout showing the `info.version` from the committed JSON. Replaces the Phase 224 placeholder.

### Hand-Authored Authentication Page (API-03)
- **D-10:** `/guides/api/auth.mdx` covers exactly three auth methods, in this order: **JWT Bearer**, **API key** (header AND `?api_key=` query param — both supported per CLAUDE.md memory), **OAuth/OIDC** flows. Each section has at least one working `curl` example.
- **D-11:** JWT section — short flow narrative (POST `/api/auth/login` → access_token + refresh_token), curl example with `-H "Authorization: Bearer <jwt>"`, refresh-token rotation note, security note (token TTL, where to store).
- **D-12:** API key section — both forms documented:
  - Header form: `curl -H "Authorization: Bearer <api_key>" https://...`
  - Query form: `curl 'https://.../api/collections/datasets?api_key=<key>'`
  - Note: header > query > JWT > anonymous resolution order (per `_resolve_api_key()`).
  - How to obtain a key: link to `/guides/admin/users` (forward reference; Phase 227 will fill that in — broken-link tolerance handled by D-21).
- **D-13:** OAuth section — explain that OAuth/OIDC is admin-configured (Google, Microsoft, generic OIDC providers) and end-users go through the standard authorization-code flow via the web UI. Include curl example showing how a token obtained via the UI is then used in API calls. Forward-reference `/guides/admin/oauth` for setup. **Out of scope:** documenting OIDC client-credentials/PKCE machine-flow — geolens does not currently support that, do not invent it.
- **D-14:** No flow diagrams in this phase. Examples-driven prose only. Sequence diagrams can be added in a later polish phase if reader feedback warrants.
- **D-15:** Each curl example uses the placeholder host `https://geolens.example.com/api/...` — explicit "replace with your instance" so readers don't think `getgeolens.com` is a live API.

### Hand-Authored OGC Endpoints Page (API-04)
- **D-16:** Single landing page at `/guides/api/ogc.mdx`. Sections: OGC API — Common, OGC API — Records, OGC API — Features, STAC 1.1, Tile endpoints. Matches REQUIREMENTS API-04 literal ("landing page summarizing").
- **D-17:** Each section follows the pattern: (1) what this standard provides, (2) the relevant geolens endpoint paths, (3) one curl example, (4) at least one client-tool example (QGIS or GDAL/ogr2ogr) — ideally both for Features and Records.
- **D-18:** Specific examples expected (researcher to verify exact endpoint paths against the snapshot):
  - **Common:** `GET /api/` landing, `GET /api/conformance`, `GET /api/openapi.json`. curl + brief link to the auto-rendered reference for full schemas.
  - **Records:** `GET /api/collections/datasets/items` with CQL2 query example; QGIS metadata catalog setup; GDAL `ogr2ogr` against the records collection.
  - **Features:** `GET /api/collections/{dataset_id}/items`; QGIS WFS-style "Add Vector Tile / OGC API Features" walkthrough; ogr2ogr export.
  - **STAC:** `GET /api/stac/`, `GET /api/stac/search`; pystac-client snippet.
  - **Tiles:** Vector MVT tile URL pattern (HMAC-signed access tokens — clarify these are for embedded maps, not generic API access); raster Titiler URL pattern; QGIS XYZ template URL example.
- **D-19:** **No live demo URLs that point at `demo.getgeolens.com`** — link-rot is a known constraint (REQUIREMENTS USER-07, also from this milestone's brief). Use the same placeholder host pattern as D-15.
- **D-20:** CQL2 in the Records section gets one example only (e.g., `?filter=keywords='hydrology'`); deeper CQL2 documentation belongs in a future phase if demand surfaces. Do NOT recreate full CQL2 spec content.

### Pagefind Search Exclusion (Success Criteria #4)
- **D-21:** Auto-generated `starlight-openapi` tag pages are excluded from the Pagefind index. Hand-authored `/guides/api/`, `/guides/api/auth`, `/guides/api/ogc` REMAIN indexed. Reasoning: success criterion #4 says "the API reference index page does not appear in Pagefind search results (code blocks excluded from index)" — interpreted as the auto-rendered reference subtree, while the integrator-facing prose (auth examples, OGC how-tos) stays searchable for high user value.
- **D-22 — Mechanism:** preferred path is configuring `starlight-openapi@0.25.0` to inject `data-pagefind-ignore` on its rendered layout. **Researcher MUST confirm** whether 0.25.0 supports this. Fallback options (in priority order):
  1. Override the components Starlight uses for openapi pages and wrap their root in `<div data-pagefind-ignore>`.
  2. Set page-level frontmatter `pagefind: false` on each generated page (if the plugin supports frontmatter passthrough).
  3. As a last resort, add a Pagefind config exclusion by path glob (`pagefind.options.exclude` or `pagefind.yml` `exclude_selectors`).
- **D-23:** The Phase 224 D-28 `data-pagefind-weight="0.1"` rule on `<pre>` blocks STAYS. Auto-generated pages get a hard exclusion (D-21) layered on top; hand-authored pages keep the soft weight reduction.
- **D-24:** Verification — add a `verify-build.sh` assertion: count Pagefind index entries matching `/guides/api/datasets` (or any tag slug) — must be 0. Count entries matching `/guides/api/auth` — must be ≥ 1. Confirms exclusion scope is correct, not over-broad.

### Snapshot Freshness README (API-05)
- **D-25:** Ship `docs/src/content/openapi/README.md` documenting:
  - When to refresh: before each geolens release (or after any change to `backend/app/api/main.py`'s tags, or after any router-signature change).
  - How to refresh: the operator workflow from D-03 (verbatim).
  - How to verify the snapshot is current: `git log -1 docs/src/content/openapi/geolens.json` vs `git log -1 backend/app/api/`.
  - Link to OASDIFF-01 deferral note in REQUIREMENTS.md (so future maintainers know automated drift detection is planned, not forgotten).
- **D-26:** README is checked into the repo (not `.gitignored`). Acts as the running maintenance contract until OASDIFF-01 lands.

### Links Validator (CI-01)
- **D-27:** Install and wire `starlight-links-validator` (or equivalent — researcher confirms 0.38.4-compatible package; `@starlight-plugin-links-validator` is one candidate, `astro-broken-link-checker` is another). Plugin runs at build time, fails the build on broken internal links.
- **D-28:** Wire as a Starlight plugin in `astro.config.mjs` (NOT a separate CI step) so any local `npm run build` catches breakage before CI. CI inherits the same gate via the existing `npm run build` step.
- **D-29 — Forward-reference tolerance:** The auth page links to `/guides/admin/users` and `/guides/admin/oauth`, which Phase 227 creates. Use one of:
  1. Configure the validator to tolerate paths matching `/guides/{user,admin,quickstart}/*` (allow-list of forthcoming routes) — preferred if supported.
  2. Add stub MDX pages at the destination paths in this phase with one-line "coming soon — Phase 227" content. Removes the validator gymnastic at the cost of a tiny extra file.
  3. Mark forward references as external links to absolute `https://docs.getgeolens.com/guides/admin/...` URLs (only validated as URL syntax, not reachability).
  Planner picks based on validator capability; researcher reports.

### Scope Bounds (in this phase)
- **D-30:** Phase 225 ships ONLY: fetch script + snapshot + plugin wiring + landing/auth/OGC MDX + README + links-validator + verify-build.sh additions + new llms.txt lines. No Quickstart prose, no User/Admin guides, no marketing-site changes, no GA4, no OG image generation, no robots-flip.
- **D-31:** No interactive "Try it out" console — TRY-IT-01 is deferred (REQUIREMENTS Future Requirements).
- **D-32:** No `oasdiff` CI job — OASDIFF-01 is deferred.
- **D-33:** No backend changes EXCEPT a possible `Auth` → `User Authentication` tag rename if D-07's plugin-mechanism path doesn't pan out. If the rename happens, also re-run `fetch-openapi` and re-commit the snapshot in the same PR.

### Out of Scope for Phase 225 (deferred)
- Versioned docs / per-release snapshots → VERSION-01 (deferred milestone)
- `oasdiff` drift CI → OASDIFF-01 (post-launch milestone)
- Interactive API console → TRY-IT-01 (post-launch milestone)
- Localized API reference → I18N-01 (deferred)
- Marketing /features page → Phase 228
- Per-page OG images → Phase 228 (SEO-02)
- Sitemap submission to GSC → Phase 228 (SEO-03)
- A11Y audit + Lighthouse CI → Phase 228
- Quickstart/Install content → Phase 226
- User guide / Admin guide content → Phase 227
- CF Pages deploy verification (DEPLOY-01..04) → still deferred from Phase 223

### Claude's Discretion
- Exact CSS for the API landing-page cards (must use existing OKLCH design tokens — no hardcoded colors).
- Exact runner for `fetch-openapi.ts` — `tsx`, `node --import tsx`, or `bun` if it's already on the docs path. Researcher confirms what the docs subtree currently uses.
- Exact `starlight-links-validator` package selection — confirm Starlight 0.38.4 / Astro 6.x compatibility before pinning.
- Exact slug-collision resolution for the `Auth` tag (D-07) — pick the cleaner of the two paths after the researcher reports.
- The wording of the "Spec snapshot" callout on the landing page (e.g., "Spec snapshot: v1.0.0, last refreshed YYYY-MM-DD" — derive both from the JSON's `info.version` and git mtime).
- Exact curl example shapes (single-line vs `\` continuation) — match whatever marketing-site codeblock conventions exist; consult Phase 224 outputs.
- Whether to generate a small JSON-Schema preview block on tag pages (probably yes if the plugin renders it natively, no extra work needed).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Specs
- `.planning/REQUIREMENTS.md` §API Reference (API-01..05), §CI & Quality Gates (CI-01), §Future Requirements (OASDIFF-01, TRY-IT-01), §Out of Scope (live openapi.json fetch rejected) — locked acceptance criteria
- `.planning/PROJECT.md` §Current Milestone (v15.0) — milestone context
- `.planning/ROADMAP.md` §Phase 225 — goal, depends-on, success criteria

### Phase 223 / 224 Outputs (this phase builds on)
- `.planning/phases/223-bootstrap-infrastructure-lock/223-CONTEXT.md` — D-04 (CF Pages), D-07/08 (noindex still on), D-11 (sidebar groups locked), D-14..16 (_redirects, including legacy `/api`)
- `.planning/phases/224-brand-shell-search/224-CONTEXT.md` — D-13/14 (sidebar config), D-17 (breadcrumbs), D-18/19 (editLink + lastUpdated), D-27/28 (Pagefind weight), D-31 (llms.txt stub), D-34 (CI step order)
- `.planning/phases/224-brand-shell-search/224-VERIFICATION.md` — confirm what shipped before extending

### Backend (snapshot source)
- `backend/app/api/main.py` lines 270-354 — `_OPENAPI_TAGS` (18 tags including the colliding `Auth`)
- `backend/app/api/main.py` lines 358-377 — FastAPI app config: `title="GeoLens API"`, `version="1.0.0"`, `root_path="/api"`, `openapi_url=` defaults to `/openapi.json` so full path is `/api/openapi.json`
- `backend/app/modules/auth/dependencies.py` (`_resolve_api_key`, line ~23) — header > query > JWT > anonymous resolution order, source for D-12

### Implementation Repo Reference Files (parity targets)
The docs site lives in the sibling repo `/Users/ishiland/Code/getgeolens.com`. This phase modifies these files:

**Modify in this phase:**
- `getgeolens.com/docs/astro.config.mjs` — register `starlight-openapi@0.25.0` plugin pointing at the snapshot; register `starlight-links-validator` plugin
- `getgeolens.com/docs/package.json` — add `starlight-openapi@0.25.0`, `starlight-links-validator` (TBD package name), and a `fetch-openapi` script entry
- `getgeolens.com/docs/scripts/verify-build.sh` — add snapshot-presence assertion + Pagefind-exclusion assertion (D-04, D-24)
- `getgeolens.com/docs/public/llms.txt` — add `/guides/api/auth` and `/guides/api/ogc` entries (Phase 224 D-31 baseline)
- `getgeolens.com/docs/src/content/docs/guides/api/index.mdx` — replace Phase 224 placeholder with curated landing page

**Create in this phase:**
- `getgeolens.com/docs/scripts/fetch-openapi.ts` — TS HTTP-fetch script (API-01)
- `getgeolens.com/docs/src/content/openapi/geolens.json` — committed snapshot
- `getgeolens.com/docs/src/content/openapi/README.md` — refresh-cadence doc (API-05)
- `getgeolens.com/docs/src/content/docs/guides/api/auth.mdx` — hand-authored authentication page (API-03)
- `getgeolens.com/docs/src/content/docs/guides/api/ogc.mdx` — hand-authored OGC landing page (API-04)
- *(optional, per D-29 path 2)* `getgeolens.com/docs/src/content/docs/guides/admin/users.mdx`, `oauth.mdx` — stub forward-reference targets

**Possibly modify in this phase (only if D-07's plugin-mechanism path fails):**
- `geolens/backend/app/api/main.py` — rename `Auth` tag to `User Authentication` to avoid slug collision with the hand-authored `/guides/api/auth` page

### External Documentation (research targets)
- starlight-openapi 0.25.0: https://starlight-openapi.vercel.app/ — config schema, slug overrides, search exclusion, layout customization
- starlight-links-validator (or equivalent): https://docs.astro.build/ — Astro 6.x / Starlight 0.38.4 compatibility, forward-reference allow-list capability
- Pagefind exclusion docs: https://pagefind.app/docs/indexing/#removing-individual-elements-from-the-index — `data-pagefind-ignore` semantics
- OGC API standards (for OGC page accuracy):
  - OGC API — Common: https://docs.ogc.org/is/19-072/19-072.html
  - OGC API — Records Part 1: https://docs.ogc.org/DRAFTS/20-004.html
  - OGC API — Features Part 1+3: https://docs.ogc.org/is/17-069r4/17-069r4.html
  - STAC 1.1: https://stacspec.org/en/about/stac-spec/

### Anti-Patterns / Out of Scope (do not introduce)
- Live `openapi.json` fetch at build time (REQUIREMENTS Out of Scope; D-04)
- Scalar / Redoc / Mintlify / Docusaurus (REQUIREMENTS Out of Scope; only `starlight-openapi@0.25.0`)
- Interactive "Try it out" console (TRY-IT-01 deferred)
- `oasdiff` drift detection in CI (OASDIFF-01 deferred)
- Deep-linking to `demo.getgeolens.com` (REQUIREMENTS USER-07; D-19)
- Per-tag versioned snapshots (single "latest" only; VERSION-01 deferred)
- Removing the global `data-pagefind-weight="0.1"` rule from Phase 224 (D-23)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`docs/scripts/verify-build.sh`** — already the load-bearing build-artifact gate (Phase 223 + 224). Extend with snapshot/Pagefind assertions; do NOT replace.
- **`docs/scripts/check-token-sync.sh`** — pattern for build-time bash assertion. New verify-build.sh assertions follow the same `grep | exit 1 with diff` shape.
- **Phase 224 `pluginPagefindWeight` (Expressive Code plugin)** — proven pattern for code-block search treatment. Auto-generated reference pages use a different mechanism (page-level exclusion vs per-block weight) but coexist cleanly.
- **`backend/app/api/main.py:_OPENAPI_TAGS`** — pre-existing tag taxonomy. The auto-generated reference inherits this structure verbatim. No tag-restructure work in this phase (except possibly D-07's `Auth` rename).
- **Marketing site product previews** (`getgeolens.com/src/components/`) — reuse possible if the API landing page wants illustrative cards/screenshots; researcher checks for an existing card primitive before adding a new one.

### Established Patterns
- **Cross-repo coupling is via filesystem only.** Both `geolens` and `getgeolens.com` are sibling repos. The fetch script crosses repos via HTTP (live API), not filesystem reads. The snapshot lives in the docs repo only.
- **Single source of truth for OpenAPI** = the FastAPI app at runtime. The snapshot is a frozen capture. Any drift is fixed by re-running `fetch-openapi`, not by hand-editing the JSON.
- **Forward-references inside docs** are unavoidable in v15.0 (Phase 225 references Phase 227 admin pages). Established pattern from Phase 224 D-13 (empty placeholder MDX) is the precedent for handling this.
- **Manual operator workflows** beat CI automation when the artifact is rarely changed (snapshot updates per release, not per commit). REQUIREMENTS API-01 explicitly chose manual.

### Integration Points
- `astro.config.mjs` integrations array — add starlight-openapi + starlight-links-validator entries alongside existing starlight + sitemap.
- Sidebar: existing `autogenerate: { directory: 'guides/api' }` picks up new MDX files automatically. Auto-generated tag pages are added to the sidebar by `starlight-openapi` itself (researcher confirms 0.25.0 sidebar-injection behavior).
- `verify-build.sh` runs after `npm run build` in `docs-ci.yml`. New assertions are bash greps against `dist/`.
- The `editLink.baseUrl` from Phase 224 D-18 covers all new MDX files for free; auto-generated pages may or may not honor it (researcher confirms — it's fine if they don't, since the source-of-truth is the FastAPI tags, not the MDX).

</code_context>

<specifics>
## Specific Ideas

- **Examples-driven prose, not flow diagrams** (D-14). Reader spends seconds, not minutes. curl-first.
- **Both API-key forms documented** (D-12) — header AND `?api_key=` query param — because CLAUDE.md memory specifically calls out the query param as a real, supported fallback that downstream tooling relies on.
- **OGC page is one comprehensive landing page** (D-16) — matches REQUIREMENTS API-04 literal; per-standard splits can come later if reader feedback warrants.
- **Spec snapshot freshness shown to readers** (D-09) — landing page renders `info.version` from the JSON so users know what version of the API the docs are pinned to.
- **No `demo.getgeolens.com` deep links** (D-19) — link-rot is real (REQUIREMENTS USER-07 + Phase 224 deferral pattern).

</specifics>

<deferred>
## Deferred Ideas

- **Interactive API console (TRY-IT-01)** — out of scope for v15.0; revisit when an auth model for the console is designed.
- **`oasdiff` drift CI (OASDIFF-01)** — wait until docs site is shipped and stabilized.
- **Versioned API references** — single "latest" only; URL prefix `/guides/api/` enables retrofit.
- **CQL2 deep-dive page** — single example in OGC page is enough; deeper coverage if reader demand surfaces.
- **OAuth client-credentials / PKCE machine flow** — geolens does not currently support this; do not invent docs ahead of code.
- **Sequence/PKCE flow diagrams in the auth page** — possible polish phase if reader feedback warrants.
- **Marketing-site cross-link to `/guides/api/`** — will happen as part of Phase 228's marketing /features page.

</deferred>

---

*Phase: 225-api-reference*
*Context gathered: 2026-04-25*

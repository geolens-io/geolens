# Phase 225: API Reference - Research

**Researched:** 2026-04-25
**Domain:** Astro Starlight 0.38.4 plugin integration (`starlight-openapi`, `starlight-links-validator`), Pagefind page-level exclusion, OpenAPI snapshot fetch, OGC API client examples
**Confidence:** HIGH

## Summary

Phase 225 ships the API Reference vertical of the docs site at `getgeolens.com/docs/`. The work is bounded to: (1) a manual `fetch-openapi` script that snapshots `/api/openapi.json` to `docs/src/content/openapi/geolens.json`; (2) wiring `starlight-openapi@0.25.0` to render that snapshot as static reference pages under `/guides/api/operations/`; (3) hand-authored `auth.mdx` and `ogc.mdx` siblings; (4) a snapshot-freshness README; (5) `starlight-links-validator@0.23.0` as a build-time gate; (6) two new `verify-build.sh` assertions.

Research surfaces three findings that materially change the planner's approach:

1. **The D-07 slug-collision concern is overstated.** `starlight-openapi@0.25.0` does NOT render tag pages directly under `{base}/{tag-slug}/`. Tag overviews live at `{base}/operations/tags/{slug(tag.name)}/` and per-operation pages at `{base}/operations/{operationId}/`. With `base: 'guides/api'`, the FastAPI `Auth` tag renders at `/guides/api/operations/tags/auth/` — **no collision** with the hand-authored `/guides/api/auth/` page. The schema-overview page lives at `/guides/api/` and DOES overlap with the hand-authored `index.mdx`, but Astro content-collection pages take precedence over `injectRoute` catch-alls, so the hand-authored landing page wins. Backend tag rename is unnecessary.

2. **Pagefind exclusion has a clean, supported mechanism.** Starlight 0.38.4 toggles indexing via `data-pagefind-body` on `<main>`, gated by `entry.data.pagefind !== false`. Setting `pagefind: false` on a page removes that attribute and the page is omitted from the index entirely. starlight-openapi 0.25.0 does NOT support frontmatter passthrough, but Starlight exposes `routeMiddleware` config which lets us mutate `entry.data.pagefind = false` for any URL prefix. This is the recommended path; component overrides and Pagefind config exclusion are not needed.

3. **The API key header is `X-Api-Key`, not `Authorization: Bearer <key>`.** CONTEXT.md D-12 documents the wrong header. Authoritative source: `backend/app/modules/auth/dependencies.py:23-29` — the resolver checks `X-Api-Key` header, then `?api_key=` query param. The auth.mdx page must show `-H "X-Api-Key: <key>"` for header form, NOT `-H "Authorization: Bearer <api_key>"`. Backend's own `_DESCRIPTION` block in `main.py:248-252` confirms this priority.

**Primary recommendation:** Use the curated `base: 'guides/api'` with `openAPISidebarGroups` injected after the existing autogenerate group, register a `routeMiddleware` that flips `entry.data.pagefind = false` for any URL starting with `/guides/api/operations/`, install `starlight-links-validator@0.23.0` with `exclude: ['/guides/admin/**/*', '/guides/user/**/*', '/guides/quickstart/**/*']`, and ship `fetch-openapi.mjs` (matches existing `verify-shell-layout.mjs` pattern — no `tsx` dep). If REQUIREMENTS API-01's `.ts` filename is load-bearing, add `tsx@4.21.0` as a devDep.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Snapshot Fetch Script (API-01, API-05)
- **D-01:** Ship `docs/scripts/fetch-openapi.ts` — TypeScript script run inside the docs subtree. Reads `process.env.GEOLENS_API_URL` with default `http://localhost:8000/api/openapi.json`. HTTP-fetches the spec from a running geolens API instance, validates the JSON parses and contains `openapi`, `info.version`, and at least one path, then writes pretty-printed (2-space indent) output to `docs/src/content/openapi/geolens.json`.
- **D-02:** Add an npm script `fetch-openapi` in `docs/package.json` that runs the TS file via `tsx` (or `node --import tsx docs/scripts/fetch-openapi.ts`). Document the env-var override path in the `docs/src/content/openapi/README.md` (API-05).
- **D-03:** Operator workflow documented in README: (1) `cd backend && docker compose up api`, (2) wait for healthy, (3) `cd ../getgeolens.com/docs && npm run fetch-openapi`, (4) git diff to review, (5) commit. NO CI automation.
- **D-04:** The committed snapshot is the SOURCE OF TRUTH for the docs build. CI must NOT re-fetch at build time — `verify-build.sh` asserts the snapshot is present and non-empty, but does not call `fetch-openapi`.
- **D-05:** Snapshot file contains stable, sorted-or-pretty-printed JSON (deterministic) so git diffs are reviewable. The fetch script must produce identical output for identical input — no timestamps, no random ordering.

#### URL Layout (API-02, API-03, API-04)
- **D-06:** Flat siblings under `/guides/api/`. Hand-authored: `/guides/api/`, `/guides/api/auth`, `/guides/api/ogc`. Auto-generated: `/guides/api/{tag}/` per FastAPI tag.
- **D-07 — Tag-name slug collision:** FastAPI `Auth` tag would collide with hand-authored `/guides/api/auth`. Resolution: prefer the hand-authored page; rename auto-generated tag slug. Researcher confirms the actual mechanism. Fallback: rename the FastAPI tag in `backend/app/api/main.py`.
- **D-08:** No `/guides/api/reference/` nesting. Auto-generated tag pages are direct siblings. Sidebar order: Authentication, OGC Endpoints, then auto-generated tag pages alphabetized.
- **D-09:** `/guides/api/index.mdx` is a curated landing page with: 1-paragraph orientation, three top-level cards (Authentication, OGC Endpoints, Endpoints by Tag), and a "Spec snapshot" callout showing `info.version` from the JSON.

#### Hand-Authored Authentication Page (API-03)
- **D-10:** `/guides/api/auth.mdx` covers three auth methods, in this order: **JWT Bearer**, **API key** (header AND `?api_key=` query param), **OAuth/OIDC** flows. Each has at least one working `curl` example.
- **D-11:** JWT section — short flow narrative, curl example, refresh-token rotation note, security note.
- **D-12:** API key section — both forms documented, header form + query form, resolution order note, link to `/guides/admin/users` (forward reference).
- **D-13:** OAuth section — explain admin-configured (Google, Microsoft, generic OIDC), authorization-code flow via web UI, curl example showing UI-obtained token used in API. **Out of scope:** OIDC client-credentials/PKCE machine-flow.
- **D-14:** No flow diagrams. Examples-driven prose only.
- **D-15:** Each curl example uses placeholder host `https://geolens.example.com/api/...`.

#### Hand-Authored OGC Endpoints Page (API-04)
- **D-16:** Single landing page at `/guides/api/ogc.mdx`. Sections: OGC API — Common, Records, Features, STAC 1.1, Tile endpoints.
- **D-17:** Each section: (1) what this standard provides, (2) relevant geolens endpoint paths, (3) one curl example, (4) at least one client-tool example (QGIS or GDAL/ogr2ogr).
- **D-18:** Specific examples expected (researcher to verify exact endpoint paths against the snapshot).
- **D-19:** **No live demo URLs that point at `demo.getgeolens.com`** — link-rot risk. Use placeholder pattern from D-15.
- **D-20:** CQL2 in the Records section gets one example only.

#### Pagefind Search Exclusion (Success Criteria #4)
- **D-21:** Auto-generated `starlight-openapi` tag pages excluded from Pagefind. Hand-authored `/guides/api/`, `/guides/api/auth`, `/guides/api/ogc` REMAIN indexed.
- **D-22 — Mechanism:** preferred is configuring `starlight-openapi@0.25.0` to inject `data-pagefind-ignore` on its rendered layout. Researcher confirms whether 0.25.0 supports this. Fallback options: component override, frontmatter `pagefind: false`, or Pagefind config exclusion by path glob.
- **D-23:** The Phase 224 D-28 `data-pagefind-weight="0.1"` rule on `<pre>` blocks STAYS.
- **D-24:** Verification — `verify-build.sh` assertion: count Pagefind index entries matching `/guides/api/datasets` must be 0; count entries matching `/guides/api/auth` must be ≥ 1.

#### Snapshot Freshness README (API-05)
- **D-25:** Ship `docs/src/content/openapi/README.md` documenting refresh cadence, refresh procedure, verification recipe, link to OASDIFF-01 deferral note.
- **D-26:** README is checked into the repo.

#### Links Validator (CI-01)
- **D-27:** Install and wire `starlight-links-validator` (or equivalent — researcher confirms 0.38.4-compatible package).
- **D-28:** Wire as a Starlight plugin in `astro.config.mjs` (NOT a separate CI step).
- **D-29 — Forward-reference tolerance:** allow paths matching `/guides/{user,admin,quickstart}/*`, OR add stub pages, OR use absolute external URLs.

#### Scope Bounds
- **D-30:** Phase 225 ships ONLY: fetch script + snapshot + plugin wiring + landing/auth/OGC MDX + README + links-validator + verify-build.sh additions + new llms.txt lines.
- **D-31:** No interactive "Try it out" console — TRY-IT-01 deferred.
- **D-32:** No `oasdiff` CI job — OASDIFF-01 deferred.
- **D-33:** No backend changes EXCEPT possible `Auth` → `User Authentication` tag rename (only if D-07 plugin path fails).

### Claude's Discretion
- Exact CSS for the API landing-page cards (must use existing OKLCH design tokens — no hardcoded colors).
- Exact runner for `fetch-openapi.ts` — `tsx`, `node --import tsx`, or `bun` if it's already on the docs path. Researcher confirms what the docs subtree currently uses.
- Exact `starlight-links-validator` package selection — confirm Starlight 0.38.4 / Astro 6.x compatibility before pinning.
- Exact slug-collision resolution for the `Auth` tag (D-07) — pick the cleaner of the two paths after the researcher reports.
- The wording of the "Spec snapshot" callout on the landing page.
- Exact curl example shapes (single-line vs `\` continuation) — match Phase 224 conventions.
- Whether to generate a small JSON-Schema preview block on tag pages.

### Deferred Ideas (OUT OF SCOPE)
- **Interactive API console (TRY-IT-01)** — out of scope for v15.0.
- **`oasdiff` drift CI (OASDIFF-01)** — wait until docs site is shipped.
- **Versioned API references** — single "latest" only.
- **CQL2 deep-dive page** — single example is enough.
- **OAuth client-credentials / PKCE machine flow** — not currently supported.
- **Sequence/PKCE flow diagrams** — possible future polish phase.
- **Marketing-site cross-link to `/guides/api/`** — Phase 228.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| API-01 | `openapi.json` snapshot committed to `docs/src/content/openapi/geolens.json` from a running geolens instance via a documented `scripts/fetch-openapi.ts` script (manual run, not CI-fetched at build time) | §Standard Stack: Node 20+ native `fetch`; §Code Examples: minimal-deps `fetch-openapi.mjs` reference impl. Filename `.ts` vs `.mjs` discussed in §Open Questions. |
| API-02 | `starlight-openapi@0.25.0` plugin renders the snapshot into static reference pages under `/guides/api/` | §Standard Stack: confirmed peer deps (Starlight ≥0.38.0, Astro ≥6.0.0). §Architecture Patterns: plugin registration via Starlight `plugins:` array, `base: 'guides/api'`, `openAPISidebarGroups` export pattern. |
| API-03 | Hand-authored API auth section: JWT, API key (`?api_key=` + `Authorization` header), OAuth flows with curl examples | §Backend reality: API key header is **`X-Api-Key`** (NOT `Authorization: Bearer`). §Code Examples: corrected curl shapes for all three auth methods. |
| API-04 | Hand-authored OGC endpoints landing page summarizing OGC API Common, Records, Features, STAC, and tile endpoints with QGIS / GDAL connection examples | §OGC Endpoint Inventory: verified exact paths from `backend/app/standards/ogc/router.py`, `app/standards/stac/router.py`, `app/processing/tiles/router.py`, `app/modules/catalog/search/router.py`. §Code Examples: ogr2ogr OAPIF + QGIS MetaSearch + pystac-client invocations. |
| API-05 | Snapshot freshness README in `docs/src/content/openapi/` | §Architecture Patterns: README content shape; refresh-cadence anchor for OASDIFF-01 successor. |
| CI-01 | `starlight-links-validator` runs in CI to catch broken internal links before merge | §Standard Stack: `starlight-links-validator@0.23.0` confirmed compatible. §Architecture Patterns: registered as Starlight plugin (NOT separate CI step) — `npm run build` becomes the gate. §Code Examples: `exclude` glob syntax for forward references. |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| OpenAPI snapshot fetch (`fetch-openapi.mjs`) | Build / Tooling | — | Operator-run, not CI; talks HTTP to backend. Pure data-shuttle, no UI. |
| OpenAPI rendering (tag pages, operation pages) | Build (Astro static prerender) | — | starlight-openapi runs at `astro build` — no runtime tier; output is plain HTML. |
| Hand-authored MDX (auth, ogc, index) | Build (Starlight content collection) | — | Authored prose; lives in `src/content/docs/guides/api/`; rendered statically. |
| Pagefind index control (auto-page exclusion) | Build (Starlight route middleware → Pagefind) | — | `routeMiddleware` mutates `entry.data.pagefind` before Starlight emits `data-pagefind-body`; Pagefind runs in `astro:build:done` and skips pages without that attribute. |
| Links validation | Build (`astro build` step via plugin) | — | Plugin fails the build; CI inherits the gate via existing `npm run build`. |
| Snapshot freshness gate | Build (`verify-build.sh` after build) | — | Bash assertion; runs after `npm run build`, before deploy. |
| llms.txt extension | Build (static asset in `public/`) | — | Hand-edited; phase 224 already wired. |
| Backend (FastAPI) | API/Backend (untouched in this phase) | — | Source-of-truth for `openapi.json`; ONLY modified IF the slug-collision fallback is needed (research below shows it isn't). |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `starlight-openapi` | `0.25.0` | Render OpenAPI snapshot as Starlight pages | Locked by REQUIREMENTS API-02 verbatim. Active maintenance (last release 2026-04-23 [VERIFIED: `npm view starlight-openapi version time`]). Peer deps: `@astrojs/starlight >=0.38.0`, `astro >=6.0.0` [VERIFIED: `npm view starlight-openapi@0.25.0 peerDependencies`]. Maintained by HiDeoo (the same author who maintains starlight-links-validator and many of the most-used Starlight plugins). |
| `starlight-links-validator` | `0.23.0` | Build-time internal-link validation | Latest stable as of 2026-04-09 [VERIFIED: `npm view starlight-links-validator version time`]. Peer deps: `@astrojs/starlight >=0.38.0`, `astro >=6.0.0` [VERIFIED: `npm view starlight-links-validator@0.23.0 peerDependencies`]. Same author as `starlight-openapi` — the two are explicitly designed to coexist in the Starlight `plugins` array. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Node 20+ built-in `fetch` | (runtime) | HTTP fetch in `fetch-openapi` script | Use this — no `node-fetch`, no `undici`. Available in Node 18+, stable in 20+ which is the docs `.nvmrc` pin [VERIFIED: `cat docs/.nvmrc → "20"`]. |
| `tsx` | `^4.21.0` (latest) | TypeScript runner for `.ts` scripts | ONLY needed if the planner keeps the literal `.ts` filename from REQUIREMENTS API-01. If the planner accepts `.mjs` (matches `verify-shell-layout.mjs` precedent), no extra dep. [VERIFIED: `npm view tsx version → 4.21.0`] |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `starlight-openapi` | Scalar, Redoc, Mintlify | REJECTED by REQUIREMENTS Out of Scope — Starlight-native plugin is the only fit. Do not consider. |
| `starlight-links-validator` | `astro-broken-link-checker`, `lychee-action` (CI-only) | starlight-links-validator runs as a Starlight plugin — fails `npm run build` locally too, no separate CI step needed (matches CONTEXT.md D-28). Generic Astro/CI tools require additional wiring. |
| Native `fetch` for snapshot script | `axios`, `node-fetch`, `undici` | Native `fetch` is built into Node 18+. Adding a fetch dep to a 5-line script is gratuitous coupling. |
| `tsx` (TypeScript runner) | `bun`, `node --experimental-strip-types`, plain `.mjs` | The repo has zero TS scripts (`verify-shell-layout.mjs` is the precedent). `bun` is not on the docs path. Type-stripping requires Node 22.7+ but `.nvmrc` pins Node 20. **Recommendation: use `.mjs` and have the planner negotiate the filename with the user — the `.ts` literal in REQUIREMENTS is aspirational.** |

**Installation:**
```bash
cd /Users/ishiland/Code/getgeolens.com/docs
npm install --save-dev starlight-openapi@0.25.0 starlight-links-validator@0.23.0
# Only if planner keeps .ts filename:
# npm install --save-dev tsx@^4.21.0
```

**Version verification (run during planning):**
```bash
npm view starlight-openapi version       # expect 0.25.0
npm view starlight-links-validator version  # expect 0.23.0
```

## Architecture Patterns

### System Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│ OPERATOR WORKFLOW (manual, per geolens release)                      │
└──────────────────────────────────────────────────────────────────────┘

  geolens repo                            getgeolens.com/docs repo
  ┌──────────────────┐                    ┌────────────────────────────┐
  │ FastAPI app      │  HTTP GET /api/   │ scripts/fetch-openapi.mjs   │
  │ /api/openapi.json│ ────openapi.json─►│   - fetch + parse           │
  │                  │                   │   - validate (openapi/info/  │
  │ (running locally │                   │     paths exist)             │
  │  via docker      │                   │   - JSON.stringify(2-sp)     │
  │  compose up api) │                   └─────────────┬──────────────┘
  └──────────────────┘                                  │
                                                        ▼
                                           src/content/openapi/geolens.json
                                                        │
                                              git commit + push
                                                        │
                                                        ▼
┌──────────────────────────────────────────────────────────────────────┐
│ BUILD PIPELINE (every CI run, every npm run build)                   │
└──────────────────────────────────────────────────────────────────────┘
                                                        │
                                                        ▼
  src/content/docs/guides/api/                   astro.config.mjs
  ┌────────────────────────────┐                 ┌──────────────────────┐
  │ index.mdx (curated)        │                 │ starlight({          │
  │ auth.mdx (hand-authored)   │ ──┐             │   plugins: [          │
  │ ogc.mdx  (hand-authored)   │   │             │     starlightOpenAPI([│
  └────────────────────────────┘   │             │       { base: 'guides/api',│
                                   │             │         schema: '...' }│
  src/content/openapi/             │             │     ]),               │
  ┌────────────────────────────┐   │             │     starlightLinksValidator(│
  │ geolens.json (snapshot)    │ ──┼────────────►│       { exclude: [...] }) │
  │ README.md (refresh doc)    │   │             │   ],                   │
  └────────────────────────────┘   │             │   routeMiddleware: [   │
                                   │             │     './src/middleware/ │
  src/middleware/                  │             │      pagefind-exclude.ts'│
  ┌────────────────────────────┐   │             │   ],                   │
  │ pagefind-exclude.ts        │ ──┘             │ })                    │
  │ (sets entry.data.pagefind  │                 └──────────────────────┘
  │  = false for any URL       │                          │
  │  starting /guides/api/     │                          ▼
  │  operations/)              │             ┌──────────────────────────┐
  └────────────────────────────┘             │  astro build              │
                                              │  → emits HTML to dist/    │
                                              │  → starlight-links-       │
                                              │    validator FAILS build  │
                                              │    on broken /guides/* link│
                                              │  → astro:build:done →     │
                                              │    Starlight runs Pagefind│
                                              │    indexing on dist/,     │
                                              │    skips pages where      │
                                              │    <main> lacks           │
                                              │    data-pagefind-body     │
                                              └──────────┬───────────────┘
                                                         ▼
                                              ┌──────────────────────────┐
                                              │  scripts/verify-build.sh │
                                              │  (existing, extended):   │
                                              │  - assert geolens.json   │
                                              │    present + non-empty   │
                                              │  - assert dist/guides/   │
                                              │    api/operations/*/     │
                                              │    index.html lacks      │
                                              │    data-pagefind-body    │
                                              │  - assert dist/guides/   │
                                              │    api/auth/index.html   │
                                              │    HAS data-pagefind-body│
                                              └──────────┬───────────────┘
                                                         ▼
                                              ┌──────────────────────────┐
                                              │ cloudflare/pages-action  │
                                              │ (existing) → deploy      │
                                              └──────────────────────────┘
```

### Recommended Project Structure

```
getgeolens.com/docs/                              # sibling repo
├── astro.config.mjs                              # MODIFY: register starlight-openapi + links-validator + routeMiddleware
├── package.json                                  # MODIFY: deps + fetch-openapi script
├── plugins/
│   └── ec-pagefind-weight.mjs                    # untouched (Phase 224)
├── public/
│   └── llms.txt                                  # MODIFY: add /guides/api/auth + /guides/api/ogc
├── scripts/
│   ├── check-token-sync.sh                       # untouched
│   ├── fetch-openapi.mjs                         # CREATE — recommended (.mjs matches existing precedent)
│   ├── verify-build.sh                           # MODIFY: add 4 new assertions
│   └── verify-shell-layout.mjs                   # untouched (existing precedent for .mjs scripts)
├── src/
│   ├── components/
│   │   ├── Breadcrumbs.astro                     # untouched
│   │   └── DocsHeader.astro                      # untouched
│   ├── content/
│   │   ├── docs/
│   │   │   └── guides/
│   │   │       ├── admin/                        # untouched (placeholder index.mdx)
│   │   │       ├── api/
│   │   │       │   ├── index.mdx                 # MODIFY: replace placeholder with curated landing
│   │   │       │   ├── auth.mdx                  # CREATE
│   │   │       │   └── ogc.mdx                   # CREATE
│   │   │       ├── quickstart/                   # untouched
│   │   │       └── user/                         # untouched
│   │   └── openapi/                              # NEW directory
│   │       ├── geolens.json                      # CREATE — committed snapshot
│   │       └── README.md                         # CREATE — refresh-cadence doc
│   └── middleware/                               # NEW directory
│       └── pagefind-exclude.ts                   # CREATE — route middleware for D-21/22
└── tsconfig.json                                 # untouched
```

### Pattern 1: Plugin Registration (Single Schema)

**What:** Register `starlight-openapi` as a Starlight plugin (not Astro integration). Inject its sidebar groups via the exported `openAPISidebarGroups` symbol.
**When to use:** Always — this is the only documented integration shape for `starlight-openapi@0.25.0`.

```javascript
// docs/astro.config.mjs (excerpt — Phase 225 additions)
// Source: https://starlight-openapi.vercel.app/getting-started/  [CITED]
// Source: https://starlight-links-validator.vercel.app/getting-started/  [CITED]
import starlightOpenAPI, { openAPISidebarGroups } from 'starlight-openapi';
import starlightLinksValidator from 'starlight-links-validator';

export default defineConfig({
  // ...existing config...
  integrations: [
    starlight({
      // ...existing config (Phase 224)...
      plugins: [
        starlightOpenAPI([
          {
            base: 'guides/api',
            schema: './src/content/openapi/geolens.json',
            sidebar: {
              collapsed: false,
              label: 'Endpoints by Tag',
              operations: { badges: true, sort: 'alphabetical' },
              tags: { sort: 'alphabetical' },
            },
          },
        ]),
        starlightLinksValidator({
          exclude: [
            '/guides/admin/**',     // Phase 227
            '/guides/user/**',      // Phase 227
            '/guides/quickstart/**', // Phase 226
          ],
        }),
      ],
      // SHELL-01 / D-13 (Phase 224) sidebar STAYS as autogenerate;
      // openAPISidebarGroups injects ADDITIONAL group(s).
      sidebar: [
        { label: 'Quickstart',  autogenerate: { directory: 'guides/quickstart' } },
        { label: 'User Guide',  autogenerate: { directory: 'guides/user' } },
        { label: 'Admin Guide', autogenerate: { directory: 'guides/admin' } },
        { label: 'API Reference', autogenerate: { directory: 'guides/api' } },
        ...openAPISidebarGroups,  // <- starlight-openapi adds its tag groups here
      ],
      // D-22 mechanism: routeMiddleware to set pagefind=false on auto-generated URLs
      routeMiddleware: ['./src/middleware/pagefind-exclude.ts'],
    }),
    // ...
  ],
});
```

### Pattern 2: Pagefind Exclusion via Route Middleware

**What:** Mutate `entry.data.pagefind = false` for any URL under `/guides/api/operations/`. Starlight emits `data-pagefind-body` on `<main>` only when this flag is `!== false`, and Pagefind only indexes pages with that attribute.
**When to use:** When you need to exclude a path prefix from Pagefind without touching the rendering plugin's source. This is the cleanest mechanism for plugin-generated pages where frontmatter passthrough is unavailable.

```typescript
// docs/src/middleware/pagefind-exclude.ts
// Source: Starlight Page.astro emits data-pagefind-body iff entry.data.pagefind !== false
//         (verified in withastro/starlight @ packages/starlight/components/Page.astro)  [VERIFIED]
// Source: https://starlight.astro.build/guides/route-data/  [CITED]
import { defineRouteMiddleware } from '@astrojs/starlight/route-data';

export const onRequest = defineRouteMiddleware((context) => {
  const { starlightRoute } = context.locals;
  // All starlight-openapi auto-generated pages live under /guides/api/operations/...
  // (schema overview: /guides/api/, tag overviews: /guides/api/operations/tags/{slug}/,
  // per-operation: /guides/api/operations/{operationId}/)
  // We exclude only the operation* tree — the schema-overview path is overridden by
  // the hand-authored /guides/api/index.mdx (content collection wins over injectRoute).
  if (context.url.pathname.startsWith('/guides/api/operations/')) {
    starlightRoute.entry.data.pagefind = false;
  }
});
```

### Pattern 3: Snapshot Fetch Script (`.mjs` recommended)

**What:** Operator-run script that HTTP-fetches `/api/openapi.json` and writes a deterministic, pretty-printed snapshot. Native Node 20+ `fetch`, no extra deps.

```javascript
#!/usr/bin/env node
// docs/scripts/fetch-openapi.mjs (recommended) OR fetch-openapi.ts (per REQUIREMENTS literal)
// Source: native fetch (Node 18+), JSON.stringify(value, null, 2) is deterministic
//         for stable input.  [VERIFIED]
import { writeFile, mkdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const URL = process.env.GEOLENS_API_URL ?? 'http://localhost:8000/api/openapi.json';
const OUT  = join(__dirname, '..', 'src', 'content', 'openapi', 'geolens.json');

console.log(`Fetching ${URL} ...`);
let res;
try {
  res = await fetch(URL);
} catch (err) {
  console.error(`FAIL: network error: ${err.message}`);
  console.error(`Is the geolens API running at ${URL}?`);
  process.exit(2);
}
if (!res.ok) {
  console.error(`FAIL: HTTP ${res.status} ${res.statusText} from ${URL}`);
  process.exit(2);
}
let spec;
try {
  spec = await res.json();
} catch (err) {
  console.error(`FAIL: response was not valid JSON: ${err.message}`);
  process.exit(3);
}
// Validate shape (required fields per OpenAPI 3.x spec)
if (typeof spec.openapi !== 'string') {
  console.error('FAIL: missing required field `openapi` (e.g. "3.1.0")');
  process.exit(3);
}
if (!spec.info || typeof spec.info.version !== 'string') {
  console.error('FAIL: missing required field `info.version`');
  process.exit(3);
}
if (!spec.paths || Object.keys(spec.paths).length === 0) {
  console.error('FAIL: spec has zero paths — refusing to write empty snapshot');
  process.exit(3);
}
await mkdir(dirname(OUT), { recursive: true });
// Deterministic: JSON.stringify preserves insertion order from JSON.parse;
// 2-space indent matches existing repo convention; trailing newline for POSIX-friendly diff.
await writeFile(OUT, JSON.stringify(spec, null, 2) + '\n', 'utf-8');
console.log(`OK: wrote ${OUT}`);
console.log(`    openapi=${spec.openapi} version=${spec.info.version} paths=${Object.keys(spec.paths).length}`);
```

### Pattern 4: verify-build.sh Snapshot + Pagefind Assertions

**What:** Two new bash assertions in the existing `docs/scripts/verify-build.sh`, matching the existing `grep | exit 1 with diff` idiom.

```bash
# ─── Phase 225 assertions (API-01..05, CI-01) ───

echo "Asserting API-01: openapi snapshot present and non-empty in src/content/openapi/..."
test -f src/content/openapi/geolens.json \
  || { echo "FAIL: API-01 src/content/openapi/geolens.json missing — run 'npm run fetch-openapi' against a running geolens API"; exit 1; }
# Smoke check: snapshot is valid JSON with required OpenAPI fields
node -e '
  const s = require("./src/content/openapi/geolens.json");
  if (typeof s.openapi !== "string") { console.error("snapshot missing openapi field"); process.exit(1); }
  if (!s.info || typeof s.info.version !== "string") { console.error("snapshot missing info.version"); process.exit(1); }
  if (!s.paths || Object.keys(s.paths).length === 0) { console.error("snapshot has zero paths"); process.exit(1); }
' || { echo "FAIL: API-01 src/content/openapi/geolens.json failed structural validation"; exit 1; }

echo "Asserting API-02: starlight-openapi rendered tag overview pages exist in dist/guides/api/operations/tags/..."
# At least one tag overview must exist; pick a stable known tag (Datasets) from _OPENAPI_TAGS.
ls dist/guides/api/operations/tags/ 2>/dev/null | grep -q . \
  || { echo "FAIL: API-02 no tag overview pages emitted to dist/guides/api/operations/tags/ — starlight-openapi may not be wired"; exit 1; }

echo "Asserting D-21/D-24: auto-generated reference pages are EXCLUDED from Pagefind (no data-pagefind-body)..."
# Starlight emits data-pagefind-body on <main> iff entry.data.pagefind !== false.
# Our routeMiddleware sets pagefind=false for /guides/api/operations/** — so the attribute MUST be absent.
for f in dist/guides/api/operations/tags/*/index.html; do
  if grep -q 'data-pagefind-body' "$f" 2>/dev/null; then
    echo "FAIL: D-21 auto-generated page $f has data-pagefind-body (should be excluded by pagefind-exclude.ts middleware)"
    exit 1
  fi
done

echo "Asserting D-21/D-24: hand-authored /guides/api/ pages REMAIN indexed (data-pagefind-body present)..."
for f in dist/guides/api/index.html dist/guides/api/auth/index.html dist/guides/api/ogc/index.html; do
  test -f "$f" || { echo "FAIL: hand-authored page missing: $f"; exit 1; }
  grep -q 'data-pagefind-body' "$f" \
    || { echo "FAIL: D-21 hand-authored page $f is missing data-pagefind-body — over-broad exclusion"; exit 1; }
done

echo "Asserting SEO-04 extension: llms.txt now includes /guides/api/auth and /guides/api/ogc..."
for path in /guides/api/auth /guides/api/ogc; do
  grep -qF "https://docs.getgeolens.com${path}" dist/llms.txt \
    || { echo "FAIL: llms.txt missing URL https://docs.getgeolens.com${path}"; exit 1; }
done
```

### Anti-Patterns to Avoid
- **Building a custom OpenAPI renderer from scratch.** REQUIREMENTS API-02 locks `starlight-openapi@0.25.0`. Do not import `swagger-ui`, `redoc`, or hand-roll React components.
- **Live-fetching the OpenAPI spec at build time.** REQUIREMENTS Out of Scope explicitly rejects this. The committed snapshot is the build input.
- **Using `data-pagefind-ignore` on a page-wide wrapper.** This works but is sloppier than the `pagefind: false` mechanism, and conflicts with Starlight's existing `data-pagefind-body` model. Prefer route middleware.
- **Renaming the FastAPI `Auth` tag.** No collision exists at `/guides/api/auth/` — auto-generated tag pages live at `/guides/api/operations/tags/auth/`. Backend tag rename was a fallback for an issue that doesn't exist.
- **Adding `tsx` as a runtime dep just to write `.ts`.** The repo's `verify-shell-layout.mjs` is the existing TS-free precedent. Match that.
- **Writing the snapshot fetch script as a shell+`jq` pipeline.** Native Node `fetch` + `JSON.stringify(2)` produces deterministic output; `jq` formatting can vary across versions.
- **Excluding by Pagefind config glob.** Pagefind's CLI/config supports `exclude_selectors` (CSS selectors) but NOT URL/path globs [VERIFIED: §pagefind.app/docs/config-options]. Don't try to wire this — it doesn't exist.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Render OpenAPI as docs pages | Custom React/Astro components iterating `paths` | `starlight-openapi@0.25.0` | Handles parameter tables, request/response schemas, code snippets, security, webhooks, $ref dereferencing, sidebar grouping, deep-link slugs. ~5K LoC of edge cases. |
| Validate internal links at build | Custom rehype/Astro plugin walking `<a href>` and 404-checking | `starlight-links-validator@0.23.0` | Handles glob excludes, hash anchors, inconsistent locales, MDX components. Already integrated with Starlight's plugin lifecycle. |
| Fetch + validate OpenAPI JSON | curl + `jq` shell pipeline | Native Node `fetch` + JSON.parse + structural checks | Deterministic output (insertion-order preserved), no shell-quoting bugs, works on macOS + Linux + Windows without `jq` install. |
| Exclude pages from Pagefind | Post-build script that walks `dist/` deleting fragment files | Starlight `routeMiddleware` setting `entry.data.pagefind = false` | Native, supported, runs before Pagefind indexing. Post-build deletion races with the index file format and breaks on Starlight upgrades. |
| Forward-reference link tolerance | Stub `.mdx` placeholder pages at every Phase 226/227 destination | `starlight-links-validator` `exclude: [...]` glob | Pure-config; no orphan pages to clean up later; Phase 227 just removes the exclude entries when those routes land. |

**Key insight:** Every problem in this phase has a maintained Starlight plugin or a one-line config flag. Hand-rolling any of them is an anti-pattern that will need re-validation on every Starlight 0.39+ upgrade.

## Common Pitfalls

### Pitfall 1: Misreading the auto-generated URL space
**What goes wrong:** Planner assumes `starlight-openapi` puts tag pages directly at `/guides/api/auth/`, conflicts with the hand-authored `auth.mdx`, and proposes a backend tag rename.
**Why it happens:** The plugin's docs only show `base: 'api'` minimal examples — the operations/tags/{slug} sub-namespace isn't visible at a glance.
**How to avoid:** Read `packages/starlight-openapi/libs/route.ts` directly. The function `getPathItemRoutes` builds: schema overview at `{base}/`, tag overviews at `{base}/operations/tags/{slug}`, operations at `{base}/operations/{operationId}`. The `Auth` tag will live at `/guides/api/operations/tags/auth/`. **There is no collision with `/guides/api/auth/`.** Backend tag rename (CONTEXT.md D-33's fallback) is unnecessary.
**Warning signs:** Planner's task list contains "modify backend/app/api/main.py to rename Auth tag" — this is a phantom requirement.

### Pitfall 2: API key header name in auth.mdx examples
**What goes wrong:** auth.mdx documents `curl -H "Authorization: Bearer <api_key>"` for the API-key flow. Users copy-paste, get 401s, and file confused issues.
**Why it happens:** CONTEXT.md D-12 was authored from memory; the actual header is `X-Api-Key`. The CLAUDE.md project memory mentions "header > query > JWT" priority but doesn't quote the header name.
**How to avoid:** **Source of truth is `backend/app/modules/auth/dependencies.py:23-29`** — `request.headers.get("X-Api-Key")` is the only header check. The backend's own description block in `main.py:248-252` confirms: `X-Api-Key: <key>` for header form. Use this exact header in every API-key curl example.
**Warning signs:** Any draft of `auth.mdx` that uses `Authorization: Bearer` in a sentence near "API key" — flag during plan-check.

### Pitfall 3: Pagefind index file confusion in verify-build.sh
**What goes wrong:** Planner writes `grep "...." dist/_pagefind/...` (with leading underscore) — file doesn't exist, assertion silently passes/fails.
**Why it happens:** Pagefind itself produces `_pagefind/` in some installations; Starlight 0.38.4 writes to `dist/pagefind/` (no underscore) [VERIFIED: `ls /Users/ishiland/Code/getgeolens.com/docs/dist/pagefind/`]. Furthermore, the fragment files are gzipped binary, not greppable for URL paths.
**How to avoid:** Don't grep Pagefind index files at all. Instead, verify the upstream signal — the presence/absence of `data-pagefind-body` on rendered HTML in `dist/guides/api/...`. This is what Pagefind itself uses to decide indexing. See Pattern 4 above.
**Warning signs:** Any verify-build.sh draft that opens `.pf_fragment` or `.pf_index` files; any reference to `_pagefind/` (with underscore).

### Pitfall 4: starlight-openapi as Astro integration
**What goes wrong:** Planner adds `starlightOpenAPI()` to the top-level `integrations:` array — build fails or generates no pages.
**Why it happens:** It's a **Starlight plugin** (registered inside `starlight({ plugins: [...] })`), not an Astro integration. Documentation examples show this clearly but the distinction is subtle.
**How to avoid:** Always nest inside `starlight({...})` config block. The exported `openAPISidebarGroups` symbol must be spread (`...openAPISidebarGroups`) into `sidebar`, not added as a single entry.
**Warning signs:** `astro.config.mjs` showing `integrations: [starlight({...}), starlightOpenAPI(...)]` — wrong tier.

### Pitfall 5: routeMiddleware path conflicts
**What goes wrong:** starlight-openapi already registers its own route middleware (visible in `packages/starlight-openapi/middleware.ts` — for sidebar pagination). Adding a second middleware via Starlight's `routeMiddleware:` config could be skipped, ordered wrong, or shadow the plugin's own.
**Why it happens:** Multiple `routeMiddleware` registrations exist; Starlight runs them in declaration order. Plugins use `addRouteMiddleware({ order: 'post' })` API; user-config middleware runs in the user's declared order.
**How to avoid:** The plugin's middleware mutates `sidebar` and `pagination`. Our middleware mutates `entry.data.pagefind`. They touch different fields — no conflict. Place ours in the `routeMiddleware: ['./src/middleware/pagefind-exclude.ts']` config; Starlight invokes both. Confirm the plugin's middleware survives by inspecting the rendered sidebar at runtime during verification.
**Warning signs:** Sidebar group "Endpoints by Tag" empty in built HTML; pagination missing on auto-generated pages.

### Pitfall 6: starlight-links-validator catches edit-this-page link as broken
**What goes wrong:** The `editLink.baseUrl` from Phase 224 (`https://github.com/geolens-io/getgeolens.com/edit/main/docs/`) generates external links from every page. starlight-links-validator might flag the destination paths if it interprets relative-looking strings.
**Why it happens:** External URLs (`https://...`) are not validated by default for reachability — the validator only checks internal links by default. But misconfigured `errorOnLocalLinks` or aggressive globs could cause false positives.
**How to avoid:** Leave `errorOnLocalLinks: false` (default). Don't add aggressive `exclude` entries for github.com. Test locally with a known-good build before pushing.
**Warning signs:** `npm run build` failure with "broken link to https://github.com/..." — indicates errorOnLocalLinks was inadvertently enabled.

### Pitfall 7: Snapshot drift unnoticed at build time
**What goes wrong:** The snapshot in `geolens.json` is months stale; no one re-ran `fetch-openapi` before release; the docs render wrong endpoint signatures.
**Why it happens:** REQUIREMENTS API-01 explicitly chose manual snapshot refresh; OASDIFF-01 (drift CI) is deferred. There's no automated gate.
**How to avoid:** D-25's README is the only mechanism for now. Make it prominent: link to it from `index.mdx` "Spec snapshot: vX.Y.Z" callout, include a `git log -1` recipe in the README, and put a banner in `auth.mdx` directing readers to file an issue if endpoint signatures look wrong.
**Warning signs:** PR diff shows backend router signature changes WITHOUT a snapshot bump — flag in code review until OASDIFF-01 lands.

## Runtime State Inventory

> Phase 225 is a greenfield content/config phase in the `getgeolens.com/docs/` subtree. There is no rename/refactor/migration component. Section omitted.

## Code Examples

Verified patterns from official sources.

### Example 1: starlight-openapi minimal config
```javascript
// Source: https://starlight-openapi.vercel.app/getting-started/  [CITED]
import starlight from '@astrojs/starlight'
import { defineConfig } from 'astro/config'
import starlightOpenAPI, { openAPISidebarGroups } from 'starlight-openapi'

export default defineConfig({
  integrations: [
    starlight({
      plugins: [
        starlightOpenAPI([
          { base: 'guides/api', schema: './src/content/openapi/geolens.json' },
        ]),
      ],
      sidebar: [
        { label: 'Quickstart',  autogenerate: { directory: 'guides/quickstart' } },
        // ... other autogenerate groups ...
        ...openAPISidebarGroups,
      ],
      title: 'GeoLens Docs',
    }),
  ],
})
```

### Example 2: starlight-links-validator with exclude
```javascript
// Source: https://starlight-links-validator.vercel.app/configuration/  [CITED]
// picomatch glob syntax  [VERIFIED: peerDeps include picomatch ^4.0.3]
import starlightLinksValidator from 'starlight-links-validator'

starlightLinksValidator({
  exclude: [
    '/guides/admin/**',
    '/guides/user/**',
    '/guides/quickstart/**',
  ],
})
```

### Example 3: Curl examples for `auth.mdx` (CORRECTED HEADER)

```bash
# JWT Bearer  [VERIFIED: backend/app/modules/auth/router.py:54 — POST /auth/login/]
# Step 1: obtain access token
curl -X POST https://geolens.example.com/api/auth/login/ \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=alice&password=hunter2"
# → { "access_token": "eyJhbGc...", "refresh_token": "...", "token_type": "bearer" }

# Step 2: use the token
curl https://geolens.example.com/api/collections/datasets/items \
  -H "Authorization: Bearer eyJhbGc..."
```

```bash
# API key (header form)  [VERIFIED: backend/app/modules/auth/dependencies.py:25 — X-Api-Key]
curl https://geolens.example.com/api/collections/datasets/items \
  -H "X-Api-Key: glk_live_..."
```

```bash
# API key (query-param form)  [VERIFIED: backend/app/modules/auth/dependencies.py:27 — api_key]
curl 'https://geolens.example.com/api/collections/datasets/items?api_key=glk_live_...'
```

```bash
# OAuth/OIDC (admin-configured providers)  [VERIFIED: backend/app/modules/auth/oauth/router.py:69]
# Step 1: redirect user to provider login (browser flow, NOT curl)
#   GET https://geolens.example.com/api/auth/oauth/{provider_slug}/login
# Step 2: provider calls back to /api/auth/oauth/{provider_slug}/callback,
#         GeoLens issues a session and redirects to the web UI.
# Step 3: web UI extracts the JWT and uses it like above:
curl https://geolens.example.com/api/collections/datasets/items \
  -H "Authorization: Bearer eyJhbGc..."
```

### Example 4: OGC endpoint examples for `ogc.mdx`

```bash
# OGC API Common — landing page  [VERIFIED: backend/app/standards/ogc/router.py:81]
curl https://geolens.example.com/api/

# OGC API Common — conformance  [VERIFIED: ogc/router.py:128 — see _OPENAPI_TAGS for 16 conf classes]
curl https://geolens.example.com/api/conformance

# OGC API Common — OpenAPI definition (link from landing page)
curl https://geolens.example.com/api/openapi.json
```

```bash
# OGC API Records — list catalog records (datasets)
# [VERIFIED: backend/app/modules/catalog/search/router.py:1272 — GET /collections/datasets/items]
curl https://geolens.example.com/api/collections/datasets/items

# With CQL2 filter (conformance class advertised in /api/conformance)  [CITED: ogc-records-1 + cql2 conf classes]
curl 'https://geolens.example.com/api/collections/datasets/items?filter=keywords%3D%27hydrology%27&filter-lang=cql2-text'
```

```bash
# OGC API Features — per-dataset items  [VERIFIED: backend/app/standards/ogc/router.py:244]
curl https://geolens.example.com/api/collections/{dataset_id}/items
```

```bash
# GDAL ogr2ogr — list collections via OAPIF
# Source: https://gdal.org/en/latest/drivers/vector/oapif.html  [CITED]
ogrinfo OAPIF:https://geolens.example.com/api/

# Download a collection to GeoPackage (with API key)
ogr2ogr -f GPKG out.gpkg "OAPIF:https://geolens.example.com/api/?api_key=glk_live_..." {dataset_id}
```

```python
# pystac-client — search the STAC catalog
# Source: https://pystac-client.readthedocs.io/en/stable/usage.html  [CITED]
# [VERIFIED: backend/app/standards/stac/router.py:48 — prefix="/stac"]
# [VERIFIED: backend/app/standards/stac/router.py:1072 — POST /stac/search]
from pystac_client import Client

client = Client.open("https://geolens.example.com/api/stac/")
search = client.search(
    collections=["my-raster-collection"],
    bbox=[-122.5, 37.5, -122.0, 38.0],
    datetime="2024-01-01/2024-12-31",
)
for item in search.items():
    print(item.id, item.assets["data"].href)
```

```
QGIS — OGC API Records via MetaSearch plugin
Source: https://docs.qgis.org/3.44/en/docs/user_manual/plugins/core_plugins/plugins_metasearch.html  [CITED]

1. Web ▸ MetaSearch ▸ MetaSearch (built-in, no install)
2. Services tab ▸ New
3. Name: GeoLens
   URL:  https://geolens.example.com/api/
   Catalog Type: OGC API - Records
4. Save → Search tab to query records.
```

```
QGIS — OGC API Features (vector)
Source: https://docs.qgis.org/3.44/en/docs/user_manual/working_with_ogc/ogc_client_support.html  [CITED]

1. Layer ▸ Add Layer ▸ Add WFS / OGC API Features Layer
2. New ▸ Name: GeoLens, URL: https://geolens.example.com/api/?api_key=glk_live_...
3. Connect → pick collection → Add.
```

```
Vector tile (MVT) URL pattern  [VERIFIED: backend/app/processing/tiles/router.py:563 —
                                /tiles/{table_path:path}/{z:int}/{x:int}/{y:int}.pbf]
https://geolens.example.com/api/tiles/{dataset_id}/{z}/{x}/{y}.pbf?token={hmac_signed_token}

  # token obtained via:
  #   POST /api/tiles/tokens/  [VERIFIED: tiles/router.py:510]
  #   GET  /api/tiles/token/{dataset_id}/  [VERIFIED: tiles/router.py:468]
  # These are SIGNED ACCESS TOKENS for embedded maps — not generic API keys.
  # They expire and are scoped to a single dataset.

Raster (Titiler) URL pattern — verify shape against snapshot before publishing.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Live OpenAPI fetch at build time | Committed snapshot | REQUIREMENTS Out of Scope decision (2026-04) | Zero CF Pages → backend network dep at build; reviewable git diffs on every API change. |
| Frontmatter `pagefind: false` only | `routeMiddleware` mutates `entry.data.pagefind` | Starlight 0.34+ added route middleware (~mid-2025) | Lets us toggle indexing for plugin-generated pages without forking the plugin. Older Starlight (≤0.33) needed component override or post-build hacks. |
| `data-pagefind-body` opt-in (Pagefind 1.0) | Same — used by Starlight today | n/a | Stable since Pagefind 1.x. The Starlight Page.astro check is `entry.data.pagefind !== false` which we mutate. |
| Tag-based slug collisions | Sub-namespace `operations/tags/{slug}` | starlight-openapi internal design | No collision with hand-authored siblings; the schema overview at `{base}/` is the only overlap point and content collections win. |

**Deprecated/outdated:**
- **`@astrojs/starlight-tailwind`** — phase 224 D-05 + REQUIREMENTS Out of Scope; do not introduce. Starlight 0.38.4's customCss bridge is sufficient.
- **Live "Try it out" consoles via `@scalar/api-reference`** — TRY-IT-01 deferred. Don't preemptively wire.
- **`oasdiff` GitHub Action** — OASDIFF-01 deferred. Snapshot freshness is enforced by README + reviewer discipline only.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The QGIS MetaSearch plugin in QGIS 3.44+ correctly handles GeoLens's OGC API Records implementation | Code Examples | Doc instructions could fail in QGIS for users; mitigation = verify locally before publish or note "tested with QGIS 3.44 LTR". |
| A2 | The `OAPIF:` GDAL driver correctly handles the `?api_key=` query param on the URL passed to `ogrinfo`/`ogr2ogr` | Code Examples + backend/_DESCRIPTION:258 | Backend's own _DESCRIPTION block already shows this pattern — this isn't truly assumed; backend authors validated it. Reclassify as low-risk verification. |
| A3 | starlight-openapi's `routeMiddleware` (registered with `order: 'post'`) does not block our user-registered `routeMiddleware` from running | Architecture Patterns Pattern 5 | If they conflict, sidebar/pagination on auto-pages could break. Mitigation = empirically verify with a small probe build before claiming the plan is complete. |
| A4 | The starlight-openapi tag overview pages will inherit Starlight's `<Page.astro>` template (and thus the `data-pagefind-body` toggle) | Pattern 2 | If the plugin uses a custom layout that bypasses `<Page>`, our middleware doesn't apply and we'd need component override. Verified above: plugin uses `StarlightPage` from `@astrojs/starlight/components` which IS Page.astro under the hood. Low risk. |
| A5 | The OpenAPI snapshot's `info.version` will track the FastAPI app's version field (currently `1.0.0`) | landing page "Spec snapshot" callout | Backend authors must remember to bump `version=` in `main.py:360` on each release. If they don't, the docs report stale version. Mitigation = README Refresh Cadence section. |
| A6 | starlight-links-validator's `exclude: string[]` accepts picomatch globs like `/guides/admin/**` | Pattern 1 / Code Examples | Confirmed via official docs page; risk low. |
| A7 | Pagefind's index in Starlight 0.38.4 is at `dist/pagefind/` (no underscore prefix) | Common Pitfalls #3 | Verified by inspecting current `dist/pagefind/pagefind-entry.json` in the live repo. No risk. |
| A8 | Native Node `fetch` is stable in Node 20 (the docs `.nvmrc` pin) | Pattern 3 | Node 20 ships fetch as stable (graduated in 21+, available behind a flag in 18-20 but no flag needed in 20). Verified. No risk. |

**These assumptions need user/planner discussion only if A3 fails empirically.** A1-A2 and A5-A8 are research findings, not user-decision points.

## Open Questions

1. **Filename: `fetch-openapi.ts` (per REQUIREMENTS literal) vs `fetch-openapi.mjs` (matches existing repo convention)?**
   - What we know: REQUIREMENTS API-01 says `.ts`. Existing scripts are `.sh` and `.mjs`. The `tsx` runner adds 0 runtime cost but 1 devDep + 1 npm-script complication.
   - What's unclear: whether the `.ts` literal in REQUIREMENTS was prescriptive or aspirational.
   - Recommendation: **Planner asks user** during plan-checkpoint. Default to `.mjs` (zero new deps) unless user insists. Both filenames are equivalent in operator-facing behavior; the README can list either.

2. **Should the OGC page show the Vector MVT tile URL example with a placeholder HMAC token, or skip the token-bearing example?**
   - What we know: `/tiles/{dataset_id}/{z}/{x}/{y}.pbf?token=...` is the actual pattern; tokens are issued via `POST /api/tiles/tokens/`.
   - What's unclear: whether the docs should provide a copy-pasteable invocation that requires a separate token issuance step, or just describe the URL shape.
   - Recommendation: describe the shape, link to the Tiles tag in the auto-rendered reference (which documents `POST /tiles/tokens/`), do NOT paste a fake token in a curl example. CONTEXT.md D-18 hints at this — be explicit in the page that these are signed embed-tokens, not API keys.

3. **Should `auth.mdx` correct CONTEXT.md D-12's `Authorization: Bearer <api_key>` claim, or is the planner expected to use the corrected header silently?**
   - What we know: backend reality is `X-Api-Key`. CONTEXT.md D-12 contradicts this.
   - What's unclear: whether D-12 is locked or revisable.
   - Recommendation: **Planner surfaces this discrepancy explicitly** in the plan-check pass. The auth.mdx must use `X-Api-Key` regardless; D-12 should be patched in CONTEXT.md or the discrepancy noted in a phase decision.

4. **D-09 "Spec snapshot" callout: should it derive `last refreshed` from `git log -1 docs/src/content/openapi/geolens.json` at build time, or just show `info.version`?**
   - What we know: `info.version` is in the JSON; git log requires reading process at build time (Astro `astro:config:setup` could `execSync('git log ...')`).
   - What's unclear: whether the build environment has git available (CF Pages does — confirmed by `lastUpdated: true` already working).
   - Recommendation: do BOTH — read `info.version` from the JSON in the MDX via `import` (Astro supports `import spec from '../../openapi/geolens.json'` in MDX frontmatter or component), and use Starlight's `lastUpdated` (already on per Phase 224) to surface the file's git mtime.

5. **`build.format: 'directory'` vs `'file'` interaction with starlight-openapi.**
   - What we know: starlight-openapi has special handling for `build.format: 'file'` (per `libs/path.ts:14`). The current docs `astro.config.mjs` doesn't set `build.format` — Astro defaults to `'directory'`.
   - What's unclear: nothing — defaults are fine.
   - Recommendation: do not set `build.format`. Leave the default.

6. **Snapshot file location relative to `astro.config.mjs`.**
   - What we know: the schema config takes either a path or URL string. Path is resolved relative to the Astro project root.
   - What's unclear: whether `./src/content/openapi/geolens.json` works when the schema is also a content collection (Astro auto-glob's `src/content/**`).
   - Recommendation: place the snapshot OUTSIDE Astro's content-collection scan if collisions occur. Specifically, `src/content/openapi/` is NOT a registered collection by default (only `docs/` is wired by Starlight), so it should be inert. If Astro starts complaining, move to `src/openapi/geolens.json` and update the schema path.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js | All build/scripts | ✓ | 20 (per `.nvmrc`); local dev v25.6.1 | — |
| npm | Install scripts/plugins | ✓ | bundled with Node | — |
| Running geolens API at `localhost:8000` | `fetch-openapi` script (operator-time only) | requires `docker compose up api` | n/a — operator runs this manually | `GEOLENS_API_URL` env override to staging URL |
| `git` | `lastUpdated` Starlight feature; potential `git log` for snapshot freshness | ✓ | system git | — |
| Backend Python/FastAPI runtime | Generates the snapshot — but NOT at docs build time | n/a — operator-only | n/a | snapshot is committed; CI never invokes the backend |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None — operator can override `GEOLENS_API_URL` to point at any reachable instance.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Bash assertion script (`verify-build.sh`) — existing precedent in this repo. No JS unit-test framework in the docs subtree. |
| Config file | `docs/scripts/verify-build.sh` (existing); extended with Phase 225 assertions. |
| Quick run command | `cd docs && npm run build && bash scripts/verify-build.sh` |
| Full suite command | Same — single bash script gates everything in this phase. |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| API-01 | `geolens.json` snapshot is present, parses, has required OpenAPI fields | unit (bash + node -e structural check) | `bash scripts/verify-build.sh` (new assertion) | ❌ Wave 0 — assertion to be added |
| API-01 | `fetch-openapi` script exits 0 for happy path, non-zero for malformed JSON | manual (operator-run only) | `GEOLENS_API_URL=http://localhost:8000/api/openapi.json npm run fetch-openapi` | ❌ Wave 0 — script to be created |
| API-02 | Auto-rendered tag pages emitted to `dist/guides/api/operations/tags/` | smoke (bash existence check) | `bash scripts/verify-build.sh` (new assertion) | ❌ Wave 0 |
| API-02 | Sidebar contains "Endpoints by Tag" (or per-tag) groups | manual (Playwright probe — optional) | `node scripts/verify-shell-layout.mjs` (extend) or local visual check | ✅ verify-shell-layout.mjs exists; extension optional |
| API-03 | `/guides/api/auth/index.html` exists and contains JWT + X-Api-Key + OAuth code blocks | smoke (grep on dist) | `grep -F 'X-Api-Key' dist/guides/api/auth/index.html` | ❌ Wave 0 |
| API-04 | `/guides/api/ogc/index.html` exists and contains OGC API + STAC + Tile examples | smoke (grep on dist) | `grep -F 'OAPIF:' dist/guides/api/ogc/index.html && grep -F 'pystac-client' dist/guides/api/ogc/index.html` | ❌ Wave 0 |
| API-05 | `src/content/openapi/README.md` exists and references the fetch script + freshness procedure | smoke (test -f + grep) | `test -f src/content/openapi/README.md && grep -qF 'fetch-openapi' src/content/openapi/README.md` | ❌ Wave 0 |
| CI-01 | `npm run build` fails on broken internal link | unit (negative-test smoke) | introduce a broken `[link](/nope)` in a temporary MDX file, expect `npm run build` exit 1; remove. Optional during Wave 0. | ❌ Wave 0 (optional) |
| CI-01 | `npm run build` succeeds with current MDX (no broken links) | unit | `cd docs && npm run build` | ✓ existing CI pattern |
| D-21/D-24 | Auto-generated pages are excluded from Pagefind index | unit (HTML attribute check) | `grep -L 'data-pagefind-body' dist/guides/api/operations/tags/*/index.html` returns ALL files | ❌ Wave 0 |
| D-21/D-24 | Hand-authored API pages remain indexed | unit (HTML attribute check) | `grep -l 'data-pagefind-body' dist/guides/api/auth/index.html dist/guides/api/ogc/index.html dist/guides/api/index.html` returns all 3 | ❌ Wave 0 |
| SEO-04 ext | llms.txt now lists `/guides/api/auth` and `/guides/api/ogc` | unit | `grep -F 'docs.getgeolens.com/guides/api/auth' dist/llms.txt && grep -F 'docs.getgeolens.com/guides/api/ogc' dist/llms.txt` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `cd docs && npm run build` (catches links-validator failures + plugin wiring failures fast)
- **Per wave merge:** `cd docs && npm run build && bash scripts/verify-build.sh` (full assertion suite)
- **Phase gate:** Same — single command stack covers everything before `/gsd-verify-work`. Operator additionally runs `npm run fetch-openapi` against a healthy backend at least once before phase sign-off.

### Wave 0 Gaps
- [ ] `docs/scripts/fetch-openapi.mjs` (or `.ts`) — covers API-01
- [ ] `docs/scripts/verify-build.sh` extension — covers API-01..05, D-21/24, SEO-04 ext (modify in-place)
- [ ] `docs/src/content/openapi/geolens.json` — covers API-01 (committed artifact, not a test file)
- [ ] `docs/src/content/openapi/README.md` — covers API-05
- [ ] `docs/src/middleware/pagefind-exclude.ts` — covers D-21/24
- [ ] `docs/src/content/docs/guides/api/index.mdx` — modify (replace placeholder)
- [ ] `docs/src/content/docs/guides/api/auth.mdx` — covers API-03
- [ ] `docs/src/content/docs/guides/api/ogc.mdx` — covers API-04
- [ ] `docs/astro.config.mjs` — wire plugins + routeMiddleware
- [ ] `docs/package.json` — add deps + `fetch-openapi` script
- [ ] `docs/public/llms.txt` — add 2 lines
- [ ] No new test framework needed — bash + node -e is the established pattern.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (docs only) | The auth.mdx documents how readers authenticate to a GeoLens instance — must show CORRECT mechanisms (`X-Api-Key`, `Authorization: Bearer <jwt>`, `?api_key=`) so readers don't roll insecure variants. The docs site itself doesn't authenticate users. |
| V3 Session Management | no | Docs site is static HTML; no sessions. |
| V4 Access Control | no | Docs site is publicly readable (after Phase 228 robots-flip); no authz. |
| V5 Input Validation | yes (build-tooling) | `fetch-openapi` script must validate that the response is a real OpenAPI spec before overwriting the snapshot. Mitigates "rogue local server returns garbage and corrupts our committed snapshot". |
| V6 Cryptography | no | No crypto in this phase. JWT/HMAC details belong to backend, not docs scope. |
| V7 Error Handling | yes | `fetch-openapi` script must fail loudly with a distinct exit code on each failure mode (network, parse, validation) so the operator can diagnose. |
| V14 Configuration | yes | `GEOLENS_API_URL` env override must default to localhost — never to a hardcoded production URL — to prevent accidental snapshot of a stale prod spec when intent was local-dev. |

### Known Threat Patterns for {Astro/Starlight static-site stack}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Snapshot poisoning (malicious local backend or rogue env override) writes garbage to `geolens.json`, breaks docs build silently | Tampering | `fetch-openapi.mjs` validates `openapi`, `info.version`, `paths` keys before writing. CI's `verify-build.sh` re-validates structural shape with `node -e` on every build. Defense-in-depth. |
| Forward-reference link rot (Phase 226/227 routes never land, exclude entries stay) | Repudiation (silent doc-rot) | Exclude entries in `starlight-links-validator` are PR-reviewable. When Phases 226-227 land, those exclude entries get removed in the same PR; CI then validates real links. Phase 228 verification gate confirms exclude list is empty before launch. |
| Stale snapshot indicates wrong endpoints, users follow broken docs | Information Disclosure (of incorrect info) | README D-25 + landing-page "spec snapshot" callout makes snapshot version visible to readers. OASDIFF-01 (deferred) closes the loop in a future phase. |
| Pagefind exclusion misconfigured — sensitive backend tag descriptions get crawled and indexed | Information Disclosure | Auto-generated pages are excluded from Pagefind by design (D-21). The site is also `noindex` until Phase 228, which is a belt-and-suspenders gate against any indexing slip. Verify-build.sh asserts both ends of the exclusion (excluded pages + indexed pages) on every build. |
| Plugin supply chain — `starlight-openapi` is a third-party Starlight plugin | Tampering | Pin to exact version `0.25.0` (not `^0.25.0` or `~0.25.0`). Re-pin only after reading the changelog. Same posture for `starlight-links-validator@0.23.0`. |

## Project Constraints (from CLAUDE.md)

User's global CLAUDE.md directives that affect this phase:

- **Version Control: never indicate AI/Bot activity in commit messages.** Standard for this repo. No phase-specific impact.
- **Code Style: prefer simple, readable code over clever abstractions; follow existing project conventions when editing files.**
  - For Phase 225: prefer `.mjs` (matches `verify-shell-layout.mjs`) over `.ts` (introduces tsx runner). Bash assertions in `verify-build.sh` follow the existing `grep | exit 1` idiom.
- **Communication: be direct and concise; ask before assuming.**
  - For Phase 225: the planner should surface the `Authorization: Bearer <api_key>` discrepancy in CONTEXT.md D-12 instead of silently using `X-Api-Key`. Likewise, the `.ts` vs `.mjs` filename choice should be confirmed.

No project-level CLAUDE.md exists at `/Users/ishiland/Code/geolens/CLAUDE.md`. The geolens repo has CLAUDE.md memory at `/Users/ishiland/.claude/projects/-Users-ishiland-Code-geolens/memory/MEMORY.md`, which is informational (project stack notes, known issues) — no enforcement directives that constrain this phase beyond what's already in CONTEXT.md.

## Sources

### Primary (HIGH confidence)
- npm registry: `npm view starlight-openapi version time peerDependencies` — confirmed `0.25.0` published 2026-04-23, peer deps `@astrojs/starlight >=0.38.0`, `astro >=6.0.0` [VERIFIED]
- npm registry: `npm view starlight-links-validator version time peerDependencies` — confirmed `0.23.0` published 2026-04-09, same peer deps as openapi plugin [VERIFIED]
- starlight-openapi source: `https://github.com/HiDeoo/starlight-openapi/blob/main/packages/starlight-openapi/libs/route.ts` and `libs/path.ts` — auto-route slug structure is `{base}/`, `{base}/operations/{operationId}`, `{base}/operations/tags/{slug}` [VERIFIED via direct file read]
- starlight-openapi source: `index.ts` — registers as Starlight plugin (`StarlightPlugin`), exports `openAPISidebarGroups` symbol-based sidebar placeholder [VERIFIED]
- Starlight source: `packages/starlight/components/Page.astro` — confirms `pagefindEnabled` gate is `entry.data.pagefind !== false` and emits `data-pagefind-body` on `<main>` only when enabled [VERIFIED]
- Backend: `backend/app/modules/auth/dependencies.py:23-29` — API key header is `X-Api-Key`, not `Authorization` [VERIFIED]
- Backend: `backend/app/api/router.py:45-80` — full router include order [VERIFIED]
- Backend: `backend/app/standards/ogc/router.py:81,128,165,244` — OGC API endpoints [VERIFIED]
- Backend: `backend/app/standards/stac/router.py:48,241,293,1072` — STAC endpoints [VERIFIED]
- Backend: `backend/app/processing/tiles/router.py:44,468,510,563` — tile endpoints [VERIFIED]
- Backend: `backend/app/api/main.py:270-354` — full `_OPENAPI_TAGS` list (18 tags); `main.py:358-377` confirms `title="GeoLens API"`, `version="1.0.0"`, `root_path="/api"` [VERIFIED]

### Secondary (MEDIUM confidence — official documentation)
- starlight-openapi docs: `https://starlight-openapi.vercel.app/getting-started/` — minimal config example [CITED]
- starlight-openapi docs: `https://starlight-openapi.vercel.app/configuration/` — full option schema (`base`, `schema`, `sidebar.collapsed`, `sidebar.label`, `sidebar.operations.{badges,labels,sort}`, `sidebar.tags.sort`, `snippets.*`) — does NOT mention `slug`, `frontmatter`, `pagefind`, or per-tag URL overrides [CITED]
- starlight-links-validator docs: `https://starlight-links-validator.vercel.app/configuration/` — `exclude: string[] | (infos) => boolean` with picomatch globs; full option list (`exclude`, `errorOnFallbackPages`, `errorOnInconsistentLocale`, `errorOnRelativeLinks`, `errorOnInvalidHashes`, `errorOnLocalLinks`, `sameSitePolicy`, `failOnError`, `reporters`, `components`) [CITED]
- starlight-links-validator docs: `https://starlight-links-validator.vercel.app/configuration/#exclude` — exact glob syntax verified [CITED]
- Starlight docs: `https://starlight.astro.build/guides/site-search/` — `pagefind: false` frontmatter is the official mechanism; `data-pagefind-ignore` for partial exclusion [CITED]
- Starlight docs: `https://starlight.astro.build/reference/configuration/#routemiddleware` — `routeMiddleware: string | string[]` [CITED]
- Starlight docs: `https://starlight.astro.build/guides/route-data/` — `defineRouteMiddleware`, `context.locals.starlightRoute` shape [CITED]
- Pagefind docs: `https://pagefind.app/docs/indexing/` — `data-pagefind-body` is the page-level gate; absence on a page = page is excluded [CITED]
- Pagefind docs: `https://pagefind.app/docs/config-options/` — `exclude_selectors` is CSS-selector-based; NO URL/path glob option [CITED]
- GDAL docs: `https://gdal.org/en/latest/drivers/vector/oapif.html` — `OAPIF:` driver syntax [CITED]
- pystac-client docs: `https://pystac-client.readthedocs.io/en/stable/usage.html` — `Client.open()` + `client.search(...)` API [CITED]
- QGIS docs: `https://docs.qgis.org/3.44/en/docs/user_manual/plugins/core_plugins/plugins_metasearch.html` — MetaSearch plugin (built-in) supports OGC API Records [CITED]

### Tertiary (LOW confidence — secondary searches; verify before claiming)
- (None — every claim in the OGC examples section is anchored to either a backend file or an official docs URL above.)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — npm registry confirmed versions and peer deps; both plugins from same active maintainer (HiDeoo).
- Architecture: HIGH — read plugin source directly to confirm route generation; read Starlight Page.astro to confirm pagefind toggle; route middleware mechanism documented in Starlight 0.38+ official docs.
- Pitfalls: HIGH — every pitfall has a verified evidence chain (file/line citation, plugin source inspection, or empirical test against the live `dist/`).
- API-key header correction: HIGH — direct read of `backend/app/modules/auth/dependencies.py` and confirmation against backend's own self-documenting `_DESCRIPTION` block.
- OGC endpoint paths: HIGH — every URL traced to a `@router.get(...)` declaration in `backend/app/`.
- QGIS / GDAL examples: MEDIUM — official docs cited, but not empirically tested against a running geolens instance during this research session. Phase verification should include a manual probe.

**Research date:** 2026-04-25
**Valid until:** 2026-05-25 (30 days; stable Starlight + plugin ecosystem; refresh sooner if Starlight 0.39+ ships and breaks plugin peer deps)

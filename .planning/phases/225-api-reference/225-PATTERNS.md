# Phase 225: API Reference - Pattern Map

**Mapped:** 2026-04-25
**Files analyzed:** 10 (6 create, 4 modify) plus 1 backend file flagged as no-touch
**Analogs found:** 9 / 10 (one NEW PATTERN: Starlight route middleware)

## File Classification

| Target file (full path) | Role | Data flow | Closest analog (full path) | Match quality |
|-------------------------|------|-----------|----------------------------|---------------|
| `/Users/ishiland/Code/getgeolens.com/docs/astro.config.mjs` | Astro/Starlight config (plugin registration + middleware wiring) | build-time config | itself (in-place modification) | exact — extend existing block |
| `/Users/ishiland/Code/getgeolens.com/docs/package.json` | npm manifest (deps + script) | build-time config | itself | exact — extend in place |
| `/Users/ishiland/Code/getgeolens.com/docs/scripts/verify-build.sh` | Bash build-artifact assertion script | post-build CI gate | itself + `scripts/check-token-sync.sh` | exact — extend existing idiom |
| `/Users/ishiland/Code/getgeolens.com/docs/public/llms.txt` | Static text manifest of canonical URLs | static asset | itself (extend list) | exact — append new lines |
| `/Users/ishiland/Code/getgeolens.com/docs/src/content/docs/guides/api/index.mdx` | Hand-authored MDX content page (curated landing) | content-collection | sibling Phase 224 placeholders + `docs/src/content/docs/index.mdx` | role-match (no curated landing exists yet) |
| `/Users/ishiland/Code/getgeolens.com/docs/scripts/fetch-openapi.mjs` (CREATE) | Node script: HTTP fetch + write file | build-tooling, request-response | `docs/scripts/verify-shell-layout.mjs` | role-match (only `.mjs` script in tree) |
| `/Users/ishiland/Code/getgeolens.com/docs/src/content/openapi/geolens.json` (CREATE) | Committed JSON build input | static data file | none in repo (new content directory) | NEW PATTERN — script-emitted artifact |
| `/Users/ishiland/Code/getgeolens.com/docs/src/content/openapi/README.md` (CREATE) | In-tree maintenance doc | static doc | `docs/README.md` (top-level) | role-match (only existing README in docs subtree) |
| `/Users/ishiland/Code/getgeolens.com/docs/src/content/docs/guides/api/auth.mdx` (CREATE) | Hand-authored MDX with curl/code blocks | content-collection | `docs/src/content/docs/index.mdx` (frontmatter shape) + `ec-pagefind-weight.mjs` comments (code-block weight contract) | role-match (no tutorial-style MDX exists yet) |
| `/Users/ishiland/Code/getgeolens.com/docs/src/content/docs/guides/api/ogc.mdx` (CREATE) | Hand-authored MDX, multi-section landing | content-collection | same as auth.mdx | role-match |
| `/Users/ishiland/Code/getgeolens.com/docs/src/middleware/pagefind-exclude.ts` (CREATE) | Starlight route middleware mutating `entry.data.pagefind` | build-time route hook | none in tree | **NEW PATTERN** (capture from RESEARCH.md §Pattern 2) |
| `/Users/ishiland/Code/geolens/backend/app/api/main.py` | FastAPI tag taxonomy | (not modified) | n/a | DO NOT TOUCH — researcher confirmed no rename is required |

> **Naming note for the route-middleware file:** the phase prompt suggests `src/content/docs/_routeMiddleware.ts` (older Starlight convention — underscore-prefixed file inside the content collection). RESEARCH.md §Pattern 2 (authoritative) uses `src/middleware/pagefind-exclude.ts` plus an explicit `routeMiddleware: ['./src/middleware/pagefind-exclude.ts']` entry in `astro.config.mjs`. Starlight 0.34+ supports both shapes; the explicit-config form is what the researcher verified against the cited Starlight docs (`starlight.astro.build/reference/configuration/#routemiddleware`), so the planner should default to it. If the planner chooses the underscore form for the path, the file body and `defineRouteMiddleware` call shape are identical.

---

## Pattern Assignments

### Group A — Config

#### `docs/astro.config.mjs` (modify) — register two new Starlight plugins + routeMiddleware

**Analog:** the existing file at `/Users/ishiland/Code/getgeolens.com/docs/astro.config.mjs` (Phase 224 baseline) — same file, extend in place.

**Imports pattern** (lines 1-5) — add two new ESM imports alongside the existing four:
```javascript
// docs/astro.config.mjs
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import sitemap from '@astrojs/sitemap';
import { pluginPagefindWeight } from './plugins/ec-pagefind-weight.mjs';
```

The Phase 224 convention is **named ESM imports**, no default `* as`, no JSON imports. New imports must follow the same shape. RESEARCH.md §Pattern 1 (line 284-285) gives the canonical names:
```javascript
import starlightOpenAPI, { openAPISidebarGroups } from 'starlight-openapi';
import starlightLinksValidator from 'starlight-links-validator';
```

**Starlight plugins-array pattern** — Phase 224 nests its single plugin (`pluginPagefindWeight`) inside the `expressiveCode.plugins` slot (lines 25-27), NOT the top-level Starlight `plugins:` slot. The Starlight `plugins:` array does NOT yet exist in this file — it must be added inside the `starlight({ ... })` block. Place it adjacent to `expressiveCode` to keep all plugin wiring co-located.

**Sidebar-merge pattern** (lines 49-66) — current sidebar is a 4-entry array with `autogenerate` for each guide. Phase 224's intent (`D-13`) was to keep `autogenerate: { directory: 'guides/api' }` at index 3. Phase 225 must spread `...openAPISidebarGroups` AFTER the existing 4 entries (D-08 sidebar order: hand-authored first, auto-generated tag pages alphabetized after).

**Existing block to extend** (verbatim lines 49-66 of current file):
```javascript
sidebar: [
  {
    label: 'Quickstart',
    autogenerate: { directory: 'guides/quickstart' },
  },
  {
    label: 'User Guide',
    autogenerate: { directory: 'guides/user' },
  },
  {
    label: 'Admin Guide',
    autogenerate: { directory: 'guides/admin' },
  },
  {
    label: 'API Reference',
    autogenerate: { directory: 'guides/api' },
  },
],
```

**Notes on what to change vs preserve:**
- PRESERVE: every line above (`title`, `customCss`, `editLink`, `pagination`, `lastUpdated`, `expressiveCode.plugins`, `components`, `head[noindex]`, the 4 sidebar entries, the top-level `sitemap()` integration).
- ADD inside `starlight({...})`: `plugins: [starlightOpenAPI([{...}]), starlightLinksValidator({exclude: [...]})]`, append `...openAPISidebarGroups` to `sidebar`, add `routeMiddleware: ['./src/middleware/pagefind-exclude.ts']`.
- DO NOT change the Phase 224 head/noindex meta (carryover D-07/08 says it stays through Phase 228).

---

#### `docs/package.json` (modify) — add deps + `fetch-openapi` script

**Analog:** the existing file at `/Users/ishiland/Code/getgeolens.com/docs/package.json` — extend in place.

**Existing scripts block** (verbatim, lines 9-16):
```json
"scripts": {
  "dev": "astro dev",
  "build": "astro build",
  "preview": "astro preview",
  "check": "astro check",
  "verify": "bash scripts/verify-build.sh",
  "astro": "astro"
},
```

**Convention to replicate:**
- Bash scripts run via `bash scripts/<name>.sh` (see `verify`).
- `.mjs` scripts have no precedent in `scripts:` yet (`verify-shell-layout.mjs` is invoked by hand from `npm run preview`, not via npm script). The researcher (RESEARCH.md §Standard Stack and §Open Questions) recommends `node scripts/fetch-openapi.mjs` — matches the `bash scripts/<name>.sh` shape (direct runner invocation, no wrapper).
- ALL scripts use **relative paths from the docs root** (`scripts/...`, never `./scripts/` or `docs/scripts/`).
- `engines.node: ">=22.12.0"` is already pinned — native `fetch` is available, no `tsx` dep needed.

**New script entry to add** (between `verify` and `astro`):
```json
"fetch-openapi": "node scripts/fetch-openapi.mjs",
```

**New devDependencies to add** (alphabetized into `dependencies` block — note: this repo currently has all packages under `dependencies`, no `devDependencies` block; preserve that convention):
```json
"starlight-links-validator": "^0.23.0",
"starlight-openapi": "^0.25.0"
```

**Notes:**
- DO NOT introduce a new `devDependencies` block — match existing single-`dependencies` shape.
- If the planner keeps the literal `.ts` filename from REQUIREMENTS API-01 (researcher recommends against), add `"tsx": "^4.21.0"` and change script to `node --import tsx scripts/fetch-openapi.ts`. Researcher prefers `.mjs`.

---

### Group B — Build-time scripts

#### `docs/scripts/verify-build.sh` (modify) — add 4 new Phase 225 assertions

**Analog:** the existing file at `/Users/ishiland/Code/getgeolens.com/docs/scripts/verify-build.sh` — same file, extend in place. Secondary analog for the **bash assertion shape** is `docs/scripts/check-token-sync.sh`.

**Header pattern** (lines 1-3) — every assertion script in this tree opens identically:
```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
```

PRESERVE this header; new assertions append to the bottom.

**Assertion idiom — `grep | exit 1` short form** (lines 5-7, 9-11, 14, 17, 35-36):
```bash
echo "Asserting canonical URL points to docs.getgeolens.com..."
grep -F 'rel="canonical"' dist/index.html | grep -F 'https://docs.getgeolens.com' \
  || { echo "FAIL: canonical missing or wrong"; exit 1; }
```

**Assertion idiom — file-presence + content gate** (lines 14, 119-122, 128-129):
```bash
test -f dist/sitemap-index.xml || { echo "FAIL: sitemap-index missing"; exit 1; }

test -f plugins/ec-pagefind-weight.mjs \
  || { echo "FAIL: SEARCH-02 plugins/ec-pagefind-weight.mjs missing"; exit 1; }
grep -qF 'postprocessRenderedBlock' plugins/ec-pagefind-weight.mjs \
  || { echo "FAIL: SEARCH-02 EC plugin missing postprocessRenderedBlock hook"; exit 1; }
```

**Assertion idiom — for-loop over expected paths** (lines 65-68, 138-141):
```bash
for label in 'Quickstart' 'User Guide' 'Admin Guide' 'API Reference'; do
  grep -qF "$label" dist/index.html \
    || { echo "FAIL: SHELL-01 sidebar label '$label' missing from dist/index.html"; exit 1; }
done

for path in /guides/quickstart /guides/user /guides/admin /guides/api; do
  grep -qF "https://docs.getgeolens.com${path}" dist/llms.txt \
    || { echo "FAIL: SEO-04 llms.txt missing URL https://docs.getgeolens.com${path}"; exit 1; }
done
```

**Sectional comment idiom** (line 38, line ~135) — phases delimit their additions with a comment fence:
```bash
# ─── Phase 224 assertions (BRAND-01/02, SHELL-01..05, SEARCH-01/02, SEO-04) ───
```

Phase 225 must add a matching `# ─── Phase 225 assertions (API-01..05, CI-01) ───` fence at the bottom, BEFORE the final `echo "All build-artifact assertions passed."` line (which stays last — that line lives at line 143 today).

**Notes on what to change vs preserve:**
- PRESERVE: every line of the existing 143-line script.
- APPEND: 4 assertion blocks per RESEARCH.md §Pattern 4 (lines 417-457): (1) snapshot present + structurally valid, (2) tag-overview pages emitted, (3) auto-generated pages LACK `data-pagefind-body`, (4) hand-authored pages HAVE `data-pagefind-body`, (5) llms.txt extended with two new paths.
- The "last line" `echo "All build-artifact assertions passed."` must remain the literal last echo — append above it, not below.
- `check-token-sync.sh` (lines 28-51) is the cleaner precedent for **looped comparison with diff output** if the planner wants to extend Phase 225 with cross-file structural diffs (probably not needed for this phase).

---

#### `docs/scripts/fetch-openapi.mjs` (CREATE) — manual operator HTTP-fetch script

**Analog:** `/Users/ishiland/Code/getgeolens.com/docs/scripts/verify-shell-layout.mjs` — the only existing `.mjs` script in the tree. Demonstrates the project conventions for ESM scripts that talk to a network resource and exit non-zero on failure.

**Shebang + header pattern** (lines 1-19 of `verify-shell-layout.mjs`):
```javascript
#!/usr/bin/env node
/*
 * verify-shell-layout.mjs — SHELL-05 runtime non-overlap probe (gap-closure plan 224-05).
 *
 * Drives Playwright Chromium against a locally-running `npm run preview` server to
 * assert that the back-link and the Starlight site-title anchors do NOT overlap...
 *
 * Usage:
 *   # Terminal 1: cd docs && npm run preview
 *   # Terminal 2: cd docs && node scripts/verify-shell-layout.mjs
 *
 * Exit 0 on success; exit 1 with bounding-rect diff on overlap or unreachable preview.
 */

import { chromium } from 'playwright';
```

The convention: `#!/usr/bin/env node` shebang, multi-line block comment naming the script, citing the requirement ID it satisfies, including a `Usage:` block, ESM imports below.

**Error-handling pattern** (lines 86-93):
```javascript
let browser;
try {
  browser = await chromium.launch();
} catch (err) {
  console.error('FAIL: could not launch Playwright Chromium:', err.message);
  console.error('       Hint: run `npx playwright install chromium` from the repo root.');
  process.exit(1);
}
```

The convention: `console.error('FAIL: ...')` prefix on every failure line (matches `verify-build.sh` `FAIL:` prefix exactly), distinct exit codes when meaningful, helpful "Hint:" lines pointing at the recovery action.

**Exit-code pattern** — `verify-shell-layout.mjs` uses `exit(0)` / `exit(1)` only. RESEARCH.md §Pattern 3 (lines 360-411) shows the planned `fetch-openapi.mjs` graduated codes (`2` = network/HTTP error, `3` = invalid spec). That graduation is acceptable and matches the existing FAIL/Hint prose style.

**Body shape — copy from RESEARCH.md §Pattern 3 verbatim** (researcher already verified against Node 20+ native fetch + `JSON.stringify(_, null, 2)` determinism). Key conventions to preserve:
- `process.env.GEOLENS_API_URL ?? 'http://localhost:8000/api/openapi.json'` — env override with literal default.
- `import.meta.url` + `fileURLToPath` to derive `__dirname` (matches modern ESM idiom; `verify-shell-layout.mjs` doesn't need this but RESEARCH.md uses it).
- `JSON.stringify(spec, null, 2) + '\n'` — 2-space indent + trailing newline (POSIX-friendly diff).

**Notes:**
- This file is the single point where REQUIREMENTS API-01's "documented script" promise lives. The header comment must cite API-01 and reference `docs/src/content/openapi/README.md` for the operator workflow.
- DO NOT add dependencies (no `node-fetch`, no `axios`, no `commander`). Native `fetch` + `process.argv` only. Researcher confirmed `engines.node: ">=22.12.0"` makes this safe.

---

### Group C — Static content / data

#### `docs/public/llms.txt` (modify) — add two new lines

**Analog:** the existing `/Users/ishiland/Code/getgeolens.com/docs/public/llms.txt` — extend in place.

**Existing format** (lines 1-11 verbatim):
```
# GeoLens Documentation

> Documentation for the GeoLens self-hosted GIS data catalog. Covers install, user guide, admin guide, and OGC/REST API reference. Single canonical home for all GeoLens user-facing documentation; supersedes legacy backend/docs/{install,admin}.md files.

## Guides

- [Quickstart](https://docs.getgeolens.com/guides/quickstart): Stand up GeoLens with Docker Compose and complete first-login flow.
- [User Guide](https://docs.getgeolens.com/guides/user): Search, dataset detail, map builder, collections, imports, and exports.
- [Admin Guide](https://docs.getgeolens.com/guides/admin): User management, OAuth/OIDC, settings, backups, monitoring, and cloud deployment.
- [API Reference](https://docs.getgeolens.com/guides/api): OGC API (Common, Records, Features, STAC), REST endpoints with auth examples.
```

**Convention to replicate (CRITICAL):**
- Every line is `- [Title](https://docs.getgeolens.com/PATH): Sentence-case description ending with a period.`
- Title case for the bracketed label.
- Absolute `https://docs.getgeolens.com/...` URL (no trailing slash on the path component — note `guides/api` not `guides/api/`).
- One sentence per entry; descriptive, not promotional.
- Existing entries are listed under a single `## Guides` heading. Phase 225 may either: (a) append two new lines under `## Guides` (simplest, recommended), or (b) introduce a sub-section. Researcher's note in CONTEXT.md `### From Phase 224 (D-31)` says "Phase 225 may extend it (one new line for `/guides/api/auth` and one for `/guides/api/ogc`)" — interpret as (a).

**Lines to add** (under `## Guides`, after the existing API Reference line):
```
- [API Authentication](https://docs.getgeolens.com/guides/api/auth): JWT, API key (header and query forms), and OAuth/OIDC examples for the GeoLens REST API.
- [API OGC Endpoints](https://docs.getgeolens.com/guides/api/ogc): OGC API Common, Records, Features, STAC, and tile endpoints with QGIS and ogr2ogr examples.
```

**Notes:**
- DO NOT change the existing 4 entries — Phase 224 D-31 is locked.
- The verify-build.sh assertion (Phase 225 §Pattern 4) will grep for these exact URLs.

---

#### `docs/src/content/openapi/geolens.json` (CREATE) — committed snapshot

**Analog:** none in the repo. This is a script-emitted artifact — its shape is dictated by the OpenAPI 3.x spec from FastAPI, not by any local convention.

**Convention to preserve (from RESEARCH.md §Pattern 3):**
- Pretty-printed with 2-space indent (`JSON.stringify(spec, null, 2) + '\n'`).
- Trailing newline.
- Insertion-order preserved (no key sorting — `JSON.parse` + `JSON.stringify` round-trip is deterministic on stable input).
- File created by `scripts/fetch-openapi.mjs`, NOT hand-authored.

**Notes:**
- Validate post-fetch using the bash assertion in `verify-build.sh` (Phase 225 §Pattern 4 — the `node -e` smoke check).
- Spec required-fields gate: `openapi`, `info.version`, `paths` (≥1 entry).
- Phase 225 commits this file. Subsequent phases re-run `npm run fetch-openapi` and review the diff before committing (operator workflow per D-03).

---

#### `docs/src/content/openapi/README.md` (CREATE) — refresh-cadence doc

**Analog:** `/Users/ishiland/Code/getgeolens.com/docs/README.md` — the only existing README in the docs subtree. Demonstrates the project's README convention: short top-level title, link table for site/project metadata, code-fenced shell recipes, phase-boundary section listing what each phase ships.

**Header pattern** (lines 1-3 of `docs/README.md`):
```markdown
# GeoLens Docs

Astro Starlight documentation site, deployed independently from the marketing site.
```

**Bullet-list metadata pattern** (lines 5-7):
```markdown
- **Site:** https://docs.getgeolens.com (currently noindex during bootstrap, flips in Phase 228)
- **CF Pages project:** `getgeolens-docs`
- **Build isolation:** Owns its own `package.json`, `node_modules/`, and `dist/`. CI path-filtered to `docs/**`.
```

**Code-recipe pattern** (lines 11-18):
```markdown
## Local development

```sh
cd docs
npm install
npm run dev      # Astro dev server
npm run check    # astro check (type errors)
npm run build    # Static build → dist/
npm run verify   # Build-artifact assertions (canonical, noindex, sitemap, _redirects)
```
```

Note: ` ```sh` fence (NOT `bash`), trailing inline-comments after each command, two-space alignment.

**Phase-boundary footer pattern** (lines 24-31):
```markdown
## Phase boundaries

- **Phase 223 (this scaffold):** infrastructure only — bootstrap, deploy, URL structure lock, noindex insurance.
- **Phase 224:** brand depth (full OKLCH token bridge, Inter font), sidebar labels, search, shell components.
- **Phase 225:** API reference (openapi.json snapshot, starlight-openapi plugin).
```

**What `openapi/README.md` should adapt from this analog:**
- Top-level `# OpenAPI Snapshot` heading.
- One-paragraph orientation explaining the snapshot is the build's source of truth (D-04).
- Bullet-list metadata: where the spec comes from, where it's written, how often it refreshes.
- ```sh ``` fenced code block reproducing the operator workflow from CONTEXT.md D-03 verbatim.
- A "How to verify the snapshot is current" sub-section with the `git log -1 docs/src/content/openapi/geolens.json` recipe (D-25).
- Final paragraph linking to OASDIFF-01 deferral note in `.planning/REQUIREMENTS.md` so future maintainers know automated drift CI is planned (D-25).

**Notes:**
- DO NOT add a `## Phase boundaries` section in this README — that's the docs-root README's role.
- This README is **content-collection-adjacent**, not part of a content collection. Astro will not render it as a docs page (it lives under `src/content/openapi/`, not `src/content/docs/`). Verify by checking the `src/content.config.ts` — only the `docs` collection is registered.

---

#### `docs/src/content/docs/guides/api/index.mdx` (modify) — replace placeholder with curated landing

**Analog (frontmatter shape):** `/Users/ishiland/Code/getgeolens.com/docs/src/content/docs/index.mdx` (the docs-root landing page — closest existing curated content with a prose body).

**Existing placeholder to REPLACE** (full file, 5 lines):
```mdx
---
title: API Reference (coming soon)
---

Content for this section ships in Phase 225.
```

**Frontmatter convention** (from `docs/src/content/docs/index.mdx` lines 1-5):
```mdx
---
title: GeoLens Documentation
description: Documentation for the GeoLens self-hosted GIS data catalog.
template: doc
---
```

**Convention to replicate:**
- `title:` is the H1 (Starlight derives `<h1>` from frontmatter — DO NOT also write `# Title` in the body).
- `description:` is short, one sentence. Starlight emits it as `<meta name="description">`.
- `template: doc` is the default — explicit declaration is fine for clarity.
- Body uses simple Markdown. NO custom Astro components imported here in Phase 224 (the `Card`, `CardGrid` Starlight components are available but not yet used; Phase 225 may introduce them — see RESEARCH.md §Code Examples). Internal links use `/guides/...` absolute paths (no trailing slash — see line 17-19 of analog).

**Body pattern from `docs/src/content/docs/index.mdx`** (lines 7-22):
```mdx
# GeoLens Documentation

GeoLens v1.0 documentation — coming soon.

We're migrating the install and admin guides into a dedicated docs site.
The full content arrives across phases 224–227.

## Planned URL Structure

- [Quickstart & Install](/guides/install) — getting GeoLens running via `docker compose`
- [Admin Guide](/guides/admin) — RBAC, OAuth, settings, backups, infrastructure
- [API Reference](/guides/api) — REST + OGC endpoints (auto-generated)

In the meantime, see the [GeoLens repository](https://github.com/geolens-io/geolens)
on GitHub.
```

**Notes:**
- The body H1 (`# GeoLens Documentation`) in this analog is **redundant with frontmatter `title`** — Starlight will render both unless one is removed. Phase 225 should NOT replicate the duplicate H1; only the frontmatter `title:` should drive the h1.
- The "Spec snapshot: vX.Y.Z" callout (D-09) does NOT have a precedent component in-tree. RESEARCH.md §State of the Art recommends Starlight's built-in `<Aside>` from `@astrojs/starlight/components`. If the planner wants a card layout, RESEARCH.md §Recommended Project Structure mentions `<Card>`/`<CardGrid>` are Starlight built-ins; the import shape is `import { Card, CardGrid } from '@astrojs/starlight/components';`.
- Forward-link `/guides/admin/oauth` and `/guides/admin/users` will be flagged by `starlight-links-validator` unless covered by the `exclude:` glob from astro.config.mjs (D-29 path 1).

---

#### `docs/src/content/docs/guides/api/auth.mdx` (CREATE) — hand-authored authentication page

**Analog (frontmatter + body shape):** same as `index.mdx` — `docs/src/content/docs/index.mdx`. No tutorial-style MDX with curl examples exists yet in the docs subtree, so curl/code-block conventions are pulled from the **Expressive Code plugin contract** in `docs/plugins/ec-pagefind-weight.mjs`.

**Code-block convention** — every fenced block becomes an Expressive Code `<figure><pre>` with `data-pagefind-weight="0.1"` (Phase 224 D-28). Source of truth for what the plugin does:

```javascript
// docs/plugins/ec-pagefind-weight.mjs lines 17-29
export function pluginPagefindWeight() {
  return definePlugin({
    name: 'pagefind-weight',
    hooks: {
      postprocessRenderedBlock: (context) => {
        const { blockAst } = context.renderData;
        blockAst.properties = blockAst.properties || {};
        blockAst.properties['data-pagefind-weight'] = '0.1';
      },
    },
  });
}
```

**Implication for auth.mdx:**
- Use **standard fenced code blocks** (` ```bash`, ` ```javascript`, ` ```http`). Expressive Code handles them automatically — DO NOT manually add `data-pagefind-weight` attributes.
- Curl examples should be ` ```bash` fences (matches RESEARCH.md §Code Examples 3, 4 exactly).
- DO NOT use ` ```sh` for curl (use `bash` consistently; `sh` is reserved for `cd`/`npm` recipes per the docs-root README precedent).

**Body content source — RESEARCH.md §Code Examples 3** (verified curl shapes — must use literally because researcher caught a CONTEXT.md D-12 error):
- API key header is `X-Api-Key`, NOT `Authorization: Bearer <api_key>` (the latter is JWT-only).
- Placeholder host MUST be `https://geolens.example.com/api/...` (D-15) — never `demo.getgeolens.com`, `localhost:8000`, or `getgeolens.com`.

**Frontmatter to use:**
```mdx
---
title: API Authentication
description: JWT, API key (header and query forms), and OAuth/OIDC for the GeoLens REST API.
---
```

**Forward-reference convention** (D-29) — auth.mdx links to `/guides/admin/users` and `/guides/admin/oauth`. The `starlight-links-validator` plugin must be configured with `exclude: ['/guides/admin/**', ...]` so these don't fail the build until Phase 227 lands. RESEARCH.md §Code Example 2 gives the exact `exclude:` glob.

**Notes:**
- Sectioning: H2 per auth method (`## JWT Bearer Tokens`, `## API Keys`, `## OAuth / OIDC`). Order locked by D-10.
- Each section has at least one ` ```bash ` curl example (D-10 + D-11/12/13).
- NO flow diagrams (D-14 — examples-driven prose only).
- NO live demo URLs (D-19).
- This is the FIRST hand-authored MDX with non-trivial body content in the entire docs subtree. It implicitly establishes the convention for `ogc.mdx`, Phase 226 (Quickstart), and Phase 227 (User/Admin guides).

---

#### `docs/src/content/docs/guides/api/ogc.mdx` (CREATE) — hand-authored OGC landing

**Analog:** identical to `auth.mdx` (same content collection, same fenced-code convention via Expressive Code plugin). Plus, since ogc.mdx contains a 5-section landing, its **section-listing pattern** can borrow from the `index.mdx` "Planned URL Structure" bullet list:

```mdx
## Planned URL Structure

- [Quickstart & Install](/guides/install) — getting GeoLens running via `docker compose`
- [Admin Guide](/guides/admin) — RBAC, OAuth, settings, backups, infrastructure
- [API Reference](/guides/api) — REST + OGC endpoints (auto-generated)
```

**Convention to replicate:**
- `[Title](/relative/path) — em-dash + one-line description` for each row.
- No tables in `index.mdx` for cross-section navigation; bullet lists are the convention.
- For the section bodies themselves (Common, Records, Features, STAC, Tiles), use H2 per section + the `auth.mdx` curl pattern.

**Frontmatter:**
```mdx
---
title: OGC API & Standards Endpoints
description: OGC API Common, Records, Features, STAC, and tile endpoints with QGIS and ogr2ogr examples.
---
```

**Body content source — RESEARCH.md §Code Examples 4** (lines 611-697) — copy curl/ogrinfo/pystac-client snippets verbatim; researcher already verified each path against backend source files.

**Notes:**
- Single-page landing per D-16. DO NOT split into per-standard sub-pages.
- Five sections, in order: OGC API Common → Records → Features → STAC 1.1 → Tiles (D-16).
- QGIS instructions use a plain ` ``` ` fence (no language tag) — RESEARCH.md §Code Examples 4 lines 664-674 / 676-683 demonstrate this. Expressive Code will still apply `data-pagefind-weight="0.1"`.
- Tile section must distinguish HMAC-signed access tokens (for embedded maps) from generic API keys (D-18).

---

### Group D — Middleware

#### `docs/src/middleware/pagefind-exclude.ts` (CREATE) — Starlight route middleware

**Analog:** **NEW PATTERN** — no `defineRouteMiddleware` usage anywhere in the docs subtree today. The pattern source is RESEARCH.md §Pattern 2 (lines 332-353), which the researcher verified against:
1. Starlight 0.34+ documented `routeMiddleware` config (`https://starlight.astro.build/reference/configuration/#routemiddleware` [CITED]).
2. `defineRouteMiddleware` API (`https://starlight.astro.build/guides/route-data/` [CITED]).
3. `withastro/starlight @ packages/starlight/components/Page.astro` — emits `data-pagefind-body` iff `entry.data.pagefind !== false` [VERIFIED].

**Imports pattern** (RESEARCH.md §Pattern 2 line 340):
```typescript
import { defineRouteMiddleware } from '@astrojs/starlight/route-data';
```

**Core pattern** (RESEARCH.md §Pattern 2 lines 342-352):
```typescript
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

**Wiring in `astro.config.mjs`** (RESEARCH.md §Pattern 1 line 323):
```javascript
routeMiddleware: ['./src/middleware/pagefind-exclude.ts'],
```

**Header comment convention** — match the in-repo style established by `ec-pagefind-weight.mjs` (multi-line block comment naming the file, citing the requirement ID, explaining why the mechanism is necessary). Reproduced for reference:
```javascript
// ec-pagefind-weight.mjs — SEARCH-02 / D-28.
//
// Adds data-pagefind-weight="0.1" to every Expressive Code rendered code block.
// Per RESEARCH.md Pivot #1: a rehype plugin DOES NOT work — EC replaces <pre> AST nodes
// with its own rendered <figure><pre> tree, discarding any attributes a user-defined
// rehype plugin sets...
```

The new `pagefind-exclude.ts` should open with an analogous block: name the file, cite D-21/D-22, summarise why route-middleware was chosen over component override or `data-pagefind-ignore` wrappers (RESEARCH.md §Don't Hand-Roll table — entry "Exclude pages from Pagefind").

**Notes:**
- TS file (`.ts`), NOT `.mjs` — Starlight's `defineRouteMiddleware` ships TypeScript types; using `.ts` lets `astro check` validate the middleware. The repo's `tsconfig.json` extends `astro/tsconfigs/strict` and includes `**/*` (line 3), so the file will be type-checked automatically.
- Pitfall to flag (RESEARCH.md §Pitfall 5): starlight-openapi already registers its own `routeMiddleware` (with `order: 'post'`) for sidebar/pagination. Both middlewares run; ours mutates `entry.data.pagefind`, theirs mutates sidebar — no field overlap. Verify by inspecting rendered sidebar at runtime.
- The phase prompt mentions `_routeMiddleware.ts` (older Starlight content-collection convention). RESEARCH.md uses `src/middleware/pagefind-exclude.ts` (current Starlight `routeMiddleware:` config convention). The **planner should default to RESEARCH.md's path** (`src/middleware/pagefind-exclude.ts`) because the cited Starlight docs URL is for the explicit-config form.

---

## Shared Patterns (cross-cutting)

### S-1 — Citation header on every new file

**Source:** `docs/plugins/ec-pagefind-weight.mjs` (lines 1-15), `docs/scripts/check-token-sync.sh` (lines 1-15), `docs/scripts/verify-shell-layout.mjs` (lines 1-19), `docs/src/components/Breadcrumbs.astro` (lines 1-3), `docs/src/components/DocsHeader.astro` (lines 1-12).

**Apply to:** every new `.mjs`, `.ts`, `.astro`, `.sh` file.

**Convention:**
- Open with a multi-line block comment.
- First line: filename + requirement ID (e.g., `// pagefind-exclude.ts — D-21 / D-22`).
- One-paragraph summary of what the file does.
- Cite RESEARCH.md pivots / pitfalls when behaviour is non-obvious.
- Cite specific line numbers in upstream config files when wiring is involved (e.g., `Wired in docs/astro.config.mjs: routeMiddleware: ['./src/middleware/pagefind-exclude.ts']`).
- For shell scripts, include a `# Usage:` block.

**Excerpt (Breadcrumbs.astro lines 1-3):**
```astro
---
// Breadcrumbs.astro — SHELL-02 (D-17). Override target: components.PageTitle in astro.config.mjs.
// Renders before the default PageTitle (which emits the page <h1>).
// Hidden when fewer than 2 path segments (homepage, top-level group landings).
import Default from '@astrojs/starlight/components/PageTitle.astro';
---
```

### S-2 — `FAIL:` prefix + recovery hint on every error path

**Source:** `docs/scripts/verify-build.sh`, `docs/scripts/check-token-sync.sh`, `docs/scripts/verify-shell-layout.mjs`.

**Apply to:** `verify-build.sh` new assertions, `fetch-openapi.mjs` error paths, any future bash/JS gate.

**Convention:**
- Every failure line starts with `FAIL:` (capitalized).
- Where the recovery action isn't obvious from the error, add a `Hint:` line on the next line pointing at the fix.
- Exit codes: `1` for general failure (the dominant convention); graduated codes (2 = network, 3 = invalid input) acceptable when meaningful.

**Excerpt (verify-shell-layout.mjs lines 89-93):**
```javascript
console.error('FAIL: could not launch Playwright Chromium:', err.message);
console.error('       Hint: run `npx playwright install chromium` from the repo root.');
process.exit(1);
```

**Excerpt (verify-build.sh lines 9-11):**
```bash
echo "Asserting noindex meta present..."
grep -F 'name="robots"' dist/index.html | grep -F 'noindex' \
  || { echo "FAIL: noindex meta missing"; exit 1; }
```

### S-3 — Fenced code blocks use Expressive Code (no manual attributes)

**Source:** `docs/plugins/ec-pagefind-weight.mjs` + `docs/astro.config.mjs` lines 25-27.

**Apply to:** `auth.mdx`, `ogc.mdx`, the new `index.mdx`, `openapi/README.md`.

**Convention:**
- Every fenced block in MDX is rendered by Expressive Code; the plugin auto-adds `data-pagefind-weight="0.1"`.
- DO NOT manually add HTML attributes to MDX code blocks.
- Use language tags consistently: `bash` for curl/shell, `javascript` for Node, `python` for pystac-client, `http` for raw request/response, plain ` ``` ` for client-tool walkthroughs (QGIS step lists).
- DO NOT use ` ```sh ` for curl examples (the docs-root README uses `sh` for npm/cd recipes; the docs-content convention is `bash`).

**Wiring excerpt (astro.config.mjs lines 25-27):**
```javascript
expressiveCode: {
  plugins: [pluginPagefindWeight()],
},
```

### S-4 — All paths inside `astro.config.mjs` are repo-relative `./...`

**Source:** `docs/astro.config.mjs` line 5 (`./plugins/ec-pagefind-weight.mjs`), lines 14, 31-32 (`./src/styles/custom.css`, `./src/components/DocsHeader.astro`, `./src/components/Breadcrumbs.astro`).

**Apply to:** the new `routeMiddleware: ['./src/middleware/pagefind-exclude.ts']`, the new `schema: './src/content/openapi/geolens.json'`.

**Convention:** leading `./` is mandatory; bare `src/...` will fail at runtime in Astro 6.

**Excerpt (astro.config.mjs lines 30-33):**
```javascript
components: {
  Header: './src/components/DocsHeader.astro',
  PageTitle: './src/components/Breadcrumbs.astro',
},
```

### S-5 — Frontmatter shape for every new MDX content page

**Source:** `docs/src/content/docs/index.mdx` (lines 1-5).

**Apply to:** the new `guides/api/index.mdx`, `guides/api/auth.mdx`, `guides/api/ogc.mdx`.

**Convention:**
- `title:` (required — drives Starlight `<h1>`; do NOT also write `# Title` in body).
- `description:` (one sentence; emits `<meta name="description">`).
- `template: doc` (default — explicit declaration acceptable but not required).
- DO NOT add custom frontmatter keys unrecognised by `docsSchema()` (registered in `src/content.config.ts`) — they will fail `astro check`.

**Excerpt:**
```mdx
---
title: GeoLens Documentation
description: Documentation for the GeoLens self-hosted GIS data catalog.
template: doc
---
```

### S-6 — Phase-fence comments inside long-lived config files

**Source:** `docs/scripts/verify-build.sh` line 38 (`# ─── Phase 224 assertions (BRAND-01/02, ...) ───`).

**Apply to:** `verify-build.sh` (new assertions get a Phase 225 fence).

**Convention:** when a file accumulates contributions from multiple phases, prefix each phase's block with a `# ─── Phase NNN assertions (REQ-IDs) ───` divider so future readers can see ownership.

---

## Files With No Strong Analog

| File | Why no analog | Substitute pattern source |
|------|---------------|---------------------------|
| `docs/src/middleware/pagefind-exclude.ts` | First-time use of Starlight `routeMiddleware` in this repo | RESEARCH.md §Pattern 2 (researcher-verified against cited Starlight docs) |
| `docs/src/content/openapi/geolens.json` | Script-emitted JSON — no convention to replicate (just OpenAPI 3.x spec output) | `JSON.stringify(spec, null, 2) + '\n'` per RESEARCH.md §Pattern 3 |
| `docs/src/content/openapi/README.md` | Only the docs-root `README.md` exists in-tree — small parity surface | `docs/README.md` (header shape, bullet metadata, ` ```sh ` recipes) |

## Files explicitly not modified (despite being mentioned)

| File | Reason |
|------|--------|
| `/Users/ishiland/Code/geolens/backend/app/api/main.py` (lines 270-354) | RESEARCH.md §Summary finding #1: no slug collision exists. Auto-generated tag pages live at `/guides/api/operations/tags/auth/`, hand-authored at `/guides/api/auth/`. The CONTEXT.md D-33 fallback rename (`Auth` → `User Authentication`) is **a phantom requirement** (Pitfall 1). Do not modify. |

## Metadata

**Analog search scope:**
- `/Users/ishiland/Code/getgeolens.com/docs/` (full subtree, all files except `node_modules/`, `dist/`, `.astro/`)
- `/Users/ishiland/Code/getgeolens.com/` (top-level — confirmed only `scripts/capture-screenshots.ts` matches `README.md`, irrelevant to this phase)
- `/Users/ishiland/Code/geolens/backend/app/api/main.py` (skim only — no modification)

**Files scanned:** 14 (all docs-subtree source files: 1 config, 1 manifest, 3 scripts, 1 plugin, 1 stylesheet, 2 components, 5 MDX content pages, 1 content config, 1 README).

**Key patterns identified (1-line summary each):**
- Phase 224 plugins are nested INSIDE `starlight({...})`, never at the top-level Astro `integrations:` array — applies directly to starlight-openapi + starlight-links-validator wiring.
- All build-time assertion scripts use `set -euo pipefail`, `cd "$(dirname "$0")/.."`, and `FAIL:` prefix on errors — verify-build.sh extension MUST follow.
- The Expressive Code `pluginPagefindWeight` is the established mechanism for code-block search-weight; new content pages use plain fenced blocks and inherit this automatically.
- Starlight `routeMiddleware` is a NEW PATTERN — pattern source is RESEARCH.md §Pattern 2 (cited Starlight docs), and the file's header comment must explain why route middleware was chosen over component overrides.

**Pattern extraction date:** 2026-04-25

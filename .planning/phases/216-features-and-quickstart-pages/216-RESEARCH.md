# Phase 216: Features and Quickstart Pages — Research

**Researched:** 2026-04-11
**Domain:** Astro 6 marketing pages, Playwright screenshot capture, GeoLens UI inventory, OGC conformance
**Confidence:** HIGH (code-verified), MEDIUM (Playwright/Astro API cross-check), noted where ASSUMED

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 (updated):** All capability previews use real screenshots via Playwright — no SVG mocks. Retrofit Phase 214 previews (SearchPreview, MapBuilderPreview, DatasetDetailPreview). 6 screenshots: search, map-builder, data-ingestion, raster-vrt, ai-chat, rbac.
- **D-02:** /features = 6 zig-zag capability stripes + 7th OGC section. Alternating `var(--background)` / `var(--surface-0)` stripe backgrounds.
- **D-03:** Capability order: search → map builder → data ingestion → raster/VRT → AI chat → RBAC.
- **D-04:** OGC section = two-column list by API family. No external links to spec URIs. Conformance class names only (no raw URIs in copy).
- **D-05:** Quickstart depth = Standard (prereqs + core flow + troubleshooting, 7 steps).
- **D-06 (updated):** QUICK-03 "What you'll see" = prose + real screenshot via same Playwright workflow.
- **D-07:** Nav amended: desktop (sm+) shows Features + Quickstart + GitHub; mobile shows Logo + GitHub only.
- **D-08:** All preview components live in `components/previews/`.
- **D-09:** Quickstart code blocks = plain `<pre><code>`, no JS copy button. Zero-JS constraint.
- **D-10:** Playwright capture script at `getgeolens.com/scripts/capture-screenshots.ts`, writes to `src/assets/screenshots/`.
- **D-11:** Screenshots render inside existing `BrowserFrame.astro`. Callsite API (`<SearchPreview />` etc.) unchanged.
- **D-12:** Astro `<Picture>` from `astro:assets`, AVIF + WebP + PNG fallback. Source PNGs in `src/assets/screenshots/`.
- **D-13:** Filename map: `search.png`, `map-builder.png`, `data-ingestion.png`, `raster-vrt.png`, `ai-chat.png`, `rbac.png`, `quickstart-outcome.png`.

### Claude's Discretion

- Whether to extract `FeatureStripe.astro` or inline the zig-zag pattern 6 times.
- Whether to extract `CodeBlock.astro` for quickstart code blocks.
- Whether `quickstart-outcome.png` aliases `search.png` or is a distinct capture.
- `loading="eager"` vs `loading="lazy"` for first-above-fold screenshot.
- Whether QUICK-03 screenshot uses BrowserFrame or unframed treatment.

### Deferred Ideas (OUT OF SCOPE)

- CI visual-regression gate on screenshots.
- Mobile-specific screenshot captures.
- Docs site `/docs`.
- Blog `/blog`.
- Enterprise contact form.
- Per-capability deep-dive pages.
- Syntax highlighting on quickstart code blocks (below D-09 locked decision, but see Q11 for the build-time option that IS allowed).
- Troubleshooting as its own page.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FEAT-01 | Capability sections: search, map builder, data ingestion, raster/VRT, AI chat, RBAC | All 6 UIs confirmed to exist in GeoLens 1.0.0 with caveats (see Q2) |
| FEAT-02 | Each section has description, key points, and stylized product preview | Screenshot workflow researched (Q1–Q7); BrowserFrame + `<Picture>` pattern confirmed |
| FEAT-03 | OGC API compliance section with supported conformance classes | Verified against `backend/app/ogc/router.py` (see Q8) |
| QUICK-01 | Step-by-step guide from zero to running GeoLens via docker compose | docker-compose.yml and .env.example audited; step structure confirmed (see Q9) |
| QUICK-02 | Copyable code blocks with env setup, docker compose commands, first-login | zero-JS `<pre><code>` approach confirmed; Shiki `<Code>` build-time option verified (see Q11) |
| QUICK-03 | Expected outcome description with what user sees after completing quickstart | Screenshot of catalog search UI is the right choice (see Q6/D-06 answer) |
</phase_requirements>

---

## Summary

Phase 216 builds two new pages (`/features` and `/quickstart`) in the `getgeolens.com` Astro repo and retrofits three Phase 214 SVG preview components to use real screenshots. The primary complexity is the screenshot capture workflow (Plan 01/02) which must precede all component retrofit and build work.

All 6 capability UIs exist in GeoLens 1.0.0, but two require special handling: the AI Chat capability lives inside the Map Builder page (no standalone `/chat` route) and requires an LLM API key to be enabled; the RBAC admin page (`/admin/users`) requires an admin session. The capture script must handle auth and conditional AI availability.

Astro 6.1.3's `<Picture>` component from `astro:assets` is the correct image optimization path. Images MUST be imported (not string-referenced) from `src/assets/screenshots/` for build-time AVIF/WebP derivation. The `<Code>` component from `astro:components` provides build-time Shiki syntax highlighting with zero client-side JS — this is allowed under D-09's "plain `<pre><code>`" constraint if the planner chooses to use it.

**Primary recommendation:** Plan 01 (Playwright capture script) and Plan 02 (run captures, commit PNGs) must gate all subsequent plans. The capture script needs to handle: (a) auth login for admin captures, (b) AI availability detection or a flag to skip AI chat capture, (c) seeded demo data for meaningful screenshots.

---

## Q1: Running GeoLens for Capture — How the Capture Script Gets a Live Instance

**Answer:** The capture script assumes a running GeoLens instance at `http://localhost:8080` (default dev URL). The user must run `docker compose up -d` in the geolens monorepo before executing `npm run capture` in getgeolens.com.

**Seeding for screenshot content:**

Phase 218 (Demo Themed Collections) ships a complete seeder at `geolens/scripts/demo/seed-thematic-demo.py`. This seeder creates:
- Theme 1 "Planet Earth (2025 Snapshot)": NE 10m vector layers + raster COGs (GEBCO bathymetry, NE shaded relief)
- Theme 2: Urban/population data (vectors)
- Theme 3: additional thematic collections

The Phase 218 seeder is the recommended seed for screenshots because:
1. It produces real, content-rich maps with multiple layers (needed for the Map Builder screenshot)
2. It includes raster COGs (needed for the Raster/VRT screenshot)
3. It is already version-controlled in the monorepo

**Quickstart workflow for the capture operator:**
```bash
# In geolens monorepo
cp .env.example .env
# Set ANTHROPIC_API_KEY (or OPENAI_API_KEY) for AI chat capture
docker compose up -d --build
# Run Phase 218 seeder to populate content
pip install httpx
python scripts/demo/seed-thematic-demo.py --base-url http://localhost:8080

# In getgeolens.com repo
npm run capture
```

The capture script README (to be created in `scripts/README.md`) must document this cross-repo dependency clearly. [VERIFIED: docker-compose.yml reviewed, Phase 218 seeder confirmed at scripts/demo/seed-thematic-demo.py]

**Fallback if seeder is unavailable:** The `e2e/fixtures/sample.geojson` at `/Users/ishiland/Code/geolens/e2e/fixtures/sample.geojson` is the e2e test fixture. It's minimal (not production-quality for marketing screenshots) but serves as a fallback upload for the data ingestion screenshot. The `e2e/fixtures/sample-nonspatial.csv` provides table data. [VERIFIED: ls e2e/fixtures/]

---

## Q2: UI State Availability Per Capability

**Verdict per capability:**

| # | Capability | Target Route | UI Exists? | Notes |
|---|-----------|--------------|------------|-------|
| 1 | Search | `/` (index route, SearchPage) | YES — full UI | Healthy with seeded data. URL in BrowserFrame should read `app.geolens.io/search` |
| 2 | Map Builder | `/maps/:id` (via MapViewerGate → MapBuilderPage for editors) | YES — full UI | Requires logged-in editor session AND a saved map. Use a Phase 218 seeded map. URL: `app.geolens.io/maps/{id}` |
| 3 | Data Ingestion | `/datasets/:id` (DatasetPage) | YES — full UI | Works with any ingested dataset. Shows metadata, tabs (overview/metadata/data/structure/sources), extent map. URL: `app.geolens.io/datasets/{id}` |
| 4 | Raster/VRT | `/datasets/:id` (same DatasetPage, raster record) | YES — full UI | Same page as Data Ingestion, different content. Phase 218 seeds GEBCO COG raster and NE shaded relief COG. The VRT create dialog is also accessible here. URL: `app.geolens.io/datasets/{raster-id}` |
| 5 | AI Chat | Inside `/maps/:id` (ChatPanel.tsx, lazy-loaded via MapBuilderPage) | **CONDITIONAL** | No standalone `/chat` route exists. The AI chat is a panel within the Map Builder — accessed via a chat icon button. Only renders when AI is enabled in admin settings AND an API key (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`) is configured. The ChatPanel component exists and is production-quality. |
| 6 | RBAC | `/admin/users` (AdminUsersPage → UserList) | YES — full UI | Requires admin session. Shows paginated user table with approve/reject/deactivate actions. Populated with at least the admin user + any seeded users. |

[VERIFIED: frontend/src/App.tsx routes, frontend/src/pages/MapViewerGate.tsx, frontend/src/pages/admin/AdminUsersPage.tsx, frontend/src/components/builder/ChatPanel.tsx]

### Gap: AI Chat (capability 5)

**The gap:** There is no standalone AI chat page. The chat UI is a slide-out panel within the Map Builder, only shown when:
1. An LLM API key is configured
2. AI is enabled in admin settings (`SettingsAITab.tsx` controls this)

**Capture options for Plan 01:**
- (A) **Recommended:** Capture the Map Builder page with the chat panel open. This IS the real chat UI. Set `ANTHROPIC_API_KEY` in `.env`, open the panel in the seeded map, compose a query like "Show only aquifers in California", and screenshot the panel with a visible response. The capture script logs in as admin and navigates to `/maps/:id?chat=open` (or scripted click).
- (B) **Fallback:** If AI key is unavailable, screenshot the Map Builder with the chat panel visible but empty (the input placeholder shows "Ask anything about your map data..."). The panel itself is still a real UI.
- (C) **Skip:** If the operator has not configured an AI key, skip the `ai-chat.png` capture with a warning. The capture script must handle this gracefully (per D-10: "skip with warning, not fail").

**Recommendation for planner:** Plan 01 should detect AI availability by checking admin settings API before attempting the chat screenshot. If unavailable, log a warning and write a placeholder or skip. Document in script README that AI chat screenshot requires `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` in `.env`.

**User decision needed (per D-01 fallback logic):** If the user does not want to require an API key to regenerate screenshots, option (B) (empty panel) is viable for marketing purposes. The ChatPanel itself is still "real UI" even without a conversation. This is a user decision, not a researcher decision.

### Gap: Map Builder route mismatch in CONTEXT.md

**CONTEXT.md D-01 lists the Map Builder URL as `app.geolens.io/builder/{id}`** — this is INCORRECT. The actual route is `/maps/:id` (routed via `MapViewerGate`, which shows `MapBuilderPage` for authenticated editors). The BrowserFrame `url` prop should read `app.geolens.io/maps/{id}` (or the seeded map's specific ID). [VERIFIED: App.tsx route `/maps/:id`]

---

## Q3: Playwright Setup in getgeolens.com

**Current state:**
- `getgeolens.com` has NO Playwright installed. `node_modules/playwright` does not exist. [VERIFIED: `ls node_modules | grep playwright` returned empty]
- The geolens monorepo has Playwright 1.58.2 at `/Users/ishiland/Code/geolens/node_modules/playwright`. [VERIFIED: playwright/package.json version field]
- The monorepo uses Playwright for e2e tests under `geolens/e2e/` with `playwright.config.ts`.

**Install path for getgeolens.com:**

```bash
# In getgeolens.com
npm install --save-dev playwright @playwright/test
npx playwright install chromium
```

Alternatively, use `playwright` (headful API only) without `@playwright/test` since the capture script is NOT a test suite — it's a script. `playwright` package alone is sufficient.

**Minimum install (script-only, no test runner):**
```bash
npm install --save-dev playwright
npx playwright install chromium
```

The script uses `chromium.launch()` directly (not `test()`). Chromium is the only browser needed for screenshot capture.

**Cross-repo sharing consideration:** The monorepo's browser binaries are installed at `~/.cache/ms-playwright/` (or OS equivalent). They are shared globally — `getgeolens.com`'s Playwright install will find the same cached binaries if the version matches. However, installing separately in `getgeolens.com` is safer and decouples the capture script from the monorepo's version. [VERIFIED: geolens monorepo playwright.config.ts, package.json]

**npm script entry point:**
```json
{
  "scripts": {
    "capture": "npx tsx scripts/capture-screenshots.ts"
  }
}
```
Note: `tsx` needs to be installed for TypeScript execution. The getgeolens.com repo already has TypeScript (`"typescript": "^5.9.3"` in devDependencies). Add `tsx` as a devDependency:
```bash
npm install --save-dev tsx
```

[VERIFIED: getgeolens.com/package.json checked — no tsx currently installed]

---

## Q4: Astro `<Picture>` + `astro:assets` API in Astro 6.1.3

**Confirmed API** [VERIFIED: Astro 6.1.3 installed; docs confirmed at docs.astro.build/en/reference/modules/astro-assets/]

**Import:**
```typescript
import { Picture } from 'astro:assets';
```

**Required props:**
- `src` — imported image object (NOT a string path)
- `alt` — descriptive alt text (required by component, not optional)
- `formats` — array of `ImageOutputFormat` (e.g., `['avif', 'webp']`)

**Optional props relevant to this phase:**
- `fallbackFormat` — defaults to `'png'` for static images. Explicit `fallbackFormat="png"` is redundant but acceptable for clarity.
- `widths` — array of pixel widths for `<source srcset>` generation (e.g., `[448, 896]`)
- `sizes` — media query for responsive `sizes` attribute (e.g., `"(max-width: 640px) 100vw, 448px"`)
- `loading` — `"lazy"` (default) or `"eager"`
- `pictureAttributes` — HTML attributes for the outer `<picture>` element

**No `width`/`height` required for local images** — Astro infers dimensions automatically from imported local images. `width`/`height` are only required for `public/` images or remote URLs.

**CRITICAL import pattern:**
```astro
---
import { Picture } from 'astro:assets';
import searchScreenshot from '../../assets/screenshots/search.png';
---

<Picture
  src={searchScreenshot}
  formats={['avif', 'webp']}
  alt="GeoLens catalog search page showing 207 datasets with filter tabs and preview cards"
  widths={[448, 896]}
  sizes="(max-width: 640px) 100vw, 448px"
  loading="lazy"
/>
```

**The footgun:** Using a string path (`src="/screenshots/search.png"` or `src="../../assets/screenshots/search.png"`) bypasses Astro's optimization pipeline entirely. Only the import form triggers AVIF/WebP generation. [VERIFIED: docs.astro.build/en/guides/images/]

---

## Q5: `src/assets/` vs `public/` for Image Optimization

**Confirmed distinction** [VERIFIED: Astro docs + existing repo structure]

| Location | Astro optimization | Import form | Format conversion | Fingerprinted hash |
|----------|--------------------|-------------|-------------------|--------------------|
| `src/assets/screenshots/` | YES (build-time) | `import img from '../../assets/screenshots/search.png'` | AVIF + WebP generated | YES — `_astro/search.xyz.avif` |
| `public/screenshots/` | NO | `src="/screenshots/search.png"` (string) | None — served as-is | NO |

**Current state:** `getgeolens.com/src/assets/` exists and contains only `fonts/`. The `screenshots/` subdirectory does not yet exist and must be created. [VERIFIED: ls src/assets/]

**Why `public/` is wrong for this use case:** The capture script (D-10) writes PNGs as source-of-truth. If a developer accidentally writes to `public/screenshots/` and references them with string paths, the build will serve unoptimized PNGs. Six 1600×1000 PNG screenshots at ~300-500KB each = ~1.8-3MB uncompressed page payload. Astro gives no warning — it silently skips optimization.

**Pitfall for executor:** The `<Picture src={...}>` component accepts a string `src` attribute at runtime (it renders fine) but produces no optimization. Only the TypeScript import path triggers the image optimization plugin. The type system does help here — `src` expects `ImageMetadata`, not a string, so a TypeScript error will surface if the wrong form is used.

---

## Q6: Viewport Dimensions for Each Capability Screenshot

**Analysis per capability:**

| # | Capability | Recommended Viewport | Rationale |
|---|-----------|----------------------|-----------|
| 1 | Search | 1600×900 | SearchPage is a card grid — 900px height captures the filter bar + 3-4 result cards. 1000px adds empty space. |
| 2 | Map Builder | 1600×900 | MapBuilderPage is a split layout (layer panel left, map right). 900px fills the screen without unnecessary vertical padding. Full map canvas visible. |
| 3 | Data Ingestion | 1600×800 | DatasetPage tabs are above the fold at 800px. The "overview" tab shows metadata + extent thumbnail — compact enough for 800px. |
| 4 | Raster/VRT | 1600×800 | Same DatasetPage. Raster record shows file info, type badge "Raster", and the map extent thumbnail. 800px is sufficient. |
| 5 | AI Chat | 1600×900 | Map Builder with chat panel open is a 3-pane layout. 900px shows the chat input + at least one exchange in the history. A taller viewport doesn't add value. |
| 6 | RBAC | 1600×800 | AdminUsersPage is a card with a table (`UserList`). 800px captures the table header + 3-4 user rows. The table is the evidence. |
| QUICK-03 | Quickstart outcome | 1600×900 | Reuse the Search screenshot (same capture, same file). The search page IS what you see after completing the quickstart. |

**D-10 specifies 1600×1000 as a starting point.** Research finding: 900 or 800 for most capabilities is better because: (a) shorter page = less blank space in the BrowserFrame preview, and (b) a 16:9 aspect ratio at 1600×900 maps to a more natural browser viewport than 1600:1000 (which reads slightly tall for a general screenshot).

**Single vs multiple viewports:** Use a single utility function in the capture script that accepts `{ width, height }` per capability. Defaults all to 1600×900, with 1600×800 for dataset detail pages. This is still "effectively a single viewport" — the variation is minor.

**BrowserFrame rendering:** The captured screenshots are down-scaled to fit inside the ~448px-wide BrowserFrame. A 1600×900 PNG at 448px display width gives ~3.57× down-scaling, which is excellent detail. Going to 1600×1000 is fine but wastes ~11% vertical space.

---

## Q7: Lighthouse Impact Projection — /features Page Image Payload

**Transfer size estimate per screenshot (AVIF, 1600px source):**

| PNG source size | AVIF typical compression | WebP fallback | PNG fallback |
|-----------------|--------------------------|---------------|--------------|
| 300-600KB | 30-60KB | 60-100KB | 300-600KB |

Browser requests AVIF only (Chrome/Firefox/Safari 16+ all support AVIF). Modern browsers will download the first `<source>` with AVIF format.

**Per /features page (6 screenshots):**
- AVIF transfer per image: ~30-60KB
- Total AVIF transfer: ~180-360KB for 6 screenshots
- Plus HTML/CSS/fonts: ~50-80KB
- Estimated total page weight: ~230-440KB

This is well within marketing site norms. Lighthouse Performance score impact should be minimal if `loading="lazy"` is used on all non-above-fold screenshots. The first screenshot (Search capability, section 1) should use `loading="eager"` since it may be visible near-immediately on load.

**AVIF size caveat:** These are estimates based on typical screenshot content (mostly UI with flat colors). Screenshots with maps (Map Builder, Raster/VRT) may compress less efficiently due to continuous-tone content. Expect those to land at the higher end (~50-80KB AVIF). [ASSUMED: compression ratios based on general AVIF knowledge; actual sizes only known after capture]

---

## Q8: OGC Conformance Class List — What the Backend Actually Advertises

**Verified from `backend/app/ogc/router.py` lines 131-151:** [VERIFIED: code read]

The `/conformance` endpoint returns exactly these URIs:

```
OGC API Common
  core:        http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/core
  landing-page: http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/landing-page
  json:        http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/json
  oas30:       http://www.opengis.net/spec/ogcapi-common-1/1.0/conf/oas30

OGC API Features Part 1 (Core)
  core:        http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core
  geojson:     http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson
  oas30:       http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/oas30

OGC API Features Part 3 (Filtering / CQL2)
  filter:         http://www.opengis.net/spec/ogcapi-features-3/1.0/conf/filter
  features-filter: http://www.opengis.net/spec/ogcapi-features-3/1.0/conf/features-filter
  cql2-text:      http://www.opengis.net/spec/cql2/1.0/conf/cql2-text
  cql2-json:      http://www.opengis.net/spec/cql2/1.0/conf/cql2-json
  basic-cql2:     http://www.opengis.net/spec/cql2/1.0/conf/basic-cql2

OGC API Records Part 1
  record-core:                http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/record-core
  record-core-query-parameters: http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/record-core-query-parameters
  json:                       http://www.opengis.net/spec/ogcapi-records-1/1.0/conf/json
```

**Notable absence:** No OGC API Tiles, Maps, or Processes conformance URIs are declared in the `/conformance` endpoint. The CONTEXT.md D-04 preliminary list included "Tiles (Core, Datasets, Styles)" and "Maps (Core, BBox)" — these are NOT advertised at `/conformance`. They may be served (Titiler provides raster tile serving) but are not formally declared.

**What this means for FEAT-03 copy:**

The D-04 section format must be revised to match what's actually advertised. The copy should reflect:

```
OGC API Features Page (two-col):
Left: Features API — Read and filter geospatial features by attribute, geometry, and CQL2 expressions.
Right: Core · GeoJSON · OpenAPI 3.0 · CQL2 Text · CQL2 JSON · Basic CQL2 · Features Filter

Left: Records API — Discover datasets and records via OGC-standard catalog queries.
Right: Record Core · Query Parameters · JSON · (sorting/text-search not declared, omit)
```

Do NOT list Tiles, Maps, or Processes in the OGC section — they are not declared in the `/conformance` response. The marketing claim must be accurate to avoid procurement disputes.

**D-04 correction for planner:** The planner must adjust the FEAT-03 section from the preliminary list in D-04 to the verified list above. Two API families (Features + Records), not four or five.

---

## Q9: Quickstart Env Var Minimum Set

**Verified from `.env.example` and `docker-compose.yml`:** [VERIFIED: both files read in full]

**Absolute minimum for `docker compose up` to succeed:**

```bash
# Only vars without defaults that must be set:
POSTGRES_DB=geolens
POSTGRES_USER=geolens
POSTGRES_PASSWORD=geolens
JWT_SECRET_KEY=dev-only-change-me-in-production
GEOLENS_ADMIN_USERNAME=admin
GEOLENS_ADMIN_PASSWORD=admin
```

All other vars have defaults defined via `${VAR:-default}` syntax in docker-compose.yml. `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` technically have `.env.example` defaults but the compose file needs them present in `.env`.

**Port defaults (important for quickstart):**
- Frontend: `http://localhost:8080` (FRONTEND_PORT defaults to 8080, maps to container port 5173)
- API: `http://localhost:8001` (API_PORT defaults to 8001, maps to container port 8000) — NOTE: The API is exposed on 8001, not 8000, when running via docker compose
- Database: `localhost:5434` (DB_PORT defaults to 5434, NOT the standard 5432)

**D-05 prereq port list needs correction:** D-05 lists "open ports 5432/6379/8000/8080". The actual ports used locally are 5434, 8001, and 8080 (from `.env.example` defaults). Redis/Valkey is not in the default `docker-compose.yml` (it's in the cloud-dev profile). The quickstart prereqs should say:
- Open ports: 5434 (PostgreSQL), 8001 (API), 8080 (Frontend)
- Redis is NOT required for the default dev setup

**For production (quickstart note):** The `.env.example` comments flag three vars with `[CHANGE IN PRODUCTION]`: `POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, and `GEOLENS_ADMIN_PASSWORD`. The quickstart should highlight these clearly.

**Copy `.env.example` to `.env` step** is all that's needed — defaults work out of the box for dev. This is documented in the file header: "Works out of the box for local development."

---

## Q10: Sample Dataset for Quickstart Step 5

**Existing canonical samples in the repo:** [VERIFIED: ls e2e/fixtures/]

- `geolens/e2e/fixtures/sample.geojson` — a GeoJSON file with basic feature data (used in e2e tests). This is minimal but is already in the repo.
- `geolens/e2e/fixtures/sample-nonspatial.csv` — CSV with non-spatial data.

**Assessment:** The `sample.geojson` fixture is technically valid for a first-upload demo but it's a test fixture, not a polished sample. It may have minimal or synthetic features.

**Recommended approach:** Link to Natural Earth directly in the quickstart. Use:

```
https://nacis.org/initiatives/natural-earth/ → ne_110m_admin_0_countries.zip
```

Direct download from the Natural Earth CDN (same CDN used by the Phase 218 seeder):
```
https://naturalearth.s3.amazonaws.com/110m_cultural/ne_110m_admin_0_countries.zip
```

1:110m scale countries polygon is small (~100KB), globally recognizable, requires no auth, and demonstrates the multi-feature vector ingestion well. It is public domain.

**Why not the e2e fixture:** The e2e fixture is not documented as a user-facing sample. Linking to Natural Earth is standard practice, immediately recognizable to GIS professionals, and sets a good "this is real data" tone.

**Planner note:** A sentence like "Download the Natural Earth 1:110m countries GeoJSON (~100KB)" with a direct URL is the Step 5 happy path. No file needs to be committed to the getgeolens.com repo.

---

## Q11: Astro Syntax Highlighting with Shiki — Zero-JS Constraint

**Verified:** The `<Code>` component from `astro:components` runs exclusively at build time, produces no client-side JavaScript, and works in `.astro` files (not just `.mdx`). [VERIFIED: docs.astro.build/en/reference/components-reference/#code-]

**Import and usage:**
```astro
---
import { Code } from 'astro:components';
---

<Code code={`git clone https://github.com/geolens-io/geolens.git`} lang="bash" />
```

**Is it compatible with the zero-JS constraint?** Yes. The `<Code>` component renders static HTML with inline styles at build time. No `<script>` tags, no `client:load` directive, no runtime JS.

**Is it compatible with D-09?** D-09 says "plain `<pre><code>` elements" — the `<Code>` component outputs `<code>` wrapped in a styled container. Strictly speaking it IS a `<pre>`-equivalent. D-09 was written before the researcher confirmed that `<Code>` is zero-JS. The planner may treat `<Code>` as acceptable under D-09's intent ("no JS copy button" was the core concern) OR may stay with raw `<pre><code>` for simplicity.

**Recommendation for planner:** Use `<Code>` from `astro:components` if syntax highlighting for bash commands is desired — it satisfies the zero-JS constraint completely. If plain styling is preferred, raw `<pre><code>` is fine too. Either way, D-09 is satisfied.

**Note:** The `<Code>` component does NOT inherit `shikiConfig` from `astro.config.mjs` markdown settings — configuration must be passed as props (`theme`, `lang`). The Shiki `github-light` theme matches the light-only site.

---

## Q12: Active-Link Detection in Astro — `aria-current="page"` Pattern

**Verified idiomatic pattern** [VERIFIED: docs.astro.build/en/reference/api-reference/#url]

In `Nav.astro`, use `Astro.url.pathname` to compare the current path:

```astro
---
const { pathname } = Astro.url;
---

<a
  href="/features"
  aria-current={pathname === '/features' || pathname.startsWith('/features/') ? 'page' : undefined}
  style:list={[
    { 'color: var(--primary-700)': pathname === '/features' },
    // or use class:list for Tailwind
  ]}
>
  Features
</a>
```

**Notes for Nav.astro amendment (D-07):**
- `Astro.url` is available in any `.astro` component's frontmatter — no special import needed.
- `aria-current={undefined}` vs `aria-current={false}` — use `undefined` to omit the attribute entirely on non-active links. Passing `false` explicitly sets `aria-current="false"` which is valid but verbose.
- `startsWith('/quickstart/')` pattern handles sub-routes if they are ever added.
- The homepage (`/`) requires exact match: `pathname === '/'`.

**Recommended Nav structure after amendment:**
```astro
---
import { GEOLENS_GITHUB_URL } from '../../lib/links';
const { pathname } = Astro.url;
const isFeatures = pathname === '/features' || pathname.startsWith('/features/');
const isQuickstart = pathname === '/quickstart' || pathname.startsWith('/quickstart/');
---

<!-- Desktop subnav links (sm+) -->
<a href="/features" aria-current={isFeatures ? 'page' : undefined} class="hidden sm:block ...">Features</a>
<a href="/quickstart" aria-current={isQuickstart ? 'page' : undefined} class="hidden sm:block ...">Quickstart</a>
```

---

## Standard Stack

### Core (getgeolens.com repo)

| Library | Version | Purpose | Status |
|---------|---------|---------|--------|
| astro | 6.1.3 | Static site framework | Already installed [VERIFIED] |
| tailwindcss | 4.2.2 | Utility-first CSS | Already installed [VERIFIED] |
| @tailwindcss/vite | 4.2.2 | Vite plugin for Tailwind 4 | Already installed [VERIFIED] |
| @astrojs/sitemap | 3.7.2 | Sitemap generation | Already installed [VERIFIED] |

### New Additions for This Phase

| Library | Version | Purpose | Install |
|---------|---------|---------|---------|
| playwright | ^1.58 | Browser automation for capture script | `npm install --save-dev playwright` |
| tsx | ^4.x | TypeScript execution for capture script | `npm install --save-dev tsx` |

**Note:** No new Astro integrations needed. `astro:assets` (`<Picture>`) and `astro:components` (`<Code>`) are built-in to Astro 6 — no extra install required.

**Version check:** Playwright 1.58.2 is installed in the geolens monorepo. Using the same major version in getgeolens.com ensures browser binary cache compatibility.

---

## Architecture Patterns

### Recommended Project Structure (additions this phase)

```
getgeolens.com/
├── scripts/
│   ├── capture-screenshots.ts     # NEW: Playwright capture script
│   └── README.md                  # NEW: Capture workflow documentation
├── src/
│   ├── assets/
│   │   └── screenshots/           # NEW subdirectory
│   │       ├── search.png
│   │       ├── map-builder.png
│   │       ├── data-ingestion.png
│   │       ├── raster-vrt.png
│   │       ├── ai-chat.png
│   │       ├── rbac.png
│   │       └── quickstart-outcome.png
│   ├── components/
│   │   ├── previews/
│   │   │   ├── BrowserFrame.astro    (no change)
│   │   │   ├── SearchPreview.astro   (RETROFIT: SVG → Picture)
│   │   │   ├── MapBuilderPreview.astro (RETROFIT: SVG → Picture)
│   │   │   ├── DatasetDetailPreview.astro (RETROFIT: SVG → Picture)
│   │   │   ├── RasterVrtPreview.astro  (NEW)
│   │   │   ├── AiChatPreview.astro     (NEW)
│   │   │   └── RbacPreview.astro       (NEW)
│   │   ├── features/
│   │   │   └── FeatureStripe.astro   (NEW — if planner extracts it)
│   │   ├── quickstart/
│   │   │   └── CodeBlock.astro       (NEW — if planner extracts it)
│   │   └── layout/
│   │       └── Nav.astro             (MODIFY: add subnav links)
│   └── pages/
│       ├── features/
│       │   └── index.astro           (NEW)
│       └── quickstart/
│           └── index.astro           (NEW)
```

### Pattern 1: Preview Component Retrofit (SVG → Picture)

The internal SVG markup of the three existing preview components is replaced entirely. The external API (component name, no props) stays identical.

```astro
---
// src/components/previews/SearchPreview.astro — AFTER retrofit
import BrowserFrame from './BrowserFrame.astro';
import { Picture } from 'astro:assets';
import searchScreenshot from '../../assets/screenshots/search.png';
---

<BrowserFrame url="app.geolens.io/search" class="w-full">
  <Picture
    src={searchScreenshot}
    formats={['avif', 'webp']}
    alt="GeoLens catalog search page showing dataset cards with filter tabs for vector, raster, and table types"
    widths={[448, 896]}
    sizes="(max-width: 640px) 100vw, 448px"
    loading="lazy"
    class="w-full block"
  />
</BrowserFrame>
```

**The `class="w-full block"` on `<Picture>`:** The `<Picture>` component renders a `<picture>` element wrapping an `<img>`. Without `display: block`, the img has inline bottom-gap whitespace (typical inline element issue). Adding `class="w-full block"` on the `<Picture>` applies to the generated `<img>` element, preventing the gap.

**The `min-height` removal:** The existing preview components use `min-height` on the slot content (e.g., `DatasetDetailPreview` has `min-height: 220px` and `MapBuilderPreview` has `min-height: 340px`). After the retrofit, the image dictates its own aspect ratio — remove the `min-height` from the BrowserFrame slot container. The `<Picture>` component automatically adds `width`/`height` attributes to the `<img>` for CLS prevention.

**BrowserFrame `overflow: hidden`:** The `browser-frame-inner` div has `overflow-hidden` via Tailwind. The `<Picture>` / `<img>` renders at `w-full`, so it fills the frame width. Border-radius on `browser-frame-inner` is `rounded-xl`. The image clips to the rounded corner cleanly — no additional overflow handling needed. The tilt transform is on `browser-frame-inner`, not on the slot content, so the image transforms correctly. [VERIFIED: BrowserFrame.astro reviewed in full]

### Pattern 2: New Preview Components (Net-New)

New preview components follow the exact same shape as retrofitted ones:

```astro
---
// src/components/previews/RasterVrtPreview.astro
import BrowserFrame from './BrowserFrame.astro';
import { Picture } from 'astro:assets';
import screenshot from '../../assets/screenshots/raster-vrt.png';
---

<BrowserFrame url="app.geolens.io/datasets/{raster-id}" class="w-full">
  <Picture
    src={screenshot}
    formats={['avif', 'webp']}
    alt="GeoLens dataset detail page for a GEBCO raster dataset showing bathymetry layer and raster metadata"
    widths={[448, 896]}
    sizes="(max-width: 640px) 100vw, 448px"
    loading="lazy"
    class="w-full block"
  />
</BrowserFrame>
```

### Pattern 3: FeatureStripe Component (if extracted)

D-02 specifies the same 12-column zig-zag grid layout repeated 6 times. If extracted:

```astro
---
// src/components/features/FeatureStripe.astro
interface Props {
  eyebrow: string;
  heading: string;
  body: string;
  bullets?: string[];
  previewLeft?: boolean;  // false = copy left, preview right (default)
  background?: 'default' | 'surface';
}
const { eyebrow, heading, body, bullets = [], previewLeft = false, background = 'default' } = Astro.props;
---

<section
  class="w-full overflow-x-clip py-20 sm:py-28 px-4 sm:px-6 lg:px-8"
  style:list={[{ 'background-color': background === 'surface' ? 'var(--surface-0)' : 'var(--background)' }]}
>
  <div class="max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-12 gap-12 lg:gap-16 items-center">
    <!-- Copy column: order-1 or order-2 depending on previewLeft -->
    <div class:list={["lg:col-span-5", previewLeft ? "order-2" : "order-1"]}>
      <!-- eyebrow, h2, body, bullets -->
    </div>
    <!-- Preview column -->
    <div class:list={["lg:col-span-7 flex justify-center", previewLeft ? "order-1" : "order-2"]}>
      <div class="w-full max-w-md mx-auto">
        <slot />
      </div>
    </div>
  </div>
</section>
```

**Planner note:** The `slot` approach means the preview component is passed as slot content from `features/index.astro`. This keeps the FeatureStripe prop surface small.

### Pattern 4: Capture Script Shape

```typescript
// scripts/capture-screenshots.ts
import { chromium } from 'playwright';
import * as path from 'path';
import * as fs from 'fs';

const BASE_URL = process.env.GEOLENS_URL ?? 'http://localhost:8080';
const OUTPUT_DIR = path.resolve(__dirname, '../src/assets/screenshots');
const ADMIN_USER = process.env.GEOLENS_ADMIN_USERNAME ?? 'admin';
const ADMIN_PASS = process.env.GEOLENS_ADMIN_PASSWORD ?? 'admin';

interface CaptureTarget {
  name: string;
  filename: string;
  setup: (page: Page, context: BrowserContext) => Promise<void>;
  viewport?: { width: number; height: number };
}
```

Key design points:
1. Script reads `GEOLENS_URL`, `GEOLENS_ADMIN_USERNAME`, `GEOLENS_ADMIN_PASSWORD` from env (or defaults to dev values from `.env.example`).
2. Logs in once per session (cookies/storage shared across captures).
3. Iterates a `captures` array, skips with `console.warn` if setup fails.
4. Writes to `src/assets/screenshots/{filename}` — fails loudly if directory doesn't exist.
5. Does NOT import Astro types or require the Astro dev server to be running.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Image format conversion | Custom AVIF/WebP pipeline | `astro:assets` `<Picture>` | Build-time, zero JS, automatic srcset |
| Screenshot capture | Manual browser opens + save-as | Playwright `page.screenshot()` | Reproducible, scriptable, version-controlled |
| Syntax highlighting | Custom tokenizer | `astro:components` `<Code>` | Build-time Shiki, zero JS, all popular languages |
| Active nav state | Custom URL parsing | `Astro.url.pathname` | Built-in, SSG-compatible, no JS needed |
| Image dimension inference | Manual width/height attributes | Astro imported local images | Auto-inferred, prevents CLS |

---

## Common Pitfalls

### Pitfall 1: Screenshots in `public/` Instead of `src/assets/`

**What goes wrong:** Capture script writes to `public/screenshots/`, components reference them with string paths. Astro builds successfully — no error — but ships unoptimized PNGs. /features page weighs 1.8-3MB instead of 180-360KB. Lighthouse performance regression.

**Why it happens:** The `public/` directory is intuitive ("put static files here") and string paths feel simpler than imports.

**How to avoid:** The capture script's output path MUST be `src/assets/screenshots/` (hardcoded, not configurable). Add a comment at the top of the script: "Do NOT change OUTPUT_DIR to public/ — Astro image optimization requires src/assets/". The `<Picture>` TypeScript type will also catch string path misuse.

**Warning signs:** Build output shows PNG files in `_astro/` without `.avif` / `.webp` companions. Check `dist/_astro/` after build.

### Pitfall 2: `class` Applied to `<Picture>` Goes to `<img>`, Not `<picture>`

**What goes wrong:** Applying `class="w-full"` to `<Picture>` targets the `<img>` element (correct for sizing). If you need to style the `<picture>` wrapper element, use `pictureAttributes={{ class: "..." }}` instead.

**How to avoid:** Always use `pictureAttributes` for `<picture>`-level styling. Use `class` on `<Picture>` for `<img>`-level styling.

### Pitfall 3: BrowserFrame `aria-hidden` Applied to Entire Preview Component

**What goes wrong:** BrowserFrame.astro has `aria-hidden="true"` on its outer div. This is correct — screenshots are decorative. If a new preview component wraps BrowserFrame in another container that somehow loses `aria-hidden`, screen readers announce the image alt text twice or not at all.

**How to avoid:** Verify that each preview component's `<BrowserFrame>` is the outermost element (no additional wrapper div). The BrowserFrame propagates `aria-hidden` correctly as-is. [VERIFIED: BrowserFrame.astro reviewed]

### Pitfall 4: Min-Height on BrowserFrame Slot Content Not Removed After Retrofit

**What goes wrong:** The existing `MapBuilderPreview` and `DatasetDetailPreview` use `min-height` on inner divs to give the SVG mock its displayed height. After the `<Picture>` retrofit, these `min-height` rules cause blank space below the image (the image has its own natural aspect ratio, and the `min-height` forces the container taller).

**How to avoid:** During the retrofit, delete all `min-height` and `height` constraints from the slot content. The `<Picture>` / `<img>` with `width` + `height` attributes from Astro controls the aspect ratio.

### Pitfall 5: Map Builder Route Mismatch in Capture Script

**What goes wrong:** CONTEXT.md D-01 table lists the Map Builder URL as `app.geolens.io/builder/{id}`. The ACTUAL route is `/maps/:id`. Capture script navigates to `/builder/:id` and gets a 404 (falls through to NotFoundPage).

**How to avoid:** Use the actual App.tsx route: `/maps/:id`. The seeder creates maps with known IDs (or the capture script can query `GET /api/maps/` to get the first available map ID).

### Pitfall 6: AI Chat Screenshot Fails If No API Key

**What goes wrong:** Capture script navigates to the Map Builder, tries to open the ChatPanel, and either the button doesn't exist (AI disabled) or the panel opens with an error state.

**How to avoid:** The capture script should check `GET /api/admin/settings/ai` for AI availability before attempting the chat capture. If AI is disabled or no key is configured, skip with a console warning and do not write `ai-chat.png`. The executor should document in the PR that AI chat screenshot was captured with `ANTHROPIC_API_KEY` set.

### Pitfall 7: Capture Script Called From Wrong Directory

**What goes wrong:** The capture script uses relative paths (`../../assets/screenshots`) which resolve differently depending on CWD. If called as `npx tsx scripts/capture-screenshots.ts` from the repo root, `__dirname` resolves correctly to `scripts/`. If called from a different directory, paths break.

**How to avoid:** Use `path.resolve(__dirname, '../src/assets/screenshots')` in the script (path relative to the script file's location, not CWD). This is Node.js `__dirname`, which is always the directory containing the script.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| SVG mock previews (Phase 214) | Real screenshots via Playwright (Phase 216) | 2026-04-12 (D-01 pivot) | Higher marketing credibility; maintenance cost of re-capturing on UI changes |
| Inline transform in BrowserFrame (Phase 214) | Scoped CSS rule for transform (Phase 215-04) | 2026-04-11 | Mobile tilt reset now works correctly |
| `public/` for static assets | `src/assets/` for build-optimized images | Astro best practice | AVIF/WebP auto-generation, ~80% bandwidth savings |
| Tailwind @astrojs/tailwind (Tailwind 3) | @tailwindcss/vite (Tailwind 4) | Phase 212 | Direct Vite integration, no separate integration package |

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js | getgeolens.com dev scripts | ✓ | >=22.12.0 (engines field) | — |
| Playwright (getgeolens.com) | capture-screenshots.ts | ✗ | — | Install via npm (Plan 01) |
| Playwright browser (Chromium) | capture-screenshots.ts | ✓ (cached from monorepo) | 1.58.2 | `npx playwright install chromium` |
| tsx (TypeScript runner) | npm run capture | ✗ | — | Install via npm (Plan 01), OR convert script to .mjs |
| Docker Compose v2 | Running GeoLens for capture | ✓ (assumed — project uses it) | varies | [ASSUMED] |
| GeoLens running instance | Playwright capture | ✗ (must start manually) | — | User runs `docker compose up -d` |
| Phase 218 seeder | Meaningful screenshot content | ✓ | scripts/demo/seed-thematic-demo.py | Use e2e/fixtures/sample.geojson (minimal quality) |
| ANTHROPIC_API_KEY or OPENAI_API_KEY | AI chat screenshot | ✗ (not required by default) | — | Skip ai-chat capture with warning |

**Missing dependencies with no fallback:**
- None — all blockers have an install path or documented skip behavior.

**Missing dependencies with workaround:**
- Playwright in getgeolens.com → Plan 01 install step
- tsx → Plan 01 install step (or use `.mjs` + dynamic imports)
- Running GeoLens → documented in scripts/README.md as manual prerequisite
- AI API key → capture script skips gracefully

---

## Validation Architecture

> `workflow.nyquist_validation` is absent from `.planning/config.json` — treated as enabled.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | None currently in getgeolens.com (no test framework installed) |
| Config file | None |
| Quick run command | `npm run build && npm run check` (Astro type check + build verification) |
| Full suite command | `astro build` + grep verification of output HTML |

**Note:** The getgeolens.com repo has no unit/integration test setup. Validation is via Astro's own type checker (`astro check`) and build verification. The geolens monorepo has Playwright e2e tests but those test the GeoLens app, not the marketing site.

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | Notes |
|--------|----------|-----------|-------------------|-------|
| FEAT-01 | 6 capability sections exist on /features | Build verification | `grep -c 'section' dist/features/index.html` | Manual visual check needed |
| FEAT-02 | Each section has description + preview | Build verification | `grep '&lt;picture' dist/features/index.html` | Verifies Picture tags rendered |
| FEAT-03 | OGC section exists with conformance classes | Build verification | `grep 'OGC' dist/features/index.html` | |
| QUICK-01 | 7-step guide present on /quickstart | Build verification | `grep -c 'Step' dist/quickstart/index.html` | |
| QUICK-02 | Code blocks present | Build verification | `grep -c 'pre' dist/quickstart/index.html` | |
| QUICK-03 | Outcome section + screenshot | Build verification | `grep 'quickstart-outcome' dist/quickstart/index.html` | |

### Wave 0 Gaps

- No test framework needed — validation is via `npm run build` (exit 0) + `npm run check` (0 errors). No new test files required.

---

## Security Domain

> security_enforcement absent from config.json — treated as enabled.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Static site, no auth |
| V3 Session Management | No | No sessions |
| V4 Access Control | No | All content public |
| V5 Input Validation | No | No user input forms |
| V6 Cryptography | No | No cryptographic operations |

### Known Threat Patterns (Astro Static Site)

| Pattern | STRIDE | Mitigation |
|---------|--------|------------|
| External links without rel=noopener | Spoofing (tabnabbing) | All `target="_blank"` links need `rel="noopener noreferrer"` — already enforced in Phase 215 (nav GitHub link) |
| Inline JSON-LD with user-sourced content | Tampering | Not applicable — all JSON-LD is hardcoded, no user input |

**Security note for Nav changes:** Adding `<a href="/features">` and `<a href="/quickstart">` are internal links — no `target="_blank"`, no `rel` attribute needed. Only the GitHub link in the nav requires `rel="noopener noreferrer"`.

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | AVIF transfer size ~30-60KB per screenshot at 1600×900 source | Q7 | Actual sizes could be higher for map screenshots; only real captures will confirm |
| A2 | Docker Compose v2 is available on the target machine | Environment Availability | If only Compose v1 is available, `docker compose` (space) syntax won't work; use `docker-compose` instead |
| A3 | Playwright browser binaries cached from geolens monorepo will be found by getgeolens.com's Playwright install | Q3 | If versions differ, a separate `npx playwright install chromium` is needed regardless |
| A4 | Phase 218 seeder has been run successfully on the target GeoLens instance before captures | Q1 | If seeder hasn't run, Map Builder screenshot will show empty catalog |

---

## Open Questions (Unresolved)

### OQ1: AI Chat Screenshot — Standalone Panel or Map Builder Context?

CONTEXT.md D-01 lists `app.geolens.io/chat` as the target URL for the AI Chat screenshot. **No such route exists** — the chat is a panel within the Map Builder at `/maps/:id`. The planner must decide:

- (A) Screenshot the full Map Builder page with the ChatPanel open (shows the entire map builder context, which is the real product experience)
- (B) Screenshot only the ChatPanel slide-out at a higher zoom (crops out the map context, focuses on the chat UI itself)
- (C) Ask the user whether a standalone chat page is planned

**Researcher recommendation:** Option (A). The ChatPanel in context of the Map Builder is the actual product. The BrowserFrame URL prop should read `app.geolens.io/maps/{id}` (same as the Map Builder capability). The capability copy can reference "Ask questions about your map data in natural language" to make it clear it's contextual.

**User decision:** If the user expected a standalone chat route to exist (per D-01's URL column), clarify before Plan 01 is executed.

### OQ2: AI Chat Fallback Decision (per D-01)

The CONTEXT.md explicitly defers this to the user: "Surface the gap and let the user decide." The gap is now surfaced. Fallback options:

- (a) Defer AI chat capability section to a later phase
- (b) Use a placeholder screenshot (empty ChatPanel) with "coming soon" badge — zero marketing value for AI capability
- (c) Require `ANTHROPIC_API_KEY` in the capture workflow and document it

**Researcher recommendation:** Option (c) is simplest and most honest — the AI feature exists and works; capturing it just needs an API key. Document in scripts/README.md.

---

## Sources

### Primary (HIGH confidence — verified via code)

- `backend/app/ogc/router.py` — OGC conformance URIs (lines 131-151)
- `frontend/src/App.tsx` — actual route definitions for all 6 capabilities
- `frontend/src/pages/MapViewerGate.tsx` — Map Builder route is `/maps/:id`
- `frontend/src/components/builder/ChatPanel.tsx` — AI chat is a panel, not a page
- `frontend/src/pages/admin/AdminUsersPage.tsx` + `AdminUsersPage.tsx` — RBAC users page exists
- `getgeolens.com/package.json` — Astro 6.1.3, no Playwright installed
- `getgeolens.com/src/components/previews/BrowserFrame.astro` — confirmed `overflow: hidden` behavior
- `.env.example` — minimum env var set, port defaults
- `docker-compose.yml` — service ports and dependencies
- `e2e/fixtures/` — existing sample data (sample.geojson, sample-nonspatial.csv)
- `scripts/demo/seed-thematic-demo.py` + `themes/theme1.py` — Phase 218 seeder with raster content

### Secondary (MEDIUM confidence — official docs)

- [Astro docs — Image guide](https://docs.astro.build/en/guides/images/) — `<Picture>` overview, `src/assets/` vs `public/`
- [Astro docs — astro:assets reference](https://docs.astro.build/en/reference/modules/astro-assets/) — `<Picture>` props
- [Astro docs — Code component reference](https://docs.astro.build/en/reference/components-reference/#code-) — build-time Shiki, zero JS
- [Astro docs — API reference](https://docs.astro.build/en/reference/api-reference/#url) — `Astro.url.pathname` for active link detection

### Tertiary (LOW confidence — not separately verified)

- None.

---

## Metadata

**Confidence breakdown:**
- OGC conformance list: HIGH — read directly from router.py
- UI existence per capability: HIGH — read App.tsx, MapViewerGate.tsx, all admin pages
- Astro `<Picture>` API: HIGH — verified from official docs
- Playwright version/install: HIGH — verified from monorepo node_modules
- AVIF size estimates: LOW/ASSUMED — typical compression ratios only
- Docker port defaults: HIGH — read from .env.example

**Research date:** 2026-04-11
**Valid until:** 2026-05-11 (stable platform; Astro 6 API won't change; GeoLens routes won't change without a new phase)

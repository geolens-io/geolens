---
phase: 216-features-and-quickstart-pages
created: 2026-04-12
discuss_mode: discuss
requirements: [FEAT-01, FEAT-02, FEAT-03, QUICK-01, QUICK-02, QUICK-03]
depends_on: [215]
---

# Phase 216 — Features + Quickstart Pages: Context

## Phase Goal (from ROADMAP.md)

> A technical evaluator can see the full capability depth on `/features` with product evidence for each capability, and a developer can go from zero to a running GeoLens instance in under 10 minutes following only the `/quickstart` page.

## Requirements

| ID | Description |
|----|-------------|
| FEAT-01 | Capability sections covering search, map builder, data ingestion, raster/VRT, AI chat, and RBAC |
| FEAT-02 | Each capability section includes a description, key points, and a stylized product preview |
| FEAT-03 | OGC API compliance and standards section with supported conformance classes |
| QUICK-01 | Step-by-step guide from zero to running GeoLens via `docker compose` |
| QUICK-02 | Copyable code blocks with environment setup, docker compose commands, and first-login instructions |
| QUICK-03 | Expected outcome description (what the user sees after completing the quickstart) |

## Prior Context Applied (do NOT re-decide)

From Phase 212 / 215 / STATE.md — already locked, downstream agents must honor:

- **Stack**: Astro 6 + Tailwind CSS 4 + OKLCH custom properties + Inter Variable + zero JS runtime. No shadcn. No client directives.
- **Theme**: Light mode only for v14.0. No dark mode.
- **Color tokens**: Sourced from `getgeolens.com/src/styles/global.css` (manually synced from `geolens/frontend/src/index.css`). Never use raw hex or Tailwind color names for brand tokens.
- **Contrast gate**: A11Y-01 — body-size text on white requires `primary-700` (L=0.46). `primary-500` is decorative only.
- **SEO / layout contract**: Every page inherits SiteLayout (Phase 213) with title/description/ogImage/jsonLd. Structured data per page.
- **Nav header existed in Phase 215**: logo + GitHub icon only. Phase 216 amends this to add a subnav — see Decision 7.
- **BrowserFrame hazards** (Phase 215 Plan 04): mobile tilt reset, glow containment at narrow viewports, `overflow-x: clip` on sections that embed BrowserFrame, `max-w-md mx-auto` wrapper cap with `class="w-full"` on the frame for responsive sizing. Any new BrowserFrame consumers must follow this pattern.
- **Code review conventions**: JSON-LD `softwareVersion: '1.0.0'` (not 14.0 — corrected in 215). External links with `target="_blank"` need `rel="noopener noreferrer"` AND an `aria-label` announcing new-tab behavior.
- **Pre-launch deferred**: Real screenshots of catalog + map builder will replace the stylized SVG mocks before v14.0 launch (per STATE.md Pending Todos). Phase 216 ships with stylized previews — same treatment as Phase 215.

## Phase 214 Preview Inventory (reusable)

Already built in `getgeolens.com/src/components/previews/`:

| Component | Chrome URL | Maps to Phase 216 capability |
|-----------|------------|------------------------------|
| `SearchPreview.astro` | `app.geolens.io/search` | Search (cap 1) — reuse verbatim |
| `MapBuilderPreview.astro` | `app.geolens.io/builder` | Map Builder (cap 2) — reuse verbatim (already rebuilt as hero in 215-follow-up) |
| `DatasetDetailPreview.astro` | (unused on homepage) | Data Ingestion (cap 3) — repurpose; shows ingested dataset's metadata + extent thumbnail, which IS the post-ingest product evidence |
| `BrowserFrame.astro` | n/a | Wrapper used by all previews |

## Decisions

### D-01: Product previews — REAL SCREENSHOTS (supersedes the SVG mock plan)

**Status:** SUPERSEDES earlier draft of D-01 (SVG-mock approach). Updated 2026-04-12 after user feedback: *"I'm not a big fan of the SVG illustrations to represent any feature in the app — I think we should use real screenshots."*

**Decision:** All capability previews on both the homepage AND the `/features` page use **real screenshots** captured from a running GeoLens instance via Playwright. This replaces:

- Phase 214's `SearchPreview.astro` (SVG mock) → real screenshot of `/search` or the catalog page
- Phase 214's `MapBuilderPreview.astro` (SVG mock, recently rebuilt as cartographic hero) → real screenshot of the map builder with layers loaded
- Phase 214's `DatasetDetailPreview.astro` (SVG mock, currently unused) → real screenshot of a dataset detail page post-ingest (used for Data Ingestion capability)
- All three net-new previews planned for Phase 216 (RasterVrt, AiChat, Rbac) → real screenshots from the start

**Why this changed:** The rebuilt MapBuilderPreview demonstrated that stylized SVG mocks can be impressive, but they still read as "a representation of the product" rather than "the actual product". GeoLens shipped publicly at 1.0.0 and has a real running UI. Marketing a real product should show the real product. This also closes out the STATE.md Pending Todo for pre-launch screenshot work by pulling it forward into Phase 216 scope.

**The 6 capability screenshots to capture (FEAT-01/02 order):**

| # | Capability | Target route / state | URL chrome |
|---|-----------|----------------------|------------|
| 1 | Search | `/search` with seeded results visible (Natural Earth + sample datasets) | `app.geolens.io/search` |
| 2 | Map Builder | Map builder page with 2-3 layers loaded and a visible map rendered | `app.geolens.io/builder/{id}` |
| 3 | Data Ingestion | Dataset detail page post-ingest showing metadata + extent thumbnail | `app.geolens.io/datasets/{id}` |
| 4 | Raster/VRT | Raster dataset detail OR map builder with a raster layer visible | `app.geolens.io/datasets/{raster-id}` |
| 5 | AI Chat | Chat interface with a real geospatial conversation | `app.geolens.io/chat` |
| 6 | RBAC | Admin users/roles page with a populated user list | `app.geolens.io/admin/users` |

**Fallback logic** — if any capability is missing a usable UI state (e.g., AI chat might not have a shippable interface yet, RBAC admin page might not be built), the researcher should flag it in RESEARCH.md as a gap. Options when a gap is found:
- (a) Defer that capability's section to a later phase and note on `/features` that it's coming
- (b) Ship with a placeholder screenshot + "coming soon" badge
- (c) Pull in the in-progress UI temporarily so we have something to capture

The researcher should NOT make this call — surface the gap and let the user decide.

**Implications for Phase 215 (shipped):**
- The homepage's `<SearchPreview />` and `<MapBuilderPreview />` components will be **retrofitted** — they'll still be the same component names (callsite stability) but their internals will become `<Picture>` tags pointing to the captured screenshots, wrapped in `BrowserFrame` (per D-11). The public API of each component stays the same; the implementation changes.
- Phase 215's stylized map builder hero work is NOT wasted — it taught us how to make BrowserFrame responsive (the `class="w-full"` pattern) and validated the cartographic-section rhythm, both of which carry forward.

**Notes for downstream agents:**
- The Phase 214 SVG preview files are being **replaced in place** — same file names, different content. This ensures the homepage and `/preview-test` page continue to work without callsite changes.
- The existing `BrowserFrame.astro` component is retained — screenshots render inside it (see D-11).
- Full capture workflow details in D-10 (Playwright script), D-11 (BrowserFrame wrapping), D-12 (image format), D-13 (storage + naming).

### D-02: /features page layout — 6 zig-zag stripes + OGC section

**Decision:** Each of the 6 capabilities gets its own full-width section with an alternating zig-zag layout (copy / preview swap sides every other section). The OGC API compliance section (FEAT-03) appears at the bottom as the 7th section. Page rhythm matches the homepage's ProductPreviewSection + MapBuilderSection pattern established in Phase 215.

**Capability order (from D-03):**
1. Search (copy left, preview right)
2. Map Builder (preview left, copy right)
3. Data Ingestion (copy left, preview right)
4. Raster/VRT (preview left, copy right)
5. AI Chat (copy left, preview right)
6. RBAC (preview left, copy right)
7. OGC API compliance (FEAT-03) — full-width centered section, no preview

**Rationale:** Zig-zag is the rhythm already established in Phase 215. Every capability gets equal hero treatment — critical for a marketing page targeting technical evaluators who need to see depth, not brevity. Compact grids were rejected because they signal "we have many features" rather than "each feature is substantial". Tabs/accordions were rejected because they hide content from skim-readers.

**Layout notes:**
- Each stripe uses the same `overflow-x-clip` + `max-w-7xl` + `grid-cols-12 gap-12 lg:gap-16` + `col-span-5/col-span-7` pattern as `ProductPreviewSection`.
- Alternating background: `var(--background)` (white) and `var(--surface-0)` (pale) — improves section separation.
- Stripe order is `order-1`/`order-2` classes on the preview column for zig-zag.
- Extract a shared `FeatureStripe.astro` component if the same layout is repeated 6 times (planner's call — can be inlined if the prop shape is too broad).

### D-03: Capability order = roadmap order

**Decision:** Capabilities on `/features` appear in the order they are listed in ROADMAP.md FEAT-01: **search → map builder → data ingestion → raster/VRT → AI chat → RBAC**.

**Rationale:** This order tells the natural discovery-first story: find data → use data visually → load your own data → work with rasters → ask the AI → control who sees what. It matches how a technical evaluator would mentally explore the product. It also matches REQUIREMENTS.md, so traceability is trivial.

**Alternatives considered and rejected:**
- Data-pipeline order (ingestion-first) — too operational, doesn't hook evaluators
- Impact-first order (map builder first) — front-loads visual drama but fragments the discovery flow

### D-04: OGC API compliance section format (FEAT-03)

**Decision:** Two-column list grouped by OGC API family. Left column: API name (bold) + 1-sentence description. Right column: bulleted list of supported conformance class **names** (no URIs or external links in v1).

**Structure:**
```
OGC Standards & Compliance
──────────────────────────────────────
Features API          | • Core
Read and filter       | • CRS
geospatial features.  | • Filter (CQL2 text + JSON)
                      | • Query (offset/limit/bbox)
──────────────────────────────────────
Tiles API             | • Core
Serve vector and      | • Datasets
raster tiles.         | • Styles
...
```

**APIs to cover (preliminary list — researcher should verify from REQUIREMENTS.md, backend code, and prior conformance phases like 183):**
- Features (Part 1 Core, CRS, Filter, Query)
- Tiles (Core, Datasets, Styles)
- Records (Part 1 Core, Sorting, Text Search)
- Maps (Core, BBox)
- Processes (if enabled)

**Rationale:** Two-col format is scannable without needing a table, holds up at narrow viewports, and doesn't require maintaining external URLs (which drift). Evaluators who need deeper detail know where to find the OGC spec. The hard part is getting the ACTUAL supported conformance class list right — researcher should cross-check against the backend's advertised conformance URIs, NOT the UI.

### D-05: /quickstart depth — Standard (prereqs + core flow + troubleshooting)

**Decision:** Quickstart page uses Standard depth. Page structure:

1. **Prerequisites** (brief — Docker Compose v2, ~4 GB RAM, ~10 GB disk, open ports 5432/6379/8000/8080)
2. **Step 1: Get the code** — `git clone` or download release tarball, with both options shown as copyable blocks
3. **Step 2: Configure environment** — copy `.env.example` → `.env`, set `GEOLENS_ADMIN_USERNAME` + `GEOLENS_ADMIN_PASSWORD`, any other required vars
4. **Step 3: Start services** — `docker compose up -d --build`, expected output
5. **Step 4: Log in and verify** — open `http://localhost:8080`, log in with admin creds, confirm empty catalog loads
6. **Step 5: Upload your first dataset** — happy-path instructions for uploading a sample file (Natural Earth countries GeoJSON or similar)
7. **What you'll see** (QUICK-03) — prose description + small inline SVG illustration (see D-06)
8. **Troubleshooting** — 3-4 common issues:
   - Port conflict (5432/8000/8080 already in use)
   - Admin login fails (env var typo or default credentials)
   - Services slow to start (first-time Docker image pull)
   - File upload fails (file size or format support)
9. **Next steps** — links to `/features` and GitHub repo

**Rationale:** Standard depth hits the "under 10 minutes" success criterion without bloat. Prereqs and troubleshooting prevent evaluator friction without adding "advanced configuration" content that belongs in proper docs. The structure is monolithic (no collapsible sections) because zero-JS.

**Rejected alternatives:**
- Minimal (core flow only) — too thin; evaluators would hit troubleshooting friction with no recourse
- Comprehensive (with advanced config) — breaks the 10-minute promise and duplicates docs

### D-06: QUICK-03 "What you'll see" outcome — prose + real screenshot (supersedes SVG plan)

**Status:** SUPERSEDES earlier draft of D-06. Updated 2026-04-12 alongside D-01.

**Decision:** A single paragraph describing what's live after step 5 (catalog UI with first dataset visible, map preview working, OGC endpoints responding at `http://localhost:8000/`) plus a **real screenshot** of the GeoLens landing screen immediately after a fresh install. The screenshot is captured via the same Playwright workflow as the capability screenshots (D-10).

**Which screenshot to use:** Either a dedicated "post-quickstart landing" screenshot (catalog UI right after the first dataset upload completes) OR reuse the Search screenshot from D-01 if a distinct post-quickstart state isn't meaningfully different. The researcher should propose which.

**Rationale:** Prose alone was too thin for QUICK-03's "expected outcome" language. An SVG illustration was the earlier compromise but was superseded by the D-01 pivot to real screenshots across the board. Using a real screenshot here is consistent with /features and the homepage, and it's more convincing for evaluators — they see literally what they'll see after following the quickstart.

**Notes:**
- Same `<Picture>` + AVIF/WebP/PNG pipeline as the capability previews (D-12)
- Same BrowserFrame wrapping as other previews (D-11) OR a simpler unframed treatment for visual differentiation from the capability sections above — planner's call
- If the screenshot is reused from D-01, it goes in the same `public/screenshots/` path and is just referenced twice

### D-07: Marketing subnav — Features + Quickstart + GitHub at sm+

**Decision:** Amend `Nav.astro` to add subnav links. Layout:

- **Desktop (sm+, ≥640px):** Logo + `Features` link + `Quickstart` link + GitHub icon button
- **Mobile (<640px):** Logo + GitHub icon only (current Phase 215 minimal state preserved)

The active page's link is styled with a different color or underline (`aria-current="page"` for accessibility). No hamburger menu — mobile users navigate via homepage hero CTAs and footer links. Zero-JS constraint is preserved.

**Active state styling:**
- Default: `color: var(--muted-foreground)`
- Hover: `color: var(--foreground)`
- Active (`aria-current="page"`): `color: var(--primary-700)` + subtle bottom-border or slightly heavier weight

**Rationale:** With two new pages existing as real content, the nav needs to surface them. Minimal was rejected because it forces users back to the homepage to navigate. The full nav with placeholders (Docs, Blog) was rejected because linking to content that doesn't exist creates 404 friction. Desktop-only subnav with mobile fallback is a documented pattern for zero-JS marketing sites.

**Accessibility notes:**
- `aria-label="Main navigation"` already present on the `<nav>` element
- Each nav link needs proper semantic markup; the current page link gets `aria-current="page"`
- Focus-visible outline per global `:focus-visible` rule in `global.css`

### D-08: Shared previews live in `components/previews/`

**Decision:** All preview components (existing + 3 new) live in `getgeolens.com/src/components/previews/`. No page-specific subdirectory.

**Rationale:** Phase 214's established convention. Keeps previews discoverable. If a preview is ever reused on the homepage (or vice versa — Phase 215 already pulls SearchPreview + MapBuilderPreview into the homepage), it's already in the right place. Fragmentation into page-specific subdirectories was rejected because the previews are NOT coupled to any specific page.

### D-09: Code blocks on /quickstart — plain `<pre><code>`, no JS copy button

**Decision:** Quickstart code blocks use plain `<pre><code>` elements with styled backgrounds. No JS-powered "Copy" button.

**Rationale:** Zero-JS constraint (Phase 212 decision). Browsers support native text selection and copy (Cmd/Ctrl+C) on any `<pre>` element. QUICK-02 says "Copyable code blocks" — "copyable" is satisfied by standard browser selection. A JS copy button would require a `<script>` or `client:load` directive, violating the zero-JS decision. If the user explicitly wants a copy button later, it's a Phase 217/218 polish item or a controlled JS exception.

**Styling notes for planner:**
- Use `<pre>` with `background: var(--surface-3)` or similar muted surface, rounded corners, padding, monospace via `font-family: var(--font-mono)` or `ui-monospace`.
- Each code block should be visually distinct from surrounding prose (clear border or background contrast) so copy-scope is obvious.
- Inline `<code>` within prose should use a lighter treatment.

### D-10: Screenshot capture workflow — Playwright script in the repo

**Decision:** Add a Playwright-powered capture script to `getgeolens.com/scripts/capture-screenshots.ts` (or similar) that is version-controlled, re-runnable, and produces the screenshots referenced by the preview components in D-01. The script owns the full workflow:

1. Assumes a running GeoLens instance (either local `docker compose up` or a seeded fixture instance — researcher to propose)
2. For each capability in D-01, navigates to the target route, waits for content to settle, and captures a screenshot
3. Writes outputs to `getgeolens.com/public/screenshots/` as named PNG files (source of truth)
4. Astro's `<Picture>` pipeline (D-12) handles AVIF/WebP derivation at build time

**What the script requires:**
- A running GeoLens instance accessible at a known URL (default `http://localhost:8080`)
- Seeded data so captures have content (e.g., a small reference dataset set — researcher to propose which; ideally the Phase 218 demo themed collections, but that's a separate phase; fall back to Natural Earth or inline test data)
- Playwright installed as a dev dependency in the getgeolens.com repo
- An `npm run capture` (or similar) entry point

**What the script is NOT:**
- Not a CI visual-regression gate (rejected as scope creep — may be added later if drift becomes a problem)
- Not a production dependency (dev-only)
- Not a full e2e test suite (it's capture-only)

**Viewport:** 1600×1000 for desktop captures (high enough for 2x Retina scaling without being gratuitously huge). Single viewport — no mobile-specific captures in v1 since the BrowserFrame on the marketing site is already narrow (~448px max) and showing a down-scaled desktop screenshot inside it reads correctly. Researcher can propose an alternate dimension if there's a better justification.

**Staleness handling:** Screenshots are committed to the repo and become stale when the GeoLens UI changes. The capture script must be re-run on UI changes to refresh them. This is a manual trigger for now (no CI automation). Add a README note in `scripts/` explaining when to re-run.

**Rationale:** Playwright is already used elsewhere in the project (we used it for Phase 215 visual verification). A re-runnable script is strictly better than manual one-off screenshots because (a) the author who captures them is decoupled from the author who updates them later, (b) diffs are reproducible, (c) the "how to re-capture" knowledge lives with the code instead of in someone's head. CI visual-regression was rejected as scope creep for v1 — if drift becomes a problem, it's a Phase 217+ polish item.

**Notes for downstream agents:**
- The capture script lives in getgeolens.com but depends on a running GeoLens monorepo instance. Document the cross-repo coupling clearly in the script README.
- If a capability's target UI doesn't exist yet (see D-01 fallback logic), the script should skip that capture with a warning, not fail.
- Screenshot filenames must be stable and match the references in the preview components (e.g., `search.png`, `map-builder.png`, etc. — see D-13 for naming).

### D-11: Screenshots render inside existing BrowserFrame wrapper

**Decision:** Screenshots are rendered inside the existing `BrowserFrame.astro` component. The BrowserFrame keeps its macOS traffic lights + URL pill chrome, its responsive `class="w-full"` sizing (from Phase 215 Plan 04), its perspective tilt at desktop/tablet, its mobile tilt reset, and its glow containment at narrow viewports. The only change: the **slot content** becomes an `<Image>` / `<Picture>` tag instead of the current SVG markup inside each SearchPreview/MapBuilderPreview/etc. file.

**Component shape after this phase:**

```astro
---
import BrowserFrame from './BrowserFrame.astro';
import { Picture } from 'astro:assets';
import searchScreenshot from '../../assets/screenshots/search.png';
---

<BrowserFrame url="app.geolens.io/search" class="w-full">
  <Picture
    src={searchScreenshot}
    formats={['avif', 'webp']}
    fallbackFormat="png"
    alt="GeoLens catalog search page showing …"
    widths={[448, 896]}
    sizes="(max-width: 640px) 100vw, 448px"
    loading="lazy"
  />
</BrowserFrame>
```

**Rationale:** The BrowserFrame chrome is proven marketing polish — it reads as "this is a web app", gives the screenshots a frame, and provides the glow/tilt hero effect that the user approved in Phase 215 Plan 04. Dropping it would throw away that work. Using it unchanged means no new component architecture is needed — existing consumers on the homepage and the new `/features` page continue calling `<SearchPreview />` without knowing whether the preview is SVG or image.

**What changes internally:**
- Each Phase 214 SVG preview file (`SearchPreview.astro`, `MapBuilderPreview.astro`, `DatasetDetailPreview.astro`) has its entire internal SVG markup deleted and replaced with a `<Picture>` tag
- The `BrowserFrame class="w-full"` wrapper is preserved
- The min-height styling inside the frame is removed (the image dictates the aspect ratio)
- Alt text must be descriptive for accessibility (A11Y carry-forward from 212 and 217 launch gate)

**What does NOT change:**
- Component names (callsite stability — `<SearchPreview />` still works in index.astro and will work in features.astro)
- BrowserFrame.astro itself — zero changes to the frame component
- The zig-zag section layouts on homepage and /features

### D-12: Image pipeline — Astro `<Picture>` with AVIF + WebP + PNG fallback

**Decision:** Use Astro's built-in `astro:assets` `<Picture>` component for all screenshots. Serves AVIF first, WebP second, PNG fallback. Automatic `width`/`height` attribution to prevent layout shift. Native lazy-loading. Zero client-side JS required — Astro's image optimization runs at build time.

**Configuration:**
- Source format: PNG (what Playwright produces)
- Output formats: `formats={['avif', 'webp']}` with `fallbackFormat="png"`
- Responsive: `widths={[448, 896, 1344]}` — 1×, 2×, 3× of the 448px BrowserFrame desktop target
- Sizes attribute: `sizes="(max-width: 640px) 100vw, 448px"` — full viewport on mobile, 448 fixed at sm+
- Loading: `loading="lazy"` for all non-hero screenshots; `loading="eager"` for the first one above the fold (homepage hero) — picker's call
- Alt text: mandatory, descriptive, written per screenshot (not a generic "screenshot")

**Storage:**
- Source PNGs live in `getgeolens.com/src/assets/screenshots/` (NOT `public/`) so Astro's image pipeline processes them at build time. If we use `public/`, Astro skips the optimization and we lose AVIF/WebP derivation.
- Build output lands in `_astro/` with hashed filenames, served efficiently

**Rationale:** Astro 6's `astro:assets` is the idiomatic zero-JS image optimization path. Ships modern formats automatically. The AVIF/WebP derivation happens at `astro build` time, no runtime overhead. Lighthouse loves this pattern — directly relevant to the Phase 217 a11y/performance gate. `<img>` alone was rejected because it loses format negotiation and PNG transfer sizes are painful (~300-500KB each × 6 screenshots = 1.5-3 MB for the /features page). WebP-only was rejected because it drops old-IE/old-Safari support, which matters for gov procurement.

**Bundle size expectation:** With AVIF + WebP, each screenshot should ship at ~30-80KB (vs. 200-500KB PNG). Total image payload for `/features` page ~180-480KB — acceptable for a marketing site.

**Notes for downstream agents:**
- The `astro:assets` import pattern (`import screenshot from '../../assets/screenshots/search.png'`) is required for the build pipeline to pick up the image. Referencing via string path (`src="/screenshots/search.png"`) skips optimization.
- Every screenshot needs a meaningful, descriptive `alt` attribute. Not "screenshot of search" — describe what's visible: "GeoLens catalog search showing 207 datasets, filter tabs, and preview cards".
- Researcher should confirm Astro's `<Picture>` + `astro:assets` behavior matches expectations in this specific version (Astro 6.1.3 is installed per earlier build output).

### D-13: Screenshot storage + naming

**Decision:**

- **Source PNGs:** `getgeolens.com/src/assets/screenshots/` (processed by Astro build)
- **Not `public/screenshots/`** — that path skips Astro image optimization
- **Filenames:** One per capability, kebab-case, no variants:
  - `search.png` — Search capability
  - `map-builder.png` — Map Builder capability
  - `data-ingestion.png` — Data Ingestion (dataset detail post-ingest)
  - `raster-vrt.png` — Raster/VRT capability
  - `ai-chat.png` — AI Chat capability
  - `rbac.png` — RBAC capability
  - `quickstart-outcome.png` — QUICK-03 outcome section (may alias `search.png` — planner's call)
- **Capture script writes to:** `getgeolens.com/src/assets/screenshots/` directly (not `public/`)
- **Git tracking:** All screenshot PNGs are committed. They are not build artifacts — they're source-of-truth assets. Planner should add `src/assets/screenshots/*.png` to any LFS config if the repo uses LFS (probably not for Astro marketing site).

**Rationale:** Kebab-case matches web conventions and is the Astro/Vite default for asset paths. One file per capability keeps the filename map simple. Splitting by viewport or format would be a maintenance burden (Astro handles those automatically via `<Picture>`). Putting sources in `src/assets/` (not `public/`) is a critical technical detail — get this wrong and the build pipeline silently skips optimization.

**Notes:** The `capture-screenshots.ts` script in D-10 owns the write path. If it ever writes to `public/` by mistake, the previews will ship as unoptimized PNGs and someone will notice a Lighthouse regression — the researcher should flag this in RESEARCH.md as a known pitfall.

## Shared Components to Extract (planner's call)

These may be extractable depending on how much they're reused:

- **`FeatureStripe.astro`** — if the zig-zag section layout is repeated 6 times on `/features` with only copy/preview variance, extract it
- **`CodeBlock.astro`** — if `/quickstart` has 6+ code blocks with consistent styling, extract it
- **Nav subnav links** — inline in `Nav.astro`, not a separate component (too small)
- **OGC section** — probably inline in `/features/index.astro`, not a separate component (used once)

The planner should decide based on whether extraction reduces duplication enough to justify the indirection.

### D-14: AI Chat capture — Map Builder with real conversation

**Status:** Added 2026-04-12 after research revealed AI chat has no standalone route.

**Decision:** AI Chat capability is captured by opening a Phase 218-seeded map in the Map Builder (`/maps/:id`), opening the built-in ChatPanel slide-out, typing a real geospatial query (e.g., *"Show only aquifers in California"* or *"What datasets cover New York State?"*), waiting for the AI response to render, and screenshotting the panel with a visible conversation. BrowserFrame URL shows `app.geolens.io/maps/{id}` (matches the real route).

**Rationale:** The researcher verified that GeoLens has no `/chat` route. ChatPanel.tsx is a component inside the Map Builder, gated by admin settings + API key presence. It IS the real chat UI — not a placeholder. Capturing it in its real location preserves marketing honesty. Taking an empty-panel screenshot was rejected because a real conversation is dramatically more compelling for the features page.

**Alt text must describe the conversation content** — A11Y consideration: alt text like "AI chat panel inside the Map Builder responding to a query about aquifer datasets with a dataset card and map context".

### D-15: AI chat capture fallback — detect API key, gracefully degrade to empty panel

**Status:** Added 2026-04-12 alongside D-14.

**Decision:** The capture script (D-10) checks whether AI is enabled and an LLM API key is configured BEFORE attempting the AI chat screenshot. Detection approach:
1. Call `/api/v1/settings/ai-enabled` (or equivalent admin settings endpoint the researcher identifies) OR
2. Attempt a probe query and check for error response (secondary approach if no settings endpoint exists)

**If AI is available:** Capture the full conversation variant per D-14.

**If AI is unavailable (missing API key, disabled in admin settings, or probe fails):**
- Capture the **empty-panel variant** automatically (Map Builder with chat panel open but no conversation, placeholder "Ask anything about your map data..." text visible)
- Log a warning: `⚠ AI unavailable — captured empty panel variant. Set ANTHROPIC_API_KEY or OPENAI_API_KEY for full conversation capture.`
- Continue the rest of the capture run (do NOT fail the script)
- The committed `ai-chat.png` is valid either way — the component renders the same file

**Rationale:** Contributors may not have LLM API keys locally, and we don't want that to block them from regenerating other screenshots. Graceful fallback keeps the capture workflow runnable by anyone with a running GeoLens. Script failure was rejected because it creates onboarding friction; stale-skip was rejected because it silently desyncs the screenshot from the current UI.

**For this phase's initial capture run:** If the person running the first capture has an API key configured, we get the premium "full conversation" screenshot. If not, we ship with the empty-panel variant and can re-run later when a key is available. Either is acceptable for launch.

**Notes for downstream agents:**
- The researcher identified that ChatPanel availability is controlled by `SettingsAITab.tsx` in the admin settings. The capture script should call the admin settings API (after login) rather than guessing.
- Empty-panel variant still renders inside the Map Builder, so the screenshot always shows real product UI, just with a quieter conversation state.
- Document the detection logic in `scripts/README.md` so operators know what to expect.

## Deferred Ideas (NOT in this phase)

- ~~Real screenshots replacing stylized SVG mocks~~ — **PULLED FORWARD into this phase** per D-01 (2026-04-12 update). STATE.md Pending Todo closes out here.
- CI visual regression gate on screenshots — rejected as scope creep per D-10; may add later if drift becomes a problem
- Mobile-specific screenshot captures — rejected per D-10; single desktop viewport is sufficient for the BrowserFrame-wrapped marketing use case
- Docs site (`/docs`) — out of scope, no REQUIREMENTS.md entry
- Blog (`/blog`) — out of scope
- Enterprise contact form — already deferred per STATE.md Blockers/Concerns
- Per-capability deep-dive pages (e.g., `/features/map-builder`) — out of scope; `/features` is a single page
- Syntax highlighting on quickstart code blocks — zero-JS constraint rules out Prism/Shiki client-side. If we want highlighting, it'd need build-time Shiki via Astro's built-in code block syntax, which is allowed — planner can evaluate.
- Troubleshooting as its own page (`/troubleshooting` or `/docs/troubleshooting`) — deferred; v1 has troubleshooting inline on `/quickstart`

## Open Questions for Researcher

These are for `gsd-phase-researcher` to investigate during the research step, NOT for the user to answer:

### Screenshot workflow (new, from D-01/D-10/D-11/D-12/D-13)

1. **Running GeoLens for capture** — is there a seed/fixture instance we can point the capture script at, or does it assume the user runs `docker compose up` in the monorepo before running `npm run capture`? What data should be seeded for the 6 screenshots to have meaningful content? (If Phase 218 demo collections are already on main, use those. Otherwise fall back to Natural Earth + manual uploads.)
2. **UI state availability per capability** — for each of the 6 capabilities in D-01, does a real UI exist in GeoLens 1.0.0 that is shippable as marketing evidence? Specifically investigate: (a) AI chat interface — is there a real chat UI, or is it an API-only feature? (b) RBAC admin page — does `/admin/users` or `/admin/roles` exist as a real page? (c) Raster/VRT — is there a dedicated raster detail page or is it the same dataset detail page with different content? Flag any gaps for the user per D-01 fallback logic.
3. **Playwright setup in getgeolens.com** — installed as dev dependency? What's the cleanest install path given the repo's current package.json? Does it need its own Playwright browser download or can it share with the monorepo's Playwright install?
4. **Astro `<Picture>` + `astro:assets` in Astro 6.1.3** — confirm the exact API (which props, which import path, which output formats are supported). Astro's image pipeline changed between v3/v4/v5/v6 — the researcher should verify the current v6.1.3 surface.
5. **`src/assets/` vs `public/` decision path** — confirm that `src/assets/screenshots/` is the correct location for Astro 6.1.3 build-time optimization, and that `public/` would silently skip optimization. Document the difference in RESEARCH.md so the executor can't put them in the wrong place.
6. **Screenshot viewport recommendation** — D-10 specifies 1600×1000 as a starting point. Researcher should confirm this works for all 6 capabilities (the map builder and chat screens might want taller captures to fit their content comfortably; RBAC might want a wider capture to show all columns).
7. **Lighthouse impact projection** — given that each screenshot adds AVIF+WebP+PNG variants to the build, what's the projected total transfer size for the /features page? Ballpark estimate only — real numbers come during execution. Matters for Phase 217 launch gate.

### Page content (unchanged from original CONTEXT)

8. **OGC conformance class list** — what does the GeoLens backend actually advertise? Check `backend/app/ogc/` or equivalent, the `/conformance` endpoint, and Phase 183 (OGC Records Part 1 conformance URIs) for the canonical list. The list in D-04 is preliminary.
9. **Quickstart env var minimum set** — what's the actual minimum required env set for a working `docker compose up`? Check `.env.example` and `docker-compose.yml` in the main repo. D-05 Step 2 assumes admin creds are the only hard-required var.
10. **Sample dataset for Step 5** — is there a canonical sample dataset in the repo for first-upload happy path? If not, the quickstart can link to a Natural Earth download or include one in the repo.
11. **Astro syntax highlighting option** — does Astro's built-in Shiki support satisfy our zero-JS constraint? If yes, quickstart code blocks can have proper syntax highlighting for bash/shell commands without client-side JS.
12. **Active-link detection in Astro** — cleanest way to compute `aria-current="page"` in the shared Nav component. Likely via `Astro.url.pathname` comparison; the researcher should confirm the idiomatic pattern.

## Next Steps

1. Run `/gsd-plan-phase 216` to generate plan files.
   - Researcher will investigate the 12 open questions above.
   - Planner will decompose into concrete tasks — likely 5-6 plans given the screenshot pivot:
     - **Plan 01**: Install Playwright + build `capture-screenshots.ts` script + document the workflow (D-10)
     - **Plan 02**: Run the capture script, commit 6 screenshots, validate with `astro build`
     - **Plan 03**: Retrofit Phase 214 preview components (`SearchPreview`, `MapBuilderPreview`, `DatasetDetailPreview`) to render `<Picture>` instead of SVG, keeping BrowserFrame wrapper and callsite compatibility (D-11/D-12)
     - **Plan 04**: Build 3 net-new preview components (RasterVrt, AiChat, Rbac) using the same `<Picture>` + `BrowserFrame` pattern — parallelizable with Plan 03 once screenshots exist
     - **Plan 05**: Build `/features` page with 6 zig-zag stripes + OGC section (consumes all 6 preview components)
     - **Plan 06**: Build `/quickstart` page with prereqs + core flow + troubleshooting + outcome screenshot
     - **Plan 07**: Amend `Nav.astro` subnav with active-page styling — can run in parallel with 05/06
   - Plan order may differ; planner decides dependencies. Capturing screenshots (01/02) MUST complete before the retrofit/new-preview plans can build.
2. Run `/gsd-execute-phase 216` after planning.

## Cross-phase impact

This phase touches files that Phase 215 shipped. Specifically:
- `getgeolens.com/src/components/previews/SearchPreview.astro` — retrofit to use `<Picture>` (Phase 215 consumer on the homepage)
- `getgeolens.com/src/components/previews/MapBuilderPreview.astro` — retrofit to use `<Picture>` (replaces the cartographic hero rebuilt at the end of Phase 215)
- `getgeolens.com/src/components/previews/DatasetDetailPreview.astro` — retrofit to use `<Picture>`

The homepage will inherit the changes automatically since it imports these components. The cartographic hero SVG work from Phase 215 is sunset but the BrowserFrame responsive fix (`class="w-full"`) carries forward — it's exactly what we need for responsive image rendering. No Phase 215 PLAN or SUMMARY files are modified; the changes are additive in history.

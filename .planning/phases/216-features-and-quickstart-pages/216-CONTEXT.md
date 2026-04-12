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

### D-01: Missing capability previews — build 3 new in BrowserFrame style

**Decision:** Build 3 new full-fidelity preview components for the capabilities that have no Phase 214 asset. Each wraps `BrowserFrame` with `class="w-full"` to inherit the responsive sizing fix from Phase 215 Plan 04. Light internal content (~100-200 lines of SVG/Tailwind each). Data ingestion reuses the existing `DatasetDetailPreview.astro` — "post-ingest product evidence" is a valid interpretation of FEAT-02 "stylized product preview".

**New components (in `getgeolens.com/src/components/previews/`):**

1. **`RasterVrtPreview.astro`** — chrome URL `app.geolens.io/raster/{dataset}` or similar
   - High-level: raster tile viewer with a visible raster dataset rendered on a basemap
   - Suggested elements: zoom controls, opacity slider (visual only, non-functional), colormap/legend swatch, metadata footer (CRS, bands, pixel size)
   - Content-shape left to planner/researcher — specific color palette and layout to be designed during plan phase

2. **`AiChatPreview.astro`** — chrome URL `app.geolens.io/chat`
   - High-level: a chat thread showing 3-4 message exchanges between user and assistant, with the assistant answering a geospatial question (e.g., "Show me all aquifers in New York over 1000 sq miles")
   - Suggested elements: user bubble + assistant bubble + a small inline "result" card (dataset card or mini map) that the assistant surfaced
   - Should make it visually obvious this is GIS-aware AI, not a generic chatbot

3. **`RbacPreview.astro`** — chrome URL `app.geolens.io/admin/users` or `/admin/roles`
   - High-level: a role/permission matrix or user list with role badges
   - Suggested elements: 3-4 rows of user/role, permission checkboxes/badges for things like "read", "write", "admin", possibly a "scope" column (per-dataset vs. org-wide)
   - Should communicate "enterprise-grade governance" without being a boring spreadsheet

**Rationale:** FEAT-02 is a hard requirement ("Each capability section includes … a stylized product preview"). All 6 capabilities need equal visual weight to make the evaluator feel the product depth is real. Reusing DatasetDetailPreview for ingestion is acceptable because that component shows the outcome of ingestion (metadata + extent) which is valid product evidence. Building simpler illustrations was rejected because it would create visual inconsistency with Phase 214's established BrowserFrame style.

**Notes for downstream agents:**
- Each new preview MUST use `BrowserFrame` with `class="w-full"` so it inherits the Phase 215 Plan 04 responsive fix.
- Each new preview MUST follow Phase 214's zero-JS, pure-SVG-and-Tailwind approach.
- Internal content density should match `SearchPreview`/`MapBuilderPreview` — not sparse, not overwhelming.
- Use CSS custom properties for all brand colors. Absolute no hex except the macOS chrome dots already in BrowserFrame.
- The `/preview-test` page already exists and can be used to visually review new previews before wiring into `/features`.

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

### D-06: QUICK-03 "What you'll see" outcome — prose + small inline SVG

**Decision:** A single paragraph describing what's live after step 5 (catalog UI with first dataset visible, map preview working, OGC endpoints responding at `http://localhost:8000/`) plus a small inline SVG illustration showing a silhouetted landing-screen mockup.

**Rationale:** Prose alone was too thin for QUICK-03's "expected outcome" language. Reusing `SearchPreview` was rejected because it creates visual echo with the `/features` page that already uses it. A new small inline SVG (illustrative, not a full BrowserFrame preview) gives the user a visual anchor without redundant work. Real screenshots will replace this before launch per the STATE.md pre-launch todo — today's SVG is a placeholder by design.

**Notes:** The illustration should be distinct from the BrowserFrame previews — simpler, more diagrammatic (boxes + labels, no cartography). Something like a stylized browser window with three labeled regions: "Catalog sidebar", "Search results", "Map preview".

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

## Shared Components to Extract (planner's call)

These may be extractable depending on how much they're reused:

- **`FeatureStripe.astro`** — if the zig-zag section layout is repeated 6 times on `/features` with only copy/preview variance, extract it
- **`CodeBlock.astro`** — if `/quickstart` has 6+ code blocks with consistent styling, extract it
- **Nav subnav links** — inline in `Nav.astro`, not a separate component (too small)
- **OGC section** — probably inline in `/features/index.astro`, not a separate component (used once)

The planner should decide based on whether extraction reduces duplication enough to justify the indirection.

## Deferred Ideas (NOT in this phase)

- Real screenshots replacing stylized SVG mocks — tracked in STATE.md Pending Todos, slated pre-launch
- Docs site (`/docs`) — out of scope, no REQUIREMENTS.md entry
- Blog (`/blog`) — out of scope
- Enterprise contact form — already deferred per STATE.md Blockers/Concerns
- Per-capability deep-dive pages (e.g., `/features/map-builder`) — out of scope; `/features` is a single page
- Syntax highlighting on quickstart code blocks — zero-JS constraint rules out Prism/Shiki client-side. If we want highlighting, it'd need build-time Shiki via Astro's built-in code block syntax, which is allowed — planner can evaluate.
- Troubleshooting as its own page (`/troubleshooting` or `/docs/troubleshooting`) — deferred; v1 has troubleshooting inline on `/quickstart`

## Open Questions for Researcher

These are for `gsd-phase-researcher` to investigate during the research step, NOT for the user to answer:

1. **OGC conformance class list** — what does the GeoLens backend actually advertise? Check `backend/app/ogc/` or equivalent, the `/conformance` endpoint, and Phase 183 (OGC Records Part 1 conformance URIs) for the canonical list. The list in D-04 is preliminary.
2. **Quickstart env var minimum set** — what's the actual minimum required env set for a working `docker compose up`? Check `.env.example` and `docker-compose.yml` in the main repo. D-05 Step 2 assumes admin creds are the only hard-required var.
3. **Sample dataset for Step 5** — is there a canonical sample dataset in the repo for first-upload happy path? If not, the quickstart can link to a Natural Earth download or include one in the repo.
4. **Astro syntax highlighting option** — does Astro's built-in Shiki support satisfy our zero-JS constraint? If yes, quickstart code blocks can have proper syntax highlighting for bash/shell commands without client-side JS.
5. **Active-link detection in Astro** — cleanest way to compute `aria-current="page"` in the shared Nav component. Likely via `Astro.url.pathname` comparison; the researcher should confirm the idiomatic pattern.

## Next Steps

1. Run `/gsd-plan-phase 216` to generate plan files.
   - Researcher will investigate the open questions above.
   - Planner will decompose into concrete tasks — likely 3-4 plans:
     - Plan 01: Build 3 new preview components (RasterVrtPreview, AiChatPreview, RbacPreview) — parallelizable
     - Plan 02: Build `/features` page with 6 sections + OGC section + capability wiring
     - Plan 03: Build `/quickstart` page with prereqs + core flow + troubleshooting + outcome
     - Plan 04: Amend `Nav.astro` subnav and wire active-page styling
   - Plan order may differ; planner decides dependencies.
2. Run `/gsd-execute-phase 216` after planning.

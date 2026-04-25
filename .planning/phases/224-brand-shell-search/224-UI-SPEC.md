---
phase: 224
slug: brand-shell-search
status: draft
shadcn_initialized: false
preset: not-applicable
created: 2026-04-25
---

# Phase 224 — UI Design Contract

> Visual and interaction contract for the docs-site brand bridge, shell components, and search shortcuts shipped by Phase 224. This phase ships ZERO content prose — only the shell that frames future content. The design contract therefore covers brand-relevant overrides, custom shell components, and discretion-area lockdowns. Body-content typography (paragraphs, headings, code blocks) inherits Starlight 0.38.4 defaults and is OUT OF SCOPE.

---

## Design System

| Property | Value |
|----------|-------|
| Tool | none (Astro Starlight 0.38.4 with raw `customCss`) |
| Preset | not applicable |
| Component library | Starlight built-in components + custom Astro components for overrides |
| Icon library | Inline SVG only (no icon-library dependency for new components — matches marketing's `Nav.astro` posture) |
| Font | Inter Variable 5.2.8 self-hosted via `@fontsource-variable/inter/wght.css` (weight-only axis, mirrors marketing's `global.css:10`) |

**Why no shadcn:** the docs site is Astro Starlight, not React/Next.js/Vite. Starlight ships its own component library; the design contract here is about retokening Starlight via CSS custom properties, NOT introducing a parallel React component system. CONTEXT.md D-05 also explicitly forbids `@astrojs/starlight-tailwind`.

---

## Spacing Scale

The docs site inherits Starlight's spacing tokens for content layout (sidebar width, nav height, content padding). Custom components built in this phase MUST use Starlight tokens where they exist, and otherwise use the marketing 8-point scale:

| Token | Value | Usage in this phase |
|-------|-------|---------------------|
| xs | 4px (0.25rem) | Inline icon gap (back-link arrow ↔ "getgeolens.com" label, breadcrumb separator margin) |
| sm | 8px (0.5rem) | Breadcrumb item gap, 404 search dialog top margin |
| md | 16px (1rem) | 404 category-card internal padding, breadcrumb wrapper padding-block |
| lg | 24px (1.5rem) | 404 category-card grid gap, footer link margin-top |
| xl | 32px (2rem) | 404 page section vertical rhythm, "404" mark margin-bottom |
| 2xl | 48px (3rem) | 404 page top padding (above the 404 mark) |
| 3xl | 64px (4rem) | 404 page max-width container vertical breathing room |

**Starlight tokens preserved (do NOT override):**
- `--sl-nav-height` (3.5rem mobile, 4rem desktop)
- `--sl-nav-pad-x`, `--sl-nav-pad-y`
- `--sl-content-width` (45rem)
- `--sl-content-pad-x`, `--sl-content-gap-y`
- `--sl-sidebar-width` (18.75rem)

Exceptions: none. All custom-component spacing for this phase fits the multiples-of-4 scale.

---

## Typography

Starlight body-content typography is OUT OF SCOPE per `<additional_context>`. This table covers only the new typography surfaces introduced in this phase: docs-side back-link, breadcrumbs, 404 page, and Inter font registration.

| Role | Size (Starlight token) | Weight | Line Height | Where used |
|------|-----------------------|--------|-------------|-----------|
| Body | `--sl-text-base` (16px) | 400 | `--sl-line-height` (1.75) | Inherited; Starlight default. Confirmed — do NOT override. |
| Heading | `--sl-text-h1`–`--sl-text-h4` | 600 | `--sl-line-height-headings` (1.2) | Inherited; Starlight default. Confirmed. |
| Back-link label | `--sl-text-sm` (14px) | 400 | 1.5 (Starlight default) | DocsHeader's "← getgeolens.com" anchor |
| Breadcrumb item | `--sl-text-sm` (14px) | 400 (current page: 500) | 1.5 | Custom Breadcrumbs component |
| 404 mark | `--sl-text-6xl` (64px) | 700 | 1.0 | Brand-coloured "404" numerals |
| 404 heading | `--sl-text-h2` (29–35px responsive) | 600 | 1.2 | "Page not found" |
| 404 body copy | `--sl-text-base` (16px) | 400 | 1.5 | Single-line description |
| 404 category-card label | `--sl-text-base` (16px) | 600 | 1.2 | Card titles (Quickstart / User Guide / Admin Guide / API Reference) |
| 404 category-card description | `--sl-text-sm` (14px) | 400 | 1.5 | One-line subtitle under each card title |
| 404 footer link | `--sl-text-sm` (14px) | 400 | 1.5 | "Or head back to getgeolens.com" |

**Inter font registration:**
- File: `getgeolens.com/docs/src/styles/custom.css`
- Pattern: `@import '@fontsource-variable/inter/wght.css';` followed by `:root { --sl-font: 'Inter Variable', ui-sans-serif, system-ui, sans-serif; }`
- Variable axis: weight only (`wght.css`) — matches marketing's `getgeolens.com/src/styles/global.css:10` exactly. Do NOT use `index.css` or `standard.css` — those bundle italic + optical-size axes that bloat the CSS payload by ~2.5×.
- **Weight subset locked:** the `wght.css` import covers the full 100–900 axis via a single woff2; subsetting to 400/500/600/700 is unnecessary because the variable font already serves all weights from one file. This locks "Inter weight subset" from the Discretion list — answer is "full variable axis via `wght.css` only".

---

## Color

Docs site mirrors the marketing primary blue (OKLCH hue 250). Color contract is split into two parallel concerns: (a) Starlight's three accent slots, and (b) the full 50–900 marketing palette declared as `--primary-*` custom properties so custom shell components can reference any stop.

### Color contract

| Role | Value | Usage |
|------|-------|-------|
| Dominant (60%) — light | `--sl-color-bg` (Starlight default white in light mode) | Page background, content surface |
| Dominant (60%) — dark | `--sl-color-bg` (Starlight default near-black in dark mode) | Page background, content surface |
| Secondary (30%) — light | `--sl-color-bg-nav`, `--sl-color-bg-sidebar`, `--sl-color-gray-6` | Nav bar, sidebar, hairlines |
| Secondary (30%) — dark | `--sl-color-bg-nav`, `--sl-color-bg-sidebar`, `--sl-color-gray-6` | Nav bar, sidebar, hairlines |
| Accent (10%) | `--primary-700` = `oklch(0.46 0.16 250)` | Body links, focus ring, breadcrumb separator, "404" mark, primary "Edit this page" link, `<kbd>` border |
| Destructive | not used in this phase | No destructive surfaces ship in Phase 224 |

**Accent reserved for** (explicit, finite list — not "all interactive elements"):
1. Body link text (Starlight `<a>` inside `.sl-markdown-content`) — via `--sl-color-accent` aliased to `--primary-700` (D-03)
2. The 404 page brand "404" mark
3. Breadcrumb separator characters
4. Focus-visible ring on custom-component anchors and buttons (back-link, 404 cards)
5. Active sidebar link (Starlight default — uses `--sl-color-text-accent`)
6. Search button border in header (Starlight default — uses `--sl-color-accent` for focus state)
7. Page title visible accent stripe (Starlight default — none in 0.38.4)

Accent is NOT used for: 404 category-card backgrounds, body text, neutral icons, last-updated timestamp, edit-this-page label, breadcrumb item text, ordinary headings.

### Starlight accent slots (the only 3 slots Starlight 0.38.4 actually consumes)

> **Calibration note for downstream agents:** The CONTEXT.md framing of "50–950 token bridge" mixes two concepts. Raw Starlight 0.38.4 has exactly THREE accent stops (`--sl-color-accent-low`, `--sl-color-accent`, `--sl-color-accent-high`). The 50–950 scale only exists when `@astrojs/starlight-tailwind` is installed — and CONTEXT.md D-05 explicitly forbids that plugin. We satisfy BRAND-01 by (a) mapping all three Starlight slots to GeoLens primary stops AND (b) declaring the full marketing 50–900 palette as `--primary-*` custom properties for use by custom shell components and BRAND-04's drift-detection script.

| Slot | Light mode | Dark mode | Source |
|------|-----------|-----------|--------|
| `--sl-color-accent-low` | `oklch(0.93 0.05 250)` (`--primary-100`) | `oklch(0.30 0.10 250)` (`--primary-900`) | Tinted backgrounds (search-result focus, badge default-bg) |
| `--sl-color-accent` | `oklch(0.46 0.16 250)` (`--primary-700`, NOT `-500`) | `oklch(0.70 0.16 250)` (`--primary-400`) | Body links, focus rings, badge borders |
| `--sl-color-accent-high` | `oklch(0.30 0.10 250)` (`--primary-900`) | `oklch(0.93 0.05 250)` (`--primary-100`) | Hover states, large-headline accents, badge tinted-bg |

**WCAG calibration of `--sl-color-accent`:** D-03 locks this to `--primary-700` (NOT `--primary-500`). Marketing's own `global.css:50–55` comment block flags primary-500 (`oklch(0.55 0.18 250)`) as decorative-only — only primary-700 (`oklch(0.46 0.16 250)`) passes 4.5:1 against white for 14px-and-up body text. Aliasing `--sl-color-accent` to `--primary-700` ensures Starlight's body link colour passes WCAG AA without further tuning.

### Marketing palette mirrored (BRAND-01 + BRAND-04 source of truth)

These declarations live in `:root` and `:root[data-theme='dark']` of `docs/src/styles/custom.css` so custom components (DocsHeader, Breadcrumbs, 404 page) can reference any stop. They are also the keys BRAND-04's `check-token-sync.sh` greps from both `getgeolens.com/src/styles/global.css` and `getgeolens.com/docs/src/styles/custom.css`.

```css
/* Light mode — copy verbatim from getgeolens.com/src/styles/global.css :root */
--primary-50:  oklch(0.97 0.02 250);
--primary-100: oklch(0.93 0.05 250);
--primary-200: oklch(0.87 0.09 250);
--primary-300: oklch(0.78 0.13 250);
--primary-400: oklch(0.70 0.16 250);
--primary-500: oklch(0.55 0.18 250);
--primary-600: oklch(0.48 0.18 250);
--primary-700: oklch(0.46 0.16 250);
--primary-800: oklch(0.38 0.13 250);
--primary-900: oklch(0.30 0.10 250);
```

**D-02 reconciliation:** the prompt specifies an extrapolated `--sl-color-accent-950: oklch(0.22 0.07 250)`. Since raw Starlight does NOT expose a `-950` slot, this token MUST still be declared as part of the `--primary-*` family (NOT the `--sl-color-accent-*` family). Add `--primary-950: oklch(0.22 0.07 250)` (continues the 800→900 trend: lightness drops ~0.08, chroma drops ~0.03 per step). This satisfies D-02's intent while staying within Starlight's actual token shape. The drift script in D-06 explicitly skips this stop because it has no marketing source.

### Dark mode mapping (D-04)

Both `[data-theme='light']` and `[data-theme='dark']` blocks must declare the full `--primary-*` palette identically (the OKLCH values are absolute — they don't change with theme). Only the three `--sl-color-accent-*` slots flip orientation between light and dark per the table above.

**Verification deliverable (D-12):** light + dark screenshot pair of the homepage and the Quickstart placeholder page, attached to the phase summary, confirming WCAG AA contrast on body text, link text, and focus indicators in BOTH modes.

---

## Copywriting Contract

Phase 224 ships two interactive surfaces with user-facing copy: the custom 404 page and the cross-site nav links. Plus a microcopy contract for placeholder index pages so the sidebar autogenerate has something to render.

| Element | Copy |
|---------|------|
| Marketing-side "Docs" nav link | `Docs` (single word, matching existing nav link weight; href: `https://docs.getgeolens.com`; `rel="noopener"`; no external-link icon per D-26) |
| Docs-side back-link to marketing | `← getgeolens.com` (literal, lowercase domain, U+2190 leftwards-arrow, single space; href: `https://getgeolens.com`; `rel="noopener"`; no external-link icon per D-26) |
| 404 brand mark | `404` |
| 404 heading | `Page not found` |
| 404 body copy | `The page you're looking for might have moved to a different section.` |
| 404 search prompt label | `Search the docs` (placeholder text inside the embedded search input) |
| 404 category card 1 — title | `Quickstart` |
| 404 category card 1 — description | `Stand up GeoLens with Docker Compose.` |
| 404 category card 1 — href | `/guides/quickstart` |
| 404 category card 2 — title | `User Guide` |
| 404 category card 2 — description | `Search, map, and export your data.` |
| 404 category card 2 — href | `/guides/user` |
| 404 category card 3 — title | `Admin Guide` |
| 404 category card 3 — description | `Configure auth, backups, and OAuth.` |
| 404 category card 3 — href | `/guides/admin` |
| 404 category card 4 — title | `API Reference` |
| 404 category card 4 — description | `OGC, REST, and OpenAPI endpoints.` |
| 404 footer link | `Or head back to getgeolens.com` (href: `https://getgeolens.com`; `rel="noopener"`) |
| Placeholder index pages (4 files: quickstart, user, admin, api) — title (frontmatter) | `{Group label} (coming soon)` — i.e. `Quickstart (coming soon)`, `User Guide (coming soon)`, `Admin Guide (coming soon)`, `API Reference (coming soon)` |
| Placeholder index pages — body | Single line: `Content for this section ships in Phase {N}.` (Phase 226 for quickstart, 227 for user/admin, 225 for api). NO TOC, NO hero, NO front-matter `pagefind: false` (the placeholder must NOT poison search). |
| Empty state (no equivalent in Phase 224) | not applicable — Phase 224 ships no data-driven UI |
| Error state (no equivalent in Phase 224) | not applicable — Phase 224 ships no data-driven UI |
| Destructive confirmation | not applicable — Phase 224 ships no destructive actions |

**Tone:** match marketing's `Nav.astro:79–88` register — short, declarative, Title Case for nav items and card titles, sentence case + period for descriptions. No marketing jargon ("blazingly fast", "delightful", "magical"). No emoji, no exclamation marks except the 404 page. Match the lowercase domain treatment in the back-link (`getgeolens.com` not `GetGeoLens.com`) — this is the Cloudflare/Vercel/Stripe convention noted in D-25.

**Sidebar group labels (D-13):** `Quickstart`, `User Guide`, `Admin Guide`, `API Reference` — these are already the labels in `astro.config.mjs:31, 35, 39, 43` from Phase 223. Phase 224 adds zero label changes; only the implicit autogenerate now has placeholder content to render. No label re-spec needed.

---

## Component Inventory (custom shell components shipped this phase)

These are the visible-component contracts the executor must build. Each row is a complete spec — markup pattern, behavior, accessibility role, and override-path.

### `<Breadcrumbs.astro>` (SHELL-02 / D-17)

**Path:** `getgeolens.com/docs/src/components/Breadcrumbs.astro`

**Override target:** `components.PageTitle` in `astro.config.mjs`. The `PageTitle` slot in Starlight's `Page.astro:108–113` renders BEFORE `MarkdownContent` and is the cleanest insertion point for breadcrumb chrome. Override `PageTitle` with a wrapper that renders `<Breadcrumbs />` then the default `<PageTitle />` — preserves Starlight's `<h1>` semantics and the page-title id (`PAGE_TITLE_ID`) used by the skip-link.

**Markup pattern (lock):**

```astro
---
import type { Props } from '@astrojs/starlight/props';
import Default from '@astrojs/starlight/components/PageTitle.astro';

const segments = Astro.url.pathname
  .split('/')
  .filter(Boolean)
  // Drop trailing-slash empties; Starlight's default is trailingSlash: 'ignore'
  .map((segment, index, arr) => {
    const href = '/' + arr.slice(0, index + 1).join('/') + '/';
    const label = segment
      .replace(/-/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase());
    const isLast = index === arr.length - 1;
    return { label, href, isLast };
  });

// Hide breadcrumbs on the homepage (no segments) and on top-level group landings
// where the breadcrumb would only show "Guides → Quickstart" — redundant with the sidebar
const showBreadcrumbs = segments.length >= 2;
---

{showBreadcrumbs && (
  <nav class="breadcrumbs" aria-label="breadcrumb">
    <ol>
      <li><a href="/">Docs</a></li>
      {segments.map(({ label, href, isLast }) => (
        <li>
          <span class="separator" aria-hidden="true">/</span>
          {isLast
            ? <span aria-current="page">{label}</span>
            : <a href={href}>{label}</a>
          }
        </li>
      ))}
    </ol>
  </nav>
)}

<Default {...Astro.props} />
```

**Locked decisions for the Discretion item "Exact Breadcrumbs markup":**
- Outer element: `<nav aria-label="breadcrumb">` (semantic landmark, screen reader announces "breadcrumb")
- List element: `<ol>` (ordered — breadcrumbs are sequential)
- Separator character: `/` (forward slash, U+002F) wrapped in `<span class="separator" aria-hidden="true">` (decorative; screen readers ignore — list semantics convey order)
- Current page: `<span aria-current="page">` (NOT an `<a>`; current page is not navigable)
- "Docs" root anchor always present — links to `/` (homepage)
- Segment label transform: kebab-case → Title Case (`oauth-setup` → `Oauth Setup`; an explicit override map is OUT OF SCOPE for this phase — labels are good-enough)
- Hidden when fewer than 2 path segments (homepage, top-level group landings)

**Styling (locked):**
```css
.breadcrumbs {
  margin-bottom: 0.5rem;
  font-size: var(--sl-text-sm);
  color: var(--sl-color-gray-3);
}
.breadcrumbs ol {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem 0.5rem;
}
.breadcrumbs li {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem 0.5rem;
}
.breadcrumbs a {
  color: var(--sl-color-gray-3);
  text-decoration: none;
}
.breadcrumbs a:hover {
  color: var(--sl-color-text-accent);
  text-decoration: underline;
}
.breadcrumbs .separator {
  color: var(--sl-color-gray-4);
  user-select: none;
}
.breadcrumbs [aria-current="page"] {
  color: var(--sl-color-white); /* Starlight's --sl-color-white is theme-flipped: dark-mode white-text, light-mode dark-text */
  font-weight: 500;
}
```

**Accessibility:** `nav[aria-label="breadcrumb"]` is the WAI-ARIA pattern. The trailing `aria-current="page"` marks the active leaf. Separator characters carry `aria-hidden="true"` to avoid screen-reader noise. Focus-visible inherits `--primary-700` outline from Starlight's defaults (already 2px solid).

### `<DocsHeader.astro>` (SHELL-05 / D-25 + Cmd+K hook from D-29)

**Path:** `getgeolens.com/docs/src/components/DocsHeader.astro`

**Override target:** `components.Header` in `astro.config.mjs`.

**Pattern (lock):**

```astro
---
import type { Props } from '@astrojs/starlight/props';
import Default from '@astrojs/starlight/components/Header.astro';
---

<div class="docs-header-wrapper">
  <a class="back-link" href="https://getgeolens.com" rel="noopener">
    <span aria-hidden="true">&#x2190;</span>
    <span>getgeolens.com</span>
  </a>
  <Default {...Astro.props} />
</div>

<style>
  .docs-header-wrapper {
    display: contents; /* Pass through Starlight's grid layout */
  }
  .back-link {
    /* Place at start of header grid — Starlight's grid template puts site title at column 1 */
    grid-column: 1 / 2;
    align-self: center;
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    font-size: var(--sl-text-sm);
    font-weight: 400;
    color: var(--sl-color-gray-3);
    text-decoration: none;
    padding: 0.25rem 0.5rem;
    border-radius: 0.25rem;
  }
  .back-link:hover {
    color: var(--sl-color-text-accent);
    background-color: var(--sl-color-gray-6);
  }
  .back-link:focus-visible {
    outline: 2px solid var(--sl-color-accent);
    outline-offset: 2px;
  }
  /* On narrow viewports, hide the domain label to save space — keep the arrow as a back affordance */
  @media (max-width: 50rem) {
    .back-link span:last-child {
      display: none;
    }
  }
</style>

<script is:inline>
  // D-29: Cmd+K / Ctrl+K hook.
  // Starlight 0.38.4's Search component natively binds Cmd+K (see Search.astro:118-124).
  // This script is therefore a NO-OP duplicate-guard ONLY — it does not introduce a
  // second listener. The block is included so future Starlight upgrades (which may
  // remove or rebind Cmd+K) do not silently regress this contract.
  // The "/" shortcut is NOT bound by Starlight or by this site (D-30: leave / free
  // for type-to-search inside input fields).
  // If you find yourself needing to add a manual binding for Cmd+K, the API is:
  //   document.querySelector('button[data-open-modal]')?.click();
</script>
```

**Locked decisions for Discretion item "Exact Cmd+K hook implementation":**
- **Cmd+K is already bound by Starlight 0.38.4** at `node_modules/@astrojs/starlight/components/Search.astro:118-124` (`window.addEventListener('keydown', (e) => { if ((e.metaKey || e.ctrlKey) && e.key === 'k') { ... openModal(); }})`). Phase 224 must NOT add a duplicate listener.
- **`/` is NOT bound by Starlight 0.38.4** — confirmed by grep for `key === '/'` in `node_modules/@astrojs/starlight/components/`. The CONTEXT.md prompt's claim that "`/` is Starlight default" was investigated and found to be incorrect for this version. **Per D-30 we do NOT add a `/` binding** (would conflict with type-to-search inside text inputs).
- **Verification deliverable:** the executor verifies the Cmd+K shortcut works by manual probe (`Cmd+K` opens dialog, `Esc` closes), captured in the phase verification doc. NO Phase-224 client-side keydown listener is added.
- **Fallback API for future use:** if a future Starlight upgrade removes the native Cmd+K binding, the recovery is `document.querySelector('button[data-open-modal]')?.click();` documented as a comment block in `DocsHeader.astro`.

**Why a wrapper instead of a from-scratch header:** Starlight's `Header.astro` (verified at `node_modules/@astrojs/starlight/components/Header.astro:17-31`) uses a 3-column CSS Grid with the site title in column 1, search box in column 2, and right-cluster (social, theme select, language) in column 3. Replacing it from scratch would re-implement the responsive grid math (`--__sidebar-width`, `--__main-column-fr`, etc.). Wrapping with `display: contents` plus a `grid-column: 1 / 2` back-link slot preserves Starlight's grid intact while injecting the back-link before the site title.

### `<404.astro>` (SHELL-03 / D-21–D-23)

**Path:** `getgeolens.com/docs/src/pages/404.astro` (Astro page, NOT Starlight content collection — Starlight's content schema requires a slug, and 404 is a special page)

**Layout (lock — vertical stack, max-width 640px, centered):**

```
┌─────────────────────────────────────────┐
│                                         │  ← 3rem padding-top
│             404                         │  ← 64px brand mark, --primary-700, weight 700
│                                         │  ← 2rem margin-bottom
│      Page not found                     │  ← h1, --sl-text-h2, weight 600
│                                         │  ← 1rem margin-bottom
│  The page you're looking for might      │  ← p, 16px, weight 400, line-height 1.5
│  have moved to a different section.     │
│                                         │  ← 2rem margin-bottom
│  ┌──────────────────────────────────┐   │
│  │ [search this site...           ] │   │  ← Pagefind search input, full width
│  └──────────────────────────────────┘   │
│                                         │  ← 3rem margin-bottom
│  ┌──────────┐  ┌──────────┐             │
│  │Quickstart│  │User Guide│             │  ← 4 cards in 2×2 grid (mobile: 1 column)
│  │subtitle  │  │subtitle  │             │
│  └──────────┘  └──────────┘             │
│  ┌──────────┐  ┌──────────┐             │
│  │ Admin    │  │   API    │             │
│  │subtitle  │  │subtitle  │             │
│  └──────────┘  └──────────┘             │
│                                         │  ← 2rem margin-bottom
│  Or head back to getgeolens.com         │  ← link, 14px, --sl-color-gray-3
│                                         │  ← 4rem padding-bottom
└─────────────────────────────────────────┘
```

**Locked decisions for Discretion item "Exact 404 page CSS":**
- Container: `max-width: 40rem; margin: 0 auto; padding: 3rem 1rem 4rem;` (centered, comfortable reading width)
- Background: inherit from Starlight (`--sl-color-bg`) — no card-on-background visual; the 404 page lives flush with site chrome
- Brand mark: `font-size: var(--sl-text-6xl); font-weight: 700; color: var(--primary-700); line-height: 1; margin-bottom: 2rem;`
- Heading: `font-size: var(--sl-text-h2); font-weight: 600; line-height: var(--sl-line-height-headings); margin-bottom: 1rem;`
- Body copy: `font-size: var(--sl-text-base); color: var(--sl-color-gray-2); line-height: 1.5; margin-bottom: 2rem;`
- Search wrapper: `margin-bottom: 3rem;` — REUSE Starlight's `<Search />` component via `import Search from 'virtual:starlight/components/Search'` so styling, translations, and Pagefind config are inherited.
- Card grid: `display: grid; grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr)); gap: 1rem;` (responsive: 1 col on narrow, 2 col on wide)
- Card: `display: block; padding: 1rem; border: 1px solid var(--sl-color-gray-5); border-radius: 0.5rem; background-color: var(--sl-color-black); text-decoration: none; color: inherit;` (Starlight's `--sl-color-black` is theme-flipped: white in light mode, near-black in dark mode)
- Card hover: `border-color: var(--sl-color-accent); background-color: var(--sl-color-accent-low);`
- Card focus-visible: `outline: 2px solid var(--sl-color-accent); outline-offset: 2px;`
- Card title: `font-size: var(--sl-text-base); font-weight: 600; line-height: 1.2; margin-bottom: 0.25rem; color: var(--sl-color-white);`
- Card description: `font-size: var(--sl-text-sm); color: var(--sl-color-gray-3); line-height: 1.5;`
- Footer link: `display: inline-block; margin-top: 2rem; font-size: var(--sl-text-sm); color: var(--sl-color-gray-3); text-decoration: underline;`
- Footer link hover: `color: var(--sl-color-text-accent);`
- All colors use design tokens — NO hardcoded `#hex` or `rgb()` per D-23 / Discretion clause "must use design tokens — no hardcoded colors"

**Frontmatter:** since `404.astro` is an Astro page (not a content-collection MDX entry), it uses Starlight's `<StarlightPage>` layout component to inherit chrome:

```astro
---
import StarlightPage from '@astrojs/starlight/components/StarlightPage.astro';
import Search from 'virtual:starlight/components/Search';
---
<StarlightPage frontmatter={{ title: 'Page not found', template: 'splash' }}>
  <!-- markup above -->
</StarlightPage>
```

`template: 'splash'` removes the sidebar and TOC, giving the 404 page full width — Starlight's documented pattern for landing-style pages.

**Search component reuse:** verified at `node_modules/@astrojs/starlight/components/Search.astro:18-30` — `<Search />` is a custom-element-wrapped button that opens a Pagefind dialog. Embedding it inside the 404 page gives identical search UX to the header's search button. The button is auto-styled at full width below 50rem viewport (`Search.astro:181-201`) which suits the 404 layout.

**Indexability:** the 404 page is auto-excluded from Pagefind by Starlight (verified at `node_modules/@astrojs/starlight/components/Page.astro:36-39`: `pagefindEnabled = entry.id !== '404' && !entry.id.endsWith('/404') && data.pagefind !== false`). No additional config needed.

### Pagefind code-block weighting (SEARCH-02 / D-28)

**Locked decision for Discretion item "Code-component override mechanism for `data-pagefind-weight`":**

**Mechanism: Astro rehype plugin** (NOT a Starlight `Code` component override — that override path does not exist in Starlight 0.38.4; verified at the components-override list in `node_modules/@astrojs/starlight/index.ts` and the Context7 docs surface).

**Why rehype, not Expressive Code:** Starlight uses Expressive Code as the renderer, but injecting `data-pagefind-weight` would require an Expressive Code plugin (heavier surface, more API to learn, brittle across Starlight upgrades). A 12-line rehype plugin that visits `<pre>` nodes and adds the attribute is the smallest possible footprint.

**Plugin path:** `getgeolens.com/docs/plugins/rehype-pagefind-code-weight.mjs`

**Plugin contract:**

```javascript
// Adds data-pagefind-weight="0.1" to all <pre> nodes in built HTML.
// Code stays findable but ranks 1/100 of normal prose (Pagefind weighting is quadratic;
// 0.1^2 = 0.01 effective rank multiplier).
// Per Pagefind official guidance:
// https://pagefind.app/docs/v1-migration/#changes-to-search-relevancy-and-ranking
import { visit } from 'unist-util-visit';

export default function rehypePagefindCodeWeight() {
  return (tree) => {
    visit(tree, 'element', (node) => {
      if (node.tagName === 'pre') {
        node.properties = node.properties || {};
        node.properties['data-pagefind-weight'] = '0.1';
      }
    });
  };
}
```

**Wiring (locked):** in `astro.config.mjs`, add the plugin to Astro's `markdown.rehypePlugins`:

```javascript
import rehypePagefindCodeWeight from './plugins/rehype-pagefind-code-weight.mjs';
// ...
export default defineConfig({
  // ...
  markdown: {
    rehypePlugins: [rehypePagefindCodeWeight],
  },
  integrations: [/* starlight, sitemap */],
});
```

**Why weight 0.1 (not 0.5 from Pagefind's recommended default):** CONTEXT.md D-28 explicitly locks 0.1. Pagefind's docs recommend 0.5 as a starting point; D-28's stricter 0.1 reflects the milestone's heavy code-content forecast (API reference, install commands, OGC endpoints) and the explicit goal of "code stays findable but prose ranks above". The quadratic curve means 0.1 is 25× weaker than 0.5 — code must REALLY underperform prose to be the right call. We trust the CONTEXT decision; if Phase 226 surfaces relevance complaints, planner can revise.

**Verification:** add an assertion to `verify-build.sh`: `grep -E 'data-pagefind-weight=\"0\.1\"' dist/**/*.html` returns at least one match on any built page that contains a code block (the placeholder index pages have none, so this assertion runs against any built guide page once content lands; for Phase 224's verify run, the assertion is "no `<pre>` without the attribute" which is trivially true since no `<pre>` blocks exist in placeholder content).

---

## Registry Safety

| Registry | Blocks Used | Safety Gate |
|----------|-------------|-------------|
| (no registry — Astro Starlight, not shadcn) | not applicable | not applicable |

No third-party shadcn-style registries are in scope. The components added in this phase (`Breadcrumbs.astro`, `DocsHeader.astro`, `404.astro`, `rehype-pagefind-code-weight.mjs`) are project-authored Astro components inspired by published Starlight patterns from the Starlight 0.38.4 docs (https://starlight.astro.build/guides/overriding-components/). No third-party block was copy-pasted; no `npx shadcn add` invocation is part of this phase.

---

## llms.txt Stub (SEO-04 / D-31, D-32, D-33)

**Path:** `getgeolens.com/docs/public/llms.txt`

**Locked content (verbatim):**

```
# GeoLens Documentation

> Documentation for the GeoLens self-hosted GIS data catalog. Covers install, user guide, admin guide, and OGC/REST API reference. Single canonical home for all GeoLens user-facing documentation; supersedes legacy backend/docs/{install,admin}.md files.

## Guides

- [Quickstart](https://docs.getgeolens.com/guides/quickstart): Stand up GeoLens with Docker Compose and complete first-login flow.
- [User Guide](https://docs.getgeolens.com/guides/user): Search, dataset detail, map builder, collections, imports, and exports.
- [Admin Guide](https://docs.getgeolens.com/guides/admin): User management, OAuth/OIDC, settings, backups, monitoring, and cloud deployment.
- [API Reference](https://docs.getgeolens.com/guides/api): OGC API (Common, Records, Features, STAC), REST endpoints with auth examples.
```

**verify-build.sh additions (D-33):**

```bash
# llms.txt presence + URL coverage
test -f dist/llms.txt || { echo "FAIL: dist/llms.txt missing"; exit 1; }
for path in /guides/quickstart /guides/user /guides/admin /guides/api; do
  grep -qF "https://docs.getgeolens.com${path}" dist/llms.txt \
    || { echo "FAIL: llms.txt missing URL ${path}"; exit 1; }
done
```

---

## Cross-Site Nav Contract (SHELL-05 / D-24, D-26)

### Marketing-side: `Nav.astro` patch

**Path:** `getgeolens.com/src/components/layout/Nav.astro`

**Insertion point:** between the existing `Quickstart` link (line 79) and the closing `</div>` of the desktop subnav cluster (line 88). After Quickstart, before the GitHub icon.

**Markup (lock):**

```astro
<a
  href="https://docs.getgeolens.com"
  rel="noopener"
  class="text-sm font-medium transition-colors no-underline nav-link"
>
  Docs
</a>
```

**Locked details:**
- NO `target="_blank"` — same brand, same window navigation (D-26 implicit; matches the Cloudflare/Vercel docs-subdomain pattern)
- NO `aria-current` logic — different subdomain means no path-based active state on the marketing side. The link is always in the `nav-link` (inactive) state when on marketing.
- NO external-link icon (D-26)
- `rel="noopener"` only — `rel="noreferrer"` is omitted because we WANT the docs site to know the user came from marketing (Referer header is one of two future cross-site analytics signals; the other being shared GA4 Measurement ID in Phase 228)
- Class list matches existing `Nav.astro:62, 73` pattern — `text-sm font-medium transition-colors no-underline nav-link`

### Docs-side: `<DocsHeader.astro>` (covered above in Component Inventory)

`← getgeolens.com` link in left cluster of header. `rel="noopener"`, no external-link icon.

---

## Token Drift Detection Contract (BRAND-04 / D-06, D-07, D-08)

This is a CI behavior contract, not a UI surface — but it's the gate that prevents brand drift between marketing and docs.

**Script:** `getgeolens.com/docs/scripts/check-token-sync.sh`

**Behavior:**
- Reads `getgeolens.com/src/styles/global.css` (marketing source-of-truth)
- Reads `getgeolens.com/docs/src/styles/custom.css`
- For each stop in {50, 100, 200, 300, 400, 500, 600, 700, 800, 900}, greps the OKLCH triplet from each file
- Normalizes whitespace and decimal precision (`0.55` ≡ `0.550`)
- Asserts the triplets match between files
- Skips stop 950 (extrapolated, no marketing source — `--primary-950` is docs-only)
- Exits 1 with a clear diff message on mismatch
- Exits 0 silently on match

**Wiring (D-07):** step in `docs-ci.yml` between `astro check` and `npm run build`. Failing this script fails the build (and therefore the deploy). Same load-bearing posture as Phase 223's `verify-build.sh`.

**Documentation (D-08):** script header comment block:
```bash
#!/usr/bin/env bash
# check-token-sync.sh — BRAND-04 runtime enforcement.
#
# Asserts that the OKLCH primary palette in:
#   getgeolens.com/src/styles/global.css      (marketing source-of-truth)
# matches:
#   getgeolens.com/docs/src/styles/custom.css (docs mirror)
# for stops 50, 100, 200, 300, 400, 500, 600, 700, 800, 900.
#
# Stop 950 is extrapolated for docs-only and intentionally not synced.
#
# Phase 227 (CONTRIBUTING.md update) documents the maintenance convention prose-side.
```

---

## Inter Font Pin Verification (BRAND-02 / D-09, D-10)

**Pin (lock):** `@fontsource-variable/inter@^5.2.8` (matches marketing's `getgeolens.com/package.json:21` exactly)

**Wiring:** in `getgeolens.com/docs/package.json`, add to `dependencies`:
```json
"@fontsource-variable/inter": "^5.2.8"
```

**Self-host posture (D-10):** the `@fontsource-variable/inter/wght.css` import resolves to a node_modules CSS file referencing local woff2 files bundled into Vite's asset pipeline. NO Google Fonts CDN reference, NO `<link rel="preconnect" href="https://fonts.gstatic.com">`. Verifiable post-build by `! grep -r "fonts.gstatic.com\|fonts.googleapis.com" dist/`.

---

## Verify-Build Additions Summary

The `verify-build.sh` script gains three new assertions in this phase:

1. `dist/llms.txt` exists and contains all four `/guides/` URLs (D-33)
2. Inter font CSS is bundled with no Google Fonts CDN reference (D-10): `! grep -rqF "fonts.gstatic.com" dist/`
3. Token drift `check-token-sync.sh` runs as a separate CI step BEFORE `verify-build.sh` (D-07) — not a verify-build assertion, but documented here for executor's CI ordering reference

The existing assertions from Phase 223 (canonical URL, noindex meta, sitemap-index.xml, _redirects, no flat URLs in HTML, robots.txt Disallow) MUST NOT be removed or weakened (CONTEXT.md "Phase 223 verify-build.sh is the load-bearing build-artifact gate").

---

## Pre-Population Source Map

| Field | Source |
|-------|--------|
| Spacing scale (multiples of 4) | Default + Starlight tokens preserved |
| Typography (Inter Variable, body inheritance) | CONTEXT.md D-09, D-10; Starlight props.css inspection; marketing parity |
| Color contract — accent slot | CONTEXT.md D-01, D-02, D-03, D-04 + Starlight props.css inspection (calibrated: 3-stop, not 11-stop) |
| Color contract — `--primary-*` palette | `getgeolens.com/src/styles/global.css:57–70` verbatim mirror |
| `--primary-950` extrapolation | CONTEXT.md D-02; reframed as `--primary-950` instead of `--sl-color-accent-950` after Starlight API reconciliation |
| Cmd+K binding | Starlight Search.astro:118-124 inspection (already bound natively); CONTEXT.md D-29, D-30 |
| Slash binding | Starlight grep (NOT bound natively); CONTEXT.md D-30 |
| Code-block weighting mechanism | Starlight components-override surface inspection (no `Code` slot exists); Pagefind v1 migration docs |
| Breadcrumbs markup | CONTEXT.md "Claude's Discretion" — locked here |
| 404 page CSS | CONTEXT.md "Claude's Discretion" — locked here |
| Cmd+K hook | CONTEXT.md "Claude's Discretion" — locked here (no manual binding needed) |
| Inter weight subset | CONTEXT.md "Claude's Discretion" — locked here (full variable axis via wght.css) |
| Cross-site nav copy | CONTEXT.md D-24, D-25; marketing Nav.astro pattern parity |
| 404 copy | CONTEXT.md D-22 |
| llms.txt content | CONTEXT.md D-31, D-32 |
| Placeholder index titles + bodies | CONTEXT.md D-35; new microcopy locked here |

---

## Checker Sign-Off

- [ ] Dimension 1 Copywriting: PASS — all interactive surfaces have explicit copy; tone matches marketing register; no marketing jargon; placeholder titles signal "coming soon" without being uncommunicative
- [ ] Dimension 2 Visuals: PASS — every custom component has locked markup, layout sketch, hover/focus states, and accessibility annotations
- [ ] Dimension 3 Color: PASS — accent reserved for finite, explicit list; 60/30/10 split preserved; OKLCH palette mirrored verbatim from marketing; no hardcoded hex/RGB in any custom component CSS
- [ ] Dimension 4 Typography: PASS — Inter Variable pinned to marketing version; body content inheritance from Starlight noted out of scope; new surfaces use Starlight tokens; no arbitrary px sizes
- [ ] Dimension 5 Spacing: PASS — all custom-component spacing fits multiples-of-4 scale; Starlight tokens preserved for chrome
- [ ] Dimension 6 Registry Safety: PASS — not applicable (no shadcn registry in this stack)

**Approval:** pending

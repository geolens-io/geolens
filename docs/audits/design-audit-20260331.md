# Design System & Accessibility Audit — 2026-03-31

## Scorecard

| Dimension | Grade | Violations | Guide Section |
|-----------|-------|------------|---------------|
| **Token Conformance** | **B** | 10 | GUIDE-01 |
| **Component Patterns** | **A** | 1 | GUIDE-03 |
| **Layout & Spacing** | **B** | 9 | GUIDE-04 |
| **Map Conventions** | **A** | 1 | GUIDE-05 |
| **Dark Mode** | **B** | 8 | GUIDE-06 |
| **Accessibility (WCAG)** | **D** | 2 critical, 3 partial | WCAG 2.1 AA |
| **Build Configuration** | **A** | 0 | Anti-patterns |

**Design System Drift Score: 92%** (239 of 260 components/pages violation-free)

### WCAG 2.1 AA Compliance Summary

| Level | Total Criteria | Pass | Fail | Partial | N/A |
|-------|---------------|------|------|---------|-----|
| A     | 10            | 9    | 0    | 1       | 0   |
| AA    | 10            | 7    | 1    | 2       | 0   |
| AAA   | 3             | 1    | 1    | 1       | 0   |
| **Total** | **23**    | **17** | **2** | **4** | **0** |

---

## Executive Summary

GeoLens achieves **92% design system adoption** across 260 components and pages — well above the 90% healthy threshold. The Tailwind v4 CSS-first build configuration is flawless, component patterns are near-perfect, and map conventions are exemplary. The primary areas of concern are:

1. **WCAG contrast failure** — `text-muted-foreground` fails the 4.5:1 minimum ratio on light backgrounds, affecting 500+ UI instances. This is the single highest-impact finding.
2. **Missing `prefers-reduced-motion` support** — Shimmer and spinner animations ignore the user's motion preference, a WCAG 2.3.3 failure.
3. **Scattered hardcoded colors** — LegendWidget uses fallback hex/rgba values instead of tokens or MAP_COLORS constants.
4. **Minor spacing drift** — 7 instances of `space-y-3` / `gap-3` where the guide specifies `space-y-4` / `gap-4`.

Token sync between the design guide and `index.css` is perfect — zero mismatches.

---

## 1. Design Token Conformance

### 1a. Hardcoded Colors

| File:Line | Value | Context | Severity |
|-----------|-------|---------|----------|
| `components/map-widgets/builtin/LegendWidget.tsx:75` | `#888` | Circle color fallback | P1 |
| `components/map-widgets/builtin/LegendWidget.tsx:110` | `#888` | Line color fallback | P1 |
| `components/auth/OAuthButtons.tsx:15,19,23,27` | `#4285F4`, `#34A853`, `#FBBC05`, `#EA4335` | Google logo SVG fills | P2 |
| `components/auth/OAuthButtons.tsx:36-39` | `#F25022`, `#00A4EF`, `#7FBA00`, `#FFB900` | Microsoft logo SVG fills | P2 |

**Note:** OAuthButtons hex values are third-party brand colors embedded in inline SVGs. Recommend adding a guide exemption for brand identity SVGs rather than tokenizing them.

### 1b. Raw Palette Classes

**No violations found.** All status-related palette classes are correctly centralized in `status-colors.ts`.

### 1c. Token Hierarchy Violations

**No violations found.** No direct `primary-50` through `primary-900` usage outside `index.css`.

### 1d. Shadow & Border Tokens

| File:Line | Value | Context | Severity |
|-----------|-------|---------|----------|
| `components/ui/sidebar.tsx:483` | `shadow-[0_0_0_1px_var(--sidebar-border)]` | Custom 1px inset shadow on sidebar outline variant | P2 |

This is a custom shadow using a CSS var reference, not the standard `shadow-sm/md/lg` utilities. However, it serves as a 1px border simulation — a legitimate edge case with no standard shadow equivalent.

### 1e. Transition Anti-Pattern

**No violations found.** All 13+ transition declarations use targeted property lists (`transition-[color,background-color,box-shadow,border-color,opacity]`). Zero `transition-all` usage.

### 1f. Token Sync (Guide vs. Code)

**All 62 token definitions match perfectly** between `index.css` and `DESIGN-GUIDE.md`:
- Primary scale (10 tokens): match
- Core palette (14 tokens): match
- Utility tokens (4 tokens): match
- Surface hierarchy (4 tokens): match
- Elevation shadows (3 tokens): match
- Status colors (6 tokens): match
- Data visualization (8 tokens): match
- Sidebar tokens (8 tokens): match
- Animations (2 tokens): match

### Hardcoded rgba in Components

| File:Line | Value | Context | Severity |
|-----------|-------|---------|----------|
| `components/map-widgets/builtin/LegendWidget.tsx:56` | `rgba(0,0,0,0.2)` | Border color fallback | P1 |
| `components/map-widgets/builtin/LegendWidget.tsx:96` | `rgba(0,0,0,0.2)` | SVG stroke fallback | P1 |
| `components/map-widgets/builtin/LegendWidget.tsx:161` | `rgba(0,0,0,0.2)` | Border color fallback | P1 |
| `components/builder/layer-adapters/heatmap-adapter.ts:13` | `rgba(0,0,0,0)` | Transparent heatmap ramp start (MapLibre expression) | P2 |

---

## 2. Component Pattern Conformance

### 2a. Button Usage

**320+ usages audited. 1 violation found.**

| File:Line | Issue | Severity |
|-----------|-------|----------|
| `components/drawing/DrawingToolbar.tsx:157-166` | `variant="destructive"` delete button fires `onDeleteFeature` without inline confirmation dialog | P2 |

**Mitigating factor:** Parent component (`DatasetMap`) wraps the callback in an `AlertDialog`. The guide requires the confirmation paired with the button, but the system-level protection exists.

All other destructive buttons (24+) are correctly paired with AlertDialog confirmations. One primary button per form/dialog rule is respected throughout.

### 2b. Card Usage

**131 usages audited. No violations.** `CardAction` used where needed. Sub-component ordering correct. Two intentional `p-0` overrides for autocomplete dropdowns (acceptable).

### 2c. Badge & Status Colors

**311+ usages audited. No violations.** Every status badge sources colors from `status-colors.ts`. Zero hardcoded palette classes in component code.

### 2d. Table Conformance

**15+ table instances. No violations.** `TableHead` uses `text-xs uppercase tracking-wide font-medium`. `TableRow` has `hover:bg-muted/50` and `focus-visible:ring-inset`.

### 2e. State Components (Loading/Empty/Error)

**24 standard component usages found. ~23 custom implementations identified.**

Custom implementations follow correct patterns (spacing, sizing, colors) but could consolidate to `LoadingState`/`EmptyState`/`ErrorState` for consistency. Not violations, but an improvement opportunity.

**Examples of custom patterns:**
- Inline `Loader2 animate-spin` in buttons (12 instances) — appropriate for button loading states
- Manual empty `<div>` with centered text (8 instances) — could use `EmptyState`
- Direct `text-destructive` error divs (3 instances) — could use `ErrorState`

### 2f. Dialog Conformance

**18+ dialog instances. No violations.** `DialogFooter` correctly implements `flex-col-reverse gap-2 sm:flex-row sm:justify-end` for mobile stacking.

---

## 3. Layout & Spacing

### 3a. PageShell Coverage

| Page | PageShell | Status |
|------|-----------|--------|
| SearchPage | `wide` | Pass |
| CollectionsPage | `narrow` | Pass |
| CollectionDetailPage | `narrow` | Pass |
| MapsPage | `narrow` | Pass |
| ImportPage | `default` | Pass |
| DatasetPage | `default` | Pass |
| SettingsPage | `narrow` | Pass |
| MapBuilderPage | N/A (full-viewport) | Exempt |
| PublicMapViewerPage | N/A (full-viewport) | Exempt |
| PublicViewerPage | N/A (full-viewport) | Exempt |
| LoginPage | N/A (hero layout) | Exempt |
| RegisterPage | N/A (centered card) | Exempt |
| NotFoundPage | N/A (minimal) | Exempt |
| Admin pages (7) | AdminLayout | Exempt |

**All standard pages wrapped in PageShell. No inline page-level padding violations.**

### 3b. PageHeader Usage

All standard pages use `PageHeader` or an appropriate specialized header (`DatasetDetailHeader`). Admin pages use `PageHeader` within `AdminLayout`.

### 3c. Spacing Rhythm

| File:Line | Found | Expected | Context | Severity |
|-----------|-------|----------|---------|----------|
| `pages/SearchPage.tsx:184` | `space-y-3` | `space-y-4` | Results list container | P2 |
| `pages/SearchPage.tsx:123` | `md:space-y-5` | `space-y-4` or `space-y-6` | Hero section responsive | P2 |
| `pages/SearchPage.tsx:151` | `gap-3` | `gap-4` | Loading skeleton grid | P2 |
| `pages/CollectionDetailPage.tsx:169` | `space-y-3` | `space-y-4` | Datasets section | P2 |
| `pages/MapsPage.tsx:129` | `gap-3` | `gap-2` | Filter toolbar | P2 |
| `pages/LoginPage.tsx:75` | `gap-3` | `gap-4` | Highlights grid | P2 |
| `pages/MapBuilderPage.tsx:75,105` | `p-3`, `py-3` | `p-4` | Chat panel header/body | P2 |

### 3d. Typography Hierarchy

| File:Line | Found | Expected | Severity |
|-----------|-------|----------|----------|
| `pages/NotFoundPage.tsx:10-11` | `<h1 text-6xl>404</h1><p text-xl>` | `<h1 text-2xl>` or `<h1 text-3xl font-bold>` | P2 |
| `pages/LoginPage.tsx:64` | `text-3xl font-semibold sm:text-4xl` | `text-3xl font-bold` (guide), `text-4xl` undocumented | P2 |

---

## 4. Map Conventions

### 4a. MAP_COLORS Usage

**14 files import MAP_COLORS correctly.** All layer adapters (`fill-adapter.ts`, `line-adapter.ts`, `circle-adapter.ts`) use `MAP_COLORS.default.*` as fallbacks. Zero hardcoded hex in map paint properties outside `map-colors.ts`.

### 4b. MapLibre CSS Rules

| Rule | Status |
|------|--------|
| No CSS transitions/transforms on map containers | Pass |
| No CSS `var()` in paint properties | Pass |
| `minzoom: 1` on vector sources | Pass (verified in `map-sync.ts`, `BuilderMap.tsx`, `ViewerMap.tsx`, `use-map-layers.ts`) |

### 4c. Popup Styling

**Fully compliant.** CSS overrides in `index.css` use `--popover`/`--popover-foreground` tokens. All four tip anchor directions recolored. `FeaturePopup` component excludes `geom`, `geometry`, and `_`-prefixed keys. Scrollable at `max-h-48`.

### 4d. Drawing Toolbar

**Fully compliant.** Position matches exactly (`absolute top-3 left-1/2 -translate-x-1/2 z-10`). Active/inactive variants correct. Button size `sm`. Separators `w-px h-6 bg-border`. Undo shortcut via `use-terra-draw.ts`. Editing action bar displays on feature selection.

### 4e. Basemap & Color Picker

| Component | Finding | Severity |
|-----------|---------|----------|
| BasemapPicker | Uses `grid-cols-4` instead of documented `grid-cols-3` | P2 |
| StyleColorPicker | 16 swatches in `grid-cols-8 gap-1`, active `ring-2 ring-primary ring-offset-1` | Pass |

**Categorical palette sync:** All 8 `MAP_COLORS.categorical` hex values match their `--viz-*` OKLCH token equivalents.

---

## 5. Dark Mode

### 5a. Hardcoded Light-Mode Values

| File:Line | Value | Context | Severity |
|-----------|-------|---------|----------|
| `components/ui/button.tsx:14` | `text-white` | Destructive variant | P2 |
| `components/ui/badge.tsx:16` | `text-white` | Destructive variant | P2 |

Both should use `text-destructive-foreground` which evaluates to white in light mode and has proper dark mode contrast.

### 5b. Excessive dark: Modifiers

**No excessive usage detected.** All `dark:` modifiers are in UI primitives (`button.tsx`, `badge.tsx`, `tabs.tsx`, `input.tsx`, `select.tsx`, `dropdown-menu.tsx`, `checkbox.tsx`, `switch.tsx`) where they serve legitimate contrast purposes (e.g., `dark:bg-input/30`, `dark:bg-destructive/60`).

### 5c. Theme Infrastructure

| Component | Status |
|-----------|--------|
| ThemeProvider + useTheme() | Pass |
| Storage key `geolens-theme` | Pass |
| FOUC prevention script in index.html | Pass |
| System preference detection | Pass |
| Dark class application | Pass |

### 5d. Primary Scale Inversion

**Correct.** Light mode: 50 is lightest (L=0.97), 900 is darkest (L=0.30). Dark mode: 50 is darkest (L=0.25), 900 is lightest (L=0.94). Shadow opacity correctly 3-5x higher in dark mode.

### Opacity-Based Text Hierarchy

6 medium-severity instances where `opacity-50/60/70` is used for text hierarchy instead of `text-muted-foreground`:

| File:Line | Value | Context |
|-----------|-------|---------|
| `components/search/SavedSearches.tsx:148` | `opacity-60` | Delete button visibility |
| `components/ui/select.tsx:47` | `opacity-50` | Chevron icon |
| `components/ui/sheet.tsx:88` | `opacity-70` | Close button |
| `components/ui/dialog.tsx:81` | `opacity-70` | Close button |
| `components/builder/LayerItem.tsx:164` | `opacity-50` | Hidden layer indicator |
| `components/builder/ChatPanel.tsx:380` | `opacity-70` | Applied changes caption |

Additionally, `disabled:opacity-50` is used across 10+ UI primitives for disabled states — this is standard practice and low priority.

---

## 6. WCAG 2.1 AA Compliance

### 6a. Color Contrast

**FAIL (WCAG 1.4.3)** — `--muted-foreground: oklch(0.556 0 0)` on `--background: oklch(1 0 0)` produces approximately **2.2:1** contrast ratio, far below the 4.5:1 minimum for normal text. This token is used in 500+ instances across the UI (filter labels, secondary text, placeholders, captions).

Dark mode passes: `--muted-foreground: oklch(0.708 0 0)` on `--background: oklch(0.145 0.008 250)` yields approximately **6.2:1**.

**Remediation:** Darken the light mode `--muted-foreground` from `oklch(0.556 0 0)` to approximately `oklch(0.40 0 0)` for ~5.5:1 contrast.

**PARTIAL (WCAG 1.4.11)** — `--border: oklch(0.922 0 0)` on white background may fail the 3:1 non-text contrast requirement for UI components. Needs instrument verification.

### 6b. Keyboard Navigation

**Pass.** All interactive elements use semantic HTML (`<button>`, `<input>`, `<a>`) or Radix UI primitives with built-in keyboard support. No `tabIndex` abuse detected. Focus rings present on all interactive components via `focus-visible:ring-2 focus-visible:ring-ring`.

### 6c. ARIA & Semantic HTML

**Partial.** Strengths: semantic `<table>`, `<form>`, `<label>` usage throughout; form inputs properly associated via `htmlFor`; icon buttons have `aria-label` attributes; `<main>` landmark present.

Areas for improvement: Some `<img>` tags lack `alt` text (11 of 18 verified). Async state changes (loading spinners, mutations) lack `aria-live` region announcements. Chat panel correctly uses `role="log" aria-live="polite"`.

### 6d. Text & Content

**Pass.** No fixed pixel font sizes — all typography uses Tailwind rem-based scale. All pages set document titles via `useDocumentTitle()` hook. No heading level skips in main pages.

### 6e. Responsive & Reflow

**Pass.** No fixed-width constraints that prevent 320px reflow. Responsive breakpoints (`sm:`, `md:`, `lg:`) used throughout.

### 6f. Motion & Animation

**FAIL (WCAG 2.3.3)** — `prefers-reduced-motion` is **not supported**. The `shimmer` animation (1.5s infinite, used in skeleton loaders) and `animate-spin` (15+ loading spinners) ignore the user's motion preference.

**Remediation:** Add to `index.css`:
```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```
Or use Tailwind's `motion-safe:` / `motion-reduce:` variants on individual animations.

### 6g. Map Accessibility

**Partial.** MapLibre canvas is inherently non-keyboard-navigable (WebGL limitation). Mitigated by providing a data table tab (`DataTab`) as a non-visual alternative. Drawing toolbar buttons have `aria-label` and `title` attributes. Map container uses `tabIndex={-1}` to exclude from tab order (correct).

Missing: No `aria-live` announcements for drawing mode changes or map state transitions.

---

## 7. Tailwind v4 Configuration

### 7a. No Legacy Config Files

**Pass.** No `tailwind.config.js/ts/cjs/mjs` at project root or `frontend/`.

### 7b. @theme inline

**Pass.** `index.css:189` uses `@theme inline { ... }` — correct for reactive `var()` references.

### 7c. Token Bridge Completeness

**Pass.** 80+ color mappings covering all semantic, primary scale, surface, status, visualization, chart, and sidebar tokens. Shadow tokens (`--shadow-sm/md/lg`) mapped through elevation tokens. Radius utilities computed from base `--radius`.

### 7d. Font Configuration

**Pass.** `@fontsource-variable/inter` imported at `index.css:2` (before `tailwindcss`). `--font-sans` includes `'Inter Variable'`. Body applies `font-sans antialiased`. Package present in `package.json` and `node_modules`.

CSS import order verified: Font (line 2) -> Tailwind (line 5) -> tw-animate-css (line 6) -> custom variant (line 9). Vite uses `@tailwindcss/vite` plugin.

---

## 8. Guide Update Recommendations

Where the code has intentionally diverged from the guide:

| Area | Guide Says | Code Does | Recommendation |
|------|-----------|-----------|----------------|
| BasemapPicker grid | `grid-cols-3 gap-2` | `grid-cols-4 gap-2` | Update guide to reflect 4-column layout (likely changed when 4th basemap was added) |
| Basemap thumbnails | "Inline SVG data URIs, no external PNG assets" | Uses imported PNG assets (`positron.png`, `dark.png`, `osm.png`, `bright.png`) | Update guide — PNGs are higher quality than SVG approximations |
| Brand logo SVGs | Not addressed | OAuthButtons embeds third-party brand hex colors | Add exemption: "Third-party brand colors in inline SVGs are exempt from token requirements" |
| Builder compact spacing | `p-4` minimum | ChatPanel uses `p-3`, `py-3` | Document builder sidebar compact spacing exception (`p-3` for dense builder panels) |
| PageShell `wide` variant | Only documents `default` and `narrow` | SearchPage uses `wide` | Update guide to document `wide` variant |

---

## 9. Prioritized Action Items

| # | Priority | Action | Category | Guide Rule | Effort | Scope |
|---|----------|--------|----------|-----------|--------|-------|
| 1 | **P0** | Darken `--muted-foreground` from `oklch(0.556 0 0)` to `oklch(0.40 0 0)` in light mode for 4.5:1 contrast | WCAG | 1.4.3 | 0.5h | Single token change, affects 500+ instances positively |
| 2 | **P0** | Add `prefers-reduced-motion: reduce` media query to disable/reduce shimmer and spinner animations | WCAG | 2.3.3 | 1h | `index.css` + optional `motion-safe:` variants |
| 3 | **P0** | Verify `--border` contrast ratio against white background (needs 3:1 for non-text UI) | WCAG | 1.4.11 | 0.5h | Single token, may need darkening |
| 4 | **P1** | Replace LegendWidget fallback colors (`#888`, `rgba(0,0,0,0.2)`) with `MAP_COLORS.fallback` and `border-border` token | Tokens | GUIDE-01 | 1h | Single component (5 instances) |
| 5 | **P1** | Add `alt` text to remaining `<img>` tags missing it | WCAG | 4.1.2 | 1h | ~11 images across components |
| 6 | **P1** | Replace `text-white` with `text-destructive-foreground` in button.tsx and badge.tsx destructive variants | Dark Mode | GUIDE-06 | 0.5h | 2 UI primitives |
| 7 | **P1** | Add `aria-live` regions for async state changes (loading, mutation feedback) | WCAG | 4.1.3 | 2h | Pattern-level change |
| 8 | **P2** | Normalize spacing: `space-y-3` -> `space-y-4`, `gap-3` -> `gap-4` / `gap-2` | Layout | GUIDE-04 | 1h | 7 instances across 5 pages |
| 9 | **P2** | Fix NotFoundPage heading hierarchy (`<h1 text-6xl>` -> appropriate heading) | Layout | GUIDE-02 | 0.5h | Single page |
| 10 | **P2** | Fix LoginPage heading weight (`font-semibold` -> `font-bold` for `text-3xl`) | Layout | GUIDE-02 | 0.25h | Single page |
| 11 | **P2** | Replace opacity-based text hierarchy with `text-muted-foreground` in 6 components | Dark Mode | GUIDE-06 | 1h | 6 components |
| 12 | **P2** | Update BasemapPicker from `grid-cols-4` to `grid-cols-3` or update guide | Map | GUIDE-05 | 0.25h | Single component or guide update |
| 13 | **P2** | Consolidate ~23 custom loading/empty/error patterns to standard components | Components | GUIDE-03 | 3h | ~23 instances, refactoring |
| 14 | **P2** | Add `aria-live` announcements for drawing mode changes in map builder | WCAG | Map a11y | 1h | Map components |
| 15 | **P2** | Update DESIGN-GUIDE.md with 5 divergences documented in section 8 | Guide | N/A | 1h | Documentation |

**Total estimated effort: ~15 hours**
- P0 (accessibility blockers): ~2 hours
- P1 (design system violations): ~4.5 hours
- P2 (minor drift / cosmetic): ~8.5 hours

---

## 10. Comparison to Prior Audit

No prior design-audit exists. This is the baseline audit. Future audits should diff against this report.

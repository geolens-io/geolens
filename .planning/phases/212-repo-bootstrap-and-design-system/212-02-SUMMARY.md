---
phase: 212-repo-bootstrap-and-design-system
plan: 02
subsystem: frontend
tags: [astro, layout, nav, footer, a11y, semantic-html, responsive]

# Dependency graph
requires:
  - 212-01 (Astro project scaffold, design tokens, links.ts)
provides:
  - SiteLayout.astro root layout shell with semantic landmarks
  - Nav.astro minimal nav (logo + GitHub icon per D-04)
  - Footer.astro single-line strip (copyright, GitHub, Apache 2.0 per D-05)
  - Stub index.astro homepage with primary-700 CTA

key-files:
  created:
    - src/components/layout/SiteLayout.astro
    - src/components/layout/Nav.astro
    - src/components/layout/Footer.astro
    - src/pages/index.astro
  modified: []
---

## What was built

Layout shell for getgeolens.com — every page using `SiteLayout.astro` inherits semantic HTML landmarks, Inter Variable font, and OKLCH design tokens.

### Components

1. **SiteLayout.astro** — Root page shell: `<!doctype html>` → `<html lang="en">` → `<head>` (meta, title, favicon) → `<body class="min-h-screen flex flex-col">` → Nav + `<main class="flex-1"><slot /></main>` + Footer. Imports `global.css` for token wiring.

2. **Nav.astro** — `<header>` → `<nav aria-label="Main navigation">`: GeoLens wordmark (blue circle SVG + "GeoLens" text) on left, GitHub Invertocat icon link on right. No page navigation links per D-04 — deferred to Phase 216.

3. **Footer.astro** — `<footer aria-label="Site footer">`: Single `flex flex-wrap` row. Left: "© 2026 GeoLens contributors". Right: GitHub link, Apache 2.0 link, "Powered by GeoLens". No multi-column grid per D-05.

4. **index.astro** — Stub homepage: h1 "GeoLens", subtitle, "Get Started" CTA button using `--primary-700: oklch(0.46 0.16 250)` background with white text (WCAG AA compliant per A11Y-01).

### Semantic HTML Landmark Structure

```
<html lang="en">
  <body>
    <header>                          ← banner landmark
      <nav aria-label="Main navigation"> ← navigation landmark
    <main>                            ← main landmark
      <slot />
    <footer aria-label="Site footer"> ← contentinfo landmark
```

### Color Contrast Decision

- CTA button: `--primary-700: oklch(0.46 0.16 250)` on white — passes WCAG AA (4.5:1)
- Body text: `--foreground: oklch(0.145 0 0)` on white — passes WCAG AAA
- Muted text: `--muted-foreground: oklch(0.45 0 0)` on white — passes WCAG AAA (~7:1)
- Primary-500 NOT used for text or interactive labels (too light for AA on white)

### Keyboard Tab Order (Verified)

1. Logo link ("GeoLens home")
2. GitHub nav icon ("GeoLens on GitHub (opens in new tab)")
3. "Get Started" CTA
4. GitHub footer link ("GeoLens GitHub repository (opens in new tab)")
5. Apache 2.0 footer link ("Apache 2.0 License (opens in new tab)")

### Responsive Breakpoint Behavior

- **375px (mobile):** Nav single row, CTA full width, footer wraps to 2 lines. No horizontal scroll.
- **768px (tablet):** All elements single row, content centered.
- **1280px (desktop):** `max-w-7xl mx-auto` caps content width, generous whitespace.

### Playwright Verification Results

All 12 automated checks passed:
- `html lang="en"` ✓
- `nav` with `aria-label="Main navigation"` ✓
- `main` landmark present ✓
- `footer` with `aria-label="Site footer"` ✓
- Single `h1` element ✓
- Nav has exactly 2 links (logo + GitHub, no page links per D-04) ✓
- Footer has no `grid` class (single flex row per D-05) ✓
- CTA background = `oklch(0.46 0.16 250)` = primary-700 ✓
- Font from `@fontsource-variable/inter` (localhost, no Google Fonts CDN) ✓
- No horizontal scroll at 375px ✓
- Responsive screenshots at 375px, 768px, 1280px ✓
- Keyboard tab order matches expected sequence ✓

## Deviations

None — implementation matches plan exactly.

## Commits

- `dddee90` — feat(212-02): create SiteLayout.astro and Nav.astro
- `375c6b6` — feat(212-02): create Footer.astro and stub index.astro homepage

## Self-Check: PASSED

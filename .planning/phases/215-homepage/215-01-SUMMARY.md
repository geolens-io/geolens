---
phase: 215-homepage
plan: 01
subsystem: getgeolens.com (marketing site)
tags: [astro, homepage, hero, trust-bar, quickstart, tailwind, oklch, marketing]
requirements: [HOME-01, HOME-02, HOME-05]

dependency_graph:
  requires:
    - 212-02 (design system, global.css custom properties, links.ts)
    - 214-01 (BrowserFrame.astro pattern reference)
  provides:
    - HeroSection.astro (HOME-01)
    - TrustSignalBar.astro (HOME-02)
    - QuickstartTeaser.astro (HOME-05)
  affects:
    - getgeolens.com homepage (Plan 03 wires these into index.astro)

tech_stack:
  added: []
  patterns:
    - Astro pure component (no client directives, no props, zero JS runtime)
    - CSS custom property inline styles for brand colors (no Tailwind color utilities)
    - Scoped <style> blocks for :hover and :focus-visible states that can't be done inline
    - Inline SVG icons (aria-hidden="true" focusable="false") with visible text labels

key_files:
  created:
    - getgeolens.com/src/components/home/HeroSection.astro
    - getgeolens.com/src/components/home/TrustSignalBar.astro
    - getgeolens.com/src/components/home/QuickstartTeaser.astro
  modified: []

decisions:
  - "Used scoped <style> blocks for :hover/:focus-visible because Tailwind 4 inline-style cascade does not reliably expose var(--primary-800) via arbitrary hover:bg-[var(...)] utilities"
  - "Badge label text left visible (not aria-hidden) in TrustSignalBar — procurement trust signals must be readable by screen readers"
  - "QuickstartTeaser has no frontmatter imports — /quickstart link is a literal path, no external URL needed"

metrics:
  duration: "~3 minutes"
  completed: "2026-04-11"
  tasks_completed: 3
  files_created: 3
  files_modified: 0
---

# Phase 215 Plan 01: Hero, Trust Bar, and Quickstart Teaser Summary

**One-liner:** Three self-contained Astro homepage sections (hero strip, trust badge strip, quickstart teaser strip) with locked copy, OKLCH custom-property brand colors, and tabnabbing-safe external links.

---

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create HeroSection.astro (HOME-01) | 32d2c74 | `src/components/home/HeroSection.astro` |
| 2 | Create TrustSignalBar.astro (HOME-02) | fe49b4f | `src/components/home/TrustSignalBar.astro` |
| 3 | Create QuickstartTeaser.astro (HOME-05) | 2dd6fe3 | `src/components/home/QuickstartTeaser.astro` |

---

## What Was Built

**HeroSection.astro** — Full-width hero with:
- Eyebrow: `Open Source · Self-Hosted · OGC Compliant` (primary-700, semibold, uppercase, tracking-widest)
- h1: `Find any geospatial dataset in seconds` (text-4xl/text-5xl, semibold, tracking-tight)
- Subtitle paragraph (text-xl, muted-foreground, max-w-2xl centered)
- Primary CTA `Get Started` → `/quickstart` (primary-700 bg, primary-foreground text)
- Secondary CTA `View on GitHub` → `GEOLENS_GITHUB_URL` (border, transparent bg, `target="_blank" rel="noopener noreferrer"`, `aria-label="GeoLens on GitHub (opens in new tab)"`)
- Scoped style block for `:hover` (primary-800) and `:focus-visible` (2px solid primary-700) on both CTAs

**TrustSignalBar.astro** — Full-width strip (surface-0 bg, border-t/border-b) with three badges:
1. Apache 2.0 — shield SVG (muted-foreground) + linked label → `GEOLENS_LICENSE_URL` (`target="_blank" rel="noopener noreferrer"`)
2. OGC API Compliant — globe SVG (primary-700) + plain `<span>` label
3. Self-Hosted — server SVG (muted-foreground) + plain `<span>` label
- All SVG icons are `aria-hidden="true" focusable="false"`; all badge labels are visible text for screen readers

**QuickstartTeaser.astro** — Full-width strip (surface-0 bg, border-t) with:
- h2: `Up and running in under 5 minutes` (text-3xl, semibold, leading-[1.2])
- Body: `Deploy GeoLens with a single docker compose command...` (text-base, muted-foreground, max-w-xl)
- CTA `Read the Quickstart` → `/quickstart` with trailing arrow SVG (aria-hidden)
- Scoped style for `:hover` (primary-800) and `:focus-visible` (2px solid primary-700)

---

## Deviations from Plan

None — plan executed exactly as written.

---

## Known Stubs

None — all copy is hardcoded verbatim from UI-SPEC copywriting contract. The `/quickstart` href is an internal link that will resolve when Phase 216 builds that page (expected 404 during development period per UI-SPEC note).

---

## Threat Surface Scan

No new surface beyond what the plan's threat model covers. Both tabnabbing mitigations (T-215-01, T-215-02) are implemented:
- HeroSection secondary CTA: `rel="noopener noreferrer"` ✓
- TrustSignalBar Apache 2.0 link: `rel="noopener noreferrer"` ✓

---

## Self-Check: PASSED

Files exist:
- FOUND: /Users/ishiland/Code/getgeolens.com/src/components/home/HeroSection.astro
- FOUND: /Users/ishiland/Code/getgeolens.com/src/components/home/TrustSignalBar.astro
- FOUND: /Users/ishiland/Code/getgeolens.com/src/components/home/QuickstartTeaser.astro

Commits exist (getgeolens.com repo):
- FOUND: 32d2c74 (HeroSection)
- FOUND: fe49b4f (TrustSignalBar)
- FOUND: 2dd6fe3 (QuickstartTeaser)

`astro check` result: 0 errors, 0 warnings, 0 hints (19 files checked)

---
name: 260508-bv1-CONTEXT
description: User decisions for syncing geolens-io/branding v0.1.0 into the GeoLens app
type: quick-task-context
---

# Quick Task 260508-bv1: Sync v0.1.0 branding - Context

**Gathered:** 2026-05-08
**Status:** Ready for planning
**Source repo:** /Users/ishiland/Code/branding @ tag v0.1.0

<domain>
## Task Boundary

Implement the v0.1.0 branding from `/Users/ishiland/Code/branding` (geolens-io/branding) into the GeoLens app. The branding repo ships per-consumer guidance for `geolens-io/geolens`:

- `tokens/` (colors + typography) → `frontend/src/index.css`
- `logos/reticle/geolens-emblem-mono.svg` → `frontend/src/components/GeoLensLogo.tsx`

This task syncs that canonical surface plus four extensions agreed in discussion (favicon variant + PNG fallbacks, PWA app icons + manifest, version marker, weights left as-is).

**Pre-existing alignment** (no work required, audited 2026-05-08):
- All 10 `--primary-50..900` OKLCH tokens (light mode) match `tokens/brand-colors.css` byte-for-byte at `frontend/src/index.css:29-38`.
- Sans `font-family` line at `frontend/src/index.css:258` matches `tokens/typography.json` byte-for-byte.
- Mono `font-family` line at `frontend/src/index.css:259` matches `tokens/typography.json` byte-for-byte.
- `frontend/src/components/GeoLensLogo.tsx` inlines the mono reticle geometry (cx/cy=26, r=18, currentColor) — matches `logos/reticle/geolens-emblem-mono.svg` byte-for-byte.
- Wordmark pattern (`Geo` `font-bold` + `Lens` `font-light text-muted-foreground`) at `GeoLensLogo.tsx:71-74` matches brand guide §7 exactly.

**Out of scope:** GitHub avatar (manual upload per brand guide §5), press-kit (private repo only), marketing site (different repo `getgeolens.com`), `--primary-*` dark-mode scale (app-specific extension, brand guide §6 explicitly says neutrals/dark scales are app-specific).

</domain>

<decisions>
## Implementation Decisions

### Favicon strategy
- **LOCKED:** Switch `/favicon.svg` to the dedicated favicon variant from `branding/logos/favicon/geolens-favicon.svg` (simplified — no graticule, hardcoded `#334155` slate, viewBox 0 0 64 64, cx/cy=28, r=18) AND add PNG fallbacks `geolens-favicon-{16,32,64}.png`.
- **Why:** Matches brand guide §3 — favicons should use the simplified mark optimized for 16–64 px tab rendering. The current mono-emblem favicon has graticule detail that becomes visual noise at 16 px.
- **index.html update:** Add `<link rel="icon" type="image/svg+xml" href="/favicon.svg">` (already present) PLUS PNG fallbacks per browser:
  - `<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16.png">`
  - `<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">`
  - `<link rel="icon" type="image/png" sizes="64x64" href="/favicon-64.png">`

### PWA app icons + manifest
- **LOCKED:** Add `geolens-app-icon-{light,dark}.png` (1024×1024) to `frontend/public/` AND a minimal `manifest.webmanifest` referenced from `index.html`.
- **Why:** Brand guide §4 designs app icons specifically for PWA/iOS/Android home-screen rendering with safe-zone padding for round-cropping. Adding a manifest unblocks PWA install prompts on supported browsers without other code changes.
- **Manifest shape:**
  - `name`: "GeoLens"
  - `short_name`: "GeoLens"
  - `description`: matches existing `<meta name="description">` content from `index.html`
  - `start_url`: "/"
  - `display`: "standalone"
  - `background_color`: "#ffffff" (light atlas paper — sRGB approx of `--background` light)
  - `theme_color`: "#3b6fd4" (frozen sRGB approx of `--primary-500` per brand guide §6)
  - `icons`: array with 1024×1024 light/dark + downscaled 192/512 for PWA install slots (downscale from 1024 source per brand guide §4 — DO NOT generate from emblem files)

### Brand-sync version marker
- **LOCKED:** Create `BRANDING-VERSION` file at repo root (not inside `.planning/`).
- **Why:** Single dedicated grep-able file as recommended by branding README §"Version pinning". Avoids polluting CLAUDE.md (loaded into every Claude Code context window). Future bumps just rewrite this one file.
- **File contents:**
  ```
  Brand assets synced from geolens-io/branding v0.1.0
  Sync date: 2026-05-08
  Source path at sync: /Users/ishiland/Code/branding @ tag v0.1.0
  Files synced: see .planning/quick/260508-bv1-sync-v0-1-0-branding/260508-bv1-SUMMARY.md
  ```

### Mono font weight imports
- **LOCKED:** Leave `frontend/src/index.css:4` `@import '@fontsource/ibm-plex-mono/500.css'` as-is.
- **Why:** Trimming risks regressing any surface that renders mono text at weight 500 (likely table headers, badges per `tokens/typography.json` weight conventions). Branding repo's typography.json specifies `400.css` as the *minimum* import path; loading additional weights is additive and not a brand violation.

### Claude's Discretion
- Generation of downscaled 192×192 and 512×512 PWA icons from 1024×1024 sources: use ImageMagick or sips on the source PNGs. Both are available on macOS — the executor agent should pick whichever it can verify produces lossless downsamples. PNG dimensions must be exact (192, 512); SVG → PNG for the favicon already exists in branding repo so no rasterization needed there.
- File naming inside `frontend/public/`: stay close to branding repo names (e.g., `app-icon-light.png` not `pwa-icon-light.png`). Predictable for future bumps.
- Existing `frontend/public/og-image.png` (175 KB) is unchanged. Branding repo doesn't ship an OG image; existing one stays as-is.

</decisions>

<specifics>
## Specific Ideas

**Files to copy verbatim from `/Users/ishiland/Code/branding`:**
- `logos/favicon/geolens-favicon.svg` → `frontend/public/favicon.svg` (replaces existing — current is mono variant, not favicon variant)
- `logos/favicon/geolens-favicon-16.png` → `frontend/public/favicon-16.png`
- `logos/favicon/geolens-favicon-32.png` → `frontend/public/favicon-32.png`
- `logos/favicon/geolens-favicon-64.png` → `frontend/public/favicon-64.png`
- `logos/app-icon/geolens-app-icon-light.png` → `frontend/public/app-icon-light.png`
- `logos/app-icon/geolens-app-icon-dark.png` → `frontend/public/app-icon-dark.png`

**Files to generate (downscaled from 1024×1024 sources):**
- `frontend/public/app-icon-192.png` (192×192, downscaled from `app-icon-light.png`)
- `frontend/public/app-icon-512.png` (512×512, downscaled from `app-icon-light.png`)

**Files to create:**
- `frontend/public/manifest.webmanifest` (minimal PWA manifest, theme_color #3b6fd4, icons array)
- `BRANDING-VERSION` (root-level sync marker)

**Files to edit:**
- `frontend/index.html` — add 3 PNG favicon `<link>` lines + 1 `<link rel="manifest">` line + `<meta name="theme-color" content="#3b6fd4">`

**Files NOT to touch:**
- `frontend/src/index.css` — already byte-for-byte aligned with `tokens/`. Verifying alignment is in scope; editing is not.
- `frontend/src/components/GeoLensLogo.tsx` — already byte-for-byte aligned with mono SVG. Verifying alignment is in scope; editing is not.
- `frontend/public/og-image.png` — branding repo doesn't ship one, existing stays.
- All app-internal color/dark-mode tokens in `index.css:144-253` — explicitly app-specific per brand guide §6.

</specifics>

<canonical_refs>
## Canonical References

- `/Users/ishiland/Code/branding/README.md` — distribution model, per-consumer guidance, version pinning convention
- `/Users/ishiland/Code/branding/BRAND-GUIDE.md` — §2 (reticle), §3 (favicon), §4 (app icon), §6 (color tokens), §7 (typography wordmark)
- `/Users/ishiland/Code/branding/tokens/colors.json` — primary palette OKLCH, sRGB approx for `--primary-500` (#3b6fd4) used as PWA `theme_color`
- `/Users/ishiland/Code/branding/tokens/typography.json` — IBM Plex package version constraints
- `/Users/ishiland/Code/branding/tokens/brand-colors.css` — drop-in CSS variables (already mirrored in `frontend/src/index.css`)
- Branding repo HEAD at sync time: tag `v0.1.0` (commit `54d2dd6`, with docs follow-up `48176c4`)

</canonical_refs>

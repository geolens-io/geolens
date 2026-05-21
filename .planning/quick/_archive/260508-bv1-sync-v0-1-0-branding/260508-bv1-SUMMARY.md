---
phase: 260508-bv1-sync-v0-1-0-branding
plan: 01
type: quick-task
status: complete
date: 2026-05-08
commits:
  - hash: a5cc2003
    message: "chore(brand): sync v0.1.0 favicon + app-icon assets to frontend/public/"
  - hash: 035d1c44
    message: "feat(brand): wire favicon variants + PWA manifest into index.html"
  - hash: f35f9a3e
    message: "chore(brand): pin sync to geolens-io/branding v0.1.0 via BRANDING-VERSION marker"
  - hash: 659b9e61
    message: "fix(brand): drop maskable purpose claim until purpose-built variant ships"
requirements: [BRAND-FAVICON-01, BRAND-PWA-01, BRAND-VERSION-01, BRAND-PARITY-01]
---

# Quick Task 260508-bv1: Sync v0.1.0 Branding - Summary

**One-liner:** Synced geolens-io/branding v0.1.0 favicon variant + PWA manifest + version marker into GeoLens app with 3 atomic commits.

## What Was Done

### Task 1: Copy verbatim assets + downscale PWA icons (commit `a5cc2003`)

8 files added to `frontend/public/`:

| File | Source | Byte size |
|---|---|---|
| `favicon.svg` | branding/logos/favicon/geolens-favicon.svg (verbatim) | 801 B |
| `favicon-16.png` | branding/logos/favicon/geolens-favicon-16.png (verbatim) | 432 B |
| `favicon-32.png` | branding/logos/favicon/geolens-favicon-32.png (verbatim) | 862 B |
| `favicon-64.png` | branding/logos/favicon/geolens-favicon-64.png (verbatim) | 1,822 B |
| `app-icon-light.png` | branding/logos/app-icon/geolens-app-icon-light.png (verbatim) | 62,801 B |
| `app-icon-dark.png` | branding/logos/app-icon/geolens-app-icon-dark.png (verbatim) | 61,366 B |
| `app-icon-192.png` | sips -z 192 192 app-icon-light.png (downscaled) | 192x192 px |
| `app-icon-512.png` | sips -z 512 512 app-icon-light.png (downscaled) | 512x512 px |

The `favicon.svg` replacement switches from the mono-emblem variant (with graticule, cx/cy=26) to the dedicated favicon variant (simplified, no graticule, cx/cy=28, hardcoded #334155 slate) — optimized for 16-64 px tab rendering per brand guide §3.

### Task 2: Wire favicons + manifest into index.html + create manifest.webmanifest (commit `035d1c44`)

**`frontend/index.html`** — 6 changes in `<head>`:

1. Line 23 edited: added `sizes="any"` to existing SVG favicon link (Chrome favicon trap fix per RESEARCH §2)
2. Line 24 inserted: `<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16.png" />`
3. Line 25 inserted: `<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png" />`
4. Line 26 inserted: `<link rel="icon" type="image/png" sizes="64x64" href="/favicon-64.png" />`
5. Line 27 inserted: `<link rel="manifest" href="/manifest.webmanifest" />`
6. After `<meta name="description">`: `<meta name="theme-color" content="#3b6fd4" />` (matches manifest theme_color per RESEARCH §4)

**`frontend/public/manifest.webmanifest`** created with:
- `name`/`short_name`: "GeoLens"
- `description`: matches existing `<meta name="description">` verbatim
- `start_url`: "/"
- `display`: "standalone"
- `background_color`: "#ffffff" (light atlas paper, sRGB approx of --background light)
- `theme_color`: "#3b6fd4" (frozen sRGB approx of --primary-500 per brand guide §6)
- `icons`: 3-entry array — 192x192 (`any`), 512x512 (`any`), 1024x1024 (`any`) — *originally `any maskable` on 192/512; downgraded to `any` only via commit `659b9e61` after code review WR-01 flagged that brand guide §4 promises 'rounded square' iOS treatment, not the W3C maskable 80% safe-zone. Revisit when branding repo ships a purpose-built maskable variant (v0.2.0+).*

### Task 3: Create BRANDING-VERSION marker (commit `f35f9a3e`)

`BRANDING-VERSION` at repo root (sibling to README.md) with 4 locked lines:

```
Brand assets synced from geolens-io/branding v0.1.0
Sync date: 2026-05-08
Source path at sync: /Users/ishiland/Code/branding @ tag v0.1.0
Files synced: see .planning/quick/260508-bv1-sync-v0-1-0-branding/260508-bv1-SUMMARY.md
```

## Pre-existing Alignment Preserved

No files under `frontend/src/` were modified. Re-confirmed at Task 1 verify step:
- `frontend/src/index.css :29-38` — `--primary-50..900` light tokens: byte-identical to branding/tokens/brand-colors.css (cmp passed, no DRIFT)
- `frontend/src/index.css :258` — sans font-family `'IBM Plex Sans Variable', ui-sans-serif, system-ui, sans-serif`: present
- `frontend/src/index.css :259` — mono font-family `'IBM Plex Mono', ui-monospace, SFMono-Regular, Menlo, monospace`: present
- `frontend/src/components/GeoLensLogo.tsx` — mono reticle geometry `cx="26" cy="26" r="18"`: present

## Research Resolutions (RESEARCH §1-4)

| Section | Question | Resolution encoded in this plan |
|---|---|---|
| §1 | Manifest placement in Vite | `frontend/public/manifest.webmanifest` + single `<link rel="manifest">` line, no vite.config.ts edit |
| §2 | Favicon ordering with `sizes="any"` | SVG first with `sizes="any"` attribute, PNG fallbacks ascending 16→32→64 |
| §3 | Icon downscaling tool | `sips -z 192 192` and `sips -z 512 512` (macOS built-in, no Homebrew dep) |
| §4 | theme_color parity | Both `<meta name="theme-color">` AND manifest `theme_color` set to `#3b6fd4` |

## Deviations from Plan

One follow-up after code review:

- **WR-01 closure (`659b9e61`):** Code reviewer flagged that the plan's specified `purpose: "any maskable"` on 192/512 icons over-promises maskable safe-zone compliance (brand guide §4 only describes iOS rounded-square padding, not Android adaptive-icon 80% center safe-zone). Followed reviewer's safer recommendation: dropped `maskable` from both entries, leaving `purpose: "any"`. Future v0.2.0+ branding bump can add a purpose-built maskable variant and we'll re-introduce maskable entries then. Plan's Task 2 verify assertion (`purpose=='any maskable'`) was satisfied at execution time — this is a post-execute correction, not a verification miss.
- **IN-01 (info, not actioned):** Reviewer noted `<meta name="viewport">` and `<meta name="theme-color">` ended up separated by `<meta name="description">` rather than adjacent. Cosmetic only — no behavior impact, no spec violation. Left as-is per the plan's "DO NOT touch any other line" constraint.

## Verification Results

- All 6 verbatim copies: `cmp` byte-identity PASS
- app-icon-192.png: `192 x 192` PASS
- app-icon-512.png: `512 x 512` PASS
- manifest.webmanifest: Python JSON validation PASS (all 9 asserted fields)
- index.html: all 6 required lines present via `grep -F`, old line absent
- BRANDING-VERSION: all 4 lines matched via `grep -Fxq`
- `npm run build`: clean (built in ~380ms, manifest.webmanifest present in dist/)
- Pre-existing alignment: no drift in index.css or GeoLensLogo.tsx

## Next-Bump Checklist (v0.2.0+)

When the branding repo publishes a new tag:

1. Rerun `cp` for any changed source files from `branding/logos/favicon/` and `branding/logos/app-icon/` to `frontend/public/`.
2. If `app-icon-light.png` source dimensions change from 1024x1024, rerun sips commands with new source.
3. Update `BRANDING-VERSION` line 1 (version tag), line 2 (sync date), line 3 (source path/tag).
4. If manifest shape changes (new fields, icon slots), update `frontend/public/manifest.webmanifest` accordingly.
5. If `theme_color` changes, update both manifest and `<meta name="theme-color">` in `frontend/index.html`.

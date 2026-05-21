---
phase: 260508-bv1-sync-v0-1-0-branding
reviewed: 2026-05-08T00:00:00Z
depth: quick
files_reviewed: 11
files_reviewed_list:
  - BRANDING-VERSION
  - frontend/index.html
  - frontend/public/app-icon-192.png
  - frontend/public/app-icon-512.png
  - frontend/public/app-icon-dark.png
  - frontend/public/app-icon-light.png
  - frontend/public/favicon-16.png
  - frontend/public/favicon-32.png
  - frontend/public/favicon-64.png
  - frontend/public/favicon.svg
  - frontend/public/manifest.webmanifest
findings:
  critical: 0
  warning: 1
  info: 1
  total: 2
status: issues_found
---

# Brand Asset Sync v0.1.0: Code Review Report

**Reviewed:** 2026-05-08
**Depth:** quick (expanded for the 3 hand-authored surfaces)
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Reviewed all 11 changed files against the locked CONTEXT decisions and PWA spec. Binary assets (6 verbatim copies + 2 downscaled PNGs) all pass `cmp` byte-identity and `file(1)` dimension checks. The simplified favicon SVG is the correct variant (no graticule, cx/cy=28 r=18, hardcoded #334155). `BRANDING-VERSION` matches the locked 4-line shape exactly with no trailing whitespace and a clean trailing newline. `index.html` HTML is well-formed and contains all 6 required lines.

Two findings: one WARNING on a PWA spec anti-pattern in the manifest that will produce a Lighthouse warning and may cause clipping on Android maskable-icon paths, and one INFO on the `<meta name="theme-color">` placement relative to `<meta name="viewport">`.

## Warnings

### WR-01: manifest icons use combined `"purpose": "any maskable"` — Lighthouse flags this, and maskable safe-zone compliance is unverified

**File:** `frontend/public/manifest.webmanifest:14,20`

**Issue:** Both the 192×192 and 512×512 icon entries declare `"purpose": "any maskable"` — a combined value. Chrome Lighthouse (and the W3C Manifest spec editors' note) explicitly discourages this pattern, because `maskable` icons are expected to fill the full canvas with all meaningful content within the central 80% safe-zone, while `any` icons make no such promise. When a browser selects the icon for a context that applies maskable masking (e.g., Android adaptive icons), it applies a circle or squircle mask to an icon that may not have been designed with that constraint in mind — clipping the logo.

The brand guide §4 states the app icons have "rendering padding suitable for rounded square home-screen treatment" but does **not** explicitly claim the 80% maskable safe-zone. "Rounded square" (iOS-style) and "maskable circle" (Android-style) have different padding requirements. The 1024×1024 source icon has not been audited for maskable compliance in the CONTEXT or RESEARCH documents.

**Fix:** Split each combined entry into two separate icon entries — one for `any`, one for `maskable`. If maskable safe-zone compliance is confirmed via visual inspection of the 1024 source (all content within central 80%), the `maskable` entries are valid and can stay. If not confirmed, drop `maskable` entirely for now and revisit when a purpose-built maskable variant is added to the branding repo.

```json
{
  "src": "/app-icon-192.png",
  "sizes": "192x192",
  "type": "image/png",
  "purpose": "any"
},
{
  "src": "/app-icon-192.png",
  "sizes": "192x192",
  "type": "image/png",
  "purpose": "maskable"
},
{
  "src": "/app-icon-512.png",
  "sizes": "512x512",
  "type": "image/png",
  "purpose": "any"
},
{
  "src": "/app-icon-512.png",
  "sizes": "512x512",
  "type": "image/png",
  "purpose": "maskable"
}
```

## Info

### IN-01: `<meta name="theme-color">` is now separated from `<meta name="viewport">` by `<meta name="description">` — minor head ordering drift vs. browser convention

**File:** `frontend/index.html:28-30`

**Issue:** The original head had `<link rel="icon">` → `<meta name="viewport">` → `<meta name="description">`. After the edit the order is: 4 favicon `<link>` lines → `<link rel="manifest">` → `<meta name="viewport">` → `<meta name="description">` → `<meta name="theme-color">`. This is functionally correct (browsers do not require any specific ordering among these tags), but `<meta name="viewport">` ended up after the manifest link rather than remaining immediately after the favicon line where it was originally. This is a cosmetic deviation from the plan's instruction to "DO NOT touch any other line" — the viewport line itself is unchanged but its relative position shifted because the favicon block expanded.

Separately, many browser style guides recommend grouping `<meta name="viewport">` and `<meta name="theme-color">` adjacently (both affect initial render behavior), but that is a style preference and not a spec requirement.

**Fix (optional):** If head ordering hygiene matters, move `<meta name="viewport">` to immediately after `<meta charset="UTF-8" />` (line 4), before the FOUC-prevention script block. This is the conventional position per the WHATWG HTML "important meta" recommendation and keeps favicon/manifest links clearly grouped separately. This is low-priority — no current browser exhibits different behavior based on viewport vs. manifest ordering.

---

_Reviewed: 2026-05-08_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: quick (expanded per task instructions)_

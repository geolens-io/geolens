---
status: complete
---

# Design Audit Command & Design Guide Review — Summary

## Changes Made

### docs/DESIGN-GUIDE.md (90 insertions, 34 deletions)

**Token value corrections (code wins):**
- Fixed 20+ light-mode neutral tokens from achromatic `oklch(X 0 0)` to warm `oklch(X 0.003 85)` — background, card, popover, secondary, muted, accent, border, input, surfaces, sidebar
- Fixed foreground tokens from `oklch(0.145 0 0)` to `oklch(0.145 0.005 250)` (blue tint)

**Font family:**
- Changed "Inter Variable" → "IBM Plex Sans Variable" throughout
- Added IBM Plex Mono documentation

**Layout:**
- PageShell: `py-6 space-y-6` → `py-4 space-y-4`
- PageShell wide: `max-w-screen-2xl` → `max-w-6xl`
- Added `space-y-3` as valid tight-within-sections convention
- Updated spacing conventions table

**New token sections added:**
- Brand Accent Tokens (signature, signature-soft)
- Map-Native Surface Tones (map-paper, map-street, map-water)
- Record-Type Colors (8 tokens for vector/raster/table/VRT)
- Code Syntax Tokens (12 tokens for code display)

**Principles:**
- Added "Warm atlas paper" as key principle
- Documented warm/cool hue strategy in dark mode section

### .claude/commands/design-audit.md

- BasemapPicker grid: `grid-cols-3` → `grid-cols-4`
- BasemapPicker thumbnails: corrected from "Inline SVG thumbnails" to "PNG assets + SVG fallback"
- Font check: Inter → IBM Plex Sans Variable
- Added subagent 1g: Extended token category scan (record-type, code, map, signature)
- Spacing subagent: corrected conventions, `space-y-3`/`gap-3` marked as valid
- Report structure: added 1f Extended Token Categories section

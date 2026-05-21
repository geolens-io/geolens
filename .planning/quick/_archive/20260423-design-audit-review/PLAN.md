---
slug: design-audit-review
goal: Review design-audit command completeness and design guide accuracy
status: complete
---

# Quick Task: Design Audit Command & Design Guide Review

## Findings

### A. Design Guide Corrections Needed (Code Wins)

1. **Font family** — Guide says Inter Variable; code uses IBM Plex Sans Variable
2. **Light-mode neutral hue** — Guide says `oklch(X 0 0)` (achromatic); code uses `oklch(X 0.003 85)` (warm earth tone hue 85)
3. **PageShell spacing** — Guide says `py-6 space-y-6`; code uses `py-4 space-y-4`
4. **Foreground tokens** — Guide says `oklch(0.145 0 0)` (achromatic); code uses `oklch(0.145 0.005 250)` (slight blue tint)
5. **PageShell wide** — Guide says `max-w-screen-2xl`; code uses `max-w-6xl`
6. **Sidebar light value** — Guide says `oklch(0.985 0 0)`; code uses `oklch(0.98 0.003 85)` (warm)
7. **Sidebar border light** — Guide says `oklch(0.922 0 0)`; code uses `oklch(0.92 0.005 85)` (warm)
8. **Undocumented tokens** — Record-type colors, code syntax tokens, map-native tones, signature brand accent

### B. Design Audit Command Issues

1. **BasemapPicker thumbnails** — Audit says "Inline SVG thumbnails (not external PNGs)" (line 468); code uses PNG imports + SVG fallback
2. **BasemapPicker grid** — Audit says `grid-cols-3` (line 465); code/guide both say `grid-cols-4`
3. **Spacing false positives** — Audit flags `space-y-3` and `gap-3` as violations (subagent 3d); guide and code both document these as valid for tight/compact layouts
4. **Missing token categories** — Audit doesn't scan for record-type tokens (--type-vector etc.), code tokens (--code-*), map-native tokens (--map-*), or signature tokens
5. **Font check** — Audit checks for Inter (line 782); should check for IBM Plex Sans
6. **Missing component coverage** — Toast/Sonner, Sidebar, Skeleton, Sheet not explicitly audited
7. **No Sonner/toast styling audit** — Toast system uses sonner library but no audit checks verify it uses design tokens

### C. Design Guide Enhancement Opportunities

1. **Document warm palette intent** — The guide describes tokens numerically but never explains the "warm atlas paper" aesthetic (light-mode hue 85)
2. **Document IBM Plex Sans choice** — No rationale for font family; add brief note about IBM Plex vs Inter
3. **Add Record-Type Tokens section** — 4 color pairs used for type badges (vector, raster, table, VRT) with dark mode variants
4. **Add Code Syntax Tokens section** — 12 tokens for code snippet rendering
5. **Add Map-Native Tones section** — 3 tokens (paper, street, water) for map surfaces
6. **Add Signature Brand Accent section** — 2 tokens for brand tint
7. **Document mono font** — IBM Plex Mono is imported but not documented
8. **Spacing table update** — Add `space-y-3` and `gap-3` as first-class conventions, not anti-patterns

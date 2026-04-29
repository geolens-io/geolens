# /design-audit — Design System Conformance & Accessibility Audit

Audit the GeoLens frontend against `docs/DESIGN-GUIDE.md` for design system drift, token misuse, component pattern violations, and WCAG 2.1 AA accessibility compliance. The design guide is the spec — every finding is measured against a documented rule, not subjective preference.

**Usage:** `/design-audit` (full audit) or `/design-audit <section>` where section is `tokens`, `components`, `layout`, `map`, `a11y`, or `dark-mode`

---

## INTAKE (Serial — do this first)

### Step 1: Read the design guide

```bash
cat docs/DESIGN-GUIDE.md
```

This is the source of truth. If the guide disagrees with the code, the code wins and the guide needs updating — but FLAG the disagreement either way.

### Step 2: Read the token source of truth

```bash
# The actual CSS tokens
cat frontend/src/index.css

# Status color centralization
cat frontend/src/lib/status-colors.ts 2>/dev/null

# Map color constants
cat frontend/src/lib/map-colors.ts 2>/dev/null

# Basemap utils
cat frontend/src/lib/basemap-utils.ts 2>/dev/null
```

### Step 3: Inventory all components and pages

```bash
# UI components (shadcn/ui layer)
find frontend/src/components/ui -name "*.tsx" 2>/dev/null | sort

# Layout components
find frontend/src/components/layout -name "*.tsx" 2>/dev/null | sort

# All page components
find frontend/src/pages -name "*.tsx" 2>/dev/null | sort

# All other component directories
find frontend/src/components -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort

# Total component count
find frontend/src/components frontend/src/pages -name "*.tsx" 2>/dev/null | wc -l
```

### Step 4: Check for existing /ux-review command

```bash
cat .claude/commands/ux-review.md 2>/dev/null
```

Note any overlap. This command is design-guide-specific + WCAG; `/ux-review` covers general usability heuristics. They complement each other.

---

## SUBAGENT DISPATCH (Parallel)

Run these 7 subagents in parallel.

### Subagent 1: Design Token Conformance (GUIDE-01, GUIDE-06)

**Goal:** Find every instance of hardcoded colors, raw Tailwind palette classes, and token misuse across the entire frontend.

**Process:**

#### 1a. Hardcoded color scan

```bash
# Hardcoded hex colors in components (NOT in map-colors.ts, status-colors.ts, or index.css)
grep -rn "#[0-9a-fA-F]\{3,8\}" frontend/src/ --include="*.tsx" --include="*.ts" --include="*.css" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "index.css" \
  | grep -v "map-colors.ts" \
  | grep -v "status-colors.ts" \
  | grep -v "basemap-utils.ts" \
  | grep -v "\.svg" \
  | grep -v "StyleColorPicker"

# Hardcoded rgb/rgba/hsl/oklch in components
grep -rn "rgb(\|rgba(\|hsl(\|hsla(\|oklch(" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "index.css" \
  | grep -v "map-colors.ts"
```

For each hit, classify:
- **🔴 Anti-pattern violation** — Hardcoded color in a component where a token should be used (Anti-Pattern #1, #2)
- **🟢 Exempt** — Inside `map-colors.ts`, `status-colors.ts`, `index.css`, `StyleColorPicker`, or MapLibre paint properties (where CSS vars don't work)

#### 1b. Raw Tailwind palette scan

```bash
# Tailwind palette classes that should be semantic tokens instead
# This catches bg-gray-*, text-slate-*, border-zinc-*, etc.
grep -rn "bg-\(gray\|slate\|zinc\|neutral\|stone\|red\|orange\|amber\|yellow\|lime\|green\|emerald\|teal\|cyan\|sky\|blue\|indigo\|violet\|purple\|fuchsia\|pink\|rose\)-" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "status-colors.ts" \
  | grep -v "index.css"

grep -rn "text-\(gray\|slate\|zinc\|neutral\|stone\|red\|orange\|amber\|yellow\|lime\|green\|emerald\|teal\|cyan\|sky\|blue\|indigo\|violet\|purple\|fuchsia\|pink\|rose\)-" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "status-colors.ts"

grep -rn "border-\(gray\|slate\|zinc\|neutral\|stone\)-" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "status-colors.ts"
```

**Exemptions:** `status-colors.ts` intentionally uses palette classes for tinted badge backgrounds — the guide documents this exception explicitly ("The palette classes are intentional here — semantic tokens with opacity modifiers do not provide sufficient text contrast on tinted backgrounds").

#### 1c. Token usage hierarchy violations

```bash
# Primary scale tokens used directly (should be rare — GUIDE-01 says "only for edge cases")
grep -rn "primary-\(50\|100\|200\|300\|400\|500\|600\|700\|800\|900\)" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "index.css" \
  | grep -v "status-colors.ts"

# Surface tokens used where semantic tokens would suffice
grep -rn "surface-[0-3]" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "index.css"
```

For each primary-scale hit, assess whether a semantic token (`primary`, `accent`, `muted`) would work instead. The guide says: "Never use raw primary scale tokens for UI semantics."

#### 1d. Border token check

```bash
# Borders should use border-border or border-input, never border-gray-200 etc.
grep -rn "border-\(gray\|slate\|zinc\|neutral\|stone\)" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules
```

#### 1e. Shadow token check

```bash
# Should use shadow-sm/md/lg (mapped through elevation tokens), not custom shadows
grep -rn "shadow-\[" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules

# Check for inline box-shadow styles
grep -rn "boxShadow\|box-shadow" frontend/src/ --include="*.tsx" --include="*.ts" --include="*.css" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "index.css"
```

#### 1f. Transition anti-pattern

```bash
# transition-all is forbidden — causes layout thrash (Anti-Pattern #5)
grep -rn "transition-all" frontend/src/ --include="*.tsx" --include="*.ts" --include="*.css" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "index.css"
```

#### 1g. Extended token category scan

```bash
# Record-type tokens — should be used via token utilities, not hardcoded
grep -rn "type-vector\|type-raster\|type-table\|type-vrt" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "index.css" \
  | grep -v "status-colors.ts"

# Code syntax tokens — verify usage in code display components
grep -rn "code-bg\|code-chrome\|code-text\|code-keyword\|code-function\|code-string\|code-number\|code-comment\|code-method-badge" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "index.css"

# Map-native tones — verify usage in map-adjacent UI
grep -rn "map-paper\|map-street\|map-water" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "index.css"

# Signature brand accent — verify usage
grep -rn "signature\|signature-soft" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "index.css"
```

Verify these extended token categories are used consistently and not duplicated with hardcoded values.

#### 1h. Token source of truth sync

Compare every token value in `index.css` against what the design guide documents. Flag mismatches — remember, "if it disagrees with the code, the code wins and this guide needs updating."

```bash
# Extract all CSS custom property definitions from index.css
grep -E "^\s+--[a-z]" frontend/src/index.css | head -100
```

**Output:** Token violations table — File:Line | Violation | Rule (GUIDE-01/#) | Severity | Fix

---

### Subagent 2: Component Pattern Conformance (GUIDE-03)

**Goal:** Verify that every instance of buttons, cards, badges, tables, dialogs, selects, inputs, and state components matches the documented patterns.

**Process:**

#### 2a. Read all UI components

```bash
# Read each documented component
for comp in button card badge table dialog select input; do
  echo "=== $comp ==="
  find frontend/src/components/ui -iname "*${comp}*" -name "*.tsx" 2>/dev/null | while read f; do
    cat "$f"
  done
done

# State components
for comp in EmptyState LoadingState ErrorState; do
  echo "=== $comp ==="
  find frontend/src/components/layout -iname "*${comp}*" -name "*.tsx" 2>/dev/null | while read f; do
    cat "$f"
  done
done
```

#### 2b. Button usage audit

```bash
# Find all Button usages across the codebase
grep -rn "<Button\|variant=\"\|variant='" frontend/src/ --include="*.tsx" 2>/dev/null | grep -v node_modules | grep -v "components/ui/button"
```

Check against guide rules:
- **One primary (`default` variant) button per form/dialog** — scan each dialog/form for multiple `variant="default"` buttons
- **`destructive` variant paired with confirmation dialog** — find all `variant="destructive"` and verify a dialog/confirm exists
- **Correct size usage** — `xs` for toolbar, `sm` for tight layouts, `default` for standard, `lg` for prominent CTAs
- **Icon button sizing** — `icon` (36px), `icon-xs` (24px), `icon-sm` (32px), `icon-lg` (40px)

#### 2c. Card usage audit

```bash
# Card usage patterns
grep -rn "<Card\|<CardHeader\|<CardContent\|<CardAction\|<CardFooter" frontend/src/ --include="*.tsx" 2>/dev/null | grep -v node_modules | grep -v "components/ui/card"
```

Check:
- Cards use `CardAction` for top-right buttons (not absolute positioning)
- Card subcomponent order: Header → Content → Footer
- No custom padding overriding the component's built-in padding

#### 2d. Badge and status color audit

```bash
# All Badge usages
grep -rn "<Badge" frontend/src/ --include="*.tsx" 2>/dev/null | grep -v node_modules | grep -v "components/ui/badge"

# Status-related coloring — should come from status-colors.ts
grep -rn "jobStatus\|userStatus\|visibility\|ingestionStatus\|validationLevel\|healthDot\|qualityScore\|recordType\|vrtGeneration\|vrtRaster\|activeDot" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | grep -v "status-colors.ts"

# Hardcoded status colors (violation of Anti-Pattern #1)
grep -rn "bg-green\|bg-red\|bg-yellow\|bg-amber\|text-green\|text-red\|text-yellow" frontend/src/ --include="*.tsx" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "status-colors.ts" \
  | grep -v "index.css"
```

Every status badge should reference a map from `status-colors.ts`, never hardcode Tailwind palette classes.

#### 2e. Table conformance

```bash
# Table usage
grep -rn "<Table\|<TableHead\|<TableRow\|<TableCell" frontend/src/ --include="*.tsx" 2>/dev/null | grep -v node_modules | grep -v "components/ui/table"
```

Check:
- `TableHead` uses `text-xs uppercase tracking-wide font-medium`
- `TableRow` has hover state (`hover:bg-muted/50`)
- Focus ring uses `ring-inset` (not offset) for table rows

#### 2f. State component usage

```bash
# Find loading, empty, and error states that DON'T use the standard components
grep -rn "loading\|Loading\|spinner\|Spinner" frontend/src/ --include="*.tsx" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "LoadingState" \
  | grep -v "components/ui" \
  | grep -i "state\|indicator\|spin"

grep -rn "empty\|Empty\|no.*results\|no.*data" frontend/src/ --include="*.tsx" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "EmptyState" \
  | grep -v "components/ui" \
  | grep -i "state\|placeholder\|message"

grep -rn "error\|Error" frontend/src/ --include="*.tsx" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "ErrorState\|ErrorBoundary" \
  | grep -v "components/ui" \
  | grep -i "state\|display\|message\|fallback"
```

Flag any custom loading/empty/error patterns that duplicate what `LoadingState`, `EmptyState`, and `ErrorState` already provide.

#### 2g. Dialog conformance

```bash
grep -rn "<Dialog\|<DialogContent\|<DialogHeader\|<DialogFooter" frontend/src/ --include="*.tsx" 2>/dev/null | grep -v node_modules | grep -v "components/ui/dialog"
```

Check `DialogFooter` uses proper stacking (`flex-col-reverse sm:flex-row`) for mobile.

**Output:** Component conformance table — Component | Usage count | Violations | Guide rule | Fix

---

### Subagent 3: Layout & Spacing Conformance (GUIDE-04)

**Goal:** Verify all pages use `PageShell`, `PageHeader`, and the documented spacing system.

**Process:**

#### 3a. PageShell coverage

```bash
# Read PageShell component
find frontend/src/components/layout -name "PageShell*" -exec cat {} \;

# Which pages use PageShell?
grep -rn "PageShell" frontend/src/pages/ --include="*.tsx" 2>/dev/null | grep -v node_modules

# Which pages DON'T use PageShell? (potential violations)
find frontend/src/pages -name "*.tsx" 2>/dev/null | while read f; do
  if ! grep -q "PageShell" "$f"; then
    echo "NO PAGESHELL: $f"
  fi
done
```

Check exemptions — the guide says "All standard (non-builder, non-admin) pages must be wrapped in PageShell." Builder and admin pages have their own layouts.

#### 3b. Inline page-level padding (Anti-Pattern #7)

```bash
# Pages adding their own max-width or page-level padding (should use PageShell)
find frontend/src/pages -name "*.tsx" 2>/dev/null | while read f; do
  hits=$(grep -n "max-w-\|mx-auto.*px-\|container\b" "$f" 2>/dev/null | grep -v "PageShell\|import")
  if [ -n "$hits" ]; then
    echo "=== $f ==="
    echo "$hits"
  fi
done
```

#### 3c. PageHeader usage

```bash
# Which pages use PageHeader?
grep -rn "PageHeader" frontend/src/pages/ --include="*.tsx" 2>/dev/null | grep -v node_modules

# Pages with custom h1/h2 that might need PageHeader instead
find frontend/src/pages -name "*.tsx" -exec grep -ln "<h1\|<h2" {} 2>/dev/null \; | while read f; do
  if ! grep -q "PageHeader" "$f"; then
    echo "CUSTOM HEADING (no PageHeader): $f"
  fi
done
```

#### 3d. Spacing consistency

```bash
# Spacing values used across pages
grep -rn "space-y-\|gap-\|p-\|px-\|py-\|m-\|mx-\|my-\|mt-\|mb-\|ml-\|mr-" frontend/src/pages/ --include="*.tsx" 2>/dev/null \
  | grep -v node_modules \
  | sed 's/.*\(space-y-[0-9]*\|gap-[0-9]*\|p-[0-9]*\|px-[0-9]*\|py-[0-9]*\).*/\1/' \
  | sort | uniq -c | sort -rn | head -20
```

Check against documented conventions:

- Page padding: `px-6 py-4` (via PageShell)
- Page section rhythm: `space-y-4` (via PageShell)
- Between major sections: `space-y-6` (when not using PageShell rhythm)
- Tight within sections: `space-y-3` (compact component internals, PageHeader)
- Within sections: `space-y-4`
- Form field gaps: `space-y-4`
- Grid gaps: `gap-3` (tight grids), `gap-4` or `gap-6` (standard)
- Inline gaps: `gap-2`

Flag non-standard spacing values (e.g., `space-y-5`, `p-5`, `gap-5`) that break the rhythm. Note: `space-y-3` and `gap-3` are intentional for compact/tight layouts — do not flag.

#### 3e. Typography hierarchy

```bash
# Heading usage
grep -rn "text-2xl\|text-xl\|text-lg\|text-3xl\|font-semibold\|font-bold" frontend/src/pages/ --include="*.tsx" 2>/dev/null | grep -v node_modules | head -40
```

Check against guide:
- Page title: `text-2xl font-semibold`
- Large page title: `text-3xl font-bold`
- Section heading: `text-lg font-semibold`
- Body text: `text-sm` (default)
- Caption: `text-xs text-muted-foreground`

Flag mismatches (e.g., `text-xl font-bold` for a section heading should be `text-lg font-semibold`).

**Output:** Layout conformance checklist — Page | PageShell? | PageHeader? | Spacing violations | Typography violations

---

### Subagent 4: Map Convention Conformance (GUIDE-05)

**Goal:** Verify map components follow the documented color constants, popup styling, drawing toolbar, and MapLibre CSS rules.

**Process:**

#### 4a. MAP_COLORS usage

```bash
# Read the actual map-colors.ts
cat frontend/src/lib/map-colors.ts

# Who imports from map-colors.ts?
grep -rn "map-colors\|MAP_COLORS\|mapColors" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules

# Hardcoded hex in map components (should use MAP_COLORS)
find frontend/src/components/map frontend/src/components/builder frontend/src/components/drawing -name "*.tsx" -name "*.ts" 2>/dev/null | while read f; do
  hits=$(grep -n "#[0-9a-fA-F]\{6\}" "$f" 2>/dev/null | grep -v "import\|MAP_COLORS\|map-colors")
  if [ -n "$hits" ]; then
    echo "=== $f ==="
    echo "$hits"
  fi
done
```

#### 4b. MapLibre CSS rules

```bash
# CSS transitions on map containers (GUIDE-05 rule: DO NOT)
grep -rn "transition\|transform" frontend/src/components/map/ frontend/src/components/builder/ --include="*.tsx" --include="*.ts" --include="*.css" 2>/dev/null | grep -v node_modules

# CSS var() in MapLibre paint properties (GUIDE-05 rule: DO NOT)
grep -rn "var(--" frontend/src/components/map/ frontend/src/components/builder/ --include="*.tsx" --include="*.ts" 2>/dev/null \
  | grep -v node_modules \
  | grep -i "paint\|layer\|style\|fill\|stroke\|color\|opacity\|width\|radius"

# Minzoom check — should be at least 1 for PostGIS sources
grep -rn "minzoom\|minZoom\|min_zoom" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules
```

#### 4c. Popup styling

```bash
# Popup CSS overrides in index.css
grep -A 30 "maplibregl-popup" frontend/src/index.css 2>/dev/null

# FeaturePopup component
find frontend/src -name "*FeaturePopup*" -o -name "*Popup*" 2>/dev/null | grep -E "\.(tsx|ts)$" | while read f; do
  echo "=== $f ==="
  cat "$f"
done
```

Check:
- Popup uses `--popover` / `--popover-foreground` tokens (not hardcoded)
- Dark mode `.dark .maplibregl-popup-content` overrides exist
- Tip anchors recolored in dark mode
- Excluded keys: `geom`, `geometry`, keys starting with `_`

#### 4d. Drawing toolbar

```bash
find frontend/src -name "*DrawingToolbar*" -exec cat {} \;
```

Check:
- Position: `absolute top-3 left-1/2 -translate-x-1/2 z-10`
- Active mode: `variant="default"`, inactive: `variant="outline"`
- Button size: `sm`
- Undo shortcut: Ctrl+Z
- Editing action bar present for selected features

#### 4e. Basemap picker

```bash
find frontend/src -name "*BasemapPicker*" -exec cat {} \;
```

Check:
- Grid: `grid-cols-4 gap-2`
- Active highlight: `ring-2 ring-primary bg-accent`
- Built-in basemaps use imported PNG assets; unknown/custom basemaps use inline SVG data URI fallback

#### 4f. Style color picker

```bash
find frontend/src -name "*StyleColorPicker*" -exec cat {} \;
```

Check:
- 16 preset swatches in `grid-cols-8 gap-1`
- Active swatch: `ring-2 ring-primary ring-offset-1`
- react-colorful `HexColorPicker` for custom colors

#### 4g. Map categorical palette sync

Verify `MAP_COLORS` categorical palette matches `--viz-*` tokens (guide says they should match):

```bash
# Extract viz tokens from index.css
grep "viz-" frontend/src/index.css | head -20

# Extract categorical palette from map-colors.ts
grep -A 20 "categorical\|palette\|CATEGORICAL" frontend/src/lib/map-colors.ts 2>/dev/null
```

**Output:** Map conformance table — Component | Guide rule | Status | Violations

---

### Subagent 5: Dark Mode Conformance (GUIDE-06)

**Goal:** Verify every component and page works correctly in dark mode using the documented token strategy.

**Process:**

#### 5a. Dark mode checklist scan

Run the guide's own dark mode checklist against every component:

```bash
# bg-white instead of bg-card or bg-background
grep -rn "bg-white" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules | grep -v "index.css"

# text-black/text-white instead of text-foreground (except on explicitly colored backgrounds)
grep -rn "text-black\b\|text-white\b" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "index.css" \
  | grep -v "status-colors.ts" \
  | grep -v "text-white.*destructive\|destructive.*text-white"

# Hardcoded opacity for text hierarchy instead of muted-foreground
grep -rn "opacity-\(50\|60\|70\|75\)" frontend/src/ --include="*.tsx" 2>/dev/null \
  | grep -v node_modules \
  | grep -i "text\|label\|caption\|description"
```

#### 5b. Dark mode class usage

```bash
# Components using dark: modifier — verify they match token strategy
grep -rn "dark:" frontend/src/ --include="*.tsx" --include="*.ts" --include="*.css" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "index.css" \
  | grep -v "status-colors.ts" \
  | head -50
```

The design guide's approach: tokens handle dark mode automatically via the `.dark` CSS block. Explicit `dark:` modifiers should be rare and only for cases where the token approach doesn't suffice (like `dark:bg-input/30`).

Flag excessive `dark:` modifier usage — it suggests the component is fighting the token system instead of using it.

#### 5c. Theme infrastructure

```bash
# ThemeProvider
find frontend/src -name "*ThemeProvider*" -o -name "*theme-provider*" 2>/dev/null | while read f; do
  echo "=== $f ==="
  cat "$f"
done

# useTheme hook usage
grep -rn "useTheme" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules

# FOUC prevention script in index.html
cat frontend/index.html 2>/dev/null | grep -A 10 "theme\|dark"

# Storage key
grep -rn "geolens-theme" frontend/src/ --include="*.tsx" --include="*.ts" --include="*.html" 2>/dev/null | grep -v node_modules
```

#### 5d. Primary scale inversion verification

The guide says dark mode inverts the primary scale: 50 is darkest, 900 is lightest. Verify in `index.css`:

```bash
# Extract primary scale from both :root and .dark blocks
sed -n '/:root/,/}/p' frontend/src/index.css | grep "primary-"
sed -n '/.dark/,/}/p' frontend/src/index.css | grep "primary-"
```

Verify lightness values increase from 50→900 in light mode and the scale inverts in dark mode.

**Output:** Dark mode violations table — File:Line | Issue | Guide rule | Fix

---

### Subagent 6: WCAG 2.1 AA Accessibility Audit

**Goal:** Full accessibility audit against WCAG 2.1 Level AA success criteria.

**Process:**

#### 6a. Color contrast (WCAG 1.4.3, 1.4.11)

**Text contrast (1.4.3 — minimum 4.5:1 for normal text, 3:1 for large text):**

Compute contrast ratios for every foreground/background token pair used in the guide. The OKLCH values are given — convert to sRGB and compute relative luminance ratios.

Key pairs to verify:
```
foreground on background (body text)
card-foreground on card (card text)
popover-foreground on popover
muted-foreground on background (secondary text — MOST LIKELY TO FAIL)
muted-foreground on card
muted-foreground on muted
primary-foreground on primary (button text)
destructive-foreground on destructive
success-foreground on success
warning-foreground on warning
info-foreground on info
sidebar-foreground on sidebar
```

Check BOTH light and dark mode values.

**Non-text contrast (1.4.11 — minimum 3:1 for UI components):**
- Border color (`--border`) against background
- Input border (`--input`) against background
- Focus ring (`--ring`) against background
- Icon colors against their backgrounds

```bash
# Find icons without sufficient contrast handling
grep -rn "text-muted-foreground.*icon\|icon.*text-muted-foreground\|className.*muted.*svg\|className.*muted.*Icon" frontend/src/ --include="*.tsx" 2>/dev/null | grep -v node_modules | head -20
```

#### 6b. Keyboard navigation (WCAG 2.1.1, 2.1.2, 2.4.7)

```bash
# Interactive elements that might not be keyboard accessible
# Custom click handlers on non-interactive elements
grep -rn "onClick.*<div\|onClick.*<span\|onClick.*<td\|onClick.*<li" frontend/src/ --include="*.tsx" 2>/dev/null | grep -v node_modules | head -30

# Missing role attributes on clickable non-button elements
grep -rn "onClick" frontend/src/ --include="*.tsx" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "<button\|<Button\|<a \|<Link\|<input\|role=" \
  | head -20

# Focus trap in modals/dialogs
grep -rn "FocusTrap\|focus.*trap\|inert\|aria-modal" frontend/src/ --include="*.tsx" 2>/dev/null | grep -v node_modules

# Tab order issues — tabIndex values other than 0 or -1
grep -rn "tabIndex\|tabindex" frontend/src/ --include="*.tsx" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "tabIndex={0}\|tabIndex={-1}\|tabindex=\"0\"\|tabindex=\"-1\""
```

Check focus ring standard compliance (GUIDE-03):
```bash
# Components missing focus-visible ring
grep -rn "focus-visible\|focus:" frontend/src/components/ui/ --include="*.tsx" 2>/dev/null | grep -v node_modules
```

All interactive components must have `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2` (or `ring-inset` for table rows).

#### 6c. ARIA and semantic HTML (WCAG 1.3.1, 4.1.2)

```bash
# Images without alt text
grep -rn "<img" frontend/src/ --include="*.tsx" 2>/dev/null | grep -v node_modules | grep -v "alt="

# SVG icons without aria-label or aria-hidden
grep -rn "<svg\|<Icon\|lucide" frontend/src/ --include="*.tsx" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "aria-hidden\|aria-label\|role=\"img\"\|role=\"presentation\"" \
  | head -20

# Form inputs without labels
grep -rn "<Input\|<Select\|<input\|<select\|<textarea" frontend/src/ --include="*.tsx" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "aria-label\|aria-labelledby\|id=.*<Label\|htmlFor" \
  | head -20

# Landmark regions
grep -rn "<nav\|<main\|<aside\|<header\|<footer\|role=\"navigation\"\|role=\"main\"\|role=\"complementary\"" frontend/src/ --include="*.tsx" 2>/dev/null | grep -v node_modules

# Live regions for dynamic content
grep -rn "aria-live\|role=\"alert\"\|role=\"status\"\|aria-atomic" frontend/src/ --include="*.tsx" 2>/dev/null | grep -v node_modules
```

#### 6d. Text and content (WCAG 1.4.4, 1.4.10, 1.4.12, 2.4.2, 2.4.6)

```bash
# Fixed pixel font sizes (should use rem — WCAG 1.4.4 text resize)
grep -rn "font-size:.*px\|fontSize:.*px\|text-\[.*px\]" frontend/src/ --include="*.tsx" --include="*.ts" --include="*.css" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "index.css"

# Page titles (WCAG 2.4.2)
grep -rn "document.title\|<title>\|useTitle\|Helmet\|<head>" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null | grep -v node_modules

# Heading hierarchy (WCAG 2.4.6, 1.3.1) — check for skipped levels
grep -rn "<h[1-6]\|role=\"heading\"" frontend/src/pages/ --include="*.tsx" 2>/dev/null | grep -v node_modules | sort
```

#### 6e. Responsive and reflow (WCAG 1.4.10)

```bash
# Fixed widths that might prevent reflow at 320px
grep -rn "w-\[\|min-w-\[\|width:" frontend/src/ --include="*.tsx" --include="*.ts" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "min-w-0\|w-full\|w-screen" \
  | grep -i "px\]" \
  | head -20

# Horizontal overflow containers without visible scrollbar or indication
grep -rn "overflow-x-auto\|overflow-x-hidden\|overflow-hidden" frontend/src/ --include="*.tsx" 2>/dev/null | grep -v node_modules | head -20
```

#### 6f. Motion and animation (WCAG 2.3.1, 2.3.3)

```bash
# Respects prefers-reduced-motion?
grep -rn "prefers-reduced-motion\|reduced-motion\|motionSafe\|motionReduce" frontend/src/ --include="*.tsx" --include="*.ts" --include="*.css" 2>/dev/null | grep -v node_modules

# Animations that might not respect reduced-motion
grep -rn "animate-\|animation\|@keyframes" frontend/src/ --include="*.tsx" --include="*.ts" --include="*.css" 2>/dev/null \
  | grep -v node_modules \
  | grep -v "index.css" \
  | head -20
```

The guide defines `fade-in` (200ms) and `shimmer` (1.5s infinite) animations. Verify `shimmer` (infinite loop) respects `prefers-reduced-motion`.

#### 6g. Map accessibility

MapLibre GL maps present unique accessibility challenges:

```bash
# Map ARIA roles and labels
grep -rn "aria-label\|role=\|tabIndex" frontend/src/components/map/ frontend/src/components/builder/ --include="*.tsx" 2>/dev/null | grep -v node_modules

# Keyboard interaction for map features
grep -rn "onKeyDown\|onKeyUp\|onKeyPress\|keyboard" frontend/src/components/map/ frontend/src/components/builder/ --include="*.tsx" 2>/dev/null | grep -v node_modules

# Screen reader announcements for map state changes
grep -rn "aria-live\|announceToScreenReader\|sr-only" frontend/src/components/map/ frontend/src/components/builder/ --include="*.tsx" 2>/dev/null | grep -v node_modules
```

Check:
- Map container has `role` and `aria-label`
- Feature popups are keyboard-reachable
- Drawing mode changes are announced
- Non-visual alternatives exist for spatial data (data table tab)

**Output:** WCAG 2.1 AA compliance matrix — Success Criterion | Level | Status (Pass/Fail/Partial/N/A) | Findings | Remediation

---

### Subagent 7: Tailwind v4 & Build Configuration (GUIDE-01 Anti-Patterns #3, #4)

**Goal:** Verify the Tailwind v4 CSS-first configuration is correct and no legacy patterns are present.

**Process:**

#### 7a. No tailwind.config.js (Anti-Pattern #3)

```bash
# This file should NOT exist
ls -la tailwind.config.* frontend/tailwind.config.* 2>/dev/null
```

If it exists, flag as a violation — all theme config must live in `index.css` via `@theme inline`.

#### 7b. @theme inline usage (Anti-Pattern #4)

```bash
# Verify @theme inline is used, not bare @theme
grep -n "@theme" frontend/src/index.css 2>/dev/null
```

Must be `@theme inline`. Without `inline`, Tailwind bakes values at build time, breaking opacity modifiers and `var()` reactive references.

#### 7c. Token bridge completeness

```bash
# Verify the @theme inline block maps all CSS custom properties to Tailwind utilities
grep -A 200 "@theme inline" frontend/src/index.css 2>/dev/null

# Check that every --color-* mapping exists for every token used in components
grep -rn "bg-\|text-\|border-\|ring-\|shadow-" frontend/src/components/ --include="*.tsx" 2>/dev/null \
  | grep -v node_modules \
  | sed 's/.*\(bg-[a-z-]*\|text-[a-z-]*\|border-[a-z-]*\|ring-[a-z-]*\).*/\1/' \
  | sort -u | head -50
```

Cross-reference: every Tailwind utility class used in components must have a corresponding `--color-*` mapping in the `@theme inline` block or be a built-in Tailwind utility.

#### 7d. Font configuration

```bash
# IBM Plex Sans Variable font import
grep -rn "fontsource\|IBM Plex\|ibm-plex" frontend/src/ --include="*.tsx" --include="*.ts" --include="*.css" 2>/dev/null | grep -v node_modules

# Antialiasing
grep -rn "antialiased" frontend/src/index.css 2>/dev/null
```

Verify: `@fontsource-variable/ibm-plex-sans` and `@fontsource/ibm-plex-mono` are imported, `--font-sans` includes `'IBM Plex Sans Variable'`, `--font-mono` includes `'IBM Plex Mono'`, body has `antialiased`.

#### 7e. Legacy artifact scan

```bash
# Any references to tailwindcss v3 patterns
grep -rn "darkMode:\|content:\s*\[" frontend/tailwind.config.* tailwind.config.* 2>/dev/null
grep -rn "@tailwind base\|@tailwind components\|@tailwind utilities" frontend/src/ --include="*.css" 2>/dev/null | grep -v node_modules

# PostCSS config that might conflict
cat frontend/postcss.config.* postcss.config.* 2>/dev/null
```

**Output:** Build configuration health check — Item | Expected | Actual | Status

---

## SYNTHESIS (Serial — after all subagents complete)

### Scoring

| Dimension | What it measures | Guide section |
|-----------|-----------------|---------------|
| **Token Conformance** | Semantic tokens used, no hardcoded colors, correct hierarchy | GUIDE-01 |
| **Component Patterns** | Buttons, cards, badges, etc. match documented specs | GUIDE-03 |
| **Layout & Spacing** | PageShell, PageHeader, spacing rhythm, typography hierarchy | GUIDE-04 |
| **Map Conventions** | MAP_COLORS, popup styling, MapLibre CSS rules | GUIDE-05 |
| **Dark Mode** | Token-driven theming, no hardcoded light-mode values | GUIDE-06 |
| **Accessibility (WCAG)** | Color contrast, keyboard nav, ARIA, landmarks, motion | WCAG 2.1 AA |
| **Build Configuration** | Tailwind v4 CSS-first, @theme inline, no legacy | Anti-patterns |

Grade each A–F:
- **A** — Fully conformant. No violations.
- **B** — 1–5 minor violations. No pattern-level issues.
- **C** — 6–15 violations or 1–2 pattern-level issues (e.g., a whole page missing PageShell).
- **D** — Widespread violations. Design system is partially followed.
- **F** — Design system is not followed. Tokens are not used.

### Drift Score

Calculate: `(total components audited - components with violations) / total components audited × 100`

This is the **design system adoption rate**. Above 90% is healthy. Below 70% means the guide isn't being enforced.

### WCAG Compliance Summary

```
| Level | Total Criteria | Pass | Fail | Partial | N/A |
|-------|---------------|------|------|---------|-----|
| A     | XX            | XX   | XX   | XX      | XX  |
| AA    | XX            | XX   | XX   | XX      | XX  |
```

### Action Items

| Field | Description |
|-------|-------------|
| Priority | P0 (accessibility blocker — legal risk), P1 (design system violation — visual inconsistency), P2 (minor drift — cosmetic) |
| Action | Specific fix with file:line |
| Category | Tokens / Components / Layout / Map / Dark Mode / WCAG / Build |
| Guide Rule | Which design guide section or WCAG criterion |
| Effort | Hours estimate |
| Scope | Single component vs. pattern-level change |

Sort by: priority → scope (pattern-level first) → effort.

### Guide Update Recommendations

If the audit finds areas where the code has intentionally diverged from the guide, recommend guide updates. The guide says: "if it disagrees with the code, the code wins and this guide needs updating."

---

## DELIVERY

### Output format

Write the report to: `docs-internal/audits/design-audit-{YYYYMMDD}.md`

### Report structure

```markdown
# Design System & Accessibility Audit — {YYYY-MM-DD}

## Scorecard
<!-- Grades per dimension + drift score + WCAG summary -->

## Executive Summary
<!-- 3-5 sentences: conformance posture, biggest drift areas, accessibility status -->

## 1. Design Token Conformance
### 1a. Hardcoded Colors
### 1b. Raw Palette Classes
### 1c. Token Hierarchy Violations
### 1d. Shadow & Border Tokens
### 1e. Transition Anti-Pattern
### 1f. Extended Token Categories (Record-Type, Code, Map, Signature)
### 1g. Token Sync (Guide vs. Code)

## 2. Component Pattern Conformance
### 2a. Button Usage
### 2b. Card Usage
### 2c. Badge & Status Colors
### 2d. Table Conformance
### 2e. State Components (Loading/Empty/Error)
### 2f. Dialog Conformance

## 3. Layout & Spacing
### 3a. PageShell Coverage
### 3b. PageHeader Usage
### 3c. Spacing Rhythm
### 3d. Typography Hierarchy

## 4. Map Conventions
### 4a. MAP_COLORS Usage
### 4b. MapLibre CSS Rules
### 4c. Popup Styling
### 4d. Drawing Toolbar
### 4e. Basemap & Color Picker

## 5. Dark Mode
### 5a. Hardcoded Light-Mode Values
### 5b. Excessive dark: Modifiers
### 5c. Theme Infrastructure
### 5d. Primary Scale Inversion

## 6. WCAG 2.1 AA Compliance
### 6a. Color Contrast
### 6b. Keyboard Navigation
### 6c. ARIA & Semantic HTML
### 6d. Text & Content
### 6e. Responsive & Reflow
### 6f. Motion & Animation
### 6g. Map Accessibility

## 7. Tailwind v4 Configuration
### 7a. No Legacy Config Files
### 7b. @theme inline
### 7c. Token Bridge Completeness
### 7d. Font Configuration

## 8. Guide Update Recommendations
<!-- Where the code has intentionally diverged from the guide -->

## 9. Prioritized Action Items
<!-- Action items table -->

## 10. Comparison to Prior Audit
<!-- If a previous design-audit exists, diff findings -->
```

### Post-delivery

1. If `lessons.md` exists, append reusable insights about design system enforcement.
2. Print summary: drift score + WCAG pass rate + P0 accessibility blocker count.

---

## RELATIONSHIP TO OTHER COMMANDS

- `/ux-review` — covers general usability heuristics and visual regression. This command is design-guide-specific + WCAG. They complement each other.
- `/ux-plan` — produces the UX engineering plan. This command audits whether the design system is being followed.
- `/doc-audit` — checks whether DESIGN-GUIDE.md itself is accurate and current.

---

## WHAT NOT TO FLAG

- **`status-colors.ts` using Tailwind palette classes** — The guide explicitly documents this exception. Tinted badge backgrounds need explicit palette classes for sufficient text contrast.
- **MAP_COLORS using hardcoded hex** — MapLibre GL cannot consume CSS custom properties. The guide documents this and mandates hex constants in `map-colors.ts`.
- **`StyleColorPicker` containing hex values** — It's a color picker; it must display actual color values.
- **Builder and admin pages not using PageShell** — They have their own layouts (`MapBuilderPage` uses full-viewport flex, `AdminLayout` uses sidebar provider). Only standard pages need PageShell.
- **`dark:` modifiers in UI primitives** — Some components legitimately need `dark:` (e.g., `dark:bg-input/30` on inputs). Only flag excessive use that suggests fighting the token system.
- **Decorative icons without aria-label** — Icons that are purely decorative should have `aria-hidden="true"`, not labels. Only flag icons that convey meaning without a text label.
- **MapLibre canvas not being keyboard-navigable** — WebGL canvases have inherent accessibility limitations. Flag the absence of non-visual alternatives (data table), not the canvas itself.
- **`text-base` on mobile inputs** — The guide documents this intentionally: "prevents iOS zoom on focus." Don't flag the `text-base md:text-sm` pattern on inputs.
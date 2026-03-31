# GeoLens Design Guide

This document is the single reference for visual consistency across GeoLens. Every value is extracted directly from source files -- if it disagrees with the code, the code wins and this guide needs updating.

## 1. Overview & Principles

GeoLens targets a clean, professional, data-focused aesthetic. The interface prioritizes content density without feeling cramped.

**Target platforms:** Desktop and tablet first. Mobile viewports are supported (responsive layouts, touch targets) but not optimized -- complex workflows like the map builder and data tables assume a wider viewport.

**Key principles:**

- **Generous whitespace** -- let content breathe with consistent spacing between sections and cards.
- **Subtle accents** -- neutral base palette with color reserved for meaningful signals (status, actions, data visualization).
- **Clear hierarchy** -- use font weight, size, and color to establish visual priority without decoration.
- **Muted backgrounds with vibrant status indicators** -- the neutral OKLCH grays make semantic colors (success, warning, destructive) immediately visible.

**Default rule:** When unsure which tokens or colors to use, stick with `background` + `card` + `primary`. Do not introduce new tokens or colors without a clear reason.

**Technical notes:**

- All colors use the **OKLCH** color space. OKLCH is perceptually uniform -- equal numeric changes in lightness produce equal perceived brightness changes. This means opacity modifiers like `bg-primary/50` produce predictable, visually consistent results across all token colors.
- All theme configuration lives in `frontend/src/index.css` via `@theme inline`. There is no `tailwind.config.js`.
- Token source of truth: `:root` (light) and `.dark` blocks in `index.css`.

## 2. Design Tokens (GUIDE-01)

Every token is defined in `frontend/src/index.css`. The `@theme inline` bridge maps raw CSS custom properties to Tailwind utility classes (e.g., `--color-primary: var(--primary)` enables `bg-primary`, `text-primary`).

### Token Usage Hierarchy

When styling a component, reach for tokens in this order:

1. **Semantic tokens first** -- `background`, `card`, `primary`, `foreground`, `muted-foreground`, `destructive`, `success`, `warning`, `info`. These cover 90% of use cases.
2. **Surface tokens for layering** -- `surface-0` through `surface-3`. Only when you need explicit elevation stacking beyond the card/popover defaults.
3. **Primary scale tokens (rare)** -- `primary-50` through `primary-900`. Only for custom tints that no semantic token provides (e.g., a subtle primary wash on a selected row).

**Hard rule:** Never use raw primary scale tokens for UI semantics. If you need "the action color", use `primary`. If you need "a subtle highlight", use `accent` or `muted`. The scale exists for edge cases, not daily use.

### Primary Scale (50-900)

10-step scale on blue hue 250. In dark mode the scale is **inverted**: 50 is the darkest step and 900 is the lightest. This allows `bg-primary-100` to always mean "subtle primary tint" regardless of theme.

| Token | Light Value | Dark Value | Tailwind Utility |
|-------|------------|------------|------------------|
| `--primary-50` | `oklch(0.97 0.02 250)` | `oklch(0.25 0.04 250)` | `bg-primary-50`, `text-primary-50` |
| `--primary-100` | `oklch(0.93 0.05 250)` | `oklch(0.30 0.07 250)` | `bg-primary-100`, `text-primary-100` |
| `--primary-200` | `oklch(0.87 0.09 250)` | `oklch(0.36 0.10 250)` | `bg-primary-200`, `text-primary-200` |
| `--primary-300` | `oklch(0.78 0.13 250)` | `oklch(0.44 0.14 250)` | `bg-primary-300`, `text-primary-300` |
| `--primary-400` | `oklch(0.70 0.16 250)` | `oklch(0.54 0.17 250)` | `bg-primary-400`, `text-primary-400` |
| `--primary-500` | `oklch(0.55 0.18 250)` | `oklch(0.65 0.18 250)` | `bg-primary-500`, `text-primary-500` |
| `--primary-600` | `oklch(0.48 0.18 250)` | `oklch(0.72 0.17 250)` | `bg-primary-600`, `text-primary-600` |
| `--primary-700` | `oklch(0.46 0.16 250)` | `oklch(0.80 0.14 250)` | `bg-primary-700`, `text-primary-700` |
| `--primary-800` | `oklch(0.38 0.13 250)` | `oklch(0.88 0.09 250)` | `bg-primary-800`, `text-primary-800` |
| `--primary-900` | `oklch(0.30 0.10 250)` | `oklch(0.94 0.04 250)` | `bg-primary-900`, `text-primary-900` |

### Core Palette

14 semantic tokens that define the application's base colors.

| Token | Light Value | Dark Value | Tailwind Utility | Usage |
|-------|------------|------------|------------------|-------|
| `--background` | `oklch(1 0 0)` | `oklch(0.145 0.008 250)` | `bg-background` | Page background |
| `--foreground` | `oklch(0.145 0 0)` | `oklch(0.985 0 0)` | `text-foreground` | Default body text |
| `--card` | `oklch(1 0 0)` | `oklch(0.18 0.008 250)` | `bg-card` | Card surfaces |
| `--card-foreground` | `oklch(0.145 0 0)` | `oklch(0.985 0 0)` | `text-card-foreground` | Text on cards |
| `--popover` | `oklch(1 0 0)` | `oklch(0.22 0.010 250)` | `bg-popover` | Dropdown/popover surfaces |
| `--popover-foreground` | `oklch(0.145 0 0)` | `oklch(0.985 0 0)` | `text-popover-foreground` | Text on popovers |
| `--primary` | `oklch(0.55 0.18 250)` | `oklch(0.72 0.17 250)` | `bg-primary`, `text-primary` | Primary action buttons, links |
| `--primary-foreground` | `oklch(0.985 0 0)` | `oklch(0.18 0.008 250)` | `text-primary-foreground` | Text on primary backgrounds |
| `--secondary` | `oklch(0.97 0 0)` | `oklch(0.269 0.008 250)` | `bg-secondary` | Secondary surfaces |
| `--secondary-foreground` | `oklch(0.205 0 0)` | `oklch(0.985 0 0)` | `text-secondary-foreground` | Text on secondary |
| `--muted` | `oklch(0.97 0 0)` | `oklch(0.269 0.008 250)` | `bg-muted` | Muted backgrounds |
| `--muted-foreground` | `oklch(0.45 0 0)` | `oklch(0.708 0 0)` | `text-muted-foreground` | De-emphasized text, captions |
| `--accent` | `oklch(0.97 0 0)` | `oklch(0.269 0.008 250)` | `bg-accent` | Hover/focus highlight |
| `--accent-foreground` | `oklch(0.205 0 0)` | `oklch(0.985 0 0)` | `text-accent-foreground` | Text on accent |
| `--destructive` | `oklch(0.577 0.245 27.325)` | `oklch(0.704 0.191 22.216)` | `bg-destructive`, `text-destructive` | Danger actions, error states |
| `--destructive-foreground` | `oklch(0.985 0 0)` | `oklch(0.25 0.05 22)` | `text-destructive-foreground` | Text on destructive backgrounds |

### Utility Tokens

| Token | Light Value | Dark Value | Tailwind Utility | Usage |
|-------|------------|------------|------------------|-------|
| `--border` | `oklch(0.87 0 0)` | `oklch(1 0 0 / 10%)` | `border-border` | Default border color |
| `--input` | `oklch(0.87 0 0)` | `oklch(1 0 0 / 15%)` | `border-input` | Form input borders |
| `--ring` | `oklch(0.55 0.18 250)` | `oklch(0.72 0.17 250)` | `ring-ring` | Focus ring color |
| `--radius` | `0.625rem` | `0.625rem` | `rounded-sm/md/lg/xl` | Border radius scale base |

### Surface Hierarchy

4-level surface system for layered elevation. Higher numbers = visually "above" lower surfaces.

| Token | Light Value | Dark Value | Tailwind Utility | Usage |
|-------|------------|------------|------------------|-------|
| `--surface-0` | `oklch(0.985 0 0)` | `oklch(0.145 0.008 250)` | `bg-surface-0` | Page base, deepest layer |
| `--surface-1` | `oklch(1 0 0)` | `oklch(0.18 0.008 250)` | `bg-surface-1` | Cards, panels |
| `--surface-2` | `oklch(0.98 0 0)` | `oklch(0.22 0.010 250)` | `bg-surface-2` | Popovers, dropdowns |
| `--surface-3` | `oklch(0.96 0 0)` | `oklch(0.26 0.012 250)` | `bg-surface-3` | Tooltips, top layer |

### Elevation Shadows

3-level shadow system. Dark mode uses **3-5x higher opacity** because shadows on dark surfaces need more contrast to be visible.

| Token | Light Value | Dark Value | Tailwind Utility |
|-------|------------|------------|------------------|
| `--elevation-sm` | `0 1px 2px oklch(0 0 0 / 5%)` | `0 1px 2px oklch(0 0 0 / 20%)` | `shadow-sm` |
| `--elevation-md` | `0 4px 6px -1px oklch(0 0 0 / 7%), 0 2px 4px -2px oklch(0 0 0 / 5%)` | `0 4px 6px -1px oklch(0 0 0 / 30%), 0 2px 4px -2px oklch(0 0 0 / 20%)` | `shadow-md` |
| `--elevation-lg` | `0 10px 15px -3px oklch(0 0 0 / 8%), 0 4px 6px -4px oklch(0 0 0 / 5%)` | `0 10px 15px -3px oklch(0 0 0 / 35%), 0 4px 6px -4px oklch(0 0 0 / 20%)` | `shadow-lg` |

### Status Colors

Semantic colors for application states.

| Token | Light Value | Dark Value | Tailwind Utility | Usage |
|-------|------------|------------|------------------|-------|
| `--success` | `oklch(0.53 0.19 145)` | `oklch(0.72 0.17 145)` | `bg-success`, `text-success` | Complete, active, public |
| `--success-foreground` | `oklch(0.985 0 0)` | `oklch(0.20 0.05 145)` | `text-success-foreground` | Text on success backgrounds |
| `--warning` | `oklch(0.75 0.15 85)` | `oklch(0.80 0.16 85)` | `bg-warning`, `text-warning` | Pending, restricted |
| `--warning-foreground` | `oklch(0.28 0.07 46)` | `oklch(0.28 0.07 46)` | `text-warning-foreground` | Text on warning backgrounds |
| `--info` | `oklch(0.55 0.15 195)` | `oklch(0.72 0.14 195)` | `bg-info`, `text-info` | Running, in-progress |
| `--info-foreground` | `oklch(0.985 0 0)` | `oklch(0.20 0.05 195)` | `text-info-foreground` | Text on info backgrounds |

### Data Visualization Palette

8-color categorical palette for charts and data visualization. Each color is named with a comment in `index.css`.

| Token | Light Value | Dark Value | Color | Tailwind Utility |
|-------|------------|------------|-------|------------------|
| `--viz-1` | `oklch(0.55 0.18 250)` | `oklch(0.72 0.17 250)` | blue | `bg-viz-1`, `text-viz-1` |
| `--viz-2` | `oklch(0.70 0.17 55)` | `oklch(0.76 0.16 55)` | orange | `bg-viz-2`, `text-viz-2` |
| `--viz-3` | `oklch(0.62 0.17 145)` | `oklch(0.72 0.16 145)` | green | `bg-viz-3`, `text-viz-3` |
| `--viz-4` | `oklch(0.55 0.18 310)` | `oklch(0.65 0.17 310)` | purple | `bg-viz-4`, `text-viz-4` |
| `--viz-5` | `oklch(0.65 0.13 195)` | `oklch(0.72 0.12 195)` | teal | `bg-viz-5`, `text-viz-5` |
| `--viz-6` | `oklch(0.65 0.20 5)` | `oklch(0.72 0.18 5)` | pink | `bg-viz-6`, `text-viz-6` |
| `--viz-7` | `oklch(0.75 0.16 80)` | `oklch(0.80 0.15 80)` | amber | `bg-viz-7`, `text-viz-7` |
| `--viz-8` | `oklch(0.50 0.18 280)` | `oklch(0.60 0.17 280)` | indigo | `bg-viz-8`, `text-viz-8` |

**Legacy chart tokens** (kept for compatibility with existing chart components):

| Token | Light Value | Dark Value |
|-------|------------|------------|
| `--chart-1` | `oklch(0.646 0.222 41.116)` | `oklch(0.488 0.18 264)` |
| `--chart-2` | `oklch(0.6 0.118 184.704)` | `oklch(0.696 0.17 145)` |
| `--chart-3` | `oklch(0.398 0.07 227.392)` | `oklch(0.769 0.188 70.08)` |
| `--chart-4` | `oklch(0.828 0.189 84.429)` | `oklch(0.627 0.18 303.9)` |
| `--chart-5` | `oklch(0.769 0.188 70.08)` | `oklch(0.645 0.18 16.439)` |

### Sidebar Tokens

| Token | Light Value | Dark Value | Tailwind Utility |
|-------|------------|------------|------------------|
| `--sidebar` | `oklch(0.985 0 0)` | `oklch(0.13 0.008 250)` | `bg-sidebar` |
| `--sidebar-foreground` | `oklch(0.145 0 0)` | `oklch(0.985 0 0)` | `text-sidebar-foreground` |
| `--sidebar-primary` | `oklch(0.55 0.18 250)` | `oklch(0.72 0.17 250)` | `bg-sidebar-primary` |
| `--sidebar-primary-foreground` | `oklch(0.985 0 0)` | `oklch(0.18 0.008 250)` | `text-sidebar-primary-foreground` |
| `--sidebar-accent` | `oklch(0.97 0 0)` | `oklch(0.269 0.008 250)` | `bg-sidebar-accent` |
| `--sidebar-accent-foreground` | `oklch(0.205 0 0)` | `oklch(0.985 0 0)` | `text-sidebar-accent-foreground` |
| `--sidebar-border` | `oklch(0.922 0 0)` | `oklch(1 0 0 / 10%)` | `border-sidebar-border` |
| `--sidebar-ring` | `oklch(0.55 0.18 250)` | `oklch(0.72 0.17 250)` | `ring-sidebar-ring` |

### Radius & Animation

**Radius scale** (base value `--radius: 0.625rem`):

| Tailwind Class | Computed Value |
|---------------|---------------|
| `rounded-sm` | `calc(0.625rem - 4px)` = ~0.375rem |
| `rounded-md` | `calc(0.625rem - 2px)` = ~0.5rem |
| `rounded-lg` | `0.625rem` |
| `rounded-xl` | `calc(0.625rem + 4px)` = ~0.875rem |

**Transition standard** (all interactive elements):

```
transition-[color,background-color,box-shadow,border-color,opacity] duration-200 ease-out
```

Never use `transition-all` -- it causes layout thrash by animating width, height, padding, and margin on every state change.

**Animations:**

| Name | Tailwind Utility | Definition | Usage |
|------|-----------------|------------|-------|
| `fade-in` | `animate-fade-in` | `fade-in 200ms ease-out both` | Page transitions |
| `shimmer` | `animate-shimmer` | `shimmer 1.5s ease-in-out infinite` | Skeleton loading placeholders |

## 3. Typography (GUIDE-02)

### Font Family

GeoLens uses **Inter Variable**, self-hosted via `@fontsource-variable/inter`. Configured in the `@theme inline` block:

```css
--font-sans: 'Inter Variable', ui-sans-serif, system-ui, sans-serif;
```

Applied to the body via `@apply bg-background text-foreground font-sans antialiased` in the base layer.

### Type Scale

| Size Class | Value | Pixels | Usage |
|-----------|-------|--------|-------|
| `text-xs` | 0.75rem | 12px | Captions, timestamps, badge text, table headers |
| `text-sm` | 0.875rem | 14px | Default body text, descriptions, table cells |
| `text-base` | 1rem | 16px | Input text (mobile), longer prose |
| `text-lg` | 1.125rem | 18px | Section headings, dialog titles |
| `text-xl` | 1.25rem | 20px | Sub-page titles |
| `text-2xl` | 1.5rem | 24px | Page titles |

### Heading Hierarchy

| Role | Classes | Example Usage |
|------|---------|---------------|
| Page title | `text-2xl font-semibold` | Dashboard heading, settings page title |
| Large page title | `text-3xl font-bold` | Landing/hero headings |
| Section heading | `text-lg font-semibold` | Card titles, form section labels, dialog titles |
| Body text | `text-sm` (default) | Descriptions, table cells, form help text |
| Caption / label | `text-xs text-muted-foreground` | Timestamps, metadata, field labels |
| Code / monospace | `font-mono text-sm` | API keys, file paths, code snippets |

### Weight Conventions

| Weight | Class | Usage |
|--------|-------|-------|
| 400 | `font-normal` | Body text, descriptions |
| 500 | `font-medium` | Table headers, labels, badges |
| 600 | `font-semibold` | Headings, buttons, emphasis |
| 700 | `font-bold` | Page titles when using `text-3xl` |

## 4. Spacing (GUIDE-06)

### Tailwind Spacing Scale

GeoLens uses Tailwind's default spacing scale. The most commonly used values:

| Token | Value | Pixels | Common Usage |
|-------|-------|--------|-------------|
| `2` | 0.5rem | 8px | Tight spacing, badge padding, icon gaps |
| `3` | 0.75rem | 12px | Tight within-section gaps, compact component internals |
| `4` | 1rem | 16px | Card padding (compact), form field gaps |
| `6` | 1.5rem | 24px | Page padding, section gaps, generous card padding |
| `8` | 2rem | 32px | Large section separation |

### Spacing Conventions

| Context | Classes | Notes |
|---------|---------|-------|
| Page-level padding | `px-6 py-6` | Enforced by PageShell |
| Card internal padding | `p-4` or `p-6` | `p-4` for compact cards, `p-6` for detail cards |
| Between major sections | `space-y-6` | Top-level page sections |
| Tight within sections | `space-y-3` | Compact component internals (headers, panels) |
| Within sections | `space-y-4` | Items within a section |
| Form field gaps | `space-y-4` | Between label+input groups |
| Grid gaps | `gap-3`, `gap-4`, or `gap-6` | `gap-3` for tight grids, `gap-4`/`gap-6` for standard |
| Inline element gaps | `gap-2` | Between badges, icons, inline items |

## 5. Icon Sizing (GUIDE-06)

4 standard icon size tiers used consistently across all components:

| Tier | Classes | Context | Examples |
|------|---------|---------|----------|
| Compact | `h-3 w-3` / `size-3` | xs button icons, builder toolbar | Icon-only xs buttons, badge icons |
| Standard | `h-4 w-4` / `size-4` | Inline icons in buttons, menu items, links | Default button icons, nav items, select chevrons |
| Standalone | `size-8` | Loading spinners, error indicators | `LoadingState` spinner, `ErrorState` alert icon |
| Hero | `size-10` | Empty state hero icons | `EmptyState` icon |

Rules:
- Button component auto-sizes SVG children: `[&_svg:not([class*='size-'])]:size-4` for default sizes, `:size-3` for `xs` and `icon-xs` sizes.
- Badge component auto-sizes SVG children: `[&>svg]:size-3`.
- Always let the parent component handle icon sizing unless a specific override is needed.

## 6. Components (GUIDE-03)

### Button

**Import:** `import { Button } from '@/components/ui/button'`

**Variants:**

| Variant | Classes | When to Use |
|---------|---------|-------------|
| `default` | `bg-primary text-primary-foreground hover:bg-primary/90` | Primary actions (save, create, submit) |
| `destructive` | `bg-destructive text-destructive-foreground hover:bg-destructive/90 dark:bg-destructive/60` | Dangerous actions (delete, remove) |
| `outline` | `border bg-background shadow-xs hover:bg-accent dark:bg-input/30` | Tertiary actions, less emphasis |
| `secondary` | `bg-secondary text-secondary-foreground hover:bg-secondary/80` | Secondary actions (cancel, back) |
| `ghost` | `hover:bg-accent hover:text-accent-foreground dark:hover:bg-accent/50` | Minimal chrome (icon buttons, inline actions) |
| `link` | `text-primary underline-offset-4 hover:underline` | Inline text links styled as buttons |

**Sizes:**

| Size | Classes | Dimensions | When to Use |
|------|---------|-----------|-------------|
| `default` | `h-9 px-4 py-2 has-[>svg]:px-3` | 36px height | Standard button |
| `xs` | `h-6 gap-1 px-2 text-xs has-[>svg]:px-1.5` | 24px height | Compact inline actions, toolbar items |
| `sm` | `h-8 gap-1.5 px-3 has-[>svg]:px-2.5` | 32px height | Secondary/tight layouts |
| `lg` | `h-10 px-6 has-[>svg]:px-4` | 40px height | Prominent CTAs |
| `icon` | `size-9` | 36x36px square | Icon-only default |
| `icon-xs` | `size-6 [&_svg]:size-3` | 24x24px square | Compact icon buttons (close, toolbar) |
| `icon-sm` | `size-8` | 32x32px square | Icon-only in tight spaces |
| `icon-lg` | `size-10` | 40x40px square | Prominent icon buttons |

**Rules:**
- Default variant for primary page actions. One primary button per form/dialog.
- `destructive` for irreversible actions. Always pair with a confirmation dialog.
- `asChild` prop renders the button as its child element (for wrapping `<Link>` etc.).

### Card

**Import:** `import { Card, CardHeader, CardTitle, CardDescription, CardAction, CardContent, CardFooter } from '@/components/ui/card'`

Cards use **shadow-only elevation** -- no border in the base component. The shadow provides visual lift.

**Base classes:** `bg-card text-card-foreground rounded-lg py-6 shadow-sm hover:shadow-md transition-shadow duration-200 ease-out`

**Sub-components:**

| Component | Key Classes | Purpose |
|-----------|-----------|---------|
| `CardHeader` | `px-6 gap-2 grid auto-rows-min` | Title + description + optional action layout |
| `CardTitle` | `leading-none font-semibold` | Card heading (inherits parent font-size) |
| `CardDescription` | `text-muted-foreground text-sm` | Subtitle/description |
| `CardAction` | `col-start-2 row-span-2 self-start justify-self-end` | Top-right action slot |
| `CardContent` | `px-6` | Main content area |
| `CardFooter` | `flex items-center px-6` | Bottom action bar |

**Rules:**
- Cards have `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2` for keyboard accessibility.
- Use `CardAction` for top-right buttons/menus instead of absolute positioning.
- Internal gap between sub-components is `gap-6` (built into Card flex layout).

### Badge

**Import:** `import { Badge } from '@/components/ui/badge'`

**Base classes:** `inline-flex items-center rounded-full border-transparent px-2 py-0.5 text-xs font-medium`

**Variants:**

| Variant | Classes | When to Use |
|---------|---------|-------------|
| `default` | `bg-primary text-primary-foreground` | Primary category labels |
| `secondary` | `bg-secondary text-secondary-foreground` | Neutral metadata tags |
| `destructive` | `bg-destructive text-destructive-foreground dark:bg-destructive/60` | Error/failure states |
| `outline` | `border-border text-foreground` | Subtle, bordered tags |
| `ghost` | (no background) | Minimal inline labels |
| `link` | `text-primary underline-offset-4` | Clickable badge links |

**Rules:**
- Auto-sizes SVG children to `size-3` with `gap-1`.
- Supports `asChild` for rendering as a different element.
- For status-specific badges, prefer the status-colors pattern (see Status Badges below).

### Table

**Import:** `import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell, TableFooter, TableCaption } from '@/components/ui/table'`

**Sub-component classes:**

| Component | Key Classes | Notes |
|-----------|-----------|-------|
| `Table` | `w-full caption-bottom text-sm` | Wrapped in `overflow-x-auto` container |
| `TableHeader` | `[&_tr]:border-b` | Bottom border on header rows |
| `TableHead` | `text-muted-foreground h-10 px-4 py-3 text-xs uppercase tracking-wide font-medium whitespace-nowrap` | Uppercase, xs size, wide tracking |
| `TableRow` | `hover:bg-muted/50 data-[state=selected]:bg-muted border-b` | Hover highlight, selection state |
| `TableCell` | `px-4 py-3 whitespace-nowrap` | Consistent padding |
| `TableFooter` | `bg-muted/50 border-t font-medium` | Summary/total rows |

**Focus ring exception:** Table rows use `focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring` (inset ring to avoid layout shift, unlike the standard offset ring).

### Dialog

**Import:** `import { Dialog, DialogTrigger, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter, DialogClose } from '@/components/ui/dialog'`

Built on Radix UI Dialog primitive. Content renders in a portal with an overlay.

**Key properties:**
- Content: `bg-background rounded-lg border p-6 shadow-lg sm:max-w-lg`
- Overlay: `bg-black/50` with fade animation
- Close button (X) in top-right corner, controlled by `showCloseButton` prop (default `true`)
- `DialogFooter` supports `showCloseButton` prop to add an "outline Close" button

**Sub-components:**

| Component | Key Classes | Purpose |
|-----------|-----------|---------|
| `DialogHeader` | `flex flex-col gap-2 text-center sm:text-left` | Title + description container |
| `DialogTitle` | `text-lg leading-none font-semibold` | Dialog heading |
| `DialogDescription` | `text-muted-foreground text-sm` | Explanatory text |
| `DialogFooter` | `flex flex-col-reverse gap-2 sm:flex-row sm:justify-end` | Action buttons, stacks on mobile |

### Select

**Import:** `import { Select, SelectTrigger, SelectContent, SelectItem, SelectValue, SelectGroup, SelectLabel, SelectSeparator } from '@/components/ui/select'`

Built on Radix UI Select primitive.

**Sizes:**

| Size | Height | Usage |
|------|--------|-------|
| `default` | `h-9` (36px) | Standard form selects |
| `sm` | `h-8` (32px) | Compact/inline selects |

**Trigger classes:** `border-input rounded-md border bg-transparent px-3 py-2 text-sm shadow-xs`

Dark mode: `dark:bg-input/30 dark:hover:bg-input/50`

### Input

**Import:** `import { Input } from '@/components/ui/input'`

**Base classes:** `h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-base shadow-xs md:text-sm`

Dark mode: `dark:bg-input/30`

**Focus ring:** `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background`

**Validation state:** `aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive`

**Rules:**
- Text renders `text-base` on mobile, `md:text-sm` on desktop (prevents iOS zoom on focus).
- File inputs have custom styling: `file:inline-flex file:h-7 file:bg-transparent file:text-sm file:font-medium`.

### State Components

Three layout components for common loading/empty/error states.

**EmptyState** (`@/components/layout/EmptyState`)

Props: `icon` (component), `title` (string), `description?` (string), `action?` (ReactNode). Classes: `py-16 gap-4`, icon `size-10 text-muted-foreground/50`, title `text-lg font-medium`, description `text-sm text-muted-foreground`.

**LoadingState** (`@/components/layout/LoadingState`)

Props: `message?` (string). Classes: `py-16 gap-3`, spinner `size-8 animate-spin text-muted-foreground`, message `text-sm text-muted-foreground`.

**ErrorState** (`@/components/layout/ErrorState`)

Props: `message` (string), `title?` (string), `action?` (ReactNode). Classes: `rounded-lg border border-destructive/30 bg-destructive/5 p-6`, icon `size-8 text-destructive`, title `text-lg font-semibold`, message `text-sm text-destructive`.

### Status Badges

All status-related colors are centralized in `frontend/src/lib/status-colors.ts`. Never hardcode status colors in components.

**Exports:**

| Export | Type | Keys |
|--------|------|------|
| `semanticBadgeColors` | `Record<string, string>` | `warning`, `info`, `success`, `destructive` |
| `jobStatusColors` | `Record<string, string>` | `pending`, `running`, `complete`, `failed` |
| `userStatusColors` | `Record<string, string>` | `pending`, `active`, `deactivated` |
| `visibilityColors` | `Record<string, string>` | `public`, `restricted`, `private` |
| `vrtGenerationColors` | `Record<string, string>` | `completed`, `running`, `failed` |
| `qualityScoreClasses(score)` | `(number) => string` | >=80 success, >=60 warning, <60 destructive |
| `activeDotColor` | `Record<string, string>` | `true` (success), `false` (destructive) |
| `recordTypeColors` | `Record<string, string>` | `collection`, `vector_dataset`, `raster_dataset`, `vrt_dataset`, `table`, `unknown` |
| `ingestionStatusColors` | `Record<string, string>` | `draft`, `ready`, `internal` |
| `validationLevelColors` | `Record<string, string>` | `error`, `warning`, `success` |
| `healthDotColors` | `Record<string, string>` | `healthy`, `unhealthy`, `unknown` |
| `vrtRasterStatusColors` | `Record<string, string>` | `ready`, `regenerating`, `failed` |
| `experimentalBadgeColor` | `string` | Amber outline for "Experimental" badges |
| `syntheticBadgeColor` | `string` | Violet palette for "Test Data" badges |

**Pattern:** `semanticBadgeColors` is the base layer -- domain maps (`jobStatusColors`, `visibilityColors`, etc.) reference it. Each entry returns explicit Tailwind palette classes with light and dark variants for maximum contrast on tinted backgrounds (e.g., `'border-teal-300 bg-teal-100 text-teal-950 dark:border-teal-900/60 dark:bg-teal-950/30 dark:text-teal-200'`). Apply to a `<Badge>` via `className`. The palette classes are intentional here -- semantic tokens with opacity modifiers (`bg-info/10`) do not provide sufficient text contrast on tinted backgrounds.

### Focus Ring Standard

Applies to all interactive components unless noted otherwise.

| Context | Classes |
|---------|---------|
| Default (buttons, inputs, cards, dialogs) | `focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background` |
| Table rows | `focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring` |

Table rows use `ring-inset` instead of `ring-offset` to prevent the focus ring from causing layout shift in the table grid.

## 7. Layout Patterns (GUIDE-04)

### PageShell

**Import:** `import { PageShell } from '@/components/layout/PageShell'`

Wraps all standard pages with consistent max-width and padding.

**Props:**

| Prop | Type | Default | Effect |
|------|------|---------|--------|
| `maxWidth` | `'default' \| 'narrow' \| 'wide'` | `'default'` | `'default'` = `max-w-7xl` (80rem), `'narrow'` = `max-w-4xl` (56rem), `'wide'` = `max-w-screen-2xl` |
| `className` | `string?` | -- | Merged via `cn()` |

**Base classes:** `mx-auto w-full px-6 py-6 space-y-6`

**Rules:**
- All standard (non-builder, non-admin) pages must be wrapped in PageShell.
- DO NOT add page-level `max-width` or `padding` inline -- use PageShell.
- Use `narrow` for form-heavy pages (settings, profile).
- Child sections inherit `space-y-6` vertical rhythm.

### PageHeader

**Import:** `import { PageHeader } from '@/components/layout/PageHeader'`

Consistent page header with title, optional description, navigation, and action buttons.

**Props:**

| Prop | Type | Purpose |
|------|------|---------|
| `title` | `string` | Page heading, rendered as `h1 text-2xl font-semibold tracking-tight` |
| `description?` | `string` | Subtitle, rendered as `text-sm text-muted-foreground` |
| `backLink?` | `{ to: string; label: string }` | Back arrow link (ArrowLeft icon + label) |
| `breadcrumbs?` | `{ label: string; to: string }[]` | Breadcrumb trail; current page title appended automatically |
| `actions?` | `ReactNode` | Right-aligned action buttons |

**Navigation:** Use `breadcrumbs` for multi-level navigation (e.g., Search > Dataset Name). Use `backLink` for single-parent return (e.g., "Back to settings"). They are mutually exclusive -- `backLink` takes priority.

**Layout:** Title and actions sit in a `flex items-start justify-between gap-4` row. Actions use `flex items-center gap-2 flex-shrink-0`.

### AppLayout + Navbar

**Import:** `import { AppLayout } from '@/components/layout/AppLayout'`

The top-level app shell used by React Router.

**Structure:**
- `AppLayout`: `flex min-h-screen flex-col` -- Navbar at top, `<main className="flex-1 animate-fade-in">` renders child routes via `<Outlet />`.
- `Navbar`: Fixed-height `h-14` top bar with `border-b bg-background` and `max-w-7xl` centered content.
  - Left: Logo link (`text-lg font-bold`) + `Separator` + nav links (Search, Collections, Maps, Import, Admin).
  - Right: `UserMenu` dropdown (avatar trigger with initial letter, theme/language submenus, settings link, logout).
  - Nav links use `NavLink` with active state: `bg-accent text-accent-foreground`.
  - Maps, Import, and Admin links are role-gated (`isEditor`, `isAdmin`).

### AdminLayout + AdminSidebar

**Import:** `import { AdminLayout } from '@/components/admin/AdminLayout'`

Admin section shell using shadcn/ui's `SidebarProvider`.

**Structure:**
- `AdminLayout`: Wraps content in `SidebarProvider` with `--sidebar-width: 16rem` (mobile: `18rem`).
  - `AdminSidebar` on the left.
  - `SidebarInset` with `<Outlet />` for admin page routes, padded `p-6 space-y-6`.
  - Mobile: Collapsible sidebar with a `SidebarTrigger` header bar (`h-10`, hidden on `md+`).

- `AdminSidebar`: Collapsible (`collapsible="icon"`) with `SidebarRail` for resize.
  - Navigation items: Overview, Users, Jobs, Audit Log, Share Tokens, AI.
  - Settings group: Collapsible section (General, Basemaps, Map Defaults) using `Collapsible` + `CollapsibleContent`.
  - Badge counts: Pending users and failed jobs shown via `SidebarMenuBadge`.
  - Active state: `pathname.startsWith(to)` matching.

### Detail Page (Hero Map + Tabs)

**Pattern source:** `DatasetPage.tsx`

Used for dataset detail views. Structure:

1. **PageShell** wrapper (standard max-width).
2. **PageHeader** with breadcrumbs and action buttons (Edit Details, Draw, Reupload, Delete).
3. **Hero map** -- `DatasetMap` in a rounded bordered container:
   - Default: `h-80 lg:h-96` (320px / 384px).
   - Drawing mode: `h-[60vh]` (expands for editing).
4. **Inline editable** name (`h1`) and description (`p`) via `InlineEdit` component.
5. **Tabs** (Overview, Data, History, API) using `Tabs`/`TabsList`/`TabsTrigger`/`TabsContent`.
   - URL hash synced: `#overview`, `#data`, `#history`, `#api`.
6. **Dialogs** for destructive actions (delete, reupload) rendered at page bottom.

### Full-Screen Builder

**Pattern source:** `MapBuilderPage.tsx`

Full-viewport map editor. No PageShell wrapper.

**Structure:** `flex h-[calc(100vh-3.5rem)]` (viewport minus Navbar height).

1. **Left sidebar** (`w-80 border-r bg-background flex flex-col shrink-0 overflow-hidden`):
   - Header: Map name + action buttons (AI chat toggle, PNG export, save).
   - Scrollable content: `LayerPanel`, `BasemapPicker`, `DatasetSearchPanel`, `SharePanel`.
   - Sections separated by `border-t pt-3`.
2. **Map area** (`flex-1 relative`): `BuilderMap` fills remaining space. `MapLegend` overlaid.
3. **Right sidebar** (conditional, `w-80 border-l`): `ChatPanel` for AI assistance. Pushes map via flex layout (not overlay).
   - Toggled via AI chat button in header.
   - Closes automatically if AI becomes unavailable.

**Key conventions:** Save via `Ctrl/Cmd+S`. Thumbnail auto-captured on save (400x250 JPEG, fire-and-forget). Layer state managed locally, synced to API on explicit save.

## 8. Map Conventions (GUIDE-05)

### MAP_COLORS Constants

**Source:** `frontend/src/lib/map-colors.ts`

MapLibre GL cannot consume CSS custom properties at runtime. These hex constants are the sRGB equivalents of the OKLCH design tokens. Keep them in sync when the token palette changes.

| Category | Property | Hex Value | Purpose |
|----------|----------|-----------|---------|
| **default** | `fill` | `#3b82f6` | Default polygon/point fill (primary-500) |
| | `stroke` | `#1d4ed8` | Default stroke/outline (primary-700) |
| | `fillOpacity` | `0.3` | Default fill transparency |
| | `strokeWidth` | `1.5` | Default stroke width (px) |
| **selection** | `fill` | `#f59e0b` | Highlighted feature fill (amber) |
| | `stroke` | `#d97706` | Highlighted feature stroke |
| | `fillOpacity` | `0.25` | Selection fill transparency |
| **drawing** | `fill` | `#22c55e` | Drawn geometry fill (green) |
| | `stroke` | `#15803d` | Drawn geometry stroke |
| | `fillOpacity` | `0.25` | Drawing fill transparency |
| **closing** | `point` | `#ef4444` | Terra Draw closing point (red) |
| | `pointOutline` | `#ffffff` | Closing point outline |
| **label** | `color` | `#333333` | Text label color |
| | `halo` | `#ffffff` | Text halo for readability |
| **fallback** | -- | `#cccccc` | Fallback when no style match |
| **handle** | `point` | `#ffffff` | Vertex handle fill |
| | `pointOutline` | `#1d4ed8` | Vertex handle outline |
| | `midpoint` | `#93c5fd` | Midpoint handle fill |
| | `midpointOutline` | `#1d4ed8` | Midpoint handle outline |

**Categorical Palette** (8 colors for multi-layer coloring, matches `--viz-*` tokens):

`#3b82f6` blue, `#f59e0b` orange, `#22c55e` green, `#a855f7` purple, `#14b8a6` teal, `#f43f5e` pink, `#eab308` amber, `#6366f1` indigo

### Popup Styling

**CSS source:** `frontend/src/index.css` (`.maplibregl-popup-content` overrides)
**Component source:** `frontend/src/components/map/FeaturePopup.tsx`

**Light mode:** Popup uses `--popover` background, `--popover-foreground` text, `--elevation-lg` shadow, and `--radius` border-radius via CSS overrides on `.maplibregl-popup-content`.

**Dark mode:** Same token overrides in `.dark .maplibregl-popup-content`. Additionally:
- All four popup tip anchors (bottom, top, left, right) are recolored to match `--popover`.
- Close button uses `--popover-foreground` with `oklch(1 0 0 / 10%)` hover background.

**FeaturePopup component:** Renders a `<Popup>` from `@vis.gl/react-maplibre` with:
- Optional `layerName` header (font-semibold, muted text, bottom border).
- Key-value table of feature properties, scrollable at `max-h-48`.
- Excluded keys: `geom`, `geometry`, and any key starting with `_`.
- Values formatted: numbers locale-formatted, booleans localized, null/undefined shown as `--`.

### Drawing Toolbar

**Source:** `frontend/src/components/drawing/DrawingToolbar.tsx`

**Position:** `absolute top-3 left-1/2 -translate-x-1/2 z-10` (centered at top of map).

**Main toolbar** (`rounded-lg shadow-lg border bg-background p-1 flex items-center gap-1`):
- **Select mode** button (MousePointer icon).
- **Separator** (`w-px h-6 bg-border mx-1`).
- **Drawing modes** (filtered by geometry type): Point (MapPin), Line (Spline), Polygon (Pentagon), Rectangle (Square), Circle (Circle), Freehand (PenTool).
- **Separator** + **Undo** button (Ctrl+Z).
- **Separator** + **Close** button (X icon, `ghost` variant, `icon-sm` size).

**Editing action bar** (shown when a feature is selected): Second toolbar row with Save (Check), Cancel (X), Edit Attributes (FileEdit), Delete (Trash2, destructive variant).

**Conventions:** Active mode uses `variant="default"`, inactive uses `variant="outline"`. All buttons `size="sm"` with labels hidden on small screens (`hidden sm:inline`). Available modes filtered by dataset geometry type.

### Basemap Selection

**Picker source:** `frontend/src/components/builder/BasemapPicker.tsx`
**Utils source:** `frontend/src/lib/basemap-utils.ts`

**Thumbnail approach:** Imported PNG assets for built-in basemaps (`positron.png`, `dark.png`, `osm.png`, `bright.png`). Unknown/custom basemaps get a generic gray grid fallback SVG data URI. Thumbnails defined for: `openfreemap-positron`, `openfreemap-dark`, `openstreetmap`, `openfreemap-bright`.

**Picker layout:** `grid grid-cols-4 gap-2` of thumbnail buttons. Active basemap highlighted with `ring-2 ring-primary bg-accent`.

**Basemap utility functions:**

| Function | Purpose |
|----------|---------|
| `toMaplibreStyle(url)` | Converts URL to MapLibre style. `.json` URLs returned as-is; XYZ raster URLs wrapped in inline `StyleSpecification`. |
| `resolveBasemapId(key)` | Maps legacy keys (`positron` -> `carto-positron`, `dark-matter` -> `carto-dark-matter`, `voyager` -> `carto-positron`). |
| `getThemeBasemap(basemaps, resolvedTheme)` | Returns theme-appropriate basemap: `carto-dark-matter` for dark, `carto-positron` for light. Falls back to first enabled. |
| `findBasemapById(basemaps, id)` | Finds basemap by ID, checking legacy key mapping as fallback. |

### Style Color Picker

**Source:** `frontend/src/components/builder/StyleColorPicker.tsx`

16 curated preset colors in an 8x2 swatch grid (`grid grid-cols-8 gap-1`):

`#3b82f6` blue, `#ef4444` red, `#22c55e` green, `#f59e0b` amber, `#8b5cf6` violet, `#ec4899` pink, `#06b6d4` cyan, `#f97316` orange, `#14b8a6` teal, `#6366f1` indigo, `#84cc16` lime, `#a855f7` purple, `#0ea5e9` sky, `#d946ef` fuchsia, `#64748b` slate, `#1e293b` dark

Active swatch: `ring-2 ring-primary ring-offset-1`. Full `HexColorPicker` (react-colorful) below the grid for custom colors.

### MapLibre CSS Rules

1. **DO NOT** apply CSS transitions or transforms to map containers. They interfere with WebGL rendering.
2. **DO NOT** use CSS `var()` references in MapLibre paint properties. They are not evaluated at runtime by the WebGL renderer.
3. Map colors must be JS hex constants from `MAP_COLORS` (`@/lib/map-colors.ts`), not CSS token references.
4. Low-zoom tiles (z0/z1) fail with PostGIS tolerance errors for complex geometries. Use `minzoom: 1` on sources and ensure initial map views start at zoom 2+.

## 9. Dark Mode (GUIDE-06)

### Requirements Checklist

A contributor adding a new component or page should verify ALL of the following:

- [ ] All color classes use semantic tokens (`bg-background`, `text-foreground`, `bg-card`) -- never Tailwind palette colors (`bg-gray-100`, `text-slate-900`)
- [ ] Interactive elements have visible hover feedback in both light and dark mode
- [ ] Interactive elements have visible `focus-visible` keyboard focus rings in both light and dark mode
- [ ] Status colors come from `@/lib/status-colors.ts` -- never hardcoded
- [ ] Borders use `border-border` or `border-input` -- never `border-gray-200`
- [ ] Text hierarchy uses `text-foreground` (primary), `text-muted-foreground` (secondary) -- never hardcoded opacity
- [ ] Cards use `bg-card` background -- never `bg-white`
- [ ] Shadows use `shadow-sm` / `shadow-md` / `shadow-lg` -- the `@theme inline` bridge maps these through elevation tokens automatically
- [ ] MapLibre popups have dark mode CSS overrides in `index.css` (`.dark .maplibregl-popup-content`)
- [ ] No white-on-white or dark-on-dark contrast issues in either theme

### Token Override Strategy

- All dark mode tokens are defined in the `.dark {}` block in `index.css`.
- Dark mode primary scale is **inverted**: 50 is darkest, 900 is lightest (natural usage on dark backgrounds).
- Dark mode shadow opacity is **3-5x higher** than light mode (dark backgrounds absorb shadows).
- Dark mode surfaces use near-black base with subtle blue hue (~250) for warmth.
- Theme switching via `ThemeProvider` + `useTheme()` hook, storage key `geolens-theme`.
- FOUC prevention: An inline script in `index.html` reads the stored theme and applies the `.dark` class before React renders, preventing a flash of the wrong theme.

## 10. Anti-Patterns

1. **DO NOT use hardcoded Tailwind palette colors for status semantics.** Use `@/lib/status-colors.ts` maps (`jobStatusColors`, `visibilityColors`, etc.).
2. **DO NOT use inline color hex values in components** -- except in MapLibre paint properties where CSS vars are not supported (use `MAP_COLORS` from `@/lib/map-colors.ts`) and third-party brand identity SVGs (e.g., OAuth provider logos).
3. **DO NOT create a `tailwind.config.js` file.** Tailwind v4 is CSS-first. All theme config lives in `index.css` via `@theme inline`.
4. **DO NOT use `@theme` without `inline`.** The `inline` directive is required for reactive `var()` references. Without it, Tailwind bakes values at build time, breaking opacity modifiers.
5. **DO NOT use `transition-all`.** Use targeted property-list transitions: `transition-[color,background-color,box-shadow,border-color,opacity] duration-200 ease-out`. `transition-all` causes layout thrash by animating width, height, padding, and margin.
6. **DO use Tailwind `shadow-sm`/`shadow-md`/`shadow-lg`.** The `@theme inline` bridge in `index.css` maps these utilities through elevation tokens automatically (`--shadow-sm: var(--elevation-sm)`), so dark mode higher-opacity shadows work out of the box.
7. **DO NOT add page-level max-width or padding inline.** Use the `PageShell` component.
8. **Builder sidebar panels may use compact `p-3` / `py-3` spacing** for dense control layouts. This is an intentional exception to the `p-4` minimum documented in Spacing Conventions.

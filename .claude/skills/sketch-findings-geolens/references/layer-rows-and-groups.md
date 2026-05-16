# Layer Rows and Groups

Origin: sketch 002 (`sources/002-row-expansion/`), winner **Variant A · Minimal (A-strict)**.

## Design Decisions

### The A-strict rule
**The disclosure caret has exactly one meaning: "this is a group of layers;
expand to see its children."**

- Basemap is a group (collapsible folder containing labels, roads, buildings,
  boundaries, land/water sublayers)
- Future user-created groups (Photoshop folders organizing user data) are
  groups with the same affordances
- **Render-mode is NOT a quick toggle.** It moves to the styling flyout
  (see `layer-editor-flyout.md`). DEMs and other rasters have **no caret**.
  Vectors have **no caret**.

### Row anatomy (every row, including group rows)
```
[caret] [grip] [eye] [type-icon] [name ............] [kebab]
  16px   14px   22px    22px         1fr               22px
```

- `caret`: `▸` on group rows; `visibility: hidden` on non-groups (column
  preserved for vertical alignment)
- `grip`: drag handle (`⋮⋮`), 35% opacity at rest, 70% on row hover
- `eye`: visibility toggle (`●` / `○`); independent of selection
- `type-icon`: 22×22 rounded square with the per-type background tint —
  vector / raster / basemap / label / folder
- `name`: ellipsis-truncated; bolder font-weight (500) for group rows
- `kebab`: 0 opacity at rest, 100% on row hover or when row is selected

> **Note (2026-05-16, quick tasks 260515-rdn + 260515-sqf + 260516-9g9):** The
> per-row opacity slider was removed in three sweeps — first from non-group
> rows (260515-rdn), then from user-folder group rows (260515-sqf), and finally
> from basemap group rows (260516-9g9 — also shipped master-opacity persistence
> via `basemap_config.opacity`). Opacity is now edited exclusively in the
> LayerEditorPanel Visibility section (see `layer-editor-flyout.md`) for both
> loose layers and user-folder groups, and in the BasemapGroupEditorScene
> "Master opacity" slider for basemap groups. The dedicated 60px slider column
> was collapsed across all three row variants; the row template is six columns:
> `16px 14px 22px 22px 1fr 22px`. **Only basemap-editor SUBLAYER rows** (the
> per-sublayer rows inside the BasemapGroupEditorScene flyout) retain their
> own per-row opacity sliders — every stack-list row (loose, folder group,
> basemap group) is slider-free.

### Type icons + colors

| Type | Icon | Background | Foreground |
|------|------|------------|------------|
| Vector | `●` `―` `▭` `⋯` (geometry-shaped) | `var(--type-vector-bg)` | `var(--type-vector)` |
| Raster | `▦` or `⛰` (raster/terrain feel) | `var(--type-raster-bg)` | `var(--type-raster)` |
| Basemap (group) | `⊞` | `var(--primary-50)` | `var(--primary-700)` |
| User group | `▸` (folder triangle) | `oklch(0.93 0.03 80)` | `oklch(0.45 0.10 80)` |
| Label | `A` | `var(--color-surface-3)` | `var(--color-text-muted)` |

The basemap and user-group icons are intentionally different (`⊞` vs `▸`)
so that basemap reads as "the foundation group" without anchoring it to a
specific position in the stack.

### Selection state
A selected row gets:
- `background: var(--color-accent-soft)` (light blue tint)
- `box-shadow: inset 2px 0 0 var(--color-primary)` (left rail)
- Kebab + drag affordances become visible
- Clicking a row both **selects** it AND opens the `LayerEditorPanel` flyout
  (see `layer-editor-flyout.md`). One gesture, two effects.

### Group expansion
- Caret rotates 90° on expand
- Children appear in an indented container with `1px dashed var(--color-border)`
  left border, `margin-left: 28px`
- Children are normal layer rows with their own eye / opacity / kebab
- Child rows have a `grip` (drag-to-reorder within the group) but no caret
- The `Add layer to group` affordance is reachable through the group's
  kebab menu (NOT a dedicated dashed `+ Add` row — variant C tested that and
  it added visual weight without earning it in the minimal variant)

### Group operations live in the kebab
- User group kebab: `Rename · Add layer · Ungroup · Delete`
- Basemap kebab: `Swap basemap · Reset appearance`
- This was the deciding factor over variant B (inline hover actions): the
  hover actions overlapped the opacity slider and added density to every
  row, every hover. The kebab is one-click-deeper but discoverable, and
  it keeps the rest state clean.

## CSS Patterns

### Row grid
```css
.row {
  display: grid;
  grid-template-columns: 16px 14px 22px 22px 1fr 22px;
  align-items: center; gap: 6px;
  padding: 8px 8px 8px 4px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: background 0.12s ease;
}
.row:hover { background: var(--color-surface-2); }
.row.selected {
  background: var(--color-accent-soft);
  box-shadow: inset 2px 0 0 var(--color-primary);
}
.row.group .name { font-weight: 500; }
```

### Caret with reserved column when invisible
```css
.caret {
  color: var(--color-text-muted); opacity: 0.6;
  transition: transform 0.15s; cursor: pointer;
  line-height: 1; text-align: center; user-select: none;
  font-size: 12px;
}
.caret.invisible { visibility: hidden; pointer-events: none; }
.row.expanded .caret { transform: rotate(90deg); }
```

### Type icon swatches
```css
.type-icon {
  width: 22px; height: 22px;
  display: flex; align-items: center; justify-content: center;
  border-radius: var(--radius-sm);
  font-size: 11px; font-weight: 600;
}
.type-vector  { background: var(--type-vector-bg);  color: var(--type-vector); }
.type-raster  { background: var(--type-raster-bg);  color: var(--type-raster); }
.type-basemap { background: var(--primary-50);      color: var(--primary-700); }
.type-folder  { background: oklch(0.93 0.03 80);    color: oklch(0.45 0.10 80); }
.type-label   { background: var(--color-surface-3); color: var(--color-text-muted); }
```

### Group children container
```css
.group-children { display: none; }
.group-children.open { display: block; }
.group-children.open {
  margin: 2px 0 6px 28px;
  padding-left: 12px;
  border-left: 1px dashed var(--color-border);
}
.group-children .row {
  grid-template-columns: 16px 14px 22px 22px 1fr 22px;
  padding: 6px 8px 6px 4px;
}
```

## HTML Structure

### A loose (non-group) layer row
```html
<div class="row" onclick="selectRow(this)">
  <span class="caret invisible"></span>
  <span class="grip">⋮⋮</span>
  <span class="eye" onclick="toggleEye(event, this)">●</span>
  <span class="type-icon type-vector">●</span>
  <span class="name">Console Regression Points</span>
  <span class="kebab">⋯</span>
</div>
```

### A group row (basemap or user folder)
```html
<div class="row group" onclick="toggleGroup(this)">
  <span class="caret">▸</span>
  <span class="grip">⋮⋮</span>
  <span class="eye">●</span>
  <span class="type-icon type-folder">▸</span>
  <span class="name">Demographics</span>
  <!-- Note: no per-row opacity slider on group rows as of 260516-9g9. Per-sublayer opacity lives in the BasemapGroupEditorScene flyout only. -->
  <span class="kebab">⋯</span>
</div>
<div class="group-children open"> <!-- toggle .open with the caret -->
  <!-- child .row elements: same anatomy, .caret.invisible -->
</div>
```

## What to Avoid

- **A caret on a vector or raster row.** Tested as the *original* sketch 002
  variant A and rejected — it implied render-mode was a per-row toggle, then
  created visual collision with group children. Render-mode goes to the
  flyout, period.
- **Inline hover-revealed group action buttons** (variant B). They overlap
  the opacity slider unless the opacity slider is shortened. Net density
  went up, not down. The kebab does this work fine.
- **A bordered/tinted container around expanded groups** (variant C).
  Tested and rejected — it broke the visual rhythm with neighboring loose
  layers and made the stack feel like nested boxes. The dashed left border
  on the children is sufficient.
- **The "RELIEF 1 OF 1" / "DATA 1 OF 1" position tags** that exist in the
  current builder. Drag-orderable position is implicit; tag is noise.

## Origin
Synthesized from sketch: 002-row-expansion
Source files: `sources/002-row-expansion/index.html`
The A-strict decision was reached during conversation (not in the original
variant grid); the saved variant A is the rebuilt strict version that won.

---

# Extension: Drag-into-Group Drop Affordance

Origin: sketch 007 (`sources/007-drag-into-group/`), winner **Variant A · Tint + line**.

A-strict made groups the only expandable thing in the stack. That implies
a meaningful drag-and-drop operation: **dragging a loose layer onto a
group adds it to that group.** This extension documents how that drop is
signaled visually, and how plain reorder (between two loose rows) is
disambiguated from add-to-group.

## Two distinct drag operations

The same drag gesture can land in one of two ways:

1. **Reorder** — dropping between two loose layer rows changes the z-order
   in the stack (not into a group). Visual: a thin primary-colored
   insertion line between rows.
2. **Add to group** — dropping on/over a group row (or its expanded
   children container) puts the layer inside that group. Visual:
   primary-50 tint on the group row + left primary rail (matches the
   selection visual); soft blue wash on the expanded children container.

The user disambiguates by cursor position; the UI confirms with two
visually distinct affordances.

## Drop affordance — visual specification

### When the drag-over target is a group row (collapsed or expanded)
- Group's `.row.group` element gets:
  - `background: var(--primary-50)`
  - `box-shadow: inset 2px 0 0 var(--color-primary)` (same as `.row.selected`)
- If the group is expanded, its `.group-children.open` container also gets:
  - `background: oklch(0.97 0.02 250 / 60%)` (soft blue wash; ~primary-50 at 60% alpha)
  - `border-radius: var(--radius-md)` to round its edges

### When the drag-over target is between two loose rows (not in a group)
- A 2px primary-colored insertion line, inserted between the two rows:
  ```css
  .insert-line {
    height: 2px; margin: -1px 0;
    background: var(--color-primary);
    border-radius: var(--radius-full);
    box-shadow: 0 0 0 2px oklch(0.55 0.18 250 / 25%); /* soft 25% bloom */
    pointer-events: none;
    transition: opacity 0.12s;
  }
  ```
- Position is computed from `e.clientY` vs the hovered row's bounding rect:
  - Above midpoint → insert *before* the row
  - Below midpoint → insert *after* the row

### When the dragged row itself is in flight
- `.row.dragging` gets:
  - `opacity: 0.4`
  - `background: var(--color-surface-2)` (slight tint to differentiate from rest)
  - `transform: scale(0.98)` (subtle shrink, hints "this is being moved")

### Global drag-active state
- The `.variant` container (or whatever the page root is) gets
  `.dragging-active` while a drag is in progress
- All `.kebab` controls hide (`opacity: 0 !important`) — kebabs are
  irrelevant during drag and add noise

## JavaScript drag-and-drop wiring

The sketch uses native HTML5 drag-and-drop. Real implementation can use
this or a library (`@dnd-kit/core` is idiomatic for React 19); the visual
contract is the same.

```js
// On dragstart: mark the row + the page as drag-active
row.addEventListener('dragstart', e => {
  row.classList.add('dragging');
  pageRoot.classList.add('dragging-active');
  e.dataTransfer.effectAllowed = 'move';
  e.dataTransfer.setData('text/plain', row.dataset.id);
});

// On dragend: clean up
row.addEventListener('dragend', () => {
  row.classList.remove('dragging');
  pageRoot.classList.remove('dragging-active');
});

// On dragover the stack: differentiate group vs. between-rows
stack.addEventListener('dragover', e => {
  e.preventDefault();
  clearStates();  // remove .drag-over from everything
  const groupWrap = e.target.closest('.group-wrap');
  const looseRow  = e.target.closest('.row:not(.group)');

  if (groupWrap) {
    const groupRowEl = groupWrap.querySelector('.row.group');
    const children   = groupWrap.querySelector('.group-children.open');
    groupRowEl?.classList.add('drag-over');
    children?.classList.add('drag-over');
  } else if (looseRow) {
    const rect = looseRow.getBoundingClientRect();
    const before = (e.clientY - rect.top) < rect.height / 2;
    insertLine.classList.remove('hidden');
    looseRow.parentElement.insertBefore(insertLine,
      before ? looseRow : looseRow.nextSibling);
  }
});
```

## What this extension does NOT cover

- **Auto-expand-on-hover for collapsed groups.** Variant C of sketch 007
  added a 500ms dwell expand; the winner (A) intentionally omits it. If
  the engine team needs to add a way to drop into a collapsed group's
  internal position, the right answer is "auto-expand after dwell ON
  collapsed groups only," not "always show a drop pad."
- **Keyboard alternative.** Drag-and-drop is mouse-only here. Phase
  planning should add a "Add to group…" / "Move to group…" entry in the
  layer-row kebab so non-mouse users have a path.
- **Auto-scroll near sidebar edges.** Standard pattern; not sketched.
- **Cross-stack constraints** (e.g., dropping a basemap sublayer onto a
  user group should be rejected). Implementation must enforce; the visual
  contract is "no drop-over highlight appears, cursor shows `not-allowed`."

## Origin (extension)
Synthesized from sketch: 007-drag-into-group
Source files: `sources/007-drag-into-group/index.html`

Variants B (bordered container) and C (explicit footer drop pad) were
rejected: B added too much visual weight to drag-over targets and broke
the row rhythm; C added on-stack chrome that only existed during dragging
but was distracting and over-explained. A uses the existing selection
visual vocabulary (primary tint + left rail), which means the engine team
only needs to add ONE new visual (the insertion line) — everything else
re-uses tokens already in the design system.

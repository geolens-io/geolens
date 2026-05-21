# Quick Task 260326-8ea: Fix map console errors (outline-width) - Research

**Researched:** 2026-03-26
**Domain:** MapLibre paint properties, PostgreSQL JSONB migration
**Confidence:** HIGH

## Summary

The bug: some `map_layers` rows store `outline-width` and `outline-color` (no underscore prefix) in the `paint` JSONB column. The convention is `_outline-width` / `_outline-color` (underscore-prefixed) which signals these are custom props, not MapLibre paint properties. When the unprefixed versions reach `stripCustomProps()`, they pass through and hit `map.addLayer()`, causing MapLibre to reject them as unknown paint properties. The `addLayer` failure then cascades to `finalizeLayer` which tries `setPaintProperty` on a layer that was never created.

**Primary recommendation:** Add non-prefixed forms to `CUSTOM_PAINT_PROPS`, write an Alembic migration to normalize the DB, wrap `addLayer` in try-catch, and fix ViewerMap.tsx which has the same raw-paint-passthrough bug.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Add `outline-width` and `outline-color` (non-prefixed) to `CUSTOM_PAINT_PROPS` set
- Do NOT add a general safety net that strips unknown props -- keep it explicit
- Both frontend + backend migration for long-term robustness
- Frontend: tolerate both `outline-width` and `_outline-width` forms
- Backend: Alembic migration to normalize in DB
- Wrap `addLayer` in try-catch; skip `finalizeLayer` on failure, log warning

### Claude's Discretion
- None specified

### Deferred Ideas
- None specified
</user_constraints>

## Affected Files and Locations

### 1. `frontend/src/components/builder/map-sync.ts`

**CUSTOM_PAINT_PROPS** (line 9-13):
```typescript
export const CUSTOM_PAINT_PROPS = new Set([
  '_outline-width', '_outline-color',
  '_fill-disabled', '_stroke-disabled',
  '_fill-opacity-saved', '_outline-width-saved',
]);
```
Needs: add `'outline-width', 'outline-color'` (non-prefixed forms).

**stripCustomProps** (line 101-102): Uses `CUSTOM_PAINT_PROPS.has(k)` -- will auto-benefit from the Set change.

**Outline layer creation** (lines 276-279): Reads `_outline-color` and `_outline-width`. Should also fallback to non-prefixed forms for layers not yet migrated.

**addLayer calls** (lines 209, 228, 263, 280): None are wrapped in try-catch. All call `finalizeLayer` after, which will fail if addLayer threw. Wrapping needed at minimum for lines 209, 228, 263 (the three main geometry type branches).

**finalizeLayer** (line 116-129): Called after addLayer. If addLayer fails, this will error on `setPaintProperty` for a non-existent layer.

### 2. `frontend/src/components/viewer/ViewerMap.tsx`

**CRITICAL FINDING:** ViewerMap does NOT use `stripCustomProps`. It passes raw `layer.paint` directly to `map.addLayer()` for ALL geometry types (circle: ~line 297, line: ~line 320, fill: ~line 343). This means ViewerMap has the same bug -- any custom props in paint JSON will be passed to MapLibre.

ViewerMap reads `_outline-color` / `_outline-width` correctly at lines 361-363 for the outline layer.

### 3. `frontend/src/components/map/MapLegend.tsx` and `layer-icons.tsx`

Read `_outline-color` for display purposes only. No MapLibre API calls. Low risk but should also tolerate unprefixed form for completeness.

### 4. `frontend/src/hooks/use-builder-layers.ts`

Lines 378-382, 425-429: Reads `_outline-color` / `_outline-width` for live sync. Should also check unprefixed fallback.

## Alembic Migration

### Schema Details
- Table: `catalog.map_layers`
- Column: `paint` (JSONB, default `{}`, server_default `'{}'`)
- Current revision: `0007_add_user_last_login_at`

### Migration SQL Pattern

PostgreSQL JSONB key rename via `jsonb_set` + key removal:

```sql
-- Rename outline-width -> _outline-width where non-prefixed exists
UPDATE catalog.map_layers
SET paint = (paint - 'outline-width') || jsonb_build_object('_outline-width', paint->'outline-width')
WHERE paint ? 'outline-width';

-- Rename outline-color -> _outline-color where non-prefixed exists
UPDATE catalog.map_layers
SET paint = (paint - 'outline-color') || jsonb_build_object('_outline-color', paint->'outline-color')
WHERE paint ? 'outline-color';
```

The `?` operator checks if a top-level key exists in JSONB. The `-` operator removes a key. The `||` operator merges objects. This is the standard PostgreSQL JSONB key-rename pattern.

### Alembic Migration Template

Following the project's migration conventions (see 0006, 0007):

```python
"""normalize outline paint props in map_layers

Revision ID: 0008_normalize_outline_paint
Revises: 0007_add_user_last_login_at
Create Date: 2026-03-26
"""

from alembic import op

revision = "0008_normalize_outline_paint"
down_revision = "0007_add_user_last_login_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE catalog.map_layers
        SET paint = (paint - 'outline-width') || jsonb_build_object('_outline-width', paint->'outline-width')
        WHERE paint ? 'outline-width'
    """)
    op.execute("""
        UPDATE catalog.map_layers
        SET paint = (paint - 'outline-color') || jsonb_build_object('_outline-color', paint->'outline-color')
        WHERE paint ? 'outline-color'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE catalog.map_layers
        SET paint = (paint - '_outline-width') || jsonb_build_object('outline-width', paint->'_outline-width')
        WHERE paint ? '_outline-width'
    """)
    op.execute("""
        UPDATE catalog.map_layers
        SET paint = (paint - '_outline-color') || jsonb_build_object('outline-color', paint->'_outline-color')
        WHERE paint ? '_outline-color'
    """)
```

**Note on downgrade:** The downgrade reverses ALL `_outline-*` keys, not just the ones that were migrated. This is acceptable since the convention has always been to use the prefixed form -- any `_outline-*` key in the DB was either already correct or was migrated by upgrade.

## Error Handling Pattern

The addLayer try-catch should follow the existing pattern in `replayExpressions` (line 109-110):

```typescript
try {
  map.addLayer({ ... });
  finalizeLayer(map, layerId, rawPaint, type, layer, hasExpressions);
} catch (e) {
  console.warn(`[map-sync] addLayer failed for ${layerId}:`, e);
}
```

This prevents cascading errors where `finalizeLayer` -> `setPaintProperty` fails on a non-existent layer.

## ViewerMap Fix Strategy

ViewerMap needs `stripCustomProps` imported and applied to paint for all three addLayer calls. Currently it passes `layer.paint` directly. The fix mirrors what map-sync.ts already does:

```typescript
import { stripCustomProps } from '@/components/builder/map-sync';
// ... then for each addLayer:
paint: stripCustomProps((layer.paint as Record<string, unknown>) ?? { ...defaults }),
```

## Common Pitfalls

### Pitfall 1: Migration collision with prefixed keys
If a row has BOTH `outline-width` AND `_outline-width`, the migration would overwrite the prefixed version. The SQL should guard against this:
```sql
WHERE paint ? 'outline-width' AND NOT (paint ? '_outline-width')
```
For rows with both, just remove the unprefixed one:
```sql
UPDATE catalog.map_layers
SET paint = paint - 'outline-width'
WHERE paint ? 'outline-width' AND paint ? '_outline-width';
```

### Pitfall 2: Forgetting ViewerMap
ViewerMap.tsx is the public/embed viewer -- it does NOT use stripCustomProps at all. Any fix to map-sync.ts must also be applied there, or shared map views will still error.

## Sources

### Primary (HIGH confidence)
- Direct code inspection of `map-sync.ts`, `ViewerMap.tsx`, `models.py`, existing migrations
- PostgreSQL JSONB operators (`?`, `-`, `||`) are stable, well-documented features

## Metadata

**Confidence breakdown:**
- CUSTOM_PAINT_PROPS fix: HIGH - direct code reading, clear cause
- Alembic migration: HIGH - standard JSONB operations, follows existing conventions
- ViewerMap bug: HIGH - confirmed by code inspection (no stripCustomProps usage)
- Error handling: HIGH - follows existing pattern in same file

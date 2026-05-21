# Quick Task 260318-jqi: Product concerns - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Task Boundary

Address three product concerns from the spatial filter UX review:

1. **Save Search placement** — Save Search button currently has equal prominence to core filter/sort actions. In active search mode (query entered, filters applied, spatial filter active), it should be visually de-emphasized relative to primary filtering actions. Move it to a secondary position or make it a ghost/outline button rather than a primary action.

2. **Hero compression tuning** — The `isLanding` logic exists but the hero still feels too large in active search mode. The transition from landing page to working surface needs to be more dramatic: compact sticky search bar with filters inline, not just a slightly smaller hero. The current hero takes up space that should go to results, filters, and map context.

3. **Result count feedback after spatial apply** — After applying a spatial filter, there's no explicit indicator showing how the results were affected. Add a visible result count that updates when spatial filters change, e.g., "Showing 42 datasets in selected area" or just a clear count near the results.

</domain>

<decisions>
## Implementation Decisions

- Save Search: demote to ghost/outline variant, move after sort/view controls (not before)
- Hero: two distinct states — landing (large centered hero) and active (compact sticky bar with search + filters inline). The active state should feel like a toolbar, not a hero.
- Result count: show total count with context when spatial filter is active. Place near top of results list.

</decisions>

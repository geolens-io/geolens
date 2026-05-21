# Quick Task 260318-qla: Detail Page UX Overhaul - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Task Boundary

Overhaul detail pages (vector, raster, VRT) based on third-party UX review. Focus on the top 5 highest-priority improvements to transform pages from "capable admin screens" into a polished geospatial product experience.

</domain>

<decisions>
## Implementation Decisions

### Scope
- Execute only the top 5 priorities:
  1. Strengthen top-of-page summary hierarchy (type badge + key stats inline with title)
  2. Reorganize action bars into primary vs secondary (kebab overflow menu)
  3. Make metadata sections read-first instead of form-first (collapse empty fields)
  4. Redesign Dataset Health into a guided QA/status block
  5. Make VRT pages more clearly derived/operational
- Do NOT tackle: Access section polish, tab standardization, empty states, related dataset cards, AI Assist placement

### Tab Model
- Keep current tab structure unchanged:
  - Vector: Overview / Metadata / Data / Structure
  - Raster: Overview / Metadata
  - VRT: Overview / Metadata / Sources
- Access points remain within the Overview tab
- No new tabs added

### Action Bar
- Primary actions visible as buttons: Add to Map, Download/Export, Connect, Edit Features (vector), Regenerate (VRT)
- Secondary/admin/destructive actions behind a "..." kebab/overflow menu: Re-upload, Unpublish/Publish, Create VRT, Delete
- Delete should NOT sit prominently in the top row

### Metadata Read-First Pattern
- Empty fields show "Not set" with an edit/add button
- Populated fields show values with inline edit affordance
- Forms only expand on interaction (click to edit)
- Contact form hidden behind "Add contact" button
- Empty textareas collapsed to placeholder buttons

### Claude's Discretion
- Exact visual design of the kebab menu component
- Dataset Health progress calculation and display
- VRT derivation summary layout details
- Specific component naming and file organization

</decisions>

<specifics>
## Specific Ideas

### Header Identity Band (all types)
- Breadcrumb
- Title (editable)
- Type badge + 2-4 key stats inline
- Examples from reviewer:
  - Raster: `Raster` · 4 bands · 0.3 m · EPSG:6527
  - Vector: `Vector` · MultiPolygon · 252 features · EPSG:4326
  - VRT: `Virtual Raster` · Mosaic · 2 sources · 4 bands · EPSG:6527
- Status line: Published · Updated 3 days ago

### Dataset Health Redesign
- Compact guided QA block instead of awkward strip
- Show: "5 required · 4 recommended · 62% complete"
- Single "Review issues" button instead of 4 parallel buttons
- Move into Overview tab content (below summary band) instead of between map and tabs

### VRT Derived Product Framing
- Overview should clearly communicate: derived, from what, how assembled, health, regeneration status
- Show: source count, resolution strategy, generation status, last regenerated date prominently

### Bugs to Fix
- `undefined` band color → "Not specified"
- Dash `-` empty states → "Not available" or similar intentional label

</specifics>

<canonical_refs>
## Canonical References

- Third-party UX review provided inline with task description (comprehensive detail page critique)
- Screenshots in `screenshots-review/` directory for visual reference

</canonical_refs>

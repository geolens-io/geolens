---
name: Quick Task 260408-lnq Context
description: Locked decisions for the demo environment data & maps brainstorm
type: quick-task-context
---

# Quick Task 260408-lnq: Demo Environment Data & Maps Brainstorm - Context

**Gathered:** 2026-04-08
**Status:** Ready for planning

<domain>
## Task Boundary

Come up with an interesting series of data for the demo environment and what
maps to create with them. Consider geopolitics as a prospective theme, identify
other candidate themes, propose sources, and recommend an automation posture
for ingest and map creation.

**Background:** The current demo environment (`scripts/seed-demo.sh`) seeds ~20
Natural Earth datasets — foundational reference layers only. It shows that the
platform works but tells no story, does not showcase breadth of data types
(raster, VRT, 3D, table records), and does not produce any sample maps.

</domain>

<decisions>
## Implementation Decisions

### Output Scope
- **Strategy doc only.** This quick task produces a single `PROPOSAL.md`
  covering themes, datasets, candidate maps, sources, and automation
  recommendations. **No code changes.** Any implementation (new seed scripts,
  docker-compose wiring, auto-map creation) lands as a follow-up planned phase.

### Demo Narrative
- **2-3 themed collections.** Use GeoLens Collections to present multiple
  "playlists" side by side rather than one monolithic story or a random
  sampler. This showcases breadth of content and exercises the Collections
  feature itself. Target: one geopolitics collection + 1-2 complementary
  themes so a visitor can pick a story that resonates.

### Political Sensitivity
- **Embrace carefully.** Geopolitics is in scope. Use authoritative, neutral
  sources only (ACLED, UCDP, UN, Natural Earth disputed-areas, OCHA, World
  Bank). No editorial framing — labels and descriptions must cite source and
  snapshot date. Disputed borders rendered per source's official stance, not
  GeoLens opinion. The demo must be safe to show to any prospective customer
  regardless of region.

### Data Sources
- **Static snapshots.** Prefer download-once public datasets that reproduce
  deterministically: Natural Earth, GADM, OSM thematic extracts, Our World
  in Data, USGS, NASA Earthdata COGs, OCHA HDX, World Bank, SEDAC.
- No API keys required in the baseline demo seed.
- No outbound internet assumed at demo run-time — snapshots bundled or
  fetched once during seeder container build.
- Snapshot date becomes part of dataset metadata (shown in UI).

### Claude's Discretion
- Specific dataset selection within each theme (curate for visual impact and
  diversity of data types — vector, raster, VRT, table).
- Sample map compositions (layers, styling, widgets, filters).
- Recommended automation posture: whether to automate ingest via new seeder
  scripts, whether to auto-create sample maps, and the tradeoffs of each.
- Structure of the PROPOSAL.md document (sections, depth).

</decisions>

<specifics>
## Specific Ideas

- **Current baseline:** `scripts/seed-demo.sh` uses `seed-natural-earth.py`
  to pull 20 Natural Earth `ne_10m_*` layers. There is also
  `seed-ago-data.py` (ArcGIS Online portal ingestion) available as an
  alternative pathway but not currently used by the demo.
- **Platform capabilities to showcase:** vector tiles (ST_AsMVT), raster
  COGs via Titiler, VRT mosaics, table records (v12.0 record-first
  architecture), semantic search (pgvector), AI-assisted map building,
  faceted search, Collections, share links/embeds.
- The proposal should explicitly consider whether to auto-create sample
  maps (via the maps API) as part of the seeder, or leave map creation to
  the human operator clicking through after seeding.

</specifics>

<canonical_refs>
## Canonical References

- `scripts/seed-demo.sh` — current seeder entry point
- `scripts/seed-natural-earth.py` — Natural Earth downloader/ingester
- `scripts/seed-ago-data.py` — ArcGIS Online ingester (alt path)
- `.planning/PROJECT.md` — core value proposition and capabilities list
- Memory: `v12.0 Record-First Discovery Architecture` and
  `v12.3 Map Builder Excellence` describe the record/map model the
  proposal must align with.

</canonical_refs>

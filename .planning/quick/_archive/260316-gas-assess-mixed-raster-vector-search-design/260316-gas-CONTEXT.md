# Quick Task 260316-gas: Assess mixed raster/vector search design against current GeoLens codebase - Context

**Gathered:** 2026-03-16
**Status:** Ready for planning

<domain>
## Task Boundary

Evaluate a comprehensive design document proposing a record-first discovery architecture for GeoLens, aligned to OGC API Records, STAC, and OGC API Features. Produce a gap analysis comparing the current codebase against the design recommendations, then derive a phased implementation roadmap.

The design document proposes:
- Record-first discovery (datasets + collections as primary search units)
- Three discovery layers: Record search, Component drill-down, Feature/source explorer
- Standards alignment: OGC API Records for unified discovery, STAC for raster/VRT, OGC API Features for vector
- UX patterns for mixed-modality results (badges, cards, filters/facets)
- VRT lifecycle semantics (versioning, atomic regeneration)
- Security, observability, and operational guardrails

</domain>

<decisions>
## Implementation Decisions

### Assessment Scope
- Produce BOTH a gap analysis document AND a phased implementation roadmap
- Gap analysis first, roadmap derived from identified gaps

### Priority Layer
- Analyze all three discovery layers at equal depth: Record search, STAC export, OGC Features alignment

### Standards Alignment Depth
- Pragmatic alignment: Focus on high-impact alignment points (endpoint shapes, query params, response schemas) without exhaustive spec coverage

### UI/UX Assessment
- Assess both search results unification AND detail page consistency
- Search: How current UI handles mixed raster/vector results, card anatomy, badges, filtering
- Detail: Whether raster/VRT/vector detail pages follow consistent patterns with appropriate drill-down

</decisions>

<specifics>
## Specific Ideas

- The design doc references specific standards: STAC 1.1 common bands, OGC API Records `q`/`bbox`/`datetime` params, CQL2 filtering
- Concrete examples provided: STAC Item JSON for raster/VRT, OGC Records record for vector, mermaid diagrams
- Prioritized recommendations with acceptance criteria and tests already defined in the design doc

</specifics>

<canonical_refs>
## Canonical References

- Design document: User-provided ~76K char assessment document (in conversation context)
- OGC API Records specification
- STAC 1.1 specification
- OGC API Features Parts 1 and 3
- STAC extensions: Projection, File, Processing, Alternate Assets

</canonical_refs>

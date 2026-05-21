---
quick_id: 260408-mgg
type: spike
date: 2026-04-08
verdict: unsupported
related: 260408-lnq
---

# Quick Task 260408-mgg — Summary

**One-liner:** A7 resolved — table→polygon join is not supported in the map builder today, but pre-joining CSVs into GeoJSON during seeder build is a zero-code-change workaround that preserves the full Theme 2 demo scope.

## Outcome

- **Verdict:** UNSUPPORTED
- **Impact on 260408-lnq-PROPOSAL.md:** 2 maps need rework at the seeder data layer (not the platform layer). 0 maps drop. Theme 2 signature story unchanged.
- **Recommended fallback:** Option C — pre-materialized join at seeder build time via a small `csv_to_choropleth.py` helper script.

## Key Code Evidence

- `backend/app/tiles/service.py:75-76` — MVT query unconditionally references `geom_4326` column that does not exist on CSV tables (hard failure point)
- `backend/app/maps/models.py:82-119` — `MapLayer` has single `dataset_id`, no join primitives
- `backend/app/ingest/service.py:232-321` — `register_existing_table` accepts views, making a materialized-view workaround possible (but messier than pre-materialization)
- `backend/app/maps/service.py:592-641` — `add_layer` silently accepts table records and produces a fill layer with no guard

## Secondary Bug Logged

Adding a `record_type=table` dataset to a map produces a blank layer with no error surface. Candidate for a future quick task — not blocking.

## Files

- `260408-mgg-FINDINGS.md` — full investigation with code trace, file:line citations, and phase-impact table

---
quick_id: 260515-cej
slug: docker-rebuild-builder-smoke
date: 2026-05-15
status: complete
---

# Summary — Docker Rebuild + Map Builder Smoke Check

## Outcome
- ✅ Full no-cache rebuild of all 5 Docker images
- ✅ Stack came up healthy in ~30 s
- ✅ Comprehensive Playwright smoke check completed across builder entry → catalog → add → edit → multi-select → settings → basemap flows
- 📝 `FINDINGS.md` written with 2 BLOCKERS, 4 MAJORS, 6 MINORS, 6 POLISH items
- 📸 18 reproduction screenshots captured (smoke-01..18.png)

## Headline issues
1. 🟥 **B-01** First-time layer-add doesn't push layers to MapLibre style — map looks blank after add; only reload fixes it. Critical first-run regression.
2. 🟥 **B-02** BulkActionBar Delete / Group / Ungroup buttons overflow the 340 px sidebar and are clipped — v1009 bulk-delete is unreachable.
3. 🟧 **M-01** Coordinate readout never updates lat/lng (zoom does) — misleading.
4. 🟧 **M-04** "Pending style preview" banner appears with no user edits.
5. 🟧 **M-03** Shift-click does not extend selection (replaces); ⌘-click is the only multi-select path.

## Health
- Console errors from app code: **0** (only 3 search-page quicklook 404s for stale sample datasets)
- Backend 5xx errors: **0**
- HMAC-signed tile URLs working
- All control paths verified against existing "Phase 1002 Builder Audit Baseline" map

## Deliverables
- [`PLAN.md`](PLAN.md) — scope + quality gates
- [`FINDINGS.md`](FINDINGS.md) — full report with severity, repro, files-to-investigate, recommended next steps
- `smoke-*.png` — 18 viewport screenshots referenced in FINDINGS table

## Notes
- Volumes preserved (`down` without `-v`) so seeded data survived rebuild
- No commits made — this is observational work
- Test map `Smoke Check 2026-05-15` (UUID `a00b7e96-95b7-48d6-a911-57b97b767ebc`) left in place; safe to delete or repurpose

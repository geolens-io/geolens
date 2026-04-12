---
phase: 224
name: post-impl-audit-remediation
created: 2026-04-11
status: context-gathered
source_audits:
  - docs-internal/audits/post-impl-20260411.md (full-repo, 64 findings, grade C)
  - docs-internal/audits/post-impl-20260411-b.md (backend delta, 53 net-new, grade C)
---

# Phase 224 — Post-Impl Audit Remediation Context

## Goal

Resolve all 24 must-fix items (3 P0 + 21 P1) surfaced by the 2026-04-11 post-impl audit pair. Scope is strictly P0 + P1; P2/P3 items (62 additional backend findings) remain tracked in the audit reports for future cleanup phases.

## Files to read before planning

This phase is fully driven by pre-existing audit artifacts. Read these in full before decomposing into plans:

1. **`docs-internal/audits/post-impl-20260411.md`** — parent audit (full repo). 315 lines. Contains the canonical P0/P1 list and per-dimension findings with file:line evidence.
2. **`docs-internal/audits/post-impl-20260411-b.md`** — backend delta (differential pass). 301 lines. Contains 53 net-new backend findings, including corrections/extensions to parent P0/P1 items (notably the 3-site Cartesian joinedload).

Also reference:
- `.planning/REQUIREMENTS.md` for the existing traceability table — new requirements IDs will be added for each fix
- `.planning/PROJECT.md` for project architecture context
- `CHANGELOG.md` for the wire-format contracts that must NOT change

## The 24 must-fix items (combined P0 + P1)

### P0 — 3 items (user-facing crash/degradation on every request)

| # | Area | File:line | Fix |
|---|---|---|---|
| P0-1 | Perf | `backend/app/search/service.py:676, 885` + `stac/router.py:217-231` | **Switch `joinedload` → `selectinload` at all 3 sites.** The parent audit cited only `search/service.py:676`; the delta audit (KISS-1 #4, CLEANUP-1 #1) corrected this to 3 sites. Fix must touch all 3 in one patch — extract `_eager_load_record_relations(stmt)` helper and call from each site. Count subquery on `search/service.py:847` becomes lean automatically. |
| P0-2 | Perf | `frontend/src/hooks/use-quicklook.ts:30` + `components/search/SearchResultCard.tsx:151` | **Replace base64 fetch with `<img loading="lazy">`.** Per `SearchResultCard` rendered N times per search page, the current pattern fires 20+ parallel authenticated base64 fetches. Backend `get_quicklook` already returns `Cache-Control: public, max-age=3600`. Add `?api_key=` query param support on the quicklook endpoint if needed (already supported per `backend/app/auth/dependencies.py:21`), or route through proxy-layer auth. |
| P0-3 | Resilience | `backend/app/settings/router.py:259-262` | **Re-raise embedding rebuild failures as `HTTPException(503)` + roll back persisted `embedding_dims` config key.** Current code silently swallows the rebuild failure, admin sees 200 "success", semantic search broken with no recovery. The rollback is necessary because `cfg.set("embedding_dims", ...)` on line 244 persists the new value BEFORE the DDL attempt. |

### P1 — 21 items (fix before next release)

Grouped by natural wave:

**Wave A — Backend Performance (5 items, all ~small)**

| # | File:line | Fix |
|---|---|---|
| P1-1 | `backend/app/storage/local.py:15-69` | **Wrap every `LocalStorageProvider` method body in `await asyncio.to_thread(...)`.** Every method is declared `async def` but uses sync `open()`/`write()`/`shutil.copy2`/`Path.rglob` — blocks the event loop for the duration of every storage I/O. Mirror the `S3StorageProvider` pattern at `backend/app/storage/s3.py:90-134`. Default `STORAGE_PROVIDER=local` means every quicklook read, raster ingest, and thumbnail fetch blocks the loop on typical deployments. |
| P1-2 | `backend/app/auth/dependencies.py:38-41` | **Defer `api_key_obj.last_used_at` updates.** Current code commits a write on every API-key-authenticated GET. Either batch the timestamp updates every 60s or only update if prior `last_used_at` is older than 60s. Turns programmatic read workloads back into reads. |
| P1-3 | `backend/app/ingest/router.py:170-177` + `datasets/router_reupload.py:467-474` | **Parallelize presigned URL generation with `asyncio.gather()`.** Current loops sequentially over `to_thread(generate_presigned_part_url)` — a 500-part upload takes 15-25s before the client can start uploading. |
| P1-4 | `backend/app/maps/service.py:973-1048` + `router_data.py:171-186` | **Paginate `get_maps_for_dataset`.** Add `skip`/`limit` params. Widely-used datasets return the full list of consuming maps on every dataset detail page view. |
| P1-5 | `backend/app/auth/visibility.py:96-106` + 7 other sites | **Cache user roles per-request AND deduplicate the inline SQL.** Parent audit flagged the per-request query (PERF-P1 #9); the delta revealed the canonical `get_user_roles()` helper is bypassed by 6 of 7 other call sites that inline the same SQL. Fix: (a) cache on `request.state` OR attach to the User dep object, (b) convert all inline sites to call `get_user_roles(db, user)`. Sites: `jobs/router.py` (2x), `ingest/service.py`, `auth/dependencies.py` (2x), `auth/service.py`, `datasets/router_export.py`. |

**Wave A — Backend Type Safety (7 items, all ~small)**

| # | File:line | Fix |
|---|---|---|
| P1-6 | `backend/app/datasets/schemas.py:250-355` | **Tighten Pydantic `max_length` on `DatasetMeta` fields to match SQL column widths.** `update_frequency` (1000 → 30), `record_status` (1000 → 20), `sensitivity_classification` (1000 → 20), `language` (unbounded → 10). Prevents 500/IntegrityError on user input. |
| P1-7 | `backend/app/records/schemas.py:13-14, 65-69, 91-110` + `backend/app/datasets/models.py:272, 307-309, 338-344` | **Fix 5 more column-width mismatches** (delta TYPE findings 1-3): `RecordContact.role` (100 → 30 + Literal), `RecordKeyword.keyword_type` (100 → 20 + Literal), `RecordDistribution.distribution_type` (200 → 30), `.format` (200 → 50), `.media_type` (255 → 100). Use `Literal[...]` matching CHECK constraints where applicable. |
| P1-8 | `backend/app/auth/schemas.py:19-21` + `auth/models.py:36` | **Set `UserCreate.email` / `UserUpdate.email` to `max_length=255`** to match `User.email: String(255)`. Current `max_length=320` (RFC 5321 max) exceeds column. |
| P1-9 | `backend/app/maps/models.py:25` + `schemas.py:8-11` + `frontend/src/types/api.ts:701` | **Reconcile `MapVisibility` enum drift.** SQL CHECK allows `('private', 'public', 'internal', 'unlisted')` but Pydantic enum + TS union only have 3 values. Decide: add `unlisted` everywhere OR drop from CHECK via Alembic. Source-of-truth is the CHECK constraint. |
| P1-10 | `backend/app/maps/schemas.py:14, 44-46` | **Type `MapLayerInput.layer_type` as `Literal["vector_geolens", "raster_geolens", "geojson"] \| None`** to match the `chk_map_layers_layer_type` CHECK. Prevents 500 on typo'd values. |
| P1-11 | `backend/app/maps/router.py:481, 523, 563` | **Fix `share_url` to be absolute.** Field description says "Full shareable URL including token" but all 3 handlers emit `f"/m/{token}"` (relative). Frontend treats as absolute → broken copies, broken email shares. Use `get_public_app_url(db, request=request)` + `/m/{token}`. Also update frontend `MapVisibility` type (P1-9) since both affect the same files. |
| P1-12 | `backend/app/persistent_config.py:603, 611, 621` | **Parameterize `PersistentConfig[list[BasemapEntry]]`, `PersistentConfig[MapDefaultsResponse]`, `PersistentConfig[list[str] \| None]`, `PersistentConfig[dict[str, list[str]]]`.** Bare generic types (`list`, `dict`) defeat phase 222's `TypeAdapter` runtime validation promise for 4 config keys. This is the regression finding on fresh phase-222 work — makes the phase 222 promise real. |

**Wave A — Backend Resilience (6 items, mix of small + medium)**

| # | File:line | Fix |
|---|---|---|
| P1-13 | `backend/app/maps/router.py:603-663` | **Two issues on same endpoint:** (a) Wrap `storage.put` + `db.commit()` in try/except that deletes storage object on commit failure + raises 503 (parent RESILIENCE-P1 #2). (b) Write to temp key `maps/thumbnails/{map_id}.{ext}.{uuid}`, commit DB row referencing new key, then delete old key on success — avoids destructive overwrite before commit (delta RESILIENCE-5 #3). (c) Collapse `except (ValueError, Exception)` footgun. |
| P1-14 | `frontend/src/pages/DatasetPage.tsx:575-593` | **Wrap `<DatasetMap>` in `<MapErrorBoundary>`** matching the pattern used in `MapBuilderPage`, `PublicViewerPage`, `PublicMapViewerPage`. A JS exception inside the map currently takes down the entire dataset detail view. |
| P1-15 | `backend/app/auth/oauth/router.py:139-142` | **Use `logger.exception(...)` + stable error codes.** Currently: (a) `logger.warning(error=str(e))` without `exc_info=True` loses traceback; (b) raw exception text URL-encoded into `#error=...` fragment leaks internal details to browser history + Referer. Replace with `logger.exception(...)` and redirect with `#error=oauth_failed&correlation_id=...`. |
| P1-16 | `backend/app/datasets/router.py:296-347` | **Bulk delete must handle commit failure.** Currently `delete_dataset` deletes S3 objects per-item inside the loop, then a single cross-batch `db.commit()` happens at line 340 with no try/except. If commit fails, all storage objects are gone but DB rows intact; user sees 500. Fix: either commit per-item (atomic per dataset) OR wrap the batch commit with rollback-aware error handling that marks in-batch items as `rollback_storage_lost` so user can investigate. |
| P1-17 | `backend/app/middleware/body_limit.py:19-38` | **Enforce body limit on chunked encoding.** `RequestBodyLimitMiddleware` only checks when `Content-Length` header is present. `Transfer-Encoding: chunked` slips through. Wrap the request stream, count bytes as they arrive, raise 413 mid-read when cap exceeded. |
| P1-18 | `backend/app/worker.py:30-87` | **Prevent multi-worker job recovery race.** Every worker on startup calls `recover_stale_jobs()` which marks all `status='running'` jobs as `failed` with no advisory lock. On rolling restart, new worker kills old worker's actively-processing jobs. Fix: wrap in `pg_try_advisory_xact_lock(<key>)` + add `last_heartbeat_at` column on `IngestJob` + only mark stale if heartbeat is older than N minutes. |

### Known follow-ups (NOT in this phase)

After this phase ships, the audit reports also enumerate:
- **41 backend P2 items** (cleanup, dead code, duplication, moderate perf, non-critical type gaps)
- **25 backend P3 items** (cosmetic, style, minor optimization)
- **Several frontend P2/P3 items** (from parent audit only)

These are tracked in `post-impl-20260411.md` Section 6 and `post-impl-20260411-b.md` Sections 1-5. Do NOT expand scope into P2/P3 during this phase — stay focused on the 24 items above.

## Plan structure (recommended)

The fresh session running `/gsd-plan-phase 224` should decompose this into ~5 plans along natural wave boundaries. Rough shape:

- **Plan 224-01 — Backend Performance**: items P1-1 through P1-5 (LocalStorageProvider, API key, presigned URLs, pagination, roles caching + dedup). Plus the P0-1 Cartesian fix.
- **Plan 224-02 — Backend Type Safety**: items P1-6 through P1-12. Single migration for column width changes. Single file touch for PersistentConfig parameterization.
- **Plan 224-03 — Backend Resilience**: items P1-13 through P1-18. Plus the P0-3 embedding rebuild failure.
- **Plan 224-04 — Frontend**: items P0-2 (quicklook), P1-14 (DatasetMap error boundary), and the frontend side of P1-9 (MapVisibility type) / P1-11 (share_url type). Depends on Plan 224-02 landing the backend `MapVisibility` CHECK decision.
- **Plan 224-05 — Verification + audit report closeout**: run full test suite, verify no regressions, write verification report, update audit reports to mark closed items.

Plan wave dependencies: 224-01, 224-02, 224-03 run in parallel (wave 1). 224-04 runs in wave 2 (after 224-02 lands `share_url` + `MapVisibility` decisions). 224-05 runs in wave 3 after everything else.

## Locked decisions (DO NOT deviate)

1. **Scope = P0 + P1 only.** 24 items. Do not expand into P2/P3, even if "while we're in there" feels tempting. P2/P3 items are tracked for future phases.
2. **The P0-1 Cartesian fix MUST touch all 3 sites** in a single coherent patch. A partial fix that leaves STAC or RRF broken does not close P0-1.
3. **Column-width fixes go in one Alembic migration** (P1-6, P1-7, P1-8). Don't scatter them across 6 migrations.
4. **`MapVisibility` enum drift (P1-9)** requires a single source-of-truth decision BEFORE coding. Options: add `unlisted` everywhere, or drop from the CHECK constraint. The decision affects 4 files (model, schema, router, frontend type). Lock in discuss/plan phase.
5. **Do NOT touch the marketing site path** (phases 215/216/217) or the `getgeolens.com` repo. This phase is strictly backend + limited frontend (DatasetPage, SearchResultCard, `types/api.ts`, `use-quicklook.ts`).
6. **Don't modify phase 219's refactored `regenerate_vrt`.** The helper signatures are locked by D-01 in `.planning/phases/219-regenerate-vrt-phase-extraction/219-CONTEXT.md` and verified PASS 8/8 on 2026-04-11. Hands off.
7. **Test baseline is non-negotiable.** Before starting: frontend 940/948 green, backend VRT suite 92/92 green (per phase 219 execution), ruff check clean, tsc clean. Any regression must be fixed within the same plan that introduced it.
8. **Each P0/P1 item becomes a separate task within its plan.** Atomic commits per task — a bad bisect later should pinpoint which fix introduced a regression.

## Coordination hazards

- **Phase 215 is in progress** (task 1 running `/gsd-ui-phase 215` or `/gsd-execute-phase 215`). It writes to `.planning/phases/215-homepage/`, `.planning/STATE.md`, `.planning/ROADMAP.md`. Phase 224's fresh session should use **worktree isolation** for executors (see the refined guidance in `project_worktree_contamination.md` in user memory — isolation is the default now, not the exception).
- **Codex is running** in `/Users/ishiland/Code/geolens-ux-operator-workflows/` worktree. Its branch `codex/ux-operator-workflows-20260411` is filesystem-isolated from this repo; no coordination needed.
- **Phase 224's write surface** is backend source + `.planning/phases/224-*` + `.planning/STATE.md` + `.planning/ROADMAP.md`. The last two are shared with task 1's phase 215 work — standard `gsd-tools` state/roadmap commands handle the collision via last-writer-wins.

## Handoff instructions for the next session

```
1. /gsd-progress                          # verify phase 215 status, confirm 224 is the next unblocked phase
2. /gsd-plan-phase 224                    # read audit reports, decompose into 5 plans, run plan-checker
3. /gsd-execute-phase 224                 # wave-based execution; spawn gsd-executors with worktree isolation
4. /gsd-verify-work 224                   # verify phase goal achievement
5. Close out the audit items in the reports (mark resolved inline, or supersede with VERIFICATION.md)
```

Estimated execution time: 6-10 hours of focused work across all 5 plans. Each individual fix is small-to-medium; the volume is the challenge, which is why wave parallelism matters.

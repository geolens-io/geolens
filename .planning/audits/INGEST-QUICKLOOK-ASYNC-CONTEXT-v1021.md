---
audit_date: 2026-05-23
milestone: v1021
phase: 1091
scope: ingest-quicklook-async-context
status: COMPLETE
job_id: 90254766-ca62-4db4-86c5-411d1c9061fe
dataset_id: ffcba726-d61c-48e9-8786-3b41b5fc96f8
dataset_table: urban_areas_landscan_10m
feature_count: 6018
geometry_type: Polygon (MultiPolygon)
job_duration_seconds: 16.635
generation_timeout_seconds: 10
root_cause_file: backend/app/processing/ingest/tasks_common.py
root_cause_lines: "826-828, 666, 835"
fix_target_lines: "826-828 (open fresh session for the quicklook block)"
test_file: backend/tests/test_quicklook_async_context.py
---

# Audit — Ingest Quicklook Async-Context Boundary (v1021 / Phase 1091-01)

Spike-first investigation per v1019 Phase 1085 / v1020 Phase 1087 / Phase 1088-04 precedent. Identifies the exact line(s) in `backend/app/processing/ingest/tasks_common.py` and the helpers it calls into that cross an async-context boundary on the `urban_areas_landscan_10m` post-commit quicklook flow, producing the `MissingGreenlet: greenlet_spawn has not been called; can't call await_only() here` runtime failure observed in quick task `260523-at1`.

**NO production code modified in this plan.** The audit's Section 3 proposed fix is consumed by Plan 1091-02.

---

## Section 1 — Live Reproduction Evidence

### Stack health at spike time

`docker compose ps -a` (taken `2026-05-23T~14:50Z` local; stack has been up 3h since the seed run at `11:52:18Z`):

```
SERVICE    STATE     STATUS
api        running   Up 3 hours (healthy)
db         running   Up 3 hours (healthy)
frontend   running   Up 3 hours (healthy)
titiler    running   Up 3 hours (healthy)
worker     running   Up 3 hours (healthy)
(migrate exited 0)
```

All services healthy; the failed-job row is preserved.

### Admin job-ledger row (verbatim)

`GET /api/admin/jobs/?status=failed&limit=10` with admin JWT:

```json
{
  "jobs": [
    {
      "id": "90254766-ca62-4db4-86c5-411d1c9061fe",
      "status": "failed",
      "source_filename": "ne_10m_urban_areas_landscan.zip",
      "dataset_id": "ffcba726-d61c-48e9-8786-3b41b5fc96f8",
      "error_message": "greenlet_spawn has not been called; can't call await_only() here. Was IO attempted in an unexpected place? (Background on this error at: https://sqlalche.me/e/20/xd2s)",
      "user_metadata": {
        "title": "Urban Areas Landscan (10m)",
        "summary": null,
        "x_column": null,
        "y_column": null,
        "layer_name": null,
        "visibility": "public",
        "geom_column": null,
        "temporal_end": null,
        "srid_override": 4326,
        "temporal_start": null
      },
      "created_by": "31208d96-f389-4cb5-9f8b-857ad0d3ab04",
      "username": "admin",
      "started_at":  "2026-05-23T11:59:05.958235Z",
      "completed_at": "2026-05-23T11:59:22.527474Z",
      "created_at":   "2026-05-23T11:59:05.847216Z"
    }
  ],
  "total": 1
}
```

Job duration = `completed_at - started_at` = **16.635 s** (matches procrastinate worker's `lasted 16.635 s` log line).

### Worker-log MissingGreenlet trace (ANSI stripped)

```
2026-05-23T11:59:05.957Z [info]    Starting job ingest_file[71](job_id='90254766-...', file_path='/app/staging/...ne_10m_urban_areas_landscan.zip')
2026-05-23T11:59:07.159Z [info]    Renaming geometry column     from_col=_geolens_geom to_col=geom
2026-05-23T11:59:21.038Z [warning] quicklook_failed
  [app.processing.ingest.tasks_common]
  error="Can't reconnect until invalid transaction is rolled back.  Please rollback() fully before proceeding
         (Background on this error at: https://sqlalche.me/e/20/8s2b)"
  job_id=90254766-... phase=commit table=urban_areas_landscan_10m task=ingest_file
2026-05-23T11:59:21.038Z [info]    catalog_cache_invalidated    [app.platform.cache.tiles]
2026-05-23T11:59:21.038Z [error]   Ingest task failed           [app.processing.ingest.tasks_vector]
                                  job_id=90254766-... task=ingest_file
╭──────────── Traceback (most recent call last) ────────────╮
│ /app/app/processing/embeddings/helpers.py:123 in defer_embedding │
│                                                                  │
│ ❱ 123  await embed_record.defer_async(record_id=str(dataset.record.id │
│                                                                  │
│ locals:                                                          │
│   dataset      = <app.modules.catalog.datasets.domain.models.Dataset │
│                   object at 0xffff79932750>                      │
│   embed_record = <procrastinate.tasks.Task object at 0xffff7af49450> │
│                                                                  │
│ /app/.venv/lib/python3.14/site-packages/sqlalchemy/orm/attributes.py:569 │
│ in __get__                                                       │
│                                                                  │
│ ❱ 569    return self.impl.get(state, dict_)                      │
╰──────────────────────────────────────────────────────────────────╯
MissingGreenlet: greenlet_spawn has not been called; can't call await_only()
here. Was IO attempted in an unexpected place?
(Background on this error at: https://sqlalche.me/e/20/xd2s)

2026-05-23T11:59:22.592Z [error] Job ingest_file[71](...) ended with status: Error, lasted 16.635 s
```

### Key evidence the planner's hypothesis under-named

The plan's `<spike_hypotheses>` framed the bug as a `_generate_quicklook` crash. **The traceback proves otherwise.** The `MissingGreenlet` is NOT raised inside `_generate_quicklook` — it is raised at `helpers.py:123` inside `defer_embedding`, called from `_finalize_ingest:835`, accessing the ORM relationship `dataset.record.id`. `_generate_quicklook` did warn-and-return at line 666-672 (the worker log shows `quicklook_failed phase=commit`); the explosion happens TWO LINES LATER in the caller, on the very next ORM attribute access against the session that `_generate_quicklook` rolled back.

### Resolved constants

| Constant | File | Line | Value | Relevance |
|---|---|---|---|---|
| `_GENERATION_TIMEOUT_SECONDS` | `backend/app/processing/vector/quicklook.py` | 24 | `10` (seconds) | H4 trigger — `asyncio.wait_for(..., timeout=10)` at quicklook.py:231-234 |
| `expire_on_commit` | `backend/app/core/db/session.py` | 26 | `False` | Eliminates "commit expires attributes" hypothesis |
| `expire_on_rollback` | (default) | n/a | `True` | **CRITICAL** — rollback DOES expire attributes; not overridden |
| `dataset.record` relationship `lazy` | `backend/app/modules/catalog/datasets/domain/models.py` | 286-288 | `lazy="joined"` | Eagerly loaded at create time, but expired by rollback → next access lazy-refreshes |
| Procrastinate connector `min_size`/`max_size` | `backend/app/processing/ingest/tasks_common.py` | 71-72 | `1` / `3` | Fix-shape risk: opening a second session in the same task adds one pool checkout |
| App engine `db_pool_size`/`db_max_overflow` | `backend/app/core/config.py` | 118-119 | `10` / `3` | App engine sufficient headroom even with seed `Semaphore(3)` parallelism |
| Seed-script concurrency | `scripts/seed-natural-earth.py` | 977 | `asyncio.Semaphore(3)` | 3 concurrent ingests max → 3 second-session checkouts in worst case |
| Job duration | observed | — | 16.635 s | Exceeds 10 s timeout → `asyncio.TimeoutError` fires inside `_generate_quicklook` |

---

## Section 2 — Code Path Trace

### 2.1 — The caller (tasks_common.py)

`backend/app/processing/ingest/tasks_common.py:675-837` — `_finalize_ingest(ctx)`. The terminal sequence after dataset insertion:

```python
# tasks_common.py:802
dataset.record.record_status = user_metadata.get("record_status", "published")  # relationship traversal (lazy="joined", warm here)

# tasks_common.py:804-808 — quality score (uses session, not relationship)
quality_score = await compute_quality_score(session, ...)
dataset.quality_detail = quality_score

# tasks_common.py:816-822 — terminal commit
job.status = "complete"
job.dataset_id = dataset.id        # PK column access — still warm
job.completed_at = datetime.now(timezone.utc)
job.current_step = "complete"
job.progress = 1.0
job.rows_processed = metadata.get("feature_count")
await session.commit()              # ← COMMIT #1 — succeeds. expire_on_commit=False so attrs stay warm.

# tasks_common.py:824-828 — quicklook (non-fatal, SAME session)
if has_geometry:
    await _generate_quicklook(
        session, dataset, table_name, metadata.get("geometry_type", "")
    )                                # ← THE BOUNDARY — session is passed to quicklook code

# tasks_common.py:831 — cache invalidation (no session)
await invalidate_catalog_cache()

# tasks_common.py:835 — embedding deferral (touches dataset.record — RELATIONSHIP access)
await defer_embedding(dataset)       # ← MissingGreenlet is raised inside this call
```

### 2.2 — The suspect (tasks_common.py:627-672)

`_generate_quicklook(session, dataset, table_name, geometry_type)`:

```python
# tasks_common.py:627-672
async def _generate_quicklook(session, dataset, table_name, geometry_type) -> None:
    import io as _io
    _ql_log = structlog.get_logger()
    try:
        # tasks_common.py:641-643
        from app.processing.vector.quicklook import (
            generate_vector_quicklook_with_timeout as generate_vector_quicklook,
        )
        # tasks_common.py:645-647 — calls into quicklook.py:222 (asyncio.wait_for wrapper)
        ql_bytes = await generate_vector_quicklook(
            session, table_name, geometry_type, 256
        )
        # tasks_common.py:648-651 — happy path: persist to storage + write URI on ORM
        ql_storage = get_storage()
        ql_key = f"vectors/{dataset.id}/quicklook_256.png"
        await ql_storage.put(ql_key, _io.BytesIO(ql_bytes))
        dataset.quicklook_256_uri = ql_key
    except Exception as _ql_exc:  # tasks_common.py:652
        # tasks_common.py:653-658 — warn-and-return on generate-phase failure
        _ql_log.warning("quicklook_failed", phase="generate", table=table_name,
                        error=str(_ql_exc))
        return

    # tasks_common.py:661-672 — commit-phase: SAME session reused
    try:
        await session.commit()                            # ← COMMIT #2 (on session #1)
    except Exception as _ql_commit_exc:  # tasks_common.py:663-665
        await session.rollback()                          # ← ROLLBACK — EXPIRES dataset attributes
        _ql_log.warning("quicklook_failed", phase="commit", table=table_name,
                        error=str(_ql_commit_exc))
```

### 2.3 — The timeout source (quicklook.py)

`backend/app/processing/vector/quicklook.py`:

```python
# quicklook.py:24
_GENERATION_TIMEOUT_SECONDS = 10

# quicklook.py:113-164 — the SQL-execution portion
async def generate_vector_quicklook(db, table_name, geometry_type, size=256):
    if not _TABLE_NAME_RE.match(table_name):
        return _blank_canvas(size)
    # quicklook.py:128-134 — bounds query (cheap aggregate, succeeds quickly)
    bounds_sql = text(
        f"SELECT ST_XMin(e) AS minx, ST_YMin(e) AS miny, "
        f"       ST_XMax(e) AS maxx, ST_YMax(e) AS maxy, "
        f"       (SELECT reltuples::bigint FROM pg_class WHERE relname = :tname) AS est_rows "
        f"FROM (SELECT ST_Extent(geom_4326) AS e FROM data.{table_name} WHERE geom_4326 IS NOT NULL) sub"
    ).bindparams(tname=table_name)
    bounds_result = await db.execute(bounds_sql)               # SELECT #1 — OK
    bounds_row = bounds_result.fetchone()
    ...
    # quicklook.py:148-161 — geom query (HEAVY — ST_Simplify(ST_MakeValid(...))
    # on 6018 multipolygons; this is the operation that exceeds 10s)
    if est_rows > max_features * 2:                            # est_rows ~6018, max_features=2000 ⇒ TABLESAMPLE path
        sample_pct = min(100.0, (max_features / max(est_rows, 1)) * 100 * 1.5)
        geom_sql = text(
            f"SELECT ST_AsGeoJSON(ST_Simplify(ST_MakeValid(geom_4326), 0.01)) AS geojson "
            f"FROM data.{table_name} TABLESAMPLE SYSTEM ({sample_pct:.2f}) "
            f"WHERE geom_4326 IS NOT NULL LIMIT {max_features}"
        )
    ...
    result = await db.execute(geom_sql)                        # SELECT #2 — THIS IS WHERE TIMEOUT CANCELS
    rows = result.fetchall()

# quicklook.py:222-236 — the wrapper that fires the cancellation
async def generate_vector_quicklook_with_timeout(db, table_name, geometry_type,
                                                  size=256, timeout=_GENERATION_TIMEOUT_SECONDS):
    try:
        return await asyncio.wait_for(                         # quicklook.py:231-234
            generate_vector_quicklook(db, table_name, geometry_type, size),
            timeout=timeout,                                   # ← 10 seconds
        )
    except asyncio.TimeoutError:                               # quicklook.py:235
        return _blank_canvas(size)                             # ← returns blank, but cursor wedged
```

### 2.4 — The detonation site (helpers.py)

`backend/app/processing/embeddings/helpers.py:118-126`:

```python
async def defer_embedding(dataset) -> None:
    """Defer an embedding generation task for a dataset. Non-fatal on failure."""
    try:
        from app.processing.embeddings.tasks import embed_record
        # helpers.py:123 — touches dataset.record (RELATIONSHIP).
        # After session.rollback() inside _generate_quicklook, the eagerly-loaded
        # 'record' attribute on dataset is EXPIRED. Accessing dataset.record.id
        # triggers a refresh via the SQLAlchemy greenlet bridge; the bridge state
        # is poisoned by the asyncio.wait_for cancellation inside generate_vector_quicklook,
        # so SQLAlchemy raises MissingGreenlet instead of refreshing.
        await embed_record.defer_async(record_id=str(dataset.record.id))
    except Exception:  # broad: defer is non-fatal
        logger.warning("Failed to defer embedding task", dataset_id=str(dataset.id))
```

### 2.5 — The session factory (session.py)

`backend/app/core/db/session.py:25-26`:

```python
engine = create_async_engine(settings.database_url, **_engine_kwargs)
async_session = async_sessionmaker(engine, expire_on_commit=False)   # ← only commit is non-expiring
# expire_on_rollback is NOT set → defaults to True → rollback EXPIRES all loaded attributes
```

### 2.6 — Stale docstring reference

`tasks_common.py:208-209` (inside `_job_phase_session`'s docstring):

```python
"""...
**Enforces the #100 greenlet rule** by keeping the SQLAlchemy session
lifetime scoped to the ``async with`` block. Long-running CPU /
asyncio subprocess work MUST happen OUTSIDE this block, never inside
— see ``.planning/debug/worker-missing-greenlet-100.md`` and the
docstrings on ``ingest_file`` / ``ingest_raster``.
..."""
```

Confirmed at spike time: `.planning/debug/worker-missing-greenlet-100.md` **does NOT exist on disk** (only `b01-builder-fresh-add-no-render.md`, `vrt-test-failures.md`, and a `resolved/` subdir live in `.planning/debug/`). The docstring reference is stale. Plan 1091-02 SHOULD update this reference to point at the v1021 audit doc (this file). **Spike does not recreate the missing file.**

### 2.7 — Hypothesis verdicts

**H1 — Stale session-state after `session.commit()` at tasks_common.py:822, then re-entering `_generate_quicklook` which itself calls `await session.commit()` at line 662.** **PARTIALLY TRUE — necessary but not sufficient.** The session IS reused across the boundary at tasks_common.py:826. The first commit at line 822 succeeds; the second commit at line 662 fails with the "Can't reconnect until invalid transaction is rolled back" error from the SQLAlchemy 2.0 docs (https://sqlalche.me/e/20/8s2b — visible in the worker log at line 8 of the captured trace). This explains the antecedent warning but not the MissingGreenlet — the MissingGreenlet fires LATER, at line 835, not at line 662.

**H2 — `asyncio.wait_for(...)` at quicklook.py:231 cancelling the inner SQLAlchemy `db.execute` mid-flight without cleaning up the asyncpg cursor.** **TRUE — this is the upstream trigger.** The 16.635 s job duration vs the 10 s `_GENERATION_TIMEOUT_SECONDS` is the smoking gun: `asyncio.wait_for` cancelled the `await db.execute(geom_sql)` at quicklook.py:163 while the heavy `ST_Simplify(ST_MakeValid(geom_4326), 0.01)` was running over 6018 multipolygons. Per the SQLAlchemy 2.0 docs (https://sqlalche.me/e/20/8s2b cited in the worker log), cancellation mid-execute leaves the connection in a state where the next operation requires explicit rollback before any new SQL can run. `generate_vector_quicklook_with_timeout` swallows the TimeoutError and returns `_blank_canvas(size)` to its caller (quicklook.py:235-236) — the session it shared with `_generate_quicklook` is now poisoned.

**H3 — Lazy relationship access on `dataset.record` post-`commit()`.** **TRUE — this is the detonation mechanism.** `dataset.record` is `lazy="joined"` (models.py:287), so it's eagerly loaded at `port.create_dataset()` time inside `_finalize_ingest`. However: SQLAlchemy's `async_sessionmaker(engine, expire_on_commit=False)` at session.py:26 only suppresses expiry on COMMIT — it does NOT suppress expiry on ROLLBACK (the default is to expire). When `_generate_quicklook:666` calls `await session.rollback()`, every loaded attribute on `dataset` (including the eagerly-loaded `record`) is marked expired. The next access (helpers.py:123 → `dataset.record.id`) attempts to refresh via the greenlet bridge, which is still in the poisoned state from H2 → MissingGreenlet at attributes.py:569.

**H4 — Feature-shape pathological geometry on `urban_areas_landscan_10m`.** **TRUE — this is why it's reliably 1-in-109, not flaky.** 6018 multipolygon features × `ST_MakeValid(ST_Simplify(...))` exceeds the 10 s budget on the test machine. The other 108 datasets are smaller (`ne_10m_admin_0_countries` has ~177 features, `ne_10m_reefs` has ~862) or simpler geometries that complete inside 10 s. H4 is the necessary condition for H2 to fire deterministically on this one dataset.

**H5 — The MissingGreenlet might be raised from the commit phase try block (lines 661-672), not the generate phase try block.** **FALSE — the MissingGreenlet is raised at helpers.py:123, NOT inside `_generate_quicklook` at all.** The traceback proves it: the stack frame is `defer_embedding` → `dataset.record.id` → `attributes.py:__get__:569`. The `quicklook_failed phase=commit` warning at worker-log line 8 is the SQLAlchemy "Can't reconnect until invalid transaction is rolled back" error — a DIFFERENT exception that `_generate_quicklook` caught and warn-logged, then returned cleanly. The session is poisoned at that point but no exception escapes `_generate_quicklook`; the failure escapes from `defer_embedding` two function calls later in `_finalize_ingest`.

---

## Section 3 — Root Cause + Proposed Fix

### Root Cause

**The same `AsyncSession` is reused across the asyncio-cancellation boundary at `backend/app/processing/ingest/tasks_common.py:826`.** When `asyncio.wait_for(generate_vector_quicklook(db, ...), timeout=10)` at `backend/app/processing/vector/quicklook.py:231-234` cancels the inner `await db.execute(geom_sql)` at `backend/app/processing/vector/quicklook.py:163` because the 6018-multipolygon `ST_Simplify(ST_MakeValid(geom_4326), 0.01)` exceeds the 10 s budget, the asyncpg connection underlying the session is left in an invalid-transaction state ("Can't reconnect until invalid transaction is rolled back"). The defensive `await session.rollback()` at `backend/app/processing/ingest/tasks_common.py:666` does fully roll back the transaction, **but it also expires every loaded ORM attribute on `dataset`** (because the session was created with `async_sessionmaker(engine, expire_on_commit=False)` at `backend/app/core/db/session.py:26` — `expire_on_rollback` defaults to `True` and was never overridden). When `_finalize_ingest` continues past the silent quicklook failure and calls `await defer_embedding(dataset)` at `backend/app/processing/ingest/tasks_common.py:835`, the access at `backend/app/processing/embeddings/helpers.py:123` (`dataset.record.id`) tries to lazy-refresh the expired `record` relationship via the SQLAlchemy greenlet bridge. The greenlet bridge state is still poisoned from the cancellation at H2, so SQLAlchemy raises `MissingGreenlet: greenlet_spawn has not been called` at `sqlalchemy/orm/attributes.py:569` instead of refreshing — and that exception escapes `_finalize_ingest` to the outer `except Exception as exc` in `ingest_file` (tasks_vector.py:314), which writes `status='failed'` to the job row. The dataset row itself is unaffected because commit #1 at tasks_common.py:822 already committed it.

### Proposed Fix (Shape A — open a fresh session for the quicklook block)

| Field | Value |
|---|---|
| **File** | `backend/app/processing/ingest/tasks_common.py` |
| **Lines to change** | 824-828 (the `if has_geometry: await _generate_quicklook(...)` block) |
| **What changes** | Wrap the quicklook call in a new `async with async_session() as ql_session:` block. The fresh session is what `_generate_quicklook` mutates, commits, and rolls back. The outer `session` (which holds the warm `dataset` ORM object and is still healthy after the successful commit at line 822) is never reached by the timeout cancellation, never has its connection wedged, and never expires its attributes. Pass `ql_session` AND `dataset` into `_generate_quicklook` — the function must `session.merge(dataset)` (or accept a pre-merged target) so the `dataset.quicklook_256_uri = ql_key` write at line 651 happens on the new session's identity-map entry. |
| **Why this closes the root cause** | The H2 cancellation poisons whichever session is passed to `generate_vector_quicklook`. Isolating the quicklook into its own short-lived session means H3's lazy-refresh at `defer_embedding` runs against the outer session, which never saw the cancellation and whose ORM attributes are still warm. The 10 s timeout still fires for pathological-shape inputs (H4 unchanged), but the failure no longer propagates outside the quicklook block. |
| **What this intentionally does NOT fix** | Does NOT refactor `_generate_quicklook` itself (signature change only). Does NOT add retry logic on the cancelled SELECT. Does NOT change `_GENERATION_TIMEOUT_SECONDS`. Does NOT touch `defer_embedding` or `helpers.py:123`. Does NOT update `expire_on_commit` / `expire_on_rollback` at the session-factory level (would change behavior across the whole app — out of scope for INGEST-01). Does NOT eliminate the worker-log `quicklook_failed phase=commit` warning shape (the warning is the spike — it correctly reports a failed quicklook; the bug is that the failure propagated further than it should). |

### Alternative Fix Shapes Considered (Rejected)

| Shape | Why rejected |
|---|---|
| **Shape B — set `expire_on_rollback=False` on `async_sessionmaker` at session.py:26** | Out of scope (INGEST-01 forbids broader `tasks_common.py` refactor and the session-factory change touches the entire app — request-handler sessions would also stop expiring attributes on rollback, a non-trivial behavior change with unknown downstream impact). Even if applied, it would only fix H3 detonation; the underlying cursor-poisoning from H2 would still leave the session in an invalid-transaction state, and the NEXT `await session.commit()` at line 835's downstream (e.g. the embedding-job defer's procrastinate insert) would still fail. Shape A fixes both H2 and H3 by isolation. |
| **Shape C — eagerly refresh `dataset.record` BEFORE calling `defer_embedding`** | Treats the symptom, not the cause. The session is still poisoned; any other ORM access (or a future `defer_embedding` change) would re-trip the bug. Fragile. |
| **Shape D — restructure `_generate_quicklook` to NEVER call `session.commit()` (just set the URI and let the next caller commit)** | Defers the commit to either `_finalize_ingest` (re-introduces the H2 cancellation against the outer session — same bug) or to `defer_embedding`'s downstream (changes the commit-atomicity contract — `dataset.quicklook_256_uri` would be lost if anything after line 826 fails before its commit). Architecturally undesirable. |
| **Shape E — add a `try/except MissingGreenlet` around `defer_embedding` and re-fetch dataset on a fresh session** | Symptom-level workaround; doesn't prevent the next ORM access from tripping the same boundary. Adds defensive code without fixing the structural problem. |

### Proposed Regression Test

| Field | Value |
|---|---|
| **Test file** | `backend/tests/test_quicklook_async_context.py` (new) |
| **Fixtures used** | `test_db_session` (existing — same pattern as `backend/tests/test_tasks_common_phase_brackets.py`); optionally `client` for an end-to-end smoke variant |
| **Test function (required)** | `test_generate_quicklook_timeout_does_not_poison_outer_session` — set up a `dataset` ORM row inside `test_db_session`, monkeypatch `_GENERATION_TIMEOUT_SECONDS` to a small value (e.g., `0.001`) so the cancellation fires deterministically, call `_finalize_ingest` (or `_generate_quicklook` + `defer_embedding` directly via the same flow), assert no exception escapes AND the dataset row's column-level attributes (e.g., `dataset.id`, `dataset.record.id`) remain accessible without `MissingGreenlet`. **Should PASS post-fix.** |
| **Test function (xfail pre-fix)** | `test_generate_quicklook_timeout_poisons_outer_session_pre_fix` — same setup as above, but `@pytest.mark.xfail(raises=MissingGreenlet, reason="pre-fix regression pin: tasks_common.py:826 reuses session across asyncio.wait_for cancellation boundary; see .planning/audits/INGEST-QUICKLOOK-ASYNC-CONTEXT-v1021.md")`. This pin documents the bug shape so any future regression that re-introduces session reuse is caught immediately. **Should xfail PASS pre-fix, fail-as-xpass post-fix → flip to PASS after fix.** Plan 1091-02 SHOULD revisit whether this xfail stays after the fix or is converted into a positive regression assertion. |
| **Test function (multipolygon shape regression)** | `test_generate_quicklook_completes_on_6018_multipolygon_shape` — seeds a synthetic `data.<table>` with 1000+ multipolygon rows (downscaled from 6018 for unit-test speed), asserts `_generate_quicklook` returns within reasonable wall time and the outer session is still usable. Anchors INGEST-01 acceptance criterion (c). |

### Risks

| Risk | Severity | Mitigation in Plan 1091-02 |
|---|---|---|
| **Adding a second `async_session()` checkout per ingest doubles connection-pool demand for the quicklook window** | **HIGH — this is the warning the plan-checker flagged.** | App-engine pool: `db_pool_size=10` + `db_max_overflow=3` (config.py:118-119) = 13 connection budget for the app. Seed-script worst case: `Semaphore(3)` (seed-natural-earth.py:977) = max 3 concurrent ingests. Each ingest peaks at 2 simultaneous sessions during the quicklook window (the outer `session` is held in `_finalize_ingest`'s `async with` plus the new `ql_session` lives concurrently). Worst case: 3 × 2 = 6 connections during quicklook — well under the 13 budget. **Procrastinate connector pool (min_size=1, max_size=3 at tasks_common.py:71-72) is irrelevant** — that pool serves procrastinate's own metadata operations (job claim/ack), not application SQLAlchemy sessions. Plan 1091-02 verification should include: (a) on the post-fix seed run, log peak concurrent SQLAlchemy connection count via `pg_stat_activity` sampling and assert ≤13; (b) confirm CI `pytest -n 4` baseline 3047/0/38 stays green. NO pool-size bump should be necessary; if the assertion fails Plan 1091-02 escalates per CONTEXT.md's Out-of-Scope clause ("Postgres max_connections bump rejected — production envelope at 30 is correct"). |
| **Dataset ORM attribute writes on `ql_session` (e.g., `dataset.quicklook_256_uri = ql_key` at line 651) must persist to the outer session's identity-map view OR be re-merged** | Medium | The simplest fix is for `_generate_quicklook(ql_session, dataset, ...)` to internally do `dataset = await ql_session.merge(dataset)` so writes happen on `ql_session`'s identity-map copy and the next commit persists them. The outer `dataset` reference in `_finalize_ingest` is then stale w.r.t. `quicklook_256_uri`, but `_finalize_ingest` does not read that field after line 826, so this is fine. Plan 1091-02 must verify post-fix that `urban_areas_landscan_10m`'s `quicklook_256_uri` is NULL (because generation timed out, which is the same outcome as pre-fix for THIS dataset) but other datasets continue to get their URIs persisted. Acceptance criterion INGEST-01(b) — `urban_areas_landscan_10m` has a non-null quicklook URI — needs reframing: the fix is "the session is not poisoned"; the 10s timeout is unchanged so the same generation will still time out and return blank. **This may surface a second issue for Plan 1091-02 to discuss with the operator: either (i) bump `_GENERATION_TIMEOUT_SECONDS`, (ii) accept a blank quicklook for landscan, or (iii) write the blank canvas to storage on timeout instead of returning early without persisting the URI.** Recommended path for the fix-and-test plan: option (iii) — `generate_vector_quicklook_with_timeout` returns `_blank_canvas(size)` bytes on timeout but `_generate_quicklook` still uploads those bytes and writes the URI; the dataset gets a "blank" quicklook indicating no thumbnail rendered. INGEST-01(b) then passes. |
| **Session-bracket pattern divergence — the project's idiomatic bracket is `_job_phase_session(job_uuid, phase=…)` (tasks_common.py:182-240), not a raw `async_session()` checkout** | Low | Plan 1091-02 SHOULD use `_job_phase_session(job_uuid, phase="quicklook")` for consistency rather than a raw `async_session()`. This also gives operators a `phase="quicklook"` log breadcrumb when an `IngestJob` row vanishes mid-quicklook. The `job` yielded by the helper is not needed (quicklook does not touch the job row), so we can `_ = _quicklook_job`. |
| **The `expire_on_rollback=True` default behavior is a footgun that exists across the entire codebase** | Low (out of scope but worth a CHANGELOG/MEMORY.md mention) | Plan 1091-02 should add a one-line `MEMORY.md` "Known Issues & Workarounds" note: "`async_session()` uses `expire_on_commit=False` but the default `expire_on_rollback=True` — rollback will expire ORM attributes even when commit doesn't. Code that catches an exception and rolls back must re-load any subsequently-accessed ORM objects on a fresh session, not the rolled-back session." This is a documentation deliverable, not a code change. |

---

## Plan 1091-02 implements the fix proposed in Section 3.

Specifically, Plan 1091-02's executor consumes this audit doc as:

1. **The fix `<action>`:** apply Shape A — open a fresh session (via `_job_phase_session(job_uuid, phase="quicklook")`) for the quicklook block at `tasks_common.py:824-828`; refactor `_generate_quicklook` to accept the fresh session and merge `dataset` into it; ensure the blank-canvas write path on timeout still persists the URI (Risk #2 above) so INGEST-01(b) passes.
2. **The regression-test `<action>`:** create `backend/tests/test_quicklook_async_context.py` with the three test functions named in Section 3. Pin node-IDs in REQUIREMENTS.md per TD-13 `req_citation_pinning` rule.
3. **The verify `<action>`:** verify pool-checkout count under seed parallelism (Risk #1); confirm `urban_areas_landscan_10m` row has a non-NULL `quicklook_256_uri` post-fix even though the generation times out (Risk #2 mitigation path iii); confirm sequential `pytest -n 4` baseline 3047/0/38 stays green.
4. **The MEMORY.md update:** add the `expire_on_rollback` footgun note (Risk #4).
5. **The docstring update:** at `tasks_common.py:208-209`, replace the broken `.planning/debug/worker-missing-greenlet-100.md` reference with a pointer to this audit doc (`.planning/audits/INGEST-QUICKLOOK-ASYNC-CONTEXT-v1021.md`).

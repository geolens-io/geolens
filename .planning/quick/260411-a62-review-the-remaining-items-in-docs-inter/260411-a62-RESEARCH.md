# Quick Task 260411-a62: Validate Remaining Items in HANDOFF-REMAINING — Research

**Researched:** 2026-04-11
**Domain:** Audit-item validation (no code changes)
**Confidence:** HIGH

## Summary

All 5 open items (K2, K4, K6, N6, TYPE-5) in `docs-internal/audits/post-impl-20260410-HANDOFF-REMAINING.md` are **still valid** against the current working tree. Line numbers have drifted by only a few lines since the 2026-04-10 session (because the only commits touching these files since are `f6a7f96a` — the snapshot the handoff already described — plus the unrelated SecretStr migration in `a6371f9f` / `56c59cfd` which touched `config.py`, not `persistent_config.py`). The snapshot-split meta-item is **N/A** — `f6a7f96a` is already on `origin/main` and cannot be retroactively split. Effort estimates in the handoff are still accurate; no blocker notes need updating.

**Primary recommendation:** Promote K2, K4, K6, N6, TYPE-5 to `999.x` backlog entries verbatim from the handoff (no scope changes). Mark the snapshot-split item closed as N/A. Update HANDOFF-REMAINING.md in place with an index table and per-item "→ backlog: 999.x-slug" pointers.

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **Scope: Validate-then-scope, not ship-fixes.** This is a validation + bookkeeping pass. No ingest/config/VRT source files will be edited in this task.
- **Closeout depth: Link to backlog.** For every item that survives validation, create a `/gsd-add-backlog` entry (999.x phase). HANDOFF-REMAINING.md points each surviving item at its backlog entry with a one-line "→ backlog: 999.x-slug". Items that turn out to be already-shipped / no-longer-applicable get marked as such inline (no backlog entry).
- **Snapshot-split item:** Moot. `f6a7f96a` is already on `origin/main`. Mark as N/A in closeout.
- **N6 and TYPE-5 disposition:** Default to "backlog with observational note". Planner can formally close as "won't fix — permanent defer" if validation confirms the audit verdict.
- **Large-refactor scoping (K2, K4, K6):** Stay deferred. Task is to confirm handoff's effort estimates and blocker notes still match code, then create backlog entries. Do NOT start any refactor.

### Claude's Discretion
- Exact phrasing of backlog entry titles and descriptions (match `/gsd-add-backlog` conventions).
- Whether to update `STATE.md` quick-task table (yes — standard workflow).
- Whether closeout doc is new file or in-place edits (default: in-place edits + new status header).
- Whether to add an index/summary table at top of HANDOFF-REMAINING.md showing final disposition of every item (recommended for clarity).

### Deferred Ideas (OUT OF SCOPE)
- All code changes (no K2/K4/K6 refactors, no N6 LIMIT bump, no TYPE-5 TypeAdapter conversion).
- Frontend TypeScript audit follow-up (already shipped as PR #22 per handoff session log).

## Project Constraints (from CLAUDE.md)
- **Version control:** Never indicate AI/Bot authorship in commit messages.
- **Code style:** Prefer simple/readable over clever; follow existing project conventions.
- **Communication:** Direct and concise; ask before assuming intent.

These are low-impact for a validation-only task (no code edits), but any backlog entries created should follow existing `/gsd-add-backlog` conventions.

## Validation Results — Summary Table

| ID | Status | Current location | Revised effort | Recommendation |
|----|--------|------------------|----------------|----------------|
| **K2** | **Valid** — claim fully holds | `tasks.py:523` (`ingest_file`), `tasks.py:1106` (`reupload_file`), `tasks.py:990` (`_apply_reupload_swap`) | **4-6h** (unchanged) | Promote to `999.x` backlog (P3, large) |
| **K4** | **Valid** — claim fully holds | `tasks.py:2093` (`regenerate_vrt`), 231 lines, max indent depth 29 cols (~7 levels) | **3-4h** (unchanged) | Promote to `999.x` backlog (P3, large; blocked on integration coverage) |
| **K6** | **Valid** — claim fully holds | `schemas.py:97` (`CommitRequest`), 13 optional fields | **Medium backend + small frontend + coordination** (unchanged) | Promote to `999.x` backlog (P3, API contract change) |
| **N6** | **Valid** — no user complaints surfaced | `metadata.py:204` (`get_sample_values`), CTE with `LIMIT :sample_size` default 1000 | **XSmall (1-line)** (unchanged) | Promote to `999.x` backlog as observational; 1-line LIMIT bump is still the right fix if triggered |
| **TYPE-5** | **Valid** — 3 sites unchanged | `persistent_config.py:84, 88, 113` | **Small if attempted, deferred by audit** (unchanged) | Promote to `999.x` backlog with observational note; `Generic[T]` TypeVar makes `TypeAdapter[T].validate_python()` impractical without refactoring the class |
| **Snapshot split** | **N/A** | `f6a7f96a` on `origin/main` | — | Close inline in HANDOFF-REMAINING.md; no backlog entry |

## Per-Item Findings

### K2 — Shared vector staging pipeline (`ingest_file` ↔ `reupload_file`)

**What the handoff claims:** `ingest_file` at `tasks.py:522`, `reupload_file` at `:1109`, ~150 lines of near-duplicate logic after K1/K7 extractions (validate → ogrinfo → ogr2ogr → rename_reserved_columns → DBF detect → post-process → archive). Blocker is the `_apply_reupload_swap` atomic-swap dance.

**What the code shows now:**
- `ingest_file` at `backend/app/ingest/tasks.py:523` (1-line drift from handoff's 522). Total length: 232 lines (523-754).
- `reupload_file` at `backend/app/ingest/tasks.py:1106` (3-line drift from handoff's 1109). Total length: 223 lines (1106-1328).
- `_apply_reupload_swap` at `backend/app/ingest/tasks.py:990`. The atomic swap dance (`RENAME {live}→{live}_old`, `RENAME {staging}→{live}`, `DROP {live}_old`) is still present at lines 1028-1038 with `SET LOCAL lock_timeout = '5s'` and the edge-case check for `live_exists`.
- Shared pipeline steps confirmed in both functions:
  1. `resolve_file_path` (ingest: 560 / reupload: 1158)
  2. `_validate_upload_file_safety` (ingest: 564 / reupload: 1162)
  3. `run_ogrinfo` (ingest: 586 / reupload: 1176)
  4. `run_ogr2ogr` (ingest: 643 / reupload: 1196)
  5. `rename_reserved_columns` + warning (ingest: 659 / reupload: 1209)
  6. DBF collision detect (ingest: 667-688 / reupload: 1216-1235)
  7. Post-process (`ensure_geom_column` / `clip_to_mercator_bounds` / `add_4326_column` / `grant_reader_access`): `ingest_file` delegates this to `_finalize_ingest` at `tasks.py:351` which calls them at 391/393/403/404/407; `reupload_file` inlines them at 1239-1242.
  8. `extract_metadata` + `get_sample_values` (ingest: via `_finalize_ingest` at 410/429 / reupload: inline at 1245/1246)
  9. `_archive_original_file` (ingest: 730 / reupload: 1274 with `commit=False` for CLEANUP-4)
- The only real architectural difference: `ingest_file` delegates post-process to `_finalize_ingest(IngestContext(...))` which also creates the `Dataset`; `reupload_file` inlines post-process and then calls `_apply_reupload_swap` for the version/swap dance.

**Claim accuracy:** **Fully accurate.** The ~150-line duplication count is a reasonable estimate given there are 9 shared steps across 232+223 lines of function body. The `_apply_reupload_swap` blocker is still the key divergence point.

**Disposition:** **Promote to backlog (P3, large).** The proposed refactor extracts `_ingest_vector_into_staging(session, job, file_path, target_table) -> tuple[dict, bool]` covering steps 1-7. Both callers then run their own step-8+ paths (create_dataset vs apply_reupload_swap). Effort estimate of **4-6h** is still reasonable — possibly slightly high now that `_finalize_ingest` / `_apply_reupload_swap` are already extracted, but the atomic-swap coordination and test coverage for both paths legitimately puts it in the "dedicated plan, not drive-by" bucket.

### K4 — `regenerate_vrt` phase extraction

**What the handoff claims:** `regenerate_vrt` at `tasks.py:2098`, ~220 lines, 7 levels of nesting. Proposed extractions: `_build_vrt_to_temp`, `_validate_and_extract_vrt_metadata`, `_update_vrt_dataset_geometry`. Blocker: heavy mocking in `test_vrt_source_management_174.py::TestRegenerateVrtTask` → needs integration coverage against a real tiny VRT fixture.

**What the code shows now:**
- `regenerate_vrt` at `backend/app/ingest/tasks.py:2093` (5-line drift from handoff's 2098). Length: **231 lines** (2093-2323). Max indent: 29 columns, which works out to roughly 7 indent levels (function body → `async with` → `try` → normal flow → inner blocks) — matches the handoff's "7 levels of nesting" claim.
- The 15 documented steps are all still inline in a single function:
  - Step 5 "Build VRT to temp path" (2203-2211): `tempfile.mkdtemp()` + `asyncio.to_thread(build_vrt, ...)` — unchanged, still a candidate for `_build_vrt_to_temp(ordered_assets, vrt_type, resolution_strategy, tmp_dir) -> Path`.
  - Step 6/7 "Extract metadata" (2213-2216): `extract_raster_metadata` + CRS validation — still a candidate for `_validate_and_extract_vrt_metadata(vrt_path) -> dict`.
  - Step 13 "Update dataset footprint geometry" (2275-2283): `ST_GeomFromText` update — still a candidate for `_update_vrt_dataset_geometry(session, vrt_asset, metadata)`.
- No helper extractions have landed since 2026-04-10. `_build_vrt_to_temp` / `_validate_and_extract_vrt_metadata` / `_update_vrt_dataset_geometry` do not exist anywhere in the module.
- Integration-coverage blocker unchanged: `tests/test_vrt_source_management_174.py` still uses heavy mocking. No "real tiny VRT fixture" coverage has been added.

**Claim accuracy:** **Fully accurate.** 231 lines vs the "~220 lines" claim is effectively unchanged (the handoff itself called it "~220"). Blocker note ("needs integration coverage against a real tiny VRT fixture; pair with K3-PRE follow-up") is still correct.

**Disposition:** **Promote to backlog (P3, large).** Effort estimate of **3-4h plus test coverage** is unchanged. Blocker note about needing integration coverage should be preserved in the backlog entry.

### K6 — `CommitRequest` discriminated union

**What the handoff claims:** `CommitRequest` at `schemas.py:~60` carrying 12 optional fields across vector (`srid_override`, `layer_name`, `x/y/geom_column`), raster (`compression`, `resampling`, `nodata_override`), and service auth (`token`). Blocker is API contract change requiring frontend + OpenAPI + external-consumer coordination and a deprecation window.

**What the code shows now:**
- `CommitRequest` at `backend/app/ingest/schemas.py:97` (37-line drift from handoff's "~60" — this line number was approximate and the drift came from the TYPE-2/TYPE-3 structured warning additions earlier in the file).
- 1 required field: `title`
- 13 optional fields (handoff said 12; the discrepancy is either the handoff rounding or `summary` / `visibility` being classified as "generic" and excluded from the count):
  - **Generic (4):** `summary`, `visibility`, `temporal_start`, `temporal_end`
  - **Vector (5):** `srid_override`, `layer_name`, `x_column`, `y_column`, `geom_column`
  - **Raster (3):** `compression`, `resampling`, `nodata_override`
  - **Service auth (1):** `token`
- Field descriptions explicitly call out the category ("CSV/Excel only", "Raster only: ...", "Multi-layer source only", etc.) — underscoring that the applicability rules live in prose, not in the schema.
- No partial migration has landed: there is no `VectorCommitRequest`, `RasterCommitRequest`, or `ServiceCommitRequest` class anywhere. The handoff's proposed 3-way split is still the right shape.

**Claim accuracy:** **Fully accurate.** The "12 optional fields" count is off by one (actually 13, if you count `summary` + `visibility` as commit-time metadata) but the underlying "union of every possible commit-time metadata" structural complaint is exactly as described. The mix of vector/raster/service auth fields is intact.

**Disposition:** **Promote to backlog (P3, API contract change).** API contract blocker is unchanged — the router still accepts a single shape, the frontend still serializes to it, and any external consumer of `POST /ingest/commit/{job_id}` would need coordinated updates + deprecation window. Effort estimate "medium backend + small frontend + coordination overhead" is unchanged.

### N6 — `get_sample_values` sparse-column observation

**What the handoff claims:** `get_sample_values` in `metadata.py` uses a CTE-batched single-query approach with `LIMIT :sample_size` (default 1000), which may under-sample sparse columns compared to the old per-column approach. Action: no action unless users complain; if they do, bump CTE `LIMIT :sample_size` from 1000 to 10000.

**What the code shows now:**
- `get_sample_values` at `backend/app/ingest/metadata.py:204`, default `sample_size: int = 1000` (line 208).
- CTE approach still in place (lines 269-274):
  ```python
  query = (
      f"WITH sampled AS ("
      f"  SELECT {select_cols} FROM {_qtable(table_name)} LIMIT :sample_size"
      f") "
      f"{union_sql}"
  )
  ```
- Each column branch is a `SELECT DISTINCT {col}::text FROM sampled WHERE {col} IS NOT NULL LIMIT 10` (lines 263-266), which means for a 99%-null column the distinct-count in a 1000-row base scan will effectively be ≤ 10 non-null values.
- No user complaints have been filed against `get_sample_values` since 2026-04-10 (grep of `docs-internal/` finds only the 4 audit docs that already describe this observation; no bug reports). `CHANGELOG.md` has no new `sample_values` / sparse-column fix entry.
- Docstring at lines 210-221 explicitly describes the behavior and flags it as replacing "the previous N+1 per-column query pattern (PERF-1)".

**Claim accuracy:** **Fully accurate.** CTE approach is unchanged. No user complaint trigger observed. The 1-line mitigation (`sample_size: int = 10000`) is still the correct fix if triggered — though note the side effect on the base scan width and RAM under extreme row counts.

**Disposition:** **Promote to backlog as observational note (P3).** Keep the "no action unless users complain" verdict intact. The backlog entry should make the 1-line fix discoverable (mention `app/ingest/metadata.py::get_sample_values` and the `sample_size` parameter) so a future maintainer doesn't need to re-trace the audit chain.

### TYPE-5 — `persistent_config.py` `cast(T, ...)` sites

**What the handoff claims:** 3 `cast(T, ...)` sites at `persistent_config.py:84, 88, 113`. Deferred by audit recommendation. Optional: switch to `TypeAdapter[T].validate_python(unwrapped)` for runtime shape validation.

**What the code shows now:**
- Site 1: `persistent_config.py:84` — `return cast(T, self._env_default_factory())` — inside `PersistentConfig.env_default` property. Unchanged.
- Site 2: `persistent_config.py:88` — `return cast(T, self._env_default_static)` — same property. Unchanged, and the preceding comment still documents why cast is used (None is a valid default for Optional settings like `ENABLED_WIDGETS = None`).
- Site 3: `persistent_config.py:113` — `effective = cast(T, unwrapped)` — inside `async def get(self, db)` after JSONB unwrap. Unchanged.
- `git log -- backend/app/persistent_config.py` shows the last commit to this file is `f6a7f96a` (the snapshot already described in the handoff). The env-audit commits `a6371f9f` and `56c59cfd` touched `app/config.py` and several consumers, not `app/persistent_config.py`. **Confirmed via `git log` and `git show --stat`.** The 3 cast sites are byte-for-byte unchanged from the handoff's observation.
- The `PersistentConfig` class is declared `Generic[T]` with `T = TypeVar("T")` (lines 62-63 context). This means `TypeAdapter[T].validate_python(unwrapped)` cannot work as a drop-in: `T` is an unbound TypeVar at class method resolution time, and `TypeAdapter` needs a concrete runtime type. A real migration would require either (a) reifying `T` by storing the type at `__init__` time (breaking change for every call site that constructs a `PersistentConfig`) or (b) accepting an explicit `adapter: TypeAdapter[T]` parameter on the constructor (same shape, different ergonomics).

**Claim accuracy:** **Fully accurate.** Sites unchanged. SecretStr migration did not touch them. The audit's "deferred" verdict is still correct because the `Generic[T]` → runtime-validation migration is not a drop-in — it's a class-signature change.

**Disposition:** **Promote to backlog with observational note (P3).** Recommend the backlog entry include a one-line note that the `Generic[T]` TypeVar makes `TypeAdapter[T].validate_python()` impractical without refactoring `PersistentConfig.__init__` to accept an explicit type adapter, so future maintainers understand why this stayed deferred despite the pattern elsewhere.

### Snapshot split — meta-item

**What the handoff claims:** Commit `f6a7f96a` should be split into 6-7 reviewable PRs before push.

**What the code shows now:**
- `git log origin/main` confirms `f6a7f96a` landed on `origin/main` (it is 20 commits behind `aa74d33e`, the current `origin/main` HEAD, and appears in the linear history).
- `git branch -r --contains f6a7f96a` returns `origin/main` → the snapshot is permanently merged.
- The split recommendation cannot be retroactively applied — the commit is already in the shipped history.

**Claim accuracy:** **N/A.** The recommendation was correct at the time but is now moot because the decision point has passed.

**Disposition:** **Close inline in HANDOFF-REMAINING.md.** No backlog entry. A one-line note under the "Snapshot-committed" section acknowledging the commit landed as a single push should be sufficient.

## Cross-Cutting Validation — "Done" Claims Spot Check

All "done" claims from the handoff verified intact:

| Claim | Expected location | Current location | Status |
|-------|-------------------|------------------|--------|
| `_defer_with_orphan_guard` helper | `ingest/service.py` | `service.py` (referenced from `defer_guard.py`) | Valid — new shared helper at `backend/app/jobs/defer_guard.py` per Theme H fix |
| `IngestContext` dataclass | `tasks.py:31` | `tasks.py:31` | Valid — unchanged |
| `_bind_task_log_context` with `**extra: object` | `tasks.py:156` | `tasks.py:157` (1-line drift) | Valid — `**extra: object` annotation in place |
| `create_vrt_job` | `service.py:346` | `service.py:350` (4-line drift) | Valid — service function extracted, router wrapper still thin |
| `GET /jobs/by-dataset/{id}` | `jobs/router.py:223` | `jobs/router.py:222` (1-line drift) | Valid — `get_job_status_by_dataset` endpoint present |
| CHANGELOG entries for A-G and B follow-ups | `CHANGELOG.md [Unreleased] Fixed` | Lines 51, 66 | Valid — both entries intact |
| `defer_guard.py` shared module | `backend/app/jobs/defer_guard.py` | Present (Theme H shipped in PR #21) | Valid |

None of the "done" claims have regressed.

## Environment Availability

**Skipped** — this is a code/docs/audit-review task with no external tool dependencies beyond `git` (available) and a text editor. No backlog entry creation requires tooling not already present.

## Validation Architecture

**Skipped for this quick task.** Quick tasks typically skip Nyquist validation per workflow norms, and this task performs no code changes — verification is strictly "did the file line up with the handoff's claims", which is a documentation-level check. If/when K2, K4, K6 get promoted from backlog into a real milestone plan, that plan will need its own validation architecture research pass.

## Effort Corrections

**None.** All handoff effort estimates still hold:

| ID | Handoff estimate | Revised estimate | Reason |
|----|------------------|------------------|--------|
| K2 | 4-6h (large) | **4-6h (unchanged)** | 232+223 line functions, ~150 lines near-duplicate, atomic-swap blocker unchanged |
| K4 | 3-4h (large) + test coverage | **3-4h + test coverage (unchanged)** | 231 lines, 7 indent levels, integration-fixture blocker unchanged |
| K6 | Medium backend + small frontend + coordination | **Unchanged** | 13-field union still intact, API contract blocker unchanged |
| N6 | XSmall (1-line if triggered) | **XSmall (1-line if triggered, unchanged)** | No user complaints; 1-line `sample_size=10000` bump is still the right fix |
| TYPE-5 | Small if attempted (but deferred) | **Unchanged — still deferred** | 3 sites unchanged; `Generic[T]` TypeVar makes runtime validation non-trivial |

## Blocker / Dependency Updates

**None.** Every blocker note in the handoff is still accurate:

- **K2:** `_apply_reupload_swap` atomic-swap dance still diverges the two pipelines at the post-process / commit boundary. No intervening refactor has changed this.
- **K4:** raster VRT tests still use heavy mocking (`test_vrt_source_management_174.py::TestRegenerateVrtTask`). No "real tiny VRT fixture" integration coverage has been added. Pair-with-K3-PRE note still applies.
- **K6:** API contract change blocker unchanged. No coordinated frontend/backend migration has landed.
- **N6:** no user reports filed. "No action unless users complain" verdict unchanged.
- **TYPE-5:** the `Generic[T]` → runtime-validation migration is still a non-drop-in change (either reify `T` at construction or accept an explicit `TypeAdapter[T]` parameter). SecretStr migration on `config.py` did not touch this file. Deferred verdict unchanged.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | "No user complaints filed for N6 sparse-column sampling since 2026-04-10" is based on grep of `docs-internal/` and `CHANGELOG.md`. A complaint could exist in an issue tracker or Slack I can't see. | N6 finding | If a complaint exists, N6 should promote as actionable (1-line fix), not observational. Re-classify on planner's discretion if a new signal surfaces. |
| A2 | The handoff's "~150 lines of near-duplicate logic" count for K2 is rounded. Actual duplication is "9 shared pipeline steps spanning 232+223 total function lines" — the line-exact duplicate count depends on where you draw the boundary (e.g., whether `_finalize_ingest`-delegated steps count toward `ingest_file`'s duplication or not). | K2 finding | None — this is just a framing note. Effort estimate holds either way. |

## Open Questions

1. **Should the N6 backlog entry be observational or actionable?**
   - What we know: no complaints have surfaced in 1 day since 2026-04-10. The 1-line fix is trivial and low-risk (bump `sample_size` default from 1000 to 10000 in `metadata.py:208`).
   - What's unclear: whether 1 day is enough signal to hold the "no action" verdict, vs. just doing the low-risk fix proactively.
   - Recommendation: **Keep as observational (default).** The handoff's own verdict was explicit, and there's no new data. If the backlog sits untouched for another month and no complaints arise, consider closing entirely. If a complaint lands, promote to actionable.

2. **Should TYPE-5 be "deferred with note" or "won't fix"?**
   - What we know: the `Generic[T]` constraint is a real obstacle. The cast sites are stable. The rest of the codebase's `TypeAdapter` pattern doesn't apply cleanly here.
   - What's unclear: whether future Pydantic work on `persistent_config.py` might naturally land the refactor (at which point TYPE-5 closes itself), or whether it'll stay in this shape forever.
   - Recommendation: **"Deferred with observational note"** — matches the CONTEXT.md default. Re-evaluate only if `PersistentConfig`'s signature is being changed for another reason.

## Sources

### Primary (HIGH confidence) — working tree evidence
- `backend/app/ingest/tasks.py` — direct read of `ingest_file`, `reupload_file`, `regenerate_vrt`, `_apply_reupload_swap`, `_finalize_ingest`, `_bind_task_log_context`.
- `backend/app/ingest/schemas.py` — direct read of `CommitRequest` at line 97.
- `backend/app/ingest/metadata.py` — direct read of `get_sample_values` at line 204.
- `backend/app/persistent_config.py` — direct read of all 3 `cast(T, ...)` sites at lines 84, 88, 113.
- `backend/app/ingest/service.py` — direct read of `create_vrt_job` at line 350.
- `backend/app/jobs/router.py` — direct read of `GET /by-dataset/{dataset_id}` at line 222.
- `CHANGELOG.md` — direct grep of "Post-impl audit 2026-04-10" entries at lines 51 and 66.
- `git log --oneline -- backend/app/persistent_config.py` — confirms last touch was `f6a7f96a` (the snapshot).
- `git log` / `git show --stat a6371f9f 56c59cfd` — confirms SecretStr commits touched `config.py`, not `persistent_config.py`.
- `git log origin/main -1` — confirms `aa74d33e` is HEAD of `origin/main`, and `f6a7f96a` is in its history.

### Secondary — handoff + audit trail (docs)
- `docs-internal/audits/post-impl-20260410-HANDOFF-REMAINING.md` — source of the claims being validated.
- `.planning/quick/260411-a62-review-the-remaining-items-in-docs-inter/260411-a62-CONTEXT.md` — user decisions.
- `CHANGELOG.md` — verification of shipped "done" items.

### Tertiary — not used
- No Context7, WebSearch, or external sources were consulted. This is a self-contained validation against the local working tree.

## Metadata

**Confidence breakdown:**
- K2 validation: **HIGH** — direct file reads, line counts verified.
- K4 validation: **HIGH** — direct file read, line/indent count measured.
- K6 validation: **HIGH** — direct file read, field-by-field enumeration.
- N6 validation: **HIGH** (code state) + **MEDIUM** (no-complaint claim depends on grep scope — see Assumption A1).
- TYPE-5 validation: **HIGH** — direct file read + git log verification of non-touching commits.
- Snapshot-split N/A: **HIGH** — git branch/log verification.

**Research date:** 2026-04-11
**Valid until:** 2026-04-18 (1 week — all findings are working-tree line-number-specific and will drift as soon as anyone touches `tasks.py` / `schemas.py` / `metadata.py` / `persistent_config.py`).

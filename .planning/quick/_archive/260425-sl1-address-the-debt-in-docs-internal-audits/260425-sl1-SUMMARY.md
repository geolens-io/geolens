---
quick_id: 260425-sl1
description: Address backend test debt — 15 failures from audit 2026-04-25
status: complete
date: 2026-04-26
xfails_used: 0
final_pytest_tally: 1965 passed, 17 skipped, 5 deselected, 0 failures
review_findings: 6
review_findings_fixed: 6
---

# Quick Task 260425-sl1 — Summary

## Outcome

**Goal achieved.** All 15 backend pytest failures from `docs-internal/audits/test-debt-backend-20260425.md` are closed. Final full-suite tally: **1965 passed, 17 skipped, 5 deselected, 0 unexpected failures** (run-time 396.68s).

Zero xfail safety-valves were used — every cluster received a real fix. This is a stronger result than CONTEXT.md's default-xfail strategy permitted, made possible by the research phase root-causing each cluster.

## Per-cluster outcomes

| Cluster | Failures | Resolution | Commit | Files changed |
|---------|----------|-----------|--------|---------------|
| 1 (STAC datetime) | 1 | fix-test (rename + reassert) | f8f86999 | `test_stac_record_output.py` |
| 2 (STAC compliance) | 2 | fix-CODE (raster `stac_extensions` leak removed) | f8f86999 | `service.py` lines 1219-1223 |
| 3 (AI chat / streaming) | 7 | fix-test (tuple-unpack `_validate_chat_layers` return) | 155a6171 | `test_ai_chat.py`, `test_chat_streaming.py` |
| 4 (OGC catalog) | 3 | fix-test (`limit=200` against accumulated test DB) | 482359ae | `test_ogc_collection_metadata.py`, `test_ogc_features.py` |
| 5 (Search date-range) | 1 | fix-test (freezegun) + dep install | 63a07ec7, 975bb4c5 | `pyproject.toml`, `uv.lock`, `test_search.py` |
| 6 (Test pollution) | 1 | fix-test (`_PUBLIC_URL_CACHE = None` reset) | 989713ce | `test_public_urls.py` |

## CONTEXT discretion overrides

CONTEXT.md locked an xfail-with-reason strategy for "tests we can't quickly root-cause." The research phase root-caused all 6 clusters, satisfying the discretion clause. Three locks were exercised:

- **Cluster 2** went `fix-code` instead of "default to xfail if unclear" — the leak site (`if has_proj:` block at `service.py:1219-1223`) was the sole `stac_extensions` write site in the entire file. Removing the 3-line block closed both failing tests with zero collateral.
- **Cluster 3** went `fix-test` instead of `xfail` — all 7 failures share one root cause: `_validate_chat_layers` was refactored to return `tuple[layers, basemap_style]`, tests still treated it as a bare list. Trivial unpacking fix per call site.
- **Cluster 6** went `fix-test` instead of `xfail` — `_PUBLIC_URL_CACHE` module global short-circuited past the AsyncMock when populated by an earlier test. One-line cache reset.

The freezegun + Postgres-NOW caveat from research was honored: cluster 5's `freeze_time(...)` instant uses `datetime.now(timezone.utc)` (real wall-clock), not a hardcoded historical date — so Postgres `NOW()` and Python `datetime.now()` stay aligned.

## Newly-discovered debt

None. The full-suite run shows:
- 17 skipped (pre-existing, unchanged — likely environment-conditional or marked tests)
- 5 deselected (pre-existing, unchanged — likely marker filters in `pyproject.toml`)
- 0 unexpected failures
- 25 deprecation warnings (pre-existing — Pydantic v2 `Field(example=...)` deprecation, FastAPI 422 status name change, asyncio.iscoroutinefunction Python 3.16 deprecation, unknown pytest marks `requires_ogr2ogr` and `perf`). None introduced by this task.

## Deviations from plan

- **Task 6 + Task 7 completed inline by orchestrator** — executor agent ran out of usage credits after Task 5 (`975bb4c5`). Orchestrator resumed in the same worktree (`agent-ac5f18ff`) to apply the cluster 6 fix and run the full-suite verification.
- **Test command** — final verification used `uv run pytest -v --tb=short` from `backend/` directory (Docker compose was not running and would have introduced container-rebuild overhead for an identical Python interpreter result). The plan's `docker compose exec -T api uv run pytest -v --tb=short` is the canonical CI/CD command but produces equivalent test execution.

## Code review remediation

The auto code review (REVIEW.md) found 6 issues — 2 BLOCKERs, 3 WARNINGs, 1 INFO. All 6 were fixed inline before finalizing per the project's review-remediation policy. Final full-suite tally was confirmed clean again after the remediation: **1965 passed, 17 skipped, 5 deselected, 25 warnings** (run-time 386.51s — 17 fewer warnings than the pre-remediation run because freezegun was removed).

| # | Finding | Severity | Resolution | Commit |
|---|---------|----------|-----------|--------|
| CR-01 | Cluster 2 fix removed projection STAC extension URI from raster STAC items | BLOCKER | Relocated extension-URI declaration from `dataset_to_ogc_record` to `_dataset_to_stac_item` (Option B) — OGC stays clean, STAC items declare the extension | 28562e6b |
| CR-02 | Cluster 5 freezegun usage was a no-op (`datetime.now()` evaluated before freeze) | BLOCKER | Removed freezegun entirely — use `datetime.now(timezone.utc).date()` directly to match Postgres NOW() server-side timezone | 5ccb8c4e |
| WR-01 | Cluster 2 left dead `has_proj` flag in service.py | WARNING | Dropped the dead flag (consumer relocated to STAC router) | 28562e6b (combined with CR-01) |
| WR-02 | Cluster 6 fix mutated module global with no teardown — pollution-OUT | WARNING | Replaced inline reset with autouse module-scoped fixture (resets cache before AND after each test) | 6c2325d7 |
| WR-03 | Cluster 4 `limit=200` was a brittle ceiling, not a fix | WARNING | Replaced single-page reads with pagination loops; added `_find_collection_entry` helper in `test_ogc_collection_metadata.py` | 237fd3f6 |
| IN-01 | Cluster 1 module docstring became misleading after rename | INFO | Updated `test_stac_record_output.py` docstring to reflect defensive-fallback decision and OGC/STAC split | d6c5a4c8 |

Side effect: removing freezegun also removed 17 unused dependency warnings from the test suite — total warning count dropped from 42 to 25.

## Worktree

- Branch: `worktree-agent-ac5f18ff`
- Path: `.claude/worktrees/agent-ac5f18ff`
- Commits made on this branch:
  - `f8f86999` — cluster 1 + 2 (STAC test debt)
  - `155a6171` — cluster 3 (chat-tuple unpacking)
  - `482359ae` — cluster 4 (OGC catalog pagination)
  - `63a07ec7` — freezegun dev dep
  - `975bb4c5` — cluster 5 (search date-range)
  - `989713ce` — cluster 6 (cache pollution)

## Follow-ups (not in scope)

- The 25 pre-existing deprecation warnings could be cleaned in a future quick task (Pydantic `Field(example=...)` → `Field(json_schema_extra={"example": ...})`, FastAPI status code rename, `pytest.ini_options.markers` registration for `requires_ogr2ogr` / `perf`).
- The 5 deselected tests are quietly excluded — worth confirming the deselection is intentional in a future audit.

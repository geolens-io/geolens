# Phase 214 — Deferred Items

Pre-existing issues discovered during execution that are out of scope per the executor scope boundary (only auto-fix issues directly caused by the current task's changes).

## 2026-04-27 — Plan 01 execution

### Pre-existing flaky test: `tests/test_collections.py::TestUpdateDeleteCollection::test_update_collection`

- **Discovered during:** Plan 214-01 full-suite regression run (after Task 01-03 commit `538a933b`).
- **Failure:** `sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called; can't call await_only() here. Was IO attempted in an unexpected place?`
- **Location:** `backend/tests/test_collections.py:168` — `await client.patch(f"/catalog/collections/{coll_id}", ...)` after a successful POST creating the collection.
- **Reproduction:** Fails consistently when run alone (`uv run pytest tests/test_collections.py::TestUpdateDeleteCollection::test_update_collection`) and when run with the full suite.
- **Why deferred:** Phase 214 Plan 01 is purely additive — `core/identity.py` is a new file, `DefaultIdentityExtension` and `get_identity_extension()` add new symbols only, and no production caller imports them yet. The failure is in HTTP integration code (PATCH `/catalog/collections/{id}`) running through SQLAlchemy async/greenlet machinery that does not touch any of Plan 01's files.
- **Suite state after Plan 01:** `1988 passed, 1 failed, 17 skipped, 5 deselected` — the 3 new `TestGetIdentityExtension` tests added by Task 01-03 all pass.
- **Note on baseline:** The plan claims a `≥1999 passing` baseline; on the executing machine the actual pass count was `1988` before Plan 01 (and `1991` after, accounting for the 3 new tests passing — minus the 1 unrelated failure). The discrepancy is environment-specific (skip/deselected categories vary by machine config), but the conclusion (Plan 01 introduces zero behavior change) is unaffected: the same single test fails before and after Plan 01's edits because Plan 01 is purely additive scaffolding with no production caller.
- **Action:** Owner should investigate `test_collections.py::test_update_collection` separately as a stability issue. Phase 214 Plan 01 is unaffected and does not need to fix it.

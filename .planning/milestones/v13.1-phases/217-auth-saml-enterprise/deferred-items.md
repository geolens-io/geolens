# Phase 217 — Deferred / Out-of-Scope Items

Tracked during Plan 05 verification gate execution; pre-existing failures
unrelated to Phase 217 work. Documented here so the orchestrator and
future phases have visibility, but NOT auto-fixed (executor scope-
boundary policy: only fix issues directly caused by current task changes).

## tests/test_collections.py::TestUpdateDeleteCollection::test_update_collection — pre-existing baseline failure

**Status:** PRE-EXISTING (verified on parent repo `main` branch; same failure mode without any Phase 217 changes)

**Failure mode:** `sqlalchemy.exc.MissingGreenlet: greenlet_spawn has not been called` during `await client.patch(...)` on a collection update endpoint.

**Why pre-existing:** Reproduced on `/Users/ishiland/Code/geolens` (parent repo, on `main`, no Phase 217 patches applied) — same single-test failure. Phase 217 did not introduce or change anything in `app.modules.catalog.collections`. Likely cause: an earlier change in catalog/collections introduced a sync DB call inside an async path; orthogonal to SAML overlay work.

**Recommended follow-up:** File as a separate quick task or `/gsd-quick` issue. Phase 217's verification gate notes the failure as out-of-scope but otherwise green; SAML-specific surface (test_saml_overlay.py + the 5 ROADMAP SC-mapped tests) is fully passing.

## tests/test_cli_round_trip.py — collection error (`ModuleNotFoundError: keyring`)

**Status:** PRE-EXISTING (Plan 03 SUMMARY documented this same issue under "Issues Encountered"; same root cause: the worktree backend venv doesn't have the CLI's `keyring` dep installed because `cli/` is a separate package not pulled in by `backend/pyproject.toml`).

**Workaround:** `--ignore=tests/test_cli_round_trip.py` in pytest invocations (mirrors Plan 03's pattern).

**Recommended follow-up:** Either install `cli/` editable into the backend venv as part of CI setup, OR mark `test_cli_round_trip.py` with `@pytest.importorskip("keyring")` at collection time. Out of Phase 217 scope.

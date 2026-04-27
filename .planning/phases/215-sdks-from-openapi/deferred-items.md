# Phase 215 — Deferred Items

Items discovered during Phase 215 execution that are out-of-scope for the
phase's must-haves and were not fixed.

## actionlint warning on e2e-test job (pre-existing)

- **Symptom:** `actionlint .github/workflows/ci.yml` reports
  `constant expression "false" in condition. remove the if: section [if-cond]`
  at line 339 (`if: false` on the `e2e-test` job).
- **Origin:** Commit `42712a19` (2026-04-20), 7 days before Phase 215 started.
  The e2e job is intentionally disabled to save GitHub Actions minutes; the
  job is run locally via `npx playwright test` per the inline comment.
- **Why deferred:** Pre-existing finding unrelated to Phase 215's changes
  (sdks-check job + publish-sdks.yml are both actionlint-clean — exit 0
  on `publish-sdks.yml` alone). Per executor scope-boundary rule, Phase 215
  does not auto-fix pre-existing issues in unrelated files.
- **Suggested fix when revisited:** Replace `if: false` with a workflow_dispatch
  trigger and a `manual` input, or restructure into a separate workflow file
  triggered only on `workflow_dispatch`. Coordinate with whoever maintains the
  e2e-test policy.

## test_collections.py::test_update_collection (pre-existing flake)

- **Symptom:** `tests/test_collections.py::TestUpdateDeleteCollection::test_update_collection`
  fails with a `MissingGreenlet` exception during a starlette TaskGroup.
- **Origin:** Phase 214's verification gate (Plan 214-04 SUMMARY) documented
  this as a "pre-existing flake first logged in Plan 01's deferred-items.md
  and confirmed unrelated to identity work in Plan 03 — out of scope". Phase
  215 inherits the same baseline; we made no changes to `test_collections.py`
  or `app/modules/catalog/collections/`.
- **Why deferred:** Pre-existing. Not introduced by Phase 215. Documented in
  Phase 214's deferred items, carried forward unchanged. Triage is a
  separate concern (likely a sqlalchemy-async fixture-teardown bug).
- **Container baseline impact:** The full `pytest -m 'not perf'` run still
  reports 2001 passed (the post-Phase-214 floor) plus 6 skipped (1 new skip
  from Phase 215's SDK round-trip module guarded on host-only paths) and
  1 failed (this flake). The 2001-pass count meets the ≥1988 floor.

## Pydantic v2 deprecation warnings (pre-existing)

- **Symptom:** ~15 `PydanticDeprecatedSince20` warnings about
  `Field(example=...)` usage in `app/modules/{embed_tokens,catalog/layers}/schemas.py`.
- **Origin:** Pre-existing. Documented in Phase 214's notes.
- **Why deferred:** Out of scope for Phase 215; would require touching
  multiple unrelated schema files. Tracked for a future code-quality pass.

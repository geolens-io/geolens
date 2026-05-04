---
phase: 230
plan: 04
type: execute
wave: 3
depends_on:
  - 230-02
  - 230-03
files_modified:
  - backend/tests/test_layering.py
autonomous: true
requirements:
  - CATPORT-02
  - CATPORT-04
  - CATPORT-05
must_haves:
  truths:
    - test_no_catalog_imports_processing exists and passes
    - Negative-control proof confirms the guard fails on a forbidden top-of-file import and the injected import is reverted
    - Phase verification artifact records passed status or concrete gaps
---

<objective>
Seal the Phase 230 invariant in CI and verify the completed migration.
</objective>

<tasks>
<task type="auto">
  <name>Add catalog-to-processing architecture guard</name>
  <files>backend/tests/test_layering.py</files>
  <action>Add test_no_catalog_imports_processing mirroring test_no_processing_imports_catalog. The guard must grep backend/app/modules/catalog/ for top-of-file imports from app.processing or backend.app.processing and fail with offending lines. Document that function-local imports are permitted only as deferred boundaries.</action>
  <verify>pytest backend/tests/test_layering.py::test_no_catalog_imports_processing</verify>
  <done>Architecture guard passes on the migrated codebase.</done>
</task>

<task type="auto">
  <name>Run negative control and phase checks</name>
  <action>Temporarily add a forbidden top-of-file processing import to a catalog file, confirm pytest backend/tests/test_layering.py::test_no_catalog_imports_processing fails and reports the line, then revert the injected line. Run grep and focused tests. Write 230-VERIFICATION.md with status.</action>
  <verify>grep, architecture test, negative-control output, focused tests</verify>
  <done>230-VERIFICATION.md exists with passed status or exact gaps.</done>
</task>
</tasks>

<verification>
pytest backend/tests/test_layering.py::test_no_catalog_imports_processing
git grep -n -E '^(from|import) (backend\.)?app\.processing' -- backend/app/modules/catalog/
</verification>


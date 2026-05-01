---
phase: 225
plan: 04
type: execute
wave: 3
depends_on:
  - 225-02
  - 225-03a
  - 225-03b
files_modified:
  - backend/tests/test_layering.py
  - backend/tests/test_processing_port.py
autonomous: false
requirements:
  - PROCESS-04
  - PROCESS-05
threat_model:
  block: false
  rationale: "Refactor-only — no new attack surface introduced. New tests are static-analysis (architecture guard) and unit-level seam proof. They do not change application behavior, do not introduce new endpoints, do not change auth/authz semantics. The negative-control verification temporarily reintroduces a forbidden import to prove the guard works; this is a one-time human action that is reverted before commit."

must_haves:
  truths:
    - "test_no_processing_imports_catalog architecture-guard test exists and passes when applied to the post-Plan-03 codebase"
    - "Negative-control verification proves the guard fails CI when a forbidden import is reintroduced (PROCESS-04 binding requirement)"
    - "FakeProcessingPort seam test exists at backend/tests/test_processing_port.py and passes — proves the AI service seam works in isolation (PROCESS-03 / SC#5)"
    - "test_layering.py module docstring updated to credit Phase 225 (D-25)"
    - "Full backend test suite remains green at the new baseline (2036/2036 + 2 new tests OR 2036+ if minor adjustments to existing tests were needed)"
    - "alembic check returns no new operations (D-29 verification gate — refactor-only)"
    - "ruff check passes clean across the entire backend tree"
    - "Phase 214 IDENT-01 + Phase 224 DECOUPLE-04 + all other architecture guards continue to pass"
    - "If OQ-4 Outcome B was chosen in Plan 03a/03b, the architecture guard includes the documented :!backend/app/processing/ingest/tasks_raster.py pathspec exclusion"
    - "Implements CONTEXT.md decisions: D-22 (one new architecture-guard test test_no_processing_imports_catalog), D-23 (strict zero-hit, no allowlist for processing/* — or single OQ-4 Outcome B exception), D-24 (reuses @pytest.mark.architecture marker — no new marker), D-25 (update test_layering.py module docstring crediting Phase 225), D-26 (negative-control verification — temporarily reintroduce forbidden import, confirm guard fails, revert), D-27 (focused FakeProcessingPort unit test in backend/tests/test_processing_port.py), D-28 (no runtime conformance test isinstance check), D-30 (acceptance gate = 2036/2036 + ruff + arch-guard + alembic), D-32 (Phase 226 sequencing — does NOT touch llm_loop.py:117,132 or service.py:387-398)"
  artifacts:
    - path: "backend/tests/test_layering.py"
      provides: "test_no_processing_imports_catalog architecture-guard test method + module docstring crediting Phase 225"
      contains: "def test_no_processing_imports_catalog"
    - path: "backend/tests/test_processing_port.py"
      provides: "FakeProcessingPort + seam unit test for AI service (D-27 / SC#5)"
      contains: "class FakeProcessingPort"
  key_links:
    - from: "backend/tests/test_layering.py"
      to: "git grep on backend/app/processing/"
      via: "subprocess.run with regex pattern ^\\s*(from|import)\\s+app\\.modules\\.catalog"
      pattern: "git\\s+grep"
    - from: "backend/tests/test_processing_port.py"
      to: "processing/ai/service.py service-layer function"
      via: "explicit port=FakeProcessingPort() kwarg (D-15 seam)"
      pattern: "port=FakeProcessingPort"
---

<objective>
Add the **architecture-guard test** (`test_no_processing_imports_catalog`) to `backend/tests/test_layering.py` and the **FakeProcessingPort seam test** (new file `backend/tests/test_processing_port.py`). Both tests seal Phase 225's invariants in CI.

The architecture-guard test (D-22 / PROCESS-04) **MUST land last** because it fails until cross-domain catalog imports are gone (Plans 02 + 03 cleared them). Adding it earlier would break CI immediately.

The FakeProcessingPort test (D-27 / SC#5) **MUST land in this phase** because ROADMAP §225 SC#5 binds: "AI features consume catalog data exclusively through the Protocol — verifiable by the same grep guard plus a focused unit test that swaps in a fake `ProcessingPort`."

Per RESEARCH.md §Migration Sequencing, this plan is the **verification gate**:
1. Phase-wide grep returns zero hits (or 1 allowlisted hit per OQ-4 Outcome B from Plan 03a/03b)
2. `pytest tests/test_layering.py -m architecture` all pass (including the new guard)
3. `alembic check` clean
4. `ruff check` clean
5. `pytest tests/test_processing_port.py -x` passes
6. **Negative-control verification (D-26)**: temporarily reintroduce a forbidden import in `processing/embeddings/backfill.py`, run the new test, confirm it fails with the offending line, revert. This is a one-time human action documented in the plan output.
7. Full pytest run: `2036 passed` (or new baseline including the 2 added tests)

This plan has a `checkpoint:human-verify` task for the D-26 negative-control verification — an unavoidable manual proof step.

Output: 1 modified test file (`test_layering.py`), 1 new test file (`test_processing_port.py`).
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/225-processing-port-protocol-cycle-inversion/225-CONTEXT.md
@.planning/phases/225-processing-port-protocol-cycle-inversion/225-RESEARCH.md
@.planning/phases/225-processing-port-protocol-cycle-inversion/225-PATTERNS.md
@.planning/phases/225-processing-port-protocol-cycle-inversion/225-VALIDATION.md
@.planning/phases/225-processing-port-protocol-cycle-inversion/225-02-SUMMARY.md
@.planning/phases/225-processing-port-protocol-cycle-inversion/225-03a-SUMMARY.md
@.planning/phases/225-processing-port-protocol-cycle-inversion/225-03b-SUMMARY.md
@backend/app/core/processing_port.py
@backend/app/platform/extensions/__init__.py
@backend/app/platform/extensions/defaults.py
@backend/tests/test_layering.py
@backend/tests/conftest.py
@backend/app/processing/ai/service.py
@backend/app/processing/embeddings/backfill.py

<interfaces>
<!-- Plans 01-03 produced these. Plan 04 verifies them. -->

After Plan 03a/03b, the codebase satisfies:
- core/processing_port.py declares ProcessingPort + companion Protocols
- platform/extensions/defaults.py implements DefaultProcessingPort
- platform/extensions/__init__.py exposes get_processing_port()
- 8 module-level + ~24 function-scope catalog imports in processing/* are gone
- (Possibly) `tasks_raster.py:143` retains a single allowlisted import (per OQ-4 Outcome B in Plan 03a/03b SUMMARY — read 225-03b-SUMMARY.md before this plan to determine which outcome was chosen)

From PATTERNS.md §5 and RESEARCH.md §Architecture Guard Specification — the test invocation:

```python
@pytest.mark.architecture
def test_no_processing_imports_catalog() -> None:
    """Phase 225 PROCESS-02/04: backend/app/processing/ must not import from app.modules.catalog.*.

    All catalog access must go through ProcessingPort (app.core.processing_port).
    Strict zero-hit — no allowlist for processing/* (D-23).

    Excluded paths:
      - backend/tests/ — test fixtures construct catalog ORM objects directly,
        structurally satisfying the Protocols (D-23 pathspec exclusion).

    Maps to Phase 225 ROADMAP SC#2 / SC#3. Inlines former Phase 999.11
    (added in same phase as the inversion — guard before inversion fails CI).
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")
    if not _has_pathspec_magic():
        pytest.skip(
            "git < 2.13 lacks `:!` pathspec exclusion; cannot enforce "
            "Phase 225 PROCESS-04 invariant via grep-based guard"
        )

    result = subprocess.run(
        [
            "git", "grep", "-n", "-E",
            r"^\s*(from|import)\s+app\.modules\.catalog",
            "--",
            "backend/app/processing/",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0:
        pytest.fail(
            "Phase 225 PROCESS-02/04 invariant violated: backend/app/processing/ "
            "contains direct imports from app.modules.catalog.*. All catalog access "
            "must go through ProcessingPort (app.core.processing_port). "
            f"Offending lines:\n{result.stdout}"
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )
```

If Plan 03a/03b chose OQ-4 Outcome B (kept `tasks_raster.py:143` Dataset import as exception), modify the `subprocess.run` args to include the exclusion:
```python
[
    "git", "grep", "-n", "-E",
    r"^\s*(from|import)\s+app\.modules\.catalog",
    "--",
    "backend/app/processing/",
    ":!backend/app/processing/ingest/tasks_raster.py",
],
```

From PATTERNS.md §4 + RESEARCH.md §Test Seam Specification — the FakeProcessingPort + seam test:

```python
"""Unit test for the ProcessingPort seam (Phase 225 D-27 / PROCESS-03).

Constructs a minimal FakeProcessingPort with canned return values and
passes it to a service-layer function (e.g., generate_map_from_prompt or
_build_map_spec_and_persist) to verify the seam is genuinely testable
in isolation without a database or LLM.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


class FakeProcessingPort:
    """Minimal stub implementing the ProcessingPort surface with canned returns."""

    def __init__(self):
        _dataset_id = uuid.uuid4()
        self._dataset = MagicMock()
        self._dataset.id = _dataset_id
        self._dataset.table_name = "test_dataset_table"
        self._dataset.geometry_type = "Polygon"
        self._dataset.feature_count = 100
        self._dataset.srid = 4326
        self._dataset.column_info = [{"name": "area", "type": "float"}]
        self._dataset.sample_values = {"area": [1.0, 2.0]}
        self._dataset.record = MagicMock()
        self._dataset.record.title = "Test Dataset"
        self._dataset.record.summary = "A test dataset"
        self._dataset.record.keywords = []
        self._dataset.record.spatial_extent = None

        self._map = MagicMock()
        self._map.id = uuid.uuid4()
        self._map.name = "Test Map"
        self._dataset_id = str(_dataset_id)

    async def search_datasets(self, session, user, user_roles, filters):
        return ([self._dataset], 1)

    def apply_visibility_filter(self, stmt, user, user_roles, record_cls, grant_cls=None):
        return stmt  # No-op

    async def check_dataset_access(self, session, dataset, dataset_id, user, *, user_roles=None):
        return user_roles or set()

    async def get_user_roles(self, session, user):
        return {"viewer"}

    async def get_dataset(self, session, dataset_id):
        if str(dataset_id) == self._dataset_id:
            return self._dataset
        return None

    async def get_record(self, session, record_id):
        return self._dataset.record

    async def get_column_stats(self, session, table_name, column_name, **kwargs):
        return {"min": 0.0, "max": 100.0, "count": 100, "mean": 50.0, "quantiles": [25.0, 50.0, 75.0]}

    async def get_distinct_values(self, session, table_name, column_name, limit=100, **kwargs):
        return ["A", "B", "C"]

    def extract_bbox(self, dataset):
        return [-74.0, 40.7, -73.9, 40.8]

    async def create_dataset(self, session, table_name, title, created_by, **kwargs):
        return self._dataset

    async def create_map(self, session, name, description, created_by, notes=None):
        self._map.name = name
        return self._map

    async def update_map(self, session, map_id, **kwargs):
        return (self._map, [], None, None)

    def build_gdal_source(self, service_type, base_url, layer_name, **kwargs):
        return (f"{service_type}:{base_url}", layer_name)

    # Plan 02 Task 0 helpers
    def get_record_orm_class(self):
        return MagicMock  # Stand-in — tests don't construct real SQL with it
    def get_grant_orm_class(self):
        return MagicMock
    async def get_dataset_with_attributes(self, session, dataset_id):
        return self._dataset

    # OQ-3 helpers
    async def get_records_without_embeddings(self, session, *, force=False):
        return [self._dataset.record]
    async def get_datasets_meta_by_ids(self, session, ids):
        return [(self._dataset.id, self._dataset.table_name, self._dataset.geometry_type)]
    async def get_catalog_vocabulary(self, session):
        return ["test", "vocab"]
    async def get_related_keywords(self, session, dataset_id, limit=10):
        return ["related"]
    async def get_record_keyword_count(self, session, record_id):
        return 0
    async def get_attribute_metadata(self, session, dataset_id):
        return []
    async def get_dataset_version(self, session, dataset_id):
        return None
    def create_ingestion_result(self, **kwargs):
        result = MagicMock()
        for k, v in kwargs.items():
            setattr(result, k, v)
        return result

    # Any additional helpers added in Plan 03a/03b Task 0 — re-add here if missing
    # (e.g., get_dataset_orm_class, get_record_distribution_orm_class)
```

The seam test itself: choose ONE service-layer function in `processing/ai/service.py` that takes `port: ProcessingPort` (e.g., `_build_map_spec_and_persist` or a smaller helper). Mock LLM dependencies. Pass `port=FakeProcessingPort()`. Assert function returns / behaves correctly.

Simpler alternative (preferred): test that `port.search_datasets` and `port.create_map` are called with expected arguments when invoking the inner helper. Avoid full LLM mocking by testing the smallest seam-using function.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Append test_no_processing_imports_catalog architecture-guard test to backend/tests/test_layering.py + update module docstring</name>
  <files>backend/tests/test_layering.py</files>
  <read_first>
    - backend/tests/test_layering.py (entire file — read existing structure, helpers _has_git_metadata, _has_pathspec_magic, _git_grep, REPO_ROOT, current docstring at lines 1-36, line 421 test_no_log_action_calls_outside_audit_service to mirror, line 333 test_no_external_imports_of_dataset_domain_submodules)
    - .planning/phases/225-processing-port-protocol-cycle-inversion/225-03b-SUMMARY.md (read OUTCOME of OQ-4: Outcome A or B)
    - .planning/phases/225-processing-port-protocol-cycle-inversion/225-PATTERNS.md (§5 — exact subprocess.run shape and adaptation)
    - .planning/phases/225-processing-port-protocol-cycle-inversion/225-RESEARCH.md (§Architecture Guard Specification)
  </read_first>
  <action>
**Step 1: Update module docstring** (D-25)

Read the current docstring at lines 1-36 of `backend/tests/test_layering.py`. Update the title and the bulleted phase list to add Phase 225.

Replace the title line (currently `"""Layering rules across Phases 212, 213, and 214."`) with:
```
"""Layering rules across Phases 212, 213, 214, 222, 223, 224, and 225.
```

In the bulleted list of "Enforces open-core boundaries closed by:", add this line BEFORE the existing Phase 218 close-gate paragraph (or wherever the bullet list ends):
```
- Phase 225 PROCESS-02/04 - processing/ must not import from app.modules.catalog.*;
  all catalog access goes through ProcessingPort (app.core.processing_port).
```

Preserve every existing line in the docstring; only append.

**Step 2: Append test method** at end of file (after the last existing test).

Use this exact body. **CRITICAL**: Read `225-03b-SUMMARY.md` first to determine OQ-4 outcome:

**If OQ-4 Outcome A (Plan 03a/03b successfully removed `tasks_raster.py:143`)**: use the test body without exclusion:

```python
@pytest.mark.architecture
def test_no_processing_imports_catalog() -> None:
    """Phase 225 PROCESS-02/04: backend/app/processing/ must not import from app.modules.catalog.*.

    All catalog access must go through ProcessingPort (app.core.processing_port).
    Strict zero-hit — no allowlist for processing/* (D-23).

    Excluded paths:
      - backend/tests/ — test fixtures construct catalog ORM objects directly,
        structurally satisfying the Protocols (the scan target backend/app/processing/
        is already disjoint from backend/tests/, so no explicit pathspec exclusion
        is needed).

    Maps to Phase 225 ROADMAP SC#2 / SC#3. Inlines former Phase 999.11
    (added in same phase as the inversion — guard before inversion fails CI).
    """
    if not _has_git_metadata():
        pytest.skip("git metadata unavailable; arch test only runs on full clones")
    if not _has_pathspec_magic():
        pytest.skip(
            "git < 2.13 lacks `:!` pathspec exclusion; cannot enforce "
            "Phase 225 PROCESS-04 invariant via grep-based guard"
        )

    result = subprocess.run(
        [
            "git", "grep", "-n", "-E",
            r"^\s*(from|import)\s+app\.modules\.catalog",
            "--",
            "backend/app/processing/",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode == 0:
        pytest.fail(
            "Phase 225 PROCESS-02/04 invariant violated: backend/app/processing/ "
            "contains direct imports from app.modules.catalog.*. All catalog access "
            "must go through ProcessingPort (app.core.processing_port). "
            f"Offending lines:\n{result.stdout}"
        )
    if result.returncode != 1:
        pytest.fail(
            f"git grep failed unexpectedly: rc={result.returncode}\n"
            f"stderr: {result.stderr}"
        )
```

**If OQ-4 Outcome B (Plan 03a/03b retained `tasks_raster.py:143` as the single allowlist exception)**: use the test body WITH a `:!backend/app/processing/ingest/tasks_raster.py` pathspec exclusion AND extend the docstring to document the exception. Insert immediately after `"backend/app/processing/",` in the subprocess.run argument list:

```python
            ":!backend/app/processing/ingest/tasks_raster.py",
```

And update the docstring's "Excluded paths" section to add:
```
      - backend/app/processing/ingest/tasks_raster.py — line 143 retains
        `from app.modules.catalog.datasets.domain.models import Dataset  # noqa: F401`
        as a Procrastinate worker `Base.metadata` registration side-effect import
        (analogous to Phase 214's User allowlist exception). Documented as
        Phase 225 D-23 amendment in 225-03b-SUMMARY.md.
```

**NOTE**: Excluding the entire file is broader than excluding only line 143. If only line 143 is the exception, the broader exclusion accepts that any other line in `tasks_raster.py` could trip the guard without being caught. **Mitigation**: a separate manual grep verification in the SUMMARY ensures `tasks_raster.py` has only the line-143 exception. If the grep ever finds other lines in `tasks_raster.py`, that's a Phase 225 regression and should be fixed (not allowlisted).

**Step 3: Verify**

Run:
```
cd backend && uv run pytest tests/test_layering.py::test_no_processing_imports_catalog -x
```

Expected: PASSES (because Plans 02 + 03 cleared the imports). If the test FAILS:
- Read the offending lines in the failure message
- Migrate any missed sites (do not allowlist unless OQ-4 Outcome B)
- Re-run

Run the full architecture-guard suite to confirm no regressions:
```
cd backend && uv run pytest tests/test_layering.py -m architecture -x
```

All architecture tests must pass.
  </action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_layering.py::test_no_processing_imports_catalog tests/test_layering.py -m architecture -x</automated>
  </verify>
  <acceptance_criteria>
    - File contains the new test method: `grep -c "def test_no_processing_imports_catalog" backend/tests/test_layering.py` returns 1.
    - Test method has `@pytest.mark.architecture` decorator: verifiable by reading the file lines containing the test definition.
    - Test method exists with the regex pattern: `grep -c 'r"\^\\\\s\*(from|import)\\\\s+app\\\\.modules\\\\.catalog"' backend/tests/test_layering.py` returns ≥ 1 (or use simpler pattern: `grep -c "app.modules.catalog" backend/tests/test_layering.py` returns ≥ 1 inside the new test).
    - Test method calls `subprocess.run` with `git grep` invocation: verifiable by inspecting the new method body for `subprocess.run` and `git`, `grep` strings.
    - Module docstring credits Phase 225: `grep -c "Phase 225" backend/tests/test_layering.py` returns ≥ 1.
    - The new test passes: `cd backend && uv run pytest tests/test_layering.py::test_no_processing_imports_catalog -x` exits 0.
    - All other architecture tests still pass: `cd backend && uv run pytest tests/test_layering.py -m architecture -x` exits 0 with all tests passing.
    - If OQ-4 Outcome B was chosen, the test body includes the line `:!backend/app/processing/ingest/tasks_raster.py` (verifiable: `grep -c "tasks_raster.py" backend/tests/test_layering.py` returns ≥ 1).
  </acceptance_criteria>
  <done>
    `test_no_processing_imports_catalog` lands in `test_layering.py`, passes against the post-Plan-03 codebase, and seals the Phase 225 boundary. Module docstring credits Phase 225. All architecture-guard tests pass.
  </done>
</task>

<task type="auto">
  <name>Task 2: Create backend/tests/test_processing_port.py with FakeProcessingPort + seam test</name>
  <files>backend/tests/test_processing_port.py</files>
  <read_first>
    - backend/tests/test_layering.py (after Task 1)
    - backend/tests/conftest.py (entire file — confirm whether `fake_session` and `fake_user` fixtures exist; if not, add minimal versions inline in the new test file)
    - backend/tests/test_embedding_backfill.py (mirror structure — pure unit test with AsyncMock/MagicMock)
    - backend/app/core/processing_port.py (confirm full ProcessingPort surface that FakeProcessingPort must implement structurally)
    - backend/app/processing/ai/service.py (after Plan 02 — confirm which service-layer function to invoke in the seam test; D-15 ensures `port` is keyword-only)
    - .planning/phases/225-processing-port-protocol-cycle-inversion/225-PATTERNS.md (§4 — FakeProcessingPort skeleton)
    - .planning/phases/225-processing-port-protocol-cycle-inversion/225-RESEARCH.md (§Test Seam Specification)
  </read_first>
  <action>
Create `backend/tests/test_processing_port.py` (NEW file).

**Header**:
```python
"""Unit test for the ProcessingPort seam (Phase 225 D-27 / PROCESS-03).

Constructs a minimal FakeProcessingPort with canned return values and
passes it to a service-layer function in app/processing/ai/service.py
(per D-15 — the function takes `port: ProcessingPort` as keyword-only)
to verify the seam is genuinely testable in isolation without a database
or LLM.

Maps to Phase 225 ROADMAP SC#5: "AI features consume catalog data exclusively
through the Protocol — verifiable by ... a focused unit test that swaps
in a fake ProcessingPort."
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
```

**FakeProcessingPort class** (verbatim from PATTERNS.md §4 plus all helpers added in Plans 02/03 Task 0). Include:
- All read methods (get_dataset, get_record, search_datasets, apply_visibility_filter, check_dataset_access, get_user_roles, get_column_stats, get_distinct_values, extract_bbox)
- All write methods (create_dataset, create_map, update_map, create_ingestion_result)
- All OQ-3 helpers (get_records_without_embeddings, get_datasets_meta_by_ids, get_catalog_vocabulary, get_related_keywords, get_record_keyword_count, get_attribute_metadata)
- get_dataset_version
- get_dataset_with_attributes
- get_record_orm_class, get_grant_orm_class
- build_gdal_source
- Any additional helpers added in Plan 03a/03b Task 0 (re-grep `core/processing_port.py` to enumerate)

Use the skeleton from PATTERNS.md / RESEARCH.md as the starting point. All async methods use `async def`; sync methods use `def`. All return canned values (no real I/O).

**Seam test**:

The seam test invokes a real service-layer function from `processing/ai/service.py` that takes `port: ProcessingPort` (per D-15). Choose the simplest target — the smallest function that touches the Port. Options (read service.py to confirm):
- `_build_map_spec_and_persist(session, user, user_roles, llm_spec, *, port)` — calls `port.create_map`, `port.update_map`. Smaller than `generate_map_from_prompt`.
- A helper inside `_execute_get_dataset_details(...)` — calls `port.get_dataset`.
- `_execute_search_tool(session, user, user_roles, query, *, port)` — calls `port.search_datasets`.

Recommended: pick the simplest one that does NOT require LLM mocking. If `_build_map_spec_and_persist` doesn't call the LLM, that's a good target.

If every reachable service-layer function calls the LLM, mock the LLM client at a higher level (e.g., patch `processing.ai.llm_loop.run_tool_loop` or the `anthropic.AsyncAnthropic` client). Or test a lower-level helper (e.g., `_execute_search_tool`) directly.

Sample test (adjust to the actual chosen function):

```python
@pytest.mark.asyncio
async def test_processing_port_seam_search() -> None:
    """Verify _execute_search_tool runs through FakeProcessingPort.

    Demonstrates the seam: the AI service function receives port via D-15
    keyword-only parameter and invokes port.search_datasets, port.apply_visibility_filter,
    etc. — entirely without a database.
    """
    from app.processing.ai.service import _execute_search_tool  # adjust to actual function name

    port = FakeProcessingPort()
    fake_session = AsyncMock()
    fake_user = MagicMock(id=uuid.uuid4(), username="test_user")

    result = await _execute_search_tool(
        fake_session,
        fake_user,
        {"viewer"},
        "polygon datasets",
        port=port,
    )

    # Assert the function returned canned datasets via FakeProcessingPort.search_datasets
    assert result is not None  # adapt to the actual return shape
    # If function returns a dict with dataset list:
    # assert "datasets" in result
    # assert len(result["datasets"]) == 1
    # assert result["datasets"][0]["id"] == port._dataset_id
```

If `_execute_search_tool` doesn't exist as a separate function (or is fully internal), pick another target. The key requirement: invoke ONE service-layer function with `port=FakeProcessingPort()` and assert the function returns the expected shape based on canned data.

If no AI service function is structured for direct unit testing without heavy mocking, the simpler fallback is to test the FakeProcessingPort itself by directly calling Port methods and asserting return values:

```python
@pytest.mark.asyncio
async def test_fake_processing_port_satisfies_protocol() -> None:
    """Verify FakeProcessingPort structurally satisfies ProcessingPort
    and can stand in for DefaultProcessingPort in tests.
    """
    from app.core.processing_port import ProcessingPort

    port = FakeProcessingPort()
    assert isinstance(port, ProcessingPort), "FakeProcessingPort does not satisfy ProcessingPort Protocol"

    # Exercise read methods
    fake_session = AsyncMock()
    datasets, count = await port.search_datasets(fake_session, None, {"viewer"}, MagicMock())
    assert count == 1
    assert datasets[0].id == uuid.UUID(port._dataset_id)

    bbox = port.extract_bbox(datasets[0])
    assert bbox == [-74.0, 40.7, -73.9, 40.8]
```

This is acceptable as the focused unit test required by SC#5 — it proves FakeProcessingPort works AND structurally satisfies the Protocol. Combined with the architecture-guard test, the SC#5 invariant is verifiable.

**Stronger version** (preferred if achievable): include BOTH a structural check AND a service-layer invocation. The structural check is cheap; the service-layer invocation closes the binding "AI service function called with FakeProcessingPort" requirement.

**Verify**:
```
cd backend && uv run pytest tests/test_processing_port.py -x -v
```

Both tests should pass.
  </action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_processing_port.py -x -v</automated>
  </verify>
  <acceptance_criteria>
    - File `backend/tests/test_processing_port.py` exists.
    - File contains `class FakeProcessingPort:` (verifiable: `grep -c "class FakeProcessingPort:" backend/tests/test_processing_port.py` returns 1).
    - FakeProcessingPort defines all Port methods needed for `isinstance(FakeProcessingPort(), ProcessingPort)` to be True. Verifiable: `cd backend && uv run python -c "import sys; sys.path.insert(0, 'tests'); from test_processing_port import FakeProcessingPort; from app.core.processing_port import ProcessingPort; assert isinstance(FakeProcessingPort(), ProcessingPort), 'FakeProcessingPort does not satisfy ProcessingPort'; print('OK')"` exits 0.
    - File contains at least one `@pytest.mark.asyncio` test function (verifiable: `grep -c "@pytest.mark.asyncio" backend/tests/test_processing_port.py` returns ≥ 1).
    - The seam test invokes `port=FakeProcessingPort()` (or `port=port` where `port = FakeProcessingPort()`) somewhere — proving the seam is exercised. Verifiable: `grep -c "FakeProcessingPort()" backend/tests/test_processing_port.py` returns ≥ 1 inside a test function.
    - All tests pass: `cd backend && uv run pytest tests/test_processing_port.py -x` exits 0 with at least 1 test passed.
  </acceptance_criteria>
  <done>
    `test_processing_port.py` exists, contains a working FakeProcessingPort that structurally satisfies ProcessingPort, and at least one focused unit test passes — proving the AI service seam works in isolation per SC#5 / D-27.
  </done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 3: Negative-control verification (D-26) — prove the architecture guard fails CI when a forbidden import is reintroduced</name>
  <what-built>
The Phase 225 architecture-guard test `test_no_processing_imports_catalog` (Task 1) and the FakeProcessingPort seam test (Task 2) are in place. Plans 02 + 03 cleared the catalog imports from `processing/*`. The test passes against the current codebase.

Per D-26 / VALIDATION.md §Manual-Only Verifications, ROADMAP §225 SC#3 binds: "intentionally adding a forbidden import causes the test to fail in CI." This is the negative-control proof.
  </what-built>
  <how-to-verify>
1. Open `backend/app/processing/embeddings/backfill.py` in your editor.
2. Add the following line at the top of the file (after the module docstring / `from __future__ import annotations`):
   ```
   from app.modules.catalog.datasets.domain.models import Record  # NEGATIVE CONTROL — TEMPORARY
   ```
3. Run the architecture-guard test:
   ```
   cd backend && uv run pytest tests/test_layering.py::test_no_processing_imports_catalog -x
   ```
4. **Expected outcome**: the test FAILS with output that includes:
   - The phrase `"Phase 225 PROCESS-02/04 invariant violated"`
   - The line number 14 (or wherever you added the line) and content `from app.modules.catalog.datasets.domain.models import Record`
5. Capture the full failure output (paste into the resume signal below).
6. Revert the change:
   ```
   git checkout backend/app/processing/embeddings/backfill.py
   ```
7. Re-run the test:
   ```
   cd backend && uv run pytest tests/test_layering.py::test_no_processing_imports_catalog -x
   ```
8. **Expected outcome**: the test PASSES.

If step 4 does NOT produce the expected failure (test still passes despite the forbidden import being added), the architecture-guard test is broken — investigate the regex / pathspec / subprocess.run shape; do not finalize Plan 04 until the negative control is observed.

If step 8 does NOT pass after revert, something else is wrong — investigate before finalizing.
  </how-to-verify>
  <resume-signal>
Type one of:
- "verified" + paste the failure output from step 4 (proves D-26 negative control works)
- "guard broken" + describe why the test did not fail when the forbidden import was added (this is a Plan 04 defect; the planner / executor must fix and re-run)
- "revert failed" + describe why the test does not pass after revert
  </resume-signal>
</task>

<task type="auto">
  <name>Task 4: Final phase verification gate — alembic check, ruff, full pytest run</name>
  <files>(none modified — verification only)</files>
  <read_first>
    - backend/tests/test_layering.py (after Task 1)
    - backend/tests/test_processing_port.py (after Task 2)
    - .planning/phases/225-processing-port-protocol-cycle-inversion/225-RESEARCH.md (§Migration Sequencing — Commit 4 verification gate)
  </read_first>
  <action>
This is the Phase 225 verification gate (per RESEARCH.md §Migration Sequencing — Commit 4). Run each command in order. ALL must pass before Plan 04 is considered complete.

**Step 1: Phase-wide architecture grep**

```
grep -REn '^[[:space:]]*(from|import) app\.modules\.catalog' backend/app/processing/
```

Expected: zero hits OR exactly 1 hit at `tasks_raster.py:143` (per OQ-4 Outcome B).

**Step 2: Architecture-guard test passes**

```
cd backend && uv run pytest tests/test_layering.py -m architecture -x
```

Expected: all architecture tests pass (Phase 212/213/214/222/223/224 + new Phase 225).

**Step 3: FakeProcessingPort seam test passes**

```
cd backend && uv run pytest tests/test_processing_port.py -x
```

Expected: pass.

**Step 4: alembic check returns no new operations** (D-29)

```
cd backend && uv run alembic check
```

Expected: "No new upgrade operations detected." (refactor-only — no ORM model change).

**Step 5: ruff check is clean**

```
cd backend && uv run ruff check .
```

Expected: clean (no errors).

**Step 6: Full backend test suite**

```
cd backend && uv run pytest -q
```

Expected: `2036 passed` OR slightly higher count (2038 — the +2 new tests from Tasks 1 + 2). Confirm count is ≥ 2036 (no regressions).

**Step 7: openapi-check still clean** (D-31)

```
cd backend && make openapi-check
```

Expected: clean (no schema drift — refactor-only).

If any step fails, do NOT finalize Plan 04. Report the failure, fix, re-run all steps in order. Plan 04 only completes when every step is green.

After all 7 steps pass, document the results in `225-04-SUMMARY.md` with:
- Pre/post baseline test count
- All 7 verification step outputs
- D-26 negative-control evidence (from Task 3 resume signal)
- Phase-wide grep result
- Confirmation that Phase 225's PROCESS-01..05 requirements are satisfied
- Statement that Phase 225 is ready for `/gsd-verify-work`
  </action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_layering.py -m architecture tests/test_processing_port.py -x && uv run alembic check && uv run ruff check . && uv run pytest -q</automated>
  </verify>
  <acceptance_criteria>
    - Phase-wide grep returns 0 hits or exactly 1 hit (OQ-4 Outcome B): `grep -REn '^[[:space:]]*(from|import) app\.modules\.catalog' backend/app/processing/ | grep -v 'tasks_raster.py:143' | wc -l` returns 0.
    - All architecture-guard tests pass: `cd backend && uv run pytest tests/test_layering.py -m architecture -x` exits 0.
    - FakeProcessingPort seam test passes: `cd backend && uv run pytest tests/test_processing_port.py -x` exits 0.
    - alembic clean: `cd backend && uv run alembic check` exits 0 with output containing "No new upgrade operations" (or equivalent).
    - ruff clean: `cd backend && uv run ruff check .` exits 0.
    - Full pytest suite passes with count ≥ 2036: `cd backend && uv run pytest -q` exits 0 with `passed` count ≥ 2036.
    - openapi-check clean: `cd backend && make openapi-check` exits 0 (or has no schema drift output).
    - 225-04-SUMMARY.md documents all 7 verification step outputs and the D-26 negative-control evidence.
  </acceptance_criteria>
  <done>
    Phase 225 verification gate passes. The processing→catalog cycle is inverted; the boundary is sealed in CI; the seam is verifiably testable. Phase 225 is ready for `/gsd-verify-work`.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| (none new) | Refactor-only — new tests are static-analysis (architecture guard) + unit-level seam proof |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-225-04 | (n/a) | Phase 225 surface | accept | Refactor-only — no new attack surface introduced. New tests are static-analysis (architecture guard) and unit-level seam proof. They do not change application behavior, do not introduce new endpoints, do not change auth/authz semantics. The negative-control verification in Task 3 temporarily reintroduces a forbidden import to prove the guard works; this is a one-time human action that is reverted before commit. |

**Block:** false. Refactor only.
</threat_model>

<verification>
- `cd backend && uv run pytest tests/test_layering.py -m architecture -x` — all architecture tests pass (8 existing + 1 new = 9)
- `cd backend && uv run pytest tests/test_processing_port.py -x` — FakeProcessingPort seam test passes
- `cd backend && uv run alembic check` — no new operations
- `cd backend && uv run ruff check .` — clean
- `cd backend && uv run pytest -q` — count ≥ 2036 passed (typically 2038 with the two new tests)
- `cd backend && make openapi-check` — clean
- D-26 negative-control verified manually (Task 3 checkpoint): adding a forbidden import causes the architecture-guard test to fail
- Phase-wide grep: zero `from app.modules.catalog` in `backend/app/processing/` (or exactly 1 at `tasks_raster.py:143` per OQ-4 Outcome B)
</verification>

<success_criteria>
- `test_no_processing_imports_catalog` is added to `test_layering.py` and passes
- `test_layering.py` module docstring credits Phase 225 (D-25)
- Negative-control verification (D-26) demonstrates the guard fails CI on forbidden imports
- `backend/tests/test_processing_port.py` exists with FakeProcessingPort + at least one passing seam test (D-27 / SC#5)
- Phase-wide grep returns zero `from app.modules.catalog` in `processing/*` (or 1 documented exception at `tasks_raster.py:143`)
- Full backend test suite passes at count ≥ 2036
- alembic clean
- ruff clean
- openapi-check clean
- All 5 PROCESS-01..05 requirements verifiably satisfied:
  - PROCESS-01: ProcessingPort Protocol exists in `core/processing_port.py` (Plan 01)
  - PROCESS-02: zero `from app.modules.catalog` in `processing/*` (Plans 02 + 03; verified by Plan 04 architecture guard)
  - PROCESS-03: AI features consume catalog via Protocol (Plan 02; verified by Plan 04 FakeProcessingPort seam test)
  - PROCESS-04: architecture-guard test fails CI on forbidden imports (Plan 04 Task 1 + Task 3 negative control)
  - PROCESS-05: zero functional regressions — full suite green at 2036+ baseline
</success_criteria>

<output>
After completion, create `.planning/phases/225-processing-port-protocol-cycle-inversion/225-04-SUMMARY.md` with:
- Pre/post baseline test count (e.g., 2036 → 2038 with two new tests)
- All 7 verification gate step outputs (Step 1-7 from Task 4)
- D-26 negative-control evidence (failure output from Task 3 manual verification)
- Phase-wide grep result and OQ-4 disposition
- Mapping of each PROCESS-01..05 requirement to its verification command
- Statement: "Phase 225 PROCESS-01..05 requirements verifiably satisfied. Phase 225 is ready for `/gsd-verify-work`."
- Note any coverage of the audit P0 #2 directive ("Break catalog ↔ processing two-way cycle via ProcessingPort Protocol") — Phase 225 closes the processing→catalog half (8 module-level + ~24 function-scope import edges); the catalog→processing direction is the legitimate top-down driver and remains intact per SC#2.
</output>
</content>
</invoke>
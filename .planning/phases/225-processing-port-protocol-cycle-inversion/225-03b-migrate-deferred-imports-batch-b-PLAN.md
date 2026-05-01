---
phase: 225
plan: 03b
type: execute
wave: 2
depends_on:
  - 225-01
  - 225-03a
files_modified:
  - backend/app/processing/ingest/tasks_vrt.py
  - backend/app/processing/ingest/tasks_raster.py
  - backend/app/processing/ingest/metadata.py
  - backend/app/processing/ingest/router.py
  - backend/app/processing/ingest/service.py
autonomous: true
requirements:
  - PROCESS-02
threat_model:
  block: false
  rationale: "Refactor-only. Function-scope deferred imports relocate path; calls route through DefaultProcessingPort which delegates byte-for-byte to the same catalog functions. No endpoint surface change, no auth/authz semantics change, no data flow change. Worker tasks remain in their existing process boundaries; Procrastinate semantics unchanged."

must_haves:
  truths:
    - "Function-scope deferred from app.modules.catalog.* imports migrated in 5 processing files: ingest/tasks_vrt.py, ingest/tasks_raster.py, ingest/metadata.py, ingest/router.py, ingest/service.py"
    - "Deferral discipline preserved (D-19) — imports remain inside function bodies; only the path swaps from app.modules.catalog.* to app.platform.extensions"
    - "InstrumentedAttribute SQL uses replaced with Port method calls or via port.get_*_orm_class() helpers (using helpers added in 03a Task 0)"
    - "After this plan: grep -REn '^[[:space:]]*(from|import) app\\.modules\\.catalog' backend/app/processing/ returns zero hits (or exactly 1 at tasks_raster.py:143 per OQ-4 Outcome B)"
    - "tasks_raster.py:143 # noqa: F401 import resolved per OQ-4 (Outcome A: removed; Outcome B: retained as documented exception)"
    - "TYPE_CHECKING block in metadata.py:18 migrated to app.core.processing_port aliases"
    - "RecordKeyword and AttributeMetadata SQL uses across metadata.py routed through Port encapsulators (port.get_record_keyword_count, port.get_attribute_metadata)"
    - "Full backend test suite remains green (2036/2036) — behavior is byte-for-byte identical"
  artifacts:
    - path: "backend/app/processing/ingest/tasks_vrt.py"
      provides: "Migrated Dataset/Record/RecordDistribution access at all 4 deferred sites"
    - path: "backend/app/processing/ingest/tasks_raster.py"
      provides: "Migrated Dataset/Record/RecordDistribution access; line 143 F401 resolved per OQ-4"
    - path: "backend/app/processing/ingest/metadata.py"
      provides: "Migrated TYPE_CHECKING block + 5 deferred RecordKeyword/AttributeMetadata sites"
    - path: "backend/app/processing/ingest/router.py"
      provides: "Migrated deferred Dataset/Record imports at lines 819, 1005"
    - path: "backend/app/processing/ingest/service.py"
      provides: "Migrated 3 remaining deferred imports at lines 320, 368, 405"
  key_links:
    - from: "backend/app/processing/ingest/metadata.py"
      to: "port.get_record_keyword_count + port.get_attribute_metadata"
      via: "OQ-3 InstrumentedAttribute encapsulators"
      pattern: "port\\.(get_record_keyword_count|get_attribute_metadata)"
    - from: "backend/app/processing/ingest/service.py"
      to: "port.create_ingestion_result"
      via: "OQ-1 mitigation — IngestionResult constructed via Port helper"
      pattern: "port\\.create_ingestion_result"
    - from: "backend/app/processing/ingest/tasks_raster.py"
      to: "Plan 04 architecture-guard test"
      via: "OQ-4 Outcome A or Outcome B — Plan 04 conditionally adds :! pathspec exclusion"
      pattern: "tasks_raster\\.py"
---

<objective>
Migrate the function-scope deferred imports of `from app.modules.catalog.*` across 5 files in `backend/app/processing/ingest/` (batch B of the deferred-import sweep). Each deferred import preserves the deferral (D-19); only the path swaps from `app.modules.catalog.*` to `app.platform.extensions`.

This plan is the second half of the deferred-import sweep. Plan 03a covered embeddings/tasks.py + ingest/tasks_vector.py + tasks_common.py + tasks_reupload.py. After this plan AND 03a both land, the comprehensive grep `grep -REn '^[[:space:]]*(from|import) app\.modules\.catalog' backend/app/processing/` returns ZERO hits across the entire processing/ tree (or exactly 1 at `tasks_raster.py:143` per OQ-4 Outcome B). Plan 04's architecture-guard test can then be added safely.

Special handling:
- **OQ-3 (InstrumentedAttribute SQL)**: Plan 03a Task 0 already amended Port surface with any helpers needed by THIS plan's files (e.g., `port.get_dataset_orm_class`, `port.get_record_distribution_orm_class`, `RecordDistributionProtocol`). Plan 03b consumes those helpers — no further scaffold amendments needed.
- **OQ-4 (tasks_raster.py:143 # noqa: F401)**: Per RESEARCH.md and VALIDATION.md Manual-Only Verifications, attempt removal first. If worker tests fail, restore as the sole allowlist exception and amend Plan 04's guard test with `:!backend/app/processing/ingest/tasks_raster.py:143`.

Behavior is byte-for-byte identical because every Port call routes to DefaultProcessingPort which delegates to the original catalog function. The 2036/2036 backend test suite must remain green.

Output: 5 modified processing files. No scaffold amendments (those happened in 03a Task 0).
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
@.planning/phases/225-processing-port-protocol-cycle-inversion/225-01-SUMMARY.md
@.planning/phases/225-processing-port-protocol-cycle-inversion/225-03a-SUMMARY.md
@backend/app/core/processing_port.py
@backend/app/platform/extensions/__init__.py
@backend/app/platform/extensions/defaults.py
@backend/app/processing/ingest/tasks_vrt.py
@backend/app/processing/ingest/tasks_raster.py
@backend/app/processing/ingest/metadata.py
@backend/app/processing/ingest/router.py
@backend/app/processing/ingest/service.py

<interfaces>
<!-- After Plans 01 + 02 Task 0 + 03a Task 0, the Port surface is complete. Plan 03b consumes it. -->

Per Plan 03a Task 0 SUMMARY, the Port should now expose (in addition to Plan 01/02 helpers):
- get_dataset_orm_class, get_record_distribution_orm_class (or `port.get_record_distribution_attribute_set` etc.)
- RecordDistributionProtocol type alias
- Any other helpers needed by tasks_vrt.py, tasks_raster.py, metadata.py, router.py, service.py

If Plan 03b discovers a missing helper at task time, halt and amend `core/processing_port.py` + `defaults.py` (treating it as an inline Task 0 amendment within the relevant Plan 03b task) BEFORE continuing the migration. Document the addition in 225-03b-SUMMARY.md.

Concrete migration patterns from RESEARCH.md §Caller Migration Inventory:

ingest/metadata.py:18 (TYPE_CHECKING):
BEFORE:
```
if TYPE_CHECKING:
    from app.modules.catalog.datasets.domain.models import (AttributeMetadata, Dataset, Record)
```
AFTER:
```
if TYPE_CHECKING:
    from app.core.processing_port import Attribute, Dataset, Record
```

ingest/metadata.py:466, 1076, 1102, 1130, 1188 (RecordKeyword + AttributeMetadata SQL):
BEFORE (typical):
```
from app.modules.catalog.datasets.domain.models import RecordKeyword
result = await session.execute(select(func.count()).where(RecordKeyword.record_id == record_id))
```
AFTER:
```
from app.platform.extensions import get_processing_port
port = get_processing_port()
count = await port.get_record_keyword_count(session, record_id)
```

For select(AttributeMetadata)... at metadata.py:1076 etc.:
```
from app.platform.extensions import get_processing_port
port = get_processing_port()
attributes = await port.get_attribute_metadata(session, dataset_id)
```

</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1 (formerly 03/Task 4): Migrate deferred imports in ingest/tasks_vrt.py and ingest/tasks_raster.py (resolve OQ-4 for line 143)</name>
  <files>backend/app/processing/ingest/tasks_vrt.py, backend/app/processing/ingest/tasks_raster.py</files>
  <read_first>
    - backend/app/processing/ingest/tasks_vrt.py (entire file — lines 51, 165, 283, 362)
    - backend/app/processing/ingest/tasks_raster.py (entire file — lines 47, 143, 301)
    - backend/app/core/processing_port.py (after 03a Task 0)
    - .planning/phases/225-processing-port-protocol-cycle-inversion/225-RESEARCH.md (§Open Questions OQ-4)
    - .planning/phases/225-processing-port-protocol-cycle-inversion/225-VALIDATION.md (Manual-Only Verifications: tasks_raster.py:143)
    - .planning/phases/225-processing-port-protocol-cycle-inversion/225-03a-SUMMARY.md (Port amendments made in 03a Task 0)
  </read_first>
  <action>
File 1: `backend/app/processing/ingest/tasks_vrt.py`

Four deferred sites at lines 51, 165, 283, 362. Each imports some combination of `Dataset`, `Record`, `RecordDistribution`. Read each site to classify:

(a) Type annotation only — replace with `from app.core.processing_port import Dataset, Record` (Protocol aliases). For `RecordDistribution`, use `from app.core.processing_port import RecordDistribution` (added in 03a Task 0).

(b) SQL InstrumentedAttribute — replace with appropriate Port method (`port.get_dataset`, `port.get_record`) or Port helper (`port.get_dataset_orm_class`, `port.get_record_distribution_orm_class` from 03a Task 0).

(c) Constructor use (e.g., `Dataset(...)`)— very unlikely in worker tasks; if found, raise as a finding and add a `port.create_*` helper (inline Task 0-style amendment).

For each site:

```
# Pattern: deferred import inside function body — keep deferred, swap path
from app.platform.extensions import get_processing_port
port = get_processing_port()
# rewrite call sites to use port.method(...)
```

File 2: `backend/app/processing/ingest/tasks_raster.py`

Three deferred sites at lines 47, 143, 301:

Site 1 (line ~47): same analysis as `tasks_vrt.py` sites.

Site 2 (line ~143): the `# noqa: F401` side-effect import (OQ-4)
```
from app.modules.catalog.datasets.domain.models import Dataset  # noqa: F401
```

Per OQ-4 / VALIDATION.md Manual-Only Verifications:
- ATTEMPT REMOVAL FIRST. Comment out or delete the import.
- Run the worker test path: `cd backend && uv run pytest tests/test_ingest_raster*.py tests/test_raster*.py -x` (or the closest equivalent — re-grep for raster-related tests).
- Also run a smoke worker startup check if available: `cd backend && uv run python -c "from app.processing.ingest.tasks_raster import *"`.

Outcome A — removal succeeds (worker imports/tests pass without the F401):
- Keep removal. Document in 225-03b-SUMMARY.md.
- No D-23 amendment needed.

Outcome B — removal fails (worker startup fails because `Dataset` is not registered in `Base.metadata`):
- Restore the import: `from app.modules.catalog.datasets.domain.models import Dataset  # noqa: F401`.
- This is now the SOLE allowlist exception. D-23 needs amendment (which Plan 04's architecture-guard test must reflect via a `:!backend/app/processing/ingest/tasks_raster.py` pathspec exclusion).
- Document the outcome and its implications in 225-03b-SUMMARY.md so Plan 04 can wire the exclusion correctly.

Site 3 (line ~301): same as line 47.

Verify: ruff clean both files. Re-grep:
- If Outcome A: zero `from app.modules.catalog` in `tasks_raster.py`.
- If Outcome B: exactly 1 hit at line 143; the architecture-guard test in Plan 04 must exclude this line via pathspec.
  </action>
  <verify>
    <automated>cd backend && uv run ruff check app/processing/ingest/tasks_vrt.py app/processing/ingest/tasks_raster.py && uv run pytest tests/test_ingest_*.py tests/test_raster*.py -x</automated>
  </verify>
  <acceptance_criteria>
    - `grep -c "from app.modules.catalog" backend/app/processing/ingest/tasks_vrt.py` returns 0.
    - `grep -c "from app.modules.catalog" backend/app/processing/ingest/tasks_raster.py` returns 0 (Outcome A) OR exactly 1 (Outcome B; line 143 only).
    - All call sites in `tasks_vrt.py` and `tasks_raster.py` route through Port: `grep -cE "port\.(get_dataset|get_record|build_gdal_source|create_dataset)" backend/app/processing/ingest/tasks_vrt.py backend/app/processing/ingest/tasks_raster.py` returns ≥ 4 combined.
    - ruff clean for both files.
    - Targeted tests pass: `cd backend && uv run pytest tests/test_ingest_*.py tests/test_raster*.py -x` exits 0.
    - Full suite still green: `cd backend && uv run pytest -q` exits 0.
    - OQ-4 outcome (Outcome A or B) documented in eventual 225-03b-SUMMARY.md with the test-run evidence.
  </acceptance_criteria>
  <done>
    `tasks_vrt.py` and `tasks_raster.py` deferred imports migrated. OQ-4 resolved (Outcome A: removal; or Outcome B: kept with line-143 exclusion noted for Plan 04). Full suite green.
  </done>
</task>

<task type="auto">
  <name>Task 2 (formerly 03/Task 5): Migrate deferred imports in ingest/metadata.py (TYPE_CHECKING + 5 SQL sites)</name>
  <files>backend/app/processing/ingest/metadata.py</files>
  <read_first>
    - backend/app/processing/ingest/metadata.py (entire file — TYPE_CHECKING at line 18, deferred sites at lines 466, 1076, 1102, 1130, 1188)
    - backend/app/core/processing_port.py (after 03a Task 0 — confirm get_record_keyword_count, get_attribute_metadata, get_catalog_vocabulary, get_related_keywords)
  </read_first>
  <action>
File: `backend/app/processing/ingest/metadata.py`

Site 1 (line ~18): TYPE_CHECKING block

BEFORE:
```
if TYPE_CHECKING:
    from app.modules.catalog.datasets.domain.models import (
        AttributeMetadata,
        Dataset,
        Record,
    )
```

AFTER:
```
if TYPE_CHECKING:
    from app.core.processing_port import Attribute, Dataset, Record
```

The local name `AttributeMetadata` becomes `Attribute` (Protocol alias). Update all type annotations in the file that reference `AttributeMetadata` to `Attribute`.

Sites 2-6 (lines 466, 1076, 1102, 1130, 1188): RecordKeyword + AttributeMetadata SQL InstrumentedAttribute uses

Read each site. Typical pattern:

BEFORE (count keywords):
```
from app.modules.catalog.datasets.domain.models import RecordKeyword
result = await session.execute(
    select(func.count()).where(RecordKeyword.record_id == record_id)
)
count = result.scalar() or 0
```

AFTER:
```
from app.platform.extensions import get_processing_port
port = get_processing_port()
count = await port.get_record_keyword_count(session, record_id)
```

BEFORE (read attributes):
```
from app.modules.catalog.datasets.domain.models import AttributeMetadata
result = await session.execute(
    select(AttributeMetadata).where(AttributeMetadata.dataset_id == dataset_id)
)
attributes = result.scalars().all()
```

AFTER:
```
from app.platform.extensions import get_processing_port
port = get_processing_port()
attributes = await port.get_attribute_metadata(session, dataset_id)
```

For any other deferred SQL pattern not covered (e.g., a more complex AttributeMetadata join), evaluate whether to add a new Port method (inline Task 0-style amendment) or use `port.get_dataset_orm_class()` to keep the SQL with the ORM class.

Verify: ruff clean; zero `from app.modules.catalog` in this file.
  </action>
  <verify>
    <automated>cd backend && uv run ruff check app/processing/ingest/metadata.py && grep -REn "(from|import) app\.modules\.catalog" backend/app/processing/ingest/metadata.py | (! grep .); echo "exit=$?"</automated>
  </verify>
  <acceptance_criteria>
    - `grep -c "from app.modules.catalog" backend/app/processing/ingest/metadata.py` returns 0.
    - `grep -c "from app.core.processing_port import" backend/app/processing/ingest/metadata.py` returns ≥ 1 (TYPE_CHECKING block).
    - `grep -c "port.get_record_keyword_count\|port.get_attribute_metadata\|port.get_catalog_vocabulary\|port.get_related_keywords" backend/app/processing/ingest/metadata.py` returns ≥ 2.
    - No remaining direct `RecordKeyword.` or `AttributeMetadata.` SQL column references in this file: `grep -cE "RecordKeyword\.|AttributeMetadata\." backend/app/processing/ingest/metadata.py` returns 0.
    - ruff clean.
    - Full suite still green: `cd backend && uv run pytest -q` exits 0.
  </acceptance_criteria>
  <done>
    `metadata.py` TYPE_CHECKING block + 5 deferred SQL sites migrated. All RecordKeyword / AttributeMetadata SQL routed through Port. Full suite green.
  </done>
</task>

<task type="auto">
  <name>Task 3 (formerly 03/Task 6): Migrate deferred imports in ingest/router.py (lines 819, 1005) and ingest/service.py (lines 320, 368, 405)</name>
  <files>backend/app/processing/ingest/router.py, backend/app/processing/ingest/service.py</files>
  <read_first>
    - backend/app/processing/ingest/router.py (entire file — focus on lines 819, 1005)
    - backend/app/processing/ingest/service.py (entire file — focus on lines 320, 368, 405)
    - backend/app/core/processing_port.py (after 03a Task 0)
  </read_first>
  <action>
File 1: `backend/app/processing/ingest/router.py`

Two deferred sites at lines 819 and 1005. Re-grep to confirm exact line numbers and contents (line numbers may have drifted from RESEARCH.md). Each likely imports `Dataset` and/or `Record` from catalog models.

For each site:

If type annotation only — switch to Protocol alias from `app.core.processing_port`.

If SQL InstrumentedAttribute use:
- Simple lookup → `await port.get_dataset(...)` or `await port.get_record(...)`.
- Exotic SQL → use `port.get_dataset_orm_class()` / `port.get_record_orm_class()`.

Pattern (deferred, keeping inside function body):
```
from app.platform.extensions import get_processing_port
port = get_processing_port()
# call sites use port.method(...)
```

File 2: `backend/app/processing/ingest/service.py`

Three deferred sites at lines 320, 368, 405. Re-grep to confirm.

Site at line 320 — `Dataset`: type or SQL? Apply same analysis as router.py.

Site at line 368 — `IngestionResult`: replace with `port.create_ingestion_result(**kwargs)`:

BEFORE:
```
from app.modules.catalog.datasets.domain.schemas import IngestionResult
ingestion = IngestionResult(success=False, ...)
```

AFTER:
```
from app.platform.extensions import get_processing_port
port = get_processing_port()
ingestion = port.create_ingestion_result(success=False, ...)
```

Site at line 405 — `Dataset`: type or SQL? Apply same analysis.

**FINAL CHECK** — after this task, the comprehensive grep:
```
grep -REn '^[[:space:]]*(from|import) app\.modules\.catalog' backend/app/processing/
```
must return ZERO HITS (or, if OQ-4 Outcome B was chosen in Task 1, exactly 1 hit at `tasks_raster.py:143`). All deferred imports across all 9 processing files (4 from 03a + 5 from 03b) are migrated. Plan 04's architecture-guard test can now be safely added.

Verify: ruff clean both files.
  </action>
  <verify>
    <automated>cd backend && uv run ruff check app/processing/ingest/router.py app/processing/ingest/service.py && grep -REn "(from|import) app\.modules\.catalog" backend/app/processing/ingest/router.py backend/app/processing/ingest/service.py | (! grep .); echo "exit=$?"</automated>
  </verify>
  <acceptance_criteria>
    - `grep -c "from app.modules.catalog" backend/app/processing/ingest/router.py` returns 0.
    - `grep -c "from app.modules.catalog" backend/app/processing/ingest/service.py` returns 0.
    - `grep -c "port.create_ingestion_result" backend/app/processing/ingest/service.py` returns ≥ 1.
    - **FINAL PHASE-WIDE CHECK**: `grep -REn '^[[:space:]]*(from|import) app\.modules\.catalog' backend/app/processing/` returns 0 hits OR exactly 1 hit at `tasks_raster.py:143` (per OQ-4 Outcome B). Verifiable: `grep -REn '^[[:space:]]*(from|import) app\.modules\.catalog' backend/app/processing/ | grep -v 'tasks_raster.py:143' | wc -l` returns 0.
    - ruff clean for both files.
    - Full suite still green: `cd backend && uv run pytest -q` exits 0 with `2036 passed`.
    - `cd backend && uv run alembic check` returns "no new operations".
  </acceptance_criteria>
  <done>
    Last 5 deferred sites migrated. Phase-wide grep returns zero hits (or 1 allowlisted hit per OQ-4 Outcome B). Full suite green. The catalog ↔ processing import cycle is now completely inverted on the processing→catalog half. Plan 04 can land the architecture-guard test.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| (none new) | Refactor-only — deferred imports relocate path; behavior unchanged via DefaultProcessingPort delegation |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-225-03b | (n/a) | Phase 225 surface | accept | Refactor-only — no new attack surface introduced. Function-scope deferred imports relocate path; calls route through DefaultProcessingPort which delegates byte-for-byte to the same catalog functions. Worker tasks remain in their existing process boundaries; Procrastinate semantics unchanged. Threats inherited from existing catalog services. |

**Block:** false. Refactor only.
</threat_model>

<verification>
- Phase-wide grep returns zero hits (or 1 allowlisted hit per OQ-4 Outcome B): `grep -REn '^[[:space:]]*(from|import) app\.modules\.catalog' backend/app/processing/ | wc -l` returns 0 (or 1 if Outcome B)
- `cd backend && uv run pytest -q` returns `2036 passed`
- `cd backend && uv run ruff check app/processing/` clean
- `cd backend && uv run alembic check` no new operations
- All 5 modified processing files compile and pass their targeted tests
- (Plan 04's architecture-guard test will land in Wave 3, sealing the boundary in CI)
</verification>

<success_criteria>
- 5 processing files migrated (tasks_vrt.py, tasks_raster.py, metadata.py, router.py, service.py)
- Deferral discipline preserved (D-19) — imports still inside function bodies
- After this plan: `grep -REn '^[[:space:]]*(from|import) app\.modules\.catalog' backend/app/processing/` returns zero hits (or exactly 1 at `tasks_raster.py:143` per OQ-4 Outcome B)
- `tasks_raster.py:143` `# noqa: F401` resolution documented (OQ-4 Outcome A or B)
- Full backend test suite green at 2036/2036 baseline
- ruff clean
- alembic clean
</success_criteria>

<output>
After completion, create `.planning/phases/225-processing-port-protocol-cycle-inversion/225-03b-SUMMARY.md` with:
- 5 files migrated (batch B), line-count delta per file
- Total deferred-import sites migrated in batch B (target: ~17 sites — 4 in tasks_vrt + 3 in tasks_raster + 6 in metadata + 2 in router + 3 in service)
- Final phase-wide grep result: ZERO hits (or 1 allowlisted hit at `tasks_raster.py:143`)
- OQ-4 outcome: Outcome A (removed) or Outcome B (retained as single exception). If Outcome B, explicit instruction to Plan 04 to add `:!backend/app/processing/ingest/tasks_raster.py` pathspec exclusion to the architecture-guard test, and a corresponding `D-23` amendment note in CONTEXT.md.
- Confirmation that 2036/2036 baseline holds
- Confirmation that all existing architecture guards still pass
- Plan 04 readiness statement: "The boundary is now clean (or has 1 documented exception). Plan 04 can safely add `test_no_processing_imports_catalog`."
</output>

---
phase: 225
plan: 03
type: execute
wave: 2
depends_on:
  - 225-01
files_modified:
  - backend/app/processing/embeddings/tasks.py
  - backend/app/processing/ingest/tasks_vector.py
  - backend/app/processing/ingest/tasks_common.py
  - backend/app/processing/ingest/tasks_reupload.py
  - backend/app/processing/ingest/tasks_vrt.py
  - backend/app/processing/ingest/tasks_raster.py
  - backend/app/processing/ingest/metadata.py
  - backend/app/processing/ingest/router.py
  - backend/app/processing/ingest/service.py
  - backend/app/core/processing_port.py
  - backend/app/platform/extensions/defaults.py
autonomous: true
requirements:
  - PROCESS-02
threat_model:
  block: false
  rationale: "Refactor-only. Function-scope deferred imports relocate path; calls route through DefaultProcessingPort which delegates byte-for-byte to the same catalog functions. No endpoint surface change, no auth/authz semantics change, no data flow change. Worker tasks remain in their existing process boundaries; Procrastinate semantics unchanged."

must_haves:
  truths:
    - "All function-scope deferred from app.modules.catalog.* imports across 9 processing files are migrated"
    - "Deferral discipline preserved (D-19) — imports remain inside function bodies; only the path swaps from app.modules.catalog.* to app.platform.extensions"
    - "InstrumentedAttribute SQL uses replaced with Port method calls or via port.get_*_orm_class() helpers"
    - "After this plan: grep -REn '^[[:space:]]*(from|import) app\\.modules\\.catalog' backend/app/processing/ returns zero hits"
    - "tasks_raster.py:143 # noqa: F401 import resolved per OQ-4"
    - "IngestionResult constructor uses route through port.create_ingestion_result(**kwargs) instead of direct import"
    - "DatasetVersion use at tasks_common.py:849 routed through port.get_dataset_version (OQ-2)"
    - "Full backend test suite remains green (2036/2036) — behavior is byte-for-byte identical"
    - "TYPE_CHECKING block in metadata.py:18 migrated to app.core.processing_port aliases"
  artifacts:
    - path: "backend/app/processing/embeddings/tasks.py"
      provides: "Migrated TYPE_CHECKING-only catalog references"
    - path: "backend/app/processing/ingest/tasks_vector.py"
      provides: "Migrated build_gdal_source via Port"
    - path: "backend/app/processing/ingest/tasks_common.py"
      provides: "Migrated create_dataset, IngestionResult constructor, DatasetVersion access"
    - path: "backend/app/processing/ingest/tasks_reupload.py"
      provides: "Migrated Dataset access (lines 38, 257) and build_gdal_source (line 273)"
    - path: "backend/app/processing/ingest/tasks_vrt.py"
      provides: "Migrated Dataset/Record/RecordDistribution access at all 4 deferred sites"
    - path: "backend/app/processing/ingest/tasks_raster.py"
      provides: "Migrated Dataset/Record/RecordDistribution access; line 143 F401 resolved"
    - path: "backend/app/processing/ingest/metadata.py"
      provides: "Migrated TYPE_CHECKING block + 5 deferred RecordKeyword/AttributeMetadata sites"
    - path: "backend/app/processing/ingest/router.py"
      provides: "Migrated deferred Dataset/Record imports at lines 819, 1005"
    - path: "backend/app/processing/ingest/service.py"
      provides: "Migrated 3 remaining deferred imports at lines 320, 368, 405"
  key_links:
    - from: "backend/app/processing/ingest/tasks_common.py"
      to: "port.get_dataset_version"
      via: "OQ-2 — DatasetVersion fetched through Port"
      pattern: "port\\.get_dataset_version"
    - from: "backend/app/processing/ingest/tasks_common.py"
      to: "port.create_ingestion_result"
      via: "OQ-1 mitigation — IngestionResult constructed via Port helper"
      pattern: "port\\.create_ingestion_result"
    - from: "backend/app/processing/embeddings/tasks.py"
      to: "TYPE_CHECKING block uses app.core.processing_port aliases"
      via: "static typing forward ref"
      pattern: "from app\\.core\\.processing_port import"
---

<objective>
Migrate the function-scope deferred imports of `from app.modules.catalog.*` across 9 files in `backend/app/processing/ingest/` and `backend/app/processing/embeddings/`. Each deferred import preserves the deferral (D-19 — circular-import safety, slow-startup mitigation); only the path swaps from `app.modules.catalog.*` to `app.platform.extensions` (`get_processing_port`).

This plan completes the import inversion. After this plan, `grep -REn '^[[:space:]]*(from|import) app\.modules\.catalog' backend/app/processing/` returns ZERO hits across both top-level and function-scope locations. Plan 04's architecture-guard test can then be added safely.

Special handling:
- **OQ-1 (IngestionResult construction)**: Plan 02 Task 0 added `port.create_ingestion_result(**kwargs)`. This plan rewrites `tasks_common.py:697` and `ingest/service.py:368` to use it.
- **OQ-2 (DatasetVersion at tasks_common.py:849)**: Plan 01 added `port.get_dataset_version(...)` and `DatasetVersionProtocol`. This plan migrates the call site.
- **OQ-3 (InstrumentedAttribute SQL)**: Plan 02 Task 0 added Port methods. Task 0 here adds any additional helpers needed (e.g., `port.get_dataset_orm_class`, `RecordDistributionProtocol`) based on a re-grep.
- **OQ-4 (tasks_raster.py:143 # noqa: F401)**: Per RESEARCH.md, attempt removal first. If worker tests fail, restore as the sole allowlist exception and amend Plan 04's guard test with `:!backend/app/processing/ingest/tasks_raster.py`.

Behavior is byte-for-byte identical because every Port call routes to DefaultProcessingPort which delegates to the original catalog function. The 2036/2036 backend test suite must remain green.

Output: 9 modified processing files + 2 amended scaffold files (core/processing_port.py + defaults.py if Task 0 needs additions).
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
@.planning/phases/225-processing-port-protocol-cycle-inversion/225-01-SUMMARY.md
@backend/app/core/processing_port.py
@backend/app/platform/extensions/__init__.py
@backend/app/platform/extensions/defaults.py
@backend/app/processing/embeddings/tasks.py
@backend/app/processing/ingest/tasks_vector.py
@backend/app/processing/ingest/tasks_common.py
@backend/app/processing/ingest/tasks_reupload.py
@backend/app/processing/ingest/tasks_vrt.py
@backend/app/processing/ingest/tasks_raster.py
@backend/app/processing/ingest/metadata.py
@backend/app/processing/ingest/router.py
@backend/app/processing/ingest/service.py

<interfaces>
<!-- Plans 01 + 02 Task 0 produced these helpers. Plan 03 consumes them. -->

After Plan 02 Task 0, `core/processing_port.py` declares:
- All read methods (get_dataset, get_record, search_datasets, ...)
- All write methods (create_dataset, create_map, update_map, create_ingestion_result)
- ORM-class helpers: get_record_orm_class, get_grant_orm_class
- get_dataset_with_attributes
- OQ-3 InstrumentedAttribute encapsulators: get_records_without_embeddings, get_datasets_meta_by_ids, get_catalog_vocabulary, get_related_keywords, get_record_keyword_count, get_attribute_metadata
- OQ-2: get_dataset_version
- build_gdal_source

Plan 03 Task 0 may add (verify by re-grep):
- get_dataset_orm_class (if any deferred site uses select(Dataset) for non-trivial SQL)
- get_record_distribution_orm_class + RecordDistributionProtocol (if RecordDistribution is used as InstrumentedAttribute)

Concrete migration patterns from RESEARCH.md §Caller Migration Inventory.

embeddings/tasks.py:21 (TYPE_CHECKING — typing-only):
BEFORE:
```
if TYPE_CHECKING:
    from app.modules.catalog.datasets.domain.models import Dataset, Record
```
AFTER:
```
if TYPE_CHECKING:
    from app.core.processing_port import Dataset, Record
```

ingest/tasks_vector.py:302 (deferred function body):
BEFORE:
```
from app.modules.catalog.sources.preview import build_gdal_source
url, layer = build_gdal_source(service_type, base_url, ...)
```
AFTER:
```
from app.platform.extensions import get_processing_port
port = get_processing_port()
url, layer = port.build_gdal_source(service_type, base_url, ...)
```

ingest/tasks_common.py:618 (deferred):
BEFORE:
```
from app.modules.catalog.datasets.domain.service import create_dataset
result = await create_dataset(session, ...)
```
AFTER:
```
from app.platform.extensions import get_processing_port
port = get_processing_port()
result = await port.create_dataset(session, ...)
```

ingest/tasks_common.py:697 (IngestionResult — OQ-1):
BEFORE:
```
from app.modules.catalog.datasets.domain.schemas import IngestionResult
ingestion = IngestionResult(success=True, ...)
```
AFTER:
```
from app.platform.extensions import get_processing_port
port = get_processing_port()
ingestion = port.create_ingestion_result(success=True, ...)
```

ingest/tasks_common.py:849 (DatasetVersion — OQ-2):
BEFORE:
```
from app.modules.catalog.collections.models import DatasetVersion
result = await session.execute(select(DatasetVersion).where(DatasetVersion.dataset_id == dataset_id).order_by(...))
version = result.scalar_one_or_none()
```
AFTER:
```
from app.platform.extensions import get_processing_port
port = get_processing_port()
version = await port.get_dataset_version(session, dataset_id)
```

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
  <name>Task 0: Re-grep all deferred sites; amend Plan 01 outputs if additional Port helpers needed</name>
  <files>backend/app/core/processing_port.py, backend/app/platform/extensions/defaults.py</files>
  <read_first>
    - backend/app/core/processing_port.py (after Plan 02 Task 0)
    - backend/app/platform/extensions/defaults.py (after Plan 02 Task 0)
    - backend/app/processing/ingest/tasks_reupload.py (lines 38, 257 — determine type vs SQL)
    - backend/app/processing/ingest/tasks_vrt.py (lines 51, 165, 283, 362 — determine type vs SQL)
    - backend/app/processing/ingest/tasks_raster.py (lines 47, 301 — determine type vs SQL)
    - backend/app/processing/ingest/router.py (lines 819, 1005 — determine type vs SQL)
    - backend/app/processing/ingest/service.py (lines 320, 405 — determine type vs SQL)
    - backend/app/modules/catalog/datasets/domain/models.py (RecordDistribution attribute set if needed)
  </read_first>
  <action>
Step 1: Comprehensive re-grep to enumerate every deferred catalog import currently in `backend/app/processing/`:

```
grep -REn '^[[:space:]]+(from|import) app\.modules\.catalog' backend/app/processing/
```

This captures function-scope (indented) imports only. Compare with the RESEARCH.md inventory; flag any new sites (codebase may have drifted).

Step 2: Classify each remaining site as one of: (a) type annotation only, (b) runtime SQL InstrumentedAttribute use, (c) runtime constructor use, (d) runtime function call.

Run:

```
grep -nE "select\(Dataset|select\(Record|select\(RecordDistribution|select\(RecordKeyword|select\(AttributeMetadata|select\(DatasetVersion|select\(DatasetGrant" backend/app/processing/
```

This pinpoints SQL InstrumentedAttribute uses across the codebase.

Step 3: Identify gaps in Port surface. Compare the SQL InstrumentedAttribute uses against the Port surface (Plans 01 + 02 Task 0). If any gaps exist, amend `core/processing_port.py` and `defaults.py`.

Likely amendments needed (verify against re-grep):

1) `port.get_dataset_orm_class() -> type` if any deferred site uses `select(Dataset).where(Dataset.id == ...)` and a simple `port.get_dataset` lookup is not equivalent. Add to Port + DefaultProcessingPort:

```python
# core/processing_port.py
def get_dataset_orm_class(self) -> type: ...

# defaults.py
def get_dataset_orm_class(self):  # type: ignore[no-untyped-def]
    from app.modules.catalog.datasets.domain.models import Dataset
    return Dataset
```

2) `port.get_record_distribution_orm_class() -> type` if `tasks_vrt.py` or `tasks_raster.py` uses `select(RecordDistribution).where(...)`. Add similarly.

3) `RecordDistributionProtocol` if any file uses `RecordDistribution` as type annotation:

```python
@runtime_checkable
class RecordDistributionProtocol(Protocol):
    """Catalog RecordDistribution surface — fields read by ingest workers."""
    id: uuid.UUID
    record_id: uuid.UUID
    # Add other fields read cross-domain — re-grep at task time

RecordDistribution = RecordDistributionProtocol
```

4) Any other Port methods needed — e.g., if `ingest/service.py:320` uses `select(Dataset).where(Dataset.created_by == user.id)` for ownership lookup, add `port.get_user_datasets(session, user_id) -> list[DatasetProtocol]` rather than exposing Dataset ORM class.

Step 4: Apply amendments. Edit `core/processing_port.py` and `defaults.py` accordingly. Mirror the structures established in Plan 01 (deferred imports, `# type: ignore[no-untyped-def]`, façade discipline).

Step 5: Verify amendments don't break existing invariants. Run smoke import + architecture guards + full pytest. All must pass.

Step 6: Document amendments in the eventual `225-03-SUMMARY.md`. List each new Port method and the deferred sites that consume it.
  </action>
  <verify>
    <automated>cd backend && uv run python -c "from app.core.processing_port import ProcessingPort; from app.platform.extensions.defaults import DefaultProcessingPort; assert isinstance(DefaultProcessingPort(), ProcessingPort), 'fail'; print('OK')" && uv run pytest tests/test_layering.py -m architecture -x</automated>
  </verify>
  <acceptance_criteria>
    - Port amendments (if any added) are reachable from `app.core.processing_port` and implemented in `DefaultProcessingPort`.
    - DefaultProcessingPort still satisfies ProcessingPort: smoke isinstance check passes.
    - Phase 214 IDENT-01 guard still passes: `cd backend && uv run pytest tests/test_layering.py::test_core_does_not_import_from_any_module -x` exits 0.
    - Phase 224 façade guard still passes: `cd backend && uv run pytest tests/test_layering.py::test_no_external_imports_of_dataset_domain_submodules -x` exits 0.
    - Full backend test suite still green: `cd backend && uv run pytest -q` exits 0 with `2036 passed`.
    - The re-grep output is captured (paste in commit message or summary). Total count of deferred sites identified.
  </acceptance_criteria>
  <done>
    Re-grep complete. Port surface amended (if needed) to cover every InstrumentedAttribute SQL use site. Smoke checks pass. Full suite green.
  </done>
</task>

<task type="auto">
  <name>Task 1: Migrate deferred imports in embeddings/tasks.py and ingest/tasks_vector.py</name>
  <files>backend/app/processing/embeddings/tasks.py, backend/app/processing/ingest/tasks_vector.py</files>
  <read_first>
    - backend/app/processing/embeddings/tasks.py (entire file — line 21 TYPE_CHECKING block)
    - backend/app/processing/ingest/tasks_vector.py (entire file — line 302 build_gdal_source deferred import)
    - backend/app/core/processing_port.py (after Task 0 — confirm aliases)
  </read_first>
  <action>
File 1: `backend/app/processing/embeddings/tasks.py`

The line ~21 contains a TYPE_CHECKING-only import:
```
if TYPE_CHECKING:
    from app.modules.catalog.datasets.domain.models import Dataset, Record
```

Replace with:
```
if TYPE_CHECKING:
    from app.core.processing_port import Dataset, Record
```

No runtime behavior change. The local names `Dataset` and `Record` continue to resolve as type annotations.

If the file uses these names anywhere else as runtime symbols (not just annotations), re-grep first; if found, those become runtime InstrumentedAttribute or constructor uses and need Port methods. RESEARCH.md says line 21 is TYPE_CHECKING only — verify by reading the file end-to-end. If re-grep shows any runtime use, follow Plan 02 patterns (port.method calls).

File 2: `backend/app/processing/ingest/tasks_vector.py`

The line 302 contains:
```
# inside function body (~line 302):
from app.modules.catalog.sources.preview import build_gdal_source
url, layer = build_gdal_source(service_type, base_url, ...)
```

Replace with:
```
# inside function body — keep deferred (D-19)
from app.platform.extensions import get_processing_port
port = get_processing_port()
url, layer = port.build_gdal_source(service_type, base_url, ...)
```

Verify: ruff clean both files; grep for any remaining `from app.modules.catalog` in these two files returns zero.
  </action>
  <verify>
    <automated>cd backend && uv run ruff check app/processing/embeddings/tasks.py app/processing/ingest/tasks_vector.py && grep -REn "(from|import) app\.modules\.catalog" backend/app/processing/embeddings/tasks.py backend/app/processing/ingest/tasks_vector.py | (! grep .); echo "exit=$?"</automated>
  </verify>
  <acceptance_criteria>
    - `grep -c "from app.modules.catalog" backend/app/processing/embeddings/tasks.py` returns 0.
    - `grep -c "from app.modules.catalog" backend/app/processing/ingest/tasks_vector.py` returns 0.
    - `grep -c "from app.core.processing_port import" backend/app/processing/embeddings/tasks.py` returns ≥ 1 (TYPE_CHECKING block).
    - `grep -c "port.build_gdal_source" backend/app/processing/ingest/tasks_vector.py` returns ≥ 1.
    - ruff clean for both files.
    - Targeted tests pass: `cd backend && uv run pytest tests/test_embedding_tasks.py tests/test_ingest_tasks_vector.py tests/test_ingest_*.py -x` exits 0 (or whichever subset covers these files).
    - Full suite still green: `cd backend && uv run pytest -q` exits 0.
  </acceptance_criteria>
  <done>
    `embeddings/tasks.py` TYPE_CHECKING block migrated to Protocol aliases. `ingest/tasks_vector.py:302` `build_gdal_source` deferred call routes through Port. Full suite green.
  </done>
</task>

<task type="auto">
  <name>Task 2: Migrate deferred imports in ingest/tasks_common.py (lines 618, 697, 849)</name>
  <files>backend/app/processing/ingest/tasks_common.py</files>
  <read_first>
    - backend/app/processing/ingest/tasks_common.py (entire file — read all three deferred sites at lines 618, 697, 849 and surrounding code)
    - backend/app/core/processing_port.py (after Task 0)
    - backend/app/modules/catalog/collections/models.py (DatasetVersion model — confirm field shape if needed for type hints)
  </read_first>
  <action>
File: `backend/app/processing/ingest/tasks_common.py`

Three deferred sites need migration:

Site 1 (line ~618): `create_dataset`

BEFORE:
```
from app.modules.catalog.datasets.domain.service import create_dataset
result = await create_dataset(session, ...)
```

AFTER:
```
from app.platform.extensions import get_processing_port
port = get_processing_port()
result = await port.create_dataset(session, ...)
```

Site 2 (line ~697): `IngestionResult` (OQ-1)

BEFORE:
```
from app.modules.catalog.datasets.domain.schemas import IngestionResult
ingestion = IngestionResult(success=True, ...)
```

AFTER:
```
from app.platform.extensions import get_processing_port
port = get_processing_port()
ingestion = port.create_ingestion_result(success=True, ...)
```

(Per Plan 02 Task 0, `port.create_ingestion_result(**kwargs)` is the helper added on the Port. It internally constructs IngestionResult via deferred import in DefaultProcessingPort.)

Site 3 (line ~849): `DatasetVersion` (OQ-2)

BEFORE (the existing pattern is likely):
```
from app.modules.catalog.collections.models import DatasetVersion
result = await session.execute(
    select(DatasetVersion)
    .where(DatasetVersion.dataset_id == dataset_id)
    .order_by(DatasetVersion.version_number.desc())
    .limit(1)
)
version = result.scalar_one_or_none()
# downstream use: version.id, possibly version.version_number, etc.
```

AFTER:
```
from app.platform.extensions import get_processing_port
port = get_processing_port()
version = await port.get_dataset_version(session, dataset_id)
# downstream use: version.id (per DatasetVersionProtocol from Plan 01)
```

If downstream code reads more fields than `version.id` (e.g., `version.version_number`, `version.created_at`), expand `DatasetVersionProtocol` in `core/processing_port.py` (Task 0 amendment). Re-grep `tasks_common.py` for any `version.X` reads to enumerate the fields needed.

If the existing code modifies `DatasetVersion` instances (e.g., `version.is_active = False` for the swap path), that's a write operation. The Port's `get_dataset_version` returns the ORM instance (since `DefaultProcessingPort.get_dataset_version` does the `select(DatasetVersion)` query and returns the result). The returned instance is the concrete ORM class — mutations work. The Protocol just types it as `DatasetVersionProtocol` which is structurally satisfied. No problem.

If the existing code does multi-step DatasetVersion operations (create new, deactivate old, swap), consider adding `port.finalize_dataset_version(session, dataset_id, ...)` as a higher-level Port method that encapsulates the entire swap. **Decision rule**: if the deferred logic is just "fetch latest DatasetVersion", use `port.get_dataset_version`. If it's "create + deactivate + swap", add a new Port method via Task 0 amendment.

Verify: ruff clean. Re-grep zero `from app.modules.catalog` in this file.
  </action>
  <verify>
    <automated>cd backend && uv run ruff check app/processing/ingest/tasks_common.py && grep -REn "(from|import) app\.modules\.catalog" backend/app/processing/ingest/tasks_common.py | (! grep .); echo "exit=$?"</automated>
  </verify>
  <acceptance_criteria>
    - `grep -c "from app.modules.catalog" backend/app/processing/ingest/tasks_common.py` returns 0.
    - `grep -c "port.create_dataset\|port.create_ingestion_result\|port.get_dataset_version" backend/app/processing/ingest/tasks_common.py` returns ≥ 3.
    - No direct `IngestionResult(...)` constructor call remains: `grep -c "IngestionResult(" backend/app/processing/ingest/tasks_common.py` returns 0 (all replaced by `port.create_ingestion_result`).
    - No direct `DatasetVersion` reference remains except via `port.get_dataset_version` return value: `grep -c "DatasetVersion" backend/app/processing/ingest/tasks_common.py` returns 0 (or only in commented-out code).
    - ruff clean.
    - Targeted tests pass: `cd backend && uv run pytest tests/test_ingest_*.py tests/test_reupload*.py -x` exits 0.
    - Full suite still green: `cd backend && uv run pytest -q` exits 0.
  </acceptance_criteria>
  <done>
    Three deferred sites migrated. `create_dataset`, `IngestionResult` constructor, and `DatasetVersion` access all route through Port. Full suite green.
  </done>
</task>

<task type="auto">
  <name>Task 3: Migrate deferred imports in ingest/tasks_reupload.py (lines 38, 257, 273)</name>
  <files>backend/app/processing/ingest/tasks_reupload.py</files>
  <read_first>
    - backend/app/processing/ingest/tasks_reupload.py (entire file — read all three deferred sites and surrounding code)
    - backend/app/core/processing_port.py (after Task 0)
  </read_first>
  <action>
File: `backend/app/processing/ingest/tasks_reupload.py`

Three deferred sites:

Site 1 (line ~38): `Dataset`

Determine via re-grep whether this is type annotation only or SQL InstrumentedAttribute use.

If type annotation only (e.g., used in a function signature `def fn(dataset: Dataset)`): replace with `from app.core.processing_port import Dataset` at the top of the function body or move to a TYPE_CHECKING block at the top of the file.

If SQL InstrumentedAttribute use (e.g., `select(Dataset).where(Dataset.id == ...)`):
- If the query is a simple lookup: replace with `await port.get_dataset(session, dataset_id)` (or `port.get_dataset_with_attributes` if attributes are needed).
- If the query is exotic (multi-condition, joins): use `port.get_dataset_orm_class()` if Task 0 added it, or add it now. Then keep the SQL using the ORM class returned by the helper.

```
# Pattern A (simple lookup):
from app.platform.extensions import get_processing_port
port = get_processing_port()
dataset = await port.get_dataset(session, dataset_id)

# Pattern B (exotic SQL — only if needed):
from app.platform.extensions import get_processing_port
port = get_processing_port()
Dataset = port.get_dataset_orm_class()
result = await session.execute(select(Dataset).where(Dataset.created_by == user_id, Dataset.is_active == True))
```

Site 2 (line ~257): `Dataset` — same analysis as line 38.

Site 3 (line ~273): `build_gdal_source`

BEFORE:
```
from app.modules.catalog.sources.preview import build_gdal_source
url, layer = build_gdal_source(service_type, base_url, ...)
```

AFTER:
```
from app.platform.extensions import get_processing_port
port = get_processing_port()
url, layer = port.build_gdal_source(service_type, base_url, ...)
```

Verify: ruff clean. Zero `from app.modules.catalog` in this file.
  </action>
  <verify>
    <automated>cd backend && uv run ruff check app/processing/ingest/tasks_reupload.py && grep -REn "(from|import) app\.modules\.catalog" backend/app/processing/ingest/tasks_reupload.py | (! grep .); echo "exit=$?"</automated>
  </verify>
  <acceptance_criteria>
    - `grep -c "from app.modules.catalog" backend/app/processing/ingest/tasks_reupload.py` returns 0.
    - `grep -c "port.build_gdal_source\|port.get_dataset\|port.get_dataset_orm_class" backend/app/processing/ingest/tasks_reupload.py` returns ≥ 1.
    - ruff clean.
    - Targeted tests pass: `cd backend && uv run pytest tests/test_reupload*.py -x` exits 0 (or relevant subset).
    - Full suite still green: `cd backend && uv run pytest -q` exits 0.
  </acceptance_criteria>
  <done>
    `tasks_reupload.py` Dataset and build_gdal_source deferred imports migrated. Full suite green.
  </done>
</task>

<task type="auto">
  <name>Task 4: Migrate deferred imports in ingest/tasks_vrt.py and ingest/tasks_raster.py (resolve OQ-4 for line 143)</name>
  <files>backend/app/processing/ingest/tasks_vrt.py, backend/app/processing/ingest/tasks_raster.py</files>
  <read_first>
    - backend/app/processing/ingest/tasks_vrt.py (entire file — lines 51, 165, 283, 362)
    - backend/app/processing/ingest/tasks_raster.py (entire file — lines 47, 143, 301)
    - backend/app/core/processing_port.py (after Task 0)
    - .planning/phases/225-processing-port-protocol-cycle-inversion/225-RESEARCH.md (§Open Questions OQ-4)
    - .planning/phases/225-processing-port-protocol-cycle-inversion/225-VALIDATION.md (Manual-Only Verifications: tasks_raster.py:143)
  </read_first>
  <action>
File 1: `backend/app/processing/ingest/tasks_vrt.py`

Four deferred sites at lines 51, 165, 283, 362. Each imports some combination of `Dataset`, `Record`, `RecordDistribution`. Read each site to classify:

(a) Type annotation only — replace with `from app.core.processing_port import Dataset, Record` (Protocol aliases). For `RecordDistribution`, if Task 0 added `RecordDistributionProtocol`, use `from app.core.processing_port import RecordDistribution`.

(b) SQL InstrumentedAttribute — replace with appropriate Port method (`port.get_dataset`, `port.get_record`) or Port helper (`port.get_dataset_orm_class`, `port.get_record_distribution_orm_class` from Task 0).

(c) Constructor use (e.g., `Dataset(...)`)— very unlikely in worker tasks; if found, raise as a finding and add a `port.create_*` helper.

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
- Keep removal. Document in 225-03-SUMMARY.md.
- No D-23 amendment needed.

Outcome B — removal fails (worker startup fails because `Dataset` is not registered in `Base.metadata`):
- Restore the import: `from app.modules.catalog.datasets.domain.models import Dataset  # noqa: F401`.
- This is now the SOLE allowlist exception. D-23 needs amendment (which Plan 04's architecture-guard test must reflect via a `:!backend/app/processing/ingest/tasks_raster.py` pathspec exclusion).
- Document the outcome and its implications in 225-03-SUMMARY.md so Plan 04 can wire the exclusion correctly.

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
    - OQ-4 outcome (Outcome A or B) documented in eventual 225-03-SUMMARY.md with the test-run evidence.
  </acceptance_criteria>
  <done>
    `tasks_vrt.py` and `tasks_raster.py` deferred imports migrated. OQ-4 resolved (Outcome A: removal; or Outcome B: kept with line-143 exclusion noted for Plan 04). Full suite green.
  </done>
</task>

<task type="auto">
  <name>Task 5: Migrate deferred imports in ingest/metadata.py (TYPE_CHECKING + 5 SQL sites)</name>
  <files>backend/app/processing/ingest/metadata.py</files>
  <read_first>
    - backend/app/processing/ingest/metadata.py (entire file — TYPE_CHECKING at line 18, deferred sites at lines 466, 1076, 1102, 1130, 1188)
    - backend/app/core/processing_port.py (after Task 0 — confirm get_record_keyword_count, get_attribute_metadata, get_catalog_vocabulary, get_related_keywords)
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

For any other deferred SQL pattern not covered (e.g., a more complex AttributeMetadata join), evaluate whether to add a new Port method (Task 0 amendment) or use `port.get_dataset_orm_class()` to keep the SQL with the ORM class.

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
  <name>Task 6: Migrate deferred imports in ingest/router.py (lines 819, 1005) and ingest/service.py (lines 320, 368, 405)</name>
  <files>backend/app/processing/ingest/router.py, backend/app/processing/ingest/service.py</files>
  <read_first>
    - backend/app/processing/ingest/router.py (entire file — focus on lines 819, 1005)
    - backend/app/processing/ingest/service.py (entire file — focus on lines 320, 368, 405)
    - backend/app/core/processing_port.py (after Task 0)
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
must return ZERO HITS (or, if OQ-4 Outcome B was chosen in Task 4, exactly 1 hit at `tasks_raster.py:143`). All other deferred imports across all 9 files are migrated. Plan 04's architecture-guard test can now be safely added.

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
| T-225-03 | (n/a) | Phase 225 surface | accept | Refactor-only — no new attack surface introduced. Function-scope deferred imports relocate path; calls route through DefaultProcessingPort which delegates byte-for-byte to the same catalog functions. Worker tasks remain in their existing process boundaries; Procrastinate semantics unchanged. Threats inherited from existing catalog services. |

**Block:** false. Refactor only.
</threat_model>

<verification>
- Phase-wide grep returns zero hits (or 1 allowlisted hit per OQ-4 Outcome B): `grep -REn '^[[:space:]]*(from|import) app\.modules\.catalog' backend/app/processing/ | wc -l` returns 0 (or 1 if Outcome B)
- `cd backend && uv run pytest -q` returns `2036 passed`
- `cd backend && uv run ruff check app/processing/` clean
- `cd backend && uv run alembic check` no new operations
- All 9 modified processing files compile and pass their targeted tests
- (Plan 04's architecture-guard test will land in Wave 3, sealing the boundary in CI)
</verification>

<success_criteria>
- All ~24 function-scope deferred catalog imports across 9 processing files migrated
- Deferral discipline preserved (D-19) — imports still inside function bodies
- After this plan: `grep -REn '^[[:space:]]*(from|import) app\.modules\.catalog' backend/app/processing/` returns zero hits (or exactly 1 at `tasks_raster.py:143` per OQ-4 Outcome B)
- `IngestionResult` constructor uses replaced by `port.create_ingestion_result(**kwargs)` (OQ-1)
- `DatasetVersion` access at `tasks_common.py:849` routed through `port.get_dataset_version` (OQ-2)
- `tasks_raster.py:143` `# noqa: F401` resolution documented (OQ-4 Outcome A or B)
- Full backend test suite green at 2036/2036 baseline
- ruff clean
- alembic clean
</success_criteria>

<output>
After completion, create `.planning/phases/225-processing-port-protocol-cycle-inversion/225-03-SUMMARY.md` with:
- 9 files migrated, line-count delta per file
- Total deferred-import sites migrated (target: ~24 sites)
- Final phase-wide grep result: ZERO hits (or 1 allowlisted hit at `tasks_raster.py:143`)
- OQ-1 outcome: `IngestionResult` constructor calls migrated to `port.create_ingestion_result`
- OQ-2 outcome: `DatasetVersion` access migrated to `port.get_dataset_version`
- OQ-3 outcome: any additional Port methods added in Task 0 (with rationale and consuming sites)
- OQ-4 outcome: Outcome A (removed) or Outcome B (retained as single exception). If Outcome B, explicit instruction to Plan 04 to add `:!backend/app/processing/ingest/tasks_raster.py` pathspec exclusion to the architecture-guard test, and a corresponding `D-23` amendment note in CONTEXT.md.
- Confirmation that 2036/2036 baseline holds
- Confirmation that all existing architecture guards still pass
- Plan 04 readiness statement: "The boundary is now clean (or has 1 documented exception). Plan 04 can safely add `test_no_processing_imports_catalog`."
</output>
</content>
</invoke>
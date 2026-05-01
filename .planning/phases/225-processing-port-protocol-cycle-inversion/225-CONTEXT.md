# Phase 225: processing-port-protocol-cycle-inversion - Context

**Gathered:** 2026-05-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Cross-domain code stops depending on the concrete `app.modules.catalog.*` ORM/service surface and depends instead on a structural `ProcessingPort` Protocol defined in `backend/app/core/processing_port.py`. The Port mirrors Phase 214's `IdentityProtocol` pattern: stdlib-typed structural Protocols, comprehensive read+write surface covering every cross-domain catalog accessor `processing/*` needs today, runtime-checkable, and accompanied by an extension hook so future overlays (tier-aware quotas, audit-emitting catalog wrappers) can replace the implementation without touching core. After this phase:

- `backend/app/core/processing_port.py` is a NEW file. It defines:
  - `ProcessingPort` — the comprehensive Protocol capturing every catalog accessor `processing/*` calls today (read-side: `get_dataset`, `get_record`, `search_datasets`, `apply_visibility_filter`, `check_dataset_access`, `get_user_roles`, `get_column_stats`, `get_distinct_values`, `extract_bbox_from_record`; write-side: `create_dataset`, `create_map`, `update_map`).
  - Companion structural Protocols where ORM types cross the boundary: `DatasetProtocol`, `RecordProtocol`, `MapProtocol`, `DatasetGrantProtocol` (slim — only the fields `processing/*` actually reads, mirroring Phase 214's `RoleProtocol` discipline).
  - `ProcessingPortExtension` — the enterprise/overlay registration contract; one `get_port() -> ProcessingPort` factory method so an overlay can return a tier-aware/quota-enforcing wrapper. Mirrors `IdentityExtension` exactly.
- `backend/app/platform/extensions/defaults.py` adds `DefaultProcessingPort` — community-edition implementation. Each method does a deferred import into `app.modules.catalog.*` and delegates to the existing function (mirrors Phase 222's `DefaultAuditSink.emit()` pattern: deferred imports keep `platform/extensions/` free of module-load-time `modules.*` edges; behavior is unchanged).
- `backend/app/platform/extensions/__init__.py` exposes a typed accessor `get_processing_port() -> ProcessingPort` registered under `_extensions["processing_port"]`, falling back to `DefaultProcessingPort()`. Mirrors `get_identity_extension()` exactly (single-slot, NOT list-shaped — `ProcessingPort` is a singleton consumer surface, not a fan-out hook like `AuditSink`/`BillingExtension`).
- All 8 processing files (~20 module-level imports + ~24 function-scope deferred imports — full inventory below) swap `from app.modules.catalog.X import Y` → `from app.core.processing_port import DatasetProtocol|RecordProtocol|...` for type annotations + `port = get_processing_port()` + `port.method(...)` for the actual call. Function-scope deferred imports keep the deferral (Phase 213 D-04 / Phase 214 D-08 discipline); only the path swaps.
- A new `@pytest.mark.architecture` test in `backend/tests/test_layering.py` named `test_no_processing_imports_catalog` enforces that `^(from|import)\s+app\.modules\.catalog` returns zero hits under `backend/app/processing/`. Mirrors Phase 222's `test_no_log_action_calls_outside_audit_service` (line 421) and Phase 224's `test_no_external_imports_of_dataset_domain_submodules` (line 333) patterns. Strict zero-hit, NO allowlist — `processing/*` has no legitimate side-effect catalog imports today (verified by codebase scan).
- The full backend test suite (2036/2036 v13.3 baseline per STATE.md) stays green with `DefaultProcessingPort` wired in — zero functional regressions because the default implementation just forwards to the existing catalog functions.
- The catalog → processing direction (51 import lines under `backend/app/modules/catalog/` reaching into `app.processing.*` — driven by routers/services orchestrating ingest tasks, embedding services, raster registration, export helpers) is **NOT touched** by Phase 225. The audit P0 #2 only flags the `processing → catalog` direction; the reverse direction is the natural top-down driver shape.
- The architecture-guard test ALSO inlines former Phase 999.11 (per ROADMAP §225 note) — the guard ships in the same phase as the inversion because adding it before the inversion would fail CI immediately.

**Allowlist — sites that legitimately keep `from app.modules.catalog` imports:**
- **None under `backend/app/processing/`.** Codebase scan confirms zero side-effect-only catalog imports in processing/* (unlike Phase 214 where `tasks_raster.py:142` legitimately registers `User` for `Base.metadata` in the Procrastinate worker — there's no equivalent for catalog ORM because catalog models are transitively pulled in via `app.api.main` and the `app.modules.catalog` module loader). Strict zero-hit guard.
- The architecture-guard's pathspec excludes `backend/tests/` (tests construct catalog ORM objects directly, structurally satisfying the Protocols at the call site).

**In scope:** create `core/processing_port.py` (Protocol surface + companion structural Protocols + `ProcessingPortExtension` hook); create `DefaultProcessingPort` + `get_processing_port()` accessor in `platform/extensions/`; migrate the 8 processing files (top-level + function-scope) — including AI features (`chat_service.py`, `metadata_service.py`, `embeddings/backfill.py`); add the `test_no_processing_imports_catalog` architecture-guard test; verify the 2036/2036 baseline + alembic check + ruff.

**Out of scope:** any change to catalog→processing imports (the legitimate top-down direction); any change to behavior of the catalog services themselves (`create_dataset`, `search_datasets`, etc.); any AI provider abstraction (Phase 226 owns that — `AIProviderExtension`); any new `PermissionExtension` (Phase 999.8 backlog supersedes the authorization-helper inclusion in `ProcessingPort` later); any `CatalogReadPort` for non-processing read-only consumers (audit-26-b §7 P2 #4 — separate phase); any Alembic migration; any frontend change; any change to `processing/ingest/tasks_raster.py:142`'s `User` side-effect import (allowlisted by Phase 214 — out of Phase 225's scope); any change to FastAPI dependency injection patterns at the route layer (routes can still use `Depends(get_processing_port)` if convenient, but the wire-in is allowed to be a direct module-level call to `get_processing_port()` like `get_audit_sinks()`).

</domain>

<decisions>
## Implementation Decisions

### Protocol surface

- **D-01:** `ProcessingPort` is a **single comprehensive Protocol** mirroring Phase 214's `IdentityProtocol` D-01 reasoning. The audit P0 #2 says "mirror Phase 214 IdentityProtocol pattern"; ROADMAP §225 binds the goal to "ProcessingPort Protocol." A narrower per-call-site decomposition (e.g., `DatasetReadPort`, `MapWritePort`, `SearchPort`, `AuthzPort`) would force the 8 processing files to take 3+ Port dependencies each and split test seams across multiple stubs. Comprehensive lets every processing site receive ONE port and call all the methods it needs. The audit's P2 #4 `CatalogReadPort` for non-processing read-only consumers is a separate, later phase.

- **D-02:** Companion **structural Protocols** for ORM types crossing the boundary: `DatasetProtocol`, `RecordProtocol`, `MapProtocol`, `DatasetGrantProtocol`. Each captures only the fields `processing/*` reads today (mirrors Phase 214 `RoleProtocol`'s `name: str` discipline). Sample shapes:
  - `DatasetProtocol`: `id: UUID`, `record_id: UUID`, `geometry_type: str | None`, `feature_count: int | None`, `bbox: tuple | None`, `attributes: Sequence[AttributeProtocol]`, `record: RecordProtocol`, `table_name: str | None`, `srid: int | None`.
  - `RecordProtocol`: `id: UUID`, `title: str`, `summary: str | None`, `keywords: Sequence[KeywordProtocol]`, `bbox: tuple | None`, `created_at: datetime`.
  - `MapProtocol`: `id: UUID`, `name: str`, `owner_id: UUID`, `layers: Sequence[LayerProtocol]`.
  - `DatasetGrantProtocol`: `id: UUID`, `dataset_id: UUID`, `user_id: UUID`, `role: str`.
  Concrete catalog ORM classes (`Dataset`, `Record`, `Map`, `DatasetGrant`) satisfy the Protocols structurally — no inheritance, no class-level conformance assertion. Mirrors Phase 214 D-06.

- **D-03:** **`@runtime_checkable`** on every Protocol (mirrors `IdentityProtocol` D-04, `AuditSink`, `BillingExtension`). Enables future `isinstance(x, DatasetProtocol)` checks if Phase 226+ overlays need them; cost is negligible.

- **D-04:** Type aliases for caller annotations: `Dataset = DatasetProtocol`, `Record = RecordProtocol`, `Map = MapProtocol`, `DatasetGrant = DatasetGrantProtocol`. Reason: `dataset: Dataset` reads cleaner than `dataset: DatasetProtocol` and matches Phase 214 D-05's `Identity = IdentityProtocol` convention. Both names exported. **Conflict mitigation:** the concrete ORM types `Dataset`, `Record`, `Map`, `DatasetGrant` live in `app.modules.catalog.datasets.domain.models` / `.maps.models` — caller files that previously did `from app.modules.catalog.datasets.domain.models import Dataset` swap entirely to `from app.core.processing_port import Dataset` (the alias). The local name `Dataset` is preserved at the call site; only the import path moves. Identical to Phase 214's `User` → `Identity` rename pattern.

- **D-05:** **No** `is_*` derived properties on the Port Protocols (e.g., no `is_published`, no `is_authorized_for_user`). Audit-26-b precedent (Phase 214 D-02 rejected `is_admin`): derived predicates are computed by callers from raw attributes, not exposed as Protocol fields. Authorization checks call `port.check_dataset_access(session, dataset_id, user)` (an explicit method, not a Protocol field).

### Method surface — what `ProcessingPort` exposes

- **D-06:** **Read-side methods** (cover every cross-domain read in `processing/*`):
  - `async get_dataset(session, dataset_id: UUID) -> DatasetProtocol | None` — used by `ai/router.py`, `ai/service.py`, `ai/metadata_service.py`, `tiles/router.py`, `export/router.py`, `ingest/service.py`, `ingest/tasks_*.py` (many sites). Replaces `from app.modules.catalog.datasets.domain.models import Dataset` + direct `select(Dataset)` queries.
  - `async get_record(session, record_id: UUID) -> RecordProtocol | None` — used by AI metadata service + embeddings backfill.
  - `async search_datasets(session, filters: "SearchFilters", user: Identity) -> "SearchResult"` — used by `ai/service.py`. The `SearchFilters` and `SearchResult` types are forward-referenced via `TYPE_CHECKING` (mirrors `protocols.py:18-19`'s `AuditEvent` forward-ref) — they stay in `app.modules.catalog.search.service` because they're catalog-domain types, not core types.
  - `apply_visibility_filter(stmt, user: Identity, *, role_check: str = "viewer") -> Select` — synchronous (matches today's `catalog/authorization.py:34` shape). Used by `ai/service.py`, `tiles/router.py`. Returns the SQLAlchemy `Select` with the visibility predicate applied; callers chain additional `.where(...)` / `.options(...)` clauses.
  - `async check_dataset_access(session, dataset_id: UUID, user: Identity, *, role: str = "viewer") -> bool` — used by `tiles/router.py`, `export/router.py`. Wraps the existing `catalog/authorization.py:check_dataset_access`.
  - `async get_user_roles(session, user: Identity) -> set[str]` — used by `ai/router.py`, `tiles/router.py`, `ingest/service.py`. Wraps `catalog/authorization.py:get_user_roles`.
  - `async get_column_stats(session, dataset_id: UUID, column: str) -> "ColumnStats"` — used by `ai/service.py`, `ai/chat_service.py`. Forward-referenced return type.
  - `async get_distinct_values(session, dataset_id: UUID, column: str, *, limit: int = 100) -> Sequence[str]` — used by `ai/chat_service.py`.
  - `extract_bbox(record: RecordProtocol) -> tuple[float, float, float, float] | None` — synchronous utility; mirrors `catalog/datasets/domain/utils.py:extract_bbox`. Used by `ai/service.py`.

- **D-07:** **Write-side methods** (the AI-feature + ingest mutation surface):
  - `async create_dataset(session, payload: "DatasetCreatePayload", user: Identity) -> DatasetProtocol` — used by `ingest/service.py`, `ingest/tasks_common.py`. The `DatasetCreatePayload` type is a forward-referenced schema.
  - `async create_map(session, spec: "MapSpec", user: Identity) -> MapProtocol` — used by `ai/service.py`. Wraps `catalog/maps/service.py:create_map`.
  - `async update_map(session, map_id: UUID, spec: "MapSpec", user: Identity) -> MapProtocol` — used by `ai/service.py`, `ai/chat_service.py`. Wraps `catalog/maps/service.py:update_map`.

- **D-08:** **Source preview helper** for ingest workers — `build_gdal_source(...)` is exposed via the Port: `port.build_gdal_source(...)`. Used by `ingest/tasks_vector.py:302`, `ingest/tasks_reupload.py:273`. The exact signature matches today's `catalog/sources/preview.py:build_gdal_source` 1:1 (planner re-grep at plan time to confirm).

- **D-09:** **No new domain logic in `DefaultProcessingPort`** — every method is a thin `async def get_dataset(self, session, dataset_id): from app.modules.catalog.datasets.domain.service import get_dataset; return await get_dataset(session, dataset_id)` shape. Mirrors `DefaultAuditSink.emit()` exactly (Phase 222 D-04 / `defaults.py:62-76`). Reason: the Port is the seam, not a re-implementation. Behavior must match the pre-phase-225 baseline byte-for-byte; the deferred import keeps `platform/extensions/defaults.py` free of `modules.catalog` edges at module-load time.

### Default impl + accessor location

- **D-10:** **Protocol surface lives in `backend/app/core/processing_port.py`** (NEW file) — mirrors Phase 214 D-12's reasoning (`core/identity.py`). Consumer-facing types belong in `core/` because the 8 processing files annotate against them and `core/` is the lowest layer (Phase 214 IDENT-01 architecture-guard already enforces `core/ → modules/` is forbidden, so `core/processing_port.py` is forced to use only stdlib + structural typing). The file's docstring follows the `core/identity.py:1-20` template — credit Phases 214/222/223/225, list the comprehensive surface, point to overlay extensibility.

- **D-11:** **Default implementation lives in `backend/app/platform/extensions/defaults.py`** as `DefaultProcessingPort` — mirrors `DefaultIdentityExtension` (Phase 214 D-14 / `defaults.py:27-43`) and `DefaultAuditSink` (Phase 222 / `defaults.py:46-76`). Reason: `platform/extensions/` is the layer allowed to reach into `app.modules.*` (only `core/` is forbidden per Phase 214 IDENT-01); the deferred-import pattern in `DefaultAuditSink.emit()` is the established discipline for keeping module-load order clean.

- **D-12:** **Typed accessor `get_processing_port() -> ProcessingPort`** lives in `backend/app/platform/extensions/__init__.py`, registered under `_extensions["processing_port"]`, falling back to `DefaultProcessingPort()` when no overlay registers. Single-slot shape (NOT list-shape like `get_audit_sinks()` / `get_billing_extensions()`) — mirrors `get_identity_extension()` exactly (single Port instance per deployment; overlays REPLACE rather than APPEND). Reason: ProcessingPort is a consumer surface (callers pull data); only one impl is in use per deployment.

- **D-13:** **No `ProcessingPortExtension` registration helper** — the Port itself is what overlays register. An overlay's `register_extensions(registry)` callback does:
  ```python
  registry["processing_port"] = TierAwareProcessingPort(quota_config)
  ```
  No nested `Extension` Protocol that returns a Port (which would be the BillingExtension shape). Reason: the overlay is responsible for instantiating the wrapper Port; making them go through a `get_port()` factory adds a layer of indirection without value. Phase 226 (AIProviderExtension) is a different shape because providers fan out by name; ProcessingPort is single-instance. **One exception** — if the overlay genuinely needs lifecycle access (e.g., async startup), the `BillingExtension` pattern can be added in a later phase; Phase 225 ships the simpler shape.

### Wire-in pattern

- **D-14:** **Two wire-in shapes** depending on caller context:
  - **HTTP routes** (`processing/*/router.py`, `processing/ingest/router.py`, `processing/tiles/router.py`, `processing/ai/router.py`, `processing/export/router.py`): use `port: ProcessingPort = Depends(get_processing_port)` FastAPI dependency. The dep function in `platform/extensions/__init__.py` returns `get_processing_port()` (or routes can call `get_processing_port()` directly — both shapes work). Default to FastAPI Depends for routes because it composes with existing `Depends(get_db)`, `Depends(get_optional_user)` etc. cleanly.
  - **Worker task functions** (`processing/ingest/tasks_*.py`, `processing/embeddings/backfill.py`, `processing/embeddings/tasks.py`): call `get_processing_port()` directly at the top of the task body. Workers don't go through FastAPI dependency injection (Procrastinate task functions take plain args). The deferred-import pattern is preserved — same as today's `from app.modules.catalog.datasets.domain.models import Dataset` deferred imports, just swapped to `from app.platform.extensions import get_processing_port`.

- **D-15:** **Service-layer functions** (e.g., `ai/service.py:generate_map_from_prompt`, `ai/chat_service.py:chat_edit_map`, `ai/metadata_service.py:_build_dataset_context`): take `port: ProcessingPort` as an explicit parameter rather than reaching for `get_processing_port()` internally. Reason: explicit parameters are testable (the focused unit test required by ROADMAP SC#5 swaps in a `FakeProcessingPort` via the parameter) and match the existing pattern of passing `session: AsyncSession` and `user: Identity` explicitly. Callers (routes, worker tasks) acquire the port via D-14 and forward it.

- **D-16:** **No FastAPI dep stub at `auth/dependencies.py`** — `get_processing_port` is NOT in auth/. It lives in `platform/extensions/__init__.py` next to `get_identity_extension()`. Rationale: the Port is not auth-scoped. Auth/dep retypes happen in `auth/dependencies.py` (Phase 214); extension accessors live in `platform/extensions/`.

### Caller migration

- **D-17:** **Two coordinated changes deliver the migration:** (1) introduce `core/processing_port.py` + `DefaultProcessingPort` + `get_processing_port()` accessor — pure additive, no behavior change; (2) rewrite the 8 processing files (top-level + function-scope) to swap `from app.modules.catalog.X import Y` for `from app.core.processing_port import Y` (Protocol-typed alias) + `port = get_processing_port()` + `port.method(...)` calls.

- **D-18:** **Closed-set migration via `git grep`** — Phase 212/213/214/222 used `git grep` (not `import-linter`) to enumerate callers and to enforce the layering boundary. Phase 225 inherits this. Do NOT introduce `import-linter` or any architecture-DSL dependency. The architecture-guard test (D-22) is the regression seal.

- **D-19:** **Function-scope deferred imports migrate too** — the ~24 function-scope `from app.modules.catalog.X import Y` sites under `processing/ingest/tasks_*.py` + `processing/ingest/router.py` + `processing/ai/*` rewrite to `from app.platform.extensions import get_processing_port; port = get_processing_port(); ... = await port.X(...)`. The deferral itself is preserved (Phase 213 D-04 discipline — circular-import safety, slow-startup mitigation); only the path swaps. Reason: ROADMAP §225 SC#2 grep is strict (`grep -RE "from backend.app.modules.catalog|from app.modules.catalog" backend/app/processing/ returns zero hits`) — top-level + function-scope both match the pattern.

- **D-20:** **No backward-compat re-export shim** — no `Dataset = ...` re-export in `app.modules.catalog`, no `processing_port` alias in `core/`. Phase 212 D-04, Phase 213 D-04, Phase 214 D-10 set this discipline. Hard cutover. The migration is mechanical: `git grep` + ruff + the architecture-guard test are the safety net.

- **D-21:** **Mandatory planner step:** run `git grep -nE "^(from|import)\s+app\.modules\.catalog" -- backend/app/processing/` and confirm every hit is on the migration list. Re-run after edits to confirm zero hits remain. If new hits appear (e.g., a recently-added processing file imports catalog), migrate them too.

### Architecture guard

- **D-22:** Add ONE new `@pytest.mark.architecture` test to `backend/tests/test_layering.py`:
  - **`test_no_processing_imports_catalog`** — fails CI if any line under `backend/app/processing/` matches `^\s*(from|import)\s+app\.modules\.catalog`. Mirrors the Phase 222 `test_no_log_action_calls_outside_audit_service` (line 421) structure: `git grep` + pathspec exclusion (excludes `backend/tests/` and excludes the test file itself), `_has_git_metadata()` skip guard, `_has_pathspec_magic()` git-version check, fail with offending lines. Maps directly to ROADMAP SC#2 / SC#3.

- **D-23:** **Strict zero-hit, NO allowlist for processing/*** — codebase scan confirms no legitimate side-effect catalog imports exist in `processing/*` today. (Compare with Phase 214's `User` allowlist — `tasks_raster.py:142` registers `User` for `Base.metadata` because the Procrastinate worker doesn't transitively import it; catalog ORM classes are transitively imported via the catalog module loader, so no equivalent side-effect import is needed for catalog.) The pathspec excludes only `backend/tests/` (test fixtures construct catalog ORM objects directly, structurally satisfying the Protocols).

- **D-24:** **Test marker `@pytest.mark.architecture`** — already registered in `backend/pyproject.toml` since Phase 212-03. No new marker.

- **D-25:** **Update `test_layering.py` module docstring** to credit Phase 225 alongside 212/213/214/222/223/224. Same pattern as Phase 214 D-20.

- **D-26:** **Negative-control verification** — the planner verifies the guard works: temporarily reintroduce `from app.modules.catalog.datasets.domain.models import Dataset` in (e.g.) `processing/embeddings/backfill.py`, run the test, confirm it fails with the offending line. Revert. This step is the verification gate per ROADMAP SC#3 ("intentionally adding a forbidden import causes the test to fail in CI").

### Test seam

- **D-27:** **Focused unit test with `FakeProcessingPort`** — required by ROADMAP §225 SC#5 ("verifiable by … a focused unit test that swaps in a fake `ProcessingPort`"). Test lives in `backend/tests/test_processing_port.py` (NEW file). Constructs a minimal `FakeProcessingPort` with canned return values for `get_dataset`, `search_datasets`, etc.; passes it explicitly to one or more AI service functions (per D-15's "service-layer functions take port as parameter"); asserts the AI function produces the expected output. Single high-signal test; not a full coverage sweep. The architecture-guard test + the existing 2036/2036 backend baseline are the broader correctness gate.

- **D-28:** **No runtime conformance test** — Phase 214 D-21's reasoning applies: `User` ORM structurally satisfies `IdentityProtocol`; same for catalog ORM and the new Port-side Protocols. A runtime `isinstance(Dataset(), DatasetProtocol)` test adds marginal value when the full pytest exercise already runs the dep chain end-to-end.

### Migration & verification

- **D-29:** **No Alembic migration** — the catalog ORM classes are NOT moved or modified; only the consumers' import paths and parameter annotations change. Verification step (mirrors Phase 214 D-23): after the refactor, run `cd backend && uv run alembic check` and confirm "no new operations." A non-empty diff means the refactor accidentally touched a catalog model and the planner stops.

- **D-30:** **Acceptance gate = 2036/2036 backend tests + ruff + architecture-guard** — per STATE.md (v13.3 close), the baseline is 2036/2036 passing. Phase 225's verification gate is identical to Phase 214's D-24: full pytest run, ruff clean, alembic check clean, the new `test_no_processing_imports_catalog` test passing, and the negative-control demonstration (D-26) showing the guard works.

- **D-31:** **No frontend involvement** — zero HTTP contract change. Phase 225 is a pure backend refactor. `make openapi-check` continues to pass without regenerating `backend/openapi.json`.

- **D-32:** **Phase 226 dependency relationship** — Phase 226 (AIProviderExtension) depends on Phase 225 because both touch `processing/ai/`. Sequencing: Phase 225 lands first, lays the Port, leaves `processing/ai/llm_loop.py:117,132` and `service.py:387-398` for Phase 226 to handle the AI provider seam. The architecture-guard test from Phase 225 stays clean during Phase 226's edits because Phase 226 doesn't add any `from app.modules.catalog` imports — it splits provider dispatch within `processing/ai/`.

- **D-33 [informational]:** Phase 225 does NOT pre-empt Phase 999.8 (`PermissionExtension`). The authorization helpers (`apply_visibility_filter`, `check_dataset_access`, `get_user_roles`) live on `ProcessingPort` for now; when Phase 999.8 lands, it can refactor them out of the Port into a dedicated `PermissionExtension` Protocol. Phase 225 doesn't pretend to solve the authorization seam — it just relocates the access path so the catalog-coupling is no longer at the import-level.

### Claude's Discretion

- **Commit decomposition** — likely 4 atomic commits mirroring Phases 212/213/214/222: (1) introduce `core/processing_port.py` (Protocol + companion structural Protocols); introduce `DefaultProcessingPort` in `platform/extensions/defaults.py`; introduce `get_processing_port()` in `platform/extensions/__init__.py` — pure additive, zero behavior change. (2) Migrate the 8 module-level top-of-file imports across `ai/{service,router,chat_service,metadata_service}.py`, `tiles/router.py`, `export/router.py`, `embeddings/backfill.py`, `ingest/service.py`. Includes the parameter-annotation rewrite (D-15) for service-layer functions. (3) Migrate the ~24 function-scope deferred imports across `ingest/tasks_*.py`, `ingest/router.py`, `ingest/metadata.py`, `ingest/service.py` (lines 320, 368, 405). Mechanical sweep. (4) Add `test_no_processing_imports_catalog` to `test_layering.py`; update module docstring; add `tests/test_processing_port.py` with `FakeProcessingPort` seam test; phase verification gate (alembic check + full pytest + ruff + ROADMAP SC verification + negative-control). Planner may collapse, split, or reorder based on dependency ordering and file-size budgets. Whichever decomposition is chosen, every commit must keep the test suite green — the architecture-guard test (commit 4) MUST land last because it fails until cross-domain catalog imports are gone.

- **Module docstring wording** in `core/processing_port.py` — keep the spirit of `core/identity.py:1-20` and `platform/extensions/protocols.py:1-9` ("Uses only stdlib types to avoid circular imports with domain models") plus a one-liner pointing to the milestone (Phase 225 / PROCESS-01..05) and Phase 226 as the next consumer. Planner picks exact wording.

- **Whether to refactor any catalog helper functions during the migration** — default is NO. If the planner sees a trivial dead-import or unused-name cleanup along the way (e.g., a router that imports `Dataset` but never references it after the annotation rewrite), removal is allowed; anything bigger is deferred to a future cleanup pass.

- **Method naming** — the Port method names mirror the existing catalog function names exactly (`get_dataset`, `search_datasets`, etc.) for grep-ability; if a name conflict arises (unlikely; the Port methods live in a different namespace) the planner picks a disambiguating prefix and documents it.

- **`SearchFilters` / `SearchResult` / `MapSpec` / `DatasetCreatePayload` / `ColumnStats` types** — left as forward-referenced in `core/processing_port.py` per D-06/D-07. Their concrete definitions stay in `app.modules.catalog.search.service`, `.maps.schemas`, etc. Planner verifies the forward references resolve cleanly under `from __future__ import annotations` (they do; `if TYPE_CHECKING:` block at the top of `core/processing_port.py` will import them for typing).

- **AI service signature changes** — `processing/ai/service.py:generate_map_from_prompt`, `stream_generate_map`, `chat_edit_map` get a `port: ProcessingPort` parameter added (per D-15). Their callers (`processing/ai/router.py`) supply the port from FastAPI Depends. Planner can choose whether to make `port` keyword-only or positional; default is keyword-only with no default value (forcing every caller to pass it explicitly). Callers in tests must pass a `FakeProcessingPort` or `DefaultProcessingPort()`.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Audit / spec

- `docs-internal/audits/oc-separation-audit-20260430-b.md` §5 (Codebase Coupling — catalog ↔ processing 16 → 19 files regression, +18%; new edges in `chat_service.py`, `metadata_service.py`, `embeddings/backfill.py`) — the source spec for Phase 225's existence. §7 P0 #2 ("Break catalog ↔ processing two-way cycle via `ProcessingPort` Protocol in `core/` (mirror Phase 214 IdentityProtocol pattern). Invert each of 8 processing→catalog imports.") is the binding directive.
- `docs-internal/audits/oc-separation-audit-20260430-b.md` §7 P1 #5 (`test_layering.py::test_no_processing_imports_catalog` guard recommendation) — formerly Phase 999.11; ROADMAP §225 inlines it into this phase because adding the guard before the inversion would fail CI immediately.
- `.planning/REQUIREMENTS.md` §PROCESS-01..05 — the five requirements this phase closes.
- `.planning/ROADMAP.md` §Phase 225 — goal statement + 5 success criteria. SC#2's `grep` is binding (strict zero-hit). SC#5's "fake ProcessingPort" unit test is binding (D-27).

### Project / state

- `.planning/PROJECT.md` — milestone overview; v13.4 audit-grade target Coupling Health B → **B+** is delivered by Phase 225.
- `.planning/STATE.md` — confirms 2036/2036 backend test baseline (post-v13.3 close, 2026-05-01) and v13.4 phase queue. §"v13.4 Design Decisions Pending" lists the questions Phase 225 resolves: Port surface area (single comprehensive vs per-call-site — resolved D-01), default impl location (resolved D-10/D-11).
- `.planning/MILESTONES.md` — milestone closure history.

### Phase 214 IdentityProtocol — the canonical pattern

- `.planning/milestones/v13.1-phases/214-identity-protocol-extract/214-CONTEXT.md` — the canonical pattern reference. Read end-to-end. Phase 225 mirrors D-01 (comprehensive surface), D-04 (`@runtime_checkable`), D-05 (type alias for caller annotations), D-06 (no concrete-class modification), D-08 (allowlist discipline), D-10 (no shim), D-12 (extension hook), D-14 (Default impl in `platform/extensions/defaults.py`), D-18 (architecture-guard test), D-23 (no Alembic migration), D-24 (full pytest baseline as gate), D-26 (no frontend change).
- `.planning/milestones/v13.1-phases/214-identity-protocol-extract/214-RESEARCH.md` (if generated by `/gsd-plan-phase`) — pitfall list including `_has_git_metadata()` skip guard, `_has_pathspec_magic()` git-version check, deferred-import discipline. Phase 225 inherits all of these.
- `backend/app/core/identity.py` — the pattern `core/processing_port.py` mirrors. Read for module docstring, Protocol decoration, alias style, extension Protocol shape.

### Phase 222 AuditSink — the canonical default-impl pattern

- `backend/app/platform/extensions/defaults.py:46-76` (`DefaultAuditSink`) — the deferred-import pattern `DefaultProcessingPort` mirrors. Each method does `from app.modules.X import Y` inside the function body, then calls into the existing service. Read end-to-end.
- `backend/app/platform/extensions/protocols.py:43-59` (`AuditSink`) — the docstring template Phase 225's Protocols mirror. Note the `TYPE_CHECKING` forward reference for `AuditEvent` (line 18-19) — Phase 225 uses the same pattern for `SearchFilters`, `SearchResult`, etc.
- `backend/tests/test_layering.py:421-489` (`test_no_log_action_calls_outside_audit_service`) — the architecture-guard test pattern Phase 225's `test_no_processing_imports_catalog` mirrors verbatim. Same pathspec-exclusion shape, same `_has_git_metadata` / `_has_pathspec_magic` skip guards.

### Phase 224 catalog god-module split — the post-split surface

- `backend/tests/test_layering.py:333-418` (`test_no_external_imports_of_dataset_domain_submodules`) — the most recent architecture-guard test (Phase 224 DECOUPLE-04). Phase 225's guard mirrors its allowlist-aware structure but uses a STRICTER zero-hit pattern (no allowlist for processing/* per D-23).
- `backend/app/modules/catalog/datasets/domain/service.py` (post-Phase-224 façade) — the file `DefaultProcessingPort.create_dataset` etc. delegates to via deferred import. Note that this is a re-export façade; the actual implementations live in `service_create.py`, `service_query.py`, `service_lifecycle.py`, `service_metadata.py`, `service_relationships.py`. `DefaultProcessingPort` MUST go through the façade (not the sub-modules directly) — Phase 224 DECOUPLE-04 forbids external sub-module imports.

### Phase 223 BillingExtension — the list-shape accessor pattern (rejected for Phase 225)

- `backend/app/platform/extensions/__init__.py:161-192` (`get_billing_extensions()`) — the list-shape accessor. Phase 225 deliberately does NOT use this shape (D-12 picks single-slot like `get_identity_extension()` instead). Read once to understand why; do not copy.

### Code (current location of the Port's surface — what `DefaultProcessingPort` delegates to)

- `backend/app/modules/catalog/authorization.py` — `apply_visibility_filter`, `check_dataset_access`, `get_user_roles`. `DefaultProcessingPort.apply_visibility_filter`, `.check_dataset_access`, `.get_user_roles` all delegate here. Read for the function signatures and the visibility-filter SQLAlchemy `Select` shape.
- `backend/app/modules/catalog/datasets/domain/service.py` (post-Phase-224 façade) — re-exports `create_dataset`, `get_dataset`, `update_dataset`, `delete_dataset`, etc. `DefaultProcessingPort` delegates here.
- `backend/app/modules/catalog/datasets/domain/models.py` — the `Dataset`, `Record`, `RecordKeyword`, `RecordDistribution`, `AttributeMetadata`, `DatasetGrant` ORM classes that structurally satisfy the new Protocols. Phase 225 leaves this file UNCHANGED (D-29 — no Alembic migration). Read for the attribute set the new `DatasetProtocol`/`RecordProtocol` must capture (D-02).
- `backend/app/modules/catalog/datasets/domain/column_stats.py` — `get_column_stats`, `get_distinct_values`. Used by AI features.
- `backend/app/modules/catalog/datasets/domain/utils.py` — `extract_bbox`. Used by `ai/service.py`.
- `backend/app/modules/catalog/datasets/domain/schemas.py` — `IngestionResult`, `DatasetCreatePayload` (or whatever the actual create schema is named — planner re-grep at plan time). Forward-referenced in `core/processing_port.py`.
- `backend/app/modules/catalog/maps/service.py` — `create_map`, `update_map`. Used by `ai/service.py`, `ai/chat_service.py`.
- `backend/app/modules/catalog/maps/models.py` — the `Map` ORM class.
- `backend/app/modules/catalog/search/service.py` — `search_datasets`, `SearchFilters`. Used by `ai/service.py`.
- `backend/app/modules/catalog/sources/preview.py` — `build_gdal_source`. Used by `ingest/tasks_vector.py:302`, `ingest/tasks_reupload.py:273`.
- `backend/app/modules/catalog/collections/models.py` — `DatasetVersion`. Used by `ingest/tasks_common.py:849`.

### Code (extension scaffold to extend)

- `backend/app/platform/extensions/__init__.py` — extension registry; current shape (Phase 222/223 list-shape + Phase 214 single-slot). Phase 225 adds `get_processing_port()` here (D-12), modeled on `get_identity_extension():115-129`.
- `backend/app/platform/extensions/protocols.py` — Protocol definitions for `BrandingExtension`, `AuditExtension`, `AuthExtension`, `AuditSink`, `BillingExtension`. **Not modified** by Phase 225 — `ProcessingPort` lives in `core/processing_port.py` per D-10 (consumer-facing type, like `IdentityProtocol`). Read the file's docstring (lines 1-9) — the same discipline applies to `core/processing_port.py`.
- `backend/app/platform/extensions/defaults.py` — current `Default*` implementations. Phase 225 adds `DefaultProcessingPort` here per D-11.
- `backend/app/platform/extensions/guards.py` — `require_enterprise()`. Not modified by Phase 225 (the Port is community-aware; default impl just calls existing catalog functions).
- `backend/app/api/main.py:125-135` — application startup wiring: `load_extensions()` → `init_edition()` → mount extension routers. Phase 225's `get_processing_port()` is consulted lazily on every call (per D-14), not at startup; no startup-wiring change needed.

### Code (architecture-guard test)

- `backend/tests/test_layering.py` — current state: 8 architecture tests (Phase 212×2, Phase 213×2, Phase 214×1, Phase 222×1, Phase 223×2, Phase 224×1). Phase 225 adds 1 more (D-22) and updates the module docstring (D-25). The test file holds the `_has_git_metadata()`, `_has_pathspec_magic()`, and `_git_grep()` helpers Phase 225 reuses verbatim.
- `backend/pyproject.toml` — registers the `architecture` pytest marker. Already done by Phase 212-03; no change.

### Code (caller files — the 8 processing files Phase 225 migrates)

The complete current-state list (`grep -REn "^(from|import)\s+app\.modules\.catalog" backend/app/processing/`), with the planner re-running this grep at plan time to catch any post-discussion drift. The 8 files match the audit's "8 processing→catalog imports" count; the line numbers shift after edits.

**Module-level top-of-file imports (~20 lines across 8 files):**
- `backend/app/processing/embeddings/backfill.py:15` — `from app.modules.catalog.datasets.domain.models import Record`
- `backend/app/processing/ingest/service.py:20, 22, 23` — `get_user_roles`, `Dataset`, `create_dataset`
- `backend/app/processing/ai/service.py:33, 34, 35, 36, 37, 39` — `apply_visibility_filter`, `Dataset/DatasetGrant/Record`, `extract_bbox`, `get_column_stats`, `create_map/update_map`, `SearchFilters/search_datasets` (5 distinct import statements; widest surface)
- `backend/app/processing/tiles/router.py:21, 23` — `check_dataset_access/get_user_roles`, `Dataset/DatasetGrant`
- `backend/app/processing/ai/router.py:42, 44, 46` — `get_user_roles`, `Dataset`, `Map`
- `backend/app/processing/ai/chat_service.py:29` — `get_column_stats, get_distinct_values`
- `backend/app/processing/ai/metadata_service.py:25` — `Dataset, Record, RecordKeyword`
- `backend/app/processing/export/router.py:16, 17` — `check_dataset_access`, `get_dataset`

**Function-scope deferred imports (~24 lines, all under processing/ingest/ + processing/ai/):**
- `backend/app/processing/embeddings/tasks.py:21` (TYPE_CHECKING — typing-only)
- `backend/app/processing/ingest/tasks_vector.py:302` — `build_gdal_source`
- `backend/app/processing/ingest/tasks_common.py:618` — `create_dataset`
- `backend/app/processing/ingest/tasks_common.py:697` — `IngestionResult`
- `backend/app/processing/ingest/tasks_common.py:849` — `DatasetVersion`
- `backend/app/processing/ingest/tasks_reupload.py:38, 257` — `Dataset`
- `backend/app/processing/ingest/tasks_reupload.py:273` — `build_gdal_source`
- `backend/app/processing/ingest/tasks_vrt.py:51, 165, 283, 362` — `Dataset/Record/RecordDistribution`
- `backend/app/processing/ingest/tasks_raster.py:47, 143, 301` — `Dataset/Record/RecordDistribution`
- `backend/app/processing/ingest/metadata.py:18, 466, 1076, 1102, 1130, 1188` — various ORM models
- `backend/app/processing/ingest/router.py:819, 1005` — `Dataset, Record`
- `backend/app/processing/ingest/service.py:320, 368, 405` — various

**No allowlist (per D-23):** every import migrates. The architecture guard's pathspec excludes only `backend/tests/`.

**Note:** The non-catalog import `from app.platform.cache.tiles import invalidate_catalog_cache` (in `tasks_common.py:19`, `tasks_reupload.py:10`, `tasks_vrt.py:10`, `tasks_raster.py:10`, `tasks.py:30`) is NOT a catalog-module import — `app.platform.cache.tiles` is a platform-layer cache helper. The function name contains "catalog" but the module path is `platform.*`. The architecture guard's regex `^\s*(from|import)\s+app\.modules\.catalog` does not trip on these. Planner verifies during the migration sweep.

### Catalog → processing direction (NOT touched by Phase 225)

- The catalog → processing direction has 51 import lines under `backend/app/modules/catalog/` reaching into `app.processing.*` (catalog routers/services orchestrating ingest tasks, embedding services, raster registration, export helpers). This is the legitimate top-down driver direction. Phase 225 does NOT touch these. ROADMAP §225 SC#2's grep is direction-specific (`from app.modules.catalog` under `backend/app/processing/`), not bidirectional.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- **`backend/app/core/identity.py` (Phase 214)** — the canonical pattern `core/processing_port.py` mirrors. Module docstring template, Protocol decoration (`@runtime_checkable`), structural-only typing (stdlib + `AsyncSession`), type alias for caller annotations (`Identity = IdentityProtocol`), Extension Protocol shape — all directly transferable to Phase 225.
- **`backend/app/platform/extensions/defaults.py:46-76` (Phase 222 `DefaultAuditSink`)** — the deferred-import pattern. Each method does `from app.modules.X import Y` inside the function body. `DefaultProcessingPort` mirrors this verbatim.
- **`backend/app/platform/extensions/__init__.py:115-129` (`get_identity_extension()`)** — single-slot accessor pattern. `get_processing_port()` mirrors it (D-12).
- **`backend/app/platform/extensions/__init__.py:38-46` (`load_extensions()`)** — `importlib.metadata.entry_points("geolens.extensions")` registration loop. Phase 225's `ProcessingPort` registers via the same group with key `"processing_port"`. Already battle-tested by Phases 192–224.
- **`backend/tests/test_layering.py` `_has_git_metadata()` + `_has_pathspec_magic()` + `_git_grep()` helpers** (Phase 212/213/214/222/223/224) — Phase 225's new test reuses them verbatim. No new helpers needed.
- **`@pytest.mark.architecture` marker registered in `backend/pyproject.toml`** — Phase 225 reuses; no new marker.
- **`platform/extensions/protocols.py:18-19` `TYPE_CHECKING` forward-ref pattern** for `AuditEvent` — Phase 225's `core/processing_port.py` uses the same shape for `SearchFilters`, `SearchResult`, `MapSpec`, `DatasetCreatePayload`, `ColumnStats`. Each forward-referenced type stays in its existing catalog-domain location; the Protocol method signature names it via string annotation.

### Established Patterns

- **Closed-set caller migration via `git grep`**: Phase 212/213/214/222 used `git grep` (not `import-linter`) to enumerate callers and to enforce the layering boundary. Phase 225 inherits this. Do NOT introduce `import-linter` or any architecture-DSL dependency.
- **Hard-cutover migration with NO compat shim**: Phase 212 D-04, Phase 213 D-04, Phase 214 D-10 — closed-set codebase, ruff + full pytest is the safety net, architecture-guard test as the regression seal. Phase 225 inherits.
- **Function-scope deferred imports as cycle-breakers / slow-startup mitigation**: ~103 deferred imports exist project-wide; ~24 in `processing/ingest/` and `processing/ai/` reach into catalog. Phase 225 rewrites the path on each (per D-19) — keeps them deferred, just swaps `app.modules.catalog.X` for `get_processing_port` + Port methods.
- **Multi-line import blocks**: `processing/ingest/metadata.py:18` and a few others use multi-line `from app.modules.catalog.datasets.domain.models import (\n  Dataset,\n  Record,\n  RecordKeyword,\n)` style. Mechanical migration rewrites the import line; the block-shape preservation rule is the same as Phase 213 D-04 / Phase 214 D-08.
- **`@runtime_checkable` on every Protocol** — `IdentityProtocol`, `RoleProtocol`, `IdentityExtension`, `AuditSink`, `BillingExtension` all use it. Phase 225's Protocols inherit.
- **`from __future__ import annotations`** at the top of every Protocol-bearing module — `core/identity.py:22`, `platform/extensions/protocols.py:11`. Phase 225's `core/processing_port.py` uses it.
- **`__table_args__ = {"schema": "catalog"}`**: every catalog-domain ORM model uses this. Phase 225 doesn't move any tables; the schema rule is unchanged.
- **Phase 224 façade discipline**: external callers reach catalog dataset domain functions via `app.modules.catalog.datasets.domain.service` (the façade), NOT via `service_create.py` / `service_query.py` / etc. (per Phase 224 DECOUPLE-04 / `test_no_external_imports_of_dataset_domain_submodules`). `DefaultProcessingPort.create_dataset`, `.get_dataset`, etc. delegate via the façade — never reach the sub-modules directly.

### Integration Points

- **`backend/app/api/main.py` startup chain**: `load_extensions()` → `init_edition()` → mount routers. The `ProcessingPort` is consulted lazily per-request via `get_processing_port()` (per D-14), NOT at startup. No startup-wiring change. The `_loaded` flag at `platform/extensions/__init__.py:38` is set after `load_extensions()` runs; if `get_processing_port()` is called before `load_extensions()` (shouldn't happen — startup runs `load_extensions()` first), it returns the default impl, which is correct fallback behavior.
- **Procrastinate worker process** (raster/vector/VRT ingest, embedding generation): worker tasks call `get_processing_port()` directly at the top of the task body (D-14). Workers don't go through FastAPI dependency injection. The deferred-import pattern is preserved — the import of `get_processing_port` itself can be top-level (it's in `app.platform.extensions`, not `app.modules.*`, so no circular-import risk); only the catalog-side imports are deferred today.
- **AI features** (`processing/ai/router.py`, `service.py`, `chat_service.py`, `metadata_service.py`): the four files PROCESS-03 specifically calls out. Routes use `Depends(get_processing_port)`; service-layer functions take `port: ProcessingPort` explicitly (D-15). Tests construct `FakeProcessingPort` (D-27).
- **Embeddings backfill** (`processing/embeddings/backfill.py`): standalone Python module (`python -m app.embeddings.backfill`). Calls `get_processing_port()` at the top of `backfill_embeddings()`. Uses `port.get_record(...)` to fetch records.
- **OpenAPI snapshot (`backend/openapi.json`)**: unaffected. `ProcessingPort` is a Python-typing concept; FastAPI generates OpenAPI from request/response Pydantic schemas, not from FastAPI dependency return types. Routes that depend on `ProcessingPort` (formerly importing concrete catalog types) emit the same OpenAPI as before.
- **Tests** (`backend/tests/`): test fixtures construct `Dataset(...)`, `Record(...)`, `Map(...)` directly. Since the concrete ORM classes structurally satisfy the new Protocols, these fixtures work unchanged. The architecture guard's pathspec excludes `backend/tests/` (D-23).
- **CLAUDE.md "FastAPI trailing slashes" / "OGC routes" rules**: not affected — Phase 225 is below the route layer.

### Risk surfaces

- **`ProcessingPort` doesn't cover everything `Dataset`/`Record`/`Map` have.** Annotated as `DatasetProtocol`, callers can read the fields listed in D-02. They CANNOT read columns NOT on the Protocol. If any cross-domain caller reads a column the Protocol doesn't expose, the migration breaks at type-annotation time. Mitigation: the planner re-greps each caller file before/after migration to confirm every attribute access is covered. From the codebase scout, the `processing/*` reads are bounded — the AI service reads `Dataset.id, .table_name, .geometry_type, .feature_count, .bbox, .attributes, .record`, the AI router reads `Dataset.id, .record_id, .table_name, .srid`, etc. — all covered by D-02's surface. Planner verifies.
- **Catalog ORM relationships and `Mapped[...]` typing**: `Dataset.attributes: Mapped[Sequence["AttributeMetadata"]]`, `Dataset.record: Mapped["Record"]`, `Map.layers: Mapped[Sequence["MapLayer"]]`. The relationships are concrete SQLAlchemy `Mapped` declarations on the ORM class; the new structural Protocols expose the relationship as a plain `Sequence[AttributeProtocol]` / `RecordProtocol` typing. Reading `dataset.attributes` returns a `Sequence` of concrete `AttributeMetadata` instances, which structurally satisfy `AttributeProtocol`. No SQLAlchemy `Mapped` declaration changes; the Protocols are read-side typing only.
- **Schemas with concrete-class-typed fields**: some Pydantic schemas in `app.modules.catalog.*.schemas` may have `dataset: Dataset` style fields. Those schemas STAY in catalog and use the concrete ORM type; Phase 225 only retypes the `processing/*` callers' parameter annotations and the Port method signatures. The OpenAPI snapshot is unchanged because the schemas are unchanged.
- **`SearchFilters` / `SearchResult` / `MapSpec` are catalog-domain types** — Phase 225 keeps them in catalog (D-06/D-07 forward-reference pattern). If a future cleanup wants to move them into a shared schema package, that's a separate phase. Phase 225's Port references them via `TYPE_CHECKING` so the import edge `core/processing_port → app.modules.catalog.*.schemas` is typing-only; runtime has no circular import.
- **Function-scope deferred imports during migration**: ~24 sites. The deferred-import discipline (Phase 213 D-04) is preserved by D-19 — keep the deferral, swap the path. If the planner finds a deferred import that becomes unnecessary post-migration (e.g., the original circular-import reason no longer applies because the new `get_processing_port` import is no-cycle), default is to keep the deferral anyway — minimizes diff churn.
- **Unit-test seam coverage**: the `FakeProcessingPort` test (D-27) is one focused test. The 2036/2036 backend baseline is the broader correctness gate. If the `FakeProcessingPort` doesn't match `DefaultProcessingPort` behavior in some subtle way, the broader suite catches it.
- **Phase 226 overlap**: Phase 226 (AIProviderExtension) sequences AFTER 225 because both touch `processing/ai/`. Phase 225 should not touch the `if/elif provider ==` dispatch branches at `llm_loop.py:117,132` and `service.py:387-398` — Phase 226 owns those.
- **`processing/raster/models.py` referenced from `catalog/maps/service.py:25`** — this is the catalog → processing direction, NOT touched by Phase 225. The audit's catalog ↔ processing 19-file count includes this edge but the inversion is one-way. No work item.

</code_context>

<specifics>
## Specific Ideas

- **Audit phrasing chosen, in their words:** Audit-26-b §7 P0 #2: "Break catalog ↔ processing two-way cycle via `ProcessingPort` Protocol in `core/` (mirror Phase 214 IdentityProtocol pattern). Invert each of 8 processing→catalog imports." Phase 225 implements this directive verbatim with comprehensive Protocol surface (D-01) per Phase 214 D-01 reasoning.
- **Audit-suggested `CatalogReadPort` for non-processing read-only consumers (P2 #4)** — explicitly NOT included in Phase 225. That's a separate phase (audit P2 priority). Phase 225 ships only the processing-side Port; admin/, embed_tokens/, settings/ etc. continue to import from catalog directly. If a future phase wants a stricter boundary across all non-catalog consumers, `CatalogReadPort` is the next step.
- **ROADMAP §225 SC#5 mandates AI-feature coverage:** "AI features (`chat_service.py`, `metadata_service.py`, `embeddings/backfill.py`) consume catalog data exclusively through the Protocol — verifiable by the same grep guard plus a focused unit test that swaps in a fake `ProcessingPort`." Phase 225 binds D-15 (service-layer functions take port as parameter, enabling the test seam) and D-27 (focused `FakeProcessingPort` unit test) to satisfy this.
- **Phase 999.11 inlined per ROADMAP §225 note** — the architecture-guard test ships in the same phase as the inversion because adding the guard before the cycle is broken would fail CI immediately. Phase 999.11 is therefore retired (already noted in ROADMAP backlog: "PROMOTED to Phase 225").
- **Phase 226 plug-in shape will look like:** the AI provider overlay (or a tier-aware processing-Port overlay) registers via `[project.entry-points."geolens.extensions"]` table calling `register_extensions(registry)`. For Phase 226's AIProviderExtension the registry slot is `"ai_providers"` (list-shape, fan-out by name). For Phase 225's ProcessingPort the registry slot is `"processing_port"` (single-slot, replace). Both flow through `load_extensions()`.
- **Phase 229 audit-grade target:** the post-implementation audit gate for v13.4 verifies Coupling Health ≥ **B+**. Phase 225's contribution: removing 20 module-level + ~24 function-scope `processing → catalog` import edges (the lever the audit identified). Phase 229 reruns `/oc-audit` and confirms grade movement. Phase 225 alone is not sufficient to flip the grade — Phase 226 (AIProviderExtension) is the second lever; together they close the last 🔴 seams.

</specifics>

<deferred>
## Deferred Ideas

- **`CatalogReadPort` for non-processing read-only consumers** (audit P2 #4): admin, embed_tokens, settings, etc. continue to import from catalog directly. If a future phase wants a stricter boundary, design it as `CatalogReadPort` Protocol. Phase 225 doesn't pre-empt; Phase 999.X territory.
- **`PermissionExtension` Protocol** (Phase 999.8 backlog, P1): the authorization helpers (`apply_visibility_filter`, `check_dataset_access`, `get_user_roles`) live on `ProcessingPort` for now. When Phase 999.8 lands, they get refactored out into a dedicated `PermissionExtension`. Phase 225 doesn't pretend to solve the authorization seam — just relocates the access path.
- **`AIProviderExtension` Protocol** (Phase 226, the next phase): replace hardcoded `if/elif provider ==` dispatch at `processing/ai/llm_loop.py:117,132` and `service.py:387-398` with extension lookup. Phase 225 sequences before; Phase 225 does NOT touch the provider dispatch branches (Phase 226 owns).
- **`WorkflowExtension` Protocol** (Phase 999.9 backlog, P1): `ALLOWED_TRANSITIONS` hardcoded dict at `catalog/datasets/api/router_data.py:210-215` — separate phase.
- **`Connector` ORM + `ConnectorAdapter` Protocol** (Phase 999.13, P2): Enterprise-tier persistent connector registry with credential vault. Greenfield.
- **`geolens-schemas` package extraction** (Phase 999.16, P2): separate phase. Phase 225 keeps `SearchFilters` / `MapSpec` etc. in catalog.
- **`geolens.yaml` declarative manifest** (Phase 999.12, P1): separate ~2-week phase. Phase 225 unrelated.
- **`Mapped["X"]` SQLAlchemy ORM relationship typing on the new Protocols**: the Protocols are read-side structural typing only (D-05). If a future phase wants Protocol-typed `Mapped` declarations (which SQLAlchemy doesn't support today), revisit. Out of scope.
- **Runtime conformance test (`isinstance(Dataset(), DatasetProtocol)`)**: D-28 deferred. Adds a test for marginal value; the full pytest exercise already runs the dep chain end-to-end against the concrete catalog ORM classes. Revisit if a `Dataset` attribute drift ever causes a hard-to-diagnose failure.
- **Pyright/mypy CI gate**: Phase 214 D-25 deferred this; Phase 225 inherits. The project does not run pyright or mypy in CI. ruff + pytest is the gate.
- **Inverting the catalog → processing direction (51 lines)**: explicitly NOT in scope. ROADMAP §225 SC#2 is direction-specific (processing → catalog only). Catalog drives processing top-down; that's the natural direction. If a future phase wants stricter bidirectional decoupling (e.g., `IngestExtension` Protocol for catalog routers to invoke ingest tasks via Protocol), that's a separate phase.
- **Replacing `Default*Extension` no-op shims with `None` returns** — Phase 214 D-14 / Phase 222 D-04 / Phase 223 D-07 all keep the Default class shape (vs. returning `None`). Phase 225 inherits; `DefaultProcessingPort` is a real class with real methods (delegates to existing catalog functions). No change to the discipline.
- **`docker-compose.yml:128-129` `AWS_MARKETPLACE_*` env-var injection cosmetic regression** (audit-26-b §4 finding #2): a 15-min cleanup unrelated to Phase 225. Could be folded into Phase 229 (post-impl audit) or done inline as a quick task.
- **`free-vs-enterprise.md:113` doc-drift** (audit-26-b §3c): 5-min doc edit unrelated to Phase 225. Same — Phase 229 or a quick task.

</deferred>

---

*Phase: 225-processing-port-protocol-cycle-inversion*
*Context gathered: 2026-05-01*

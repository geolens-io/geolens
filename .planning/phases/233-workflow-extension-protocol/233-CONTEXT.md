# Phase 233: workflow-extension-protocol - Context

**Gathered:** 2026-05-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Add a first-class `WorkflowExtension` seam at the platform extension layer for dataset publication lifecycle transitions. The seam must cover the current `draft -> ready -> internal -> published` status chain, the bidirectional one-step transitions in `backend/app/modules/catalog/datasets/api/router_data.py`, and transition hooks that overlays can use to observe or block publication changes without modifying core route logic.

The default Community behavior must preserve the existing lifecycle, `_STATUS_ORDER`, request/response shapes, validation failures, RBAC dependency behavior, transaction timing, and current audit behavior. This phase is a seam extraction, not a full approval-workflow product build. It does not add reviewer assignment, notifications, approval UI, policy authoring, custom workflow administration, or a new event bus.

Auto-mode note: this context was gathered from `$gsd-discuss-phase 233 --auto --chain`, so decisions below are conservative defaults derived from the roadmap, the 2026-05-02/2026-05-03 open-core audits, the completed Phase 232 `PermissionExtension` pattern, and the existing publication lifecycle code.

</domain>

<decisions>
## Implementation Decisions

### Workflow Contract

- Add `WorkflowExtension` as a `@runtime_checkable` Protocol in `backend/app/platform/extensions/protocols.py`.
- The Protocol must expose the default status order, allowed transitions for a given current state, and a transition hook invoked for each accepted transition.
- Use the existing status vocabulary as the default Community vocabulary: `draft`, `ready`, `internal`, `published`.
- The one-step transition map remains: `draft -> ready`, `ready -> draft/internal`, `internal -> ready/published`, and `published -> internal`.
- The target-status endpoint must continue to walk the ordered chain one step at a time, calling the extension for each intermediate transition rather than jumping directly.
- The transition hook should receive enough context for future approval overlays without forcing a product model now: session, dataset, actor, from-status, to-status, and call-site/mode context are the expected minimum. Planner may introduce a small `WorkflowTransitionContext` dataclass if that keeps signatures readable.
- Blocking should happen through the extension's allowed-transition decision or an explicit transition-validation method, while observation should happen through the hook. Do not add a separate event bus in this phase.

### Default Workflow Behavior

- Ship `DefaultWorkflowExtension` in `backend/app/platform/extensions/defaults.py`.
- Move the hardcoded `ALLOWED_TRANSITIONS` and `_STATUS_ORDER` semantics into the default extension, while preserving import compatibility from `router_data.py` if existing tests import those names.
- The default extension should be async-compatible even if its initial implementation is pure in-memory data; overlays may need database or external checks.
- Preserve existing publication endpoint API behavior:
  - `PATCH /datasets/{id}/status/` accepts only one allowed step and returns `422` with the current `"Cannot transition from ... Allowed: ..."` style detail on invalid transitions.
  - `PATCH /datasets/{id}/target-status/` returns the current status immediately when no change is needed.
  - Unknown current/target values continue to return `422` from the route-level workflow validation path.
  - Successful responses remain `StatusUpdateResponse(id=str(dataset.id), record_status=target)`.
- Preserve current commit/refresh behavior in Community mode. The route still owns the transaction boundary; the extension decides and observes transitions but does not commit independently.
- Preserve current audit behavior. The publication endpoints do not gain new audit rows by default; overlays may use the hook to write their own audit/activity records inside the route transaction.

### Status Vocabulary And Custom-State Readiness

- Core route logic should no longer hardcode the four-state vocabulary in a place that prevents overlays from accepting an extension-defined state.
- `StatusUpdate` validation should remain syntactic and safe, but status-membership validation belongs at the workflow-extension boundary. The default extension denies unknown statuses so Community API behavior stays unchanged.
- The `catalog.records.record_status` database check constraint currently hardcodes the four statuses. If research confirms this blocks extension-defined custom states, planning should include the minimal Alembic migration needed to remove or relax that hardcoded constraint while keeping Community route behavior enforced by `DefaultWorkflowExtension`.
- No frontend custom-state UI is part of this phase. If a custom status exists through an Enterprise overlay, core should not crash or fork route logic, but Community UI polish for those states is deferred.
- The minimum overlay proof for WORK-04 is adding or blocking a transition through the extension without modifying core. If the DB constraint is relaxed in this phase, include a focused custom-state proof such as `draft -> review`; otherwise include a same-vocabulary transition proof such as allowing `ready -> published`.

### Publication Call Sites

- The primary in-scope publication endpoints are in `backend/app/modules/catalog/datasets/api/router_data.py`: `/status/` and `/target-status/`.
- Both endpoints must consult `get_workflow_extension()` for every status transition. The hardcoded transition dictionary and ordered list should no longer be the source of truth inside route code.
- The metadata update path in `backend/app/modules/catalog/datasets/domain/service_metadata.py` also directly writes `record.record_status` when `PATCH /datasets/{id}` includes `record_status`. Treat this as a known adjacent bypass to evaluate during planning.
- If the metadata update path remains able to change `record_status`, it must either delegate to the workflow extension or be explicitly preserved through a default-mode hook that overlays can intercept. Enterprise approval workflow must not be bypassable through metadata PATCH.
- Preserve the current metadata-patch behavior in Community mode: publishing through `DatasetMeta.record_status` continues to run the `REQUIRE_METADATA_FOR_PUBLISH` validation gate, sets `published_at` when transitioning to `published`, and returns the existing metadata endpoint response and errors.
- Creation/import code that initializes records as `draft` or `published` is not the publication-transition surface for this phase. Do not broaden the architecture guard to fail seed/test/ingest initial status assignment unless planning finds a real route-level bypass.

### Registry Shape

- Use a single-slot typed accessor, `get_workflow_extension()`, following `get_permission_extension()`, `get_processing_port()`, and `get_catalog_port()`.
- Registry key should be `"workflow"` unless research finds an existing convention that argues for a more specific key.
- Community mode returns `DefaultWorkflowExtension` when no overlay is registered.
- Enterprise overlays replace the workflow policy by registering under the singleton key. If they need additive behavior, they can wrap or delegate to `DefaultWorkflowExtension`; core should not define multi-workflow list composition in this phase.
- Keep registration compatible with the existing `geolens.extensions` entry-point callback shape: `def register_extensions(registry: dict) -> None: ...`.

### Test Overlay And Guards

- Add tests proving an overlay can block a currently allowed transition, such as `internal -> published`, without modifying core.
- Add tests proving an overlay can add a transition. Prefer an extension-defined custom state if the DB/schema layer is loosened; otherwise prove a new transition among current statuses.
- Add tests proving the transition hook is called once per accepted transition. For `/target-status/`, a `draft -> published` request should observe the intermediate transition sequence rather than a single jump.
- Preserve and extend `backend/tests/test_publication_lifecycle.py` so valid/invalid Community transitions remain green.
- Add or extend an architecture guard in `backend/tests/test_layering.py` so known dataset publication transition call sites fail if they bypass `get_workflow_extension()`.
- Keep the guard narrow and explicit: check `router_data.py` publication endpoints and, if routed in this phase, the metadata `record_status` helper. Do not scan every fixture or seed path that assigns initial `record_status`.
- Include a negative-control proof for the guard: temporarily bypass the extension at a known transition point, confirm the guard fails with the offending surface named, then revert.

### Behavior Preservation

- Existing public API paths, request bodies, response models, status codes, RBAC dependencies, and frontend publish/unpublish flows remain unchanged in Community mode.
- `require_permission("edit_metadata")` remains the RBAC gate for publication endpoints. Phase 233 should not create a parallel permission system.
- Metadata validation for publishing remains exactly where users experience it today unless planner finds an existing discrepancy that must be fixed to preserve documented behavior.
- No approval UI, reviewer/approver tables, notification jobs, queue workflows, or workflow-admin settings are part of Phase 233.
- Keep the implementation small and audit-friendly. The result should make the 2026-05-02/2026-05-03 audit's workflow/approval seam move from adaptable/yellow to a real extension seam without starting the full Business-tier approval product.

### Claude's Discretion

- Exact Protocol method names are left to research/planning, with the roadmap's `allowed_transitions()` and `on_transition(from, to, user)` wording as the semantic anchor.
- Planner may choose whether invalid transition handling returns a small decision object, raises a workflow-specific exception, or returns a boolean/set and lets the route raise `HTTPException`. Default preference is to keep HTTP response construction in the route so API behavior stays obvious.
- Planner may decide whether the default transition map/status order constants remain re-exported from `router_data.py` for test/import compatibility or move fully into `DefaultWorkflowExtension` with tests updated.
- Plan decomposition is flexible. A likely split is: additive Protocol/default/accessor, route publication endpoints through the extension, handle metadata-patch bypass/custom-state persistence, then add overlay tests and architecture guard.

</decisions>

<specifics>
## Specific Ideas

- Treat Phase 233 as the workflow sibling of Phase 232 `PermissionExtension`: single-slot accessor, default implementation in `platform/extensions/defaults.py`, and narrow architecture guard over known chokepoints.
- Audit source names the hardcoded `ALLOWED_TRANSITIONS` dict and `_STATUS_ORDER` in `catalog/datasets/api/router_data.py` as Seam #6.
- Current lifecycle tests live in `backend/tests/test_publication_lifecycle.py` and import `ALLOWED_TRANSITIONS`; preserve that test intent even if the implementation source of truth moves.
- Current frontend publish/unpublish calls `frontend/src/api/datasets.ts` target-status helpers, so Community response shapes and target-status walking must stay stable.
- The implementation should be easy to audit by reading `platform/extensions/protocols.py`, `platform/extensions/defaults.py`, `platform/extensions/__init__.py`, `catalog/datasets/api/router_data.py`, and any metadata status helper touched in `service_metadata.py`.

</specifics>

<deferred>
## Deferred Ideas

- Full approval workflow product UI, reviewer assignment, reviewer notifications, and approval history belong in a later Business-tier phase.
- Workflow policy authoring/admin UI belongs in a later phase after the seam is proven.
- New workflow events or a durable event bus are outside this seam extraction.
- Field-level RBAC and policy-authoring UI remain deferred from the v13.5 scope.
- Tenant scoping and Cloud multi-tenant workflow isolation remain backlog Phase 999.6.

</deferred>

---

*Phase: 233-workflow-extension-protocol*
*Context gathered: 2026-05-03*

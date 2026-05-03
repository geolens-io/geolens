---
phase: 233-workflow-extension-protocol
plan: 02
type: execute
wave: 2
depends_on:
  - 233-01
files_modified:
  - backend/app/modules/catalog/datasets/domain/schemas.py
  - backend/app/modules/catalog/datasets/api/router_data.py
  - backend/tests/test_publication_lifecycle.py
  - backend/tests/test_workflow_extension.py
autonomous: true
requirements:
  - WORK-02
  - WORK-03
  - WORK-04
must_haves:
  truths:
    - "PATCH /datasets/{id}/status/ asks WorkflowExtension before accepting every one-step transition."
    - "PATCH /datasets/{id}/target-status/ walks the extension status_order and calls the extension for each intermediate transition."
    - "Community API response bodies, RBAC dependency, 404 behavior, 422 invalid-transition detail style, commit/refresh timing, and no-change target-status behavior remain unchanged."
    - "An overlay can block, add, and observe publication endpoint transitions without changing router code."
  artifacts:
    - path: backend/app/modules/catalog/datasets/api/router_data.py
      provides: "publication endpoint workflow routing"
      contains: "get_workflow_extension"
    - path: backend/app/modules/catalog/datasets/domain/schemas.py
      provides: "syntactic StatusUpdate validation"
      contains: "class StatusUpdate"
    - path: backend/tests/test_publication_lifecycle.py
      provides: "Community lifecycle endpoint regression tests"
      contains: "target-status"
    - path: backend/tests/test_workflow_extension.py
      provides: "routed overlay block/add/observe tests"
      contains: "on_transition"
  key_links:
    - from: "backend/app/modules/catalog/datasets/api/router_data.py:update_publication_status"
      to: "backend/app/platform/extensions:get_workflow_extension"
      via: "await workflow.allowed_transitions(context) before assignment"
      pattern: "allowed_transitions"
    - from: "backend/app/modules/catalog/datasets/api/router_data.py:set_target_status"
      to: "backend/app/platform/extensions:get_workflow_extension"
      via: "workflow.status_order() plus per-step allowed_transitions/on_transition"
      pattern: "status_order"
---

<objective>
Route the two dataset publication endpoints through WorkflowExtension while preserving Community behavior.

Purpose: close the primary publication lifecycle seam so Enterprise overlays can implement approval checks and transition observation without forking router_data.py.
Output: /status/ and /target-status/ consult the extension for each transition, with regression tests for default and overlay behavior.
</objective>

<execution_context>
@/Users/ishiland/.codex/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.codex/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/REQUIREMENTS.md
@.planning/phases/233-workflow-extension-protocol/233-CONTEXT.md
@.planning/phases/233-workflow-extension-protocol/233-01-SUMMARY.md

Relevant source:
@backend/app/modules/catalog/datasets/domain/schemas.py
@backend/app/modules/catalog/datasets/api/router_data.py
@backend/tests/test_publication_lifecycle.py
@backend/tests/test_workflow_extension.py

<interfaces>
Plan 01 provides:
- `WorkflowTransitionContext(session, dataset, actor, from_status, to_status, mode)`
- `get_workflow_extension()`
- `WorkflowExtension.status_order()`
- `WorkflowExtension.allowed_transitions(context)`
- `WorkflowExtension.on_transition(context)`

Keep `ALLOWED_TRANSITIONS` and `_STATUS_ORDER` import-compatible from router_data.py if tests import them, but make them compatibility aliases sourced from DefaultWorkflowExtension. They must not be the decision source for endpoint transitions.
</interfaces>
</context>

<tasks>
<task type="auto">
  <name>Make StatusUpdate validation extension-ready</name>
  <files>backend/app/modules/catalog/datasets/domain/schemas.py</files>
  <action>Change StatusUpdate validation from fixed membership validation to syntactic validation only: keep max_length=20, reject blank/whitespace-only values, and return the stripped string. Status membership now belongs at the WorkflowExtension boundary. Preserve the public request field name `status` and the StatusUpdateResponse shape.</action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_publication_lifecycle.py::TestInvalidStatusValue</automated>
  </verify>
  <done>Unknown statuses still return 422 through route workflow validation, but the schema no longer hardcodes the four-state vocabulary.</done>
</task>

<task type="auto">
  <name>Route direct status transitions through WorkflowExtension</name>
  <files>backend/app/modules/catalog/datasets/api/router_data.py, backend/tests/test_publication_lifecycle.py</files>
  <action>In update_publication_status(), build WorkflowTransitionContext(mode="status") from db, dataset, user, current, and target. Call get_workflow_extension().allowed_transitions(context) before assigning record_status. If target is not allowed, raise HTTPException 422 with the existing detail style: `Cannot transition from '{current}' to '{target}'. Allowed: {allowed}`. On success, assign dataset.record.record_status, await workflow.on_transition(context), then keep the existing commit, refresh, and StatusUpdateResponse behavior. Keep require_permission("edit_metadata") unchanged. Add or update Community tests proving all existing valid and invalid transitions still pass/fail with the same status codes.</action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_publication_lifecycle.py::TestValidTransitions tests/test_publication_lifecycle.py::TestInvalidTransitions tests/test_publication_lifecycle.py::TestDatasetNotFound</automated>
  </verify>
  <done>/status/ no longer consults hardcoded transition dictionaries for decisions and Community lifecycle tests remain green.</done>
</task>

<task type="auto">
  <name>Route target-status walking and add endpoint overlay proofs</name>
  <files>backend/app/modules/catalog/datasets/api/router_data.py, backend/tests/test_publication_lifecycle.py, backend/tests/test_workflow_extension.py</files>
  <action>In set_target_status(), use workflow.status_order() to locate current and target. Preserve the immediate no-change response before walking. For each intermediate step, build a fresh WorkflowTransitionContext(mode="target_status"), call allowed_transitions(), assign the next status, and await on_transition(). Do not jump directly from current to target. Add tests proving draft -> published through /target-status/ observes the exact sequence draft->ready, ready->internal, internal->published; an overlay can block internal->published with 422; and an overlay can add a same-vocabulary direct transition such as ready->published through /status/ without modifying router_data.py.</action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_publication_lifecycle.py tests/test_workflow_extension.py</automated>
  </verify>
  <done>/target-status/ consults the extension for every intermediate transition, and overlay block/add/observe behavior is proven at the routed endpoint surface.</done>
</task>
</tasks>

<verification>
- cd backend && uv run pytest tests/test_publication_lifecycle.py tests/test_workflow_extension.py
- cd backend && uv run ruff check app/modules/catalog/datasets/domain/schemas.py app/modules/catalog/datasets/api/router_data.py tests/test_publication_lifecycle.py tests/test_workflow_extension.py
</verification>

<success_criteria>
- WORK-02 remains true for Community endpoint behavior.
- WORK-03 is satisfied for both publication endpoints.
- WORK-04 is satisfied for endpoint-level block/add/observe overlay behavior.
</success_criteria>

<output>
After completion, create `.planning/phases/233-workflow-extension-protocol/233-02-SUMMARY.md`.
</output>

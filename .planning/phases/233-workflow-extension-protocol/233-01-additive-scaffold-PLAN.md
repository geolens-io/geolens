---
phase: 233-workflow-extension-protocol
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/platform/extensions/protocols.py
  - backend/app/platform/extensions/defaults.py
  - backend/app/platform/extensions/__init__.py
  - backend/tests/test_workflow_extension.py
autonomous: true
requirements:
  - WORK-01
  - WORK-02
  - WORK-04
must_haves:
  truths:
    - "WorkflowExtension Protocol exists at the platform extension layer and covers status ordering, allowed transitions, and transition hooks."
    - "DefaultWorkflowExtension preserves the Community draft -> ready -> internal -> published chain and one-step transition map."
    - "get_workflow_extension() returns the Community default unless an overlay registers the singleton workflow slot."
    - "A test overlay can replace the workflow policy without modifying core files."
  artifacts:
    - path: backend/app/platform/extensions/protocols.py
      provides: "WorkflowExtension Protocol and WorkflowTransitionContext"
      contains: "class WorkflowExtension"
    - path: backend/app/platform/extensions/defaults.py
      provides: "DefaultWorkflowExtension"
      contains: "class DefaultWorkflowExtension"
    - path: backend/app/platform/extensions/__init__.py
      provides: "workflow singleton accessor"
      contains: "def get_workflow_extension"
    - path: backend/tests/test_workflow_extension.py
      provides: "default and overlay seam tests"
      contains: "test_overlay_workflow_extension_is_dispatched"
  key_links:
    - from: "backend/app/platform/extensions/__init__.py:get_workflow_extension"
      to: "backend/app/platform/extensions/defaults.py:DefaultWorkflowExtension"
      via: "fallback when _extensions['workflow'] is missing"
      pattern: "DefaultWorkflowExtension"
    - from: "backend/app/platform/extensions/protocols.py:WorkflowTransitionContext"
      to: "backend/app/platform/extensions/protocols.py:WorkflowExtension"
      via: "allowed_transitions(context) and on_transition(context)"
      pattern: "WorkflowTransitionContext"
---

<objective>
Add the WorkflowExtension contract, Community default implementation, singleton registry accessor, and focused seam tests without changing dataset route behavior yet.

Purpose: establish the workflow extension surface before routing publication status changes through it.
Output: Protocol/default/accessor plus tests proving default behavior and overlay dispatch.
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
@.planning/phases/232-permission-extension-protocol/232-01-SUMMARY.md

Relevant source:
@backend/app/platform/extensions/protocols.py
@backend/app/platform/extensions/defaults.py
@backend/app/platform/extensions/__init__.py
@backend/tests/test_extensions.py
@backend/tests/test_permission_extension.py

<interfaces>
Create this platform-level contract shape, keeping imports deferred or type-only when they would point into app.modules:

```python
@dataclass(frozen=True)
class WorkflowTransitionContext:
    session: AsyncSession
    dataset: Any
    actor: Identity | None
    from_status: str
    to_status: str
    mode: str


@runtime_checkable
class WorkflowExtension(Protocol):
    def status_order(self) -> tuple[str, ...]: ...
    async def allowed_transitions(
        self, context: WorkflowTransitionContext
    ) -> set[str]: ...
    async def on_transition(self, context: WorkflowTransitionContext) -> None: ...
```

Use mode values `"status"`, `"target_status"`, and `"metadata_patch"` in later plans. The default should preserve the one-step publication endpoints for `"status"` and `"target_status"`. For `"metadata_patch"`, preserve the legacy metadata endpoint's ability to set any Community status directly while still allowing overlays to intercept the write. DefaultWorkflowExtension must still deny unknown statuses: if either from_status or to_status is outside the Community vocabulary, allowed_transitions() returns an empty set.
</interfaces>
</context>

<tasks>
<task type="auto">
  <name>Add WorkflowExtension Protocol</name>
  <files>backend/app/platform/extensions/protocols.py</files>
  <action>Add a frozen WorkflowTransitionContext dataclass and a runtime-checkable WorkflowExtension Protocol. Keep the contract at platform level: use AsyncSession, Any, and TYPE_CHECKING for Identity. Methods must expose status_order(), async allowed_transitions(context), and async on_transition(context). Do not import dataset ORM classes or catalog modules at protocol import time.</action>
  <verify>
    <automated>python -m compileall backend/app/platform/extensions/protocols.py</automated>
  </verify>
  <done>Protocol imports cleanly, is runtime_checkable, and the transition context carries session, dataset, actor, from_status, to_status, and mode.</done>
</task>

<task type="auto">
  <name>Add DefaultWorkflowExtension and accessor</name>
  <files>backend/app/platform/extensions/defaults.py, backend/app/platform/extensions/__init__.py</files>
  <action>Add DefaultWorkflowExtension with DEFAULT_STATUS_ORDER = ("draft", "ready", "internal", "published") and DEFAULT_ALLOWED_TRANSITIONS matching the current one-step map: draft -> ready, ready -> draft/internal, internal -> ready/published, published -> internal. Implement status_order(), async allowed_transitions(context), and async no-op on_transition(context). For context.mode == "metadata_patch", return all Community statuses except the current one only when both from_status and to_status are in the Community vocabulary, so PATCH /datasets/{id} keeps today's direct status-set behavior while overlays can still block. For unknown from_status or to_status, return an empty set. Add get_workflow_extension() using singleton registry key "workflow", mirroring get_permission_extension(). Add WorkflowExtension to TYPE_CHECKING imports only.</action>
  <verify>
    <automated>python -m compileall backend/app/platform/extensions/defaults.py backend/app/platform/extensions/__init__.py</automated>
  </verify>
  <done>Community default is returned when no overlay is registered; a registered _extensions["workflow"] object is returned unchanged.</done>
</task>

<task type="auto">
  <name>Add workflow seam tests</name>
  <files>backend/tests/test_workflow_extension.py</files>
  <action>Create focused unit tests following the registry-isolation fixture style from test_permission_extension.py. Cover: default accessor returns DefaultWorkflowExtension and satisfies WorkflowExtension; default status_order and allowed transition map match the current lifecycle; metadata_patch mode allows direct Community status changes; on_transition is awaitable and no-op; an entry-point overlay registered under "workflow" replaces the singleton and can return a custom allowed transition set.</action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_workflow_extension.py</automated>
  </verify>
  <done>New workflow extension tests pass without needing route or database changes.</done>
</task>
</tasks>

<verification>
- python -m compileall backend/app/platform/extensions/protocols.py backend/app/platform/extensions/defaults.py backend/app/platform/extensions/__init__.py
- cd backend && uv run pytest tests/test_workflow_extension.py
- cd backend && uv run ruff check app/platform/extensions/protocols.py app/platform/extensions/defaults.py app/platform/extensions/__init__.py tests/test_workflow_extension.py
</verification>

<success_criteria>
- WORK-01 is satisfied by the Protocol and transition context.
- WORK-02 foundation is satisfied by the default status order and one-step transition map.
- WORK-04 foundation is satisfied by the overlay-dispatch seam test.
</success_criteria>

<output>
After completion, create `.planning/phases/233-workflow-extension-protocol/233-01-SUMMARY.md`.
</output>

---
phase: 233-workflow-extension-protocol
plan: 04
type: execute
wave: 4
depends_on:
  - 233-03
files_modified:
  - backend/tests/test_layering.py
  - .planning/phases/233-workflow-extension-protocol/233-VERIFICATION.md
autonomous: true
requirements:
  - WORK-05
must_haves:
  truths:
    - "Architecture/regression tests fail if known dataset publication transition call sites bypass WorkflowExtension."
    - "The guard stays narrow: publication endpoints and the metadata record_status helper are checked, while seed/import initial status assignment is not blocked."
    - "Negative-control proof is recorded and reverted."
    - "Phase verification records WORK-01 through WORK-05 evidence and exact residual risks, if any."
  artifacts:
    - path: backend/tests/test_layering.py
      provides: "workflow extension bypass guard"
      contains: "test_workflow_publication_chokepoints_use_extension"
    - path: .planning/phases/233-workflow-extension-protocol/233-VERIFICATION.md
      provides: "goal-backward phase verification"
      contains: "WORK-05"
  key_links:
    - from: "backend/tests/test_layering.py:test_workflow_publication_chokepoints_use_extension"
      to: "backend/app/modules/catalog/datasets/api/router_data.py"
      via: "source scan for get_workflow_extension/allowed_transitions/on_transition in publication endpoint path"
      pattern: "get_workflow_extension"
    - from: "backend/tests/test_layering.py:test_workflow_publication_chokepoints_use_extension"
      to: "backend/app/modules/catalog/datasets/domain/service_metadata.py"
      via: "source scan for metadata_patch workflow routing"
      pattern: "metadata_patch"
---

<objective>
Seal the workflow extension seam with a narrow architecture guard and complete Phase 233 verification.

Purpose: prevent future publication lifecycle changes from reintroducing hardcoded route logic that Enterprise overlays cannot intercept.
Output: test_layering.py guard plus 233-VERIFICATION.md.
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
@.planning/phases/233-workflow-extension-protocol/233-02-SUMMARY.md
@.planning/phases/233-workflow-extension-protocol/233-03-SUMMARY.md

Relevant source:
@backend/tests/test_layering.py
@backend/app/modules/catalog/datasets/api/router_data.py
@backend/app/modules/catalog/datasets/domain/service_metadata.py
</context>

<tasks>
<task type="auto">
  <name>Add workflow publication chokepoint guard</name>
  <files>backend/tests/test_layering.py</files>
  <action>Update the test_layering.py module docstring to include Phase 233 WORK-05. Add test_workflow_publication_chokepoints_use_extension. Keep it source-level and narrow. It must assert that router_data.py's publication transition path uses get_workflow_extension(), allowed_transitions(), and on_transition() for both /status/ and /target-status/ behavior, and that service_metadata.py's _apply_record_status_change uses get_workflow_extension(), allowed_transitions(), on_transition(), and mode "metadata_patch". The guard should not scan factories, ingest tasks, source imports, or seed paths that assign initial record_status.</action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_layering.py::test_workflow_publication_chokepoints_use_extension</automated>
  </verify>
  <done>The guard passes on the routed implementation and names the offending surface in failure messages.</done>
</task>

<task type="auto">
  <name>Run negative control and write phase verification</name>
  <files>backend/tests/test_layering.py, .planning/phases/233-workflow-extension-protocol/233-VERIFICATION.md</files>
  <action>Temporarily bypass the extension at one known transition point, such as renaming `.allowed_transitions(` in router_data.py or service_metadata.py to a non-existent call, confirm test_workflow_publication_chokepoints_use_extension fails with the expected WORK-05 message, then revert the temporary mutation. Run focused workflow, lifecycle, validation, migration, and guard commands. Create 233-VERIFICATION.md recording status, requirement coverage for WORK-01 through WORK-05, command evidence, negative-control evidence, and residual risks. Do not broaden scope into approval UI, event bus, reviewer assignment, or workflow-admin settings.</action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_workflow_extension.py tests/test_publication_lifecycle.py tests/test_validation.py::test_publish_blocked_when_hard_validation_fails tests/test_validation.py::test_publish_succeeds_when_all_required_fields_present tests/test_validation.py::test_publish_allowed_when_require_metadata_off tests/test_layering.py::test_workflow_publication_chokepoints_use_extension</automated>
  </verify>
  <done>Negative control is documented and reverted; 233-VERIFICATION.md reports pass or exact actionable gaps.</done>
</task>
</tasks>

<verification>
- cd backend && uv run alembic upgrade head
- cd backend && uv run pytest tests/test_workflow_extension.py tests/test_publication_lifecycle.py tests/test_validation.py::test_publish_blocked_when_hard_validation_fails tests/test_validation.py::test_publish_succeeds_when_all_required_fields_present tests/test_validation.py::test_publish_allowed_when_require_metadata_off tests/test_layering.py::test_workflow_publication_chokepoints_use_extension
- cd backend && uv run ruff check app/platform/extensions app/modules/catalog/datasets/domain/schemas.py app/modules/catalog/datasets/api/router_data.py app/modules/catalog/datasets/domain/service_metadata.py app/modules/catalog/datasets/api/router.py tests/test_workflow_extension.py tests/test_publication_lifecycle.py tests/test_validation.py tests/test_layering.py
</verification>

<success_criteria>
- WORK-05 is satisfied by a guard that fails on known bypasses.
- The phase verification artifact maps WORK-01 through WORK-05 to concrete evidence.
- Deferred ideas from 233-CONTEXT.md remain out of scope.
</success_criteria>

<output>
After completion, create `.planning/phases/233-workflow-extension-protocol/233-04-SUMMARY.md`.
</output>

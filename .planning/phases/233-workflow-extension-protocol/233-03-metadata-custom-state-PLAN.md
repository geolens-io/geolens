---
phase: 233-workflow-extension-protocol
plan: 03
type: execute
wave: 3
depends_on:
  - 233-02
files_modified:
  - backend/app/modules/catalog/datasets/domain/models.py
  - backend/alembic/versions/0003_workflow_status_extension.py
  - backend/app/modules/catalog/datasets/domain/service_metadata.py
  - backend/app/modules/catalog/datasets/api/router.py
  - backend/tests/test_workflow_extension.py
  - backend/tests/test_validation.py
autonomous: true
requirements:
  - WORK-02
  - WORK-03
  - WORK-04
must_haves:
  truths:
    - "The database and ORM no longer hardcode the four Community statuses as a persistence constraint."
    - "PATCH /datasets/{id} cannot bypass WorkflowExtension when record_status is included in metadata updates."
    - "Community metadata-patch behavior is preserved: default direct publish still validates metadata, sets published_at, returns the same metadata response, and emits the existing metadata.edit audit row from the route."
    - "A test overlay can persist an extension-defined custom status without changing core route logic."
  artifacts:
    - path: backend/alembic/versions/0003_workflow_status_extension.py
      provides: "migration relaxing catalog.records record_status check constraint"
      contains: "chk_records_record_status"
    - path: backend/app/modules/catalog/datasets/domain/models.py
      provides: "Record model without hardcoded record_status CheckConstraint"
      contains: "record_status"
    - path: backend/app/modules/catalog/datasets/domain/service_metadata.py
      provides: "metadata record_status workflow routing"
      contains: "get_workflow_extension"
    - path: backend/tests/test_workflow_extension.py
      provides: "metadata bypass and custom-state overlay tests"
      contains: "metadata_patch"
  key_links:
    - from: "backend/app/modules/catalog/datasets/api/router.py:update_dataset_metadata"
      to: "backend/app/modules/catalog/datasets/domain/service_metadata.py:update_user_metadata"
      via: "passes actor=user as well as actor_id=user.id"
      pattern: "actor=user"
    - from: "backend/app/modules/catalog/datasets/domain/service_metadata.py:_apply_record_status_change"
      to: "backend/app/platform/extensions:get_workflow_extension"
      via: "metadata_patch WorkflowTransitionContext before record_status assignment"
      pattern: "metadata_patch"
---

<objective>
Close the adjacent metadata PATCH bypass and relax persistence so extension-defined statuses can exist.

Purpose: Enterprise approval workflows must not be bypassable through DatasetMeta.record_status, and custom workflow states must not require a core database fork.
Output: metadata status writes route through WorkflowExtension, the record_status DB check is relaxed, and tests prove custom-state readiness.
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

Relevant source:
@backend/app/modules/catalog/datasets/domain/models.py
@backend/alembic/versions/0001_baseline.py
@backend/alembic/versions/0002_procrastinate.py
@backend/app/modules/catalog/datasets/domain/service_metadata.py
@backend/app/modules/catalog/datasets/api/router.py
@backend/tests/test_validation.py
@backend/tests/test_workflow_extension.py
</context>

<tasks>
<task type="auto">
  <name>Relax record_status persistence constraint</name>
  <files>backend/app/modules/catalog/datasets/domain/models.py, backend/alembic/versions/0003_workflow_status_extension.py</files>
  <action>Create a new core Alembic migration with revision "0003_workflow_status_extension" and down_revision "0002_procrastinate". In upgrade(), drop `catalog.records` constraint `chk_records_record_status` using SQL that is safe if the constraint is already absent. In downgrade(), recreate the Community check constraint; it may fail if custom statuses are present, which is the correct safety behavior. Remove the hardcoded record_status CheckConstraint from the Record ORM model so metadata matches the migrated schema. Do not edit 0001_baseline.py; fresh databases should create the old baseline constraint and then drop it in 0003.</action>
  <verify>
    <automated>cd backend && uv run alembic upgrade head</automated>
  </verify>
  <done>Alembic head can upgrade and the ORM no longer declares the four-state record_status check.</done>
</task>

<task type="auto">
  <name>Route metadata record_status writes through WorkflowExtension</name>
  <files>backend/app/modules/catalog/datasets/domain/service_metadata.py, backend/app/modules/catalog/datasets/api/router.py</files>
  <action>Extend update_user_metadata() to accept `actor: Identity | None = None` while preserving actor_id behavior. Pass actor=user from update_dataset_metadata(). In _apply_record_status_change(), if new_status differs from record.record_status, build WorkflowTransitionContext(mode="metadata_patch"), call get_workflow_extension().allowed_transitions(context), and raise ValueError with the existing `Cannot transition from ... Allowed: ...` detail style when denied. Preserve current metadata behavior in Community mode: direct draft -> published through PATCH /datasets/{id} remains allowed by DefaultWorkflowExtension metadata_patch mode, REQUIRE_METADATA_FOR_PUBLISH validation still runs before publishing, published_at is set when transitioning to published, the route still owns audit_emit/commit/refresh/cache invalidation, and the extension does not commit independently. Await workflow.on_transition(context) after assignment and before the caller's flush/commit.</action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_validation.py::test_publish_blocked_when_hard_validation_fails tests/test_validation.py::test_publish_succeeds_when_all_required_fields_present tests/test_validation.py::test_publish_allowed_when_require_metadata_off</automated>
  </verify>
  <done>Metadata PATCH record_status changes are interceptable by WorkflowExtension with no Community API regression.</done>
</task>

<task type="auto">
  <name>Add metadata bypass and custom-state overlay tests</name>
  <files>backend/tests/test_workflow_extension.py, backend/tests/test_validation.py</files>
  <action>Add focused tests proving a workflow overlay can block metadata PATCH record_status=published and the API returns 422 instead of bypassing approval policy. Add a custom-state proof now that the DB constraint is relaxed: register a workflow overlay whose status_order includes "review" and whose allowed transitions include draft -> review, create a draft dataset, PATCH /datasets/{id}/status/ with {"status": "review"}, and assert the response and persisted record_status are "review". Keep existing validation tests for Community direct publish green; only strengthen assertions if needed to prove published_at is still set on publish.</action>
  <verify>
    <automated>cd backend && uv run pytest tests/test_workflow_extension.py tests/test_validation.py::test_publish_succeeds_when_all_required_fields_present tests/test_validation.py::test_publish_allowed_when_require_metadata_off</automated>
  </verify>
  <done>Enterprise-style block and custom-state add behavior are proven without editing core route logic per overlay.</done>
</task>
</tasks>

<verification>
- cd backend && uv run alembic upgrade head
- cd backend && uv run pytest tests/test_workflow_extension.py tests/test_validation.py::test_publish_blocked_when_hard_validation_fails tests/test_validation.py::test_publish_succeeds_when_all_required_fields_present tests/test_validation.py::test_publish_allowed_when_require_metadata_off
- cd backend && uv run ruff check app/modules/catalog/datasets/domain/models.py app/modules/catalog/datasets/domain/service_metadata.py app/modules/catalog/datasets/api/router.py tests/test_workflow_extension.py tests/test_validation.py
</verification>

<success_criteria>
- WORK-02 remains true for metadata publish validation, audit, transaction, and response behavior.
- WORK-03 includes the adjacent metadata PATCH transition surface.
- WORK-04 includes a custom-state overlay proof.
</success_criteria>

<output>
After completion, create `.planning/phases/233-workflow-extension-protocol/233-03-SUMMARY.md`.
</output>

---
phase: 232-permission-extension-protocol
plan: 03
type: execute
wave: 3
depends_on:
  - 232-02
files_modified:
  - backend/tests/test_layering.py
  - .planning/phases/232-permission-extension-protocol/232-VERIFICATION.md
autonomous: true
requirements:
  - PERM-05
must_haves:
  truths:
    - "Architecture/regression guard fails when known permission or visibility chokepoints bypass PermissionExtension."
    - "Negative-control proof is recorded and reverted."
    - "Phase verification records passed status or exact remaining gaps."
  artifacts:
    - path: backend/tests/test_layering.py
      provides: "Permission extension bypass guard"
      contains: "test_permission_chokepoints_use_extension"
    - path: .planning/phases/232-permission-extension-protocol/232-VERIFICATION.md
      provides: "Goal-backward phase verification"
      contains: "status:"
  key_links:
    - from: "backend/tests/test_layering.py:test_permission_chokepoints_use_extension"
      to: "backend/app/modules/auth/dependencies.py and backend/app/modules/catalog/authorization.py"
      via: "source scan for get_permission_extension/check_permission/filter_visible"
      pattern: "get_permission_extension"
---

<objective>
Seal the permission extension seam with a narrow regression guard and complete phase verification.

Purpose: prevent future direct permission/visibility decisions from bypassing the extension at known chokepoints.
Output: architecture guard plus 232-VERIFICATION.md.
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
@.planning/phases/232-permission-extension-protocol/232-CONTEXT.md
@.planning/phases/232-permission-extension-protocol/232-01-SUMMARY.md
@.planning/phases/232-permission-extension-protocol/232-02-SUMMARY.md

Relevant source:
@backend/tests/test_layering.py
@backend/app/modules/auth/dependencies.py
@backend/app/modules/catalog/authorization.py
</context>

<tasks>
<task type="auto">
  <name>Add permission chokepoint guard</name>
  <files>backend/tests/test_layering.py</files>
  <action>Add test_permission_chokepoints_use_extension. The guard should assert require_permission() contains an extension check and catalog authorization contains extension visibility filtering. Keep it source-level and narrow to avoid false positives in unrelated auth/catalog code.</action>
  <verify>cd backend && uv run pytest tests/test_layering.py::test_permission_chokepoints_use_extension</verify>
  <done>The guard passes on the routed implementation.</done>
</task>

<task type="auto">
  <name>Run negative control and verification</name>
  <files>backend/tests/test_layering.py, .planning/phases/232-permission-extension-protocol/232-VERIFICATION.md</files>
  <action>Temporarily remove or rename the extension call in one known chokepoint, confirm the guard fails, then revert. Run focused tests and write 232-VERIFICATION.md with status, requirements coverage, commands, and any residual risks.</action>
  <verify>cd backend && uv run pytest tests/test_permission_extension.py tests/test_permissions.py::TestRequirePermission tests/test_layering.py::test_permission_chokepoints_use_extension</verify>
  <done>Verification artifact exists and reports passed or concrete gaps.</done>
</task>
</tasks>

<verification>
- cd backend && uv run pytest tests/test_permission_extension.py tests/test_permissions.py::TestRequirePermission tests/test_layering.py::test_permission_chokepoints_use_extension
- cd backend && uv run ruff check app/platform/extensions app/modules/auth/dependencies.py app/modules/catalog/authorization.py tests/test_permission_extension.py tests/test_permissions.py tests/test_layering.py
</verification>

<output>
After completion, create `.planning/phases/232-permission-extension-protocol/232-03-SUMMARY.md`.
</output>

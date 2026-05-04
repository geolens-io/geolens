---
phase: 232-permission-extension-protocol
plan: 02
type: execute
wave: 2
depends_on:
  - 232-01
files_modified:
  - backend/app/modules/auth/dependencies.py
  - backend/app/modules/catalog/authorization.py
  - backend/tests/test_permissions.py
  - backend/tests/test_permission_extension.py
autonomous: true
requirements:
  - PERM-02
  - PERM-03
  - PERM-04
must_haves:
  truths:
    - "require_permission() asks get_permission_extension().check_permission() for every requested capability."
    - "Community mode keeps current role/capability behavior, request caching, 403 detail strings, and /auth/me/permissions responses."
    - "apply_visibility_filter() delegates to get_permission_extension().filter_visible()."
    - "Single-dataset catalog access cannot bypass overlay visibility rules from catalog/authorization.py."
    - "Focused tests prove overlay denial and overlay filtering affect routed call sites."
  artifacts:
    - path: backend/app/modules/auth/dependencies.py
      provides: "require_permission routed through PermissionExtension"
      contains: "get_permission_extension"
    - path: backend/app/modules/catalog/authorization.py
      provides: "catalog visibility helpers routed through PermissionExtension"
      contains: "get_permission_extension"
  key_links:
    - from: "backend/app/modules/auth/dependencies.py:require_permission"
      to: "backend/app/platform/extensions:get_permission_extension"
      via: "await permission_ext.check_permission(...)"
      pattern: "check_permission"
    - from: "backend/app/modules/catalog/authorization.py:apply_visibility_filter"
      to: "backend/app/platform/extensions:get_permission_extension"
      via: "permission_ext.filter_visible(...)"
      pattern: "filter_visible"
---

<objective>
Route the existing permission and catalog visibility chokepoints through PermissionExtension while preserving Community behavior and API semantics.

Purpose: close the actual seam gap identified by the open-core audits.
Output: require_permission(), apply_visibility_filter(), and single-dataset authorization paths consult the extension.
</objective>

<execution_context>
@/Users/ishiland/.codex/get-shit-done/workflows/execute-plan.md
@/Users/ishiland/.codex/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/232-permission-extension-protocol/232-CONTEXT.md
@.planning/phases/232-permission-extension-protocol/232-01-SUMMARY.md

Relevant source:
@backend/app/modules/auth/dependencies.py
@backend/app/modules/auth/permissions.py
@backend/app/modules/catalog/authorization.py
@backend/tests/test_permissions.py
@backend/tests/test_permission_extension.py
</context>

<tasks>
<task type="auto">
  <name>Wire require_permission through the extension</name>
  <files>backend/app/modules/auth/dependencies.py</files>
  <action>Replace the inline matrix grant decision inside require_permission() with get_permission_extension().check_permission(). Preserve user-role and effective-permission request caching, require all requested capabilities, and raise the same HTTPException detail on denial.</action>
  <verify>cd backend && uv run pytest tests/test_permissions.py::TestRequirePermission</verify>
  <done>Existing permission endpoint and update-reflection tests still pass.</done>
</task>

<task type="auto">
  <name>Wire catalog visibility helpers through the extension</name>
  <files>backend/app/modules/catalog/authorization.py</files>
  <action>Make apply_visibility_filter() delegate to the extension. Ensure check_dataset_access_or_anonymous() and check_dataset_access() remain consistent with overlay visibility rules so detail endpoints cannot bypass stricter filtering. Preserve 404 behavior for denied datasets.</action>
  <verify>cd backend && uv run pytest tests/test_datasets.py::TestListDatasets tests/test_datasets.py::TestGetDataset</verify>
  <done>List and detail visibility behavior remains compatible in Community mode.</done>
</task>

<task type="auto">
  <name>Add routed-call-site regression tests</name>
  <files>backend/tests/test_permissions.py, backend/tests/test_permission_extension.py</files>
  <action>Add focused tests that patch/register a PermissionExtension overlay and prove require_permission() uses it for denial and catalog authorization uses it for filtering. Prefer small unit tests over broad DB setup where possible.</action>
  <verify>cd backend && uv run pytest tests/test_permission_extension.py tests/test_permissions.py::TestRequirePermission</verify>
  <done>Overlay behavior is observable through production call-site helpers.</done>
</task>
</tasks>

<verification>
- cd backend && uv run pytest tests/test_permission_extension.py tests/test_permissions.py::TestRequirePermission
- cd backend && uv run pytest tests/test_datasets.py::TestListDatasets tests/test_datasets.py::TestGetDataset
- cd backend && uv run ruff check app/modules/auth/dependencies.py app/modules/catalog/authorization.py tests/test_permissions.py tests/test_permission_extension.py
</verification>

<output>
After completion, create `.planning/phases/232-permission-extension-protocol/232-02-SUMMARY.md`.
</output>

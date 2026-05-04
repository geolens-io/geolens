---
phase: 232-permission-extension-protocol
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/platform/extensions/protocols.py
  - backend/app/platform/extensions/defaults.py
  - backend/app/platform/extensions/__init__.py
  - backend/tests/test_permission_extension.py
autonomous: true
requirements:
  - PERM-01
  - PERM-02
  - PERM-04
must_haves:
  truths:
    - "PermissionExtension Protocol exists and exposes action-level permission checks plus catalog visibility filtering."
    - "DefaultPermissionExtension preserves the effective permission matrix and current default visibility filter behavior."
    - "get_permission_extension() returns the default in Community mode and a registered overlay when present."
    - "A test overlay can deny/allow an action and alter visible catalog records without modifying core files."
  artifacts:
    - path: backend/app/platform/extensions/protocols.py
      provides: "PermissionExtension Protocol"
      contains: "class PermissionExtension"
    - path: backend/app/platform/extensions/defaults.py
      provides: "DefaultPermissionExtension"
      contains: "class DefaultPermissionExtension"
    - path: backend/app/platform/extensions/__init__.py
      provides: "get_permission_extension accessor"
      contains: "def get_permission_extension"
    - path: backend/tests/test_permission_extension.py
      provides: "default, overlay, and visibility seam tests"
      contains: "test_overlay_permission_extension_is_dispatched"
  key_links:
    - from: "backend/app/platform/extensions/__init__.py:get_permission_extension"
      to: "backend/app/platform/extensions/defaults.py:DefaultPermissionExtension"
      via: "fallback when _extensions['permission'] is missing"
      pattern: "DefaultPermissionExtension"
---

<objective>
Add the PermissionExtension Protocol, the Community default implementation, the typed registry accessor, and focused seam tests without changing production call sites yet.

Purpose: establish the permission extension surface safely before routing auth and catalog authorization through it.
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
@.planning/phases/232-permission-extension-protocol/232-CONTEXT.md

Relevant source:
@backend/app/platform/extensions/protocols.py
@backend/app/platform/extensions/defaults.py
@backend/app/platform/extensions/__init__.py
@backend/app/modules/auth/permissions.py
@backend/app/modules/catalog/authorization.py
@backend/tests/test_extensions.py
@backend/tests/test_ai_provider_extension.py
</context>

<tasks>
<task type="auto">
  <name>Add PermissionExtension Protocol</name>
  <files>backend/app/platform/extensions/protocols.py</files>
  <action>Add a runtime-checkable Protocol with an async check_permission hook and a sync filter_visible hook. Keep signatures broad enough for user, roles, session-backed permission overrides, optional resource context, SQLAlchemy Select filtering, and the current Record/DatasetGrant call shape.</action>
  <verify>python -m compileall backend/app/platform/extensions/protocols.py</verify>
  <done>Protocol imports cleanly and uses existing extension typing style.</done>
</task>

<task type="auto">
  <name>Add default implementation and accessor</name>
  <files>backend/app/platform/extensions/defaults.py, backend/app/platform/extensions/__init__.py</files>
  <action>Add DefaultPermissionExtension with deferred imports into auth permissions and catalog authorization logic. Add get_permission_extension() using a single-slot "permission" registry key and Community default fallback.</action>
  <verify>python -m compileall backend/app/platform/extensions/defaults.py backend/app/platform/extensions/__init__.py</verify>
  <done>Default implementation preserves existing matrix and visibility logic when called directly.</done>
</task>

<task type="auto">
  <name>Add seam tests</name>
  <files>backend/tests/test_permission_extension.py</files>
  <action>Add tests following the existing registry isolation fixture pattern. Cover default accessor, Protocol satisfaction, overlay dispatch for action decisions, and overlay visibility filtering of a SQLAlchemy statement.</action>
  <verify>cd backend && uv run pytest tests/test_permission_extension.py</verify>
  <done>New permission extension tests pass.</done>
</task>
</tasks>

<verification>
- cd backend && uv run pytest tests/test_permission_extension.py
- cd backend && uv run ruff check app/platform/extensions/protocols.py app/platform/extensions/defaults.py app/platform/extensions/__init__.py tests/test_permission_extension.py
</verification>

<output>
After completion, create `.planning/phases/232-permission-extension-protocol/232-01-SUMMARY.md`.
</output>

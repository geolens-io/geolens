# Phase 232: permission-extension-protocol - Context

**Gathered:** 2026-05-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Add a first-class `PermissionExtension` seam at the platform extension layer. The seam must cover action/capability checks used by `require_permission()` and catalog visibility filtering in `backend/app/modules/catalog/authorization.py`, while preserving the existing Community RBAC behavior: `DEFAULT_ROLE_PERMISSIONS`, admin-configurable `ROLE_PERMISSIONS` overrides, lockout/escalation validation, user-role caching, and current API error semantics.

The phase is a governance seam extraction, not an advanced-RBAC product build. It enables Enterprise overlays to inject advanced RBAC, ABAC, and row-level catalog filtering without changing core. It does not add field-level masking, a new permissions admin UI, new product gates, tenant scoping, or Cloud multi-tenant policy infrastructure.

Auto-mode note: this context was gathered from `$gsd-discuss-phase 232 --auto --chain`, so decisions below are conservative defaults derived from the roadmap, the 2026-05-02/2026-05-03 open-core audits, and the existing extension registry patterns.

</domain>

<decisions>
## Implementation Decisions

### Permission Decision Contract

- Add `PermissionExtension` as a `@runtime_checkable` Protocol in `backend/app/platform/extensions/protocols.py`.
- The action-level hook should decide one capability/action at a time and return an allow/deny result, leaving `require_permission()` responsible for FastAPI dependency behavior and HTTP response shape.
- Use the existing capability strings as the action vocabulary (`upload`, `edit_metadata`, `manage_users`, `manage_settings`, and the rest of `ALL_CAPABILITIES`). Do not introduce a new action taxonomy in this phase.
- Preserve current multi-capability semantics in `require_permission(*capabilities)`: every requested capability must be granted; a user may satisfy the check through any of their roles; denial remains `403` with `Missing permission: {capability}`.
- Include enough context in the hook for future ABAC/resource-aware checks without forcing Enterprise overlays to fork the dependency. Default expected shape is async and session-aware, with user, capability/action, user roles, and optional resource context available. Planner may refine the exact signature, but it must support current DB-backed permission overrides and future resource-aware overlays.

### Default Permission Behavior

- Ship `DefaultPermissionExtension` in `backend/app/platform/extensions/defaults.py`.
- The default implementation preserves today's behavior by using the effective permission matrix from `backend/app/modules/auth/permissions.py`, including deep merge of stored `ROLE_PERMISSIONS` over `DEFAULT_ROLE_PERMISSIONS`.
- Keep `validate_permission_matrix()` and its lockout/escalation guarantees intact. Admin must retain `manage_users` and `manage_settings`; non-admin roles must not gain those admin-only capabilities through Community configuration.
- Preserve request-scoped caching where it exists today (`_user_roles` and `_effective_permissions` on `request.state`) unless research proves an equivalent cache belongs at the extension boundary. Do not add extra per-route DB churn as part of the seam.
- Avoid moving permission constants or stored config keys unless it is necessary to break a real import cycle. Public import compatibility from `app.modules.auth.permissions` should be preserved for existing tests and callers.

### Registry Shape

- Use a single-slot typed accessor, `get_permission_extension()`, following the `get_identity_extension()`, `get_processing_port()`, and `get_catalog_port()` pattern.
- Registry key should be a simple singleton key, preferably `"permission"`, unless research identifies an existing naming convention that argues for a more specific key.
- Community mode returns a new/default `DefaultPermissionExtension` when no overlay is registered.
- Enterprise overlays replace the permission policy by registering under the singleton key. If they need additive behavior, they can wrap or delegate to `DefaultPermissionExtension`; core should not define list-composition conflict semantics in this phase.
- Keep registration compatible with the existing `geolens.extensions` entry-point callback shape: `def register_extensions(registry: dict) -> None: ...`.

### Catalog Visibility Filtering

- Route the known catalog visibility chokepoints in `backend/app/modules/catalog/authorization.py` through the permission extension.
- Minimum bound: `apply_visibility_filter()` must delegate its SQLAlchemy `Select` filtering to the extension so overlays can apply row-level filters without modifying core.
- Also examine and route single-dataset visibility decisions in the same module when they would otherwise bypass an overlay's visibility rule. The current helpers include `check_dataset_access_or_anonymous()` and `check_dataset_access()`; planner should keep those paths consistent with the query-level hook.
- Preserve today's Community visibility rules exactly: admins see all datasets; anonymous users see only public published datasets; authenticated non-admin users see public datasets, their own private/unpublished datasets, and restricted datasets granted through their roles; non-admin users cannot see other users' drafts/unpublished records.
- Keep denied dataset access returning `404 Dataset not found`, not `403`, to preserve current privacy behavior.
- Do not expand into field-level masking, column-level access, collection-level policy authoring, or tenant-context propagation. Those are future phases.

### Test Overlay And Guards

- Add tests proving an overlay can alter action-level permission decisions through the registry/entry-point pattern without modifying core.
- Add tests proving an overlay can alter catalog visibility filtering through the registry/entry-point pattern or a focused test registry override.
- Keep default-behavior regression coverage for `require_permission()`, `get_effective_permissions()`, permission matrix validation, and catalog visibility/access helpers.
- Add or extend an architecture guard so known permission/visibility chokepoints fail tests if they bypass `get_permission_extension()`. The guard should be narrow and explicit enough to avoid noisy false positives in unrelated auth/catalog code.
- Include a negative-control proof for the guard: temporarily bypass the extension in a known chokepoint, confirm the guard fails with the offending line surfaced, then revert.

### Behavior Preservation

- Public API responses, status codes, auth dependency signatures, permission names, admin settings persistence, and catalog query results must remain unchanged in Community mode.
- No Alembic migration is expected. If planning discovers a migration, treat that as a scope warning and justify it explicitly.
- No frontend work is expected. The permissions admin UI should continue to read/write the same role-permissions config surface.
- Keep the implementation small and audit-friendly. The outcome should make the 2026-05-02 audit's Policy/permission seam move from adaptable/yellow to green without starting a broader advanced-sharing rebuild.

### Claude's Discretion

- Exact Protocol method names are left to research/planning, with the roadmap's `check_permission(user, action, resource)` and `filter_visible(user, query)` wording as the semantic anchor.
- Exact plan decomposition is flexible. A likely split is: additive Protocol/default/accessor, route `require_permission()`, route catalog authorization helpers, then add tests/architecture guard.
- Planner may decide whether to expose a small structured decision object instead of raw `bool` for permission checks if it materially improves denial diagnostics without changing API responses. Default preference is `bool` for minimal surface area.
- Planner may decide whether catalog single-dataset access uses a dedicated extension method or is expressed through the same filtering hook, as long as overlay policies cannot be bypassed through detail endpoints.

</decisions>

<specifics>
## Specific Ideas

- Treat Phase 232 as the permission sibling of the recent extension phases: IdentityExtension single-slot accessor, ProcessingPort/CatalogPort singleton seams, and AI/Embedding provider tests for entry-point dispatch.
- Source audit language identifies policy/permission as the largest remaining Enterprise-relevant adaptable seam after Phases 225, 226, 230, and 231.
- The implementation should be easy to audit by reading three surfaces: `platform/extensions/protocols.py`, `platform/extensions/defaults.py`/`__init__.py`, and `modules/auth/dependencies.py` plus `modules/catalog/authorization.py`.
- Keep the future Enterprise use cases visible in tests: custom action denial and stricter visible-dataset filtering are enough to prove the seam.

</specifics>

<deferred>
## Deferred Ideas

- Field-level masking and column-level RBAC belong in a future advanced-RBAC phase.
- A redesigned permissions/admin policy UI belongs in a future product phase.
- Tenant scoping and Cloud multi-tenant isolation remain backlog Phase 999.6.
- Collection-level policy authoring and custom grant-management workflows are outside this seam extraction unless already covered by existing catalog visibility helpers.

</deferred>

---

*Phase: 232-permission-extension-protocol*
*Context gathered: 2026-05-03*

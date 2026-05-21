# Admin Page Organization Review - Research

**Researched:** 2026-03-28
**Domain:** Frontend admin panel structure, routing, API wiring
**Confidence:** HIGH (direct source code audit)

## Summary

The admin panel is well-structured with a clear three-tier sidebar (Overview, Operations, Settings) and clean routing. All routes map to real pages, all pages wire through TanStack Query hooks to real backend endpoints, and the settings tab architecture is solid. Two concrete issues found: (1) the audit log export button calls a backend endpoint that does not exist, and (2) one backend endpoint (`POST /config-ops/validate/`) has no frontend exposure. The overall organization is logical and complete.

## Architecture Map

### Sidebar Navigation Structure

```
Admin (SidebarHeader)
|
+-- [Overview group]
|   +-- Overview          /admin/overview         -> AdminOverviewPage
|
+-- [Operations group]
|   +-- Users             /admin/users            -> AdminUsersPage       (badge: pending count)
|   +-- Jobs              /admin/jobs             -> AdminJobsPage        (badge: failed count)
|   +-- Audit Log         /admin/audit            -> AdminAuditPage
|   +-- Published Maps    /admin/shared-maps      -> AdminSharedMapsPage
|
+-- [Settings group]
|   +-- General           /admin/settings/general       -> SettingsGeneralTab
|   +-- Auth              /admin/settings/auth          -> SettingsAuthTab
|   +-- AI                /admin/settings/ai            -> SettingsAITab
|   +-- Network           /admin/settings/network       -> SettingsNetworkTab
|   +-- Storage           /admin/settings/storage       -> SettingsStorageTab
|   +-- Map               /admin/settings/map           -> SettingsMapTab
|   +-- Appearance*       /admin/settings/appearance    -> SettingsAppearanceTab  (*enterprise only)
|   +-- Permissions        /admin/settings/permissions  -> SettingsPermissionsTab
|   +-- Config Operations /admin/config-ops             -> AdminConfigOpsPage
|
+-- [Footer]
    +-- Back to App       /
```

### Route Redirects (legacy cleanup)

All old routes properly redirect to new locations:
- `/admin` -> `/admin/overview`
- `/admin/settings` -> `/admin/settings/general`
- `/admin/share-tokens`, `/admin/embed-tokens` -> `/admin/shared-maps`
- `/admin/general` -> `/admin/settings/general`
- `/admin/basemaps`, `/admin/map-defaults`, `/admin/settings/appearance` -> `/admin/settings/map`
- `/admin/security` -> `/admin/settings/auth`
- `/admin/uploads` -> `/admin/settings/storage`
- `/admin/ai` -> `/admin/settings/ai`
- `/admin/infrastructure`, `/admin/settings/infrastructure` -> `/admin/overview`

## Wiring Audit

### Backend Endpoints vs Frontend Coverage

| Backend Route | Frontend API Function | Used In | Status |
|---|---|---|---|
| `GET /admin/stats/` | `getCatalogStats()` | StatsOverview | OK |
| `GET /admin/users/` | `listUsers()` | UserList, pending badge | OK |
| `GET /admin/users/names/` | `listUserNames()` | AuditLogViewer filter | OK |
| `GET /admin/users/{id}` | (not used directly) | -- | Unused but harmless |
| `POST /admin/users/` | `createUser()` | UserCreateDialog | OK |
| `PATCH /admin/users/{id}` | `updateUser()` | UserEditDialog | OK |
| `POST /admin/users/{id}/deactivate` | `deactivateUser()` | UserList | OK |
| `POST /admin/users/{id}/approve` | `approveUser()` | UserList | OK |
| `POST /admin/users/{id}/reject` | `rejectUser()` | UserList | OK |
| `DELETE /admin/users/{id}` | `deleteUser()` | UserDeleteDialog | OK |
| `GET /admin/jobs/` | `listAdminJobs()` | JobList, failed badge | OK |
| `GET /admin/audit-logs/` | `listAuditLogs()` | AuditLogViewer | OK |
| `GET /admin/ai-status/` | `getAIStatus()` | AIStatusCard, SettingsAITab | OK |
| `PATCH /admin/ai-status/` | (no direct call) | -- | Toggle is in SettingsAITab via different mechanism |
| `GET /admin/embedding-stats/` | `getEmbeddingStats()` | AIStatusCard, SettingsAITab | OK |
| `POST /admin/backfill-embeddings/` | `triggerBackfill()` | SettingsAITab | OK |
| `GET /admin/infrastructure/` | `getInfrastructure()` | StatsOverview (SystemHealthCard) | OK |
| `POST /admin/api-keys/` | `createApiKey()` | ApiKeySection | OK |
| `GET /admin/api-keys/` | `listApiKeys()` | ApiKeySection | OK |
| `DELETE /admin/api-keys/{id}` | `revokeApiKey()` | ApiKeySection | OK |
| `GET /admin/share-tokens/` | `listShareTokens()` | AdminSharedMapsPage | OK |
| `DELETE /admin/share-tokens/{id}` | `adminRevokeShareToken()` | AdminSharedMapsPage | OK |
| `GET /admin/embed-tokens/` | `listAdminEmbedTokens()` | EmbedTokensSubTable | OK |
| `POST /admin/embed-tokens/bulk-revoke/` | `bulkRevokeEmbedTokens()` | EmbedTokensSubTable | OK |
| `GET /settings/all/` | `getAllSettings()` | AdminSettingsPage | OK |
| `PUT /settings/` | `updateSettings()` | All settings tabs | OK |
| `POST /settings/reset/` | `resetSettings()` | Settings reset buttons | OK |
| `GET /settings/config-mode/` | `getConfigMode()` | AdminSettingsPage | OK |
| `GET /settings/api-key-status/` | `getApiKeyStatus()` | SettingsAITab | OK |
| `POST /settings/detect-embedding-dims/` | `detectEmbeddingDims()` | SettingsAITab | OK |
| `GET /settings/oauth-providers/` | `listOAuthProviders()` | SettingsAuthTab | OK |
| `POST /settings/oauth-providers/` | `createOAuthProvider()` | SettingsAuthTab | OK |
| `PUT /settings/oauth-providers/{id}` | `updateOAuthProvider()` | SettingsAuthTab | OK |
| `DELETE /settings/oauth-providers/{id}` | `deleteOAuthProvider()` | SettingsAuthTab | OK |
| `GET /settings/edition/` | (via `useEdition`) | Sidebar, tabs | OK |
| `GET /settings/branding/` | `getBranding()` | SettingsAppearanceTab | OK |
| `PUT /settings/branding/` | `updateBranding()` | SettingsAppearanceTab | OK |
| `GET /config-ops/export/` | `exportConfig()` | AdminConfigOpsPage | OK |
| `POST /config-ops/import/` | `importConfig()` | AdminConfigOpsPage | OK |
| `POST /config-ops/dry-run/` | `dryRunImport()` | AdminConfigOpsPage | OK |

### Issues Found

#### ISSUE 1: Audit Export Button Calls Nonexistent Backend Endpoint (BUG)

**Severity:** Medium -- visible to enterprise users, will produce a runtime error.

The `ExportSplitButton` component (shown in AuditLogViewer when `isEnterprise` is true) calls `exportAuditLogs()` in `frontend/src/api/admin.ts`, which fetches:
```
GET /admin/audit-logs/export/{csv|json}
```

This endpoint **does not exist** in the backend. The audit router (`backend/app/audit/router.py`) only has `GET /admin/audit-logs/` (list). The extension protocol (`AuditExtension`) defines `get_export_formats()` but no route implements it.

The frontend code is fully wired (button renders, download triggered via blob), but it will 404 at runtime.

**Files involved:**
- `frontend/src/api/admin.ts:199-225` -- `exportAuditLogs()` function
- `frontend/src/components/admin/ExportSplitButton.tsx` -- the button component
- `frontend/src/components/admin/AuditLogViewer.tsx:67-76` -- renders button when `isEnterprise`
- `backend/app/audit/router.py` -- missing export endpoint
- `backend/app/extensions/protocols.py:19-22` -- AuditExtension protocol stub

#### ISSUE 2: Config Validate Endpoint Not Exposed in Frontend (MINOR)

**Severity:** Low -- nice-to-have, not a bug.

The backend has `POST /config-ops/validate/` which validates connectivity to storage, cache, and OIDC providers. This is not exposed in the frontend ConfigOps page. The SystemHealthCard on the overview page provides similar health-check information via `/admin/infrastructure/`, so this may be intentionally omitted. But having an explicit "validate config" button on the Config Operations page would be a natural fit.

**Files involved:**
- `backend/app/config_ops/router.py:76-86` -- validate endpoint
- `frontend/src/pages/admin/AdminConfigOpsPage.tsx` -- no validate section
- `frontend/src/api/config-ops.ts` -- no validate function

## Organization Assessment

### What Works Well

1. **Clear three-tier grouping.** Overview (dashboard), Operations (day-to-day), Settings (configuration) is intuitive and standard for admin panels.

2. **Sidebar uses collapsible icon mode.** Mobile gets a trigger button. Desktop sidebar collapses to icons with tooltips. Footer has "Back to App" link.

3. **Settings as sub-routes.** Each settings tab is a separate route (`/admin/settings/:tab`), enabling deep-linking and browser back/forward. Tab routing in `AdminSettingsPage` validates the tab param and redirects unknowns to `general`.

4. **Badge system.** Users nav item shows pending approval count. Jobs nav item shows failed job count. Both use lightweight queries with 60s stale time.

5. **Enterprise gating.** Appearance tab hidden from sidebar when not enterprise edition. Audit export button hidden when not enterprise. Uses `useEdition()` consistently.

6. **Unsaved changes guard.** Settings pages use `useUnsavedGuard` to warn before navigating away with dirty forms.

7. **Legacy route redirects.** 10+ old routes properly redirect to new locations, preventing broken bookmarks.

8. **Config import/export.** Full dry-run preview before apply, merge vs overwrite modes, detailed change table. Well-built.

### Settings Tab Content Summary

| Tab | Fields/Features |
|---|---|
| General | require_metadata_for_publish, public_app_url, public_api_url, log_level, log_json |
| Auth | self_registration_enabled, default_role, session_lifetime_minutes, refresh_token_enabled + full OAuth/SAML provider CRUD table |
| AI | ai_enabled, semantic_search_enabled, ai_provider, embedding_model, embedding_dimensions, api key status, embedding stats, backfill trigger, dimension auto-detect |
| Network | cors_allowed_origins, global_rate_limit |
| Storage | upload_max_size_mb, upload_allowed_extensions, tile_cache_ttl |
| Map | basemaps CRUD (add/edit/remove/reorder), map_defaults (center, zoom), cdn_base_url |
| Appearance | show_badge (branding toggle) -- enterprise only |
| Permissions | Role-capability matrix (viewer/editor/admin x 8 capabilities) |

### Minor Observations (Not Bugs)

1. **Config Ops is in the Settings sidebar group** but it is not technically a settings tab -- it is its own page at `/admin/config-ops` (not under `/admin/settings/`). Visually this is fine since it appears at the bottom of the Settings group with its own wrench icon, but semantically it could be its own group. This is a style choice, not a problem.

2. **The "Appearance" redirect**: `/admin/settings/appearance` redirects to `/admin/settings/map` (line 86 of App.tsx), but the sidebar also lists an Appearance tab at `/admin/settings/appearance` (enterprise only). This means:
   - When enterprise: sidebar shows Appearance, clicking it loads the Appearance tab correctly (the route `/admin/settings/appearance` matches the `:tab` param route before the redirect route).
   - When not enterprise: the redirect catches any manual URL visit and sends to `/admin/settings/map`.
   - This works correctly because React Router matches more specific routes first, but the redirect definition at line 86 is dead code when enterprise is enabled. No functional issue.

3. **`PATCH /admin/ai-status/`** exists in the backend for toggling AI on/off but has no corresponding frontend API function. Instead, the SettingsAITab uses the unified `PUT /settings/` endpoint (via `updateSettings`) to toggle the `ai_enabled` key. This is consistent with the settings architecture -- the PATCH endpoint is effectively an older path that still works but is bypassed. Not a problem.

## Sources

All findings from direct source code audit of:
- `frontend/src/App.tsx` (route definitions)
- `frontend/src/components/admin/AdminSidebar.tsx` (navigation)
- `frontend/src/components/admin/AdminLayout.tsx` (layout shell)
- `frontend/src/api/admin.ts`, `frontend/src/api/settings.ts`, `frontend/src/api/config-ops.ts` (API layer)
- `frontend/src/hooks/use-admin.ts`, `frontend/src/hooks/use-settings.ts` (query hooks)
- `frontend/src/pages/admin/*.tsx` (all 7 admin pages)
- `frontend/src/components/admin/settings/*.tsx` (all 8 settings tabs)
- `backend/app/admin/router.py` (admin endpoints)
- `backend/app/audit/router.py` (audit endpoints)
- `backend/app/settings/router.py` (settings endpoints)
- `backend/app/config_ops/router.py` (config-ops endpoints)
- `backend/app/embed_tokens/admin_router.py` (embed token admin endpoints)
- `frontend/src/i18n/locales/en/common.json` and `admin.json` (i18n keys)

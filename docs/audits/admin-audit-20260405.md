# Admin Audit — 2026-04-05

## Scorecard

| Dimension | Grade | Rationale |
|-----------|-------|-----------|
| **Authorization Enforcement** | **B** | All admin endpoints correctly protected except 1 mismatch (GET /admin/ai-status/) and 1 critical gap (PATCH /datasets/{id}/status/) |
| **Permission Matrix Integrity** | **C** | Core CBAC sound but `validate_permission_matrix()` does not prevent granting manage_users/manage_settings to non-admin roles |
| **User Lifecycle Safety** | **C** | Last-admin demotion via `update_user()` not guarded; self-modification via PATCH not prevented; suspended status unused |
| **API Key Security** | **B** | Keys properly hashed (SHA-256), scoped to current user permissions, revocable. Missing audit trail on key CRUD |
| **Audit Log Completeness** | **D** | All user CRUD, API key CRUD, and several admin operations are NOT audit-logged. Settings/OAuth changes are well-logged |
| **Settings Governance** | **B** | Good validation on most settings. Token expiry, embedding_dims, tile_cache_ttl lack bounds validators. CORS wildcard mitigated at runtime |
| **Admin UI Consistency** | **A** | Layered route guards (ProtectedRoute → AdminRoute), confirmation dialogs on all destructive actions, proper error handling throughout |

**Overall Admin Health: C** (driven by audit log gaps and user lifecycle safety issues)

## Executive Summary

The GeoLens admin control plane has a well-designed CBAC system with correct permission enforcement on nearly all endpoints. The frontend admin UI is exemplary with layered auth guards, confirmation dialogs, and proper error handling. However, three significant gaps exist: (1) the `update_user()` service method lacks last-admin demotion protection — a critical invariant enforced for delete/deactivate but missing for role changes; (2) audit logging is absent for all user CRUD and API key operations, creating a compliance blind spot; (3) the permission matrix validator prevents admin lockout but does not prevent granting admin-level capabilities to non-admin roles. The highest-priority fix is the last-admin demotion guard, followed by adding audit logging to user and API key operations.

## 1. Authorization Enforcement

### 1a. Endpoint Protection Map

All 42+ admin endpoints were audited. Key findings:

| Endpoint | Method | Required Permission | Actual Protection | Status |
|----------|--------|-------------------|-------------------|--------|
| /admin/users/ | POST | manage_users | `require_permission("manage_users")` | Protected |
| /admin/users/ | GET | manage_users | `require_permission("manage_users")` | Protected |
| /admin/users/names/ | GET | manage_users | `require_permission("manage_users")` | Protected |
| /admin/users/{user_id} | GET | manage_users | `require_permission("manage_users")` | Protected |
| /admin/users/{user_id} | PATCH | manage_users | `require_permission("manage_users")` | Protected |
| /admin/users/{user_id}/deactivate/ | POST | manage_users | `require_permission("manage_users")` | Protected |
| /admin/users/{user_id}/approve/ | POST | manage_users | `require_permission("manage_users")` | Protected |
| /admin/users/{user_id}/reject/ | POST | manage_users | `require_permission("manage_users")` | Protected |
| /admin/users/{user_id} | DELETE | manage_users | `require_permission("manage_users")` | Protected |
| /admin/stats/ | GET | manage_users | `require_permission("manage_users")` | Protected |
| /admin/jobs/ | GET | manage_users | `require_permission("manage_users")` | Protected |
| /admin/api-keys/ | POST | manage_users | `require_permission("manage_users")` | Protected |
| /admin/api-keys/ | GET | manage_users | `require_permission("manage_users")` | Protected |
| /admin/api-keys/{key_id} | DELETE | manage_users | `require_permission("manage_users")` | Protected |
| /admin/ai-status/ | GET | manage_users | `get_current_active_user` | **Mismatch** |
| /admin/ai-status/ | PATCH | manage_users | `require_permission("manage_users")` | Protected |
| /admin/embedding-stats/ | GET | manage_users | `require_permission("manage_users")` | Protected |
| /admin/backfill-embeddings/ | POST | manage_users | `require_permission("manage_users")` | Protected |
| /admin/infrastructure/ | GET | manage_users | `require_permission("manage_users")` | Protected |
| /admin/share-tokens/ | GET | manage_users | `require_permission("manage_users")` | Protected |
| /admin/share-tokens/{token_id} | DELETE | manage_users | `require_permission("manage_users")` | Protected |
| /admin/embed-tokens/ | GET | manage_users | `require_permission("manage_users")` | Protected |
| /admin/embed-tokens/bulk-revoke/ | POST | manage_users | `require_permission("manage_users")` | Protected |
| /settings/all/ | GET | manage_settings | `require_permission("manage_settings")` | Protected |
| /settings/ | PUT | manage_settings | `require_permission("manage_settings")` | Protected |
| /settings/reset/ | POST | manage_settings | `require_permission("manage_settings")` | Protected |
| /settings/api-key-status/ | GET | manage_settings | `require_permission("manage_settings")` | Protected |
| /settings/detect-embedding-dims/ | POST | manage_settings | `require_permission("manage_settings")` | Protected |
| /settings/oauth-providers/ | GET | manage_settings | `require_permission("manage_settings")` | Protected |
| /settings/oauth-providers/ | POST | manage_settings | `require_permission("manage_settings")` | Protected |
| /settings/oauth-providers/{id} | PUT | manage_settings | `require_permission("manage_settings")` | Protected |
| /settings/oauth-providers/{id} | DELETE | manage_settings | `require_permission("manage_settings")` | Protected |
| /admin/audit-logs/ | GET | manage_settings | `require_permission("manage_settings")` | Protected |
| /admin/audit-logs/export/{format} | GET | manage_settings | `require_permission("manage_settings")` | Protected |
| /config-ops/export/ | GET | manage_settings | `require_permission("manage_settings")` | Protected |
| /config-ops/import/ | POST | manage_settings | `require_permission("manage_settings")` | Protected |
| /config-ops/validate/ | POST | manage_settings | `require_permission("manage_settings")` | Protected |
| /config-ops/dry-run/ | POST | manage_settings | `require_permission("manage_settings")` | Protected |
| /settings/config-mode/ | GET | Public | None (intentional) | Public |
| /settings/edition/ | GET | Public | None (intentional) | Public |
| /settings/branding/ | GET | Public | None (intentional) | Public |
| /settings/basemaps/ | GET | Public | None (intentional) | Public |
| /settings/map-defaults/ | GET | Public | None (intentional) | Public |
| /settings/enabled-widgets/ | GET | Public | None (intentional) | Public |
| /settings/tile-config/ | GET | Public | None (intentional) | Public |

### 1b. Permission Consistency

- User management endpoints consistently use `manage_users`
- Settings/config endpoints consistently use `manage_settings`
- Audit log endpoints use `manage_settings` (consistent with settings governance)

### 1c. Bypass Paths

**CRITICAL: PATCH /datasets/{dataset_id}/status/** (`backend/app/datasets/router_data.py`)
- Uses `get_current_active_user` instead of `require_permission("edit_metadata")`
- Any authenticated user can change dataset publication status (draft → ready → internal → published)
- No ownership check, no dataset access verification
- Impact: Unauthorized dataset visibility changes, potential data exposure

**LOW: GET /admin/ai-status/** (`backend/app/admin/router.py:464-482`)
- Uses `get_current_active_user` instead of `require_permission("manage_users")`
- Any authenticated user can view AI provider configuration (provider name, model, enabled status)
- Impact: Minor information disclosure (inconsistent with PATCH which requires manage_users)

## 2. Permission Matrix Integrity

### 2a. Matrix Implementation

- 8 capabilities correctly defined: upload, create_layers, export, edit_metadata, manage_collections, use_ai_chat, manage_users, manage_settings
- Default matrix correctly assigns: viewer=export only, editor=all except manage_*, admin=all
- `get_effective_permissions()` correctly deep-merges DB overrides with defaults and supports custom roles

### 2b. Customization Safety

`validate_permission_matrix()` enforces:
- Matrix must be a dict
- Admin role must exist
- Admin must have manage_users (lockout prevention)
- Admin must have manage_settings (lockout prevention)

**Gap**: Does NOT prevent granting manage_users or manage_settings to non-admin roles. An admin with manage_settings could set `{"viewer": {"manage_users": true}}`, allowing all viewers to manage users.

### 2c. Escalation Analysis

| Invariant | Status | Evidence |
|-----------|--------|----------|
| Admin lockout prevention | Enforced | `validate_permission_matrix()` checks admin.manage_users and admin.manage_settings |
| Editor cannot self-promote | Enforced | PATCH /admin/users/{id} requires manage_users; editors don't have it by default |
| Non-admin cannot get manage_* | **Weak** | Validator only prevents removal from admin, not granting to others |
| API key inherits current permissions | Enforced | `_resolve_api_key()` returns current user object; roles loaded at request time |
| Anonymous access boundaries | Enforced | `get_optional_user()` used only for public dataset/map/record browsing |

### 2d. API Key Inheritance

API keys correctly inherit the creating user's **current** permissions (not frozen at creation). When a user is downgraded or deactivated, their API keys immediately reflect the change because `_resolve_api_key()` loads the live user object with current roles.

## 3. User Lifecycle Safety

### 3a. Last-Admin Protection

| Operation | Last-Admin Guard | Status |
|-----------|-----------------|--------|
| Delete user | Counts other admins; blocks if last | **Safe** |
| Deactivate user | Counts other admins; blocks if last | **Safe** |
| Demote user (role change) | **No check** | **MISSING** |

**CRITICAL**: `AdminService.update_user()` handles role changes (lines 131-143) but does NOT check if demoting the last admin. An admin could be changed from admin to viewer when they're the sole admin, locking out the system.

### 3b. Self-Operation Prevention

| Operation | Self-Guard | Status |
|-----------|-----------|--------|
| Delete user | `user_id == current_user_id` check | **Safe** |
| Deactivate user | `user_id == current_user_id` check | **Safe** |
| Update user (PATCH) | No current_user injected into endpoint | **Weak** |

The PATCH /admin/users/{user_id} endpoint uses `dependencies=[Depends(require_permission("manage_users"))]` but does not inject `current_user`, so it cannot check for self-modification. An admin could theoretically change their own role.

### 3c. Status Transitions

- User model defines 4 statuses: active, pending, suspended, deactivated
- `suspended` status is defined in the model's check constraint but no endpoint sets it — dead code or incomplete feature
- No reactivation endpoint exists — deactivated users can only be reactivated via PATCH `{"is_active": true}`
- Dual tracking (`is_active` bool + `status` string) creates semantic confusion: deactivation sets `is_active=False` but `status` remains "active"

### 3d. Registration & Approval

- Registration controlled by `REGISTRATION_ENABLED` PersistentConfig setting
- New registrations created with `status="pending"`, `is_active=False`
- Pending users cannot authenticate: `get_current_user()` checks `user.status != "active"` and `user.is_active`
- Approval flow: admin calls POST /admin/users/{id}/approve/ with role → sets status=active, is_active=True
- Rejection: hard-deletes the pending user record

### 3e. Credential Handling

- Passwords hashed with bcrypt via `pwdlib` (`PasswordHash((BcryptHasher(),))`)
- Timing-attack prevention: dummy hash verification when username not found
- Passwords never returned in API responses (`UserResponse` schema excludes `password_hash`)
- **No password change endpoint exists** — passwords can only be set during creation/registration

## 4. API Key Security

### 4a. Storage Security

- Keys generated with `secrets.token_urlsafe(32)` (256-bit entropy)
- Hashed with SHA-256 before storage in `key_hash` column (unique, not null)
- Raw key returned only once at creation; cannot be retrieved afterward
- No key prefix or last-4-chars stored for identification (informational gap)

### 4b. Key Lifecycle

- Creation: admin-only via POST /admin/api-keys/ (manage_users) or self-service via POST /auth/api-keys/
- Revocation: soft-delete via `is_active = False`; immediate and irreversible
- `last_used_at` updated on each API key use
- **No expiration**: No `expires_at` field; keys valid indefinitely until revoked (informational)
- **No rate limiting** on key creation endpoints

### 4c. Permission Scope

API keys inherit the associated user's current role/permissions at request time. No frozen permissions. If user is downgraded, key immediately reflects lower permissions. If user is deactivated, key stops working.

### 4d. Transmission Security

Keys accepted via:
- `X-Api-Key` header (preferred)
- `api_key` query parameter (less secure — logged in URLs; by design for OGC API compatibility)

### 4e. Audit Trail

**MISSING**: Neither admin nor self-service API key creation or revocation generates audit log entries.
- `POST /admin/api-keys/` — no audit log
- `DELETE /admin/api-keys/{key_id}` — no audit log
- `POST /auth/api-keys/` — no audit log
- `DELETE /auth/api-keys/{key_id}` — no audit log

## 5. Audit Log Completeness

### 5a. Coverage Map

| Admin Operation | Audit Logged? | Details | IP? |
|----------------|--------------|---------|-----|
| Setting update (PersistentConfig.set) | YES | key, old_value, new_value | YES |
| Setting reset (PersistentConfig.reset) | YES | key, old_value, new_value | YES |
| OAuth provider create | YES | slug | YES |
| OAuth provider update | YES | slug | YES |
| OAuth provider delete | YES | slug | YES |
| Config import | YES | mode, counts | NO |
| Share token admin revoke | YES | map_id, cascade count | NO |
| Embed token bulk revoke | YES | count, token_ids | NO |
| Dataset deletion | YES | title, table_name | YES |
| **User creation** | **NO** | — | — |
| **User update** | **NO** | — | — |
| **User deactivation** | **NO** | — | — |
| **User approval** | **NO** | — | — |
| **User rejection** | **NO** | — | — |
| **User deletion** | **NO** | — | — |
| **API key creation (admin)** | **NO** | — | — |
| **API key revocation (admin)** | **NO** | — | — |
| **API key creation (self)** | **NO** | — | — |
| **API key revocation (self)** | **NO** | — | — |

### 5b. Immutability

- No DELETE or UPDATE endpoints exist for audit logs
- Foreign key uses `ondelete="SET NULL"` — user deletion preserves audit entries
- Audit logs are append-only and read-only via API

### 5c. Content Quality

Fields captured per entry: id (UUID), user_id, action, resource_type, resource_id, details (JSONB with before/after values), ip_address, created_at. Quality is good where logging exists.

### 5d. Query & Export

- Query supports: user_id, action, resource_type, date_from, date_to, search (username/action/resource_type ILIKE)
- Export: CSV and JSON formats with streaming via `stream_audit_logs()` for memory-efficient handling
- Max rows configurable (default 100K, max 1M)

## 6. Settings & Config Governance

### 6a. Validation

**Well-validated settings** (via SETTING_VALIDATORS):
- login_rate_limit: 1-1000
- global_rate_limit: 1-1000
- upload_max_size_mb: 1-10000
- upload_allowed_extensions: comma-separated, must start with "."
- basemaps: validated through BasemapEntry model
- map_defaults: lat/lng/zoom clamped to valid ranges
- public_app_url / public_api_url: absolute http(s) URL required
- enabled_widgets: list of non-empty strings or null

**Settings without bounds validation**:
- access_token_expire_minutes — can be set to 0 or negative
- refresh_token_expire_days — can be set to 0 or negative
- embedding_dims — can be set to 0 or negative (causes PostgreSQL vector(N) error)
- tile_cache_ttl — no bounds (0 would disable caching)

### 6b. Dangerous Settings

- **cors_allowed_origins**: No validator in SETTING_VALIDATORS, but **mitigated at runtime** — `DynamicCORSMiddleware` explicitly rejects wildcard `"*"` origins
- **role_permissions**: Validated for admin lockout prevention but not for privilege escalation to non-admin roles (see Section 2)
- **registration_enabled**: Boolean — toggling could open public registration; low risk since pending users require admin approval

### 6c. Import Safety

- ENV_ONLY_CONFIG blocks all imports (403)
- `role_permissions` validated before applying (lockout prevention)
- Per-key validators run on all settings during import
- OAuth client_secret required for new providers (prevents incomplete config)
- Dry-run mode available and functional
- Config export redacts OAuth client_secret_encrypted via `_provider_to_dict()`
- Cannot inject admin users or API keys via config import (only settings and OAuth providers)

### 6d. Public Exposure

Public settings endpoints return only safe metadata:
- `/settings/edition/` — edition name and feature flags
- `/settings/branding/` — show_badge, show_landing_page booleans
- `/settings/basemaps/` — basemap list with api_key stripped from response
- `/settings/map-defaults/` — center_lat, center_lng, zoom
- `/settings/enabled-widgets/` — widget ID list
- `/settings/tile-config/` — CDN URL, public app/api URLs
- `/settings/config-mode/` — env_only boolean

No secrets, credentials, or internal URLs leaked through public endpoints.

## 7. Admin UI Consistency

### 7a. Route Protection

- All admin routes wrapped in `<AdminRoute />` component that checks `useAuthStore().isAdmin()`
- `AdminRoute` nested under `<ProtectedRoute />` which checks for auth token first
- Order: Login → ProtectedRoute → AdminRoute → AdminLayout → Pages
- Non-admin users see "403 Forbidden" message
- Tested in AdminRoute.test.tsx with comprehensive coverage

### 7b. Permission-Based Rendering

- Admin link (Shield icon) in Navbar only shown when `can('manage_users')` returns true
- Both desktop and mobile menus respect this
- Enterprise-only "Appearance" settings tab filtered by `isEnterprise` flag
- No admin UI elements leak to non-admin pages

### 7c. Error Handling

- All dialogs show inline error messages from mutation state
- 409 conflict errors (duplicate username/email) display readable messages
- Loading spinners prevent double-submission
- Error boundaries on all admin routes via `<RouteErrorBoundary />`
- Unsaved changes guard on settings pages via `useUnsavedGuard()`

### 7d. Destructive Action Confirmation

| Operation | Confirmation Pattern | Status |
|-----------|---------------------|--------|
| Delete user | AlertDialog modal | Adequate |
| Deactivate user | AlertDialog modal | Adequate |
| Approve user | Dialog modal | Adequate |
| Reject user | AlertDialog modal | Adequate |
| Revoke API key | AlertDialog modal (shows key name) | Adequate |
| Revoke share token | AlertDialog modal (shows map name) | Adequate |
| Bulk revoke embed tokens | Checkbox selection + AlertDialog | Good |
| Config overwrite | Destructive warning banner + dry-run required | Good |

API keys shown only once via `ApiKeyRevealDialog` with copy-to-clipboard and warning banner. Keys masked in listings (name + status only). Passwords never displayed anywhere.

## 8. Admin Health Summary

| Metric | Count |
|--------|-------|
| Admin endpoints without correct permission protection | 2 (GET /admin/ai-status/, PATCH /datasets/{id}/status/) |
| Privilege escalation vectors found | 2 (last-admin demotion, non-admin manage_* granting) |
| Admin operations missing audit log entries | 10 (all user CRUD, all API key CRUD) |
| Dangerous settings without validation guards | 3 (token expiry, embedding_dims, tile_cache_ttl) |
| Destructive UI operations without confirmation dialogs | 0 |
| API key security posture | Hashed (SHA-256), scoped, revocable. No expiry, no audit trail |
| Config import safety posture | Validated, dry-run available, secrets redacted, ENV_ONLY lockdown |
| **Total estimated hours to resolve all P0 + P1 items** | **~10-14 hours** |

## 9. Prioritized Action Items

| # | Priority | Action | Dimension | Effort | Risk if Unfixed |
|---|----------|--------|-----------|--------|-----------------|
| 1 | **P0** | Add last-admin guard to `AdminService.update_user()` before role changes. Check if target user is the sole admin when role is being changed away from admin. File: `backend/app/admin/service.py:131-143` | User Lifecycle | 1h | System lockout — no admin can manage users/settings |
| 2 | **P0** | Add `require_permission("edit_metadata")` to `PATCH /datasets/{dataset_id}/status/`. File: `backend/app/datasets/router_data.py` | Authorization | 0.5h | Any authenticated user can change dataset visibility (data exposure) |
| 3 | **P0** | Enhance `validate_permission_matrix()` to prevent granting manage_users/manage_settings to non-admin roles. File: `backend/app/auth/permissions.py:81-102` | Permission Matrix | 1h | Privilege escalation via custom permission matrix |
| 4 | **P1** | Add audit logging to all user CRUD operations: create, update, deactivate, approve, reject, delete. Include username, role changes, IP address. File: `backend/app/admin/router.py` | Audit Log | 3h | User management actions invisible to compliance review |
| 5 | **P1** | Add audit logging to all API key operations: admin create/revoke and self-service create/revoke. File: `backend/app/admin/router.py`, `backend/app/auth/router.py` | Audit Log | 2h | API key lifecycle invisible to security review |
| 6 | **P1** | Inject `current_user` into PATCH /admin/users/{user_id} endpoint and add self-modification guard. File: `backend/app/admin/router.py:142-167` | User Lifecycle | 1h | Admin can demote themselves, bypassing self-protection |
| 7 | **P1** | Add bounds validators for token expiry settings: `access_token_expire_minutes` (1-1440), `refresh_token_expire_days` (1-365). File: `backend/app/settings/schemas.py` SETTING_VALIDATORS | Settings | 1h | Setting to 0/negative creates immediate-expiry or broken tokens |
| 8 | **P1** | Add bounds validator for `embedding_dims` (1-4096). File: `backend/app/settings/schemas.py` SETTING_VALIDATORS | Settings | 0.5h | Setting to 0 causes PostgreSQL ALTER TABLE failure |
| 9 | **P2** | Add `require_permission("manage_users")` to GET /admin/ai-status/ for consistency with PATCH. File: `backend/app/admin/router.py:464-482` | Authorization | 0.5h | Minor info disclosure (AI config visible to all authenticated users) |
| 10 | **P2** | Add bounds validator for `tile_cache_ttl` (0-86400). File: `backend/app/settings/schemas.py` SETTING_VALIDATORS | Settings | 0.5h | Setting to negative causes unpredictable cache behavior |
| 11 | **P2** | Capture IP address in config import, share token revoke, and embed token revoke audit entries. Files: `backend/app/config_ops/service.py`, `backend/app/admin/router.py` | Audit Log | 1h | Partial IP coverage in audit trail |
| 12 | **P2** | Add password change endpoint for user self-service. File: new endpoint in `backend/app/auth/router.py` | User Lifecycle | 2h | Users cannot change their own password |
| 13 | **P2** | Consolidate dual status tracking (is_active + status) or document the distinction clearly. File: `backend/app/admin/service.py` | User Lifecycle | 2h | Semantic confusion: deactivated users have status="active" + is_active=False |

## 10. Comparison to Prior Audit

No previous admin-audit found in `docs/audits/`. This is the baseline admin audit.

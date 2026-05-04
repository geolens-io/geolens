# /admin-audit — Admin Control Plane & Governance Audit

Audit the GeoLens admin control plane for authorization integrity, permission matrix correctness, user management safety, API key hygiene, audit log completeness, settings governance, and config import security. GeoLens uses a capability-based access control (CBAC) system with 3 roles (admin/editor/viewer), 8 granular permissions, a customizable permission matrix stored in the database, and v13.5 governance seams (`PermissionExtension`, `WorkflowExtension`) for enterprise policy overlays — this audit verifies that governance is correctly enforced end-to-end, not just that endpoints exist.

**Usage:** `/admin-audit` (full audit) or `/admin-audit <area>` where area is `authz`, `users`, `api-keys`, `settings`, `audit-logs`, or `config-ops`

Arguments: $ARGUMENTS
- Empty → full audit (all 7 subagents)
- `authz` → Subagent 1 only (authorization enforcement)
- `users` → Subagent 3 only (user lifecycle safety)
- `api-keys` → Subagent 4 only (API key security)
- `settings` → Subagent 6 only (settings & config governance)
- `audit-logs` → Subagent 5 only (audit log completeness)
- `config-ops` → Subagent 6 only (settings & config governance, focused on import/export)

If `$ARGUMENTS` matches a scope keyword above, run only the corresponding subagent(s). Still run the full INTAKE — subagents need the context. In the SYNTHESIS, grade only the relevant dimension(s) and note the scoped execution.

---

## INTAKE (Serial — do this first)

### Step 1: Read the CBAC system

```bash
# Permission definitions and matrix
cat backend/app/modules/auth/permissions.py

# Auth dependencies — where require_permission() lives
cat backend/app/modules/auth/dependencies.py

# Auth models (User, Role, etc.)
cat backend/app/modules/auth/models.py

# Auth schemas
cat backend/app/modules/auth/schemas.py
```

### Step 2: Read all admin routers

```bash
# Admin router (user management, API keys, stats, jobs)
cat backend/app/modules/admin/router.py

# Settings router
cat backend/app/modules/settings/router.py

# Audit log router
cat backend/app/modules/audit/router.py

# Config operations router
cat backend/app/platform/config_ops/router.py

# Embed tokens admin router (admin-scoped, uses manage_users)
cat backend/app/modules/embed_tokens/admin_router.py 2>/dev/null

# Share / embed token management and edition gates
cat backend/app/modules/catalog/maps/schemas.py 2>/dev/null
cat backend/app/modules/catalog/maps/service.py 2>/dev/null
cat backend/app/modules/embed_tokens/schemas.py 2>/dev/null
cat backend/app/modules/embed_tokens/service.py 2>/dev/null
```

### Step 3: Read extension governance seams

```bash
cat backend/app/platform/extensions/protocols.py
cat backend/app/platform/extensions/defaults.py
cat backend/app/platform/extensions/__init__.py
```

### Step 4: Map the admin UI

```bash
# Admin pages
find frontend/src/pages/admin -name "*.tsx" 2>/dev/null | sort

# Admin components
find frontend/src/components/admin -name "*.tsx" 2>/dev/null | sort

# Admin API hooks and client calls
grep -rn "admin\|settings\|audit" frontend/src/api/ --include="*.ts" 2>/dev/null | head -30
grep -rn "admin\|settings\|audit" frontend/src/hooks/ --include="*.ts" 2>/dev/null | head -30
```

### Step 5: Read the persistent config system

```bash
cat backend/app/core/persistent_config.py 2>/dev/null
cat backend/app/modules/settings/service.py 2>/dev/null
cat backend/app/modules/settings/schemas.py 2>/dev/null
```

### Step 6: Read the audit logging system

```bash
cat backend/app/modules/audit/models.py 2>/dev/null
cat backend/app/modules/audit/service.py 2>/dev/null
cat backend/app/modules/audit/schemas.py 2>/dev/null
```

---

## CBAC REFERENCE (Embedded)

These are the expected permission semantics. Deviations are findings.

### Permission matrix (default)

| Capability | Admin | Editor | Viewer | Lockable |
|-----------|-------|--------|--------|----------|
| UPLOAD | yes | yes | no | no |
| CREATE_LAYERS | yes | yes | no | no |
| EXPORT | yes | yes | yes | no |
| EDIT_METADATA | yes | yes | no | no |
| MANAGE_COLLECTIONS | yes | yes | no | no |
| USE_AI_CHAT | yes | yes | no | no |
| MANAGE_USERS | yes | no | no | **yes** — admin-locked (see note) |
| MANAGE_SETTINGS | yes | no | no | **yes** — admin-locked (see note) |

**Locked permission note:** The current `validate_permission_matrix()` in `permissions.py` only enforces **lockout prevention** — it prevents removing `manage_users`/`manage_settings` from the admin role. It does NOT currently prevent granting these capabilities to non-admin roles (editor/viewer). If the subagent finds that a custom matrix grants `manage_users` or `manage_settings` to a non-admin role, flag this as a privilege escalation finding. If the validation function itself doesn't block this, flag the missing guard as a P1 action item.

### Protection invariants

- Every admin endpoint MUST use `require_permission("manage_users")` or `require_permission("manage_settings")`
- Permission checks MUST flow through the v13.5 `PermissionExtension` seam (`get_permission_extension()`), while Community still preserves the default role matrix semantics
- Catalog visibility and dataset access checks MUST also use `PermissionExtension`; direct role-name shortcuts are findings unless they are purely UI hints backed by server checks
- Dataset publication workflow transitions MUST flow through the v13.5 `WorkflowExtension` seam (`get_workflow_extension()`); Enterprise approval workflow code must not be hardcoded in Community routes/services
- The permission matrix is customizable BUT locked capabilities SHOULD NOT be grantable to non-admin roles (verify enforcement — known weak spot)
- Last-admin protection: the system must prevent deletion/deactivation of the last admin user
- Self-deletion prevention: a user must not be able to delete their own account via the admin API
- API keys must be hashed (SHA-256) and never returned in plaintext after creation
- Audit log entries must be immutable — no delete or update endpoints
- Config import must validate before applying — dry-run mode should be available
- Settings changes must be audit-logged with before/after values
- Advanced sharing gates MUST be enforced in both schemas and services: Community allows basic share link create/revoke, public/internal/private visibility, and default unrestricted embed tokens, but rejects custom share expiration, custom embed lifetimes, and non-empty embed domain restrictions unless the Enterprise overlay is active

---

## SUBAGENT DISPATCH (Parallel)

Run these 7 subagents in parallel.

### Subagent 1: Authorization Enforcement

**Goal:** Verify every admin endpoint is protected by the correct `require_permission()` dependency and that no admin functionality is accessible without proper authorization.

**Process:**

1. **Enumerate all admin endpoints and their protection:**
   ```bash
   # Every endpoint in admin-relevant routers with its dependencies
   grep -n "@router\.\|Depends\|require_permission\|require_role\|current_user" backend/app/modules/admin/router.py
   grep -n "@router\.\|Depends\|require_permission\|require_role\|current_user" backend/app/modules/settings/router.py
   grep -n "@router\.\|Depends\|require_permission\|require_role\|current_user" backend/app/modules/audit/router.py
   grep -n "@router\.\|Depends\|require_permission\|require_role\|current_user" backend/app/platform/config_ops/router.py
   grep -n "@router\.\|Depends\|require_permission\|require_role\|current_user" backend/app/modules/embed_tokens/admin_router.py 2>/dev/null
   ```

2. **Find unprotected admin endpoints:**
   ```bash
   # Endpoints in admin routers without require_permission or require_role
   for f in backend/app/modules/admin/router.py backend/app/modules/settings/router.py backend/app/modules/audit/router.py backend/app/platform/config_ops/router.py backend/app/modules/embed_tokens/admin_router.py; do
     echo "=== $f ==="
     # Find route decorators and check if the function has a permission dependency
     grep -n "async def " "$f" | while read line; do
       lineno=$(echo "$line" | cut -d: -f1)
       funcname=$(echo "$line" | grep -oP "async def \K\w+")
       # Look back 5 lines for route decorator
       has_route=$(sed -n "$((lineno-5)),$((lineno))p" "$f" | grep -c "@router\.")
       # Look forward 5 lines for permission dependency
       has_perm=$(sed -n "$((lineno)),$((lineno+5))p" "$f" | grep -c "require_permission\|require_role\|get_current_admin")
       if [ "$has_route" -gt 0 ] && [ "$has_perm" -eq 0 ]; then
         echo "UNPROTECTED: $funcname (line $lineno)"
       fi
     done
   done
   ```

3. **Verify permission consistency:**
   ```bash
   # Map each admin endpoint to its required permission
   grep -B 5 "require_permission" backend/app/modules/admin/router.py | grep -E "@router\.|require_permission"
   grep -B 5 "require_permission" backend/app/modules/settings/router.py | grep -E "@router\.|require_permission"
   grep -B 5 "require_permission" backend/app/modules/audit/router.py | grep -E "@router\.|require_permission"
   grep -B 5 "require_permission" backend/app/platform/config_ops/router.py | grep -E "@router\.|require_permission"
   grep -B 5 "require_permission" backend/app/modules/embed_tokens/admin_router.py 2>/dev/null | grep -E "@router\.|require_permission"
   ```

   Verify:
   - User management endpoints use `manage_users`
   - Settings/config endpoints use `manage_settings`
   - No endpoint uses a weaker permission than expected

4. **Check for authorization bypass paths:**
   ```bash
   # Direct DB session access without permission checks
   grep -rn "get_db\|AsyncSession" backend/app/modules/admin/ backend/app/modules/settings/ backend/app/platform/config_ops/ --include="*.py" | grep -v "require_permission\|Depends"

   # Service functions callable without going through the router
   grep -rn "^async def \|^def " backend/app/modules/admin/service.py backend/app/modules/settings/service.py 2>/dev/null | grep -v "^.*def _"
   ```

5. **Verify the require_permission() implementation:**
   ```bash
   cat backend/app/modules/auth/dependencies.py
   ```

   Check:
   - Does it check the effective permission matrix (not just role name)?
   - Does it delegate the final decision to `get_permission_extension().check_permission(...)` so enterprise RBAC/ABAC overlays can participate?
   - Does it handle missing/expired tokens correctly (401 not 500)?
   - Does it log permission denials?
   - Can the permission check be bypassed by manipulating request headers?

6. **Verify v13.5 governance seam usage:**
   ```bash
   grep -rn "get_permission_extension\|get_workflow_extension\|PermissionExtension\|WorkflowExtension" backend/app/ --include="*.py" | grep -v __pycache__
   grep -rn "record_status\|publish\|approval\|workflow" backend/app/modules/catalog/ --include="*.py" | grep -v __pycache__
   ```

   Check:
   - `require_permission()` delegates to `PermissionExtension`, not a hardcoded role-only path
   - Catalog visibility/dataset access paths call `PermissionExtension.filter_visible()` / `can_access_dataset()`
   - Dataset status transitions call `WorkflowExtension.allowed_transitions()` and `on_transition()`
   - Enterprise approval workflow concepts do not appear in Community code except behind the seam

**Output:** Endpoint protection map — Endpoint | Method | Required permission | Actual protection | Status (Protected/Unprotected/Mismatched).

---

### Subagent 2: Permission Matrix Integrity

**Goal:** Verify the CBAC permission matrix is correctly implemented, that locked permissions cannot be escalated, and that customization doesn't break invariants.

**Process:**

1. **Read the permission matrix implementation:**
   ```bash
   cat backend/app/modules/auth/permissions.py
   ```

   Verify:
   - All 8 permissions are defined
   - Default matrix matches the reference table above
   - Locked permissions (`manage_users`, `manage_settings`) have explicit lock enforcement

2. **Check matrix customization safety:**
   ```bash
   # How is the matrix modified?
   grep -rn "permission_matrix\|update_matrix\|set_permission\|capability\|grant" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test

   # Where is the matrix stored and loaded?
   grep -rn "permission\|capability\|matrix" backend/app/core/persistent_config.py backend/app/modules/settings/service.py 2>/dev/null
   ```

   Check:
   - Can a custom matrix grant `manage_users` to viewers? (Must not be possible)
   - Can a custom matrix revoke `manage_users` from all admins? (Must not — lockout prevention)
   - Is the matrix validated on write, or only on read?
   - Does `DefaultPermissionExtension` preserve matrix behavior while still allowing Enterprise overlays to add resource-aware policy?

3. **Check for privilege escalation paths:**
   ```bash
   # Can an editor change their own role?
   grep -rn "role\|update.*user\|patch.*user" backend/app/modules/admin/router.py | grep -v __pycache__

   # Can a user with manage_users grant themselves manage_settings?
   grep -rn "update_permission\|set_role\|change_role\|promote\|assign_role" backend/app/ --include="*.py" | grep -v __pycache__
   ```

   Escalation vectors to check:
   - Editor calls user update endpoint to promote themselves to admin
   - Admin with `manage_users` but not `manage_settings` modifies the permission matrix
   - API key inherits higher permissions than the creating user

4. **Verify API key permission inheritance:**
   ```bash
   # How are API key permissions determined?
   grep -rn "api_key\|ApiKey\|resolve.*permission\|key.*permission\|key.*role" backend/app/modules/auth/ --include="*.py"
   ```

   Check:
   - API keys should inherit the creating user's role/permissions at creation time
   - If the creating user is later downgraded, do existing API keys retain elevated permissions? (They should not)

5. **Check anonymous access boundaries:**
   ```bash
   # What can anonymous users access?
   grep -rn "anonymous\|public\|no_auth\|optional_auth\|allow_anonymous" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test
   ```

   Verify that anonymous access is limited to: public datasets, public share links, health check, and public settings.

**Output:** Matrix integrity assessment — Invariant | Status (Enforced/Weak/Broken) | Evidence | Risk.

---

### Subagent 3: User Lifecycle Safety

**Goal:** Verify the user management system handles all lifecycle states correctly and prevents dangerous operations.

**Process:**

1. **Read the user management endpoints:**
   ```bash
   cat backend/app/modules/admin/router.py
   cat backend/app/modules/admin/service.py 2>/dev/null
   ```

2. **Last-admin protection:**
   ```bash
   # Find the last-admin check
   grep -rn "last.*admin\|admin.*count\|sole.*admin\|only.*admin" backend/app/ --include="*.py" | grep -v __pycache__
   ```

   Test scenarios that MUST be protected:
   - Delete the last admin user → must be blocked
   - Deactivate the last admin user → must be blocked
   - Demote the last admin to editor → must be blocked
   - Suspend the last admin → must be blocked

3. **Self-operation prevention:**
   ```bash
   # Can a user delete/deactivate themselves?
   grep -rn "self.*delete\|current_user.*delete\|own.*account\|self.*deactivate" backend/app/ --include="*.py" | grep -v __pycache__
   ```

   Check:
   - Self-deletion via admin API → must be blocked
   - Self-role-change → should be blocked or require confirmation
   - Self-deactivation → must be blocked

4. **User status transitions:**
   ```bash
   # User status enum/field
   grep -rn "status\|UserStatus\|is_active\|is_suspended\|pending\|approved\|rejected\|deactivated" backend/app/modules/auth/models.py backend/app/modules/auth/schemas.py backend/app/modules/admin/ --include="*.py" | grep -v __pycache__
   ```

   Verify:
   - Valid transitions: pending → active, pending → rejected, active → suspended, active → deactivated
   - Invalid transitions are blocked (e.g., rejected → active without admin approval)
   - Suspended/deactivated users cannot authenticate

5. **Registration and approval flow:**
   ```bash
   grep -rn "register\|signup\|approve\|reject\|pending" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | grep -v alembic
   ```

   Check:
   - Is registration open or admin-controlled?
   - If admin-controlled, is the approval flow complete (pending → approve/reject)?
   - Can a pending user access any resources?

6. **Password and credential handling:**
   ```bash
   # Password hashing
   grep -rn "hash\|bcrypt\|argon\|passlib\|password" backend/app/modules/auth/ --include="*.py" | grep -v __pycache__

   # Password update flow
   grep -rn "change_password\|reset_password\|update_password\|set_password" backend/app/ --include="*.py" | grep -v __pycache__
   ```

   Check:
   - Passwords are hashed (bcrypt/argon2, not MD5/SHA)
   - Password changes require old password or admin override
   - Password is never returned in API responses

**Output:** User lifecycle safety — Operation | Protection | Status (Safe/Weak/Missing) | Evidence.

---

### Subagent 4: API Key Security

**Goal:** Verify API key creation, storage, usage, and revocation are secure.

**Process:**

1. **Read API key implementation:**
   ```bash
   # API key model
   grep -rn "class.*ApiKey\|class.*APIKey\|api_key" backend/app/modules/auth/models.py | head -20
   cat backend/app/modules/admin/router.py | grep -A 30 "api.key\|api_key"

   # API key resolution
   grep -rn "_resolve_api_key\|verify_api_key\|check_api_key" backend/app/modules/auth/dependencies.py
   ```

2. **Key storage security:**
   ```bash
   # How keys are stored
   grep -rn "sha256\|hash.*key\|key.*hash\|bcrypt.*key\|store.*key" backend/app/ --include="*.py" | grep -v __pycache__
   ```

   Verify:
   - Keys are hashed (SHA-256 minimum) before storage
   - Raw key is returned only at creation time, never after
   - Key prefix or last-4 chars stored separately for identification

3. **Key lifecycle:**
   ```bash
   # Key creation, revocation, expiry
   grep -rn "create.*key\|revoke.*key\|delete.*key\|expire.*key\|expires_at\|valid_until" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test
   ```

   Check:
   - Keys can be revoked immediately
   - Revoked keys fail authentication on next use
   - Is there key expiry? (Missing = informational finding, not critical)
   - Is there key rotation support?

4. **Key permission scope:**
   ```bash
   # What permissions does an API key grant?
   grep -rn "api_key.*role\|api_key.*permission\|key.*scope\|key.*capability" backend/app/ --include="*.py" | grep -v __pycache__
   ```

   Check:
   - API key permissions are scoped (not full admin access by default)
   - Key permissions cannot exceed the creating user's permissions

5. **Key transmission security:**
   ```bash
   # How is the key sent in requests?
   grep -rn "X-API-Key\|Authorization\|api_key\|apikey" backend/app/modules/auth/dependencies.py

   # Is the key accepted via query parameter? (Less secure — logged in URLs)
   grep -rn "query.*api_key\|api_key.*Query\|request.query" backend/app/modules/auth/dependencies.py
   ```

   If keys are accepted via query parameter, flag as informational (may be logged in access logs, browser history).

6. **Key audit trail:**
   ```bash
   # Are key operations logged?
   grep -rn "audit\|log.*key\|key.*created\|key.*revoked" backend/app/modules/admin/router.py backend/app/modules/admin/service.py 2>/dev/null
   ```

**Output:** API key security — Aspect | Status (Secure/Weak/Missing) | Evidence | Recommendation.

---

### Subagent 5: Audit Log Completeness

**Goal:** Verify that all admin-sensitive operations are audit-logged, that logs are immutable, and that the logging system captures sufficient context for compliance.

**Process:**

1. **Read the audit log system:**
   ```bash
   cat backend/app/modules/audit/models.py
   cat backend/app/modules/audit/service.py 2>/dev/null || find backend/app/modules/audit -name "*.py" | while read f; do echo "=== $f ==="; cat "$f"; done
   ```

2. **Map all audit-logged operations:**
   ```bash
   # Every place audit logging is called
   grep -rn "audit_log\|create_audit\|log_audit\|AuditLog\|log_action\|record_audit\|emit_audit" backend/app/ --include="*.py" | grep -v __pycache__ | grep -v test | grep -v models.py | grep -v schemas.py
   ```

   Build an inventory of what IS logged.

3. **Map all admin operations that SHOULD be logged:**
   ```bash
   # User CRUD
   grep -n "@router\." backend/app/modules/admin/router.py | grep -E "post|put|patch|delete"

   # Settings changes
   grep -n "@router\." backend/app/modules/settings/router.py | grep -E "post|put|patch|delete"

   # Config import/export
   grep -n "@router\." backend/app/platform/config_ops/router.py | grep -E "post|put|patch|delete"

   # Dataset deletion (admin-sensitive)
   grep -rn "delete.*dataset\|bulk.*delete\|remove.*dataset" backend/app/modules/catalog/datasets/router.py 2>/dev/null | head -10

   # Permission/role changes
   grep -rn "role\|permission\|grant\|revoke" backend/app/modules/admin/router.py | head -20
   ```

   Cross-reference: every mutating admin operation should have a corresponding audit log entry.

4. **Audit log immutability:**
   ```bash
   # Check for delete/update endpoints on audit logs
   grep -n "@router\.\(delete\|put\|patch\)" backend/app/modules/audit/router.py 2>/dev/null

   # Check for DELETE operations on audit table in service layer
   grep -rn "delete\|update\|truncate" backend/app/modules/audit/service.py backend/app/modules/audit/router.py 2>/dev/null | grep -v "# \|query\|filter\|select"
   ```

   Audit logs MUST be append-only. Any delete/update capability is a critical finding.

5. **Audit log content quality:**
   ```bash
   # What fields are captured per entry?
   grep -rn "class AuditLog\|Column\|Field" backend/app/modules/audit/models.py
   ```

   Required fields: timestamp, user_id, action, resource_type, resource_id, IP address, details (before/after for changes).
   Missing any of these = finding.

6. **Audit log query and export:**
   ```bash
   # Query capabilities
   grep -n "async def " backend/app/modules/audit/router.py | head -10

   # Export formats
   grep -rn "csv\|json\|export\|download\|stream" backend/app/modules/audit/ --include="*.py" | grep -v __pycache__
   ```

   Check:
   - Logs are queryable by date range, user, action type, resource
   - Export supports CSV and JSON
   - Large exports use streaming (not load-all-into-memory)

**Output:** Audit log completeness — Admin Operation | Logged? | Context captured | Gap.

---

### Subagent 6: Settings & Config Governance

**Goal:** Verify that settings management is safe, validated, and doesn't allow dangerous configurations that could break the system or create security holes.

**Process:**

1. **Read the settings system:**
   ```bash
   cat backend/app/modules/settings/router.py
   cat backend/app/modules/settings/service.py 2>/dev/null
   cat backend/app/modules/settings/schemas.py 2>/dev/null
   cat backend/app/core/persistent_config.py 2>/dev/null
   ```

2. **Settings validation:**
   ```bash
   # Pydantic validation on settings writes
   grep -rn "validator\|field_validator\|model_validator\|Annotated\|constr\|conint\|confloat\|Literal\|Enum" backend/app/modules/settings/schemas.py 2>/dev/null

   # Settings value bounds
   grep -rn "min_\|max_\|ge=\|le=\|gt=\|lt=\|regex\|pattern" backend/app/modules/settings/schemas.py 2>/dev/null
   ```

   Check:
   - Are all settings validated on write?
   - Are there range constraints on numeric settings?
   - Can an admin set a setting to an invalid value that crashes the system?

3. **Dangerous settings:**
   ```bash
   # Settings that affect security posture
   grep -rn "cors\|origin\|allow\|debug\|secret\|key\|token\|password\|auth\|registration\|public\|visibility" backend/app/modules/settings/ backend/app/core/persistent_config.py --include="*.py" 2>/dev/null | grep -v __pycache__
   ```

   Flag settings that could:
   - Open CORS to `*` in production
   - Enable debug mode
   - Disable authentication
   - Make all datasets public
   - Disable audit logging
   - Change the admin password hash algorithm

4. **Config import safety:**
   ```bash
   cat backend/app/platform/config_ops/router.py
   cat backend/app/platform/config_ops/service.py 2>/dev/null || find backend/app/platform/config_ops -name "*.py" | while read f; do echo "=== $f ==="; cat "$f"; done
   ```

   Check:
   - Import validates schema before applying
   - Dry-run mode is available and functional
   - Import cannot inject new admin users or API keys
   - Import cannot change the permission matrix to grant unauthorized access
   - Import cannot bypass `PermissionExtension`, `WorkflowExtension`, or advanced-sharing Community/Enterprise gates by writing lower-level config directly
   - Overwrite mode has additional confirmation requirements

5. **Settings rollback:**
   ```bash
   # Can settings be reverted to defaults?
   grep -rn "default\|reset\|rollback\|revert" backend/app/modules/settings/ backend/app/platform/config_ops/ --include="*.py" 2>/dev/null | grep -v __pycache__
   ```

   Check if there is a mechanism to revert settings to safe defaults if a misconfiguration breaks the system.

6. **Settings exposure in frontend:**
   ```bash
   # Public settings endpoint (no auth required)
   grep -rn "public.*settings\|settings.*public\|unauthenticated\|no.*auth" backend/app/modules/settings/router.py 2>/dev/null

   # What settings are exposed without authentication?
   grep -rn "PublicSettings\|public_settings\|settings_response" backend/app/modules/settings/ --include="*.py" 2>/dev/null
   ```

   Verify that public settings don't leak: internal URLs, secret keys, database credentials, or admin configuration details.

7. **Advanced sharing governance:**
   ```bash
   grep -rn "ADVANCED_SHARING_ERROR\|expires_at\|expires_in_days\|allowed_origins\|is_enterprise" backend/app/modules/catalog/maps/ backend/app/modules/embed_tokens/ --include="*.py"
   grep -rn "advanced-sharing\|useEdition\|isEnterprise\|allowedOrigins\|expiresAt" frontend/src/pages/admin frontend/src/components/admin frontend/src/components/builder --include="*.tsx" --include="*.ts" 2>/dev/null
   ```

   Check:
   - Community basic share create/revoke still works without Enterprise
   - Community rejects custom share expiration and non-default embed token lifetimes at schema and service layers
   - Community rejects non-empty embed `allowed_origins` / domain restrictions at schema and service layers
   - Admin shared-map views do not expose Enterprise-only quota/domain/lifetime controls unless the Enterprise overlay is active
   - Enterprise can enable the advanced controls without modifying Community source

**Output:** Settings governance — Setting/Operation | Validated? | Dangerous? | Audit-logged? | Status.

---

### Subagent 7: Admin UI Consistency

**Goal:** Verify the admin frontend correctly enforces permissions, handles errors gracefully, and doesn't expose admin functionality to unauthorized users.

**Process:**

1. **Admin route protection in frontend:**
   ```bash
   # Admin route guards
   grep -rn "admin\|role\|permission\|protect\|guard\|redirect\|unauthorized" frontend/src/pages/admin/ --include="*.tsx" | head -30

   # Router configuration — how admin routes are gated
   grep -rn "admin\|AdminLayout\|ProtectedRoute\|RequireAuth\|RequireRole" frontend/src/ --include="*.tsx" | grep -v node_modules | head -30
   ```

   Verify:
   - Admin pages are wrapped in a route guard
   - Non-admin users are redirected, not shown an error
   - Admin navigation is hidden for non-admin users

2. **Permission-based UI rendering:**
   ```bash
   # Does the UI check permissions before showing admin controls?
   grep -rn "permission\|canManage\|isAdmin\|role.*admin\|has_permission\|usePermission" frontend/src/ --include="*.tsx" --include="*.ts" | grep -v node_modules | head -30
   ```

   Check:
   - Admin-only buttons/links are conditionally rendered based on permissions
   - Delete/dangerous actions have confirmation dialogs
   - Bulk operations require explicit confirmation

3. **Error handling in admin operations:**
   ```bash
   # Error handling in admin API calls
   grep -rn "onError\|catch\|error\|403\|401\|isError" frontend/src/pages/admin/ --include="*.tsx" | head -30
   grep -rn "onError\|catch\|error\|403\|401\|isError" frontend/src/components/admin/ --include="*.tsx" | head -30
   ```

   Check:
   - 403 responses show a clear "insufficient permissions" message
   - 401 responses redirect to login
   - Failed admin operations don't leave the UI in an inconsistent state
   - Optimistic updates are rolled back on failure

4. **Sensitive data display:**
   ```bash
   # API key display
   grep -rn "api.key\|apiKey\|API_KEY\|secret\|token\|password" frontend/src/pages/admin/ frontend/src/components/admin/ --include="*.tsx" | head -20
   ```

   Check:
   - API keys are masked after creation (show only prefix or last 4 chars)
   - Passwords are never displayed
   - Copy-to-clipboard for secrets works without exposing in DOM

5. **Admin sidebar navigation accuracy:**
   ```bash
   cat frontend/src/components/admin/AdminSidebar.tsx 2>/dev/null || find frontend/src/components/admin -name "*[Ss]idebar*" -o -name "*[Nn]av*" | while read f; do echo "=== $f ==="; cat "$f"; done
   ```

   Check:
   - Sidebar links match available admin pages
   - Active page highlighting works correctly
   - No dead links or routes to non-existent pages

6. **Confirmation patterns for destructive actions:**
   ```bash
   # Delete confirmations
   grep -rn "confirm\|dialog\|modal\|AlertDialog\|destructive\|danger" frontend/src/pages/admin/ frontend/src/components/admin/ --include="*.tsx" | head -20

   # Title-confirmation pattern (type name to confirm)
   grep -rn "type.*confirm\|confirm.*name\|confirm.*title\|match.*name" frontend/src/pages/admin/ frontend/src/components/admin/ --include="*.tsx" | head -10
   ```

   Destructive admin operations (delete user, overwrite config, bulk operations) MUST have confirmation dialogs. Highest-impact operations (delete all, config overwrite) should use type-to-confirm.

**Output:** Admin UI assessment — Aspect | Status (Correct/Weak/Missing) | Evidence | Impact.

---

## SYNTHESIS (Serial — after all subagents complete)

### Scoring

| Dimension | What it measures |
|-----------|-----------------|
| **Authorization Enforcement** | Every admin endpoint is protected by correct permissions |
| **Permission Matrix Integrity** | CBAC system is sound, escalation-proof, lockout-proof |
| **User Lifecycle Safety** | User management handles all edge cases (last-admin, self-ops, status transitions) |
| **API Key Security** | Keys are hashed, scoped, revocable, and audit-trailed |
| **Audit Log Completeness** | All admin operations are logged with sufficient context |
| **Settings Governance** | Settings are validated, dangerous configs are guarded, imports are safe |
| **Admin UI Consistency** | Frontend enforces permissions, handles errors, confirms destructive ops |

Grade each A-F using:
- **A** — No issues. Admin control plane is production-ready.
- **B** — Minor issues. Missing non-critical audit entries, cosmetic UI gaps. No security risk.
- **C** — Significant issues. Missing permission checks on low-impact endpoints, incomplete audit coverage. Deployable but undertrusted.
- **D** — Dangerous issues. Permission bypass paths, escalation vectors, missing protections on destructive operations.
- **F** — Broken. Admin endpoints unprotected, permission matrix bypassable, critical operations unlogged.

**Overall admin health** = minimum grade (the weakest dimension determines admin readiness).

### Action Items

| Field | Description |
|-------|-------------|
| Priority | P0 (privilege escalation or auth bypass), P1 (missing protection on destructive operation or audit gap), P2 (UI inconsistency or missing validation) |
| Action | Specific fix — include file, function, current and expected behavior |
| Dimension | Which audit dimension |
| Effort | Hours estimate |
| Risk if unfixed | What an attacker or misconfigured admin could exploit |

Sort by priority, then effort.

### Admin Health Summary

Summarize total admin control plane debt:
- Number of admin endpoints without correct permission protection
- Number of privilege escalation vectors found
- Number of admin operations missing audit log entries
- Number of dangerous settings without validation guards
- Number of destructive UI operations without confirmation dialogs
- API key security posture (hashed? scoped? expiring? rotatable?)
- Config import safety posture (validated? dry-run? scoped?)
- Total estimated hours to resolve all P0 + P1 items

---

## DELIVERY

### Output format

Write the report to: `docs-internal/audits/admin-audit-{YYYYMMDD}.md`

### Report structure

```markdown
# Admin Audit — {YYYY-MM-DD}

## Scorecard
<!-- Letter grades + overall health -->

## Executive Summary
<!-- 3-5 sentences: admin control plane state, biggest risks, top fix -->

## 1. Authorization Enforcement
### 1a. Endpoint Protection Map
### 1b. Permission Consistency
### 1c. Bypass Paths
<!-- Subagent 1 findings -->

## 2. Permission Matrix Integrity
### 2a. Matrix Implementation
### 2b. Customization Safety
### 2c. Escalation Analysis
### 2d. API Key Inheritance
<!-- Subagent 2 findings -->

## 3. User Lifecycle Safety
### 3a. Last-Admin Protection
### 3b. Self-Operation Prevention
### 3c. Status Transitions
### 3d. Registration & Approval
### 3e. Credential Handling
<!-- Subagent 3 findings -->

## 4. API Key Security
### 4a. Storage Security
### 4b. Key Lifecycle
### 4c. Permission Scope
### 4d. Transmission Security
### 4e. Audit Trail
<!-- Subagent 4 findings -->

## 5. Audit Log Completeness
### 5a. Coverage Map
### 5b. Immutability
### 5c. Content Quality
### 5d. Query & Export
<!-- Subagent 5 findings -->

## 6. Settings & Config Governance
### 6a. Validation
### 6b. Dangerous Settings
### 6c. Import Safety
### 6d. Public Exposure
<!-- Subagent 6 findings -->

## 7. Admin UI Consistency
### 7a. Route Protection
### 7b. Permission-Based Rendering
### 7c. Error Handling
### 7d. Destructive Action Confirmation
<!-- Subagent 7 findings -->

## 8. Admin Health Summary
<!-- Aggregate metrics -->

## 9. Prioritized Action Items
<!-- Action items table -->

## 10. Comparison to Prior Audit
<!-- If a previous admin-audit exists, diff findings -->
```

### Post-delivery

1. If `lessons.md` exists, append reusable insights about admin control plane patterns for CBAC systems.
2. Print one-line summary: overall grade + P0 count + total admin debt hours.

---

## RELATIONSHIP TO OTHER COMMANDS

- `/sec-audit` — covers general application security (OWASP Top 10, injection, XSS, etc.). This command focuses specifically on the admin control plane: authorization, permissions, governance.
- `/test-audit` — covers test suite health. This command verifies whether admin features *behave correctly*, not whether they have tests.
- `/oc-audit` — covers open-core community/enterprise separation. This command audits admin features that exist today, regardless of tier.
- `/env-audit` — covers environment variable configuration. This command covers admin-configurable settings stored in the database.
- `/db-audit` — covers database health. This command covers the admin operations that modify database state.

---

## WHAT NOT TO FLAG

Avoid false positives on these:

- **Public settings endpoint returning non-sensitive config** — basemap defaults, feature toggles, and branding are intentionally public. Only flag if secrets or internal URLs leak.
- **API keys accepted via query parameter** — this is a documented design decision for OGC API compatibility. Flag as informational, not as a vulnerability. The primary concern (URL logging) is acknowledged.
- **Audit logs growing without retention policy** — immutability is by design. Log rotation is a scaling concern, not a correctness issue. Flag as P2 informational if the table is large.
- **Basic OIDC/OAuth configuration in settings** — community edition includes basic OAuth. Only flag if the settings UI allows configuring SAML (enterprise-tier feature) without the enterprise module.
- **Admin users with both `manage_users` and `manage_settings`** — admin role having all permissions is the default and expected configuration.
- **Missing MFA support** — MFA is not currently in the product scope. Flag as enhancement only if the audit is specifically scoped to enterprise readiness.
- **Settings without per-key audit log entries** — bulk settings updates logged as a single audit entry is acceptable. Only flag if settings changes produce no audit entry at all.
- **API key without expiry** — the current design uses revocation-based lifecycle. Expiry is a nice-to-have, not a security gap. Flag as P2 informational.
- **Self-password-change without old password** — admin-initiated password resets (for other users) don't require the old password by design. Only flag if a user can change their *own* password without providing the current one.

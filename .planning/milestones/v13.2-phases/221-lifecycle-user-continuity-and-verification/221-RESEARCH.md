# Phase 221: lifecycle-user-continuity-and-verification - Research

**Researched:** 2026-04-30
**Domain:** Admin user-conversion endpoint + deactivate→reactivate registry round-trip test + targeted runbook section replacing Phase 220's TODO marker
**Confidence:** HIGH (all major axes locked in CONTEXT.md; remaining open questions are wording-level)

## Summary

Phase 221 closes LIFECYCLE-06 and LIFECYCLE-07 by adding three artifacts on top of Phase 220's foundation:

1. **A new admin endpoint `POST /admin/users/{user_id}/convert-saml-to-local`** (router + service method + Pydantic schema in `backend/app/modules/admin/`) that converts a SAML-authenticated user to local-password in a single transaction, preserving `users.id` (and therefore every FK referencing it), deleting only the `oauth_accounts` linkage row, and writing one `audit_log` entry with `action="auth.convert_saml_to_local"`.
2. **A "Handling existing SAML users" section in `docs/edition-deactivation.md`** that replaces the line-81 TODO blockquote left as a forward-pointer by Phase 220, and a one-paragraph forward-pointer in `docs/edition-reactivation.md`.
3. **Two new test functions in `backend/tests/test_lifecycle.py`** — both `@pytest.mark.lifecycle` — that close LIFECYCLE-06 (conversion preserves user data) and LIFECYCLE-07 (deactivate→reactivate round-trip is lossless across User identities, `oauth_providers` rows, and seeded `audit_log` entries).

No CI workflow change is needed — Phase 220's `geolens-enterprise` overlay install (D-06) and `lifecycle` marker registration (already at `backend/pyproject.toml:74`) are inherited verbatim. Phase 221 ships entirely backend + docs.

The architectural mechanism Phase 221 must respect is exactly the three module-level state surfaces Phase 220 RESEARCH §Pitfall 2 named: `app.platform.extensions._extensions`, `app.platform.extensions._routers`, and `app.core.edition._info`. The round-trip test resets them on the deactivate side, then *re-populates* them on the reactivate side via the same `geolens_enterprise.register_extensions(_extensions)` call the `saml_overlay_registered` fixture uses on setup (`backend/tests/conftest.py:472-478`).

**Primary recommendation:** Implement the conversion endpoint as a dedicated `POST` (not as a UserUpdate field), keep the conversion strictly in-transaction with the audit_log write last, and make the round-trip test use `register_extensions(_extensions)` directly (rather than re-instantiating the SAML extension by hand) so the reactivate path mirrors the production import behavior.

## User Constraints (from CONTEXT.md)

### Locked Decisions

**Re-onboarding mechanism (LIFECYCLE-06):**

- **D-01: Dedicated narrow endpoint** — `POST /admin/users/{user_id}/convert-saml-to-local`. Body schema `SamlToLocalConversion`: `{ "password": "<min 8 chars>" }`. Response: existing `UserResponse`. Service method `AdminService.convert_saml_user_to_local(user_id, password) -> User`. NOT tacked onto the `UserUpdate` PATCH schema.
- **D-02: SC#1 satisfied via runbook + curl example** against the new endpoint. Frontend admin UI button deferred to a polish phase. CLI subcommand also deferred.
- **D-03: Single conversion target — local-password.** OIDC mentioned in runbook as a manual procedure; OIDC tooling deferred.
- **D-04: `oauth_accounts` linkage row DELETED on conversion.** `oauth_providers` SAML row PRESERVED (other users may still link to it post-reactivation). Clean break, not soft-delete.
- **D-05: Single transaction** wrapping all five steps: validate → set password → flip auth_provider → delete oauth_accounts → write audit_log. audit_log write is LAST. Failure surfaces: 404 (user not found), 422 (user not SAML-authenticated, or self-conversion guard).

**Conversion preserves what (LIFECYCLE-06 acceptance):**

- **D-06: `users.id` UUID is the immutable handle.** Conversion never updates `users.id`; every FK referencing it (audit_logs.user_id, user_roles.user_id, datasets.created_by, datasets.updated_by, api_keys.user_id, etc.) is automatically retained.
- **D-07: Conversion does NOT clear** `users.last_login_at`, `user_roles`, `api_keys`, `share_tokens`, or any other user-attributed records. Only the four explicit fields touched in D-01.

**Round-trip test design (LIFECYCLE-07):**

- **D-08: Two new test functions in `backend/tests/test_lifecycle.py`** — `test_convert_saml_user_to_local_preserves_user_data` (LIFECYCLE-06) and `test_deactivate_reactivate_roundtrip_preserves_saml_data` (LIFECYCLE-07). Three test functions total in the file after Phase 221.
- **D-09: Round-trip test simulates reactivation via `register_extensions()` re-invocation.** The same call path the `saml_overlay_registered` fixture uses for setup. Test does NOT touch alembic mid-test (Phase 220 destructive_path_prohibition).
- **D-10: Audit-trail assertion uses a SEEDED `audit_log` row** — not vacuous FK-survival reflection. ~5 lines of seed code; real end-to-end coverage of LIFECYCLE-07's literal text.
- **D-11: Test cleanup extends Phase 220's `_cleanup_lifecycle_rows` pattern.** Cleanup fixture stays test-local (defined inside `test_lifecycle.py`), NOT promoted to conftest.py.

**Documentation structure (LIFECYCLE-06):**

- **D-12: "Handling existing SAML users" section replaces line-81 TODO in `docs/edition-deactivation.md` in-place.** 6-step structure: inventory SAML users → decide conversion targets → run conversion endpoint (curl) → communicate new credentials out-of-band → verify login → appendix: OIDC manual procedure.
- **D-13: One-paragraph forward-pointer in `docs/edition-reactivation.md`** stating that converted users persist as local-password through reactivation; reverse conversion is deferred.

**Audit-log catalog:**

- **D-14: `auth.convert_saml_to_local` is the new audit-log action name.** Pattern matches `user.update`, `user.deactivate`, `user.change_password` (existing). [VERIFIED] no central enum/catalog of action names exists at `app/modules/audit/` — see Code Insights below; the action ships as a string literal at the call site.

### Claude's Discretion

- **Frontend admin UI affordance** — deferred; track shape (modal collecting/auto-generating temp password, gated on `user.auth_provider == 'oauth'` AND admin permission) for the polish phase.
- **`auth_provider` validation pre-conversion** — endpoint must reject non-SAML users. Check pattern: user has at least one `oauth_accounts` row pointing to an `oauth_providers` row with `provider_type='saml'`. If user has multiple `oauth_accounts` rows (multi-IdP, uncommon), delete ONLY the SAML linkage. Planner picks exact SQL.
- **Password complexity** — `min_length=8` matching existing `AdminUserCreate.password` (`backend/app/modules/admin/schemas.py:23-26`). Planner can lift if a stricter project-wide policy exists.
- **Curl example auth token** — runbook references existing admin login flow (`POST /auth/login/`, NOT `/auth/token`; see Pitfall 5 below). Planner picks whether to embed two-step (login then convert) or convert-only with `$TOKEN` placeholder.
- **`_cleanup_lifecycle_rows` extension scope** — planner picks whether each new row type (audit_log, user_roles, datasets) needs explicit DELETE or whether FK CASCADE/SET NULL handles it. The simpler pattern: dependency-order DELETE (audit_log by user_id; user_roles by user_id; datasets by created_by; oauth_accounts; users; oauth_providers stays).
- **Self-conversion guard** — Recommendation: block `current_user.id == user_id` with 422 (admin self-lockout fat-finger). Mirror `admin/router.py:180-184` shape.

### Deferred Ideas (OUT OF SCOPE)

- Frontend admin UI affordance for the conversion endpoint (polish phase).
- OIDC conversion tooling (deferred; manual procedure documented in runbook only).
- Reverse conversion (local → SAML on reactivation) (deferred).
- CLI subcommand `geolens admin user convert-saml-to-local` (deferred).
- Audit-log action-name central enum/catalog (deferred; ship as string literal at call site).
- Conversion History admin UI surface (audit_log already records all conversions; UI surfacing is reporting feature).
- Compose-stack-swap fidelity for round-trip test (Phase 220 deferred idea).
- `is_enterprise()` gating on registry accessors (Phase 220 D-08 deferred).
- Audit-log entry on `init_edition()` transitions (Phase 220 deferred).
- Doc-test for `docs/saml.md` (Phase 220 deferred).
- Tenant scoping (TENANT-01, backlog 999.6).

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| LIFECYCLE-06 | SAML-authenticated users have a documented and tested re-onboarding path; admin can convert account to local-password (or OIDC) without losing audit history, group memberships, or dataset ownership | Endpoint design §Standard Stack + §Architecture Patterns Pattern 1; FK survival §Code Examples; runbook section §Pattern 4; conversion test §Pattern 2 |
| LIFECYCLE-07 | CI re-activation symmetry test confirms `deferred=True` SAML columns round-trip losslessly through deactivate → reactivate cycle (User identities, `oauth_providers` rows, audit trail intact) | Round-trip mechanism §Architecture Patterns Pattern 3; module-level state §Pitfall 1; seed-and-assert pattern §Code Examples; reuse of Phase 220 fixtures §Don't Hand-Roll |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Conversion HTTP surface | API / Backend (`backend/app/modules/admin/router.py`) | — | Admin endpoint; reuses `require_permission("manage_users")` dependency |
| Conversion business logic | API / Backend service (`backend/app/modules/admin/service.py`) | — | `AdminService.convert_saml_user_to_local` mirrors `update_user` shape |
| Password hashing | API / Backend auth provider (`backend/app/modules/auth/providers/local.py`) | — | Black-box reuse of `hash_password()` (already imported in admin/service.py:15) |
| Audit-log write | API / Backend audit module (`backend/app/modules/audit/service.py`) | — | `log_action()` reused; transaction inherited from caller (no commit inside) |
| User row mutation (`auth_provider`, `password_hash`) | Database / Storage (`catalog.users`) | ORM (`backend/app/modules/auth/models.py:18-55`) | `chk_users_auth_provider` CHECK admits `'local'` |
| Linkage row deletion (`oauth_accounts`) | Database / Storage (`catalog.oauth_accounts`) | ORM | Filtered DELETE by user_id + provider's saml-type |
| LIFECYCLE-06 verification | Backend test (`backend/tests/test_lifecycle.py`) | TestClient | HTTP-level invocation; ORM-level assertions |
| LIFECYCLE-07 verification | Backend test (`backend/tests/test_lifecycle.py`) | Module-level state mutation | Registry clear → re-register; SQL-level assertions |
| Operator runbook (re-onboarding section) | Documentation (`docs/edition-deactivation.md`) | — | Replaces Phase 220 line-81 TODO marker in-place |
| Reactivation forward-pointer | Documentation (`docs/edition-reactivation.md`) | — | One-paragraph caveat about converted users |

## Standard Stack

### Core (already in repo — no new dependencies)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | (project pinned) | Admin router framework | [VERIFIED: backend/app/modules/admin/router.py:7] Existing pattern |
| Pydantic v2 | (project pinned) | `SamlToLocalConversion` schema | [VERIFIED: backend/app/modules/admin/schemas.py:7] Existing pattern (Field, field_validator) |
| SQLAlchemy 2.x | >=2.0.25 | ORM mutation + ORM `delete()` for oauth_accounts | [VERIFIED: backend/app/modules/admin/service.py:6] Existing pattern |
| pwdlib + bcrypt | (project pinned) | Password hashing via `hash_password` | [VERIFIED: backend/app/modules/auth/providers/local.py:6-7,16,24-26] Project standard |
| pytest 9.0.3+ | >=9.0.3 | Round-trip + conversion tests | [VERIFIED: backend/pyproject.toml] anyio_mode=auto, asyncio_mode=strict |
| `lifecycle` pytest marker | — | Both new tests inherit | [VERIFIED: backend/pyproject.toml:74] Already registered by Phase 220 |
| `geolens-enterprise` (sibling repo) | 0.1.0 | Round-trip test imports `register_extensions` | [VERIFIED: ~/Code/geolens-enterprise/geolens_enterprise/__init__.py:5-25] CI installs (Phase 220 D-06) |

### Supporting (test infrastructure — already wired)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `saml_overlay_registered` fixture | — | Both new tests take it for overlay setup | [VERIFIED: backend/tests/conftest.py:454-484] Save/restore semantics already implemented |
| `_seed_saml_provider` helper | — | Conversion test + round-trip test seed phase | [VERIFIED: backend/tests/test_saml_overlay.py:96-137] Import or re-define |
| `test_db_session` fixture | — | ORM-level SQL assertions | [VERIFIED: backend/tests/conftest.py:386-395] Existing |
| `client` fixture (httpx AsyncClient) | — | TestClient for conversion endpoint | [VERIFIED: backend/tests/conftest.py:6,261] Existing pattern |
| `admin_auth_header` fixture | — | Conversion endpoint requires admin JWT | [VERIFIED: backend/tests/conftest.py:357-364] Existing pattern |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Dedicated POST endpoint (D-01) | Field on UserUpdate PATCH | Conflates conversion with field-edit; adds password to generic-update audit; rejected per CONTEXT.md |
| Update + preserve oauth_accounts row | Delete oauth_accounts row (D-04) | Preserving creates contradiction (`auth_provider='local'` AND live oauth link). Rejected. |
| Two-arm endpoint (local + OIDC) | Local-only endpoint (D-03) | OIDC arm triples test surface, requires picking target provider_id at runtime. Deferred per CONTEXT.md. |
| Programmatic re-register via direct ORM `_extensions["auth"] = ...` | `register_extensions(_extensions)` (D-09) | Direct assignment skips the actual production import path; calling the published function mirrors operator-side reactivation more faithfully. **Recommended.** |
| Vacuous "FK survives by definition" assertion | Seed an audit_log row, assert post-cycle (D-10) | Vacuous version doesn't actually exercise the audit table; requirement says "audit trail entries are all intact" — needs a real entry. |

**Installation:** No new dependencies. Phase 221 adds:
- 1 new endpoint in `backend/app/modules/admin/router.py`
- 1 new service method in `backend/app/modules/admin/service.py`
- 1 new schema in `backend/app/modules/admin/schemas.py`
- 2 new test functions + 1 extended cleanup fixture in `backend/tests/test_lifecycle.py`
- 1 new section in `docs/edition-deactivation.md` (replaces line-81 TODO)
- 1 paragraph in `docs/edition-reactivation.md`

**Version verification:** Not applicable — no new external dependencies added. All referenced libraries are existing project pins.

## Architecture Patterns

### System Architecture Diagram

```
                     ┌──────────────────────────────────────────────┐
                     │  Operator (post-deactivation, before reactivation) │
                     └─────────────────────┬────────────────────────┘
                                           │ reads
                                           ▼
              ┌──────────────────────────────────────────────────────┐
              │ docs/edition-deactivation.md                         │
              │  ├─ §pre-flight (existing inventory SQL)             │
              │  ├─ §"Handling existing SAML users" (NEW — Phase 221)│
              │  │   1. Inventory SAML users (existing SQL reuse)    │
              │  │   2. Decide conversion target (local vs OIDC)     │
              │  │   3. POST /admin/users/{id}/convert-saml-to-local │
              │  │      (curl example with $TOKEN)                   │
              │  │   4. Communicate new credentials out-of-band      │
              │  │   5. Verify login                                 │
              │  │   └─ Appendix: OIDC manual procedure              │
              │  └─ §destructive (existing alembic-downgrade content)│
              └──────────────────────────────────────────────────────┘
                                           │ describes
                                           ▼
    ───────── Conversion request flow (LIFECYCLE-06) ─────────

  ┌─────────────┐    ┌──────────────────────────┐    ┌─────────────────────────────┐
  │ admin curl  │───▶│ POST /admin/users/{id}/  │───▶│ AdminService.convert_       │
  │ + JWT       │    │ convert-saml-to-local    │    │ saml_user_to_local()        │
  │             │    │ (router.py)              │    │                              │
  │             │    │ require_permission(      │    │ TX:                          │
  │             │    │   "manage_users")        │    │  1. SELECT user + saml link │
  │             │    │ self-conversion guard    │    │  2. set password_hash       │
  │             │    └──────────┬───────────────┘    │  3. flip auth_provider      │
  │             │               │                    │  4. DELETE oauth_accounts    │
  │             │◀──────────────┴────────────────────│     (saml provider only)    │
  │             │   UserResponse                     │  5. log_action(              │
  └─────────────┘                                    │     action="auth.convert_   │
                                                     │             saml_to_local") │
                                                     │  COMMIT                      │
                                                     └─────────────────────────────┘

    ───────── Round-trip test flow (LIFECYCLE-07) ─────────

  ┌──────────────────────────────────────────────────────────────────────────┐
  │ test_deactivate_reactivate_roundtrip_preserves_saml_data                 │
  │                                                                           │
  │ SETUP    ──▶ saml_overlay_registered fixture (registry populated)        │
  │              save edition_mod._info; init_edition(["enterprise"])        │
  │                                                                           │
  │ SEED     ──▶ OAuthProvider (saml) + OAuthAccount + User (auth_provider=  │
  │              "oauth") + AuditLog row (action="test.seed", user_id=user)  │
  │                                                                           │
  │ DEACTIVATE ▶ _extensions.clear(); _routers.clear(); init_edition([])    │
  │              assert is_enterprise() is False  (mid-cycle checkpoint)    │
  │                                                                           │
  │ REACTIVATE ▶ from geolens_enterprise import register_extensions          │
  │              register_extensions(_extensions)  (idempotent re-call)     │
  │              init_edition(["enterprise"])                                │
  │              assert is_enterprise() is True                              │
  │                                                                           │
  │ ASSERT   ──▶ • 4 deferred SAML columns retained (undefer_group("saml")) │
  │              • OAuthAccount row intact                                  │
  │              • User row intact, auth_provider == "oauth"                 │
  │              • AuditLog row intact, user_id == seeded_user.id           │
  │              • is_enterprise() is True                                  │
  │              • get_audit_extension() etc. return enterprise instances   │
  │                                                                           │
  │ TEARDOWN ──▶ edition_mod._info = saved_info                             │
  │              saml_overlay_registered fixture restores _extensions/routers│
  │              _cleanup_lifecycle_rows fixture deletes seeded rows        │
  └──────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| File | Responsibility | Action |
|------|----------------|--------|
| `backend/app/modules/admin/router.py` | New `POST /admin/users/{user_id}/convert-saml-to-local` route | EDITED (add route) |
| `backend/app/modules/admin/service.py` | New `AdminService.convert_saml_user_to_local()` method | EDITED (add method) |
| `backend/app/modules/admin/schemas.py` | New `SamlToLocalConversion` Pydantic schema | EDITED (add class) |
| `backend/app/modules/audit/service.py` | `log_action()` reused (no change) | UNCHANGED — reference |
| `backend/app/modules/auth/providers/local.py` | `hash_password()` reused (no change) | UNCHANGED — reference |
| `backend/app/modules/auth/models.py` | `User.auth_provider` column + `chk_users_auth_provider` CHECK | UNCHANGED — read-only |
| `backend/app/modules/auth/oauth/models.py` | `OAuthAccount` row deletion target; `OAuthProvider` row preserved | UNCHANGED — read-only |
| `backend/tests/test_lifecycle.py` | +2 test functions, extended `_cleanup_lifecycle_rows` | EDITED |
| `backend/tests/test_saml_overlay.py` | `_seed_saml_provider` helper reused (or copied) | UNCHANGED — pattern source |
| `backend/tests/conftest.py` | `saml_overlay_registered`, `test_db_session`, `client`, `admin_auth_header` reused | UNCHANGED — fixture sources |
| `backend/pyproject.toml` | `lifecycle` marker (already registered Phase 220) | UNCHANGED |
| `.github/workflows/ci.yml` | Overlay install (Phase 220 D-06) inherited | UNCHANGED |
| `docs/edition-deactivation.md` | Replace line-81 TODO blockquote with new "Handling existing SAML users" section | EDITED (replace) |
| `docs/edition-reactivation.md` | Add forward-pointer paragraph (caveat for converted users) | EDITED (insert) |
| `~/Code/geolens-enterprise/geolens_enterprise/__init__.py` | `register_extensions()` re-invoked by round-trip test | UNCHANGED — referenced |

### Recommended Project Structure

```
backend/
├── app/modules/
│   ├── admin/
│   │   ├── router.py        # EDIT: add POST /admin/users/{id}/convert-saml-to-local
│   │   ├── service.py       # EDIT: add AdminService.convert_saml_user_to_local()
│   │   └── schemas.py       # EDIT: add SamlToLocalConversion class
│   ├── auth/
│   │   ├── models.py        # untouched
│   │   ├── oauth/models.py  # untouched
│   │   └── providers/local.py # untouched (hash_password reused)
│   └── audit/
│       └── service.py       # untouched (log_action reused)
└── tests/
    ├── conftest.py          # untouched (saml_overlay_registered + others reused)
    ├── test_saml_overlay.py # untouched (pattern + helper source)
    └── test_lifecycle.py    # EDIT: +2 test fns, extend _cleanup_lifecycle_rows

docs/
├── edition-deactivation.md  # EDIT: replace line-81 TODO blockquote with section
├── edition-reactivation.md  # EDIT: insert one-paragraph forward-pointer
└── saml.md                  # untouched
```

### Pattern 1: Admin Endpoint Shape (LIFECYCLE-06)

**What:** New `POST /admin/users/{user_id}/convert-saml-to-local` route follows the exact pattern of every existing admin user endpoint at `backend/app/modules/admin/router.py:62-371`.

**When to use:** Single-purpose admin mutation endpoints with audit-log entries.

**Example (sketch — final code in plan phase):**
```python
# Source: pattern from backend/app/modules/admin/router.py:213-249 (deactivate_user)
#         + 168-210 (update_user — self-action guard pattern)
@router.post(
    "/users/{user_id}/convert-saml-to-local/",
    response_model=UserResponse,
)
async def convert_saml_to_local(
    user_id: uuid.UUID,
    body: SamlToLocalConversion,
    request: Request,
    current_user: User = Depends(require_permission("manage_users")),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Convert a SAML-authenticated user to local-password authentication (admin only)."""
    # Self-conversion guard — admin self-lockout protection (Claude's Discretion)
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot convert your own account; use a different admin account",
        )
    service = AdminService(db)
    try:
        user, provider_slug = await service.convert_saml_user_to_local(
            user_id, body.password
        )
    except ValueError as exc:
        detail = str(exc)
        if "not found" in detail.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=detail,
            )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail,
        )
    ip = get_client_ip(request)
    await log_action(
        session=db,
        user_id=current_user.id,
        action="auth.convert_saml_to_local",
        resource_type="user",
        resource_id=user_id,
        details={"from": "saml", "to": "local", "provider_slug": provider_slug},
        ip_address=ip,
    )
    await db.commit()
    return _user_response(user)
```

[VERIFIED: backend/app/modules/admin/router.py:213-249] `deactivate_user` is the closest analog — same `current_user` dep, same `try/except ValueError → HTTPException` shape, same `log_action` call before `db.commit()`. The trailing slash on `/convert-saml-to-local/` matches existing patterns (e.g., `/users/{user_id}/deactivate/` at line 214) — **see Pitfall 4 below for the trailing-slash gotcha**.

### Pattern 2: Service Method (LIFECYCLE-06)

**What:** `AdminService.convert_saml_user_to_local()` mirrors the load-validate-mutate-return shape of `update_user` at `service.py:114-172`.

**Example (sketch):**
```python
# Source: pattern from backend/app/modules/admin/service.py:114-172 (update_user)
#         + 88-112 (deactivate_user — single-purpose mutation pattern)
async def convert_saml_user_to_local(
    self, user_id: uuid.UUID, password: str
) -> tuple[User, str]:
    """Convert a SAML-authenticated user to local-password.

    Returns (user, provider_slug). Raises ValueError on:
      - user not found (mapped to 404 by router)
      - user is not SAML-authenticated (mapped to 422)
    """
    # 1. Load user + verify SAML linkage
    result = await self.db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError("User not found")

    if user.auth_provider != "oauth":
        raise ValueError(
            f"User auth_provider is '{user.auth_provider}', not 'oauth' — "
            "conversion only applies to OAuth/SAML-authenticated users"
        )

    # Find a SAML linkage for this user
    saml_link_stmt = (
        select(OAuthAccount, OAuthProvider.slug)
        .join(OAuthProvider, OAuthAccount.provider_id == OAuthProvider.id)
        .where(
            OAuthAccount.user_id == user_id,
            OAuthProvider.provider_type == "saml",
        )
    )
    link_row = (await self.db.execute(saml_link_stmt)).first()
    if link_row is None:
        raise ValueError(
            "User has no SAML provider linkage — not a SAML-authenticated user"
        )
    saml_account, provider_slug = link_row

    # 2. Set password hash
    user.password_hash = hash_password(password)

    # 3. Flip auth_provider (CHECK constraint admits 'local')
    user.auth_provider = "local"

    # 4. Delete the SAML linkage row (D-04 — clean break)
    await self.db.execute(
        delete(OAuthAccount).where(OAuthAccount.id == saml_account.id)
    )

    # 5. Caller (router) writes the audit_log entry — keeps service free of
    #    request-context concerns (ip_address, current_user.id).
    await self.db.flush()
    await self.db.refresh(user)
    return user, provider_slug
```

[VERIFIED: backend/app/modules/admin/service.py:114-172] `update_user` shape: load → validate → mutate → flush → refresh → return. The `delete(OAuthAccount).where(...)` pattern matches the existing `delete(UserRole).where(...)` at line 166 + `delete(ApiKey).where(...)` at line 280.

**Note:** The service returns `(user, provider_slug)` so the router can include `provider_slug` in the audit-log `details` JSON. Audit-log writes are kept in the router (matches existing pattern `admin/router.py:200-209` `user.update`).

### Pattern 3: Round-Trip Reactivation Mechanism (LIFECYCLE-07)

**What:** The reactivation phase of the round-trip test calls `geolens_enterprise.register_extensions(_extensions)` directly — the same call path the `saml_overlay_registered` fixture uses for setup at `backend/tests/conftest.py:472-478`.

**Why this is critical:** The fixture's setup populates `_extensions["auth"]`, `_extensions["identity"]`, and appends to `_routers` — but it does so by **manually instantiating `EnterpriseSamlExtension()` and appending the SAML router only**. The production `register_extensions()` (`~/Code/geolens-enterprise/geolens_enterprise/__init__.py:5-25`) populates **four** keys (`auth`, `identity`, `audit`, `branding`) AND populates `registry["_routers"]` (a list) inside the registry dict (different shape from `_routers` global). Reading the production code carefully:

```python
# ~/Code/geolens-enterprise/geolens_enterprise/__init__.py:5-25
def register_extensions(registry: dict) -> None:
    saml_ext = _get_saml_extension()
    registry["auth"] = saml_ext
    registry["identity"] = saml_ext
    registry["audit"] = _get_audit_extension()
    registry["branding"] = _get_branding_extension()
    registry["_routers"] = _get_routers()    # NOTE: stores LIST under key "_routers"
```

`register_extensions(registry)` writes a `"_routers"` key INTO the dict — it does NOT mutate the module-level `_routers: list`. The fixture (`conftest.py:478`) bridges this by `_routers.append(saml_router)`. **The round-trip test must therefore use the same bridging idiom the fixture uses, not call `register_extensions()` blindly.** Two viable shapes:

**Shape A (mirror the fixture exactly — recommended):**
```python
# Reactivate: reproduce the fixture's setup steps (idempotent re-call)
from geolens_enterprise.auth.saml import EnterpriseSamlExtension
from geolens_enterprise.auth.saml.router import router as saml_router

ext = EnterpriseSamlExtension()
_extensions["auth"] = ext
_extensions["identity"] = ext
_routers.append(saml_router)
edition_mod.init_edition(["enterprise"])
```

**Shape B (call register_extensions, accept divergence):**
```python
from geolens_enterprise import register_extensions
register_extensions(_extensions)
# Note: _routers list (module-level) is NOT populated by this call;
# instead _extensions["_routers"] holds the list. The lifecycle test does
# NOT assert on routers being mounted into the FastAPI app, so this is OK
# for SQL-level symmetry assertions. But documenting the divergence.
edition_mod.init_edition(["enterprise"])
```

**Recommendation:** Shape A. Mirror the fixture's setup verbatim — that is the proven path the rest of the SAML test suite trusts. Shape B is closer to the production discovery sequence but sets the module-level `_routers` to the empty list, which would diverge from the fixture's pre-test state and confuse downstream tests if the order of test runs matters.

[VERIFIED: backend/tests/conftest.py:466-484] Fixture body. [VERIFIED: ~/Code/geolens-enterprise/geolens_enterprise/__init__.py:5-25] Production register_extensions shape. [VERIFIED: backend/tests/test_lifecycle.py:177-179] Phase 220 deactivate side already uses `_extensions.clear(); _routers.clear(); init_edition([])` — the test should symmetrically *re-populate* on the reactivate side using the same module-level surfaces.

### Pattern 4: Runbook Section Replacement (LIFECYCLE-06 docs)

**What:** Replace the existing TODO blockquote at `docs/edition-deactivation.md:79-81` with a 6-step section.

**Existing line (Phase 220 placeholder):**
```markdown
3. **Communicate to SAML-authenticated users.**

   > **Existing SAML users will lose their login path.** Phase 221 ships the user re-onboarding procedure ("Handling existing SAML users", planned). Until that lands, communicate the downgrade to SAML users out-of-band and convert their accounts manually via the admin UI (set local password or convert to OIDC).
```

**Replacement (sketch — exact wording is planner's call):**
```markdown
3. **Communicate to SAML-authenticated users — see [Handling existing SAML users](#handling-existing-saml-users) below.** Plan the order: convert users *after* the overlay is removed (so the SAML routes 404 immediately and no SAML login can race the conversion).

[...rest of pre-flight unchanged...]

## Handling existing SAML users

Existing SAML-authenticated users lose their login path the moment the overlay is removed. The conversion endpoint below moves each affected user to a local-password account in a single transaction, preserving every record they own (audit history, role memberships, dataset ownership) — `users.id` is unchanged across the conversion, so every foreign-key reference (`audit_logs.user_id`, `user_roles.user_id`, `datasets.created_by`, etc.) remains valid.

### Step 1: Inventory SAML users

Reuse the SQL from §pre-flight step 2:

\```sql
SELECT u.id, u.username, u.email, op.slug AS provider_slug
FROM catalog.users u
JOIN catalog.oauth_accounts oa ON oa.user_id = u.id
JOIN catalog.oauth_providers op ON op.id = oa.provider_id
WHERE op.provider_type = 'saml'
  AND u.auth_provider = 'oauth';
\```

### Step 2: Decide conversion target per user

| Target | When to use | Procedure |
|---|---|---|
| **Local-password** | Default. Universal — works regardless of OIDC config state. | Endpoint below |
| **OIDC re-link** | You have an OIDC `oauth_providers` row already configured | Manual procedure — see [Appendix](#appendix-oidc-conversion-manual) |

### Step 3: Run the conversion endpoint per user

Obtain an admin JWT first (replace `$ADMIN_USER` / `$ADMIN_PASSWORD`):

\```bash
TOKEN=$(curl -fsS -X POST http://localhost:8000/auth/login/ \
  -d "username=$ADMIN_USER&password=$ADMIN_PASSWORD" \
  | jq -r .access_token)
\```

Then convert each user:

\```bash
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"password": "<temp-strong-password>"}' \
  http://localhost:8000/admin/users/<user-id>/convert-saml-to-local/
\```

A successful response is the user's `UserResponse` payload with `auth_provider` reflecting the new local state. The endpoint:

- Validates the user is currently SAML-authenticated (`auth_provider='oauth'` AND has a SAML `oauth_accounts` row). Otherwise 422.
- Sets `users.password_hash` to a bcrypt hash of the supplied password.
- Flips `users.auth_provider` to `'local'`.
- Deletes the user's `oauth_accounts` row pointing at the SAML provider (the SAML `oauth_providers` row itself is preserved — other users may still link to it).
- Writes one `audit_log` entry with `action='auth.convert_saml_to_local'` and `details` recording the original provider slug.

All steps run in one transaction; partial failures roll back.

### Step 4: Communicate the new credentials out-of-band

Choose a secure delivery channel (encrypted email, password manager share, in-person credential drop). Each user logs in using the new local-password credentials at `/login`.

### Step 5: Verify the user can log in

\```bash
curl -fsS -X POST http://localhost:8000/auth/login/ \
  -d "username=$USERNAME&password=<temp-strong-password>"
\```

Expected: 200 with `access_token`. If the response is 401, confirm the conversion endpoint returned 200 and the user supplied the temporary password verbatim.

### Appendix: OIDC conversion (manual)

If your deployment already has an OIDC `oauth_providers` row configured and you want a SAML user to keep federated SSO via OIDC instead of moving to local-password:

1. Run the OIDC enrollment flow from the user's perspective (sign in via the OIDC provider button on `/login`); GeoLens JIT-creates the `oauth_accounts` link.
2. Manually delete the SAML `oauth_accounts` row for the user via SQL (matching the user_id and the SAML provider_id).
3. The user's `auth_provider` stays `'oauth'`; the user's `users.id` is unchanged; their audit history and role memberships remain intact.

OIDC conversion has no automated endpoint in v13.2 — automation is on the deferred roadmap.
```

[VERIFIED: docs/edition-deactivation.md:79-81] Existing TODO blockquote text. [VERIFIED: docs/edition-deactivation.md:62-77] Existing inventory SQL pattern (reused). [VERIFIED: docs/saml.md tone] `> blockquote` callouts + matrix tables + code-block-heavy structure (Phase 220 RESEARCH §Pitfall 1 confirms `docs/saml.md` is the only substantive style reference).

### Anti-Patterns to Avoid

- **Anti-pattern 1: Putting `password` on `UserUpdate`.** [LOCKED: D-01] Conflates conversion with field-edit. Never do this — the conversion is a domain-specific operation, not a generic update.
- **Anti-pattern 2: Soft-deleting the `oauth_accounts` row.** [LOCKED: D-04] Creates a contradictory state (`auth_provider='local'` AND live SAML link). Always hard-delete.
- **Anti-pattern 3: Writing the audit_log row OUTSIDE the conversion transaction.** [LOCKED: D-05] If the conversion fails post-audit-log-write, the audit log records something that didn't happen. The audit_log call must be the LAST step before commit.
- **Anti-pattern 4: Touching `users.id` during conversion.** [LOCKED: D-06] FK rollover would be required for every dependent table; the entire LIFECYCLE-06 contract turns into a complex cascade. The user's UUID is the durable handle.
- **Anti-pattern 5: Calling `alembic` mid-test.** [INHERITED: Phase 220 destructive_path_prohibition] The 4 SAML columns must remain physically present throughout the round-trip test. Mid-test alembic upgrade/downgrade defeats the test premise.
- **Anti-pattern 6: Adding `not lifecycle` to `addopts` deselect list.** [INHERITED: Phase 220 RESEARCH §Pitfall 7] Lifecycle tests run in CI by default. Only `perf` is heavy enough to deselect.
- **Anti-pattern 7: Touching `_outstanding_requests` or `replay_cache._seen` in the lifecycle test.** [INHERITED: Phase 220 RESEARCH §Pitfall 3] Those caches are SAML-flow-specific. The lifecycle test never exercises an ACS POST.
- **Anti-pattern 8: Module-level imports of `geolens_enterprise` inside `test_lifecycle.py`.** [INHERITED: Phase 220 RESEARCH §Pitfall 5] Defer enterprise imports inside test/function bodies so collection succeeds in community-only environments.
- **Anti-pattern 9: Promoting `_cleanup_lifecycle_rows` to conftest.py.** [LOCKED: D-11] Stays test-local. Other tests don't need it.
- **Anti-pattern 10: Round-trip test asserts on FastAPI route remounting.** [INHERITED: Phase 220 RESEARCH §Pitfall 8] `app.routes` membership is fragile under test ordering. SQL-only assertions are sufficient for LIFECYCLE-07.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Password hashing for the conversion endpoint | New bcrypt wrapper | `hash_password()` from `backend/app/modules/auth/providers/local.py:24-26` | Already imported in admin/service.py:15; project standard |
| Audit-log write for the conversion | New audit-write helper | `log_action()` from `backend/app/modules/audit/service.py:49-67` | Existing pattern: caller commits, log_action only adds the row to session |
| Auth dependency for the new endpoint | New permission check | `require_permission("manage_users")` from `backend/app/modules/auth/dependencies.py` | Used by every existing user-mutation admin route |
| ValueError → HTTPException mapping | New exception class | Existing pattern (`router.py:188-198` update_user) | Convention: ValueError is service-layer signal; router maps to 404/422 |
| User-row mutation | Raw SQL UPDATE | ORM attribute assignment (`user.password_hash = ...`) | Matches existing patterns; SQLAlchemy flush handles UPDATE |
| `oauth_accounts` row delete | Raw SQL DELETE | ORM `delete(OAuthAccount).where(...)` | Matches `delete(UserRole)` at `service.py:166`, `delete(ApiKey)` at `service.py:280` |
| Round-trip test "overlay registered" setup | New fixture from scratch | Existing `saml_overlay_registered` (`conftest.py:454-484`) | Already implements save/restore semantics correctly |
| SAML provider seeding in tests | Hand-built ORM object | `_seed_saml_provider()` from `test_saml_overlay.py:96-137` (import or copy) | Includes encrypt_secret() for cert, sane defaults |
| Edition state save/restore | Direct `_info` assignment + ad-hoc patches | `init_edition([])` / `init_edition(["enterprise"])` (precedent at `test_saml_overlay.py:239,270`) | Public API path; deactivate-side test already uses it |
| Cleanup of seeded test rows | Manual `db.delete(...)` per row | Extend Phase 220's `_cleanup_lifecycle_rows` (`test_lifecycle.py:76-102`) | Already uses scoped DELETE-by-slug/username pattern |
| TestClient invocation of the conversion endpoint | New client setup | Existing `client` + `admin_auth_header` (`conftest.py:357-364`) | Standard admin-test pattern (see `test_admin_user_operations.py`) |

**Key insight:** Phase 221 is almost entirely composition over construction — the new endpoint is 3 small additions to existing files reusing 5 existing primitives, and the new tests are 2 functions reusing every Phase 217/220 fixture and helper. The risk is over-engineering; the planner should default to "smallest possible diff" for both the endpoint and the tests.

## Runtime State Inventory

> Phase 221 adds a new endpoint and two tests; the only "rename/refactor" surface is the docs/edition-deactivation.md TODO marker that gets replaced. Most categories are explicitly "nothing found."

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — the conversion endpoint MUTATES existing rows (`users.password_hash`, `users.auth_provider`) and DELETES one `oauth_accounts` row per call, but no data migration is required for any pre-existing record. The test seeds throwaway rows under the `lifecycle-test` slug + `lifecycle-saml-user` username (Phase 220 pattern) and cleans up. | None — endpoint is per-request; no batch migration. |
| Live service config | None — no n8n / Datadog / Tailscale / Cloudflare touchpoints. The audit-log catalog (if one existed) would gain the action name `auth.convert_saml_to_local`, but [VERIFIED: ls backend/app/modules/audit/] there is no catalog file (`backend/app/modules/audit/` contains only `__init__.py`, `models.py`, `router.py`, `schemas.py`, `service.py` — no `actions.py` enum). The action ships as a string literal at the call site (D-14). | None |
| OS-registered state | None | None |
| Secrets/env vars | None — no new secret needed; CI's `GEOLENS_ENTERPRISE_TOKEN` (Phase 220) is reused. Operator-side: the runbook references the existing admin login flow (`POST /auth/login/` with `GEOLENS_ADMIN_USERNAME` + `GEOLENS_ADMIN_PASSWORD` env vars per project memory) for obtaining the conversion JWT. | None |
| Build artifacts / installed packages | None — no pip egg-info / Docker image tag / npm install impact. CI install of `geolens-enterprise` is fresh per job (Phase 220 D-06). | None |

**The canonical question:** *After every file in the repo is updated, what runtime systems still have the old framing cached?*

Two answers:

1. The line-81 TODO blockquote in `docs/edition-deactivation.md` references "Phase 221 will land this section." Phase 221's edit removes that forward-pointer in-place. **Verify there are no other in-repo references to the line-81 TODO** — see Pitfall 6 below for the grep.
2. `docs.getgeolens.com` (the marketing/docs site, separate repo) may carry a snapshot of `docs/edition-deactivation.md`. Phase 221 ships in this repo only; cross-repo sync is a follow-up task (Phase 220 RESEARCH §Open Question 1, deferred).

## Common Pitfalls

### Pitfall 1: Three module-level state surfaces — three explicit resets, three explicit re-populations

**What goes wrong:** Round-trip test resets only `_extensions` + `_routers` on the deactivate side, then forgets one of the three on the reactivate side. `is_enterprise()` returns the wrong answer after the cycle, or the test is silently asymmetric.

**Why it happens:** [INHERITED: Phase 220 RESEARCH §Pitfall 2] `app.platform.extensions._extensions`, `app.platform.extensions._routers`, and `app.core.edition._info` are three independent module-level singletons. Phase 220's deactivate test resets all three; Phase 221's round-trip test must do the same on the reactivate side too:

```python
# Deactivate side (Phase 220 inheritance)
_extensions.clear()
_routers.clear()
edition_mod.init_edition([])

# Reactivate side (Phase 221 NEW — must symmetrically restore all three)
ext = EnterpriseSamlExtension()
_extensions["auth"] = ext
_extensions["identity"] = ext
_routers.append(saml_router)
edition_mod.init_edition(["enterprise"])    # third reset — DON'T forget
```

**How to avoid:** Match the fixture's setup verbatim on the reactivate side (Pattern 3 Shape A). One pair, one mirror.

**Warning signs:** Test asserts `is_enterprise() is True` after reactivate but it returns False — `init_edition(["enterprise"])` was forgotten.

### Pitfall 2: `register_extensions(registry)` writes `registry["_routers"]` (key in dict), NOT `_routers` (module-level list)

**What goes wrong:** Test calls `register_extensions(_extensions)` blindly thinking it will populate `_routers` — but the function's contract is `registry["_routers"] = _get_routers()`, which writes a *key* into the dict, not the module-level list. The fixture's setup pattern (`_routers.append(saml_router)`) does NOT match `register_extensions()`'s shape.

**Why it happens:** [VERIFIED: ~/Code/geolens-enterprise/geolens_enterprise/__init__.py:5-25] `register_extensions()` is the *production* discovery contract — the core repo's `load_extensions()` reads the registry dict and pulls `_routers` out by key. The fixture (`backend/tests/conftest.py:466-484`) bridges between this dict-shape and the module-level `_routers: list` by manually appending. The two shapes are not interchangeable; Pattern 3 Shape A above mirrors the fixture exactly to avoid the divergence.

**How to avoid:** Use Shape A (manual instantiation matching the fixture), or accept Shape B's divergence and document it. Recommendation: Shape A.

**Warning signs:** Test passes assertion on `_extensions["auth"]` but fails to find the SAML router somewhere — the divergence between dict-key `_routers` and module-level `_routers` was not bridged.

### Pitfall 3: `_seed_saml_provider`'s `client_secret_encrypted` placeholder is encrypt_secret("unused")

**What goes wrong:** New seed code uses a raw string `"unused"` for `client_secret_encrypted` and the test fails with a Fernet decryption error or NOT-NULL constraint mismatch.

**Why it happens:** [VERIFIED: backend/tests/test_saml_overlay.py:96-137 + backend/app/modules/auth/oauth/encryption.py] `client_secret_encrypted` is NOT-NULL on the ORM (`oauth/models.py:47`). The existing seed helper passes `encrypt_secret("unused")` not raw `"unused"` — Fernet ciphertext is required at-rest. Same goes for `idp_certificate` (`oauth/models.py:73-75`).

**How to avoid:** Reuse `_seed_saml_provider` from `test_saml_overlay.py:96-137` (import it directly) OR copy its body verbatim. Phase 220's `test_lifecycle.py:136-147` already follows this pattern — Phase 221 inherits.

**Warning signs:** Seed phase fails with `IntegrityError: client_secret_encrypted` violates NOT-NULL or `cryptography.fernet.InvalidToken` on read. The Phase 220 test file is the working reference (`test_lifecycle.py:141,144`).

### Pitfall 4: FastAPI trailing-slash 307 redirects break the curl example

**What goes wrong:** Runbook curl is documented as `POST /admin/users/<id>/convert-saml-to-local` (no trailing slash); operator gets a 307 redirect to `/admin/users/<id>/convert-saml-to-local/` and the JSON body is lost on the redirect.

**Why it happens:** [VERIFIED: project memory MEMORY.md / `feedback_no_blanket_add_planning.md` neighborhood — known issue documented in MEMORY.md "FastAPI trailing slashes"] FastAPI routes defined with `"/"` cause 307 redirects when called without trailing slash. Existing admin endpoints follow trailing-slash convention (`@router.post("/users/{user_id}/deactivate/", ...)` at router.py:214).

**How to avoid:** Define the new route with the trailing slash (`@router.post("/users/{user_id}/convert-saml-to-local/", ...)`) AND document the curl example with the trailing slash (`/admin/users/<id>/convert-saml-to-local/`).

**Warning signs:** Runbook's curl example lacks the trailing slash; manual UAT shows 307 in the admin's terminal.

### Pitfall 5: Auth login path is `/auth/login/`, NOT `/auth/token`

**What goes wrong:** Runbook references `/auth/token` for obtaining the admin JWT; curl returns 404; operator is confused.

**Why it happens:** [VERIFIED: backend/tests/conftest.py:328-334] The conftest helper `get_auth_header()` posts to `/auth/login/` (form-data with `username` + `password`). There is no `/auth/token` endpoint in this codebase. (CONTEXT.md D-Discretion notes "POST /auth/token" in passing — that wording is incorrect for this repo.)

**How to avoid:** Runbook curl example uses `POST http://localhost:8000/auth/login/` with form-data `-d "username=...&password=..."` — copy the conftest pattern exactly.

**Warning signs:** Manual UAT of the runbook gets 404 on the token-obtaining curl.

### Pitfall 6: Phase 220 line-81 TODO has downstream references that may need updating

**What goes wrong:** Phase 221 deletes the TODO blockquote in-place but in-repo cross-references remain (e.g., audit reports, planning docs, CHANGELOG entries) pointing operators at "see line 81."

**Why it happens:** Phase 220's discussion log + verification artifacts may reference the line-81 TODO explicitly. CONTEXT.md acknowledges this risk.

**How to avoid:** Before merging Phase 221, run a grep for `edition-deactivation.md.*81` and `Phase 221 ships the user re-onboarding` across the repo to find any stragglers. Verified clean as part of the planner's wave-merge gate.

```bash
grep -rn "Phase 221 ships the user re-onboarding" /Users/ishiland/Code/geolens
grep -rn "edition-deactivation.md:81" /Users/ishiland/Code/geolens
```

**Warning signs:** PR review comment says "this section says Phase 221 is planned — that's now."

### Pitfall 7: Self-conversion fat-finger (admin locks themselves out)

**What goes wrong:** Sole admin invokes the conversion endpoint on their own account, fat-fingers the new password, and now there's no admin left who can log in. (CONTEXT.md Risk Surfaces flags this; mitigation is the self-conversion guard.)

**Why it happens:** Endpoint is permissive about converting any user — `require_permission("manage_users")` doesn't gate self-vs-other. The existing `update_user` route DOES gate this for role changes (`router.py:180-184`).

**How to avoid:** Block `current_user.id == user_id` with 422 — recommended wording: "Cannot convert your own account; use a different admin account or convert someone else's account first." (Mirror `admin/router.py:180-184` shape exactly.)

**Warning signs:** Manual smoke test deliberately tries to self-convert and gets a 200 instead of 422.

### Pitfall 8: Race — SAML user mid-login while conversion runs

**What goes wrong:** A SAML user POSTs to `/auth/saml/{slug}/acs` while the admin runs the conversion. The login flow's `find_or_create_oauth_user` may hit a partially-converted state (linkage already deleted but user.auth_provider not yet flipped) or vice versa, depending on race ordering.

**Why it happens:** Two transactions race against the same User row. `find_or_create_oauth_user` (`oauth/service.py:183-`) does a SELECT-based linkage lookup that doesn't lock the user.

**How to avoid:** [LOCKED: CONTEXT.md Risk Surfaces] Runbook explicitly orders: "convert users *after* deactivation, not before." Once the overlay is removed, `/auth/saml/*` returns 404 (verified by Phase 220's deactivation runbook step 4) and no SAML login can race the conversion. Phase 221 runbook documents this ordering explicitly in the "Handling existing SAML users" section's preamble.

**Warning signs:** Phase 221 runbook is missing the "after deactivation" ordering note; an operator runs the conversion before the overlay is removed.

### Pitfall 9: Empty `Assumptions Log` is fine — but the open OIDC-conversion question is real

**What goes wrong:** Planner reads "OIDC manual procedure" in the runbook and thinks the appendix is fully specified.

**Why it happens:** D-03 + the runbook appendix sketch above describe the procedure at a high level (run OIDC enrollment, manually delete SAML linkage). The exact SQL and ordering are *not* fully specified — they are intentionally Claude's-discretion content for the runbook author at plan time.

**How to avoid:** Planner should treat the OIDC appendix as "describe the procedure faithfully but do not over-specify SQL the operator will tailor to their schema." Three short steps (enroll OIDC → delete SAML linkage → confirm) are sufficient; longer prescriptions are over-engineering.

**Warning signs:** OIDC appendix exceeds ½ page or includes copy-paste-able SQL with concrete UUIDs — that's over-specification.

## Code Examples

### Example 1 — Schema declaration (`backend/app/modules/admin/schemas.py`)

```python
# Source: pattern from backend/app/modules/admin/schemas.py:17-43 (AdminUserCreate.password)
class SamlToLocalConversion(BaseModel):
    password: str = Field(
        min_length=8,
        max_length=256,
        description="Local-password for the converted account (minimum 8 characters). "
                    "The user can change this after first login.",
    )
```

[VERIFIED: backend/app/modules/admin/schemas.py:23-26] `min_length=8` matches `AdminUserCreate.password`.

### Example 2 — Endpoint definition (`backend/app/modules/admin/router.py`)

See Pattern 1 sketch above. Insertion point: alongside `update_user` at line 168 or `deactivate_user` at line 213.

### Example 3 — Service method (`backend/app/modules/admin/service.py`)

See Pattern 2 sketch above. Insertion point: between `update_user` (line 114) and `list_users` (line 174).

### Example 4 — LIFECYCLE-06 conversion test (`backend/tests/test_lifecycle.py`)

```python
# Source: pattern from backend/tests/test_lifecycle.py:111-235 (Phase 220 test) +
#         test_admin_user_operations.py:27-99 (admin endpoint TestClient pattern)
@pytest.mark.lifecycle
async def test_convert_saml_user_to_local_preserves_user_data(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
    saml_overlay_registered,
    _cleanup_lifecycle_rows,
):
    """LIFECYCLE-06: converting a SAML user to local-password preserves audit
    history, group memberships, and dataset ownership.

    Steps:
      1. Seed: SAML provider + User (auth_provider='oauth') + OAuthAccount linkage
         + UserRole assignment + AuditLog row + (optionally) Dataset row with
         created_by=user.id.
      2. Invoke POST /admin/users/{user.id}/convert-saml-to-local/ via TestClient.
      3. Assert response 200 with auth_provider='local'.
      4. Assert preservation:
         - users.id unchanged (same row)
         - users.auth_provider == 'local'
         - users.password_hash is not None
         - oauth_accounts row deleted
         - oauth_providers row preserved (not deleted)
         - user_roles row preserved with same user_id
         - audit_log seed row preserved with original user_id
         - datasets.created_by == user.id (if seeded)
         - new audit_log row exists with action='auth.convert_saml_to_local'
    """
    # ... seed phase mirrors Phase 220 test:128-174 ...
    # ... add UserRole + AuditLog seed rows + (optionally) Dataset.created_by ...
    # ... call client.post with admin_auth_header ...
    # ... assert preservation ...
```

### Example 5 — LIFECYCLE-07 round-trip test (`backend/tests/test_lifecycle.py`)

```python
# Source: pattern from backend/tests/test_lifecycle.py:111-235 (Phase 220 deactivate-only)
#         + Pattern 3 Shape A above (reactivation mechanism)
@pytest.mark.lifecycle
async def test_deactivate_reactivate_roundtrip_preserves_saml_data(
    test_db_session: AsyncSession,
    saml_overlay_registered,
    _cleanup_lifecycle_rows,
):
    """LIFECYCLE-07: deactivate→reactivate cycle is lossless across User
    identities, oauth_providers rows, oauth_accounts rows, and audit_log entries.
    """
    saved_info = edition_mod._info
    edition_mod.init_edition(["enterprise"])

    try:
        # 1. SEED phase — overlay registered, edition flipped to enterprise
        provider = OAuthProvider(
            slug=LIFECYCLE_SLUG, ...
            idp_entity_id=LIFECYCLE_IDP_ENTITY_ID,
            idp_sso_url=LIFECYCLE_IDP_SSO_URL,
            idp_certificate=encrypt_secret(LIFECYCLE_CERT_PEM),
            sp_entity_id=LIFECYCLE_SP_ENTITY_ID,
        )
        test_db_session.add(provider)
        await test_db_session.commit()
        await test_db_session.refresh(provider)
        seeded_provider_id = provider.id

        user = User(
            username=LIFECYCLE_USERNAME,
            email=LIFECYCLE_USER_EMAIL,
            auth_provider="oauth",
            password_hash=None,
            is_active=True,
        )
        test_db_session.add(user)
        await test_db_session.commit()
        await test_db_session.refresh(user)
        seeded_user_id = user.id

        account = OAuthAccount(
            user_id=seeded_user_id,
            provider_id=seeded_provider_id,
            subject=LIFECYCLE_USER_SUBJECT,
        )
        test_db_session.add(account)
        await test_db_session.commit()

        # SEED an audit_log row (D-10 — real audit-trail assertion)
        from app.modules.audit.service import log_action
        await log_action(
            session=test_db_session,
            user_id=seeded_user_id,
            action="test.seed.lifecycle",
            resource_type="user",
            resource_id=seeded_user_id,
            details={"phase": "221", "purpose": "round-trip-symmetry"},
        )
        await test_db_session.commit()

        # 2. DEACTIVATE phase — three module-level surfaces reset
        _extensions.clear()
        _routers.clear()
        edition_mod.init_edition([])

        # mid-cycle checkpoint
        from app.core.edition import is_enterprise
        assert is_enterprise() is False, "deactivate side did not flip is_enterprise"

        # 3. REACTIVATE phase — Pattern 3 Shape A (mirror the fixture)
        from geolens_enterprise.auth.saml import EnterpriseSamlExtension
        from geolens_enterprise.auth.saml.router import router as saml_router
        ext = EnterpriseSamlExtension()
        _extensions["auth"] = ext
        _extensions["identity"] = ext
        _routers.append(saml_router)
        edition_mod.init_edition(["enterprise"])

        # 4. ASSERT symmetry
        # is_enterprise restored
        assert is_enterprise() is True

        # 4 deferred SAML columns retained
        stmt = (
            select(OAuthProvider)
            .where(OAuthProvider.id == seeded_provider_id)
            .options(undefer_group("saml"))
        )
        survivor = (await test_db_session.execute(stmt)).scalar_one()
        assert survivor.idp_entity_id == LIFECYCLE_IDP_ENTITY_ID
        assert survivor.idp_sso_url == LIFECYCLE_IDP_SSO_URL
        assert decrypt_secret(survivor.idp_certificate) == LIFECYCLE_CERT_PEM
        assert survivor.sp_entity_id == LIFECYCLE_SP_ENTITY_ID

        # OAuthAccount linkage row intact
        account_row = (
            await test_db_session.execute(
                select(OAuthAccount).where(
                    OAuthAccount.provider_id == seeded_provider_id,
                    OAuthAccount.user_id == seeded_user_id,
                )
            )
        ).scalar_one_or_none()
        assert account_row is not None

        # User row intact
        user_row = (
            await test_db_session.execute(
                select(User).where(User.id == seeded_user_id)
            )
        ).scalar_one()
        assert user_row.auth_provider == "oauth"

        # Audit log seed row intact (D-10)
        from app.modules.audit.models import AuditLog
        audit_row = (
            await test_db_session.execute(
                select(AuditLog).where(
                    AuditLog.user_id == seeded_user_id,
                    AuditLog.action == "test.seed.lifecycle",
                )
            )
        ).scalar_one_or_none()
        assert audit_row is not None, (
            "audit_log row was destroyed by deactivate→reactivate cycle"
        )
        assert audit_row.user_id == seeded_user_id

        # Typed accessors return enterprise instances post-reactivation
        from app.platform.extensions import (
            get_audit_extension, get_branding_extension,
            get_auth_extension, get_identity_extension,
        )
        assert isinstance(get_auth_extension(), EnterpriseSamlExtension)

    finally:
        edition_mod._info = saved_info
        # _extensions / _routers restored by saml_overlay_registered.finally
```

[VERIFIED: backend/tests/test_lifecycle.py:111-235] Phase 220 test gives the exact seed-phase pattern. Phase 221's round-trip test extends it with the reactivate phase and the audit_log seed/assert pair (D-10).

### Example 6 — Extended `_cleanup_lifecycle_rows` fixture

```python
# Source: pattern from backend/tests/test_lifecycle.py:76-102 (Phase 220 fixture)
@pytest.fixture
async def _cleanup_lifecycle_rows(test_db_session: AsyncSession):
    """Best-effort teardown of lifecycle test rows (extended for Phase 221).

    Adds: audit_log + user_roles + datasets cleanup scoped to the test's user UUID.
    Order matters — delete child rows before parent rows to satisfy FK CASCADE
    semantics (or, when SET NULL is configured, to keep tests deterministic).
    """
    yield
    try:
        # Resolve the test user's id (if seeded)
        result = await test_db_session.execute(
            text("SELECT id FROM catalog.users WHERE username = :username"),
            {"username": LIFECYCLE_USERNAME},
        )
        user_row = result.scalar_one_or_none()

        if user_row is not None:
            # audit_log: SET NULL on user delete, but explicit DELETE for tighter isolation
            await test_db_session.execute(
                text("DELETE FROM catalog.audit_logs WHERE user_id = :uid"),
                {"uid": user_row},
            )
            # user_roles: CASCADE on user delete; explicit DELETE for clarity
            await test_db_session.execute(
                text("DELETE FROM catalog.user_roles WHERE user_id = :uid"),
                {"uid": user_row},
            )
            # datasets: SET NULL on created_by/updated_by; explicit DELETE if seeded
            # NOTE: planner picks whether to DELETE datasets seeded by this test
            # or NULL them out via SET NULL when the user is deleted.

        # Phase 220 inheritance — provider + account + user
        await test_db_session.execute(
            text(
                "DELETE FROM catalog.oauth_accounts WHERE provider_id IN "
                "(SELECT id FROM catalog.oauth_providers WHERE slug = :slug)"
            ),
            {"slug": LIFECYCLE_SLUG},
        )
        await test_db_session.execute(
            text("DELETE FROM catalog.oauth_providers WHERE slug = :slug"),
            {"slug": LIFECYCLE_SLUG},
        )
        await test_db_session.execute(
            text("DELETE FROM catalog.users WHERE username = :username"),
            {"username": LIFECYCLE_USERNAME},
        )
        await test_db_session.commit()
    except Exception:
        await test_db_session.rollback()
```

[VERIFIED: backend/tests/test_lifecycle.py:76-102] Phase 220 fixture body. Phase 221 extends with audit_log + user_roles + datasets (the new row types LIFECYCLE-06 test seeds).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Phase 220's line-81 placeholder TODO ("Phase 221 will land this section, planned") | A real "Handling existing SAML users" section + a real backend endpoint | Phase 221 (this phase) | Operators have a tested, copy-paste-able procedure instead of a forward-pointer |
| Deactivate-only test (Phase 220) | Deactivate-only + conversion + round-trip = 3 lifecycle tests | Phase 221 (this phase) | LIFECYCLE-07's symmetry guarantee is verified, not theoretical |
| Re-onboarding via "manually via the admin UI" claim (Phase 220 line-81) | Real `POST /admin/users/{id}/convert-saml-to-local/` endpoint | Phase 221 (this phase) | Operators no longer pointed at a non-existent UI affordance |

**Deprecated/outdated:**
- The Phase 220 line-81 blockquote ("convert their accounts manually via the admin UI") was always inaccurate — there was no such admin UI affordance. Phase 221 deletes it.

## Assumptions Log

> Claims tagged `[ASSUMED]` in this research that need user/planner confirmation before becoming locked.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Service method returns `(user, provider_slug)` tuple so router can include `provider_slug` in audit-log details | Pattern 2 | Low — alternative: service writes the audit_log internally and accepts request context. Pattern is bikeshed; CONTEXT.md doesn't lock the return signature. |
| A2 | Round-trip test uses Pattern 3 Shape A (mirror fixture) over Shape B (`register_extensions(_extensions)`) | Pattern 3 | Low — both work for SQL-level assertions. Shape A is recommended; planner can pick Shape B with documented divergence. |
| A3 | `audit_log` seed action name `"test.seed.lifecycle"` (D-10 implementation detail) | Example 5 | Very low — placeholder string for a test-only row; planner picks final wording. |
| A4 | Self-conversion guard surfaces 422 (not 400 or 403) | Pattern 1, Pitfall 7 | Low — matches the existing `admin/router.py:180-184` self-action guard which uses 422. |
| A5 | Runbook curl uses `/auth/login/` (form-data) for token; recommended over `$TOKEN` placeholder | Pattern 4, Pitfall 5 | Medium — if planner wants the runbook to be backend-agnostic for cloud deployments where login is via OIDC, the `/auth/login/` example is over-prescriptive. Acceptable since deactivation runbook is on-prem-focused. |
| A6 | Cleanup fixture extension does explicit DELETEs on audit_logs/user_roles before user, even though FK semantics (SET NULL / CASCADE) would handle it implicitly | Example 6 | Low — explicit DELETEs are defensive; CONTEXT.md Claude's Discretion explicitly leaves this to planner choice. |
| A7 | The "Handling existing SAML users" section is appended to `docs/edition-deactivation.md` as a top-level `##` heading after the destructive-path section — not nested inside §pre-flight | Pattern 4 | Low — placement is style; planner picks. Anchor link `#handling-existing-saml-users` is referenced from §pre-flight step 3, so the section must exist at top-level for the anchor to resolve. |
| A8 | OIDC appendix is intentionally short (3 high-level steps) with no copy-paste SQL | Pitfall 9 | Low — if user wants a more prescriptive OIDC procedure, Phase 221 can expand or punt to a follow-up. CONTEXT.md D-03 commits to "manual procedure documented in runbook." |
| A9 | The new endpoint URL ends with a trailing slash (`/convert-saml-to-local/`) — consistent with existing admin POST routes | Pitfall 4, Pattern 1 | Low — convention; matches `admin/router.py:214 /users/{user_id}/deactivate/`. |

**Empty `Assumptions Log` would mean every claim above is verified — but A1, A2, A5, A7, A8 are intentionally left to planner discretion per CONTEXT.md Claude's Discretion. They are flagged here so the plan-checker doesn't mistake them for locked.**

## Open Questions

1. **Should the audit-log row written by the conversion include the new `password_hash`?**
   - What we know: existing `user.update` audit at `admin/router.py:200-208` calls `body.model_dump(exclude_none=True)` which would include the password if the schema had one — but `UserUpdate` does NOT have a password field, so this leak risk doesn't exist today.
   - What's unclear: should the conversion's audit `details` include `provider_slug` AND nothing password-related (recommended), or NOTHING at all (more conservative)?
   - Recommendation: `details = {"from": "saml", "to": "local", "provider_slug": <slug>}`. Never the password (in any form, hashed or not — operational principle: audit logs are read by humans, password material never appears).

2. **OIDC manual procedure SQL prescriptiveness**
   - What we know: D-03 + D-12 commit to documenting OIDC as a manual appendix.
   - What's unclear: how concrete should the SQL be?
   - Recommendation: short procedural prose only — no copy-paste SQL with concrete UUIDs. Operators tailor the procedure to their schema.

3. **Should `_cleanup_lifecycle_rows` also clean up audit_log rows written BY the conversion endpoint (the real `auth.convert_saml_to_local` row, not just the test's seeded `test.seed.lifecycle` row)?**
   - What we know: LIFECYCLE-06 test invokes the endpoint, which writes an audit_log row. Cleanup needs to handle it.
   - What's unclear: cleanup by `action = 'auth.convert_saml_to_local' AND resource_id IN (test users)` vs. cleanup by `user_id IN (test admin + test user)`.
   - Recommendation: scope cleanup by `resource_id` of the seeded test user (already known UUID); the admin's audit-log entries from the test invocation can be left intact since they have no production fingerprint.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| pytest | Test suite | ✓ | >=9.0.3 (already installed) | — |
| `lifecycle` pytest marker | Both new tests | ✓ | Registered Phase 220 (`backend/pyproject.toml:74`) | — |
| `geolens-enterprise` (sibling repo) | Round-trip test imports `register_extensions` indirectly via `EnterpriseSamlExtension` | ✓ | 0.1.0 (filesystem at `~/Code/geolens-enterprise`); CI installs via Phase 220 D-06 | None — required |
| GitHub PAT `GEOLENS_ENTERPRISE_TOKEN` | CI checkout (Phase 220 D-06) | ✓ (configured Phase 220) | — | Skip lifecycle tests on fork PRs (Phase 220 gating) |
| `hash_password` from `auth/providers/local.py` | Conversion endpoint password hashing | ✓ | already imported in admin/service.py:15 | — |
| `log_action` from `audit/service.py` | Conversion audit-log entry | ✓ | already imported in admin/router.py:31 | — |
| `require_permission("manage_users")` | Conversion endpoint auth gate | ✓ | already imported in admin/router.py:32 | — |

**Missing dependencies with no fallback:** None. Every primitive Phase 221 needs is already imported in the target files or available via CI install (Phase 220 D-06).

**Missing dependencies with fallback:** None for Phase 221's scope.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3+ with anyio_mode=auto, asyncio_mode=strict |
| Config file | `backend/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `cd backend && uv run pytest tests/test_lifecycle.py -v -m lifecycle` |
| Full suite command | `cd backend && uv run pytest -v -m 'not perf' --cov=app --cov-fail-under=58.5` |
| Doc-content check | grep block (see below) |
| Estimated runtime | ~6-10s for 3 lifecycle tests (vs. ~2s for Phase 220's single test); ~120s full backend suite |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LIFECYCLE-06 | New `POST /admin/users/{id}/convert-saml-to-local/` endpoint exists and converts SAML → local-password preserving FK-linked rows | integration test | `pytest tests/test_lifecycle.py::test_convert_saml_user_to_local_preserves_user_data -v -m lifecycle` | ❌ Wave 0 (test) |
| LIFECYCLE-06 | `docs/edition-deactivation.md` "Handling existing SAML users" section exists | doc-grep | `grep -q "## Handling existing SAML users" docs/edition-deactivation.md && grep -q "convert-saml-to-local" docs/edition-deactivation.md` | ❌ Wave 0 (doc edit) |
| LIFECYCLE-06 | Phase 220 line-81 TODO blockquote no longer present | doc-grep (negative) | `! grep "Phase 221 ships the user re-onboarding" docs/edition-deactivation.md` | ❌ Wave 0 (doc edit) |
| LIFECYCLE-06 | `docs/edition-reactivation.md` forward-pointer paragraph for converted users present | doc-grep | `grep -q -i "converted" docs/edition-reactivation.md && grep -q "edition-deactivation.md" docs/edition-reactivation.md` (already true; verify still true post-edit) | ❌ Wave 0 (doc edit) |
| LIFECYCLE-07 | Round-trip deactivate→reactivate test passes; SQL-level assertions on User, OAuthAccount, OAuthProvider columns, AuditLog row | integration test | `pytest tests/test_lifecycle.py::test_deactivate_reactivate_roundtrip_preserves_saml_data -v -m lifecycle` | ❌ Wave 0 (test) |
| LIFECYCLE-07 | Test runs in CI as part of standard backend suite (no `-m lifecycle` opt-in needed for CI) | CI integration | Workflow run shows the test in the test report; same `lifecycle` marker as Phase 220 (no addopts deselect) | ✅ already enabled (Phase 220 D-06 + marker registration) |

### Per-Requirement Validation Contract

#### LIFECYCLE-06 — Re-onboarding path (conversion endpoint + runbook)

**Acceptance criteria from CONTEXT.md / SC#1, SC#2:**

1. `POST /admin/users/{user_id}/convert-saml-to-local/` exists.
2. Conversion converts a SAML-authenticated user to local-password.
3. Conversion preserves audit history, group memberships, and dataset ownership.
4. `docs/edition-deactivation.md` includes a "Handling existing SAML users" section linking to admin tooling.

**Concrete test assertions (`test_convert_saml_user_to_local_preserves_user_data`):**

| # | Assertion | What it verifies |
|---|-----------|------------------|
| 1 | `response.status_code == 200` | Endpoint exists and accepts the request |
| 2 | `response.json()["auth_provider"] == "local"` | auth_provider correctly flipped |
| 3 | `users.id` UNCHANGED post-conversion (same UUID before/after) | D-06: durable user handle |
| 4 | `users.password_hash IS NOT NULL` post-conversion | Local-password set |
| 5 | `users.auth_provider == 'local'` in DB (not just response) | DB-level mutation |
| 6 | `oauth_accounts` row for (user_id, saml_provider_id) DELETED | D-04: clean break |
| 7 | `oauth_providers` row for the SAML provider PRESERVED | D-04: provider stays for other users |
| 8 | Pre-conversion `user_roles` row preserved with same user_id | LIFECYCLE-06 "group memberships" |
| 9 | Pre-conversion `audit_log` seed row preserved with same user_id (FK survival) | LIFECYCLE-06 "audit history" |
| 10 | (Optional but recommended) Pre-conversion `datasets.created_by` preserved with same user_id | LIFECYCLE-06 "dataset ownership" |
| 11 | Post-conversion `audit_log` row exists with `action='auth.convert_saml_to_local'`, `resource_id=user.id`, `details.provider_slug == <slug>` | D-05: audit-log entry written by endpoint |
| 12 | Self-conversion (current_user.id == user_id) returns 422 | Self-lockout guard (Pitfall 7) |
| 13 | Non-SAML user (e.g., already local) returns 422 | D-05 validation |
| 14 | Non-existent user returns 404 | D-05 not-found mapping |

**Doc-grep assertions (LIFECYCLE-06 SC#2):**

```bash
# Section exists at top-level
grep -q '^## Handling existing SAML users' docs/edition-deactivation.md
# Endpoint URL referenced in runbook
grep -q '/admin/users/.*/convert-saml-to-local' docs/edition-deactivation.md
# Curl example uses the trailing slash (Pitfall 4)
grep -q 'convert-saml-to-local/' docs/edition-deactivation.md
# Phase 220 TODO marker GONE
! grep -q 'Phase 221 ships the user re-onboarding' docs/edition-deactivation.md
! grep -q 'manually via the admin UI' docs/edition-deactivation.md
# OIDC appendix referenced
grep -q -i 'oidc' docs/edition-deactivation.md
# Audit-log preservation language present
grep -q -i 'audit' docs/edition-deactivation.md
# Forward-pointer in reactivation doc
grep -q -i 'converted' docs/edition-reactivation.md
grep -q 'edition-deactivation' docs/edition-reactivation.md
```

#### LIFECYCLE-07 — Round-trip symmetry test

**Acceptance criteria from CONTEXT.md / SC#3:**

1. CI test (`pytest -m lifecycle`) exercises deactivate → reactivate round-trip.
2. Asserts User identities intact.
3. Asserts `oauth_providers` rows intact.
4. Asserts audit trail entries intact.

**Concrete test assertions (`test_deactivate_reactivate_roundtrip_preserves_saml_data`):**

| # | Assertion | What it verifies |
|---|-----------|------------------|
| 1 | Mid-cycle: `is_enterprise() is False` after deactivate phase | Three module-level surfaces all reset (Pitfall 1) |
| 2 | Post-cycle: `is_enterprise() is True` after reactivate phase | Three module-level surfaces all re-populated symmetrically |
| 3 | `oauth_providers` row queryable post-cycle; provider_type still 'saml' | LIFECYCLE-07 "oauth_providers rows intact" |
| 4 | All 4 deferred SAML columns (`idp_entity_id`, `idp_sso_url`, `idp_certificate`, `sp_entity_id`) retain their seeded values via `undefer_group("saml")` | LIFECYCLE-07 "deferred=True SAML columns round-trip losslessly" |
| 5 | `oauth_accounts` linkage row queryable post-cycle | LIFECYCLE-07 implicit (linkage is part of "intact") |
| 6 | `users` row queryable post-cycle; `auth_provider == 'oauth'` (unchanged) | LIFECYCLE-07 "User identities intact" |
| 7 | Seeded `audit_log` row queryable post-cycle; `user_id == seeded_user.id` | LIFECYCLE-07 "audit trail entries intact" — D-10 real assertion, not vacuous |
| 8 | `get_auth_extension()` returns `EnterpriseSamlExtension` post-reactivation (not Default*) | Re-population restored typed accessors (symmetry with Phase 220 deactivate-side accessor assertion) |

**CI integration check:**

```bash
# Marker registered (Phase 220 inheritance)
grep -q '"lifecycle:' backend/pyproject.toml
# Phase 220 CI overlay install still in place
grep -q 'geolens-enterprise' .github/workflows/ci.yml
grep -q -E 'GEOLENS_ENTERPRISE_TOKEN|secrets.GEOLENS' .github/workflows/ci.yml
# Three lifecycle tests collected
cd backend && uv run pytest tests/test_lifecycle.py --collect-only -m lifecycle | grep -c "test_"  # expect: 3
```

### Sampling Rate
- **Per task commit:** `cd backend && uv run pytest tests/test_lifecycle.py -v -m lifecycle` (~6-10s)
- **Per wave merge:** Full backend suite + doc-grep block
- **Phase gate:** Full suite green + every doc-grep assertion green + CI workflow run green on a real PR (not just push, per project memory `feedback_ci_local_first.md` + `project_geolens_io_actions_billing.md`)
- **Max feedback latency:** 120 seconds

### Wave 0 Gaps

- [ ] `backend/app/modules/admin/schemas.py` — add `SamlToLocalConversion` class (LIFECYCLE-06)
- [ ] `backend/app/modules/admin/service.py` — add `AdminService.convert_saml_user_to_local()` method (LIFECYCLE-06)
- [ ] `backend/app/modules/admin/router.py` — add `POST /admin/users/{id}/convert-saml-to-local/` route (LIFECYCLE-06)
- [ ] `backend/tests/test_lifecycle.py` — add `test_convert_saml_user_to_local_preserves_user_data` (LIFECYCLE-06)
- [ ] `backend/tests/test_lifecycle.py` — add `test_deactivate_reactivate_roundtrip_preserves_saml_data` (LIFECYCLE-07)
- [ ] `backend/tests/test_lifecycle.py` — extend `_cleanup_lifecycle_rows` for audit_log + user_roles + datasets cleanup
- [ ] `docs/edition-deactivation.md` — replace line-81 TODO blockquote with "Handling existing SAML users" section (LIFECYCLE-06)
- [ ] `docs/edition-reactivation.md` — insert forward-pointer paragraph for converted users (LIFECYCLE-06)

*(No framework install needed; no CI workflow change; no new pytest marker. All inherited from Phase 220.)*

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | bcrypt via `pwdlib + BcryptHasher` (existing project standard at `auth/providers/local.py:16-21`); `min_length=8` on the conversion password (matches existing `AdminUserCreate.password`) |
| V3 Session Management | yes (transitive) | Conversion endpoint requires admin JWT via `require_permission("manage_users")`; existing JWT lifecycle is untouched |
| V4 Access Control | yes | Endpoint gated by `require_permission("manage_users")`; self-conversion guard (Pitfall 7) prevents admin self-lockout fat-finger |
| V5 Input Validation | yes | Pydantic `SamlToLocalConversion` schema enforces `min_length=8`, `max_length=256`; `user_id` is path-typed as `uuid.UUID` (FastAPI rejects non-UUID input with 422 automatically) |
| V6 Cryptography | yes | bcrypt for password hashing (existing standard); Fernet for `idp_certificate` at-rest (existing standard, untouched) |
| V7 Error Handling & Logging | yes | Audit-log entry written via existing `log_action()`; `details` field intentionally excludes the new password (Open Question 1 confirms) |
| V8 Data Protection | yes | The new password is never logged (audit_log `details` carries only `{"from": "saml", "to": "local", "provider_slug": ...}`) |
| V9 Communication | n/a | No new network surface beyond the existing admin endpoint pattern |
| V14 Configuration | n/a | No new env var or config |

### Known Threat Patterns for {admin endpoint + auth conversion}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Admin self-lockout (fat-finger password) | Denial of Service | Self-conversion guard (Pitfall 7) — 422 when `current_user.id == user_id` |
| SAML login race during conversion | Tampering / Repudiation | Runbook ordering: convert AFTER overlay removed (Pitfall 8); `/auth/saml/*` returns 404 mid-conversion |
| Password leakage via audit-log details | Information Disclosure | Audit `details` MUST exclude password material; explicit allow-list `{"from", "to", "provider_slug"}` (Open Question 1) |
| Lower-privileged user converts other admin | Elevation of Privilege | `require_permission("manage_users")` already gates admin-only access |
| Replay of conversion request | Repudiation | Audit_log row records `user_id` (admin), `resource_id` (target user), `ip_address`, `created_at` — the standard repudiation defense matches existing `user.update`, `user.deactivate` patterns |
| Conversion of non-SAML user (e.g., local user) accidentally clears their password | Tampering | Pre-flight check rejects non-SAML users with 422 (D-05) — endpoint MUST NOT silently set password on a non-SAML user |
| `auth_provider` CHECK constraint violation | Tampering | `chk_users_auth_provider` admits `'local'` (verified at `auth/models.py:25-28`); flip is safe |
| Partial conversion leaving inconsistent state | Tampering / Integrity | Single transaction (D-05); failure of any step rolls back all five |

## Project Constraints (from CLAUDE.md)

- **Version control:** Never indicate AI/Bot activity in commit messages.
- **Code style:** Prefer simple, readable code over clever abstractions; follow existing project conventions.
- **Communication:** Be direct and concise; skip preamble.
- **Project context (from MEMORY.md):**
  - Backend FastAPI + PostGIS; v13.2 in progress (Phase 220 shipped, Phase 221 next).
  - v13.1 SAML implementation is ground truth.
  - **FastAPI trailing slashes:** Routes defined with `"/"` cause 307 redirects when called without trailing slash. Use `/convert-saml-to-local/` (Pitfall 4).
  - **Auth login endpoint:** `/auth/login/` (form-data), NOT `/auth/token` (Pitfall 5).
  - **Audit sibling repo at milestone close:** Phase 221 closes v13.2 — verify `~/Code/geolens-enterprise/` for unpushed commits before declaring milestone complete (per `feedback_audit_sibling_repos_at_milestone_close.md`).
  - **Run CI locally first:** Run lint/typecheck/tests locally before pushing; prefer PR path for time-sensitive verification because free-tier Actions minutes are routinely exhausted (per `feedback_ci_local_first.md` + `project_geolens_io_actions_billing.md`).
  - **No blanket `git add -fA .planning/`:** Add `.planning/phases/221-*/` files individually (per `feedback_no_blanket_add_planning.md`).
  - **No emojis** in committed files (per global communication rule).
  - **Fix review findings inline** when running `/gsd-quick --full` — surface every reviewer finding and default to fixing all inline before finalizing (per `feedback_review_findings_inline.md`).

## Sources

### Primary (HIGH confidence)
- [VERIFIED: backend/app/modules/admin/router.py:1-405] User CRUD route patterns (lines 168-373); `log_action` import (line 31); `require_permission` import (line 32); `_user_response` helper (lines 48-59).
- [VERIFIED: backend/app/modules/admin/service.py:1-425] `AdminService.update_user` method (lines 114-172); `hash_password` import (line 15); `delete()` ORM patterns (lines 166, 280).
- [VERIFIED: backend/app/modules/admin/schemas.py:1-276] `AdminUserCreate.password` pattern (lines 17-43); `UserUpdate` minimal-field pattern (lines 60-80).
- [VERIFIED: backend/app/modules/auth/providers/local.py:1-74] `hash_password` definition (lines 24-26); bcrypt via pwdlib.
- [VERIFIED: backend/app/modules/audit/service.py:1-159] `log_action` signature + transaction-semantics (lines 49-67) — adds row, does NOT commit.
- [VERIFIED: backend/app/modules/audit/models.py:1-35] `AuditLog.user_id` FK with `ondelete=SET NULL` (lines 22-23) — conversion does NOT delete user, so FK survives.
- [VERIFIED: backend/app/modules/auth/models.py:18-55] `User.auth_provider` column + `chk_users_auth_provider` CHECK admits `'local'` (line 26-28).
- [VERIFIED: backend/app/modules/auth/oauth/models.py:22-122] `OAuthProvider` (4 deferred SAML columns lines 67-78); `OAuthAccount` linkage (lines 95-122).
- [VERIFIED: backend/app/modules/auth/router.py:344-384] `change_password` audit pattern — same `log_action` shape Phase 221's endpoint follows.
- [VERIFIED: backend/app/modules/auth/oauth/service.py:183-280] `find_or_create_oauth_user` JIT-create flow — race-window context (Pitfall 8).
- [VERIFIED: backend/app/modules/catalog/datasets/domain/models.py:121-126] `Dataset.created_by` / `Dataset.updated_by` FK with `ondelete=SET NULL` — conversion does NOT delete user, ownership survives.
- [VERIFIED: backend/tests/test_lifecycle.py:1-235] Phase 220 test in full — pattern for seed phase, three module-level resets, cleanup fixture, edition save/restore.
- [VERIFIED: backend/tests/test_saml_overlay.py:96-137,222-277] `_seed_saml_provider` helper; `init_edition` save/restore precedent.
- [VERIFIED: backend/tests/conftest.py:328-395,454-484] `get_auth_header`, `_create_test_user`, `admin_auth_header`, `test_db_session`, `saml_overlay_registered`.
- [VERIFIED: backend/tests/test_admin_user_operations.py:1-120] Admin endpoint TestClient pattern — TestClient + `admin_auth_header` invocation shape.
- [VERIFIED: backend/pyproject.toml:65-76] Pytest config; `lifecycle` marker registered (line 74); `addopts = "-m 'not perf'"` (line 70 — does NOT exclude lifecycle).
- [VERIFIED: backend/app/modules/audit/{__init__,models,router,schemas,service}.py listing] No central audit-action enum/catalog file exists — D-14 ships action as string literal.
- [VERIFIED: ~/Code/geolens-enterprise/geolens_enterprise/__init__.py:1-67] `register_extensions()` shape; `_get_saml_extension`, `_get_audit_extension`, `_get_branding_extension`, `_get_routers` factory functions.
- [VERIFIED: docs/edition-deactivation.md:1-187] Existing structure; line-81 TODO blockquote; pre-flight inventory SQL (lines 62-77); destructive-path section (lines 144-177).
- [VERIFIED: docs/edition-reactivation.md:1-76] Existing structure; placement reference for forward-pointer.
- [VERIFIED: .planning/phases/221-lifecycle-user-continuity-and-verification/221-CONTEXT.md] Locked decisions D-01..D-14 + Claude's Discretion.
- [VERIFIED: .planning/phases/220-lifecycle-runbooks-and-preservation/220-CONTEXT.md, 220-RESEARCH.md, 220-PATTERNS.md, 220-VALIDATION.md] Inherited pitfalls (1-8), patterns (registry-clear, fixture reuse), assertion contract.
- [VERIFIED: .planning/REQUIREMENTS.md] LIFECYCLE-06 + LIFECYCLE-07 text.
- [VERIFIED: .planning/ROADMAP.md] Phase 221 SC#1, SC#2, SC#3.
- [VERIFIED: .planning/STATE.md] Phase 221 next; Phase 220 shipped.
- [VERIFIED: ls /Users/ishiland/Code/geolens-enterprise/geolens_enterprise/] `audit/`, `auth/`, `branding/`, `migrations/` subdirectories — confirms `register_extensions()` populates 3 extension keys (auth, identity, audit, branding) via the factory functions.

### Secondary (MEDIUM confidence)
- [CITED: project memory `feedback_audit_sibling_repos_at_milestone_close.md`] — relevant when Phase 221 closes v13.2; verify enterprise repo for unpushed commits.
- [CITED: project memory FastAPI trailing slashes note] — Pitfall 4.
- [CITED: project memory `feedback_ci_local_first.md` + `project_geolens_io_actions_billing.md`] — Pitfall: prefer PR path; run tests locally first.

### Tertiary (LOW confidence — none)
- No tertiary sources required; all claims trace to verified code, official documentation, or explicit CONTEXT.md decisions.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new deps; every primitive is already imported or available via Phase 220 inheritance.
- Endpoint design: HIGH — Pattern 1 mirrors `deactivate_user` shape verbatim; ValueError-to-HTTPException mapping is project standard.
- Service method: HIGH — Pattern 2 mirrors `update_user` shape; `delete(OAuthAccount)` matches existing `delete(UserRole)`/`delete(ApiKey)` patterns.
- Round-trip test: HIGH — Pattern 3 Shape A mirrors `saml_overlay_registered` fixture verbatim; the only divergence (Shape B's `register_extensions()`-direct vs. Shape A's manual ext + router.append) is documented and the recommended path matches the trusted fixture pattern.
- Pitfalls: HIGH — Pitfalls 1-3 inherit from Phase 220 RESEARCH; Pitfalls 4-9 are net-new but every claim traces to verified code or project memory.
- Documentation patterns: MEDIUM — only `docs/saml.md` + Phase 220's runbooks available as substantive style references; new "Handling existing SAML users" section is net-new operator content.
- Audit-log catalog: HIGH — verified absent (no `actions.py` enum exists); D-14 action shipped as string literal is correct.

**Research date:** 2026-04-30
**Valid until:** 2026-05-30 (30 days — stable surface; no fast-moving dependencies. Re-verify if `geolens-enterprise.register_extensions()` shape changes or if the audit module gains a central action-name catalog.)

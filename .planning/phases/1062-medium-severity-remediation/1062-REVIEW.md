---
status: fixed
fixed_date: 2026-05-20
resolution: "All 4 critical + 5 warning findings fixed inline; see REVIEW-FIX.md for commit list. 3 info deferred."
phase: 1062
review_date: 2026-05-20
depth: standard
files_reviewed: 25
files_reviewed_list:
  - backend/app/modules/auth/dependencies.py
  - backend/app/modules/auth/models.py
  - backend/app/modules/auth/password_policy.py
  - backend/app/modules/auth/router.py
  - backend/app/modules/auth/schemas.py
  - backend/app/modules/auth/service.py
  - backend/app/modules/admin/schemas.py
  - backend/app/modules/admin/router.py
  - backend/app/modules/admin/service.py
  - backend/alembic/versions/0019_users_token_version.py
  - backend/alembic/versions/0020_records_simple_search_vector_idx.py
  - backend/app/modules/catalog/search/router.py
  - backend/app/modules/catalog/search/service_filters.py
  - backend/app/modules/catalog/datasets/api/router_data.py
  - backend/app/modules/settings/router.py
  - backend/app/core/persistent_config.py
  - backend/app/modules/catalog/maps/router.py
  - backend/app/modules/catalog/maps/service_public.py
  - backend/app/api/middleware/security.py
  - backend/app/processing/export/where_validator.py
  - backend/app/processing/export/service.py
  - backend/app/core/config.py
  - frontend/eslint.config.js
  - frontend/nginx.conf
  - .env.example
findings:
  critical: 4
  warning: 5
  info: 3
  total: 12
---

# Phase 1062 Code Review

**Reviewed:** 2026-05-20T00:00:00Z
**Depth:** standard
**Files Reviewed:** 25
**Status:** findings_found

## Summary

Phase 1062 delivers nine MEDIUM-severity security remediations: JWT revocation
via `token_version` (SEC-S15), password complexity policy (SEC-S16), rate limits
on embedding/basemap endpoints (SEC-S10/S11), FTS simple-regconfig GIN index
(SEC-S12), a `max_length` guard on the search `q` param (SEC-S13), an AST-based
WHERE-clause validator (SEC-S09), embed CSP via `frame-ancestors` (SEC-S08),
and an ESLint rule banning `localStorage.setItem` for token-shaped keys (SEC-S14).

The implementations are generally sound. Four blockers and five warnings are
flagged below. The most serious issues are: (1) the `change_password` route calls
`revoke_all_tokens` which internally commits the session, then mutates
`current_user.password_hash` and calls `audit_emit` after that commit — meaning
the password hash mutation and audit row can end up committed in a second
transaction that has no relationship to the revocation, with an ordering that
leaves an observability gap; (2) the SAML-to-local conversion never bumps
`token_version`, leaving any outstanding access JWTs for the converted user valid
until they expire naturally; (3) the `_update_sync_cache` helper in
`persistent_config.py` only warms the sync cache for `login_rate_limit` and
`global_rate_limit`, so the two new knobs `semantic_search_rate_limit` and
`basemap_proxy_rate_limit` never populate from DB overrides at runtime; and (4)
the `EmbedToken.expires_at > func.now()` predicate in `service_public.py` will
return no rows (empty CSP) when the EmbedToken has no expiry (NULL), silently
reverting to `frame-ancestors 'self'` for non-expiring embed tokens.

---

## Critical Issues

### CR-01: `change_password` — password hash mutation happens after `revoke_all_tokens` commits, creating a two-transaction ordering hazard

**File:** `backend/app/modules/auth/router.py:425-446`

**Issue:** `revoke_all_tokens` issues its own `await self.db.commit()` internally
(see `service.py:216`). The caller then mutates `current_user.password_hash` and
calls `audit_emit` on the same session object. Those writes land in a second
implicit transaction that the comment at line 444 tries to acknowledge
("Note: revoke_all_tokens already commits; this commit handles the password_hash
mutation..."). The ordering is dangerous:

1. Token revocation + `token_version` bump → committed (transaction 1).
2. Any request arriving between commit 1 and commit 2 with the old access JWT
   will see the bumped `token_version` and be rejected — correct — but the user's
   password is unchanged. A server crash between commit 1 and commit 2 leaves the
   user with a bumped `token_version` (all old tokens rejected) but the **old
   password unchanged**. The user is then locked out until an admin intervenes,
   because their old tokens are all invalid and their password was never updated.

The design intent should be: bump the password hash atomically with revocation,
not after. The fix is to avoid the mid-function commit in `revoke_all_tokens` by
splitting the revocation logic so the caller controls the single commit.

**Fix:** Move the password hash assignment before calling `revoke_all_tokens`,
and refactor `revoke_all_tokens` to accept an optional `commit=False` parameter
(or use the already-present `revoke_all_refresh_tokens` + a separate
`token_version` bump that does not commit). The simplest safe approach:

```python
# In change_password route:
current_user.password_hash = hash_password(body.new_password)

# Revoke refresh tokens inline (no intermediate commit)
await db.execute(
    update(RefreshToken)
    .where(RefreshToken.user_id == current_user.id, RefreshToken.revoked == False)
    .values(revoked=True)
)
await db.execute(
    update(User)
    .where(User.id == current_user.id)
    .values(token_version=User.token_version + 1)
)

ip = get_client_ip(request)
await audit_emit(db, AuditEvent(...))
await db.commit()  # single commit: password + revocation + audit
```

---

### CR-02: SAML-to-local conversion does not bump `token_version`

**File:** `backend/app/modules/admin/service.py:185-255`  
**File:** `backend/app/modules/admin/router.py:266-328`

**Issue:** `convert_saml_user_to_local` sets a new `password_hash` and flips
`auth_provider` to `"local"`, but never touches `User.token_version`. A SAML
user who had an active access JWT at the moment of conversion continues to hold a
valid JWT until it expires (default 15 minutes). This is a gap in SEC-S15 because
the audit requirement document explicitly lists SAML-to-local conversion as a
password-set entry point that should force re-auth. The schema (SEC-S16) and doc
comment in `password_policy.py:7-9` both name this endpoint.

**Fix:** Add a `token_version` bump in `AdminService.convert_saml_user_to_local`:

```python
# After step 4 (setting password_hash):
user.password_hash = hash_password(password)
user.auth_provider = "local"

# SEC-S15: bump token_version so the SAML JWT is rejected on next request.
await self.db.execute(
    update(User)
    .where(User.id == user_id)
    .values(token_version=User.token_version + 1)
)

# Also revoke any refresh tokens (belt-and-suspenders).
await self.db.execute(
    update(RefreshToken)
    .where(RefreshToken.user_id == user_id, RefreshToken.revoked == False)
    .values(revoked=True)
)
```

The router already controls the commit, so no commit is needed inside the service.

---

### CR-03: `_update_sync_cache` never populates `semantic_search_rate_limit` or `basemap_proxy_rate_limit`, so DB-overridden values are never applied at runtime

**File:** `backend/app/core/persistent_config.py:277-280`

**Issue:** The `_update_sync_cache` hook that feeds `get_cached_semantic_search_rate_limit()` and `get_cached_basemap_proxy_rate_limit()` is wired for `"login_rate_limit"` and `"global_rate_limit"` only:

```python
def _update_sync_cache(self, value: Any) -> None:
    if self.key in ("login_rate_limit", "global_rate_limit"):   # ← only 2 keys
        _sync_rate_limit_cache[self.key] = (value, time.monotonic())
```

The two new rate limit configs (`SEMANTIC_SEARCH_RATE_LIMIT` at key `"semantic_search_rate_limit"` and `BASEMAP_PROXY_RATE_LIMIT` at key `"basemap_proxy_rate_limit"`) are never added to `_sync_rate_limit_cache`. As a result:

- `get_cached_semantic_search_rate_limit()` always returns `_DEFAULT_SEMANTIC_SEARCH_RATE_LIMIT` (30).
- `get_cached_basemap_proxy_rate_limit()` always returns `_DEFAULT_BASEMAP_PROXY_RATE_LIMIT` (120).

Changing the limits via the Admin UI writes them to the DB but slowapi's callable
never picks up the new values — the rate limits are permanently stuck at their
defaults even after an admin changes them.

**Fix:** Extend `_update_sync_cache` to include the two new keys:

```python
def _update_sync_cache(self, value: Any) -> None:
    if self.key in (
        "login_rate_limit",
        "global_rate_limit",
        "semantic_search_rate_limit",
        "basemap_proxy_rate_limit",
    ):
        _sync_rate_limit_cache[self.key] = (value, time.monotonic())
```

---

### CR-04: `EmbedToken.expires_at > func.now()` excludes non-expiring embed tokens, silently defaulting to `frame-ancestors 'self'`

**File:** `backend/app/modules/catalog/maps/service_public.py:263-274`

**Issue:** The query that fetches `allowed_origins` for the CSP header is:

```python
embed_stmt = (
    select(EmbedToken.allowed_origins)
    .where(
        EmbedToken.map_id == token_obj.map_id,
        EmbedToken.is_active == True,
        EmbedToken.expires_at > func.now(),   # ← NULLs fail this comparison
    )
    ...
)
```

In PostgreSQL, `NULL > now()` evaluates to `NULL` (falsy). An `EmbedToken` with
`expires_at IS NULL` (non-expiring, which is the community-edition default) will
be filtered out by this WHERE clause. The result is that `allowed_origins` is
`None` (no row returned), and `_build_frame_ancestors(None)` returns
`"frame-ancestors 'self'"` — the most restrictive default. This silently breaks
embed framing for any map using a non-expiring embed token.

**Fix:** Handle the NULL case explicitly:

```python
.where(
    EmbedToken.map_id == token_obj.map_id,
    EmbedToken.is_active == True,
    or_(
        EmbedToken.expires_at.is_(None),
        EmbedToken.expires_at > func.now(),
    ),
)
```

---

## Warnings

### WR-01: `validate_where_ast` allows `exp.Neg` but has no allowlist entry for `exp.Add`, `exp.Sub`, `exp.Mul`, `exp.Div` — arithmetic in `IN` lists reaches the column-name checker instead

**File:** `backend/app/processing/export/where_validator.py:59`

**Issue:** The allowlist includes `exp.Neg` (unary minus, e.g. `-5`) but excludes
all binary arithmetic operators. This means `WHERE x IN (-5, 3)` passes (negation
OK), but `WHERE x = 2 + 3` would be blocked at the AST level (the `exp.Add`
node is not allowed). This is the correct security behaviour. However the
allowlist comment says "unary minus (e.g. -5)" without documenting why binary
arithmetic is excluded — a future maintainer might add `exp.Add` by analogy with
`exp.Neg`, inadvertently allowing `WHERE 1=1 UNION SELECT ...`-style expression
tricks. This is a maintenance risk worth a guard comment.

Also: `exp.Dot` (table-qualified column like `table.column`) is not in the
allowlist, so references like `schema.table.column` or table-prefixed columns
will be rejected by the AST validator even if the identifier regex below would
pass them. This is likely intentional (single unqualified column names only), but
should be documented.

**Fix:** Add an explicit comment in `ALLOWED_EXPRESSIONS`:

```python
# Arithmetic operators are intentionally EXCLUDED. Adding exp.Add/Sub/Mul/Div
# would allow expression injection into IN-list or comparison arguments.
# exp.Neg is included only for negative literal values like WHERE col = -5.
#
# exp.Dot is intentionally EXCLUDED. Only unqualified column names are accepted;
# table.column or schema.table.column forms are rejected at the AST level.
```

---

### WR-02: `facets/` endpoint rate-limited under `_semantic_search_rate_limit` even when no semantic/embedding path is invoked

**File:** `backend/app/modules/catalog/search/router.py:537`

**Issue:** `search_facets_endpoint` is decorated with `@limiter.limit(_semantic_search_rate_limit)` (30/min). The facets endpoint computes record-type counts and never invokes an embedding model — it is a pure SQL aggregation. Applying the embedding cost-limit (SEC-S11) to a non-embedding endpoint silently restricts legitimate users. A user refreshing the search UI 30 times per minute (normal SPA behaviour) gets rate-limited on facets even without a text query.

The intent of SEC-S11 is to cap embedding API calls, not all search activity. The correct endpoints to rate-limit are those that trigger an embedding: `/search/datasets/` (when `q` is non-empty) and `/datasets/{id}/related/`.

**Fix:** Remove the `@limiter.limit(_semantic_search_rate_limit)` decorator from `search_facets_endpoint`, or apply a separate (higher) limit appropriate for a non-embedding endpoint.

---

### WR-03: `change_password` route validation gap — `ChangePasswordRequest` has `min_length=8` field floor but `validate_new_password` calls `validate_password_from_settings` (default min 12), yet the field description says "policy: min 12 chars"

**File:** `backend/app/modules/auth/schemas.py:134-144`

**Issue:** This is a documentation accuracy concern that could mislead future maintainers. The field is annotated `min_length=8` (the floor) but the docstring says "policy: min 12 chars". While the runtime policy wins (the validator raises at 12), someone reading the Pydantic schema / OpenAPI doc will see `minLength: 8`, not 12. The mismatch between the OpenAPI schema and the actual enforced minimum could cause clients (automated or human) to generate passwords that pass schema validation but fail the route validator with a 422 they didn't anticipate.

The `UserCreate` schema in `auth/schemas.py:28-37` has the same pattern with a similar comment acknowledging the intentional floor, but the field description on `ChangePasswordRequest.new_password` (line 135) says only `min_length=1` on `current_password`, and the `new_password` field description is absent — there is no description string at all, making the field opaque in the OpenAPI docs.

**Fix:** Add an explicit description to `ChangePasswordRequest.new_password` matching the policy:

```python
new_password: str = Field(
    min_length=8,
    max_length=256,
    description="New password (policy: min 12 chars, 3+ character classes)",
)
```

---

### WR-04: `service.py:57` — `token_version: int = result.scalar_one_or_none() or 1` coerces DB value of `0` to `1`

**File:** `backend/app/modules/auth/service.py:57`

**Issue:** The line:

```python
token_version: int = result.scalar_one_or_none() or 1
```

The `or 1` fallback handles the `None` case (user not found), which is correct. However, it also handles `0` as falsy — any user row with `token_version = 0` in the DB would have their JWT issued with `token_version = 1` instead of `0`. In normal operation this cannot happen because the migration's `server_default="1"` ensures all rows start at 1. But if a manual DB intervention sets a user's `token_version` to 0, the token issued would have `version=1` while the DB stores `0`, and since `1 >= 0` (validator: `jwt_version < user.token_version`), the token would be accepted — no harm. The more dangerous case is the reverse: if `scalar_one_or_none()` returns `None` because the user row disappeared between the login check above (line 78-90) and this query (a TOCTOU window), the token is issued with `version=1` for a non-existent user — but that token would be rejected by the next `get_current_user` call anyway.

The risk is low but the intent is ambiguous. The correct guard is:

```python
token_version: int = result.scalar_one_or_none()
if token_version is None:
    # User disappeared; token issuance should not proceed, but
    # we can't raise here without restructuring. Use 1 as safe default.
    token_version = 1
```

Or more concisely:

```python
token_version: int = result.scalar_one_or_none() if result.scalar_one_or_none() is not None else 1
```

At minimum, replace `or 1` with an explicit `None` check to make intent clear.

---

### WR-05: nginx `/m/.+` location regex does not match the bare path `/m/` (token exactly empty), but more importantly re-declares no `X-Frame-Options` while the global scope adds `SAMEORIGIN`, creating a browser-observable inconsistency between `/m/` (gets SAMEORIGIN via server scope fallback) and `/m/<non-empty>` (gets no XFO)

**File:** `frontend/nginx.conf:137-142`

**Issue:** The `location ~ ^/m/.+` regex requires at least one character after
`/m/`. The path `/m/` (slash, then nothing) falls through to `location /`, which
inherits the global `add_header X-Frame-Options "SAMEORIGIN"`. This is an edge
case (no real share token is the empty string) but represents a divergence from
the intended SEC-S08 design where `/m/*` routes omit XFO.

Additionally, while the comment block explains nginx inheritance semantics
correctly, the current `location ~ ^/m/.+` block does not carry a `try_files`
fallback — it does, at line 141 (`try_files $uri /index.html`). This is correct.

The bigger concern is that `location /` uses the server-scope `X-Frame-Options:
SAMEORIGIN`, which is **more permissive** than the API's `X-Frame-Options: DENY`
(from `SecurityHeadersMiddleware`). For SPA routes that are NOT `/m/*`, the nginx
layer allows same-origin framing but the API layer denies all framing — these are
different layers serving different content, so the inconsistency is likely
intentional, but it should be documented.

**Fix:** Change the regex to `~ ^/m/` to catch `/m/` as well, and add a comment
that the `X-Frame-Options: SAMEORIGIN` on the server scope is intentional for SPA
routes (the browser SPA never renders in an iframe; only `/m/*` embed paths are
expected to be framed):

```nginx
location ~ ^/m/ {
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    # X-Frame-Options intentionally omitted — see SEC-S08 comment above.
    try_files $uri /index.html;
}
```

---

## Informational

### IN-01: `.env.example` missing `PASSWORD_MIN_LENGTH` and `PASSWORD_REQUIRE_CLASSES` env var documentation

**File:** `.env.example`

**Issue:** SEC-S16 introduces two new configurable env vars (`PASSWORD_MIN_LENGTH`
and `PASSWORD_REQUIRE_CLASSES`). Both are referenced in `config.py` (confirmed)
and in `password_policy.py`'s module docstring, but neither appears in `.env.example`.
Operators discovering the password policy for the first time have no canonical
reference for how to tune these values. The file documents every other env var.

**Fix:** Add to the Authentication section:

```bash
# Minimum password length enforced at all entry points (register, change-password,
# admin create, SAML-to-local). Default is 12 (NIST SP 800-63B minimum).
# SEC-S16 (Phase 1062-01)
# Type: integer | Default: 12
# PASSWORD_MIN_LENGTH=12

# Number of character classes required in passwords (1–4: lower, upper, digit, symbol).
# Type: integer | Default: 3
# PASSWORD_REQUIRE_CLASSES=3
```

---

### IN-02: `validate_password_complexity` includes whitespace as a "symbol" character class

**File:** `backend/app/modules/auth/password_policy.py:52`

**Issue:** The symbol class definition:

```python
has_symbol = any(not c.isalpha() and not c.isdigit() for c in password)
```

...counts whitespace (space, tab, newline) as a symbol. A password consisting of
12 lowercase letters plus a space (`"aaaaaaaaaaa "`) would satisfy `has_lower=True`
and `has_symbol=True` — only 2 classes, so it fails the default `require_classes=3`
check correctly. But `"aaaaaaaaaaaa "` (12 lowercase + space = 13 chars) also only
reaches 2 classes. The comment says "punctuation, whitespace, Unicode non-letter/digit
chars" — so whitespace is intentionally counted. This is consistent with most NIST
guidance. However the user-facing error message does not mention whitespace:

```
"Password must include at least 3 of: lowercase, uppercase, digit, symbol"
```

A user who enters a password with spaces expecting them to count as "symbol" would
be confused if the password still fails (e.g., all-lowercase + space). The message
should clarify that whitespace counts as a symbol.

**Fix:** Update the error message:

```python
raise ValueError(
    f"Password must include at least {require_classes} of: "
    "lowercase letters, uppercase letters, digits, symbols (including spaces)"
)
```

---

### IN-03: `where_validator.py` has no test for the `exp.Dot` (table-qualified column) bypass path

**File:** `backend/app/processing/export/where_validator.py`

**Issue:** A WHERE clause like `"t.column = 1"` would be rejected by the AST
validator (because `exp.Dot` is not in `ALLOWED_EXPRESSIONS`), but the regex
identifier extractor (`_IDENTIFIER_RE`) in `service.py` would extract both `t`
and `column` as separate identifiers. If `t` happens to match a column name in
the dataset's `column_info`, the second defense layer (identifier check) would
accept it. This is a defense-in-depth inconsistency rather than an injection
vector (the AST validator runs first and would block the expression), but the
test suite should cover it.

**Fix:** Add a test case for `validate_where_clause("t.column = 1", [...])` that
asserts a `ValueError` is raised (the AST gate rejects the Dot node before the
identifier check runs).

---

## Test Coverage Assessment

The authentication changes (SEC-S15/S16) touch all four password-entry points in
the schema layer. The `revoke_all_tokens` path is exercised by the logout route
but the `change_password` double-commit ordering is not tested for the crash-window
scenario (CR-01). The SAML-to-local conversion test in `backend/tests/test_lifecycle.py`
should be extended to assert that an access JWT issued before the conversion is
rejected after it completes (CR-02).

The WHERE validator has no explicit test file referenced in the review scope;
the `_IDENTIFIER_RE` / `validate_where_clause` path deserves tests for injection
bypass attempts (table-qualified names, semicolon injection, comment injection).

The embed CSP path (CR-04) is not covered by a test that creates a non-expiring
`EmbedToken` and asserts the `frame-ancestors` header contains the `allowed_origins`.

---

## Recommendations

1. **CR-01** (critical): Restructure `change_password` to do a single-commit path
   — move `current_user.password_hash` assignment before the revocation, and
   change `revoke_all_tokens` to not internally commit (or add a `commit=False`
   parameter).

2. **CR-02** (critical): Add a `token_version` bump to `convert_saml_user_to_local`
   in `admin/service.py`.

3. **CR-03** (critical): Extend `_update_sync_cache` to include
   `"semantic_search_rate_limit"` and `"basemap_proxy_rate_limit"` so DB overrides
   propagate to slowapi at runtime.

4. **CR-04** (critical): Fix the `EmbedToken.expires_at > func.now()` predicate
   in `service_public.py:get_shared_map` to also include `IS NULL` so non-expiring
   tokens contribute their `allowed_origins` to the CSP.

5. **WR-02** (warning): Remove the embedding rate limit from the `/search/facets/`
   endpoint — it does not invoke embeddings and 30/min is too tight for the SPA.

---

_Reviewed: 2026-05-20_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_

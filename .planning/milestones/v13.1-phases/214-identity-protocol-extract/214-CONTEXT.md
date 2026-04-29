# Phase 214: identity-protocol-extract - Context

**Gathered:** 2026-04-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Cross-domain code stops depending on the concrete `User` SQLAlchemy ORM and depends instead on a structural `IdentityProtocol` defined in `backend/app/core/identity.py`. The `geolens-enterprise` overlay (Phase 217) gains a registration seam — `get_identity_extension()` parallel to the existing `get_branding_extension()` / `get_audit_extension()` accessors — so a SAML/SCIM/LDAP backend can resolve identities for arriving requests without modifying core. After this phase:

- `backend/app/core/identity.py` is a NEW file. It defines:
  - `IdentityProtocol` — structural Protocol capturing the surface 51 cross-domain call sites depend on (`id`, `username`, `email`, `is_active`, `roles`, `created_at`).
  - `RoleProtocol` — slim companion Protocol (`name: str`) so `IdentityProtocol.roles` can be typed without re-creating a `core → modules.auth` import edge.
  - `IdentityExtension` Protocol — the enterprise-overlay registration contract, with one method: `async resolve_identity_from_token(token, request, db) -> IdentityProtocol | None`.
  - `Identity` — type alias of `IdentityProtocol` for shorter caller annotations.
- `backend/app/platform/extensions/__init__.py` exposes a typed accessor `get_identity_extension() -> IdentityExtension`, mirroring the existing `get_branding_extension()` / `get_audit_extension()` / `get_auth_extension()` pattern.
- `backend/app/platform/extensions/defaults.py` adds `DefaultIdentityExtension` — community-edition fallback whose `resolve_identity_from_token()` returns `None` (existing JWT/API-key path runs unchanged).
- `backend/app/modules/auth/dependencies.py` retypes `get_optional_user()` and `get_current_active_user()` to return `Identity` (not `User`). Inside `get_optional_user()`, the extension is called between the API-key path and the JWT path: if it returns a non-None identity, that wins; otherwise the existing JWT decode + DB lookup runs. Default impl returns None → zero behavior change in community edition.
- ~42 cross-domain User import sites (catalog/, processing/ai/, processing/export, processing/tiles, non-registration processing/ingest sites, platform/jobs, platform/sandbox, platform/config_ops, modules/settings/router.py, audit/router.py, audit/service.py, embed_tokens/, standards/ogc/router.py) swap `from app.modules.auth.models import User` → `from app.core.identity import Identity` and rewrite `user: User` parameter annotations to `user: Identity`.
- 9 sites legitimately KEEP concrete `User` (allowlist below).
- A new architecture-guard test in `backend/tests/test_layering.py` enforces (a) `core/` no longer imports from `app.modules.*` AT ALL (broadening Phase 212's settings-only guard), and (b) cross-domain code does not import `User` from `app.modules.auth.models` outside the explicit allowlist.
- 1965-test backend baseline stays green; existing JWT/OAuth/API-key/refresh-token flows operate unchanged because `User` structurally satisfies `IdentityProtocol`.

**Allowlist — sites that legitimately keep concrete `User`:**
1. `backend/app/modules/auth/**` — owns `User` (models, dependencies, service, router, oauth/, providers/, refresh-token/etc.)
2. `backend/app/modules/admin/router.py`, `backend/app/modules/admin/service.py` — manages users as ORM resources (CRUD `User` rows; reads `password_hash`, `auth_provider`, `last_login_at` columns that are NOT on IdentityProtocol)
3. `backend/app/modules/audit/models.py` — defines `AuditLog.user: Mapped["User"]` relationship (TYPE_CHECKING-only import)
4. `backend/app/api/main.py` — imports `Role, User, UserRole` to populate `Base.metadata` for SQLAlchemy
5. `backend/app/processing/ingest/tasks_raster.py:142` — `from app.modules.auth.models import User  # noqa: F401` for SQLAlchemy registration in the Procrastinate worker process
6. `backend/app/modules/auth/oauth/models.py:92` — `from app.modules.auth.models import User  # noqa: E402, F401` for relationship registration

**In scope:** create `core/identity.py`; create `DefaultIdentityExtension` + `get_identity_extension()` accessor; retype FastAPI dependencies; wire extension into the dep chain; migrate ~42 cross-domain caller annotations; add two architecture-guard tests; verify 1965-test baseline + alembic check.

**Out of scope:** any change to authentication semantics, JWT/OAuth/API-key flows, role model, RBAC matrix, permission checks, refresh-token rotation, OAuth state, or session handling. No Alembic migration. No frontend changes. No SAML/SCIM/LDAP implementation (Phase 217 owns that — Phase 214 only adds the seam). No `is_admin` derived helper on the Protocol (audit-26-b suggested it; rejected — admin role checks stay where they are). No runtime `isinstance(user, IdentityProtocol)` conformance tests (implicit structural conformance is the discipline). No relocation of FastAPI dependency stubs out of `auth/dependencies.py` (they stay in auth — only their return type changes). No new permissions, no new roles, no new endpoints.

</domain>

<decisions>
## Implementation Decisions

### Protocol surface
- **D-01:** `IdentityProtocol` exposes the **comprehensive** 6-field surface that mirrors what cross-domain code actually reads today: `id: UUID`, `username: str`, `email: str | None`, `is_active: bool`, `roles: Sequence[RoleProtocol]`, `created_at: datetime`. Reason: the audit's minimal 4-field suggestion (id, email, is_active, roles) doesn't cover `username` (read in admin/router.py:52, audit/router.py:72,153,189, catalog/maps/router.py:252, catalog/datasets/api/router.py:450, catalog/sources/provenance.py:54,77) or `created_at` (read in admin/router.py:57). A minimal Protocol would force admin/audit/maps/sources to keep importing concrete `User`, splitting cross-domain code into half-converted sites. Comprehensive lets every non-allowlist site annotate against `Identity` cleanly.
- **D-02:** **No** `is_admin` derived property on the Protocol. Audit-26-b §1 suggested it; rejected. Reason: there's no `is_admin` column on the `User` ORM today — it's derived from `roles` via `'admin' in {r.name for r in user.roles}` (admin/service.py:29,153). Adding a derived property to the Protocol would make `User` no longer satisfy the Protocol structurally, forcing a change to the ORM class. Admin-role checks stay where they are; consumers compute the predicate themselves.
- **D-03:** `roles` is typed as `Sequence[RoleProtocol]`, NOT `Sequence[Role]` — and `RoleProtocol` (defined as `class RoleProtocol(Protocol): name: str`) lives in the same `core/identity.py` file. Reason: typing `roles` against the concrete `Role` ORM class would re-create the `core → modules.auth` import edge this milestone is closing. Mirrors the documented pattern at `platform/extensions/protocols.py` ("Uses only stdlib types to avoid circular imports with domain models"). The concrete `Role` ORM model satisfies `RoleProtocol` structurally — admin/service.py's `{r.name for r in user.roles}` and admin/router.py:58's `sorted(r.name for r in user.roles)` both keep working untouched.
- **D-04:** `IdentityProtocol` and `RoleProtocol` are decorated `@runtime_checkable` (matches `BrandingExtension` / `AuditExtension` / `AuthExtension` in `platform/extensions/protocols.py`). Enables future `isinstance(x, IdentityProtocol)` checks if a Phase 217+ overlay needs them; cost is negligible.
- **D-05:** A type alias `Identity = IdentityProtocol` is defined in `core/identity.py` and is the name caller files import. Reason: `user: Identity` reads cleaner than `user: IdentityProtocol` and matches the existing project convention of `User` (one-word type names in annotations). Both names are exported.
- **D-06:** `User` ORM class is **NOT modified** — no inheritance from Protocol, no class-level conformance assertion, no `TYPE_CHECKING` annotation in `auth/models.py`. Reason: Python Protocols are structural; if `User` has the right attributes, it satisfies the Protocol automatically. Mirrors how `DefaultBrandingExtension` / `DefaultAuditExtension` satisfy their Protocols today (no inheritance). Keeps `auth/models.py` purely declarative.

### Caller migration
- **D-07:** Two coordinated changes deliver the migration: (1) retype `get_optional_user()` and `get_current_active_user()` in `backend/app/modules/auth/dependencies.py` to return `Identity` instead of `User`; (2) rewrite ~42 cross-domain caller files to swap their import (`from app.modules.auth.models import User` → `from app.core.identity import Identity`) and parameter annotations (`user: User` → `user: Identity`, `user: User | None` → `user: Identity | None`). Reason: realizes ROADMAP SC#2 ("all 51 cross-domain `User` import sites type against `IdentityProtocol`") literally. Annotation-only swap (without dep retype) wouldn't cut the coupling the audit measures.
- **D-08:** Sites that import `Role` and/or `UserRole` from `app.modules.auth.models` for SQL-filter or junction-table use (e.g., `UserRole.user_id == user.id` at catalog/maps/service.py:637, `from app.modules.auth.models import Role, User, UserRole` at catalog/authorization.py:21, function-scope `from app.modules.auth.models import UserRole` at processing/tiles/router.py:213) keep the `Role` / `UserRole` imports concrete — those classes are NOT covered by `IdentityProtocol`. Only the `User` import is replaced with `Identity`. The architecture-guard test (D-12) regexes specifically against `\bUser\b` in the import line, not against `Role` / `UserRole`.
- **D-09:** Allowlist (sites that keep importing concrete `User` from `app.modules.auth.models`):
  - `backend/app/modules/auth/**` — owns the model. All paths under this prefix exempt.
  - `backend/app/modules/admin/router.py`, `backend/app/modules/admin/service.py` — admin endpoints CRUD `User` rows; legitimately read `password_hash`, `auth_provider`, `last_login_at` (NOT on Identity); construct `User(...)` instances; query `select(User).where(...)`. Migrating admin to Identity would split admin's per-method API into Identity-typed and User-typed halves with no boundary win.
  - `backend/app/modules/audit/models.py` — defines `AuditLog.user: Mapped["User"]` relationship under `if TYPE_CHECKING: from app.modules.auth.models import User`. ORM relationship typing requires the concrete class; Protocols don't work for SQLAlchemy `Mapped[...]`.
  - `backend/app/api/main.py` — imports `Role, User, UserRole` to populate `Base.metadata` (Alembic migration discovery). No annotation change needed; the import exists for side-effect.
  - `backend/app/processing/ingest/tasks_raster.py:142` — `from app.modules.auth.models import User  # noqa: F401` inside the Procrastinate worker entrypoint to register `User` with `Base.metadata` in the worker process. Side-effect import.
  - `backend/app/modules/auth/oauth/models.py:92` — `from app.modules.auth.models import User  # noqa: E402, F401` for relationship registration ordering. Side-effect import.
  - `backend/tests/**` — entirely exempt. Test fixtures construct `User(...)` and import the concrete model freely. The architecture guard's pathspec excludes `backend/tests/`.
- **D-10:** No backward-compat re-export shim is left in `app.modules.auth.models` and no `Identity` re-export is added to `app.modules.auth`. Phase 212 D-04 and Phase 213 D-04 set this discipline — closed-set codebase, ruff + full pytest run is the safety net. The migration is a hard cutover.
- **D-11:** Mandatory planner step: run `git grep -nE "from app\.modules\.auth\.models import" -- backend/app/` and confirm every hit corresponds to either an allowlist entry (D-09) or a site to migrate. If new hits appear (e.g., a recently-added router imports `User`), migrate them too. Re-run after edits to confirm zero new `User`-import sites land in non-allowlisted code.

### Extension hook
- **D-12:** Define a NEW `IdentityExtension` Protocol in `core/identity.py` with one forward-looking method:
  ```python
  @runtime_checkable
  class IdentityExtension(Protocol):
      async def resolve_identity_from_token(
          self, token: str, request: Request, db: AsyncSession
      ) -> Identity | None: ...
  ```
  Reason: minimal surface that satisfies IDENT-03 ("overlays can register custom identity backends through the extension system without modifying core") and gives Phase 217 (auth-saml-enterprise) a clear plug-in point. SAML overlay implements this method to validate a SAML session token, run JIT provisioning through the existing `find_or_create_oauth_user()` pathway (per ROADMAP §Phase 217 SC#3), and return an `Identity`. Audit-26-b §10's "concrete User ORM stays in auth but invisible to consumers" only holds if such a hook exists.
- **D-13:** Typed accessor `get_identity_extension() -> IdentityExtension` lives in `backend/app/platform/extensions/__init__.py`, registered under `_extensions["identity"]`, falling back to `DefaultIdentityExtension()` when no enterprise overlay registers. Mirrors `get_branding_extension()` / `get_audit_extension()` / `get_auth_extension()` exactly. The existing `geolens.extensions` entry-point group is reused; the SAML overlay's setup will provide an entry point that calls `_extensions["identity"] = SAMLIdentityExtension()` from its loader.
- **D-14:** `DefaultIdentityExtension` lives in `backend/app/platform/extensions/defaults.py` next to `DefaultBrandingExtension` / `DefaultAuditExtension` / `DefaultAuthExtension`. Implementation: `async def resolve_identity_from_token(self, token, request, db) -> Identity | None: return None`. Returning None signals "I don't recognize this token; fall through to the existing JWT path." Zero runtime cost in community edition (one async method call returning None per request).
- **D-15:** Wire-in: `get_optional_user()` in `backend/app/modules/auth/dependencies.py` calls the extension between the API-key path and the JWT path. Order:
  1. Resolve API key (existing — `_resolve_api_key()`).
  2. Extract bearer token (existing).
  3. **NEW:** if a bearer token exists, call `await get_identity_extension().resolve_identity_from_token(token, request, db)`. If the result is non-None, return it.
  4. Otherwise, fall through to existing JWT decode + DB lookup.
  5. Anonymous (None) if no token at all.
  Reason: SAML session tokens may not be valid JWTs (e.g., opaque session IDs); intercepting before JWT decode lets the extension recognize its own format. Default impl returns None → existing JWT path always runs in community edition.
- **D-16:** `get_current_user()` and `get_current_active_user()` build on `get_optional_user()` in the existing pattern (per `auth/dependencies.py:169-178`); they inherit the extension wire-in for free. The `is_active` gate in `get_current_active_user()` runs against the returned `Identity` (which has `is_active: bool` per D-01).
- **D-17:** The extension is NOT consulted in the API-key resolution path (D-15 step 1). API keys remain a core/community concern; if a future enterprise SCIM overlay needs to issue API keys, that's a separate Protocol design decision driven by a real consumer (Phase 213-style YAGNI discipline).

### Architecture guard
- **D-18:** Add **two** new `@pytest.mark.architecture` tests to `backend/tests/test_layering.py`:
  1. `test_core_does_not_import_from_any_module()` — broadens Phase 212-03's `test_core_does_not_import_from_settings_module()` from `app.modules.settings` to `app.modules.*`. The Phase 212-03 docstring explicitly anticipates this expansion: "Phase 218 will broaden this guard to `from app.modules.<*>` once those phases land." Phase 214 brings that broadening forward because `core/identity.py` is the new file that must respect it. The original Phase 212 test stays in place (specific-to-general defense in depth) OR is replaced by the broader version — planner picks based on diff cleanliness; default is to REPLACE the narrow version with the broader one and update the docstring to credit Phases 212+214.
  2. `test_cross_domain_does_not_import_user_from_auth_models()` — fails if any line under `backend/` (excluding the allowlist) does `from app.modules.auth.models import .*\bUser\b`. Maps directly to ROADMAP SC#2.
- **D-19:** Test 2's allowlist is expressed via git pathspec `:!` exclusions on the `git grep` invocation, mirroring Phase 213-03's `test_no_auth_visibility_module_referenced` pattern. Concrete invocation:
  ```python
  result = subprocess.run([
      "git", "grep", "-n", "-E",
      r"^\s*(from|import)\s+app\.modules\.auth\.models\s+import\s+.*\bUser\b",
      "--", "backend/",
      ":!backend/app/modules/auth/",
      ":!backend/app/modules/admin/",
      ":!backend/app/modules/audit/models.py",
      ":!backend/app/api/main.py",
      ":!backend/app/processing/ingest/tasks_raster.py",
      ":!backend/app/modules/auth/oauth/models.py",  # already covered by auth/** but explicit
      ":!backend/tests/",
  ], cwd=REPO_ROOT, capture_output=True, text=True, check=False)
  ```
  Reuses the existing `_has_git_metadata()` skip guard and `_has_pathspec_magic()` git-version check from Phase 213-03. The regex matches `import .*\bUser\b` so `import Role, User, UserRole` and `import User` both trip; `import UserRole` alone (no standalone `User`) does not — the `\bUser\b` word boundary handles this.
- **D-20:** Update the module docstring of `test_layering.py` to credit Phase 214 — same pattern as Phase 213's update. Reference Phases 212, 213, **214** as the closed boundaries; note Phase 218 will revisit if any layering finding remains.
- **D-21:** **No** runtime conformance test (`assert isinstance(User(), IdentityProtocol)`). Reason: implicit structural conformance is the discipline (D-06); a runtime `isinstance` check requires `@runtime_checkable` (which we have per D-04) but adds a third test file (`test_identity.py`?) for marginal value. The full pytest run already exercises the dep chain end-to-end against the concrete `User`; if `User` ever stops satisfying `IdentityProtocol`, the FastAPI dep call sites will fail at runtime via attribute-access errors. Defer formal conformance testing if it ever becomes load-bearing.
- **D-22:** **No** ruff-level boundary rule (e.g., `tool.ruff.lint.per-file-ignores`-driven import-from prohibition). The architecture-guard tests are the project's convention (Phase 212/213); we don't add a parallel mechanism.

### Migration & verification
- **D-23:** No Alembic migration. The `app.modules.auth.models.User` SQLAlchemy class is NOT moved — only its consumers' import paths and parameter annotations change. The `users`, `roles`, `user_roles`, `api_keys`, `refresh_tokens` tables are unchanged. Proof step in the phase plan: after the refactor, run `cd backend && uv run alembic check` and confirm "no new operations." A non-empty diff means the refactor accidentally touched `User.__table_args__` and the planner stops.
- **D-24:** The 1965-test backend baseline (per STATE.md, restored 2026-04-26 by quick task `260425-sl1`, confirmed green at end of Phases 212+213) is the acceptance gate. Phase plan's verification gate runs full pytest; any non-baseline failure is a defect introduced by the refactor.
- **D-25:** ROADMAP SC#5 ("`pyright`/`mypy` reports no new typing regressions") is interpreted **softly**. The project does not run pyright or mypy in CI — `backend/pyproject.toml` only configures `ruff`, pytest, and coverage. The acceptance criterion is satisfied if (a) ruff passes, (b) the full pytest run passes, and (c) optional ad-hoc `pyright backend/app` invocation by the planner reports no new errors *introduced by Phase 214's edits* (existing pyright errors elsewhere are not blockers). Phase 214 does NOT add a pyright/mypy CI gate — that's a separate decision owned by Phase 218 if the audit demands it.
- **D-26:** Frontend has zero involvement. No HTTP contract change, no error-shape change, no schema change. `make openapi-check` continues to pass without regenerating `backend/openapi.json`.
- **D-27 [informational]:** Phase 214 is independent of Phases 212 and 213 per ROADMAP — they may run in parallel. Phase 214 will overlap with Phase 213's caller-migration set in the same files (catalog/, processing/, etc.) but on different lines (Phase 213 rewrote `from app.modules.auth.visibility import ...`; Phase 214 rewrites `from app.modules.auth.models import User`). Since both phases are now sequenced (212 + 213 already complete), Phase 214 starts from a clean main with both prior refactors landed. Phase 214 is a hard prerequisite for Phase 217 (auth-saml-enterprise).

### Claude's Discretion
- **Commit decomposition** — likely 4 atomic commits mirroring Phases 212/213: (1) introduce `core/identity.py` with `IdentityProtocol`, `RoleProtocol`, `IdentityExtension`, and `Identity` alias; introduce `DefaultIdentityExtension` in `platform/extensions/defaults.py`; introduce `get_identity_extension()` in `platform/extensions/__init__.py` — pure additive, no behavior change. (2) Retype `get_optional_user`/`get_current_user`/`get_current_active_user` in `auth/dependencies.py` to return `Identity`; wire `get_identity_extension().resolve_identity_from_token(...)` between the API-key and JWT paths. (3) Migrate the ~42 cross-domain caller import + annotation sites; mechanical sweep. (4) Extend `test_layering.py` with the two new architecture-guard tests + update its docstring; replace (or supplement — planner picks) the narrow `test_core_does_not_import_from_settings_module` with the broader `test_core_does_not_import_from_any_module`; phase verification gate (alembic check + full pytest + ruff + ROADMAP SC verification, mirroring 212-04 and 213-04). Planner may collapse, split, or reorder based on dependency ordering and file-size budgets. Whichever decomposition is chosen, every commit must keep the test suite green — i.e., the dep retype (commit 2) must land BEFORE caller migrations (commit 3) so callers can import `Identity` and have something concrete to annotate against; the architecture-guard tests (commit 4) must land LAST because they fail until cross-domain User imports are gone.
- **Module docstring wording** in `core/identity.py` — keep the spirit of `platform/extensions/protocols.py`'s "Uses only stdlib types to avoid circular imports with domain models" plus a one-liner pointing to the milestone (Phase 214, IDENT-01..03) and Phase 217 as the first concrete consumer of the extension hook. Planner picks exact wording.
- **Whether to refactor any cross-domain helper functions** during the migration — default is NO. If the planner sees a trivial dead-import or unused-name cleanup along the way (e.g., a router that imports `User` but never references it after the annotation rewrite), removal is allowed; anything bigger is deferred.
- **Whether to keep BOTH the narrow Phase 212 guard AND the broadened Phase 214 guard** — default is REPLACE the narrow one with the broad one (the broad subsumes it). Keeping both adds noise. Planner makes the call based on whether the broader test gives an equally clear failure message.
- **`Request` parameter on `IdentityExtension.resolve_identity_from_token`** — included for SAML's likely needs (cookies, header introspection, etc.). If the planner determines Phase 217's design will not need it (e.g., pure bearer-token validation), it can be dropped. Default: keep `Request` on the signature.
- **Test marker** — both new architecture tests use `@pytest.mark.architecture` (already registered in `backend/pyproject.toml` since Phase 212-03). No new marker.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Audit / spec
- `docs-internal/audits/oc-separation-deferred-items-20260426.md` — P1 bucket, row "Extract `IdentityProtocol` in `core/identity.py`". This is the source spec. Names the file count (51), domain count (11), and effort estimate (3–5 days).
- `docs-internal/audits/oc-separation-audit-20260426.md` §5 / §10 — full audit body. The §10 recommendation reads: "Extract `app/core/identity.py` Protocol exposing `IdentityProtocol` (just `id`, `email`, `is_active`, `roles`) plus FastAPI dependency stubs. Have all 51 `User` import sites depend on the Protocol; keep concrete SQLAlchemy `User` inside `modules/auth/`. Enterprise can then swap implementations (LDAP, SCIM, SSO-only) without touching catalog/audit/admin/settings/ai." Phase 214 expands the surface from 4 to 6 fields per D-01 — note the divergence in the planning notes.
- `docs-internal/audits/oc-separation-audit-20260426-b.md` §1 / §10 — supplementary audit. Names `IdentityProtocol` again, suggests `is_admin` instead of `is_active` (we adopt `is_active`, reject `is_admin` per D-02). §10 also says "Convert FastAPI dependencies (`get_current_active_user`, `get_optional_user`) to return the protocol. Concrete `User` ORM stays in `auth` but invisible to consumers" — this is the dep-retype directive Phase 214 implements.
- `.planning/REQUIREMENTS.md` §IDENT-01, IDENT-02, IDENT-03 — the three requirements this phase closes.
- `.planning/ROADMAP.md` §Phase 214 — goal statement and 5 success criteria. The wording "`core/identity.py`" is binding; SC#3's "typed accessor + entry_point seam, mirroring `get_branding_extension()` / `get_audit_extension()`" pins the integration pattern.

### Project / state
- `.planning/PROJECT.md` — milestone overview; v13.1 is audit-driven with target grades Boundary B → A−, Seam Quality C → B, OSS Surface D → C. Phase 214 contributes to all three (Boundary by removing 42 cross-domain User-coupling edges; Seam by adding the IdentityExtension hook; OSS Surface indirectly by unblocking enterprise overlay distribution).
- `.planning/STATE.md` — confirms 1965/1965 backend test baseline (restored 2026-04-26 by quick task `260425-sl1`) and Phase 212+213 completion status.
- `.planning/phases/212-core-settings-decouple/212-CONTEXT.md` — companion phase, established the all-callers-in-one-shot + no-shim + architecture-guard pattern. Phase 214 inherits this discipline.
- `.planning/phases/213-catalog-authz-relocate/213-CONTEXT.md` — companion phase, extended the architecture-guard pattern with a second test and `:!` pathspec exclusion (the same exclusion pattern Phase 214 uses for the User-import allowlist guard).
- `.planning/phases/212-core-settings-decouple/212-RESEARCH.md`, `.planning/phases/213-catalog-authz-relocate/213-RESEARCH.md` (if generated by `/gsd-plan-phase`) — pitfall lists and codebase-pattern surveys; reuse the `_has_git_metadata()` skip guard pattern (RESEARCH.md Pitfall 4 in Phase 212), the `_has_pathspec_magic()` git-version check, and the `_git_grep` helper.

### Code (current location of `User` and friends)
- `backend/app/modules/auth/models.py` — defines `User`, `Role`, `UserRole`, `ApiKey`, `RefreshToken`. Phase 214 leaves this file UNCHANGED. Read end-to-end so the planner knows the exact attribute set `IdentityProtocol` must capture (D-01).
- `backend/app/modules/auth/dependencies.py` — defines `get_optional_user()`, `get_current_user()`, `get_current_active_user()`, `get_cached_user_roles()`, `_resolve_api_key()`, `require_permission()`, `require_role()`. Phase 214 retypes the first three to return `Identity` and wires the extension call into `get_optional_user()` (D-15). Read end-to-end so the planner understands the API-key/header/query/JWT precedence (per CLAUDE.md auth notes — header > query > JWT > anonymous), the request-state caching of user roles, and the `_resolve_api_key()` query-param fallback.
- `backend/app/modules/auth/providers/__init__.py` — defines the OTHER auth Protocol: `AuthProvider` + `AuthenticatedIdentity` dataclass. NOT the same surface as `IdentityProtocol`; `AuthProvider.authenticate()` is post-login (token issuance), `IdentityProtocol` is consumer-facing (typed surface for downstream code). Phase 214 leaves this file untouched but the planner should be aware both exist.
- `backend/app/modules/auth/providers/local.py` — `LocalAuthProvider` implementation. Reads `User.password_hash`, `User.username`. Stays in auth; Phase 214 doesn't touch it.
- `backend/app/modules/auth/oauth/service.py` — defines `find_or_create_oauth_user()` referenced in ROADMAP §Phase 217 SC#3 as the JIT-provisioning pathway SAML will reuse. Phase 214 leaves it untouched but the planner should confirm its signature returns `User` (concrete) — that's fine because OAuth flow is internal to auth/.

### Code (extension scaffold to extend)
- `backend/app/platform/extensions/__init__.py` — extension registry; defines `_extensions: dict[str, object]`, `_routers: list`, `load_extensions()`, `get_extension()`, `has_extension()`, `list_extensions()`, `get_extension_routers()`, and the typed accessors `get_branding_extension()` / `get_audit_extension()` / `get_auth_extension()`. Phase 214 adds `get_identity_extension()` here (D-13).
- `backend/app/platform/extensions/protocols.py` — Protocol definitions for `BrandingExtension`, `AuditExtension`, `AuthExtension`. **Not modified** by Phase 214 — `IdentityExtension` lives in `core/identity.py` per D-12 (different layer; it returns `Identity` which lives in core, and putting the Protocol in core keeps the related types co-located). Read the file's docstring ("Uses only stdlib types to avoid circular imports with domain models") — the same discipline applies to `core/identity.py`.
- `backend/app/platform/extensions/defaults.py` — `DefaultBrandingExtension`, `DefaultAuditExtension`, `DefaultAuthExtension`. Phase 214 adds `DefaultIdentityExtension` here (D-14).
- `backend/app/platform/extensions/guards.py` (per audit-26-b §4) — `require_enterprise()` FastAPI dependency. Not modified by Phase 214 but the planner should understand it: an enterprise overlay registers extensions AND uses `require_enterprise()` to gate routes. The IdentityExtension is community-aware (default impl returns None) so it doesn't need a `require_enterprise()` gate — the gating happens implicitly because no extension registers in community edition.
- `backend/app/api/main.py:125-135` — application startup wiring: `load_extensions()` → `init_edition()` → mount extension routers. Phase 214's `get_identity_extension()` is consulted lazily on every request (per D-15), not at startup; no startup-wiring change needed.

### Code (architecture-guard test)
- `backend/tests/test_layering.py` — current state: 4 architecture tests (2 from Phase 212, 2 from Phase 213). Phase 214 adds 2 more (D-18) and updates the module docstring (D-20). The test file holds the `_has_git_metadata()`, `_has_pathspec_magic()`, and `_git_grep()` helpers Phase 214 reuses verbatim.
- `backend/pyproject.toml` — registers the `architecture` pytest marker. Already done by Phase 212-03; no change.

### Code (caller files — the ~42 sites Phase 214 migrates)

The complete current-state list (`grep -rn "from app.modules.auth.models import" backend/app/`), with the planner re-running this grep at plan time to catch any post-discussion drift:

**Migrate to `Identity` (~42 sites):**
- `backend/app/modules/settings/router.py:12`
- `backend/app/modules/audit/router.py:31`
- `backend/app/modules/audit/service.py:24` (TYPE_CHECKING-only import; rewrite to import `Identity` instead)
- `backend/app/modules/embed_tokens/admin_router.py:10`
- `backend/app/modules/embed_tokens/router.py:27`
- `backend/app/modules/embed_tokens/service.py:312` (function-scope deferred import)
- `backend/app/modules/catalog/maps/router.py:25`
- `backend/app/modules/catalog/maps/service.py:19`
- `backend/app/modules/catalog/records/router.py:10`
- `backend/app/modules/catalog/layers/router.py:11`
- `backend/app/modules/catalog/datasets/api/router.py:27`
- `backend/app/modules/catalog/datasets/api/router_data.py:22`
- `backend/app/modules/catalog/datasets/api/router_export.py:24`
- `backend/app/modules/catalog/datasets/api/router_metadata.py:21`
- `backend/app/modules/catalog/datasets/api/router_reupload.py:20`
- `backend/app/modules/catalog/datasets/api/router_vrt.py:18`
- `backend/app/modules/catalog/datasets/domain/service.py:28`
- `backend/app/modules/catalog/datasets/domain/helpers.py:9`
- `backend/app/modules/catalog/features/router.py:14`
- `backend/app/modules/catalog/search/router.py:18`
- `backend/app/modules/catalog/search/service.py:31`
- `backend/app/modules/catalog/search/cache.py:12`
- `backend/app/modules/catalog/sources/router.py:14`
- `backend/app/modules/catalog/sources/stac_router.py:23`
- `backend/app/modules/catalog/collections/router.py:15`
- `backend/app/modules/catalog/collections/service.py:26`
- `backend/app/modules/catalog/authorization.py:21` (currently `import Role, User, UserRole` — Phase 214 splits this into `from app.modules.auth.models import Role, UserRole` + `from app.core.identity import Identity`)
- `backend/app/processing/ingest/service.py:19`
- `backend/app/processing/ingest/router.py:22`
- `backend/app/processing/tiles/router.py:20`
- `backend/app/processing/tiles/router.py:213` (function-scope `from app.modules.auth.models import UserRole` — KEEPS importing `UserRole`, only the `User` annotation in the surrounding function changes)
- `backend/app/processing/ai/service.py:31`
- `backend/app/processing/ai/router.py:41`
- `backend/app/processing/ai/streaming.py:32`
- `backend/app/processing/ai/chat_service.py:28`
- `backend/app/processing/export/router.py:15`
- `backend/app/platform/sandbox/__init__.py:17`
- `backend/app/platform/sandbox/validator.py:17`
- `backend/app/platform/jobs/router.py:13`
- `backend/app/platform/config_ops/router.py:12`
- `backend/app/standards/ogc/router.py:10`

**Allowlist — do NOT migrate (9 sites; per D-09):**
- `backend/app/modules/auth/dependencies.py:14` (auth/**)
- `backend/app/modules/auth/router.py:13` (auth/**)
- `backend/app/modules/auth/service.py:12` (auth/**)
- `backend/app/modules/auth/oauth/service.py:10` (auth/**)
- `backend/app/modules/auth/oauth/models.py:92` (auth/**, side-effect)
- `backend/app/modules/auth/providers/local.py:9` (auth/**)
- `backend/app/modules/admin/router.py:33` (admin/**)
- `backend/app/modules/admin/service.py:14, 296` (admin/**)
- `backend/app/modules/audit/models.py:12` (TYPE_CHECKING relationship)
- `backend/app/api/main.py:26` (model registration)
- `backend/app/processing/ingest/tasks_raster.py:142` (worker registration, `# noqa: F401`)

(Yes, the allowlist enumerates 11 file lines but covers 9 logical "sites" — `auth/**` is one allowlist entry that subsumes 6 individual import lines.)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`backend/app/platform/extensions/__init__.py` typed-accessor pattern** (`get_branding_extension()`, `get_audit_extension()`, `get_auth_extension()`): Phase 214 adds `get_identity_extension()` next to these, identical shape — `_extensions.get("identity") or DefaultIdentityExtension()`, return-type-annotated `IdentityExtension`. ROADMAP SC#3 binds this pattern.
- **`backend/app/platform/extensions/defaults.py` Default*Extension community-fallback pattern**: Phase 214 adds `DefaultIdentityExtension` here. The class implements one async method that returns None — community edition behavior is exactly today's behavior (existing JWT path always wins).
- **`backend/app/platform/extensions/protocols.py` "stdlib-types-only" Protocol discipline**: docstring documents the rule. Phase 214's `core/identity.py` follows the same rule by design — it imports only `typing.Protocol`, `typing.Sequence`, `typing.runtime_checkable`, `uuid.UUID`, `datetime.datetime`, `fastapi.Request`, `sqlalchemy.ext.asyncio.AsyncSession` (the last two are infrastructure types the extension method signature needs; `Request` and `AsyncSession` do NOT live under `app.modules.*` so they don't violate the layering rule).
- **`backend/tests/test_layering.py` `_has_git_metadata()` + `_has_pathspec_magic()` + `_git_grep()` helpers** (Phases 212+213): Phase 214's two new tests reuse them verbatim. No new helpers needed.
- **`@pytest.mark.architecture` marker registered in `backend/pyproject.toml`** (Phase 212-03): Phase 214's new tests use it directly.
- **`importlib.metadata.entry_points(group="geolens.extensions")` registration loop** at `platform/extensions/__init__.py:38`: Phase 214's `IdentityExtension` registers via the same group with key `"identity"` (the SAML overlay's loader does `extensions["identity"] = SAMLIdentityExtension()`). Already battle-tested by Phases 192–211 (v13.0 enterprise scaffold) and the v13.0 release.

### Established Patterns
- **Phase 212/213 mechanical-refactor discipline**: Phase 214 inherits the same rules — closed-set codebase, all-callers-in-one-shot, no shim, no re-export aliases, ruff + full pytest as the safety net, architecture-guard test as the regression seal. The migration is a hard cutover.
- **Closed-set caller migration via `git grep`**: Phase 212/213 used `git grep` (not import-graph libs like `import-linter`) to enumerate callers and to enforce the layering boundary. Phase 214 inherits this. Do NOT introduce `import-linter` or any architecture-DSL dependency.
- **`__table_args__ = {"schema": "catalog"}`**: every catalog-domain ORM model uses this. `User`, `Role`, `UserRole` all sit in the `catalog` schema. Phase 214 doesn't move any tables; the schema rule is unchanged.
- **API key precedence**: per CLAUDE.md auth notes, `_resolve_api_key()` at `auth/dependencies.py:23` resolves from header > query (`?api_key=`) > JWT > anonymous. Phase 214's extension wire-in (D-15) preserves this — extension is consulted ONLY in the bearer-token branch, NOT in the API-key branch. API keys remain a core/community concern.
- **TYPE_CHECKING imports for ORM relationships** (e.g., `audit/models.py:12`, `audit/service.py:24`): SQLAlchemy `Mapped["User"]` declarations require the concrete class symbol but don't need it at runtime. Phase 214 leaves `audit/models.py:12` alone (allowlisted) because the relationship is genuinely tied to the ORM. `audit/service.py:24` migrates: it's a TYPE_CHECKING-only import that exists to type a function parameter; that parameter becomes `Identity`, and the import becomes `if TYPE_CHECKING: from app.core.identity import Identity` (or just module-level — `Identity` is light, no runtime cost).
- **Function-scope deferred imports as cycle-breakers / slow-startup mitigation**: ~103 deferred imports exist project-wide. Phase 214 rewrites the path on the four `User`-related deferred imports (e.g., `embed_tokens/service.py:312`) — keeps them deferred, just swaps `User` for `Identity`. Doesn't touch the deferral itself (Phase 213 D-04 set this discipline for `auth.visibility` deferrals; Phase 214 inherits).
- **Side-effect imports for SQLAlchemy registration** (`# noqa: F401`): `processing/ingest/tasks_raster.py:142`, `modules/auth/oauth/models.py:92`, `api/main.py:26`. These exist purely to populate `Base.metadata` so Alembic's autogenerate sees the tables. They cannot be replaced with `Identity` — Identity is a Protocol, has no `__tablename__`, doesn't register. Allowlisted accordingly.

### Integration Points
- **`backend/app/api/main.py` startup chain**: `load_extensions()` → `init_edition()` → mount routers. The IdentityExtension is consulted lazily per-request via `get_identity_extension()` inside `get_optional_user()` (D-15), NOT at startup. No startup-wiring change. The `_loaded` flag at `platform/extensions/__init__.py:29` is set after `load_extensions()` runs; if `get_identity_extension()` is called before `load_extensions()` (shouldn't happen — startup runs `load_extensions()` first per `api/main.py:125-135`), it returns the default impl, which is correct fallback behavior.
- **Procrastinate worker process** (raster ingest): the worker imports `User` at `processing/ingest/tasks_raster.py:142` for `Base.metadata` registration. The worker also calls FastAPI deps? No — workers run task functions, not request handlers. They don't go through `get_optional_user()`; the Identity wire-in (D-15) is request-path only. Worker code that needs the current user receives a `user_id: UUID` parameter (per the existing pattern) and looks up the User directly. Phase 214 doesn't change this.
- **OAuth flow** (`auth/oauth/router.py`, `auth/oauth/service.py`): the OAuth flow is internal to auth/. It calls `find_or_create_oauth_user()` which returns `User` (concrete). Phase 217 (SAML) registers an `IdentityExtension` that, in its `resolve_identity_from_token()` implementation, may call `find_or_create_oauth_user()` (or a SAML-specific equivalent) to get a `User` and return it as `Identity`. Phase 214 leaves the OAuth flow untouched.
- **Embed tokens** (`modules/embed_tokens/`): currently imports `User` for type annotations (`embed_tokens/router.py:27`, `admin_router.py:10`, `service.py:312`). The embed-token resolution logic (`service.py`) doesn't need anything beyond `Identity`'s surface — `id`, `email`, etc. — so migration is safe. The function-scope import at `service.py:312` rewrites `from app.modules.auth.models import User` → `from app.core.identity import Identity` (still deferred — Phase 213 D-04 discipline).
- **OpenAPI snapshot (`backend/openapi.json`)**: unaffected. Identity is a Python-typing concept; FastAPI generates OpenAPI from request/response Pydantic schemas, not from FastAPI dependency return types. Routes that depend on `Identity` (formerly `User`) emit the same OpenAPI as before.
- **Tests** (`backend/tests/`): test fixtures construct `User(...)` directly and pass them to functions. Since `User` structurally satisfies `IdentityProtocol`, these fixtures work unchanged. The architecture guard's pathspec excludes `backend/tests/` (D-19) so test fixtures don't trip the User-import guard.

### Risk surfaces
- **`IdentityProtocol` doesn't cover everything `User` has.** Annotated as `Identity`, callers can read `id`, `username`, `email`, `is_active`, `roles`, `created_at`. They CANNOT read `password_hash`, `auth_provider`, `last_login_at`, `status`, `updated_at`. If any cross-domain caller reads those (planner verifies via `git grep -rn "user\.\(password_hash\|auth_provider\|last_login_at\|status\|updated_at\)" backend/app/`), the migration breaks at type-annotation time. Mitigation: the grep above. From the codebase scout, `password_hash` is only read in `auth/providers/local.py:38` (allowlisted); `last_login_at` and `auth_provider` only in admin (allowlisted); `status` only in auth/admin (allowlisted). No cross-domain leaks expected, but planner re-verifies.
- **Extension-call latency in the dep chain.** Wiring `get_identity_extension().resolve_identity_from_token(...)` adds one async method call per request. Default impl returns None immediately — negligible cost. Phase 217 SAML's implementation may run signature verification + DB lookup, which is non-trivial but only when a SAML token is present (no impact on JWT-token requests because the SAML overlay can short-circuit unrecognized token formats). Planner does NOT add caching at the extension layer in Phase 214 — that's Phase 217's design choice.
- **Multi-line import blocks**: `backend/app/modules/catalog/datasets/api/router*.py` and a few others use multi-line `from app.modules.auth.models import (\n  User,\n)` style. Mechanical migration rewrites the import line; the block-shape preservation rule is the same as Phase 213 D-04.
- **`IdentityExtension` returning a stale Identity**: an enterprise overlay's `resolve_identity_from_token()` could in principle return an Identity whose `is_active=False` or whose `roles` are stale. The dep chain's `get_current_active_user()` re-checks `is_active` (D-16); RBAC permission checks call `get_cached_user_roles()` (cached per-request via `request.state._user_roles`). Phase 214 does NOT redesign these — extensions inherit the existing freshness contract. If a future bug surfaces, it's owned by the extension implementation, not the seam.
- **Concrete `User` vs `Identity` ambiguity in mixed call sites**: e.g., `audit/service.py` may receive an Identity from one caller and a `User` from another (during the migration). Since `User` satisfies Identity structurally, runtime is fine; but ruff/pyright might complain about variance if a function annotated `def fn(u: Identity)` is called with `u: User` at one site and `u: Identity` at another. Resolution: structural subtyping handles this — `User` IS-A Identity. Planner verifies via ruff after the migration; if any false positive surfaces, add `# noqa: <rule>` with explanatory comment.

</code_context>

<specifics>
## Specific Ideas

- **Audit phrasing chosen, in their words:** Audit-26-b §10: "Convert FastAPI dependencies (`get_current_active_user`, `get_optional_user`) to return the protocol. Concrete `User` ORM stays in `auth` but invisible to consumers. Highest leverage — touches the single biggest coupling vector." Phase 214 implements this directive verbatim, with a 6-field surface (vs. the audit's 4) per D-01.
- **Audit-suggested `is_admin` field rejected:** Audit-26-b §1 suggested `is_admin` as a Protocol field. Rejected per D-02 — `is_admin` is not an ORM column, it's a derived predicate. Adding it to Protocol forces an `is_admin` property on `User`, which is scope creep into the role model. Admin-role checks stay where they are (admin/service.py:29,153 patterns: `'admin' in {r.name for r in user.roles}`).
- **Phase 217's plug-in shape will look like:** the SAML overlay's package contains a function `register(extensions: dict)` that does `extensions["identity"] = SAMLIdentityExtension(saml_config)`, exposed via `[project.entry-points."geolens.extensions"]` table in the overlay's `pyproject.toml` (mirroring v13.0 enterprise overlay's existing entry-point registration for branding/audit). When `load_extensions()` runs at startup, the SAML extension registers and `get_identity_extension()` returns it on subsequent requests. Phase 217 owns the SAML implementation; Phase 214 just provides the seam.
- **No `AuthorizationProtocol` extension seam introduced (companion to Phase 213's deferral):** Phase 213 explicitly deferred `AuthorizationProtocol`. Phase 214 likewise does not introduce one — `IdentityExtension` is the only new Protocol. Authorization continues to flow through `catalog/authorization.py` (Phase 213's relocation target).
- **Phase 218 is the proof:** success isn't just "tests pass," it's "Boundary B → A− and Seam Quality C → B" once `/oc-audit` reruns post-217. Phase 214's contribution is two-fold: (1) removing 42 `core ⇆ modules.auth.User` coupling edges (Boundary uplift), (2) adding the IdentityExtension seam that unblocks Phase 217 (Seam Quality uplift). Phase 218 reruns the audit and verifies grade movement.

</specifics>

<deferred>
## Deferred Ideas

- **`is_admin` as a Protocol field**: rejected per D-02. If a future phase establishes an explicit `is_admin` column on `User` (or a Boolean cached on the Identity), revisit. Until then, callers compute the predicate from `roles`.
- **`IdentityExtension.provision_identity(claims)`**: the JIT-provisioning hook some readings of IDENT-03 might suggest. Deferred — Phase 217 SAML reuses `find_or_create_oauth_user()` per ROADMAP §Phase 217 SC#3; no separate provisioning hook is needed at the seam level. Revisit when a non-OAuth provisioning shape is on the table.
- **`IdentityExtension.list_identity_methods() -> list[str]`** (parallel to `AuthExtension.get_auth_methods()`): admin UI could show "SAML active" if exposed, but Phase 214 doesn't need it. Revisit if the admin Settings page wants to surface registered identity backends.
- **API-key resolution via extension**: D-17 deferred. If a future enterprise SCIM overlay wants to issue API keys with non-default semantics, design a separate Protocol (or extend IdentityExtension) at that point. Phase 214's seam is bearer-token only.
- **Pyright/mypy CI gate**: D-25 interpreted SC#5 softly. If Phase 218's `/oc-audit` rerun finds typing-debt as a category, a separate phase adds the gate. Phase 214 doesn't.
- **Runtime conformance test (`isinstance(User(), IdentityProtocol)`):** D-21 deferred. Adds a third test file for marginal value; revisit if a `User` attribute drift ever causes a hard-to-diagnose failure.
- **Migrating admin/ to Identity**: D-09 keeps admin concrete because admin reads `password_hash`, `auth_provider`, `last_login_at` (NOT on Identity). If a future phase narrows admin's User access to the Identity surface (e.g., extracts user-management into a dedicated service that takes an Identity), revisit. Out of scope for v13.1.
- **`AuthProvider` Protocol + `AuthenticatedIdentity` dataclass unification**: the codebase has TWO Protocols touching identity now — `AuthProvider` (post-login token issuance, in `auth/providers/`) and `IdentityProtocol` (consumer-facing, in `core/`). They have different surfaces and different jobs; unification is a possible future cleanup but not load-bearing for v13.1. Track as a hypothetical, not a backlog item.
- **`Identity.tenant_id` field for multi-tenancy**: backlog item 999.6 (tenant scoping infrastructure for multi-tenant isolation) explicitly calls out adding tenant context to identity. Phase 214 does NOT pre-empt this — IdentityProtocol stays single-tenant. When 999.6 lands, IdentityProtocol grows a `tenant_id: UUID | None` field; that's a Protocol-extension exercise and architecture-guard tests don't need to change.
- **Removing the broadened `core/` guard's narrow Phase 212 sibling**: D-18 / Claude's Discretion punted the keep-or-replace decision to the planner. If the planner replaces, log it; the broader test subsumes the narrower one. If the planner keeps both, no harm.

</deferred>

---

*Phase: 214-identity-protocol-extract*
*Context gathered: 2026-04-27*

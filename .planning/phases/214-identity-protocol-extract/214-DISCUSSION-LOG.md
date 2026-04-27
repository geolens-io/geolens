# Phase 214: identity-protocol-extract - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in `214-CONTEXT.md` — this log preserves the alternatives considered.

**Date:** 2026-04-27
**Phase:** 214-identity-protocol-extract
**Areas discussed:** Protocol surface, Migration mechanism, Extension hook contract, Architecture guard

---

## Area Selection

| Option | Description | Selected |
|--------|-------------|----------|
| Protocol surface | What fields IdentityProtocol exposes; roles typing; `is_admin` helper | ✓ |
| Migration mechanism | Retype FastAPI deps vs per-site rewrites; allowlist for sites that keep concrete `User` | ✓ |
| Extension hook contract | What enterprise overlay registers (resolver fn / full Protocol); alignment with Phase 217 SAML | ✓ |
| Architecture guard | Regression tests for `core/identity.py` and cross-domain User-imports | ✓ |

**User's choice:** All four areas selected.

---

## Protocol surface

### Q1: Which fields should `IdentityProtocol` expose?

| Option | Description | Selected |
|--------|-------------|----------|
| Comprehensive (id, username, email, is_active, roles, created_at) | Full surface that mirrors what cross-domain code actually reads today; lets every cross-domain site annotate against `Identity` cleanly. | ✓ |
| Minimal (audit suggestion: id, email, is_active, roles) | Cleaner abstraction but `username`/`created_at` reads in admin/audit/maps/sources force those sites to keep concrete `User`. | |
| Comprehensive + `is_admin` helper | Comprehensive 6 fields plus a derived `is_admin` property; centralizes admin-role check. | |

**User's choice:** Comprehensive (Recommended).
**Notes:** Recorded as D-01 in CONTEXT.md. Audit-26-b suggested `is_admin` separately — rejected per D-02 because it's not an ORM column.

### Q2: How should `core/identity.py` type the `roles` field without re-creating a `core → modules.auth` import edge?

| Option | Description | Selected |
|--------|-------------|----------|
| Define slim `RoleProtocol` in core | Add `class RoleProtocol(Protocol): name: str` next to IdentityProtocol; type roles as `Sequence[RoleProtocol]`. Concrete `Role` ORM satisfies it structurally. | ✓ |
| `Sequence[str]` of role names | Simpler core but breaks current shape — `User.roles` is `Mapped[list[Role]]`, won't structurally satisfy `Sequence[str]`. Forces per-site rewrite of admin/service.py. | |
| `TYPE_CHECKING` import of `Role` | Zero runtime edge but typing-time arrow still appears; doesn't fully buy the boundary. | |

**User's choice:** Define slim `RoleProtocol` in core (Recommended).
**Notes:** Recorded as D-03. Mirrors `platform/extensions/protocols.py` "stdlib types only" pattern.

### Q3: How should the concrete `User` ORM model declare it satisfies `IdentityProtocol`?

| Option | Description | Selected |
|--------|-------------|----------|
| Implicit structural conformance | Don't change `User` at all; structural typing handles it. | ✓ |
| Explicit `isinstance` test in tests | One-line test asserting `isinstance(User(), IdentityProtocol)`; requires `@runtime_checkable`. | |
| `TYPE_CHECKING` annotation on User | Add a type-only check in `auth/models.py`; documents intent in the model file. | |

**User's choice:** Implicit structural conformance (Recommended).
**Notes:** Recorded as D-06. `User` ORM file is unchanged. D-21 documents the rejection of the runtime conformance test for the same reason.

### Continue check

| Option | Description | Selected |
|--------|-------------|----------|
| Next area | Move to Migration mechanism. | ✓ |
| More questions | Cover smaller surface decisions (alias name, `@runtime_checkable`, dep stub re-exports). | |

**User's choice:** Next area. Smaller surface decisions captured under Claude's Discretion in CONTEXT.md.

---

## Migration mechanism

### Q1: How do callers go from concrete `User` to `IdentityProtocol`?

| Option | Description | Selected |
|--------|-------------|----------|
| Retype FastAPI deps + per-site annotations | Two coordinated changes: dep return type → `Identity`, and ~51 caller files swap import + annotation. Realizes ROADMAP SC#2 literally. | ✓ |
| Retype deps only — leave caller annotations as `User` | Smaller diff but doesn't satisfy SC#2 ("all 51 cross-domain User import sites type against `IdentityProtocol`"). | |
| Type alias trick — alias User to Identity | No annotation rewrites in caller bodies; only imports change. Concrete `User` still leaks. | |

**User's choice:** Retype FastAPI deps + per-site annotations (Recommended).
**Notes:** Recorded as D-07. `Identity` (alias of `IdentityProtocol`) confirmed as the import name (D-05).

### Q2: Which sites legitimately KEEP concrete `User`?

| Option | Description | Selected |
|--------|-------------|----------|
| auth/ + admin/ + ORM-registration | auth/**, admin/router+service, audit/models.py (relationship), api/main.py, processing/ingest/tasks_raster.py:142, oauth/models.py:92. Everything else (~42 sites) migrates. | ✓ |
| Stricter — only auth/ keeps User | Even admin/ migrates; admin still queries `User` directly via SA but parameter annotations use Identity. More invasive. | |
| Looser — also keep audit/* and embed_tokens/* concrete | Smaller blast radius but reduces per-domain Protocol coverage. | |

**User's choice:** auth/ + admin/ + ORM-registration (Recommended).
**Notes:** Recorded as D-09 with explicit allowlist enumeration. ~42 sites migrate, 9 logical sites stay concrete.

### Continue check

| Option | Description | Selected |
|--------|-------------|----------|
| Next area | Move to Extension hook contract. | ✓ |
| More questions | Cover commit decomposition, `is_active` access in deps. | |

**User's choice:** Next area. Commit decomposition captured under Claude's Discretion in CONTEXT.md.

---

## Extension hook contract

### Q1: How should Phase 214 design the identity extension seam (`IDENT-03`)?

| Option | Description | Selected |
|--------|-------------|----------|
| New `IdentityExtension` Protocol, minimal surface | One method `resolve_identity_from_token(token, request, db) -> Identity \| None`; default impl returns None. Mirrors `get_branding_extension()` pattern. | ✓ |
| Extend existing `AuthExtension` Protocol | Add the resolve method to `AuthExtension`. Keeps surface flat but mixes concerns. | |
| Full `IdentityProvider` Protocol with multiple methods | `resolve`, `provision`, `list_methods` — pre-empts Phase 217 needs. Risk: over-design. | |
| Defer — empty Protocol scaffold | `class IdentityExtension(Protocol): ...` with no methods. Doesn't fully meet IDENT-03. | |

**User's choice:** New `IdentityExtension` Protocol, minimal surface (Recommended).
**Notes:** Recorded as D-12. Default impl returns None (D-14). Companion `provision_identity` and `list_identity_methods` deferred for future phases.

### Q2: Where does `IdentityExtension` actually get CALLED?

| Option | Description | Selected |
|--------|-------------|----------|
| Wire into `get_optional_user` / `get_current_user` | Between API-key path and JWT path; if extension returns non-None, that wins; else fall through. Default returns None → zero behavior change. | ✓ |
| Defer wiring to Phase 217 | Phase 214 only adds Protocol + accessor; Phase 217 wires the call. IDENT-03 only half-met. | |
| New dedicated FastAPI dep `get_extension_identity()` | Creates two parallel auth paths. | |

**User's choice:** Wire into `get_optional_user` / `get_current_user` (Recommended).
**Notes:** Recorded as D-15. Order: API key → extension → JWT → anonymous. API-key path is NOT routed through the extension (D-17).

### Continue check

| Option | Description | Selected |
|--------|-------------|----------|
| Next area | Move to Architecture guard. | ✓ |
| More questions | Cover registration key naming, error-handling, `get_identity_methods()` companion. | |

**User's choice:** Next area. The remaining details (registration under `_extensions["identity"]`, default-impl location, no companion `list_identity_methods()`) recorded as D-13/D-14 and deferred-idea entries.

---

## Architecture guard

### Q1: What architecture-guard tests does Phase 214 add to `test_layering.py`?

| Option | Description | Selected |
|--------|-------------|----------|
| Two tests — broaden core/ guard + cross-domain User-import allowlist | Test 1 broadens Phase 212's settings-only guard to all `app.modules.*`. Test 2 enforces cross-domain User-import allowlist via `git grep`. | ✓ |
| One test — cross-domain allowlist only | Skip broadening the core/ guard; defer to Phase 218. | |
| Three tests — above + runtime conformance assert | Adds `assert isinstance(User(), IdentityProtocol)`. Marginal value. | |

**User's choice:** Two tests (Recommended).
**Notes:** Recorded as D-18, D-20. The narrow Phase 212 guard may be replaced or kept alongside the broader version — planner picks (Claude's Discretion).

### Q2: How should the cross-domain User-import allowlist be expressed?

| Option | Description | Selected |
|--------|-------------|----------|
| Git pathspec exclusions | `:!path` arguments on `git grep`; same pattern Phase 213-03 already uses. | ✓ |
| Python-side allowlist set | `git grep` without exclusions, then filter in Python. More flexible (per-line allowlist) but diverges from convention. | |

**User's choice:** Git pathspec exclusions (Recommended).
**Notes:** Recorded as D-19. Concrete invocation written into CONTEXT.md including the explicit `:!` list.

---

## Done check

| Option | Description | Selected |
|--------|-------------|----------|
| I'm ready for context | Decisions are crisp; write CONTEXT.md and prepare for /gsd-plan-phase 214. | ✓ |
| Explore more gray areas | Surface 2–4 additional gray areas (commit decomposition, `Identity` `__hash__`/`__eq__`, SQL-filter-only User accesses). | |

**User's choice:** I'm ready for context.
**Notes:** Commit decomposition captured under Claude's Discretion (4-commit pattern mirroring 212/213). SQL-filter `UserRole.user_id == user.id` access captured in D-08 (UserRole/Role imports stay concrete). `Identity.__hash__`/`__eq__` not raised — Python Protocols inherit `object.__hash__` by default; structural conformance is enough for the use cases at hand.

---

## Claude's Discretion

The following decisions were left to Claude / the planner (recorded in CONTEXT.md "Claude's Discretion" subsection):

- **Commit decomposition** — likely 4 atomic commits mirroring 212/213 (Protocol introduction → dep retype + extension wire-in → caller migration → architecture guard tests + verification gate). Planner may collapse, split, or reorder; the only hard ordering constraint is that callers can't migrate before `Identity` exists, and architecture tests must land last (they fail until the migration is complete).
- **Module docstring wording** in `core/identity.py` — keep the spirit of `platform/extensions/protocols.py`'s "stdlib types only" plus a Phase-214 / IDENT-01..03 reference. Planner picks exact wording.
- **Whether to refactor cross-domain helpers during the migration** — default NO. Trivial dead-import cleanup is allowed; bigger refactors deferred.
- **Whether to keep BOTH the narrow Phase 212 guard AND the broadened Phase 214 guard** — default REPLACE; planner may keep both if test failure messages diverge usefully.
- **`Request` parameter on `IdentityExtension.resolve_identity_from_token`** — default keep; drop if planner determines Phase 217 SAML won't need it.
- **Test marker** — both new architecture tests use `@pytest.mark.architecture` (already registered).

## Deferred Ideas

(Captured in CONTEXT.md `<deferred>` section; replicated here for log completeness.)

- `is_admin` Protocol field
- `IdentityExtension.provision_identity(claims)` JIT-provisioning hook
- `IdentityExtension.list_identity_methods()` admin-UI surface
- API-key resolution via the extension
- Pyright/mypy CI gate
- Runtime `isinstance(User(), IdentityProtocol)` test
- Migrating `admin/` to Identity (admin reads non-Identity fields)
- Unifying `AuthProvider` Protocol + `AuthenticatedIdentity` dataclass with `IdentityProtocol`
- `Identity.tenant_id` field for multi-tenancy (backlog 999.6)
- Removing the broadened core/ guard's narrow Phase 212 sibling

# Phase 219: oc-audit-remediate-idp-mapping — Research

**Researched:** 2026-04-29
**Domain:** Open-core boundary enforcement (Pydantic schema validators + service-layer edition gating + audit-doc amendment)
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Schema gate (write-path)**
- **D-01:** Add `@model_validator(mode="after")` on **both** `OAuthProviderCreate` and `OAuthProviderUpdate` in `backend/app/modules/auth/oauth/schemas.py`. Each validator raises `ValueError("Group-based role mapping requires the GeoLens Enterprise overlay")` when (`group_claim` is non-None) OR (`group_role_mapping` is a non-empty dict) AND `not is_enterprise()`.
- **D-02:** Treat `group_role_mapping={}` and `group_role_mapping=None` as **allowed in community** ("no mapping" / "clear mapping"). Only **non-empty** mapping triggers the gate.
- **D-03:** Verbatim error message: `"Group-based role mapping requires the GeoLens Enterprise overlay"` — do not reword.
- **D-04:** Validator imports `is_enterprise` from `app.core.edition` at module top of `schemas.py`.

**Service gate (runtime application)**
- **D-05:** Gate at the call site `backend/app/modules/auth/oauth/service.py:261-263`, NOT inside `_resolve_role()`. Pattern: `if is_enterprise(): role_name = _resolve_role(...) else: role_name = provider.default_role`.
- **D-06:** No log/warning when the runtime gate fires in community.
- **D-07:** Do NOT touch `_resolve_role()` itself. Pure helper, signature/behavior unchanged.

**Test strategy**
- **D-08:** Split `test_group_role_mapping` (`backend/tests/test_oauth.py:458`) into 2 tests: a community variant (mapping IGNORED → default role applied; provider seeded directly via SQLAlchemy ORM to bypass the new D-01 validator) and an enterprise variant (mapping APPLIED; runs under `init_edition(["enterprise"])`).
- **D-09:** Add a new `TestIdpRoleMappingGate` class with 4-5 schema-validator tests covering Create + Update reject in community, Create accept in enterprise, Update accept in enterprise, and the `group_role_mapping={}` carve-out.
- **D-10:** Edition-state isolation between tests — `try/finally` saves and restores `app.core.edition._info`, OR a shared fixture reusing the existing `_clean_edition` autouse pattern from `backend/tests/test_edition.py:18-22`.

**Audit re-run + v13.1-close amendment**
- **D-11:** Re-run `/oc-audit`. The dated output file is **discarded** (not committed); only the milestone-close artifact is committed.
- **D-12:** **Amend** `docs-internal/audits/oc-separation-audit-v13.1-close.md` in place. Edits: replace ⚠ MILESTONE CLOSE BLOCKED banner (line 20) with ✅ MILESTONE CLOSE VERIFIED, preserve original BLOCKED narrative as a "Pre-remediation state (2026-04-29)" subsection; rewrite Boundary Integrity row in Scorecard; flip three 🔴 rows in Section 1 to 🟢; update Section 8 grade-delta `Met?` column to ✅; append "Closed by Phase 219 (2026-04-29)" to P1 Residual Triage row 1.
- **D-13:** Multi-layer verification gate: (1) lint + tests green at ≥1965/1965 + 5 new tests pass; (2) `/oc-audit` re-run yields Boundary ≥ A−; (3) doc no longer contains BLOCKED heading and contains VERIFIED heading; (4) manual smoke — POST `group_role_mapping={"admins":"admin"}` to `/settings/oauth-providers/` returns 422 in community, succeeds with `GEOLENS_EDITION=enterprise`.

**Plan structure**
- **D-14:** **Single plan** (`219-01-gate-idp-role-mapping`). Sequential, tightly coupled, ~1d.
- **D-15:** 4 atomic commits in order: (1) schema validators, (2) service gate, (3) tests, (4) audit re-run + v13.1-close amendment + deferred-items closure marker.

### Claude's Discretion

- `OAuthProviderUpdate.provider_type='saml'` redundant rejection — extension is allowed, not required.
- Validator method name (`_validate_enterprise_features` / `_validate_idp_mapping_gate` / similar) — not mandated.
- Audit re-run timing (after commit 3 or after commit 4) — either acceptable.
- `init_edition` test fixture vs inline `try/finally` — planner may introduce a shared `enterprise_edition` pytest fixture in `conftest.py` if it cleans up D-10 boilerplate.
- Optional defense-in-depth log line in `service.py:261-263` else branch — D-06 chose silence; low-stakes flip allowed.

### Deferred Ideas (OUT OF SCOPE)

- Removing `group_claim` / `group_role_mapping` columns from `oauth/models.py:82-84` — kept as forward-compat scaffolding for the SAML enterprise overlay (Phase 217 D-04).
- Frontend changes — UI is already enterprise-route-gated via `AdminSamlPage.tsx:28-33` `useEdition()` redirect; audit graded UI 🟢 Clean.
- DB migrations — columns stay; only write-path acceptance + runtime application change.
- Triaging the other 2026-04-27 audit findings (Marketplace billing P1, Branding UI key mismatch P1) — already triaged in Phase 218.
- A new `v13.1.1-close.md` or `v13.1-close-amended.md` file — explicitly rejected; amend in place.
- `/gsd-complete-milestone` — separate next step, not part of Phase 219.
- Modifying the `/oc-audit` skill — canonical, consume only.
- Tenant-scoped edition.
- Optional log line on the community runtime gate (D-06 alternative).
- `provider_type='saml'` write rejection in community.
- Re-grading already-green audit findings.
- Producing a v13.2 baseline audit.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| AUDIT-V1 | After milestone closes, re-running `/oc-audit` produces grades meeting or exceeding Boundary ≥ A−, Seam Quality ≥ B, OSS Surface ≥ C. Audit output committed under `docs-internal/audits/oc-separation-audit-v13.1-close.md`. | The audit's Section 1 (lines 53-55) prescribes the exact fix per file. The schema validator + service gate + audit re-run + close-doc amendment are the four-step path that lifts Boundary B− → A− while leaving Seam Quality (B, ✅) and OSS Surface (A−, ✅) untouched. Verified: line numbers for all three target files match `main` HEAD as of audit run (`oauth/schemas.py:121-129, 240-248, 145-169, 145`; `oauth/service.py:169-179, 261-263`; `oauth/models.py:82-84`). No drift since audit was written. |
</phase_requirements>

## Summary

The audit `docs-internal/audits/oc-separation-audit-v13.1-close.md` is the source-of-truth research artifact. Section 1 already prescribes the exact code change per file; CONTEXT.md locks all design decisions. This research validates the prescription against current `main` and surfaces the implementation-level nuances the audit doesn't address: how to bypass the new D-01 validator inside the D-08 community test (direct ORM insert, not `create_provider()`), how to isolate `init_edition` mutations between tests (reuse the `_clean_edition` autouse fixture pattern from `backend/tests/test_edition.py:18-22`), and the verbatim doc-amendment edit list (D-12).

**Validation:**

- **Line numbers match `main`.** `oauth/schemas.py` `_validate_per_type` is at line 145 (matches CONTEXT.md D-01); `group_claim` at 121-129 / 240-248 (matches Section 1); `oauth/service.py:261-263` is the `_resolve_role` call site inside `find_or_create_oauth_user` (verified); `_resolve_role` definition at 169-179; `oauth/models.py:82-84` columns `default_role` / `group_claim` / `group_role_mapping` (verified). No drift.
- **`is_enterprise()` is a cheap singleton read** at `backend/app/core/edition.py:50-52` — per-request validator invocation is safe.
- **Pydantic imports already include `model_validator`** at `oauth/schemas.py:8` — only the new `from app.core.edition import is_enterprise` import is needed.
- **Pattern precedent in repo is correct.** The existing `_validate_per_type` model_validator at `oauth/schemas.py:145-169` is the exact shape the new validators will mirror: `@model_validator(mode="after")`, raises `ValueError`, returns `self`.
- **`_resolve_role()` is a pure helper** with one and only one call site (`service.py:261`) — gating at the call site cleanly contains the edition coupling.
- **No migrations reference these columns** — confirmed via `grep -rn "group_claim\|group_role_mapping" backend/migrations/` = 0 hits.

**New nuances the audit/CONTEXT.md doesn't cover:**

1. **D-08 community test must NOT call `_create_test_provider()`** as it stands at `test_oauth.py:344-360`, because that helper builds an `OAuthProviderCreate` and runs it through `create_provider()` — which after D-01 will REJECT non-empty `group_role_mapping` in community. The community test must seed the provider via direct SQLAlchemy `OAuthProvider(...)` instantiation + `db.add()` + `db.flush()`. This simulates the legacy/direct-DB-write scenario the D-05 service gate is defending against.
2. **D-10 edition reset has a clean precedent already in the repo.** `backend/tests/test_edition.py:11-22` defines `_reset_edition()` and an `autouse=True` `_clean_edition` fixture. CONTEXT.md's Claude-discretion note allows a shared fixture; planner should choose between (a) a shared fixture in `conftest.py`, (b) a local autouse fixture in `test_oauth.py`, or (c) inline `try/finally`. **Recommendation:** local fixture mirroring `test_edition.py:18-22` to avoid coupling unrelated test files to the global state-reset.
3. **Audit re-run is non-deterministic in scope.** The `/oc-audit` skill writes a date-named file (`oc-separation-audit-{YYYYMMDD}.md`) that — per D-11 — is discarded. Planner must explicitly capture the Boundary Integrity grade from the run output text without committing the file. If the planner forgets D-11 and commits the date-named file, the repo gains a redundant artifact next to the close doc.
4. **Doc-amendment touches 5 distinct sections of the same file** — banner (line 20), Scorecard (line 9), Section 1 (lines 53-55), Section 8 grade-delta table (lines 363-372), P1 Residual Triage row 1 (line 408). All in `docs-internal/audits/oc-separation-audit-v13.1-close.md`. The Executive Summary's narrative ("Boundary B−...") at line 41 also references the unresolved P0 — minor wording update needed for internal consistency.
5. **The schema validator ordering matters.** Both `OAuthProviderCreate` and `OAuthProviderUpdate` already have a `@model_validator(mode="after")` (`_validate_per_type` on Create only). On Update there is no model_validator yet — the new one is the first. Per Pydantic v2, multiple `mode="after"` validators run in declaration order, and ordering is not load-bearing here (the new check is independent of `_validate_per_type`'s SAML field-completeness check).

**Primary recommendation:** Execute the four commits in CONTEXT.md D-15 order. Use the local-fixture pattern from `test_edition.py` for D-10 isolation. Bypass `_create_test_provider()` in the D-08 community variant via direct ORM insert. Treat the audit doc amendment as a single-file 5-section diff per D-12.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Reject `group_claim` / non-empty `group_role_mapping` writes in community | API / Backend (Pydantic schema layer) | — | Schema validators are FastAPI's request-validation layer; rejecting at the boundary returns 422 before any service logic runs. |
| Suppress IdP→role mapping at OAuth login in community | API / Backend (service orchestration layer) | — | `find_or_create_oauth_user` is the orchestration function; defense-in-depth against rows inserted before this gate shipped or via direct DB access. |
| Provide `is_enterprise()` boolean | API / Backend (`core/edition.py` singleton) | — | Already established. Both schema validator and service gate consume the same accessor. |
| UI gating of `group_claim` / `group_role_mapping` fields | Frontend Server (route gate) | Browser (component render) | Already shipped: `AdminSamlPage.tsx:28-33` redirects via `useEdition()`; the SAML provider editor is the only UI surface for these fields. **No work for this phase.** |
| Audit re-grading | Audit tooling (`/oc-audit` skill, parallel subagent grader) | — | Skill is canonical (Phase 218 D-01). Phase 219 invokes it; it writes a dated artifact that is then discarded per D-11. |
| Milestone-close documentation | `docs-internal/audits/` (close-artifact layer) | — | `oc-separation-audit-v13.1-close.md` is the milestone-bound artifact (vs the dated audit-run files). Amending in place per D-12 keeps a single canonical close artifact. |

## Standard Stack

This phase modifies existing code in established stack components. No new dependencies; no library research required.

| Component | Source | Purpose | Already in use |
|-----------|--------|---------|----------------|
| Pydantic v2 `@model_validator(mode="after")` | `pydantic` (already a backend dep) | Multi-field write-path validator that runs after type coercion and field validators | `oauth/schemas.py:145` (`_validate_per_type`) |
| `is_enterprise()` | `app.core.edition` (`backend/app/core/edition.py:50`) | Boolean read of edition singleton | `app/platform/extensions/guards.py:10` (`require_enterprise`); `app/modules/settings/router.py:100` |
| `init_edition([...])` | `app.core.edition` | Test-side mutation of edition singleton | `backend/tests/test_saml_overlay.py:239`; `backend/tests/test_edition.py:34-87` |
| Direct SQLAlchemy ORM insert | existing pattern | Bypass schema validators in tests to seed legacy/direct-DB-write rows | Used widely across `backend/tests/`; the D-08 community variant uses this |

**Installation:** none — all libraries already present.

**Version verification:** N/A (no new dependencies).

## Architecture Patterns

### System Flow Diagram

```
WRITE PATH (admin POST /settings/oauth-providers/)
   │
   ▼
FastAPI route handler
   │
   ▼
Pydantic OAuthProviderCreate / OAuthProviderUpdate
   │  ├── field_validator (URL shape) — pre-existing
   │  ├── model_validator _validate_per_type (SAML/OAuth field completeness) — pre-existing
   │  └── model_validator _validate_idp_mapping_gate (NEW — D-01)   ← gate fires here in community
   │       └── if (group_claim or non-empty group_role_mapping) AND not is_enterprise():
   │             raise ValueError("Group-based role mapping requires the GeoLens Enterprise overlay")
   ▼ (if validation passes)
service.create_provider / service.update_provider — writes to DB
   ▼
DB row persisted

LOGIN PATH (OAuth callback)
   │
   ▼
oauth/router.py callback handler
   │
   ▼
service.find_or_create_oauth_user(db, provider, userinfo, token)
   │  ├── extract groups from userinfo via provider.group_claim (existing line 203-206)
   │  ├── lookup or create user (existing)
   │  └── role resolution at service.py:261-263 (CHANGED — D-05):
   │       if is_enterprise():
   │           role_name = _resolve_role(groups, provider.group_role_mapping, provider.default_role)
   │       else:
   │           role_name = provider.default_role
   │  └── assign role to new user
```

### Project Structure (unchanged — modifying existing files)

```
backend/app/modules/auth/oauth/
├── schemas.py          # ADD: 2× model_validator (Create + Update)
├── service.py          # ADD: edition gate around _resolve_role call site (line 261-263)
└── models.py           # NO CHANGE — columns kept as forward-compat scaffolding

backend/tests/
├── test_oauth.py       # SPLIT existing test_group_role_mapping; ADD TestIdpRoleMappingGate class
└── test_saml_overlay.py # No changes — referenced as fixture pattern only

docs-internal/audits/
├── oc-separation-audit-v13.1-close.md       # AMEND in place (D-12; 5 sections)
└── oc-separation-deferred-items-20260426.md # Optional closure marker if a row tracks IdP-mapping gate
```

### Pattern 1: Mirror the existing `_validate_per_type` model_validator

**What:** Copy the exact decorator and shape used at `oauth/schemas.py:145-169`.
**When to use:** New model_validator on `OAuthProviderCreate` and `OAuthProviderUpdate`.
**Example:**

```python
# Source: backend/app/modules/auth/oauth/schemas.py:145-169 (existing)
# New validator follows this shape exactly.

from app.core.edition import is_enterprise  # NEW import at module top

class OAuthProviderCreate(BaseModel):
    # ... fields unchanged ...

    @model_validator(mode="after")
    def _validate_per_type(self):
        # ... existing SAML/OAuth field-completeness logic ...
        return self

    @model_validator(mode="after")
    def _validate_idp_mapping_gate(self):
        """Reject IdP→role mapping fields in community edition.

        ``group_claim`` and a non-empty ``group_role_mapping`` together implement
        IdP-driven role assignment, which is classed as Enterprise per
        ``docs-internal/GTM/repo-split.md``. The runtime branch in ``service.py:261-263``
        also drops the mapping in community, but rejecting writes here returns a
        clear 422 to admins instead of silently storing dead data.

        ``group_role_mapping={}`` is allowed (semantic: clear mapping); only a
        non-empty dict triggers the gate.
        """
        gates_set = (self.group_claim is not None) or (
            isinstance(self.group_role_mapping, dict)
            and len(self.group_role_mapping) > 0
        )
        if gates_set and not is_enterprise():
            raise ValueError(
                "Group-based role mapping requires the GeoLens Enterprise overlay"
            )
        return self
```

The Update variant is identical structurally; the field reads are the same names.

### Pattern 2: Service-layer call-site gate

**What:** Wrap the `_resolve_role` call at `service.py:261-263` in `if is_enterprise(): ... else: role_name = provider.default_role`.
**When to use:** Only here. `_resolve_role` itself stays a pure helper (D-07).
**Example:**

```python
# Source: backend/app/modules/auth/oauth/service.py:261-263 (current)
# Resolve role from group mapping
role_name = _resolve_role(
    groups, provider.group_role_mapping, provider.default_role
)

# After (Phase 219, D-05):
from app.core.edition import is_enterprise  # NEW import at module top

# ... inside find_or_create_oauth_user, around line 261 ...
# Resolve role from group mapping (Enterprise only — D-05 / Phase 219).
if is_enterprise():
    role_name = _resolve_role(
        groups, provider.group_role_mapping, provider.default_role
    )
else:
    role_name = provider.default_role
```

### Pattern 3: Edition-state isolation in tests (mirror `test_edition.py`)

**What:** Local autouse fixture that snapshots and restores `app.core.edition._info`.
**When to use:** Any test file that calls `init_edition(...)`.
**Example:**

```python
# Source: backend/tests/test_edition.py:11-22 (existing)
# Reuse pattern in test_oauth.py for the new TestIdpRoleMappingGate + the
# enterprise variant of the split test_group_role_mapping.

import pytest


def _reset_edition():
    import app.core.edition as ed_mod
    ed_mod._info = None


@pytest.fixture
def enterprise_edition(monkeypatch):
    """Initialize edition singleton to enterprise for the test scope."""
    from app.core.edition import init_edition

    monkeypatch.setenv("GEOLENS_EDITION", "enterprise")
    saved = _save_edition_info()
    init_edition([])
    try:
        yield
    finally:
        _restore_edition_info(saved)


def _save_edition_info():
    import app.core.edition as ed_mod
    return ed_mod._info


def _restore_edition_info(saved):
    import app.core.edition as ed_mod
    ed_mod._info = saved
```

The `monkeypatch.setenv` form ensures `GEOLENS_EDITION` is reset after the test (pytest teardown), and the explicit `_info` save/restore handles the case where another test ran `init_edition` differently. The community-variant test does not need this fixture — it relies on the module-default state (`_info=None` → `is_enterprise()` returns `False`).

### Anti-Patterns to Avoid

- **Don't gate inside `_resolve_role()`.** It's a pure helper used only by `find_or_create_oauth_user`. Moving the edition check inside spreads boundary logic into a single-purpose mapper. The audit Section 1 row 2 explicitly recommends gating at the call site (line 54 of audit).
- **Don't add a frontend gate.** UI is already enterprise-route-gated at `AdminSamlPage.tsx:28-33`. Audit graded UI 🟢. Adding a second frontend check is wasted scope.
- **Don't drop the columns.** They are reused by the SAML enterprise overlay (Phase 217 D-04 reads `group_claim` + `group_role_mapping` on SAML providers). Dropping them breaks SAML JIT provisioning in enterprise.
- **Don't reword the error message.** D-03 locks the verbatim string `"Group-based role mapping requires the GeoLens Enterprise overlay"`. Tests assert against this exact text.
- **Don't commit the dated `/oc-audit` output file.** D-11 says discard. Committing it produces a redundant artifact next to the close doc.
- **Don't produce a new close-doc file.** D-12 amends in place. A second file (`v13.1.1-close.md`) splits the milestone-close story.
- **Don't run `_create_test_provider()` for the community-variant runtime test.** That helper goes through `create_provider()` → `OAuthProviderCreate`, which post-D-01 rejects non-empty `group_role_mapping` in community. Use direct ORM insert.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Reject a field combination at write time | Custom dependency-injection guard or pre-route check | Pydantic `@model_validator(mode="after")` already used by this module | Co-located with the schema, runs in the standard FastAPI request-validation pipeline, returns the standard 422 envelope with no custom error handling. |
| Edition detection at runtime | `os.environ.get("GEOLENS_EDITION") == "enterprise"` re-reads | `is_enterprise()` from `app.core.edition` | Singleton-backed; single source of truth; survives env mutation; consumed everywhere else in the codebase. |
| Edition-state isolation in tests | Custom contextmanagers per test | Reuse the `_reset_edition()` + autouse fixture pattern from `backend/tests/test_edition.py:11-22` | Already in the repo; consistent with the existing edition-test convention; minimal code. |
| Enterprise-mode test setup | Hand-build environment + extension fixtures | `init_edition(["enterprise"])` per `test_saml_overlay.py:239`, optionally combined with `monkeypatch.setenv("GEOLENS_EDITION", "enterprise")` | Established pattern; `init_edition` is the documented public hook for forcing an edition. |
| Audit re-grading | Hand-graded comparison against rubric | `/oc-audit` skill at `.claude/commands/oc-audit.md` | Canonical (Phase 218 D-01); deterministic 6-subagent run; consumes itself in `main` HEAD without any code changes from this phase. |

**Key insight:** Every primitive needed for this phase already exists in the repo. The phase is composition + amendment, not invention.

## Runtime State Inventory

This is **not** a rename / refactor / migration phase. It adds new boundary checks; it does not change names or schemas of existing entities. No runtime state needs to migrate.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | Existing OAuth provider rows in dev/staging DBs that already have `group_claim` or `group_role_mapping` populated. The D-01 schema validator does NOT retroactively reject existing rows; only new writes/updates are rejected. The D-05 service gate provides runtime defense for these legacy rows. | None — handled by the D-05 service gate at runtime. No data migration. |
| Live service config | None. There is no externally-stored configuration that mirrors `group_claim` / `group_role_mapping` keys. | None. |
| OS-registered state | None. | None — verified by no scheduled tasks, plists, or systemd units reference these field names. |
| Secrets/env vars | `GEOLENS_EDITION` env var is the override knob; no rename. The new code reads `is_enterprise()` which already reads this var. `.env.example` does NOT yet document `GEOLENS_EDITION` (Action Item P2 in audit §4) — out of scope here. | None — env-var name unchanged. |
| Build artifacts | None. The change is in two `.py` files + one test file + one Markdown file. No package boundary changes, no entry-point changes. | None. |

**Nothing-found categories explicit:** Live service config, OS-registered state, build artifacts — all empty. Verified by audit Section 1 line 64 (`catalog/` clean: "no `Credential`/`StoredSecret`/`ConnectorConfig` model") and by absence of any `*.plist` / `*.service` / scheduler hits in the repo.

## Common Pitfalls

### Pitfall 1: Test-state pollution from `init_edition`

**What goes wrong:** `init_edition(["enterprise"])` mutates the module-level `_info` singleton. If a test calls it and doesn't reset, all subsequent tests in the run see `is_enterprise() == True`. The community-variant of `test_group_role_mapping` (D-08) would then falsely pass even if the D-05 service gate were missing.
**Why it happens:** `app.core.edition._info` is module-level state with no auto-reset between tests.
**How to avoid:** Use the `_reset_edition` autouse fixture pattern from `backend/tests/test_edition.py:18-22` — wrap any enterprise-test with snapshot/restore of `_info`, OR set `_info = None` in an autouse fixture before each test in the class.
**Warning signs:** Tests pass when run in isolation but fail when run after `test_saml_overlay.py`; the community variant of the runtime test passes mysteriously.

### Pitfall 2: D-08 community test using `_create_test_provider()`

**What goes wrong:** The existing `_create_test_provider()` helper at `test_oauth.py:344-360` calls `create_provider(db, OAuthProviderCreate(**defaults))`. After D-01 ships, passing `group_claim="groups"` + non-empty `group_role_mapping` through that helper raises `ValueError` at the schema layer. The community runtime test cannot use this helper for its setup.
**Why it happens:** The schema validator is the very gate the test is verifying defense-in-depth around.
**How to avoid:** In the community variant, instantiate the `OAuthProvider` SQLAlchemy model directly: `db.add(OAuthProvider(slug=..., group_claim="groups", group_role_mapping={...}, ...)); await db.flush()`. This simulates the legacy/direct-DB-write scenario the D-05 gate defends.
**Warning signs:** The community test setup raises `ValidationError` or `ValueError` during setup before reaching `find_or_create_oauth_user`.

### Pitfall 3: D-02 carve-out for `group_role_mapping={}`

**What goes wrong:** A naïve check `if self.group_role_mapping is not None: ...` rejects the documented "clear mapping" pattern (`OAuthProviderUpdate(group_role_mapping={})`) in community — breaking the workflow described at `oauth/schemas.py:248`.
**Why it happens:** Pydantic distinguishes "field omitted" from "field set to empty dict"; both are valid clear-mapping patterns post-downgrade.
**How to avoid:** Check `isinstance(value, dict) and len(value) > 0` for the trigger. Only non-empty dicts fire the gate.
**Warning signs:** A community admin trying to clear a previously-set mapping (after a downgrade) gets 422 instead of success. Add an explicit test for this carve-out (the D-09 fifth test variant `test_create_with_empty_mapping_allowed_in_community`).

### Pitfall 4: Audit re-run grade variance

**What goes wrong:** The audit's grader uses model-driven analysis across 6 subagents. It is not byte-deterministic; the rubric output text and column-of-evidence may vary slightly between runs. The Boundary letter grade IS the load-bearing artifact (must be ≥ A−), not the prose.
**Why it happens:** LLM-driven graders are not reproducible at the token level.
**How to avoid:** Capture only the Boundary Integrity grade letter and the per-finding 🔴/🟡/🟢 markers from Section 1. Do not assert against rubric prose. If grade lands at A (not A−), that exceeds target — accept and move on. If grade lands at B+ for unrelated reasons, the run revealed new boundary issues outside this phase's scope; triage as a follow-up phase.
**Warning signs:** Boundary grade letter is missing from the run output (rare); the section structure is incomplete (re-run before deciding).

### Pitfall 5: Doc-amendment narrative drift

**What goes wrong:** Amending only the Scorecard / Section 1 / Section 8 cells and forgetting the Executive Summary (line 41) and the BLOCKED banner narrative leaves the doc internally inconsistent. Future readers see "Boundary B− is the sole blocker" in the summary and "Boundary A− ✅" in the table.
**Why it happens:** The audit doc has the same fact stated in multiple sections for emphasis.
**How to avoid:** D-12 enumerates the five edits explicitly. Do all five. Add a brief "Pre-remediation state (2026-04-29)" subsection that quotes the original BLOCKED banner so the audit trail of the gap and its resolution is co-located.
**Warning signs:** A grep for "BLOCKED" in the post-amendment doc returns hits outside the preserved subsection; a grep for "B−" returns hits where "A−" should appear.

## Code Examples

(See Pattern 1 / Pattern 2 / Pattern 3 above — the canonical examples are pulled from existing in-repo patterns at `oauth/schemas.py:145-169`, `oauth/service.py:261-263`, and `test_edition.py:11-22`.)

### Smoke-test commands (D-13 layer 4)

```bash
# Community-mode rejection (must return 422):
GEOLENS_EDITION=community curl -X POST http://localhost:8080/settings/oauth-providers/ \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"slug":"test","display_name":"T","provider_type":"oidc","client_id":"a","client_secret":"b","group_role_mapping":{"admins":"admin"}}'

# Enterprise-mode acceptance (must return 200/201):
GEOLENS_EDITION=enterprise curl -X POST http://localhost:8080/settings/oauth-providers/ \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"slug":"test","display_name":"T","provider_type":"oidc","client_id":"a","client_secret":"b","group_role_mapping":{"admins":"admin"}}'
```

## State of the Art

This phase does not introduce a new approach. It applies the *defense-in-depth schema + service gate* pattern that is already used elsewhere in the codebase (e.g., `_ENTERPRISE_ONLY_TABS` constant + the 404 gate at `settings/router.py:62, 90-104` is the same pattern at the route level).

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single-layer route gate (`Depends(require_enterprise)`) | Schema + service gate (this phase) | 2026-04-29 (Phase 219) | Provides defense-in-depth: write-path 422 for new bad data; runtime no-op for legacy/direct-DB rows. Required because the columns persist (forward-compat scaffolding for the SAML overlay). |

**Deprecated/outdated:** none.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| (none) | All factual claims in this research are verified directly against `main` HEAD or cited from CONTEXT.md / the audit doc. | — | — |

**No assumed claims.** This research validates the audit's prescription against current `main` line numbers and pulls implementation patterns from in-repo precedent. No external doc lookups, no library version assumptions.

## Open Questions

1. **Should the planner introduce a shared `enterprise_edition` fixture in `backend/tests/conftest.py`?**
   - What we know: CONTEXT.md Claude's Discretion bullet 4 allows it. `test_edition.py` already has the reset pattern locally; `test_saml_overlay.py:222-277` has its own setup with `init_edition` + `_info` save/restore.
   - What's unclear: How many future tests will need the fixture. If only Phase 219 tests need it, a local autouse is simpler; if Phase 220+ tests will gate on edition, a `conftest.py` fixture pays off.
   - Recommendation: **Local autouse fixture in `test_oauth.py`** for now. Re-evaluate when the next edition-aware test phase lands.

2. **Should the doc-amendment closure marker for `oc-separation-deferred-items-20260426.md` be inserted, even though no row currently tracks the IdP-mapping gate as a P2 deferred item?**
   - What we know: The deferred-items doc tracks Marketplace billing demoted from P1 → P2 (added 2026-04-29 — visible at line 34). It does NOT have a row for the IdP-mapping gate (because that gate was Phase 218 → Phase 219 fix-now, not deferred).
   - What's unclear: Whether to add a "Closed by Phase 219" historical entry or skip.
   - Recommendation: **Skip** — adding a row to the deferred-items doc for an item that was never on the deferred list creates noise. CONTEXT.md scope item 5 says "if relevant row exists"; it does not. The audit doc amendment (D-12) is sufficient close-trail.

3. **What if the audit re-run lands at A or A+ instead of A−?**
   - What we know: D-13 verification gate is "Boundary ≥ A−"; A and A+ both meet.
   - What's unclear: How to reflect a *higher* grade in the close doc.
   - Recommendation: Update D-12 edits to use the actual grade. The Section 8 grade-delta `Met? ✅` column is satisfied either way.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.13 + Pydantic v2 | Schema validator (D-01) | ✓ | per `backend/pyproject.toml` | — |
| `pytest-asyncio` | Async test variants (D-08) | ✓ | (already in dev deps) | — |
| `app.core.edition.is_enterprise` + `init_edition` | Service gate (D-05) + test setup (D-08) | ✓ | `backend/app/core/edition.py:27, 50` | — |
| `/oc-audit` skill | Audit re-run (D-11) | ✓ | `.claude/commands/oc-audit.md` (canonical) | — |
| `docs-internal/audits/oc-separation-audit-v13.1-close.md` | Doc amendment (D-12) | ✓ | committed | — |

**Missing dependencies with no fallback:** none.

**Missing dependencies with fallback:** none.

## Validation Architecture

> Nyquist gate: required because `workflow.nyquist_validation` is absent from `.planning/config.json` (treat as enabled per the agent directive).

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (Python 3.13) |
| Config file | `backend/pytest.ini` / `backend/pyproject.toml` — pre-existing |
| Quick run command | `cd backend && pytest tests/test_oauth.py -x` |
| Targeted runtime-gate run | `cd backend && pytest tests/test_oauth.py::TestFindOrCreateOAuthUser::test_group_role_mapping_community_uses_default_role tests/test_oauth.py::TestFindOrCreateOAuthUser::test_group_role_mapping_enterprise_applies_mapping -x` |
| Targeted schema-gate run | `cd backend && pytest tests/test_oauth.py::TestIdpRoleMappingGate -x` |
| Full suite command | `cd backend && pytest -x` (baseline 1965/1965 must hold) |
| Audit re-run command | `/oc-audit` (slash command in Claude Code at this repo's root) |
| Doc-state check command | `grep -c "MILESTONE CLOSE BLOCKED" docs-internal/audits/oc-separation-audit-v13.1-close.md` (expect 0 outside the preserved subsection); `grep -c "MILESTONE CLOSE VERIFIED" .../v13.1-close.md` (expect ≥1) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| AUDIT-V1 (slice 1: schema gate Create — community reject) | `OAuthProviderCreate(group_role_mapping={"admins":"admin"})` raises `ValueError` with the D-03 message in community | unit (Pydantic) | `pytest tests/test_oauth.py::TestIdpRoleMappingGate::test_create_rejects_group_role_mapping_in_community -x` | ❌ Wave 0 — class added in Phase 219 commit 3 |
| AUDIT-V1 (slice 2: schema gate Create — community reject group_claim) | `OAuthProviderCreate(group_claim="groups")` raises `ValueError` in community | unit (Pydantic) | `pytest tests/test_oauth.py::TestIdpRoleMappingGate::test_create_rejects_group_claim_in_community -x` | ❌ Wave 0 |
| AUDIT-V1 (slice 3: schema gate Create — enterprise accept) | `OAuthProviderCreate(group_role_mapping={"admins":"admin"})` succeeds with `init_edition(["enterprise"])` | unit (Pydantic) | `pytest tests/test_oauth.py::TestIdpRoleMappingGate::test_create_accepts_group_mapping_in_enterprise -x` | ❌ Wave 0 |
| AUDIT-V1 (slice 4: schema gate Update — community reject) | `OAuthProviderUpdate(group_role_mapping={"admins":"admin"})` raises in community | unit (Pydantic) | `pytest tests/test_oauth.py::TestIdpRoleMappingGate::test_update_rejects_group_role_mapping_in_community -x` | ❌ Wave 0 |
| AUDIT-V1 (slice 5: D-02 carve-out — empty mapping allowed) | `OAuthProviderUpdate(group_role_mapping={})` succeeds in community ("clear mapping") | unit (Pydantic) | `pytest tests/test_oauth.py::TestIdpRoleMappingGate::test_create_with_empty_mapping_allowed_in_community -x` | ❌ Wave 0 |
| AUDIT-V1 (slice 6: service gate community — mapping IGNORED) | `find_or_create_oauth_user` with provider seeded directly via ORM (group_claim + non-empty mapping) returns user with `default_role`, NOT mapped role | integration (DB) | `pytest tests/test_oauth.py::TestFindOrCreateOAuthUser::test_group_role_mapping_community_uses_default_role -x` | ❌ Wave 0 (split from existing test_group_role_mapping) |
| AUDIT-V1 (slice 7: service gate enterprise — mapping APPLIED) | Same setup as slice 6 but `init_edition(["enterprise"])` → user has mapped role | integration (DB) | `pytest tests/test_oauth.py::TestFindOrCreateOAuthUser::test_group_role_mapping_enterprise_applies_mapping -x` | ❌ Wave 0 (renamed/split from existing test_group_role_mapping) |
| AUDIT-V1 (slice 8: full suite green) | Pre-existing 1965-test baseline still passes | integration (full) | `cd backend && pytest -x` | ✓ |
| AUDIT-V1 (slice 9: boundary grade ≥ A−) | `/oc-audit` re-run produces Boundary Integrity ≥ A− | manual / skill-driven | `/oc-audit` (Claude Code slash command); inspect Boundary row in Scorecard | ✓ skill canonical |
| AUDIT-V1 (slice 10: doc state) | `oc-separation-audit-v13.1-close.md` no longer has top-level `## ⚠ MILESTONE CLOSE BLOCKED` heading; has `## ✅ MILESTONE CLOSE VERIFIED` | doc structural | `grep -c "^## ⚠ MILESTONE CLOSE BLOCKED" docs-internal/audits/oc-separation-audit-v13.1-close.md` (expect 0); `grep -c "^## ✅ MILESTONE CLOSE VERIFIED" ...` (expect ≥1) | ✓ doc exists |
| AUDIT-V1 (slice 11: smoke — community 422) | POST `group_role_mapping={"admins":"admin"}` to `/settings/oauth-providers/` returns 422 with D-03 message in community | manual smoke | `curl -X POST ...` (see Code Examples §) | ✓ endpoint exists |
| AUDIT-V1 (slice 12: smoke — enterprise 200/201) | Same payload with `GEOLENS_EDITION=enterprise` returns 200/201 | manual smoke | `GEOLENS_EDITION=enterprise curl -X POST ...` | ✓ endpoint exists |

### Validation Layers

| Layer | Layer Name | Verification Artifact | Command | Gate |
|-------|------------|------------------------|---------|------|
| 1 | **Code-level (schema)** | 5 schema-validator tests in `TestIdpRoleMappingGate` (slices 1-5) | `pytest tests/test_oauth.py::TestIdpRoleMappingGate -x` | All pass |
| 2 | **Code-level (runtime)** | 2 service-gate tests in `TestFindOrCreateOAuthUser` (slices 6-7) + full backend suite | `pytest tests/test_oauth.py::TestFindOrCreateOAuthUser::test_group_role_mapping_* -x` then `pytest -x` | All pass; full suite at ≥1965/1965 |
| 3 | **Boundary-level (audit re-run)** | `/oc-audit` Boundary Integrity grade letter (slice 9) | `/oc-audit` slash command in Claude Code | Boundary ≥ A−; zero 🔴 in OAuth IdP-mapping cluster |
| 4 | **Doc-level (close-artifact structural)** | Two `grep` checks against `oc-separation-audit-v13.1-close.md` (slice 10) | `grep -c "^## ⚠ MILESTONE CLOSE BLOCKED" .../v13.1-close.md` and `grep -c "^## ✅ MILESTONE CLOSE VERIFIED" .../v13.1-close.md` | First is 0 (or only inside preserved subsection); second is ≥1 |
| 5 | **End-to-end (manual smoke)** | Two `curl` invocations (slices 11-12) | See Code Examples § | 422 in community with D-03 message; 200/201 in enterprise |

### Sampling Rate

- **Per task commit (D-15):**
  - Commit 1 (schema validators): `pytest tests/test_oauth.py::TestIdpRoleMappingGate -x` (slices 1-5; only valid after commit 3 lands the test class — for commit 1 alone, run `pytest tests/test_oauth.py -x` to confirm no regressions in existing tests).
  - Commit 2 (service gate): `pytest tests/test_oauth.py::TestFindOrCreateOAuthUser -x`. Existing `test_group_role_mapping` will fail after this commit alone (mapping is now suppressed in default community mode); commit 3 splits the test to fix.
  - Commit 3 (tests): `pytest tests/test_oauth.py -x` (slices 1-7).
  - Commit 4 (audit + doc): no test commit; `/oc-audit` (slice 9) + `grep` checks (slice 10) + manual smoke (slices 11-12).
- **Per wave merge:** `cd backend && pytest -x` (slice 8: full suite at 1965/1965 + 5 new tests = 1970 baseline).
- **Phase gate:** All 5 layers green. Layer 1 + 2 from `pytest -x`; Layer 3 from `/oc-audit`; Layer 4 from `grep`; Layer 5 from `curl` smoke. Then `/gsd-verify-work`.

### Wave 0 Gaps

- [x] `backend/tests/test_oauth.py` exists (1119 lines as of `main`)
- [x] `pytest` framework installed (existing dev dep)
- [x] `pytest-asyncio` installed (existing dev dep)
- [x] `init_edition` test pattern exists at `backend/tests/test_saml_overlay.py:239` and `backend/tests/test_edition.py:11-22`
- [ ] **New** `TestIdpRoleMappingGate` class — added in Phase 219 commit 3
- [ ] **Renamed/split** `test_group_role_mapping` → `test_group_role_mapping_community_uses_default_role` + `test_group_role_mapping_enterprise_applies_mapping` — added in Phase 219 commit 3
- [ ] **Optional** local autouse fixture for edition-state isolation in `test_oauth.py` (or shared in `conftest.py`) — added in Phase 219 commit 3 if planner picks the fixture path

## Project Constraints (from `~/.claude/CLAUDE.md` global)

The user's global `CLAUDE.md` has the following directives that apply to this phase:

- **Commit messages MUST NOT indicate AI / Bot activity.** Plain commit messages only.
- **Prefer simple, readable code over clever abstractions.** The new validators should be straightforward `if/raise/return self` blocks; no metaclass magic, no decorator factories.
- **Follow existing project conventions when editing files.** Mirror `_validate_per_type` shape; match existing import order; use the existing `model_validator` decorator already imported at `oauth/schemas.py:8`.
- **Be direct and concise.** No over-commenting; one clear docstring per validator citing the audit and CONTEXT.md decision (`D-01`, `D-05`).
- **When uncertain about intent, ask before making assumptions.** All design intent is locked in CONTEXT.md decisions D-01 through D-15; no design ambiguity remains for the planner.

(No project-level `./CLAUDE.md` exists.)

## Sources

### Primary (HIGH confidence — verified directly against `main`)

- `docs-internal/audits/oc-separation-audit-v13.1-close.md` — Section 1 lines 53-55 (per-file fix prescription); Scorecard line 9 (Boundary B− rationale); Section 8 lines 363-372 (grade-delta table); P1 Residual Triage row 1 line 408 (proposes Phase 219).
- `.planning/phases/219-oc-audit-remediate-idp-mapping/219-CONTEXT.md` — D-01 through D-15 (locked decisions).
- `.planning/STATE.md` — Phase 218 BLOCKED-state record (lines 33-50).
- `.planning/REQUIREMENTS.md` — AUDIT-V1 definition (line 61).
- `backend/app/modules/auth/oauth/schemas.py` — line numbers verified for `_validate_per_type` (145), `group_claim` Create (121-129), `group_role_mapping` Update (245-248), `model_validator` import (8).
- `backend/app/modules/auth/oauth/service.py` — `_resolve_role` definition (169-179) and call site (261-263) verified.
- `backend/app/modules/auth/oauth/models.py` — `default_role` / `group_claim` / `group_role_mapping` columns at 82-84 verified.
- `backend/app/core/edition.py` — `is_enterprise()` at line 50; `init_edition()` at line 27.
- `backend/tests/test_oauth.py` — `_create_test_provider` at 344-360; existing `test_group_role_mapping` at 458-481.
- `backend/tests/test_saml_overlay.py` — `init_edition(["enterprise"])` at line 239; `_info` save/restore pattern at 238/270.
- `backend/tests/test_edition.py` — `_reset_edition()` + `_clean_edition` autouse fixture at 11-22.
- `.planning/config.json` — confirms `workflow.nyquist_validation` is absent → treat as enabled.

### Secondary (MEDIUM confidence)

- (none — this phase requires no external library docs)

### Tertiary (LOW confidence)

- (none)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all primitives are in-repo and have line-number-verified precedent.
- Architecture: HIGH — pattern is locked by CONTEXT.md and the audit; only nuance is the test-bypass approach (validated against `_create_test_provider` body).
- Pitfalls: HIGH — pitfalls 1-5 derive from observed code shape and existing test patterns.

**Research date:** 2026-04-29
**Valid until:** 2026-05-13 (14 days — these line numbers will go stale if `oauth/{schemas,service}.py` is touched by another phase before Phase 219 starts; verify line numbers at planning time if any commits land in `auth/oauth/` between now and then)

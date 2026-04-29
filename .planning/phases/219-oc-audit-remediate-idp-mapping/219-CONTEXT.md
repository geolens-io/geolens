# Phase 219: oc-audit-remediate-idp-mapping - Context

**Gathered:** 2026-04-29
**Status:** Ready for planning
**Mode:** `--auto` (Claude selected recommended defaults across all gray areas)

<domain>
## Phase Boundary

Close the **single architectural P0** that blocks v13.1 milestone close: gate OAuth `group_claim` / `group_role_mapping` (IdP→role mapping) behind `is_enterprise()` so the community runtime cannot accept or apply it. Phase 217 documented this gating as out-of-scope and deferred it to Phase 218; Phase 218 was scoped as a closing-audit phase only and the deferral was never closed. The closing audit (`docs-internal/audits/oc-separation-audit-v13.1-close.md`) graded Boundary Integrity **B−** vs the v13.1 target **A−** and explicitly proposed this phase as the ~1-day fix that retires the shortfall.

Once the gate ships, the closing audit is re-run; if Boundary ≥ A−, the v13.1 close audit doc is amended in place (BLOCKED banner replaced with VERIFIED banner; scorecard / Section 8 / P1 triage row updated). The milestone-close criterion AUDIT-V1 is then met.

**In scope:**
1. **Schema gate** — Add `model_validator(mode="after")` to `OAuthProviderCreate` AND `OAuthProviderUpdate` in `backend/app/modules/auth/oauth/schemas.py`. Validators raise `ValueError("Group-based role mapping requires the GeoLens Enterprise overlay")` when `group_claim` is set OR `group_role_mapping` is non-empty AND `not is_enterprise()`.
2. **Service gate** — In `backend/app/modules/auth/oauth/service.py:261-263`, wrap the `_resolve_role(...)` call in an edition check: if `is_enterprise()`, call `_resolve_role(...)`; else `role_name = provider.default_role`. `_resolve_role()` itself stays as a pure helper (no internal edition check).
3. **Test coverage** — Split the existing `test_group_role_mapping` (which currently runs in community by default) into two tests: a community variant that asserts mapping is IGNORED (role = `default_role`), and an enterprise variant that initializes `init_edition(["enterprise"])` and asserts mapping is APPLIED. Add 2 schema-validator tests: community-mode rejection of `group_claim` / `group_role_mapping`; enterprise-mode acceptance.
4. **Audit re-run + v13.1-close amendment** — After the gate ships and tests pass, re-run `/oc-audit` against current `main`. If Boundary ≥ A−, **amend `docs-internal/audits/oc-separation-audit-v13.1-close.md` in place**: replace the `## ⚠ MILESTONE CLOSE BLOCKED` banner with `## ✅ MILESTONE CLOSE VERIFIED`; update the Scorecard row for Boundary Integrity; update Section 8 grade-delta table; flip the P1 Residual Triage row 1 verdict to **Closed by Phase 219 (date)**.
5. **Deferred-items doc closure** — Add a closure marker to any row in `docs-internal/audits/oc-separation-deferred-items-20260426.md` that tracks the IdP-mapping gate. Format: "Closed by Phase 219 (2026-04-29)".

**Out of scope (capture as deferred ideas if surfaced):**
- Removing the columns from `oauth/models.py:82-84`. They stay as forward-compat scaffolding for the enterprise overlay (the SAML overlay reads them at runtime per Phase 217 D-04). Per audit Section 1: "keep columns (forward-compat scaffolding for enterprise) but reject non-default writes in community via `model_validator` + `is_enterprise()` check".
- Frontend changes. The UI fields at `frontend/src/components/admin/saml/SamlProvidersSection.tsx:90-92, 511-528` are already enterprise-route-gated via `AdminSamlPage.tsx:28-33` (`useEdition()` redirect). Audit graded UI 🟢 Clean.
- DB migrations. No schema change — columns stay; only write-path acceptance + runtime application change.
- Triaging the **other** 2026-04-27 audit findings (Marketplace billing P1; Branding UI key mismatch P1). Both were already triaged in Phase 218's closing audit (Marketplace → P2 demote; Branding → out-of-scope for the close audit's P1 list because it doesn't break boundary integrity). Re-evaluation is part of the audit re-run, not a separate work-item here.
- Producing a brand-new `v13.1.1-close.md` or `v13.1-close-amended.md` file. Decision: **amend the existing v13.1-close.md in place**. Audit-trail is preserved by git history; fragmenting into a second file splits the milestone-close story.
- Closing the milestone. After this phase verifies, `/gsd-complete-milestone` is the separate next step (per Phase 218 deferred-items).
- Modifying the `/oc-audit` skill. It's canonical; this phase only consumes it.

</domain>

<decisions>
## Implementation Decisions

### Schema gate (write-path)

- **D-01:** Add `@model_validator(mode="after")` on **both** `OAuthProviderCreate` (around `oauth/schemas.py:169` — append after the existing `_validate_per_type`) and `OAuthProviderUpdate` (mirror placement). Each validator raises `ValueError("Group-based role mapping requires the GeoLens Enterprise overlay")` when (`group_claim` is non-None) OR (`group_role_mapping` is a non-empty dict) AND `not is_enterprise()`. Reason: matches the existing per-type validator pattern at `schemas.py:145`; small enough to inline; keeps the gate co-located with the fields it governs.

- **D-02:** Treat `group_role_mapping={}` (empty dict) and `group_role_mapping=None` as **allowed in community** — they represent "no mapping" / "clear mapping". Only **non-empty** mapping triggers the gate. Reason: the Update schema documents passing `{}` as the way to clear the mapping (`schemas.py:248` description: "Pass an empty object to clear"); blocking that would break clearing a previously-set mapping when an admin downgrades from enterprise to community.

- **D-03:** Use the audit's verbatim error message: `"Group-based role mapping requires the GeoLens Enterprise overlay"`. Reason: it's already edition-aware and explains both what's blocked and how to enable it. No need to write a new message.

- **D-04:** Validator imports `is_enterprise` from `app.core.edition` at module top of `schemas.py`. Reason: matches the existing import style; `is_enterprise()` is a cheap read of a module-level singleton initialized at app startup (`core/edition.py:50`), so per-request validator invocation has no measurable overhead.

### Service gate (runtime application)

- **D-05:** Gate at the call site `service.py:261-263`, NOT inside `_resolve_role()`. Pattern (per audit recommendation):

  ```python
  if is_enterprise():
      role_name = _resolve_role(
          groups, provider.group_role_mapping, provider.default_role
      )
  else:
      role_name = provider.default_role
  ```

  Reason: keeps `_resolve_role` a pure helper (testable without edition coupling); the orchestration flow `find_or_create_oauth_user` is the right level for edition awareness; the audit's row-1 fix description specifies this exact location and shape.

- **D-06:** No log/warning when the runtime gate fires in community. Reason: a community admin should never have `group_role_mapping` populated post-D-01 (the schema gate blocks writes). The runtime branch is a defense-in-depth fallback for: (a) data inserted before this phase shipped (legacy rows), (b) data inserted via direct DB access. Logging every login as "boundary saved" would be noise. The audit re-run is the regression detector.

- **D-07:** Do NOT touch `_resolve_role()` itself. Its signature, behavior, and internal logic stay identical. Reason: it's a pure helper used only here; modifying it would expand the diff without functional benefit. Tests for `_resolve_role()` continue to exercise both branches (matches → role; no match → default).

### Test strategy

- **D-08:** Split `test_group_role_mapping` (in `backend/tests/test_oauth.py:458`) into two tests:
  1. `test_group_role_mapping_community_uses_default_role` — runs without enterprise init. Sets up the same provider (`group_claim="groups"`, `group_role_mapping={"admins": "admin", ...}`) **directly via SQLAlchemy ORM** (NOT via the schema, to bypass the new D-01 validator and simulate a legacy/direct-DB row). Calls `find_or_create_oauth_user(...)` with userinfo containing `groups: ["admins"]`. Asserts `default_role` ("viewer") is applied, NOT "admin".
  2. `test_group_role_mapping_enterprise_applies_mapping` — runs `init_edition(["enterprise"])` (or sets `GEOLENS_EDITION=enterprise` in `os.environ`); same provider/userinfo setup as today. Asserts "admin" role is applied (existing assertion).

  Reason: explicit coverage of BOTH branches of the runtime gate; mirrors the pattern at `backend/tests/test_saml_overlay.py:239` for enterprise edition setup. The community variant intentionally bypasses the schema validator because we're testing the SERVICE gate's defense-in-depth, not the schema validator (covered by D-09).

- **D-09:** Add 4 new schema-validator tests in a new `TestIdpRoleMappingGate` class in `backend/tests/test_oauth.py`:
  1. `test_create_rejects_group_claim_in_community` — `OAuthProviderCreate(group_claim="groups", ...)` raises `ValueError` with the D-03 message; community edition (no init).
  2. `test_create_rejects_group_role_mapping_in_community` — `OAuthProviderCreate(group_role_mapping={"admins": "admin"}, ...)` raises `ValueError`; community edition.
  3. `test_create_accepts_group_mapping_in_enterprise` — same payload as #2 with `init_edition(["enterprise"])`; succeeds.
  4. `test_update_rejects_group_role_mapping_in_community` — `OAuthProviderUpdate(group_role_mapping={"admins": "admin"})` raises in community; passes in enterprise.

  Plus a passing variant: `test_create_with_empty_mapping_allowed_in_community` — `group_role_mapping={}` is accepted in community (D-02 carve-out).

  Reason: each branch of D-01 + D-02 has explicit coverage; aligns with verification gate D-13.

- **D-10:** Edition-state isolation between tests — every test that calls `init_edition(["enterprise"])` MUST reset to community state in a `try/finally` (or via a pytest fixture) so it doesn't leak into subsequent tests. Pattern: store `app.core.edition._info` before, restore after. Reason: `init_edition` mutates a module-level singleton; cross-test pollution would cause flaky failures. Check whether `test_saml_overlay.py:239` already has a pattern to reuse.

### Audit re-run + v13.1-close amendment

- **D-11:** After the code change ships and tests pass, re-run `/oc-audit` against current `main`. The skill writes a date-named file `docs-internal/audits/oc-separation-audit-{YYYYMMDD}.md`; this output is **discarded** (not committed) — its only role is to confirm Boundary ≥ A−. Reason: per Phase 218 D-01, the skill is canonical; we invoke it but only the milestone-close artifact (`v13.1-close.md`) is committed.

- **D-12:** **Amend the existing `docs-internal/audits/oc-separation-audit-v13.1-close.md` in place** with the post-fix grades. Specific edits:
  1. Replace the `## ⚠ MILESTONE CLOSE BLOCKED` banner (line 20) with `## ✅ MILESTONE CLOSE VERIFIED — Phase 219 closed boundary gap`. Keep the original "BLOCKED" narrative as a subsection ("### Pre-remediation state (2026-04-29)") so the audit trail of the gap and its resolution is co-located.
  2. Update the Scorecard table row for Boundary Integrity: grade goes from B− to the new audit grade (expected A− or A); the rationale paragraph is rewritten to note the gate now ships in community + cite the new validator/service locations.
  3. Update Section 1 (Feature Boundary Leakage) — flip the three 🔴 rows for `oauth/{schemas,service,models}.py` to 🟢 Clean; cite the new validator and runtime branch.
  4. Update Section 8 (Comparison to Prior Audit) grade-delta table: Boundary row shows `B−` (v13.1-close pre) → `A−` (v13.1-close post-219) → `↑` → `Met? ✅`.
  5. Update the P1 Residual Triage table: row 1 verdict column gets "**Closed by Phase 219 (2026-04-29)**" appended; the row stays for traceability.

  Reason: amending in place keeps a single canonical close artifact; git history preserves the BLOCKED-state version. Producing a second file (`v13.1.1-close.md`) was rejected as fragmenting the milestone-close story across two artifacts that future readers would have to reconcile.

- **D-13:** Verification gate for the phase, ordered:
  1. **Code-level**: lint passes; backend test suite green at or above baseline (1965/1965 currently); the 5 new tests in D-08/D-09 all pass.
  2. **Boundary-level**: `/oc-audit` re-run produces Boundary Integrity ≥ A− with zero 🔴 violations under the OAuth IdP mapping cluster.
  3. **Doc-level**: `v13.1-close.md` no longer contains the `## ⚠ MILESTONE CLOSE BLOCKED` heading; it contains `## ✅ MILESTONE CLOSE VERIFIED`; Section 8 shows Boundary `Met? ✅`.
  4. **Manual smoke**: in a community dev instance, POST to `/settings/oauth-providers/` with `group_role_mapping={"admins":"admin"}` returns 422 with the D-03 message; same payload succeeds with `GEOLENS_EDITION=enterprise`.

  Reason: gate is multi-layered because each layer catches a different class of regression — unit tests catch code bugs, audit catches structural drift, doc check catches close-artifact incompleteness, smoke catches end-to-end gate behavior.

### Plan structure

- **D-14:** **Single plan** (`219-01-gate-idp-role-mapping`). The work is sequential and tightly coupled: schema validator → service gate → test split → audit re-run → doc amendment. ~1 day. Splitting would add ceremony without isolation benefit. Reason: same logic as Phase 218 D-09; small phase, atomic deliverable.

- **D-15:** Commit boundary granularity within the plan:
  - Commit 1: Schema validator (D-01 + D-02 + D-03 + D-04).
  - Commit 2: Service gate (D-05 + D-06 + D-07).
  - Commit 3: Tests (D-08 + D-09 + D-10).
  - Commit 4: Audit re-run capture + v13.1-close.md amendment + deferred-items closure (D-11 + D-12 + Phase scope item 5).

  Reason: each commit is independently revertable if a downstream issue surfaces; commit 4 is doc-only so it can ship after a quick audit verification without re-running tests.

### Claude's Discretion

- **`OAuthProviderUpdate.provider_type` interaction**: If an Update payload sets `provider_type='saml'` AND `group_role_mapping={"admins":"admin"}`, the D-01 validator still fires in community. SAML providers in community should not exist at all (SAML is enterprise-only per Phase 217), so this is the right behavior. Planner can decide whether to add a redundant pre-check that rejects `provider_type='saml'` writes in community in the same validator (out of scope for D-01 but a consistent extension).
- **Validator method name**: planner may name it `_validate_enterprise_features`, `_validate_idp_mapping_gate`, or similar — name not mandated.
- **Audit re-run timing**: planner may run `/oc-audit` after commit 3 (before commit 4) or after commit 4 — either is acceptable; the audit reads `main`, not the doc artifact.
- **`init_edition` test fixture vs inline patch**: planner may introduce a shared `enterprise_edition` pytest fixture in `conftest.py` if it cleans up D-10's reset boilerplate, or keep inline `try/finally` if only a few tests need it.
- **Optional defense-in-depth log line**: planner MAY add a `logger.info("group mapping ignored — community edition", provider=provider.slug)` inside the `else` branch at `service.py:261-263` if observability is judged useful. D-06 chose silence; this is a low-stakes flip.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### The audit driving this phase
- `docs-internal/audits/oc-separation-audit-v13.1-close.md` — The closing audit that graded Boundary B− and proposed Phase 219 as the fix. Section 1 (lines 53-55) gives the exact remediation prescription per file. Section §1 sub-section "IdP group-mapping note" (line 77) explains the deferral history. P1 Residual Triage row 1 (line 408) names this phase. **Amend in place per D-12**.
- `docs-internal/audits/oc-separation-audit-20260427.md` — Mid-milestone audit that originally surfaced this P0. Confirms the same three sites (`oauth/{schemas,service,models}.py`).
- `docs-internal/audits/oc-separation-deferred-items-20260426.md` — Deferred-items source-of-truth; closure markers added per phase scope item 5.
- `.claude/commands/oc-audit.md` — `/oc-audit` skill definition. Invoked verbatim per Phase 218 D-01 (do NOT modify the skill).

### Boundary rules consumed by the audit
- `docs-internal/GTM/repo-split.md` — **IdP role mapping is explicitly classed as Enterprise** here; this is the rule the gate enforces. Cite this in commit messages.
- `docs-internal/GTM/free-vs-enterprise.md` — Free vs Enterprise feature boundary.
- `docs-internal/GTM/pricing-to-tiers.md` — Tier pricing.

### Code under change
- `backend/app/modules/auth/oauth/schemas.py:116-129, 237-248` — `group_claim` / `group_role_mapping` field definitions on `OAuthProviderCreate` (~line 121-129) and `OAuthProviderUpdate` (~line 240-248). New validators land near the end of each class (mirror the existing `_validate_per_type` at line 145).
- `backend/app/modules/auth/oauth/service.py:169-179, 261-263` — `_resolve_role()` helper definition (line 169) is unchanged; the gate wraps the call site at line 261-263 inside `find_or_create_oauth_user()`.
- `backend/app/modules/auth/oauth/models.py:82-84` — `default_role` / `group_claim` / `group_role_mapping` columns on `OAuthProvider`. **NOT modified** — kept as forward-compat scaffolding for the enterprise overlay (Phase 217 D-04).
- `backend/app/core/edition.py:50` — `is_enterprise()` helper. Used by the schema validator (D-04) and the service gate (D-05).

### Tests under change
- `backend/tests/test_oauth.py:458-481` — Existing `test_group_role_mapping`. **Renamed and split per D-08.** A new `TestIdpRoleMappingGate` class lands per D-09.
- `backend/tests/test_saml_overlay.py:239` — Reference for `init_edition(["enterprise"])` pattern in tests.
- `backend/tests/test_edition.py` — Reference for `GEOLENS_EDITION` env-var-based edition setup.

### Milestone scope anchors
- `.planning/PROJECT.md` §"Current Milestone: v13.1 Open-Core Separation P1" — milestone grade-target promise.
- `.planning/REQUIREMENTS.md` §AUDIT-V1 — the requirement Phase 218 was supposed to close; phase 219 unblocks it.
- `.planning/ROADMAP.md` §"Phase 219: oc-audit-remediate-idp-mapping" — Goal placeholder; this CONTEXT.md provides the goal narrative.
- `.planning/STATE.md` §"Phase 218 BLOCKED-state record" — verbatim diagnosis of the P0 root cause and the recommended Phase 219 path.

### Prior phase context (origin of the deferral chain)
- `.planning/phases/217-auth-saml-enterprise/217-CONTEXT.md` §"Out of scope" — explicit deferral text: *"gating OAuth `group_claim`/`group_role_mapping` behind `require_enterprise()` (audit P0 from `oc-separation-audit-20260427.md` — deferred to Phase 218)"*. Phase 217 is the originator of the deferral.
- `.planning/phases/218-oc-audit-close-v13-1/218-CONTEXT.md` — Phase 218's scope was deliberately audit-only; explains why the deferral wasn't closed there. Cites the same three remediation sites (D-04, D-05) but did not implement them.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`is_enterprise()`** at `backend/app/core/edition.py:50` — singleton-backed; cheap to call per-request. Already used by `backend/app/platform/extensions/guards.py:10` (`require_enterprise()`).
- **`@model_validator(mode="after")` precedent** at `backend/app/modules/auth/oauth/schemas.py:145` — `_validate_per_type` shows the exact decorator placement, error-raising pattern, and `return self` shape. New validators copy this style.
- **`init_edition(["enterprise"])`** at `backend/tests/test_saml_overlay.py:239` — test-time enterprise mode setup. Reuse pattern (and possibly a fixture if planner consolidates).
- **`OAuthProvider` model columns** at `backend/app/modules/auth/oauth/models.py:82-84` — already exist; NO migration needed.
- **Schema imports** in `oauth/schemas.py` already have `from pydantic import BaseModel, Field, field_validator, model_validator` — no new imports needed for the validator (just add `from app.core.edition import is_enterprise`).

### Established Patterns
- **Edition-gating call site** at `backend/app/modules/audit/router.py:96` — `_ent: None = Depends(require_enterprise)` pattern. Different gate flavor (FastAPI dependency, raises 403); the service-layer gate at `service.py:261` is plain Python because it's not a request-scoped check (it's inside an internal orchestration function).
- **Edition-aware error messaging** — community-mode errors that name "Enterprise overlay" guide admins toward the upgrade path. The D-03 message follows this convention; cf. similar messaging in `app/platform/extensions/guards.py`.
- **In-place doc amendment for milestone artifacts** — Phase 218 D-02 establishes the `oc-separation-audit-v13.1-close.md` as a milestone-bound artifact, not a dated artifact. D-12 amends in place rather than producing a new dated file.
- **Defense-in-depth (schema + service)** — Schema gate prevents new bad data; service gate handles legacy/direct-DB rows. This dual-gate is the standard pattern when columns are kept (forward-compat scaffolding) but feature is gated.

### Integration Points
- **No production code changes outside `oauth/`** — the change set is limited to two files in `backend/app/modules/auth/oauth/` (`schemas.py`, `service.py`).
- **No frontend changes** — UI is enterprise-route-gated already (`AdminSamlPage.tsx:28-33`).
- **No DB migration** — columns stay; only acceptance + application logic changes.
- **Files written/modified:**
  - `backend/app/modules/auth/oauth/schemas.py` (add 2 model_validators)
  - `backend/app/modules/auth/oauth/service.py` (wrap call site at 261-263)
  - `backend/tests/test_oauth.py` (split existing test, add TestIdpRoleMappingGate class)
  - `docs-internal/audits/oc-separation-audit-v13.1-close.md` (amend in place per D-12)
  - `docs-internal/audits/oc-separation-deferred-items-20260426.md` (closure marker if relevant row exists)

### Known facts to verify before invoking the audit re-run
1. `is_enterprise()` in test runner returns `False` by default (no `GEOLENS_EDITION` env var, no extensions loaded) — confirmed by `backend/tests/test_edition.py`.
2. `oauth/models.py:82-84` columns are NOT touched — only `schemas.py` (write-path) + `service.py` (apply-path) change.
3. `frontend/src/components/admin/saml/SamlProvidersSection.tsx` `useEdition()` redirect is intact at `AdminSamlPage.tsx:28-33` — no UI change required.
4. No migration files reference `group_claim` or `group_role_mapping` (column shapes unchanged) — `grep -rn "group_claim\|group_role_mapping" backend/migrations/` should return zero hits.

### Risk surface
- **Test pollution from `init_edition`** — see D-10. If not isolated, downstream tests may run in enterprise mode and produce false greens.
- **Existing OAuth provider rows in dev DBs** — if a dev created a provider with `group_role_mapping` populated before this gate ships, the D-01 validator does NOT retroactively reject the existing row (it only fires on new writes). The D-05 service gate is the runtime catch. No data migration needed.
- **Audit re-run sensitivity** — the audit's grader is the canonical `/oc-audit` skill; we don't tune its rubric. If the post-fix audit lands at A (not A−), that exceeds target — fine. If it lands at B+ for unrelated reasons, the phase has revealed new boundary issues and triage of those is a follow-up phase, not this phase's responsibility.

</code_context>

<specifics>
## Specific Ideas

- **Use the audit's verbatim error message.** "Group-based role mapping requires the GeoLens Enterprise overlay" — the audit author already calibrated this phrasing.
- **Amend, don't replace, the v13.1-close.md.** Preserve the BLOCKED-state narrative as a "Pre-remediation state" subsection so future readers understand why the close took two phases.
- **Don't touch `_resolve_role()`.** It's pure; making it edition-aware spreads gate logic. Gate the call site, not the helper.
- **Keep the columns.** They're forward-compat scaffolding for the enterprise overlay (Phase 217 D-04 reuses them for SAML group claims). Removing them would break SAML JIT provisioning in enterprise.
- **Defense-in-depth schema + service gate.** New writes blocked at schema level; legacy/direct-DB writes blocked at runtime level. Both are required because columns persist.

</specifics>

<deferred>
## Deferred Ideas

- **Removing `group_claim` / `group_role_mapping` columns from core `oauth/models.py`** — would require moving them to an enterprise migration + reading them via the IdentityExtension Protocol seam. Significantly larger scope than gating; deferred unless a future audit downgrades the column-presence to a violation.
- **Optional log line on community-side runtime gate** (D-06 alternative). Low-stakes observability flip; revisit if production support cases need to debug "why isn't my mapping applying".
- **`provider_type='saml'` write rejection in community** (Claude's Discretion note). Currently SAML provider writes in community would succeed at the schema layer (the per-type validator only checks SAML field completeness). Adding a community-mode rejection of `provider_type='saml'` is a consistent extension but out of this phase's audit-driven scope.
- **Tenant-scoped edition** — if multi-tenant ever lands, `is_enterprise()` becomes a tenant-scoped check. Not a v13.1 concern.
- **Re-grading audit-export gate** or other already-green findings — out of scope; audit re-run will re-evaluate everything but this phase only owns the IdP-mapping cluster.
- **Producing a v13.2 baseline audit** — that's the start-of-next-milestone artifact, not a Phase 219 artifact.

</deferred>

---

*Phase: 219-oc-audit-remediate-idp-mapping*
*Context gathered: 2026-04-29*

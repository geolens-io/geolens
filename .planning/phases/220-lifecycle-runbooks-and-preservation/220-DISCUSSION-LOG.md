# Phase 220: lifecycle-runbooks-and-preservation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-29
**Phase:** 220-lifecycle-runbooks-and-preservation
**Areas discussed:** Deactivation operator sequence, LIFECYCLE-05 alembic decision, Integration test design (incl. CI setup), Docs structure & saml.md scope

---

## Deactivation operator sequence

### Initial framing (4-option AskUserQuestion)

| Option | Description | Selected |
|--------|-------------|----------|
| Stop loading the overlay (uninstall package) | Canonical = `pip uninstall geolens-enterprise` (or stop using docker-compose.enterprise.yml) + restart. Env override is dev/testing shortcut. | |
| Set `GEOLENS_EDITION=community` + restart | Canonical = env var swap, package can stay installed. Cleaner for cloud/IaC. | |
| Both, with package-uninstall as primary | Document both. Primary = stop loading the overlay. Secondary = env var for staging/canary. | |
| Both, with env var as primary | Document both. Primary = env swap (least-invasive). Secondary = full uninstall on license expiry. | |

**User's response:** "think hard about this and do any research necessary to choose the correct approach" — handed the call to Claude with research mandate.

### Architectural finding

Traced `init_edition()` and the typed accessors `get_audit_extension()` / `get_branding_extension()`. Finding: `GEOLENS_EDITION=community` set alone leaves `register_extensions()` having already run, so `registry['audit']` and `registry['branding']` still hold enterprise instances; typed accessors return them without consulting `is_enterprise()`. SAML routes 404 because their guards check `require_enterprise()`, but audit-export and branding overlays continue silently. Therefore env-var-only is incomplete deactivation.

### Confirmation

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — overlay-removal canonical, env var defense-in-depth | Runbook prescribes overlay-removal; env var optional redundant safety. | ✓ |
| Yes, plus call out the audit/branding leak as a known issue | Same canonical path, plus runbook flags the leak + creates a backlog ticket for `is_enterprise()` accessor gating. | |
| Different framing | (declined) | |

**User's choice:** Overlay-removal canonical, env var defense-in-depth.
**Notes:** The architectural leak (registry accessors don't gate by edition) is captured in CONTEXT.md Risk Surfaces and Deferred Ideas, but is NOT escalated to a Phase 220 backlog ticket — it lives as a deferred-idea entry for a future architectural phase.

---

## LIFECYCLE-05 alembic decision

| Option | Description | Selected |
|--------|-------------|----------|
| Document destructive, export mandatory | Keep `e002.downgrade()` destructive. Runbook documents safe path = leave schema alone; destructive path requires `pg_dump` pre-step. saml.md's "reversible" line gets retargeted. | ✓ |
| Add non-destructive `e003` alembic path | Author `e003_drop_saml_safe` that nulls + relaxes CHECK without dropping columns. Two paths to maintain. | |
| Both paths documented | Add safe `e003` AND document destructive. Operator picks based on scenario. | |
| Defer to plan phase | Note trade-offs in CONTEXT.md, planner decides after sketching `e003`'s actual cost. | |

**User's choice:** Document destructive, export mandatory.
**Notes:** Rationale captured in CONTEXT.md D-02. The safe deactivation already IS "don't run alembic downgrade." Carrying a second alembic path forever for a rare ops scenario isn't justified.

---

## Integration test design

### Test simulation strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Registry-level simulation | Single pytest session: seed → clear `_extensions` / `_routers` → re-init edition as community → assert SQL persistence + 404. Lives in `backend/tests/`. | ✓ |
| Two-phase pytest with env override | Test seeds with overlay loaded, then sets `GEOLENS_EDITION=community` + re-inits to flip. Doesn't exercise canonical path. | |
| Docker-compose stack swap test | Separate CI workflow: enterprise stack → seed → community stack → assert. Heaviest fidelity, heaviest CI cost. | |
| Hybrid: fast registry test in PR CI + nightly compose test | Phase 220 ships registry test; compose test is a follow-on. | |

**User's choice:** Registry-level simulation.
**Notes:** Rationale captured in D-04. Compose-stack swap is captured as a deferred idea for future hardening.

### CI overlay availability

| Option | Description | Selected |
|--------|-------------|----------|
| Enterprise overlay always installed in CI | Amend `.github/workflows/ci.yml` to checkout + `uv add --editable geolens-enterprise` before pytest. Requires deploy key/PAT for the private repo. | ✓ |
| Test fixture applies `e002` standalone | Lifecycle test fixture programmatically applies the column-add SQL inside the test. Brittle; doesn't exercise alembic. | |
| Skip lifecycle test in OSS CI; run only in enterprise CI | Test lives in `geolens-enterprise/tests/` where overlay is always present. | |

**User's choice:** Enterprise overlay always installed in CI.
**Notes:** Side benefit: existing `backend/tests/test_saml_overlay.py` and the enterprise repo's `tests/test_registration.py` gain CI coverage. Fork-PR access is captured as a planner subdecision (Claude's Discretion in CONTEXT.md).

---

## Docs structure & saml.md scope

| Option | Description | Selected |
|--------|-------------|----------|
| Top-level `docs/` + targeted saml.md edit | New runbooks at `docs/edition-deactivation.md` + `docs/edition-reactivation.md`. saml.md Installation section gets a targeted edit (retarget "reversible" framing + link to runbook + brief "Deactivating SAML" subsection). | ✓ |
| `docs/lifecycle/` subdir + targeted saml.md edit | Runbooks at `docs/lifecycle/deactivation.md` + `docs/lifecycle/reactivation.md`. Adds a directory level. | |
| Fold into upgrade-guide.md + saml.md edit | Add Edition Deactivation/Reactivation sections to `docs/upgrade-guide.md`. One file. | |
| Top-level + heavier saml.md rewrite | Same placement as option 1, but saml.md Installation section gets a fuller rewrite (activation as lifecycle event with reactivation symmetry). | |

**User's choice:** Top-level `docs/` + targeted saml.md edit.
**Notes:** Cross-link mandatory from saml.md → edition-deactivation.md (LIFECYCLE-03). Optional cross-links from admin-guide.md / install-guide.md captured as Claude's Discretion.

---

## Claude's Discretion

- **CI fork-PR access strategy** — `geolens-enterprise` is private; fork PRs can't access secrets. Planner picks: skip-on-missing-secrets gate, separate workflow, or push-to-main-only verification. Recommendation noted in CONTEXT.md.
- **Pre-flight checklist depth** — categories are named (snapshot, inventory, communicate, stop, verify); planner picks exact wording, command examples, SQL snippets.
- **Data-fate matrix shape** — table somewhere near the top of `docs/edition-deactivation.md`; planner picks columns and exact phrasing.
- **Reactivation runbook depth** — recommendation: thin, link to existing activation docs in saml.md/install-guide, focus on post-reactivation verification checklist.
- **TestClient strategy for asserting `/auth/saml/*` returns 404 post-simulation** — planner picks mechanism (fresh app instance, direct route inspection, etc.). SQL persistence is the strict LIFECYCLE-04 deliverable.
- **Requirements text precision** — `LIFECYCLE-04` says "User columns" but they're on `oauth_providers`. Planner amends REQUIREMENTS.md / ROADMAP.md as part of Phase 220's docs work; CONTEXT.md and runbook use precise location.

## Deferred Ideas

(Verbatim from CONTEXT.md `<deferred>` section — see CONTEXT.md for the canonical list.)

- Gate registry accessors by edition (`get_audit_extension()` / `get_branding_extension()` should check `is_enterprise()`).
- Audit-log entry on edition transitions.
- `geolens admin lifecycle pre-deactivate` CLI command.
- `docs/lifecycle/` directory if v14+ adds more lifecycle topics.
- Docker-compose-level lifecycle test (hybrid PR-CI + nightly).
- Doc-test for SC#3 (automated check that saml.md doesn't reintroduce "reversible" framing).
- Phase 221 round-trip symmetry test co-location with Phase 220's lifecycle test.

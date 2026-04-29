# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v13.1 — Open-Core Separation P1

**Shipped:** 2026-04-29
**Phases:** 8 (212–219) | **Plans:** 30 | **Commits:** 179

### What Was Built
- Open-core boundary closed: `core/` no longer reaches into `modules/settings/`; `auth/visibility.py` relocated to `catalog/authorization.py`; broadened architecture-guard test prevents regression.
- `IdentityProtocol` extracted in `core/identity.py`; 51 cross-domain `User` import sites retyped to `Identity`; `get_identity_extension()` hook lets enterprise overlays register custom identity backends.
- Auto-generated SDKs (Python via `openapi-python-client`, TypeScript via `@hey-api/openapi-ts`); `make sdks` regen one-shot; `make sdks-check` CI drift gate; `flatten_openapi_defs.py` preprocessor for OpenAPI 3.1 inline `$defs`.
- Apache-2.0 `geolens` CLI on PyPI: `login` (keyring + headless), `scan`, `publish`, `export stac` — consumes only the generated Python SDK; CI grep + tomllib gates enforce zero hand-rolled HTTP.
- SAML enterprise overlay: `geolens-enterprise` registers via `importlib.metadata` entry_points with dual `AuthExtension` + `IdentityExtension` Protocol seams; SP-initiated SSO + JIT provisioning + audited attribute→role mapping; admin UI 3-layer gated.
- Closing audit produced (Phase 218) and remediated (Phase 219) — OAuth IdP→role mapping P0 surfaced by audit closed via `is_enterprise()` schema + service gate; audit doc amended in place from BLOCKED → VERIFIED.

### What Worked
- **Architecture-guard tests as forcing functions.** Phase 212 added a settings-only guard; Phase 214 broadened it to a general core/-imports guard with an 18-file allowlist. Each refactor phase shipped its guard before merging — making layering invariants enforceable at CI time, not just review time.
- **Phase 219 added mid-milestone to close a P0.** Phase 218's audit surfaced an architectural P0 (OAuth IdP→role mapping in core) that hadn't been on the milestone plan. Adding Phase 219 to fix it (rather than waving the audit) preserved the boundary contract and kept the milestone's audit-grade promise intact.
- **Pitfall-driven planning.** Phase 217 caught a HIGH-severity ORM column-not-found risk before merge by empirically testing `deferred=True` mitigation (Pitfall 11) — saved a likely production outage path.
- **Round-trip tests over unit-test theater.** Phases 215 and 216 invested in real cross-process integration tests (uvicorn-on-free-port + CliRunner via `asyncio.to_thread`; both SDKs against live FastAPI app) rather than mocking. 12 SDK + 6 CLI round-trip tests give meaningful signal.
- **Carve-outs documented as intentional.** Phase 217 SC#1 (`git grep -i saml` returns zero matches in core) explicitly carved out 5 files of Pitfall 11 mitigation scaffolding. Documenting "carve-out, not violation" in module headers + SUMMARY + audit doc avoids future "why is this here?" cycles.

### What Was Inefficient
- **Paperwork drift across 4 phases.** Phases 214, 215, 217, 218 shipped with per-plan verification gates passing but no consolidated phase-level VERIFICATION.md. Required a separate paperwork close pass at milestone end; the `gsd-audit-milestone` audit returned `tech_debt` because of artifact gaps, not functional ones. Lesson: produce phase-level VERIFICATION.md at phase-close time, not aggregated retroactively.
- **REQUIREMENTS.md traceability lag.** SAML-08..12 + AUDIT-V1 stayed `[ ]` despite all five SCs verified — checkboxes were never flipped at phase-close. Same paperwork cause as above; same fix.
- **VALIDATION.md status drift.** 6/8 phases shipped with `status: draft / nyquist_compliant: false` because `/gsd-validate-phase` was never run as a closing step. The framing turned out to be honest ("paperwork only — green test baseline already covers"), but the field was misleading.
- **170 quick_tasks accumulated as cross-milestone backlog.** Spans 2026-03-16 → 2026-04-26 (v10.x–v13.0 era). Should have been triaged via `/gsd-cleanup` between milestones; now a hygiene debt that has to be cleared eventually.
- **Audit parser produced false-positive on OCCLI-02 frontmatter.** The audit reported "216-02-SUMMARY.md is `[]`" for `requirements:` — but the SUMMARY format uses `tags:` (which already contained `occli-02`). Lost a few minutes confirming the audit was wrong; the auditor's field-name expectation didn't match the SUMMARY convention.

### Patterns Established
- **Per-phase verification gate plan as the last plan of every phase.** Phase 214's Plan 04, Phase 215's Plan 05, Phase 217's Plan 05, Phase 218's Plan 01 all followed this pattern — explicit "verify all SCs" plan with its own SUMMARY. This pattern made phase-level VERIFICATION.md trivially aggregatable when finally produced.
- **`/gsd-plan-milestone-gaps` paperwork-close path.** When the audit returns `tech_debt` due to artifact gaps (not functional gaps), skip phase creation and edit directly. Documented in this retrospective so future milestones with the same shape know they have a fast-path.
- **`is_enterprise()` runtime gate at schema validator + service entry.** Phase 219 established the canonical pattern for community/enterprise feature gates: `model_validator(mode='after')` raises `ValueError` in community; service-layer code checks `is_enterprise()` before applying enterprise-only logic. Both layers must agree — schema-only gating leaves drift, service-only gating leaks via bulk import paths.
- **Audit doc amend-in-place over re-issue.** Phase 219 amended `oc-separation-audit-v13.1-close.md` in place (BLOCKED banner replaced with VERIFIED; pre-remediation state preserved as `### Pre-remediation state (2026-04-29)` subsection). Better than issuing a new audit document — single canonical artifact, audit-trail preserved.

### Key Lessons
1. **Run phase-close paperwork as part of phase-close, not milestone-close.** Phase-level VERIFICATION.md, REQUIREMENTS.md checkbox flip, VALIDATION.md formalization should all happen at phase-close. Milestone-close should be archival, not paperwork triage.
2. **A failed audit isn't a milestone block — it's signal.** Phase 218 BLOCKED on Boundary Integrity B− vs A− target, surfacing the OAuth IdP→role mapping P0. Adding Phase 219 mid-milestone closed the cluster and preserved the milestone-close promise. The instinct to "wave the audit" is wrong; the audit is doing its job.
3. **Scaffolding documented as carve-out is fine; scaffolding hidden in core is debt.** SAML's deferred=True ORM scaffolding in 5 core files is documented carve-out from SC#1. The pattern is: be honest about boundary violations and document them with rationale, vs. pretending the boundary is clean when it isn't.
4. **Cross-milestone hygiene needs an explicit cadence.** 170 accumulated quick_tasks is a hygiene debt that should have been resolved across milestones. Add `/gsd-cleanup` to the milestone-close ritual.

### Cost Observations
- Model mix: predominantly Opus 4.7 for planning + execution; Sonnet for parallel research/integration-check agents
- Notable: 4-day milestone with 8 phases (avg 12hr/phase wall-clock); generated SDK code (655 files, 112k LOC) was the largest line-count contribution, but the architectural work (10k LOC hand-written across boundary refactor + identity protocol + SAML overlay) was the substantive change.

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Key Change |
|-----------|--------|------------|
| v13.1 | 8 (212–219) | Architecture-guard tests as CI-enforced layering invariants; mid-milestone phase additions to close audit-surfaced P0s; per-phase verification gate plan as standard pattern |

### Cumulative Quality

| Milestone | Backend Tests | Notable |
|-----------|---------------|---------|
| v13.1 | 1999+ pass (baseline maintained throughout) | 12 SDK round-trip + 9 SAML integration + 9 enterprise + 112 CLI unit + 6 CLI round-trip new |

### Top Lessons (Verified Across Milestones)

1. *Pending — first retrospective; lessons will compound across future milestones.*

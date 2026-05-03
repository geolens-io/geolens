# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v13.5 — Enterprise Governance Seams

**Shipped:** 2026-05-03
**Phases:** 4 (232, 233, 234, 235) | **Plans:** 13 | **Commits:** 49

### What Was Built
- `PermissionExtension` now covers action checks, catalog visibility filtering, and dataset detail access with a Community default, overlay tests, and a chokepoint architecture guard.
- `WorkflowExtension` now covers publication transitions and transition hooks for `/status/`, `/target-status/`, and metadata `record_status` writes.
- Advanced-sharing gates now line up across schema validators, service guards, builder UI affordances, API/OpenAPI text, and GTM docs.
- Formal close audit verified Seam Quality A, Boundary Integrity A, Inventory Accuracy A−, and no unresolved P0/P1 findings.

### What Worked
- **Single-slot governance seams.** Permission and workflow policy both fit the established typed-accessor pattern, keeping overlay behavior explicit and testable.
- **Architecture guards kept the contract small.** The permission and workflow guards verify the exact chokepoints that would regress the seam, without pretending to prove every future policy surface.
- **Contract verification paid off.** Phase 234 checked schemas, services, UI, OpenAPI, and GTM copy together, preventing paid/free claims from drifting away from actual enforcement.
- **Close audit stayed honest.** Phase 235 separated seam readiness from future product UI scope and did not claim unrun full-suite coverage.

### What Was Inefficient
- **GSD milestone helpers misread this repo shape.** `init milestone-op` reported `v1.0`, and the generic milestone CLI counted archived/backlog phases. The close path needed manual scoping to phases 232-235.
- **Local DB provisioning remains uneven.** Some phase checks needed `POSTGRES_PORT=5434` or DB-provisioning bypasses because the default reachable database lacked PostGIS/pgvector.
- **Plan artifacts remain ignored by default.** `.planning/` archival files require intentional force-adds, which is easy to miss at milestone close.

### Patterns Established
- Governance seams should ship with Protocol + default + typed accessor + production chokepoint routing + overlay test + architecture guard.
- Paid/free product contracts need dual-layer enforcement (schema + service) plus UI and OpenAPI/GTM copy review.
- Formal milestone audits should explicitly note any tool-scoping anomalies rather than let helper output drive archive scope.

### Key Lessons
1. Treat GSD helper output as advisory when old archives and backlog phases are present; use `STATE.md` and the active ROADMAP section as the source of truth.
2. For open-core seams, "Ready" means a real overlay can alter behavior without core changes and a guard catches known bypasses.
3. Keep focused close-audit evidence separate from full-suite readiness, especially when local DB provisioning differs from CI.

### Cost Observations
- Model mix: inherited frontier model for planning and audit synthesis; Sonnet-class helper configuration noted by GSD tooling but not used for a spawned checker.
- Notable: same-day milestone with a low file count compared to v13.4, but high leverage because it closed two governance seams and the advanced-sharing product contract.

---

## Milestone: v13.4 — Boundary Closeout

**Shipped:** 2026-05-03
**Phases:** 7 (225, 226, 227, 228, 230, 231, 229) | **Plans:** 23 | **Commits:** 170

### What Was Built
- `ProcessingPort` and `CatalogPort` now invert both directions of the catalog/processing dependency cycle.
- `AIProviderExtension` and `EmbeddingProviderExtension` make chat/completion and embeddings provider dispatch extensible.
- SAML overlay tests write generated fixture output to temporary paths instead of mutating committed fixtures.
- Cold publish workflows verified public registry artifacts: `geolens`, `geolens-cli`, and `@geolens/sdk` at `1.0.0`.
- Post-implementation close gate produced `post-impl-20260503-v13-4.md` with Boundary Integrity A+, Coupling Health A−, Seam Quality A−.

### What Worked
- **Symmetric boundary ports.** Phase 225's `ProcessingPort` pattern was reusable for Phase 230's `CatalogPort`, making the second half of the cycle inversion faster and more auditable.
- **Architecture guards carried the milestone.** Bidirectional catalog/processing import guards plus provider-SDK import guards gave simple evidence for the close audit.
- **Cold publish verification closed an external blocker.** Phase 228 turned package workflows from wired-but-cold into verified public registry artifacts.
- **Post-impl audit fixed real P1s inline.** Format drift and stale test patch targets were caught and fixed before close.

### What Was Inefficient
- **The milestone roster changed midstream.** Phase 230 and 231 were promoted after the 2026-05-02 audit, which meant state/roadmap tools sometimes misidentified backlog `999.*` work as next.
- **Local DB provisioning still limits full-suite signal.** Host Postgres without pgvector forced focused checks or Compose-specific env usage.
- **Dirty unrelated work affected full-suite audit evidence.** In-progress advanced-sharing changes caused one embed-token failure during Phase 229 until stashed before archival.

### Patterns Established
- Protocol seams should ship with a default adapter, registry accessor, focused seam tests, and an architecture guard in the same phase.
- Post-impl close gates should treat local dirty worktree changes as residual risk unless they are part of the committed milestone surface.
- For open-core feature gates, schema validators and service-layer checks should agree.

### Key Lessons
1. Promote audit-discovered backlog items into the active milestone only after updating both roadmap and state, otherwise transition tooling can point at backlog phases.
2. Keep milestone-close tags on a clean worktree; stash unrelated in-progress work before archival.
3. Full-suite claims need a stable local PostGIS + pgvector database, otherwise reports should use focused checks and document the environment gap.

### Cost Observations
- Model mix: planner/executor agents used inherited frontier model for hard refactors; Sonnet-class agents handled research/checking.
- Notable: 7 phases in 3 days, with generated/publication artifacts contributing heavily to file count.

---

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
| v13.5 | 4 (232, 233, 234, 235) | Governance seams for permissions and workflows; advanced-sharing contract aligned across schema/service/UI/API/GTM; close gate at A/A/A− |
| v13.4 | 7 (225, 226, 227, 228, 230, 231, 229) | Symmetric Protocol boundaries for catalog/processing; AI + embeddings provider seams; post-impl close gate with A+/A−/A− grades |
| v13.1 | 8 (212–219) | Architecture-guard tests as CI-enforced layering invariants; mid-milestone phase additions to close audit-surfaced P0s; per-phase verification gate plan as standard pattern |

### Cumulative Quality

| Milestone | Backend Tests | Notable |
|-----------|---------------|---------|
| v13.5 | Focused permission/workflow architecture guards, advanced-sharing DB-backed tests, frontend sharing tests, and OpenAPI check green; full-suite not rerun | PermissionExtension and WorkflowExtension now rated Ready; advanced-sharing paid/free contract is enforced and documented |
| v13.4 | Focused architecture/provider/reupload checks green; full-suite limited by local DB/dirty-worktree constraints | Bidirectional import guards and provider-SDK guards now enforce open-core boundaries |
| v13.1 | 1999+ pass (baseline maintained throughout) | 12 SDK round-trip + 9 SAML integration + 9 enterprise + 112 CLI unit + 6 CLI round-trip new |

### Top Lessons (Verified Across Milestones)

1. Architecture guard tests are the strongest close-gate evidence for boundary milestones.
2. Post-impl audits should fix P1s inline before milestone archival.
3. Keep the worktree clean before milestone tags; stash unrelated WIP explicitly.
4. GSD milestone helpers need manual scope validation in repos with archived and backlog phase history.

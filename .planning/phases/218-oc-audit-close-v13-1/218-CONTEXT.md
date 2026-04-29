# Phase 218: oc-audit-close-v13.1 - Context

**Gathered:** 2026-04-29
**Status:** Ready for planning
**Mode:** `--auto` (Claude selected recommended defaults across all gray areas)

<domain>
## Phase Boundary

The v13.1 milestone's audit-grade promise is **independently verified** by re-running `/oc-audit` against post-217 state and committing the result as a named "closing" audit document. The closing audit:

- Lives at the canonical path `docs-internal/audits/oc-separation-audit-v13.1-close.md` (NOT a date-named file).
- Documents grades that meet or exceed the v13.1 targets: **Boundary ≥ A−, Seam Quality ≥ B, OSS Surface ≥ C**.
- Explicitly compares to the source baseline (`docs-internal/audits/oc-separation-audit-20260426-b.md`) so the v13.1 trajectory (B → A−, C → B, D → C) is traceable in one document.
- Triages every P1-tagged residual finding the audit surfaces: each P1 is either (a) routed to a fix-now follow-up phase, (b) demoted to P2 with rationale, or (c) accepted as out-of-scope for v13.1 with explicit justification.

This is a verification phase — no production code changes, no schema changes, no UI changes. Output is a single markdown file plus its commit. The phase **gates milestone close**: if the audit grades fall short of targets, the phase stops and a remediation phase is added before v13.1 ships.

**In scope:**
1. Run the existing `/oc-audit` skill against current `main` (post-217 merged state).
2. Save its output as `docs-internal/audits/oc-separation-audit-v13.1-close.md` (rename from the default `oc-separation-audit-{YYYYMMDD}.md` produced by the skill).
3. Verify the three target grades; if any miss, document the gap and STOP — do not silently advance milestone close.
4. Add a `## P1 Residual Triage` section to the closing audit file (one row per P1 finding the audit surfaces) with a verdict for each: **Fix in 219**, **Demote to P2** (+ rationale), or **Accept as OOS** (+ rationale).
5. Update `docs-internal/audits/oc-separation-deferred-items-20260426.md` — flip the six P1 rows that map to phases 212–217 from "Suggested phase" to "Closed by Phase N (date)" so the deferred-items doc reflects v13.1 reality.
6. Commit the closing audit doc + the deferred-items update; STATE.md gets the standard discuss-phase commit via the workflow.

**Out of scope (capture as deferred ideas if they surface):**
- Modifying the `/oc-audit` skill itself (skill is canonical; this phase consumes it).
- Fixing any new P0/P1 findings the audit surfaces — those become their own phase (e.g., 219) or move to a v13.2 backlog item; this phase only triages.
- Re-running the audit a second time after fixes — that's a separate phase if needed.
- Touching SaaS/Cloud-tier criteria (the skill explicitly defers SaaS readiness — see skill INTAKE).
- Editing GTM boundary docs (`docs-internal/GTM/*.md`) based on audit findings — that's a separate writing pass.
- Closing the milestone (separate `/gsd-complete-milestone` step after this phase verifies).

</domain>

<decisions>
## Implementation Decisions

### Audit invocation mechanics

- **D-01:** Invoke `/oc-audit` directly via the existing slash command. Do NOT modify the skill, do NOT inline its 6-subagent dispatch in this phase's plan, and do NOT reimplement scoring. The plan's job is to *run* the skill, capture its output, and post-process. Reason: skill is canonical and exercised; reproducing it inline would diverge from the source-of-truth grading rubric.
- **D-02:** After `/oc-audit` produces `docs-internal/audits/oc-separation-audit-{YYYYMMDD}.md`, **rename it** to `docs-internal/audits/oc-separation-audit-v13.1-close.md`. Reason: AUDIT-V1 specifies the exact output path; the skill itself uses date-named files. Renaming after the fact keeps the skill unmodified and makes the closing audit the durable, milestone-bound artifact (not just one of many dated audits). The intermediate dated file is never committed (planner should add `git mv` or rename before staging).
- **D-03:** The closing audit document MUST include the standard `## 8. Comparison to Prior Audit` section that the `/oc-audit` skill's template already supports (`.claude/commands/oc-audit.md` "Report structure"). The "prior audit" reference is `docs-internal/audits/oc-separation-audit-20260426-b.md` (the source baseline that motivated the v13.1 milestone). Section 8 must include a small grade-delta table:

  ```
  | Dimension          | Source (2026-04-26) | v13.1 Close | Δ | Target | Met? |
  |--------------------|---------------------|-------------|---|--------|------|
  | Boundary Integrity | B                   | A−          | ↑ | A−     | ✓    |
  | Seam Quality       | C                   | B           | ↑ | B      | ✓    |
  | OSS Surface        | D                   | C           | ↑ | C      | ✓    |
  ```

  Reason: SC#1 is "running `/oc-audit` produces grades meeting or exceeding targets" — a grade-delta table is the most direct verification artifact. Without it, the verification is just narrative and not auditable.

### P1 residual triage

- **D-04:** P1 triage decisions live **in the closing audit doc itself** as a new `## P1 Residual Triage` section appended after Section 8. Schema:

  ```
  | # | Finding (audit ref) | File:line | Verdict | Rationale | Follow-up |
  |---|---------------------|-----------|---------|-----------|-----------|
  | 1 | [audit §N row]      | [file]    | Fix-now | [why]     | Phase 219 |
  | 2 | …                   | …         | Demote  | [why P2]  | deferred-items.md row added |
  | 3 | …                   | …         | Accept  | [why OOS] | none      |
  ```

  Reason: keeps the verification + triage co-located so a future reader sees both "what we found" and "what we decided to do" in one document. SC#3 explicitly requires the triage be "explicit" — a dedicated section satisfies that more clearly than scattered prose.

- **D-05:** Three triage verdicts allowed, each with mandatory rationale:
  1. **Fix-now** → Spawn a follow-up phase (typical: 219). The follow-up phase number/name is recorded in the triage row. Example: a P0 surfaces (regression introduced post-217) — must fix before milestone close.
  2. **Demote to P2** → Add a row to `docs-internal/audits/oc-separation-deferred-items-20260426.md` under "P2 — Address as enterprise tier ships" with the rationale. The closing audit's triage row references the new deferred-items entry.
  3. **Accept as OOS** → No follow-up; rationale must explicitly justify why the finding is acceptable for v13.1 (e.g., "P1 marketplace hook was already documented as out-of-scope for the open-core P1 milestone — see PROJECT.md current-milestone scope").

  Reason: aligns with the language in ROADMAP §218 SC#3 verbatim. Forces every P1 to a recorded decision rather than letting items drift.

### Failure handling

- **D-06:** If any of the three target grades is missed (Boundary < A−, Seam Quality < B, OSS Surface < C), the phase **STOPS** before commit. The plan's verification gate explicitly checks the three grades and exits non-zero on shortfall. Reason: AUDIT-V1 is a milestone-level success criterion; silently committing a sub-target audit would falsify the milestone close. The expectation given post-217 state (audit-export gated, visibility relocated, IdentityProtocol extracted, openapi.json snapshotted, SDKs published, CLI MVP shipped, SAML moved to enterprise overlay) is that all three targets are met — but the gate is enforced regardless.
- **D-07:** On grade shortfall, the phase's executor:
  1. Writes the closing audit anyway (so the gap is visible) but with a `## ⚠ MILESTONE CLOSE BLOCKED` banner at the top stating which grade(s) missed and by how much.
  2. Files a remediation phase recommendation (e.g., "Phase 219: oc-audit-remediate-{dimension}") via a deferred-items entry.
  3. Returns control to the user — does NOT auto-spawn a remediation phase, does NOT auto-advance the chain. Manual intervention required.

  Reason: a shortfall is an architectural surprise that warrants user judgment about scope (fix-now vs slip to v13.2). The chain must not paper over it.

### Deferred-items doc maintenance

- **D-08:** Update `docs-internal/audits/oc-separation-deferred-items-20260426.md` as part of this phase's commits. Specifically: for each of the six P1 rows in the "P1 — Should ship before first paid customer" table, change the "Suggested phase" column to "Closed by Phase N (date)". Six closures expected:
  - SDKs from OpenAPI → Closed by Phase 215 (2026-04-27)
  - `geolens` CLI MVP → Closed by Phase 216 (2026-04-27)
  - `auth/visibility.py` relocate → Closed by Phase 213 (2026-04-27)
  - Extract `IdentityProtocol` → Closed by Phase 214 (2026-04-27)
  - SAML enterprise overlay → Closed by Phase 217 (2026-04-29)
  - core ↔ settings layering inversion → Closed by Phase 212 (2026-04-27)

  Reason: leaves a clean source of truth for v13.2+ planning. Without this update, future readers won't know which deferred items are truly still pending vs already shipped.

### Plan structure

- **D-09:** **Single plan** for this phase (`218-01-run-and-close-audit`). The work is small, sequential, and atomic: run skill → rename → verify grades → triage P1s → update deferred-items → commit. Splitting it across multiple plans would add ceremony without isolation benefit. Reason: phase is essentially one tightly-bound deliverable; multi-plan would only help if grade verification could happen in parallel with triage, which it can't (triage depends on audit output).
- **D-10:** Verification gate for the plan is automated where possible:
  1. File exists at `docs-internal/audits/oc-separation-audit-v13.1-close.md` ✓
  2. File contains a Scorecard table with the three target dimensions ✓
  3. Each target grade meets or exceeds threshold (parser checks the letter grade and `±` modifier) ✓
  4. File contains `## 8. Comparison to Prior Audit` section ✓
  5. File contains `## P1 Residual Triage` section with one row per P1 finding ✓
  6. `oc-separation-deferred-items-20260426.md` has six closure markers (or fewer if some are absent — planner verifies expected closures against actual baseline) ✓

  Reason: AUDIT-V1 verification should be machine-checkable, not narrative. Grade parsing prevents "looks fine" approval of a sub-target close.

### Claude's Discretion

- **Audit invocation execution context:** The `/oc-audit` skill is heavyweight (6 parallel subagents). Planner decides whether the executor invokes it directly in the main loop or delegates to a single dispatch agent. Either is acceptable — the output (the audit doc) is what matters.
- **Comparison narrative depth:** Section 8 grade-delta table is mandatory; the surrounding narrative (what regressed, what improved) is at planner/executor discretion. Keep it terse — the table is the load-bearing artifact.
- **Triage row ordering:** P1 triage rows MAY be sorted by audit section number, by verdict (Fix-now first), or by leverage. No mandate.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Audit skill (the tool this phase invokes)
- `.claude/commands/oc-audit.md` — The `/oc-audit` slash command definition. Defines INTAKE → 6 SUBAGENTS → SYNTHESIS → DELIVERY flow. The skill writes to `docs-internal/audits/oc-separation-audit-{YYYYMMDD}.md` by default; this phase renames the output to the canonical close-path.

### Source baseline (what we're closing against)
- `docs-internal/audits/oc-separation-audit-20260426-b.md` — Same-day re-run of the source baseline that motivated v13.1. **Authoritative baseline** for Section 8 grade-delta comparison. Grades: Boundary B, Seam Quality C, OSS Surface D.
- `docs-internal/audits/oc-separation-audit-20260426.md` — Original morning-of source baseline (kept for completeness; same grades as the `-b.md` re-run).
- `docs-internal/audits/oc-separation-deferred-items-20260426.md` — Source-of-truth deferred-items doc. **This phase updates the P1 table** to mark v13.1-completed items with closure markers.

### Most recent reference run (mid-milestone, shows grade trajectory)
- `docs-internal/audits/oc-separation-audit-20260427.md` — Run after the 2026-04-27 inline remediation pass and after Phases 212–216 shipped, but BEFORE Phase 217 (SAML overlay). Grades: Boundary B−, Seam Quality C+, OSS Surface A−. **Note:** This run also surfaced new P0/P1 findings (IdP group-to-role mapping in Community, Marketplace billing in base runtime, branding UI key mismatch) that were NOT in the source baseline. Phase 218 must triage whether those findings remain in the v13.1-close audit and how to handle them.

### Boundary rules consumed by the skill
- `docs-internal/GTM/free-vs-enterprise.md` — Free vs Enterprise feature boundary.
- `docs-internal/GTM/pricing-to-tiers.md` — Tier pricing structure (Team / Business / Enterprise).
- `docs-internal/GTM/repo-split.md` — Open-core repo split rules. **IdP role mapping is explicitly enterprise per this doc** — relevant to triage of the 2026-04-27 P0 carry-over finding.

### Milestone scope anchors
- `.planning/PROJECT.md` §"Current Milestone: v13.1 Open-Core Separation P1" — defines the milestone's grade-target promise (B → A−, C → B, D → C).
- `.planning/REQUIREMENTS.md` §AUDIT-V1 — the requirement this phase closes. Verbatim target grades.
- `.planning/ROADMAP.md` §"Phase 218: oc-audit-close-v13.1" — Goal, Depends on (212–217 all merged), three Success Criteria.
- `.planning/STATE.md` — Confirms 217 shipped 2026-04-29; Phase 218 is the milestone gate.

### Prior phase context (for evidence cross-checks)
- `.planning/phases/212-core-settings-decouple/212-CONTEXT.md` — `core ↔ settings` layering fix evidence.
- `.planning/phases/213-catalog-authz-relocate/213-CONTEXT.md` — `auth/visibility.py` → `catalog/authorization.py` relocation evidence.
- `.planning/phases/214-identity-protocol-extract/214-CONTEXT.md` — `IdentityProtocol` extraction evidence.
- `.planning/phases/215-sdks-from-openapi/215-CONTEXT.md` — Python + TypeScript SDK delivery evidence.
- `.planning/phases/216-geolens-cli-mvp/216-CONTEXT.md` — `geolens` CLI MVP evidence.
- `.planning/phases/217-auth-saml-enterprise/217-CONTEXT.md` — SAML enterprise overlay evidence (lives in `~/Code/geolens-enterprise/`, no SAML in core).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`/oc-audit` slash command** at `.claude/commands/oc-audit.md` — invoked verbatim. 6 parallel subagent prompts, 8-section output template, embedded boundary rules, "What Not to Flag" false-positive guard.
- **`docs-internal/audits/`** directory — well-established convention. 100+ prior audit files. Closing audit lands here.
- **`docs-internal/audits/oc-separation-deferred-items-20260426.md`** — existing P1/P2/P3 deferred-items table. Phase updates the P1 section in place.

### Established Patterns
- **Audit invocation pattern** — every prior `/oc-audit` run produced a date-named file and committed it without renaming. **This phase deviates** by renaming the output to a milestone-bound name (`v13.1-close.md`). The deviation is intentional and AUDIT-V1-driven; planner must call it out so executor doesn't follow the dated-file precedent.
- **Verification gate pattern** — Phases 212–217 all used wave-based plans with executor verification (test runs, lint, evidence checks). This phase's verification is a markdown structural + grade-parse check, not a code test. Pattern: a small bash script in the plan that checks file presence + scorecard parse + grade thresholds.
- **STATE.md update via `gsd-sdk query state.record-session`** — handled by the discuss-phase workflow itself; plan does not need to manage STATE.md directly.

### Integration Points
- **No production code touched** — verification phase only.
- **Files written:**
  - `docs-internal/audits/oc-separation-audit-v13.1-close.md` (new file)
  - `docs-internal/audits/oc-separation-deferred-items-20260426.md` (modify P1 table — six closure markers)
- **Files NOT touched:** `.claude/commands/oc-audit.md`, any code under `backend/` or `frontend/`, `.planning/PROJECT.md`, `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md` (milestone close updates these in a later step, not in 218).

### Known facts to verify (post-217 evidence the audit will sample)
The audit will sample these — listing them so the executor can sanity-check before invoking the skill:
1. `backend/app/modules/audit/router.py:96` — `_ent: None = Depends(require_enterprise)` (audit-export gate).
2. `backend/app/modules/catalog/authorization.py` — exists; `backend/app/modules/auth/visibility.py` does NOT (relocation).
3. `backend/openapi.json` — exists (snapshot landed in 215).
4. `cli/` directory — exists (geolens CLI MVP from 216).
5. `sdks/python/geolens_sdk/` — exists (SDK from 215).
6. `git grep -i saml backend/` — returns zero hits outside `tests/` and `docs-internal/` (217 scrubbed core docstrings).
7. `~/Code/geolens-enterprise/geolens_enterprise/auth/saml/` — SAML overlay lives there, NOT in this repo.

### Known potential audit findings (pre-flagged from 2026-04-27 run, still relevant)
The 2026-04-27 audit (run mid-milestone, AFTER inline remediation but BEFORE 217 SAML phase) surfaced these. The closing audit must re-evaluate:
1. **IdP group-to-role mapping in Community** (P0 in 2026-04-27 audit) — `oauth/models.py:49-51`, `SettingsAuthTab.tsx:502-528`. Likely surfaces again. Triage candidate: **Fix-now Phase 219** (P0 must not ship in v13.1) OR **Demote to P2** if reclassified as forward-compat scaffolding.
2. **Marketplace billing hook in base runtime** (P1) — `docker-compose.yml:128-129`, `core/config.py:87-88`, `api/main.py:184-190`. Triage candidate: **Demote to P2** (env vars unset by default; not a true boundary violation).
3. **Branding UI key mismatch** (P1) — `frontend/src/api/settings.ts:128-131` sends `branding_show_badge`; backend expects `branding.show_badge`. Triage candidate: **Fix-now Phase 219** (small mechanical fix, paid feature broken).

The audit may also surface findings that have been resolved by 217 work or by drift between 04-27 and 04-29. Executor must not pre-judge — run the audit, then triage what it actually surfaces.

</code_context>

<specifics>
## Specific Ideas

- **No grade negotiation.** If the audit grades fall short of A−/B/C, the phase STOPS. No "close enough" interpretation; the targets in REQUIREMENTS.md and ROADMAP.md are the contract.
- **Closing audit is a milestone artifact, not a dated artifact.** The filename `oc-separation-audit-v13.1-close.md` is the contract — date-named files belong to the routine audit cadence, not to milestone closes.
- **Triage must be explicit, not inferred.** ROADMAP SC#3 says "explicitly triaged" — the closing audit must state the verdict for every P1 row in plain table form, not bury it in narrative.
- **Don't re-implement the skill.** If the planner is tempted to inline the 6 subagents into the plan, that's a planning error. The skill is the canonical grader; planner orchestrates invocation, not regrading.

</specifics>

<deferred>
## Deferred Ideas

- **Phase 219 placeholder for any Fix-now P1s** — if the closing audit surfaces P0/P1 findings that get a "Fix-now" verdict, planner queues a Phase 219 add against the v13.1 milestone (or a v13.2 milestone slot if scope warrants). NOT created in advance — only if the audit surfaces fixables.
- **Helm chart for K8s deployment** — already a P3 row in deferred-items; not relevant to v13.1 close.
- **Tenant scoping infrastructure** — already a P3 row; v14+ work.
- **Enterprise frontend bundle code-split** — already a P2 row in deferred-items.
- **`geolens.yaml` catalog manifest spec** — already a P2 row; deferred until CLI usage signals shape.
- **Re-running the audit a second time** after any 219 fixes — if a 219 happens, deciding whether to re-issue v13.1-close.md or stamp a v13.1.1-close.md is a 219-time decision, not a 218 concern.

</deferred>

---

*Phase: 218-oc-audit-close-v13.1*
*Context gathered: 2026-04-29*

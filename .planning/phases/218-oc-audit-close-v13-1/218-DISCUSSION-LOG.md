# Phase 218: oc-audit-close-v13.1 - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-29
**Phase:** 218-oc-audit-close-v13.1
**Mode:** `--auto --chain` — Claude auto-selected the recommended option for every gray area; no interactive AskUserQuestion calls were made. Single-pass cap enforced (one CONTEXT.md write).
**Areas discussed:** Audit invocation mechanics, Closing-audit format, P1 residual triage, Failure handling, Plan structure

---

## Audit invocation mechanics

| Option | Description | Selected |
|--------|-------------|----------|
| Run `/oc-audit` directly, then rename output to v13.1-close.md | Skill stays canonical and unmodified; phase post-processes its output. | ✓ (recommended default) |
| Modify `/oc-audit` skill to accept a `--output` flag | Cleaner one-step invocation; couples the milestone close to a skill change. | |
| Inline the 6-subagent dispatch into the phase plan | Avoids the rename step; duplicates the canonical grader and risks divergence. | |

**Auto-selected:** Run `/oc-audit` directly, then rename. **Rationale:** Keeps the skill as the single source of truth for grading. Post-processing (rename + add P1 triage section) is small enough to live in the phase plan without warranting a skill change.

---

## Closing-audit format

| Option | Description | Selected |
|--------|-------------|----------|
| Include §8 grade-delta table comparing to source baseline (2026-04-26-b) | The skill's template already supports a §8 "Comparison to Prior Audit" — fill it with a delta table referencing the source baseline that motivated v13.1. | ✓ (recommended default) |
| Comparison narrative without explicit table | Easier to write; harder for future reviewers to verify SC#1. | |
| No comparison section (just current grades) | Simplest; loses the milestone-trajectory traceability. | |

**Auto-selected:** §8 grade-delta table comparing to source baseline. **Rationale:** SC#1 is "running `/oc-audit` produces grades meeting or exceeding targets" — a delta table is the most direct verification artifact. Narrative-only comparison is auditable but not at-a-glance verifiable.

---

## P1 residual triage

| Option | Description | Selected |
|--------|-------------|----------|
| Dedicated `## P1 Residual Triage` section in the closing audit doc | Co-locates "what we found" + "what we decided" in one document. Each P1 gets a row with verdict (Fix-now / Demote / Accept) and rationale. | ✓ (recommended default) |
| Update existing `oc-separation-deferred-items-20260426.md` only | Spreads decisions across docs; harder to read milestone close as a single artifact. | |
| Spawn a separate `218-TRIAGE.md` file | Adds ceremony; the closing audit is already the right home for milestone-close decisions. | |

**Auto-selected:** Dedicated section in the closing audit. **Rationale:** ROADMAP SC#3 explicitly says triage must be "explicit"; a dedicated table-formatted section is the most explicit form. Three verdicts allowed: Fix-now (→ follow-up phase), Demote to P2 (→ deferred-items.md row), Accept as OOS (with rationale).

Also auto-selected: update `oc-separation-deferred-items-20260426.md` to mark the six P1 rows that map to phases 212–217 as "Closed by Phase N (date)" — leaves a clean source of truth for v13.2 planning.

---

## Failure handling (grade shortfall)

| Option | Description | Selected |
|--------|-------------|----------|
| STOP phase on shortfall; write closing audit with ⚠ banner; require manual user decision | Verification gate is enforced; user judges fix-now-vs-slip. Auto-chain stops. | ✓ (recommended default) |
| Auto-spawn remediation phase 219 on shortfall | Removes user from the loop; risks scope drift. | |
| Allow "close-enough" interpretation if within one half-grade | Soft; falsifies the milestone-close contract. | |

**Auto-selected:** STOP on shortfall + ⚠ banner + manual user decision. **Rationale:** AUDIT-V1 is a milestone-level success criterion; silently committing a sub-target audit would falsify the milestone close. A shortfall is an architectural surprise that warrants user judgment.

---

## Plan structure

| Option | Description | Selected |
|--------|-------------|----------|
| Single plan (`218-01-run-and-close-audit`) | Sequential atomic work: run skill → rename → verify → triage → update deferred-items → commit. | ✓ (recommended default) |
| Multi-plan (run audit, triage, commit as separate plans) | Adds wave-orchestration ceremony; no parallel work to enable. | |
| Two plans (audit + triage) | Some isolation, but triage has hard data-dep on audit output. | |

**Auto-selected:** Single plan. **Rationale:** Phase is essentially one tightly-bound deliverable. Multi-plan would help only if grade verification could happen in parallel with triage, which it can't (triage depends on audit output).

Verification gate auto-selected: machine-checkable (file-presence + scorecard parse + grade thresholds + section presence + closure-marker count). Reason: AUDIT-V1 verification should not be narrative-only.

---

## Claude's Discretion

The following items were left to planner/executor judgment in CONTEXT.md (see `### Claude's Discretion` section):

- `/oc-audit` execution context (direct invocation vs single dispatch agent) — output is what matters.
- Section 8 surrounding narrative depth (table is mandatory; prose is terse-by-default).
- P1 triage row ordering (by audit section, by verdict, or by leverage — no mandate).

## Deferred Ideas

The following surfaced as relevant context but explicitly belong elsewhere — captured in CONTEXT.md `<deferred>`:

- Phase 219 placeholder for any Fix-now P1s (created on demand only).
- Helm chart for K8s deployment (already P3 in deferred-items).
- Tenant scoping infrastructure (already P3, v14+ work).
- Enterprise frontend bundle code-split (already P2).
- `geolens.yaml` catalog manifest spec (already P2; defer until CLI usage signals shape).
- Re-running the audit after any 219 fixes (decision belongs to 219-time, not 218-time).

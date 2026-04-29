---
phase: 218
slug: oc-audit-close-v13-1
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-29
formalized: 2026-04-29
formalization_note: "Post-hoc paperwork close per v13.1-MILESTONE-AUDIT.md (2026-04-29). Audit-only phase — produces no executable code. verify_close_audit.py + preflight.sh structural verification gates committed; Phase 219 closed the OAuth IdP P0 surfaced by this audit and amended the audit document in place. No coverage gaps; no executable code to test."
---

# Phase 218 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> **NOTE:** This phase produces no executable production code — it's a verification/closing-audit phase. The "tests" are a single inline Python verification script that asserts the closing audit document was produced correctly. See `218-RESEARCH.md §"Validation Architecture"` for the full strategy.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Inline Python script (Python 3.14.3 on host; no pytest/jest/vitest involvement) |
| **Config file** | None — script is self-contained, ~50 lines |
| **Quick run command** | `python3 .planning/phases/218-oc-audit-close-v13-1/verify_close_audit.py` |
| **Full suite command** | Same — single script asserts all six checks |
| **Estimated runtime** | < 1 second |

---

## Sampling Rate

- **After every task commit:** Run `python3 .planning/phases/218-oc-audit-close-v13-1/verify_close_audit.py` (script accepts being run partway — checks that have not yet been satisfied print `❌ NOT YET` rather than failing).
- **After every plan wave:** Run the same script. The Wave 2 task explicitly invokes it as the verification gate.
- **Before `/gsd-verify-work`:** Full suite (the same script) must exit 0 with all six checks passing.
- **Max feedback latency:** < 1 second.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 218-01-W0 | 01 | 0 | AUDIT-V1 | — | Pre-flight evidence checks pass (audit-export gated, visibility relocated, openapi.json present, cli/ + sdks/python/ exist, no SAML logic in core, SAML overlay in enterprise repo) | smoke | `bash .planning/phases/218-oc-audit-close-v13-1/preflight.sh` (planner-created) | ❌ W0 | ⬜ pending |
| 218-01-W1a | 01 | 1 | AUDIT-V1 | — | `/oc-audit` skill produces a dated audit doc at `docs-internal/audits/oc-separation-audit-{YYYYMMDD}.md` | manual | Slash invocation (executor agent runs `/oc-audit` via SlashCommand or direct Skill dispatch) | ❌ W0 | ⬜ pending |
| 218-01-W1b | 01 | 1 | AUDIT-V1 | — | Audit doc renamed to `docs-internal/audits/oc-separation-audit-v13.1-close.md` (per D-02) | unit | `test -f docs-internal/audits/oc-separation-audit-v13.1-close.md` | ❌ W0 | ⬜ pending |
| 218-01-W1c | 01 | 1 | AUDIT-V1 | — | §8 Comparison to Prior Audit section appended with grade-delta table (per D-03) | unit | `grep -q "^## 8\\. Comparison" docs-internal/audits/oc-separation-audit-v13.1-close.md` | ❌ W0 | ⬜ pending |
| 218-01-W1d | 01 | 1 | AUDIT-V1 | — | `## P1 Residual Triage` section appended with one row per P1 finding (per D-04) | unit | `grep -q "^## P1 Residual Triage" docs-internal/audits/oc-separation-audit-v13.1-close.md` | ❌ W0 | ⬜ pending |
| 218-01-W1e | 01 | 1 | AUDIT-V1 | — | `oc-separation-deferred-items-20260426.md` updated with six closure markers (per D-08) | unit | `grep -c "Closed by Phase" docs-internal/audits/oc-separation-deferred-items-20260426.md` returns ≥ 6 | ❌ W0 | ⬜ pending |
| 218-01-W2 | 01 | 2 | AUDIT-V1 | — | All target grades meet threshold (Boundary ≥ A−, Seam Quality ≥ B, OSS Surface ≥ C); script exits 0 (per D-06/D-10) | unit | `python3 .planning/phases/218-oc-audit-close-v13-1/verify_close_audit.py` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `.planning/phases/218-oc-audit-close-v13-1/verify_close_audit.py` — Python verification script (six assertions: file presence, scorecard parse, three threshold comparisons, §8 section, P1 Residual Triage section, six closure markers in deferred-items.md). Source: see `218-RESEARCH.md §"Verification Gate Implementation"`.
- [ ] `.planning/phases/218-oc-audit-close-v13-1/preflight.sh` — bash pre-flight script that asserts seven facts about post-217 disk state before `/oc-audit` is invoked. Source: see `218-RESEARCH.md §"Pre-flight Evidence Checks"`.

*Existing test infrastructure does NOT cover this phase — its assertions are markdown-structural, not code-behavioral. Wave 0 creates both scripts before any audit invocation.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `/oc-audit` skill invocation | AUDIT-V1 | Slash command runtime can't be programmatically asserted (the skill's 6-subagent dispatch is its own black box). | Executor agent invokes `/oc-audit` via Skill dispatch or SlashCommand; success = a dated audit file appears at `docs-internal/audits/oc-separation-audit-{YYYYMMDD}.md`. The Python verify script then takes over. |
| P1 triage verdict reasonableness | AUDIT-V1 SC#3 | The verdict for each P1 (Fix-now / Demote / Accept) requires judgment about phase scope and milestone close-ness. | Plan-checker reviews the triage table for: (a) every P1 has a verdict, (b) every "Fix-now" names a follow-up phase, (c) every "Demote" cites a deferred-items.md row, (d) every "Accept" cites a phase-scope reason. |
| §8 grade-delta table accuracy | AUDIT-V1 SC#1 | Confirming the source-baseline grades (B / C / D) are quoted correctly requires reading the source file. | Reviewer cross-checks §8's "Source (2026-04-26)" column against `oc-separation-audit-20260426-b.md` Scorecard. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify (verified — every wave has at least one automated check)
- [ ] Wave 0 covers all MISSING references (preflight.sh + verify_close_audit.py)
- [ ] No watch-mode flags
- [ ] Feedback latency < 1s
- [ ] `nyquist_compliant: true` set in frontmatter (set by planner after task list locks)

**Approval:** pending

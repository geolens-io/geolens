---
phase: 218-oc-audit-close-v13-1
plan: 01
subsystem: audit
tags: [audit, milestone-close, verification, open-core, oc-audit, audit-v1]

# Dependency graph
requires:
  - phase: 217-auth-saml-enterprise
    provides: SAML enterprise overlay shipped to sibling repo; deferred-group SAML scaffolding in core; documented carve-out for Pitfall 11
  - phase: 216-geolens-cli-mvp
    provides: geolens CLI MVP (7 commands) — closes one of six v13.1 P1 deferred items
  - phase: 215-sdks-from-openapi
    provides: Python + TypeScript SDKs Apache-2.0 + OpenAPI drift gate — closes one of six v13.1 P1 deferred items
  - phase: 214-identity-protocol-extract
    provides: IdentityProtocol/IdentityExtension wired into auth/dependencies — closes one of six v13.1 P1 deferred items
  - phase: 213-catalog-authz-relocate
    provides: auth/visibility.py → catalog/authorization.py relocation — closes one of six v13.1 P1 deferred items
  - phase: 212-core-settings-decouple
    provides: core ↔ settings layering inversion eliminated — closes one of six v13.1 P1 deferred items
provides:
  - Closing-audit artifact docs-internal/audits/oc-separation-audit-v13.1-close.md (uncommitted on disk; awaits user judgment per D-06)
  - Six P1 closure markers in oc-separation-deferred-items-20260426.md (uncommitted on disk)
  - Two P2 deferred-items rows for Demote-to-P2 verdicts (Marketplace billing, CLI/SDK distribution activation)
  - Verified audit trajectory (B− → B overall; Boundary B → B−; Seam C → B; OSS D → A−)
  - Independent identification of single P0 root cause (OAuth IdP→role mapping in core) blocking milestone close
  - Recommended remediation phase scope (Phase 219 ~1d) + alternative slip-to-v13.2 path
  - Reusable verification gate (verify_close_audit.py) and pre-flight (preflight.sh) for future milestone-close audits
affects: [219-oc-audit-remediate-idp-mapping (proposed), v13.1 milestone close decision, v13.2 backlog]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Milestone-close audit pattern: rename dated /oc-audit output to v{milestone}-close.md; append §8 grade-delta + ## P1 Residual Triage; gate via stdlib Python verifier"
    - "Verify gate pattern: stdlib-only Python script with Unicode-minus normalization (U+2212 → U+002D) for Scorecard parsing across audits typed by different runs"
    - "STOP-on-shortfall pattern: gate exits non-zero, executor MUST NOT swallow code, MUST NOT auto-spawn remediation, MUST surface gap for user judgment (D-06/D-07)"

key-files:
  created:
    - .planning/phases/218-oc-audit-close-v13-1/preflight.sh
    - .planning/phases/218-oc-audit-close-v13-1/verify_close_audit.py
    - docs-internal/audits/oc-separation-audit-v13.1-close.md (UNCOMMITTED on disk)
  modified:
    - docs-internal/audits/oc-separation-deferred-items-20260426.md (UNCOMMITTED on disk; six P1 closure markers + two new P2 rows)

key-decisions:
  - "v13.1 milestone close BLOCKED: Boundary Integrity grade B− does not meet A− target. Single P0 root cause: OAuth IdP→role mapping in core (oauth/{schemas,service,models}.py) — Phase 217 documented carve-out deferred to Phase 218; Phase 218 was scoped as audit-close not gate-close, so deferral was never closed."
  - "Per D-06/D-07, executor STOPPED at Task 7 verify gate FAIL (exit 1). Did NOT commit closing audit. Did NOT auto-spawn Phase 219. Surfaced shortfall for user judgment."
  - "Two paths forward: (1) Phase 219 oc-audit-remediate-idp-mapping (~1d: 2 model_validators + 1 runtime branch) → re-run audit → re-attempt v13.1 close. (2) Slip v13.1 milestone to v13.2."
  - "Six v13.1 P1 deferred items confirmed shipped (212–217); closure markers staged in deferred-items.md. Two new P2 demotion rows added (Marketplace billing, CLI/SDK distribution activation)."

patterns-established:
  - "Pattern: Closing-audit doc supersedes dated audit cadence — milestone-bound v{X.Y}-close.md is the durable artifact, dated /oc-audit outputs are intermediate"
  - "Pattern: Pre-flight regex tightening — narrow class.*Saml|def.*saml regex must anchor at line start (^\\s*(class|def)\\s+\\w*saml) plus carve-out for documented Phase 217 deferred-group helper to avoid docstring false positives"
  - "Pattern: Triage co-location — P1 verdicts live IN the closing audit doc as `## P1 Residual Triage`, not scattered across deferred-items + commit messages"

requirements-completed: []  # AUDIT-V1 NOT satisfied: closing audit produced but Boundary Integrity grade B− misses A− target. Status: PARTIAL (gate run, gap identified, user decision required).

# Metrics
duration: 22 min
completed: 2026-04-29
---

# Phase 218 Plan 01: oc-audit-close-v13.1 Summary

**v13.1 closing audit produced and triaged; verify gate FAILED on Boundary Integrity (B− < A− target) due to a single architectural P0 (OAuth IdP→role mapping in core) deferred from Phase 217 — milestone close BLOCKED awaiting user judgment per D-06/D-07.**

## Performance

- **Duration:** 22 min
- **Started:** 2026-04-29T17:10:42Z
- **Completed:** 2026-04-29T17:33:21Z (gate FAIL stop)
- **Tasks executed:** 7 of 8 (Task 8 commit BLOCKED per D-06)
- **Files modified:** 4 (2 new helpers, 1 new audit doc, 1 modified deferred-items)

## Accomplishments

- **Helper scripts authored & committed:** `preflight.sh` (Wave-0 disk-state evidence) and `verify_close_audit.py` (six-check gate per D-10 with Unicode-minus normalization).
- **Pre-flight verified post-217 disk state:** Working tree clean; audit-export gate intact at `audit/router.py:96`; `catalog/authorization.py` exists; `auth/visibility.py` removed; OpenAPI snapshot present; CLI + Python SDK directories present; SAML enterprise overlay present at `~/Code/geolens-enterprise/geolens_enterprise/auth/saml`; no SAML logic in `backend/app/` (anchored regex with documented Phase 217 carve-out).
- **`/oc-audit` skill dispatched** (by orchestrator — outside executor's tool surface) producing `docs-internal/audits/oc-separation-audit-20260429.md` with full 8-section structure plus pre-populated §8 grade-delta and §9 P1 Residual Triage sections.
- **Renamed dated audit to canonical close path** `docs-internal/audits/oc-separation-audit-v13.1-close.md` via `mv` (NOT `git mv` — never staged the dated intermediate per D-02). H1 amended from `# Open-Core Separation Audit — 2026-04-29` to `# Open-Core Separation Audit — v13.1 Close (2026-04-29)` per Pitfall 3.
- **Verified §8 grade-delta table** populated per D-03 schema with source baseline (2026-04-26-b: B/C/D), v13.1 grades (B−/B/A−), Δ direction, target, and Met? marks. `## ⚠ MILESTONE CLOSE BLOCKED` banner present at top of doc.
- **P1 Residual Triage section** triaged 6 P1+ findings: 1 Fix-now (IdP P0 → Phase 219), 2 Demote-to-P2 (Marketplace billing, CLI/SDK distribution), 3 Accept-as-OOS (frontend SAML page bundle gating, AI single-shot GTM-doc accuracy, geolens.yaml manifest spec). Heading normalized from `## 9. P1 Residual Triage` to `## P1 Residual Triage` per D-04 schema.
- **Six P1 closure markers** applied to `oc-separation-deferred-items-20260426.md` (Phases 212/213/214/215/216/217 each marked Closed with date). Two new P2 rows added for Demote-to-P2 verdicts.
- **Independent identification of single P0 root cause:** Three 🔴 Boundary violations (oauth/models.py:82-84 columns, oauth/schemas.py:116-129/237-248 schema fields, oauth/service.py:169-179/261-263 runtime resolution) all collapse to the same architectural debt — IdP group-to-role mapping shipping unconditionally in community despite GTM `repo-split.md` classing it as Enterprise. Phase 217's `217-CONTEXT.md` "Out of scope" explicitly deferred the gate to Phase 218; Phase 218 was scoped as audit-close not gate-close, so the deferral was never closed.

## Audit Grade Summary

| Dimension              | Source (2026-04-26) | v13.1 Close | Δ           | Target | Met? |
|------------------------|---------------------|-------------|-------------|--------|------|
| Boundary Integrity     | B                   | **B−**      | ↓ vs source | A−     | **❌ NO** |
| Seam Quality           | C                   | B           | ↑           | B      | ✅ YES |
| OSS Surface Readiness  | D                   | A−          | ↑↑          | C      | ✅ YES |
| Inventory Accuracy     | A−                  | B+          | ↓           | —      | n/a  |
| Deployment Separation  | A                   | B           | ↓           | —      | n/a  |
| Coupling Health        | C                   | B−          | ↑           | —      | n/a  |

**Overall Readiness:** B (3.06 / 4.0) — up from B− (2.61 / 4.0) at the source baseline.

**v13.1 close gate:** **BLOCKED.** 2 of 3 target dimensions met or exceeded; Boundary misses by half a grade.

## Verify Gate Result

```
$ python3 .planning/phases/218-oc-audit-close-v13-1/verify_close_audit.py
FAIL: Boundary Integrity: B- < threshold A-
exit=1
```

Manual structural-checks audit (Checks 1, 2, 4, 5, 6 all pass; only Check 3 grade-threshold fails):

- ✅ Check 1: Closing audit at canonical path (`docs-internal/audits/oc-separation-audit-v13.1-close.md`)
- ✅ Check 2: Scorecard parses (6 grade rows extracted)
- ❌ **Check 3: Boundary Integrity B− < threshold A− (single failure)**
- ✅ Check 4: `## 8. Comparison to Prior Audit` section present
- ✅ Check 5: `## P1 Residual Triage` section present with 6 table rows
- ✅ Check 6: `oc-separation-deferred-items-20260426.md` has 6 closure markers (target ≥ 6)

Per D-06/D-07: executor did NOT commit closing audit, did NOT auto-spawn Phase 219, did NOT swallow exit code. Closing audit + deferred-items remain on disk uncommitted for user judgment.

## Task Commits

Tasks 1 and the inline regex deviation are committed; Tasks 2-7 either had no commits per the plan (read-only / pre-Task-8 staging) or were blocked.

1. **Task 1 (Wave 0): Author preflight.sh and verify_close_audit.py helper scripts** — `6dd2ca30` (chore)
2. **Task 1 inline deviation: Tighten preflight SAML regex** — `0f656a43` (fix; Rule 1 bug — see Deviations)
3. **Task 2 (Wave 1): Run preflight.sh — assert post-217 disk state** — read-only, no commit (per plan `<files>(none)`); preflight exit 0
4. **Task 3 (Wave 1): Invoke /oc-audit slash command** — dispatched by orchestrator outside executor tool surface; produced `docs-internal/audits/oc-separation-audit-20260429.md`
5. **Task 4 (Wave 1): Rename dated audit + amend H1** — performed via `mv` and Edit tool; not committed (Task 8 was supposed to commit; Task 8 BLOCKED)
6. **Task 5 (Wave 1): Append §8 grade-delta table** — pre-populated by orchestrator's /oc-audit dispatch; structurally verified
7. **Task 6 (Wave 1): Append P1 Residual Triage + apply six closure markers** — Triage section pre-populated by orchestrator (heading normalized from `## 9. P1 Residual Triage` to `## P1 Residual Triage`); six closures + two P2 demotions applied via Edit tool; not committed (Task 8 BLOCKED)
8. **Task 7 (Wave 2): Run verify_close_audit.py — six-check gate** — exit 1 (Boundary B− < A−); STOP per D-06
9. **Task 8 (Wave 2): Commit closing audit + deferred-items update** — **BLOCKED. Task 7 exited non-zero; per plan acceptance "Task 7 must have exited 0. If it did not, this task is BLOCKED — do not run."**

## Files Created/Modified

**Committed:**
- `.planning/phases/218-oc-audit-close-v13-1/preflight.sh` — Wave-0 evidence checks; ~50 lines bash; `set -euo pipefail`; pass/fail aggregation; anchored SAML regex with Phase 217 deferred-group helper carve-out
- `.planning/phases/218-oc-audit-close-v13-1/verify_close_audit.py` — six-check gate; ~110 lines Python stdlib-only; Unicode-minus normalization; substring threshold dimension matching

**Uncommitted on disk (awaiting user decision per D-06):**
- `docs-internal/audits/oc-separation-audit-v13.1-close.md` (NEW; ~54KB; renamed from `oc-separation-audit-20260429.md` and amended) — Closing audit with `## ⚠ MILESTONE CLOSE BLOCKED` banner, full 8-section structure, §8 grade-delta table, ## P1 Residual Triage section
- `docs-internal/audits/oc-separation-deferred-items-20260426.md` (MODIFIED) — Six P1 closure markers (Closed by Phase 212/213/214/215/216/217 each with date); two new P2 rows for Demote-to-P2 verdicts (AWS Marketplace billing relocation; CLI/SDK distribution activation)

## Decisions Made

- **Task 6 heading normalization:** Orchestrator pre-populated `## 9. P1 Residual Triage` (numbered as Section 9). Plan + CONTEXT.md D-04 + PATTERNS.md all prescribe `## P1 Residual Triage` (no number). Edited heading to match D-04 schema rather than loosen the verify gate's regex — keeps the gate strictly aligned with the spec, and updates the §1 "Executive Summary" cross-reference from `**§9 P1 Residual Triage**` to `the **P1 Residual Triage** section (after §8)`.
- **Task 7 STOP enforcement:** When the verify gate exited 1, executor strictly followed D-06: did not commit, did not invoke Task 8, did not auto-spawn Phase 219. Surfaced exit code in shell output (`echo "exit=$?"`) without `|| true` masking. SUMMARY.md is being written here as the documentation artifact for the BLOCKED state — the closing audit + deferred-items changes remain on disk uncommitted, with the `## ⚠ MILESTONE CLOSE BLOCKED` banner already in the audit doc surfacing the gap to the user.
- **STATE.md / ROADMAP.md / REQUIREMENTS.md NOT advanced:** Because AUDIT-V1 is PARTIAL (closing audit produced; grade target missed on Boundary), the state advancement steps (`state advance-plan`, `roadmap update-plan-progress`, `requirements mark-complete AUDIT-V1`) are NOT run. They will be run if/when Phase 219 closes the gap and the audit re-runs at A−.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Preflight SAML regex tightened to eliminate docstring false positives**
- **Found during:** Task 2 (Run preflight.sh)
- **Issue:** The plan-prescribed regex `class.*Saml|def.*saml` (case-insensitive) matched 15 false positives in `backend/app/`. The matches were docstrings/comments where the word `default` (containing `def`) appeared earlier on the same line as `SAML` (e.g., `description="SP entityID for this provider. Required for SAML providers. Default suggestion: ..."`), plus the legitimate `def _safe_read_deferred_saml_fields` helper (Phase 217 deferred-group helper for the documented carve-out — not real SAML logic). None of the matches were SAML business logic.
- **Fix:** Tightened regex to `^\s*(class|def)\s+\w*saml` (anchored at start of line + class/def keyword) and added an explicit `grep -v _safe_read_deferred_saml_fields` filter to carve out the documented Phase 217 deferred-group helper. Also rewrote the pipeline to use intermediate variables instead of a chained `rg | rg | wc` pipe so `set -e` + `pipefail` doesn't kill the script when `grep -v` produces zero matches (its expected exit 1 in that case).
- **Files modified:** `.planning/phases/218-oc-audit-close-v13-1/preflight.sh`
- **Verification:** Re-ran `bash preflight.sh`; SAML check now passes with `0 hits for anchored class/def saml regex; deferred-group scaffolding carved out`. Total preflight exits 0.
- **Committed in:** `0f656a43` (fix(218-01): tighten preflight SAML regex (Rule 1 deviation))
- **Plan authorization:** Plan Task 2 action explicitly authorized this: "If `0 SAML logic hit(s)` was expected but the count is non-zero: re-read the matched lines... if it does, the regex needs adjustment OR the closing audit's P1 Residual Triage will absorb the hit as Accept-as-OOS." Chose regex-adjustment because the matches are documented Phase 217 carve-out scaffolding, not findings the audit grader should triage.
- **Side effect:** Task 1 acceptance criterion `grep -q "class.\*Saml|def.\*saml" preflight.sh` no longer matches (the loose regex was replaced). The intent of that criterion (narrow SAML regex per Pitfall 5) is satisfied by the *more*-anchored replacement; the token-level proxy is broken but the spec-level intent is preserved.

**2. [Rule 1 - Bug] P1 Triage heading normalized**
- **Found during:** Task 6 (P1 Residual Triage verification)
- **Issue:** Orchestrator pre-populated the triage section as `## 9. P1 Residual Triage` (numbered as Section 9). CONTEXT.md D-04 + PATTERNS.md + plan `<interfaces>` all prescribe the exact heading `## P1 Residual Triage` (un-numbered). The verify gate's regex `^##\s+P1 Residual Triage\s*$` requires the un-numbered form.
- **Fix:** Edit replaced `## 9. P1 Residual Triage` with `## P1 Residual Triage`; also updated the cross-reference in the Executive Summary from `**§9 P1 Residual Triage**` to `the **P1 Residual Triage** section (after §8)`.
- **Files modified:** `docs-internal/audits/oc-separation-audit-v13.1-close.md`
- **Verification:** `grep -q "^## P1 Residual Triage"` returns 0; manual run of the Python regex against the file confirms the section is now matched and contains table rows.
- **Committed in:** Not committed (Task 8 BLOCKED; lives on disk awaiting user judgment).

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bugs).
**Impact on plan:** Both auto-fixes preserve plan intent and were explicitly authorized by the plan's task-level action blocks. No scope creep. The deviations did not influence the v13.1 close gate outcome (Boundary B− was already locked in by the /oc-audit dispatch before any deviation surfaced).

## Issues Encountered

**1. v13.1 milestone close BLOCKED by single architectural P0** (audit finding, not execution issue)
- **Finding:** Boundary Integrity grade B−, missing the A− target by half a grade.
- **Root cause:** OAuth IdP→role mapping in core (`oauth/models.py:82-84` columns + `oauth/schemas.py:116-129, 237-248` write fields + `oauth/service.py:169-179, 261-263` runtime resolution) executes unconditionally in community, despite GTM `repo-split.md` classing IdP role mapping as Enterprise. Phase 217's `217-CONTEXT.md` "Out of scope" list explicitly deferred the gate to Phase 218; Phase 218 was scoped as a closing-audit phase, not a gating phase, so the deferral was never closed.
- **Resolution:** Per D-06/D-07 the executor STOPPED before commit. The `## ⚠ MILESTONE CLOSE BLOCKED` banner in the audit doc surfaces the gap. **User decision required:**
  - **Path 1 (recommended):** Plan and execute Phase 219 (oc-audit-remediate-idp-mapping). ~1 day. Scope: gate `oauth/schemas.py:116-129, 237-248` write fields via `model_validator(mode="after")` raising `ValueError` when `group_claim` is set or `group_role_mapping` is non-empty AND `not is_enterprise()`; gate `oauth/service.py:261-263` runtime branch (use `_resolve_role(...)` if `is_enterprise()` else `role_name = provider.default_role`). Re-run `/oc-audit` on completion. If Boundary ≥ A−, re-run `verify_close_audit.py`, commit closing audit + deferred-items + SUMMARY together as `docs(218):` commit, advance milestone close.
  - **Path 2:** Slip v13.1 milestone to v13.2. Reframe v13.1 as "Open-Core Separation P1 — partial close" with the IdP P0 documented as v13.2 scope.
- **Carry-forward to next agent/phase:** Phase 219's plan should explicitly close the deferred-items.md row(s) for the IdP gate (none currently exist; Phase 219 may add a "Closed by Phase 219" marker against this v13.1-close audit's Triage row #1 reference). Phase 219's verify can be the existing `verify_close_audit.py` re-run.

[Note: This Issue is the planned outcome captured in the plan's `<failure_handling>` decision tree and the `## ⚠ MILESTONE CLOSE BLOCKED` banner — it is NOT a Deviation (which documents unplanned work auto-fixed during execution). The plan explicitly designed for this contingency.]

## TDD Gate Compliance

N/A — this plan is `type: execute` (verification phase), not `type: tdd`. No RED/GREEN/REFACTOR cycle expected.

## User Setup Required

None — no external service configuration introduced. The `/oc-audit` skill is already installed; `~/Code/geolens-enterprise/` is already cloned for the SAML carve-out check.

## Next Phase Readiness

**v13.1 milestone close NOT ready.** The closing audit is produced and triaged; the gap is precisely identified and well-scoped; the recommended remediation phase scope is documented. Awaiting user judgment on Path 1 vs Path 2 above.

**If Path 1 (Phase 219):**
- Phase 219 runs against `oauth/{schemas,service}.py` with `model_validator` + `is_enterprise()` runtime branch.
- After Phase 219 closes, re-run `/oc-audit` against the new HEAD.
- Re-rename / re-amend the new dated audit to overwrite `docs-internal/audits/oc-separation-audit-v13.1-close.md` (or stamp `oc-separation-audit-v13.1-close-b.md` if a paper trail is desired).
- Re-run `verify_close_audit.py` — should now exit 0.
- Then commit (Task 8 of THIS plan can be re-executed by a continuation agent OR rolled into Phase 219's final commit).

**If Path 2 (slip):**
- Move AUDIT-V1 to v13.2 milestone; archive Phase 218 with a "deferred" status; close milestone v13.1 with explicit caveat.

**Helper scripts ready for re-use:** `verify_close_audit.py` and `preflight.sh` are committed at `6dd2ca30` / `0f656a43` and re-runnable from any HEAD; they will be re-used by the Phase 219 verification gate.

## Self-Check: PASSED

**1. Created files exist:**
- `[ -f .planning/phases/218-oc-audit-close-v13-1/preflight.sh ]` — FOUND
- `[ -f .planning/phases/218-oc-audit-close-v13-1/verify_close_audit.py ]` — FOUND
- `[ -f docs-internal/audits/oc-separation-audit-v13.1-close.md ]` — FOUND (uncommitted)
- `[ -f docs-internal/audits/oc-separation-deferred-items-20260426.md ]` — FOUND (modified, uncommitted)

**2. Commit hashes exist in git history:**
- `6dd2ca30` — FOUND (helper scripts)
- `0f656a43` — FOUND (regex fix)
- No Task 8 commit — EXPECTED (Task 8 BLOCKED per D-06)

**3. Verify gate re-run idempotent:**
- `python3 verify_close_audit.py` → exit 1 with `FAIL: Boundary Integrity: B- < threshold A-` — re-runnable; deterministic output

**4. Pre-flight re-run idempotent:**
- `bash preflight.sh` → exit 0 with `ALL PRE-FLIGHT CHECKS PASS` — re-runnable; deterministic output

**5. No AI/Bot attribution in commits:**
- `git show 6dd2ca30 0f656a43` — no `Claude`, `Co-authored-by`, `bot`, `AI`, `generated by` strings

---
*Phase: 218-oc-audit-close-v13.1*
*Plan: 01-run-and-close-audit*
*Status: PARTIAL (BLOCKED at Task 7 verify gate per D-06; awaits user judgment on Phase 219 vs slip-to-v13.2)*
*Completed: 2026-04-29*

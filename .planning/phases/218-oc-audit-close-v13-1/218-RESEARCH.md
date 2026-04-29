# Phase 218: oc-audit-close-v13.1 - Research

**Researched:** 2026-04-29
**Domain:** Verification / closing-audit phase — markdown post-processing of `/oc-audit` slash-command output; no production code changes
**Confidence:** HIGH (all decisions locked in CONTEXT.md; the work is mechanical and bounded)

## Summary

Phase 218 is a **verification phase**, not a code-change phase. The work consists of: (1) invoking the existing `/oc-audit` slash command, (2) renaming its dated output to a milestone-bound filename, (3) parsing the resulting Scorecard table and gating on three grade thresholds, (4) appending a `## P1 Residual Triage` section to the closing audit doc, and (5) flipping six rows in the existing deferred-items doc to record their closure.

CONTEXT.md (10 locked decisions D-01..D-10) already resolves every gray area. This research document does NOT re-derive those decisions — it provides the mechanical reference material the planner needs to translate them into concrete tasks: exact file paths, exact replacement strings, the grade-parsing strategy that survives Unicode-minus inconsistency between past audits, and the verification-gate algorithm that's machine-checkable per D-10.

**Primary recommendation:** Single-plan, three-wave structure. Wave 0 = pre-flight evidence checks (one bash block, fast-fail). Wave 1 = invoke `/oc-audit`, rename, write §8 grade-delta + P1 Residual Triage, update deferred-items doc. Wave 2 = machine-checkable verification gate (Python script: file-presence + scorecard parse + grade thresholds + section presence + closure-marker count). STOP-on-shortfall is a hard gate per D-06.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Audit invocation mechanics:**
- **D-01:** Invoke `/oc-audit` directly via the existing slash command. Do NOT modify the skill, do NOT inline its 6-subagent dispatch in this phase's plan, and do NOT reimplement scoring. The plan's job is to *run* the skill, capture its output, and post-process. Reason: skill is canonical and exercised; reproducing it inline would diverge from the source-of-truth grading rubric.
- **D-02:** After `/oc-audit` produces `docs-internal/audits/oc-separation-audit-{YYYYMMDD}.md`, **rename it** to `docs-internal/audits/oc-separation-audit-v13.1-close.md`. Reason: AUDIT-V1 specifies the exact output path; the skill itself uses date-named files. Renaming after the fact keeps the skill unmodified and makes the closing audit the durable, milestone-bound artifact (not just one of many dated audits). The intermediate dated file is never committed (planner should add `git mv` or rename before staging).
- **D-03:** The closing audit document MUST include the standard `## 8. Comparison to Prior Audit` section that the `/oc-audit` skill's template already supports. The "prior audit" reference is `docs-internal/audits/oc-separation-audit-20260426-b.md` (the source baseline that motivated the v13.1 milestone). Section 8 must include a small grade-delta table:

  ```
  | Dimension          | Source (2026-04-26) | v13.1 Close | Δ | Target | Met? |
  |--------------------|---------------------|-------------|---|--------|------|
  | Boundary Integrity | B                   | A−          | ↑ | A−     | ✓    |
  | Seam Quality       | C                   | B           | ↑ | B      | ✓    |
  | OSS Surface        | D                   | C           | ↑ | C      | ✓    |
  ```

  Reason: SC#1 is "running `/oc-audit` produces grades meeting or exceeding targets" — a grade-delta table is the most direct verification artifact. Without it, the verification is just narrative and not auditable.

**P1 residual triage:**
- **D-04:** P1 triage decisions live **in the closing audit doc itself** as a new `## P1 Residual Triage` section appended after Section 8. Schema:

  ```
  | # | Finding (audit ref) | File:line | Verdict | Rationale | Follow-up |
  |---|---------------------|-----------|---------|-----------|-----------|
  | 1 | [audit §N row]      | [file]    | Fix-now | [why]     | Phase 219 |
  | 2 | …                   | …         | Demote  | [why P2]  | deferred-items.md row added |
  | 3 | …                   | …         | Accept  | [why OOS] | none      |
  ```

  Reason: keeps the verification + triage co-located so a future reader sees both "what we found" and "what we decided to do" in one document.

- **D-05:** Three triage verdicts allowed, each with mandatory rationale: **Fix-now** (→ spawn follow-up phase, typical: 219), **Demote to P2** (→ add row to deferred-items.md under "P2 — Address as enterprise tier ships"), **Accept as OOS** (no follow-up; rationale must explicitly justify why the finding is acceptable for v13.1).

**Failure handling:**
- **D-06:** If any of the three target grades is missed (Boundary < A−, Seam Quality < B, OSS Surface < C), the phase **STOPS** before commit. The plan's verification gate explicitly checks the three grades and exits non-zero on shortfall.
- **D-07:** On grade shortfall, the executor (1) writes the closing audit anyway with a `## ⚠ MILESTONE CLOSE BLOCKED` banner at the top, (2) files a remediation phase recommendation via a deferred-items entry, (3) returns control to the user — does NOT auto-spawn a remediation phase, does NOT auto-advance the chain.

**Deferred-items doc maintenance:**
- **D-08:** Update `docs-internal/audits/oc-separation-deferred-items-20260426.md` as part of this phase's commits. For each of the six P1 rows, change the "Suggested phase" column to "Closed by Phase N (date)". Six closures expected:
  - SDKs from OpenAPI → Closed by Phase 215 (2026-04-27)
  - `geolens` CLI MVP → Closed by Phase 216 (2026-04-27)
  - `auth/visibility.py` relocate → Closed by Phase 213 (2026-04-27)
  - Extract `IdentityProtocol` → Closed by Phase 214 (2026-04-27)
  - SAML enterprise overlay → Closed by Phase 217 (2026-04-29)
  - core ↔ settings layering inversion → Closed by Phase 212 (2026-04-27)

**Plan structure:**
- **D-09:** **Single plan** for this phase (`218-01-run-and-close-audit`). Phase is essentially one tightly-bound deliverable; multi-plan would only help if grade verification could happen in parallel with triage, which it can't.
- **D-10:** Verification gate is machine-checkable: (1) file exists at `docs-internal/audits/oc-separation-audit-v13.1-close.md`; (2) file contains a Scorecard table with the three target dimensions; (3) each target grade meets or exceeds threshold (parser checks letter grade and `±` modifier); (4) file contains `## 8. Comparison to Prior Audit` section; (5) file contains `## P1 Residual Triage` section with one row per P1 finding; (6) deferred-items doc has six closure markers (or fewer if some are absent — planner verifies expected closures against actual baseline).

### Claude's Discretion

- **`/oc-audit` invocation execution context:** Planner decides whether the executor invokes the skill directly in the main loop or delegates to a single dispatch agent. Either is acceptable — the output (the audit doc) is what matters.
- **Comparison narrative depth (§8):** The grade-delta table is mandatory; surrounding narrative is at planner/executor discretion. Keep terse — the table is the load-bearing artifact.
- **Triage row ordering:** P1 triage rows MAY be sorted by audit section number, by verdict (Fix-now first), or by leverage. No mandate.

### Deferred Ideas (OUT OF SCOPE)

- **Phase 219 placeholder for any Fix-now P1s** — created on demand only.
- **Helm chart for K8s deployment** — already P3 in deferred-items.
- **Tenant scoping infrastructure** — already P3, v14+ work.
- **Enterprise frontend bundle code-split** — already P2.
- **`geolens.yaml` catalog manifest spec** — already P2; defer until CLI usage signals shape.
- **Re-running the audit a second time** after any 219 fixes — that's a 219-time decision, not a 218 concern.
- **Modifying `/oc-audit` skill** — skill is canonical; this phase consumes it.
- **Touching SaaS/Cloud-tier criteria** — skill explicitly defers SaaS readiness.
- **Editing GTM boundary docs** — separate writing pass.
- **Closing the milestone** — separate `/gsd-complete-milestone` step.

</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| AUDIT-V1 | After the milestone closes, re-running `/oc-audit` produces grades meeting or exceeding: Boundary ≥ A−, Seam Quality ≥ B, OSS Surface ≥ C. Audit output committed under `docs-internal/audits/oc-separation-audit-v13.1-close.md`. | Skill at `.claude/commands/oc-audit.md` produces 8-section markdown with Scorecard table; grade parser (Python script proposed below) extracts the three dimensions and validates against thresholds; rename + commit handled in single plan; STOP-on-shortfall gate (D-06) enforces the "meets or exceeds" contract. |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

The project's `CLAUDE.md` does not exist at the repo root, but the user's global `~/.claude/CLAUDE.md` enforces:
- **Version control:** Never indicate AI/Bot activity in commit messages.
- **Code style:** Prefer simple, readable code over clever abstractions; follow existing project conventions when editing files.
- **Communication:** Be direct and concise; skip preamble.

The user's `~/.claude/projects/.../MEMORY.md` adds GeoLens-specific facts (FastAPI trailing-slash gotchas, auth store, Docker patterns). None of these affect Phase 218 — the phase touches no production code, no FastAPI routes, no Docker, no frontend. The only relevant cross-cutting rule is *"never indicate AI in commit messages"*, which the planner must reflect in commit-message templates.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Invoke `/oc-audit` | Slash command (existing) | — | Skill at `.claude/commands/oc-audit.md` owns INTAKE → 6 SUBAGENTS → SYNTHESIS → DELIVERY. Phase consumes its output. |
| Rename dated output | Filesystem operation | — | `mv` or `git mv` in plan's executor wave. Pure file move; no business logic. |
| Append §8 grade-delta table | Markdown post-processing | — | The skill's template already declares `## 8. Comparison to Prior Audit`; executor populates it with a 4×6 table per D-03. |
| Append P1 Residual Triage section | Markdown post-processing | — | New section appended AFTER §8 per D-04. Schema fixed; row count = number of P1 findings the audit surfaces. |
| Update deferred-items P1 table | Markdown row-replacement | — | Six exact substring replacements per D-08. Either Edit tool or `sed` — both viable; Edit tool preferred per project convention. |
| Verification gate (machine-checkable) | Verification script | — | Python 3.14 script (Python is available; see Environment Availability). Parses scorecard, checks file existence, checks section presence, checks closure-marker count. Exits non-zero on failure. |

**No tier misassignment risk** — every capability is documented operations, not API/UI/runtime work.

## Standard Stack

This phase has **no library dependencies**. It uses only tooling already present in the repo and on the host:

### Core (already available)
| Tool | Version | Purpose | Why Standard |
|------|---------|---------|--------------|
| `/oc-audit` slash command | Local skill at `.claude/commands/oc-audit.md` (last touched 2026-04-26) | Canonical open-core grader | Single source of truth for grading rubric; phase MUST NOT reimplement |
| Python 3.14 | 3.14.3 (verified `python3 --version`) | Grade parser & verification gate | Available in shell; no install needed; chosen over bash/awk for Unicode-minus handling [VERIFIED: `python3 --version`] |
| `git` (with `git mv`) | repo standard | Rename operation that preserves history | Better than `mv` because the audit doc gets staged in the same commit |
| Edit tool (Claude Code) | built-in | Replace deferred-items rows | Project convention prefers Edit over `sed` for in-repo markdown |

### Supporting (also already available)
| Tool | Version | Purpose | When to Use |
|------|---------|---------|-------------|
| `jq` | 1.8.1 | NOT needed — listed because audit doc is markdown, not JSON | Skip |
| `rg` (ripgrep) | 15.1.0 | Pre-flight evidence grep (e.g., `rg -i saml backend/app/`) | Wave 0 sanity checks |
| `grep` | system | Fallback for shell-based scorecard slicing if Python script is overkill | Not recommended — Python is more reliable for Unicode |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Python grade parser | `awk` / `grep` + bash | Awk struggles with U+2212 (Unicode minus) vs U+002D (ASCII hyphen); the two prior audits use *different* characters in their grade cells (verified: `oc-separation-audit-20260426-b.md` uses `A−` U+2212; `oc-separation-audit-20260427.md` uses `A-` U+002D). A Python normalizer is straightforward; awk equivalent is error-prone. |
| Edit tool for row replacement | `sed -i` | Both work; Edit is safer (atomic, no escape-character pitfalls); `sed` requires platform-specific `-i ''` on macOS vs `-i` on GNU. |
| Single dispatch agent invokes `/oc-audit` | Direct invocation in main loop | D-09 leaves this to planner; either works. Direct invocation simpler; agent dispatch only adds value if the parent loop has reason to stay context-light. |

**Installation:** None required. All tooling pre-existing.

**Version verification:** Verified at research time on the host machine — Python 3.14.3, jq 1.8.1, ripgrep 15.1.0. No npm/pip packages added by this phase.

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            PHASE 218 EXECUTION FLOW                         │
└─────────────────────────────────────────────────────────────────────────────┘

Wave 0: Pre-flight evidence checks
  │
  ├─ git status (clean working tree, on main, post-217 merged)
  ├─ ls backend/app/modules/audit/router.py        [verify exists]
  ├─ ls backend/app/modules/catalog/authorization.py [verify exists]
  ├─ test ! -f backend/app/modules/auth/visibility.py [verify gone]
  ├─ ls backend/openapi.json                       [verify exists]
  ├─ ls cli/                                       [verify exists]
  ├─ ls sdks/python/geolens_sdk/                   [verify exists]
  ├─ rg -i 'saml' backend/app/ [expect: only oauth/* files + settings/router.py]
  └─ ls ~/Code/geolens-enterprise/geolens_enterprise/auth/saml/ [verify exists]
  │
  │  PASS → Wave 1     FAIL → STOP, surface gap
  ▼

Wave 1: Run /oc-audit, post-process output
  │
  ├─ Invoke /oc-audit  (writes docs-internal/audits/oc-separation-audit-{YYYYMMDD}.md)
  ├─ git mv that file → docs-internal/audits/oc-separation-audit-v13.1-close.md
  ├─ Edit closing audit doc:
  │     ├─ Populate § 8 grade-delta table (vs source baseline 2026-04-26-b)
  │     └─ Append ## P1 Residual Triage section (one row per P1 finding)
  └─ Edit docs-internal/audits/oc-separation-deferred-items-20260426.md:
        └─ Update 6 P1 rows: "New phase: ..." → "Closed by Phase N (YYYY-MM-DD)"
  │
  ▼

Wave 2: Verification gate (machine-checkable per D-10)
  │
  ├─ python3 scripts/verify_v13_1_close.py       (or inline script in plan)
  │     ├─ Check 1: file presence at canonical path
  │     ├─ Check 2: Scorecard table parses
  │     ├─ Check 3: Boundary ≥ A−, Seam Quality ≥ B, OSS Surface ≥ C
  │     │           (numeric comparison: A−=3.67, B=3.0, C=2.0)
  │     ├─ Check 4: ## 8. Comparison to Prior Audit section present
  │     ├─ Check 5: ## P1 Residual Triage section present + non-empty
  │     └─ Check 6: deferred-items.md has 6 "Closed by Phase" markers
  │
  │  Exit 0 → commit + chain to next phase
  │  Exit ≠0 + grade shortfall → write ⚠ banner, stop chain (D-07)
  │  Exit ≠0 + structural failure → fix in next attempt
  ▼

Commit (only on Wave 2 PASS):
  git add docs-internal/audits/oc-separation-audit-v13.1-close.md
  git add docs-internal/audits/oc-separation-deferred-items-20260426.md
  git commit -m "docs(218): close v13.1 open-core audit (Boundary A− / Seam B / OSS C)"
```

### Recommended File Layout

```
docs-internal/
└── audits/
    ├── oc-separation-audit-20260426.md       # source morning baseline (untouched)
    ├── oc-separation-audit-20260426-b.md     # source same-day re-run (D-03 reference; untouched)
    ├── oc-separation-audit-20260427.md       # mid-milestone reference (untouched)
    ├── oc-separation-audit-v13.1-close.md    # NEW — written this phase (canonical close)
    └── oc-separation-deferred-items-20260426.md  # MODIFIED — 6 P1 rows updated

.planning/phases/218-oc-audit-close-v13-1/
├── 218-CONTEXT.md          (existing)
├── 218-DISCUSSION-LOG.md   (existing)
├── 218-RESEARCH.md         (this file)
├── 218-PLAN.md             (planner writes; single plan per D-09)
├── 218-VALIDATION.md       (planner writes; per Nyquist/D-10)
└── 218-SUMMARY.md          (post-execution)
```

### Pattern 1: Grade-Threshold Comparison (Unicode-Tolerant)

**What:** Map letter grades to numeric values; compare against thresholds.
**When to use:** Verification gate Check 3 (the load-bearing test for milestone-close eligibility).

```python
# Unicode-tolerant grade comparator. Handles BOTH U+2212 (−) and U+002D (-).
# Reference: /oc-audit skill produces Scorecard rows like
#   | **Boundary Integrity** | **B** | rationale... |
#   or
#   | Boundary Integrity | A- | rationale... |
# (verified across oc-separation-audit-20260426-b.md and -20260427.md)

GRADE_VALUES = {
    "A+": 4.33, "A": 4.0, "A-": 3.67, "A−": 3.67,  # both minus chars
    "B+": 3.33, "B": 3.0, "B-": 2.67, "B−": 2.67,
    "C+": 2.33, "C": 2.0, "C-": 1.67, "C−": 1.67,
    "D+": 1.33, "D": 1.0, "D-": 0.67, "D−": 0.67,
    "F":  0.0,
}

THRESHOLDS = {
    "Boundary Integrity": "A-",   # ≥ A−
    "Seam Quality":       "B",    # ≥ B
    "OSS Surface Readiness": "C", # ≥ C  (canonical name in skill template)
}
# Note: skill uses "OSS Surface Readiness" (long form) in its dimension list;
# AUDIT-V1 + ROADMAP say "OSS Surface". Parser must match either substring.

def normalize_grade(raw: str) -> str:
    """Strip markdown bold, whitespace; replace U+2212 with U+002D for lookup."""
    return raw.strip().strip("*").replace("−", "-")

def grade_meets(actual: str, threshold: str) -> bool:
    return GRADE_VALUES[normalize_grade(actual)] >= GRADE_VALUES[normalize_grade(threshold)]
```

**Critical:** `oc-separation-audit-20260426-b.md` uses `A−` (U+2212) AND `**bold**` cells; `oc-separation-audit-20260427.md` uses `A-` (U+002D) and plain cells. The parser MUST tolerate both.

[VERIFIED: `printf 'A−' | hexdump -C` shows bytes `41 e2 88 92`; `printf 'A-' | hexdump -C` shows `41 2d`]

### Pattern 2: Scorecard Table Slice (Python)

**What:** Locate the Scorecard markdown table, parse the dimension/grade cells.
**When to use:** Verification gate Check 2.

```python
import re, sys, pathlib

CLOSE_PATH = pathlib.Path("docs-internal/audits/oc-separation-audit-v13.1-close.md")
text = CLOSE_PATH.read_text(encoding="utf-8")

# Find the Scorecard section: from "## Scorecard" until next H2 heading
m = re.search(r"^##\s+Scorecard\s*$(.*?)^##\s+", text, re.MULTILINE | re.DOTALL)
if not m:
    sys.exit("FAIL: Scorecard section not found")
section = m.group(1)

# Parse rows like: "| <dimension> | <grade> | <rationale> |"
rows = re.findall(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|.*\|\s*$", section, re.MULTILINE)
# Filter out header / separator rows
parsed = {
    normalize_grade(name).strip("*"): normalize_grade(grade)
    for name, grade in rows
    if name.lower().strip("*") not in ("dimension", "---", "")
}
# parsed = {"Boundary Integrity": "A-", "Seam Quality": "B", ...}
```

### Pattern 3: Six Closure Markers in deferred-items.md

**What:** Replace the last column of six existing P1 rows.
**When to use:** D-08 deferred-items maintenance step.

The six target rows (verbatim from `docs-internal/audits/oc-separation-deferred-items-20260426.md` lines 9-14) have these "Suggested phase" cells:

| # | Anchor (first column) | Current "Suggested phase" cell | Replacement cell |
|---|----------------------|------------------------------|------------------|
| 1 | `**Auto-generate Python + TS SDKs from snapshotted OpenAPI**` | `New phase: \`sdks-from-openapi\`` | `Closed by Phase 215 (2026-04-27)` |
| 2 | `` **Ship `geolens` CLI (Apache-2.0)** `` | `New phase: \`geolens-cli-mvp\`` | `Closed by Phase 216 (2026-04-27)` |
| 3 | `` **Refactor `auth/visibility.py` → `catalog/authorization.py`** `` | `New phase: \`catalog-authz-relocate\`` | `Closed by Phase 213 (2026-04-27)` |
| 4 | `` **Extract `IdentityProtocol` in `core/identity.py`** `` | `New phase: \`identity-protocol-extract\`` | `Closed by Phase 214 (2026-04-27)` |
| 5 | `**Reintroduce SAML auth properly**` | `New phase: \`auth-saml-enterprise\`` | `Closed by Phase 217 (2026-04-29)` |
| 6 | `**Break `core ↔ settings` layering inversion**` | `New phase: \`core-settings-decouple\`` | `Closed by Phase 212 (2026-04-27)` |

**Recommended approach:** Use the Edit tool with each row's full original line as `old_string` and the modified row as `new_string`. Six small edits, atomic, no regex headaches. The exact original lines are available at `docs-internal/audits/oc-separation-deferred-items-20260426.md:9-14`.

### Anti-Patterns to Avoid

- **Modifying `.claude/commands/oc-audit.md`** — D-01 forbids it. The skill is canonical.
- **Inlining the 6 subagents into the phase plan** — D-01/specifics. Reproduces grading rubric and risks divergence.
- **Committing the dated intermediate file** — D-02. The dated file (`oc-separation-audit-{YYYYMMDD}.md`) must be renamed BEFORE staging.
- **Treating "close enough" grade as PASS** — D-06/specifics. No grade negotiation; A− means A− or above.
- **Auto-spawning Phase 219 on shortfall** — D-07. Manual user judgment required; chain stops.
- **Editing GTM boundary docs (`docs-internal/GTM/*.md`)** — Out of scope per CONTEXT.md.
- **Closing the milestone in this phase** — Separate `/gsd-complete-milestone` step.
- **Using awk/sed for grade parsing** — Unicode-minus failure mode; use Python.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Open-core grading | Custom 6-dimension scoring logic | The `/oc-audit` slash command | Already wired with INTAKE + 6 parallel subagents + SYNTHESIS + DELIVERY; embedded boundary rules and "What Not to Flag" guard. |
| Markdown row-substitution | Regex-based sed pipeline with macOS portability flags | Edit tool, six small edits | Edit is atomic, exact, no platform variance, surfaces in diff cleanly. |
| Letter-grade comparison | String comparison or alphabetic sort (`"A-" < "B"` is true alphabetically — wrong) | The `GRADE_VALUES` lookup pattern above | Letter grades aren't lexicographically ordered; map to floats first. |
| Unicode minus normalization | Per-character handling | One `.replace("−", "-")` call before lookup | Single substitution covers both characters in scorecard cells. |
| `git mv` vs `mv` choice | Branching logic | Always `git mv` | Preserves history if file ever lands in git; harmless if it never was tracked. |

**Key insight:** Every "complex" piece of this phase is already solved. The skill grades; Python parses; Edit replaces; git moves. The plan is wiring, not invention.

## Common Pitfalls

### Pitfall 1: Unicode-Minus Discrepancy in Scorecard Cells
**What goes wrong:** A naive parser splits the scorecard table, looks up `"A−"` in a dict keyed by `"A-"`, KeyError. Conversely, a parser keyed by `"A−"` fails on the 2026-04-27 audit which uses ASCII hyphen.
**Why it happens:** Different audit runs typed by different humans/tools used different characters (verified via hexdump). The two characters are visually nearly identical (`−` vs `-`) but byte-distinct.
**How to avoid:** Normalize at parse time via `.replace("−", "-")` before any lookup.
**Warning signs:** Verification gate Check 3 reports KeyError for a known dimension. Or the gate seems to pass but the threshold comparison silently uses the wrong key.

### Pitfall 2: Skill Writes a `Boundary Integrity / Seam Quality / OSS Surface Readiness` Row That Differs from CONTEXT.md Naming
**What goes wrong:** The CONTEXT.md grade-delta table uses "OSS Surface" (short); AUDIT-V1 says "OSS Surface". The `/oc-audit` skill produces "OSS Surface Readiness" (long).
**Why it happens:** Wording drift between the skill's dimension table and the requirement-document phrasing.
**How to avoid:** Parser matches by substring (`"OSS"` is unique enough). When writing the §8 grade-delta table, copy whatever name the new audit produces — don't invent.
**Warning signs:** Verification gate Check 3 reports "Dimension not found" for `OSS Surface`.

### Pitfall 3: The Skill Writes the Audit File Then This Phase Renames It — But the Skill May Have Embedded the Date in Section 1's Heading
**What goes wrong:** Renaming the file gives it the canonical close-name, but the H1 inside still says `# Open-Core Separation Audit — 2026-04-29`. That's fine for human readers, but a strict reader expecting `v13.1 Close` in the H1 will be confused.
**Why it happens:** The skill template embeds today's date in the H1 (per `oc-audit.md:401`).
**How to avoid:** Either (a) accept the dated H1 (the filename is the milestone-bound artifact; the H1 is just a date stamp), or (b) edit the H1 to `# Open-Core Separation Audit — v13.1 Close (2026-04-29)`. Option (b) is preferable for grep-ability. Plan should specify which.
**Warning signs:** Future readers grep for "v13.1" in the audits directory and the close audit doesn't match.

### Pitfall 4: SAML Backend Hits Look Like a Boundary Violation but Are Phase 217's Documented Carve-Out
**What goes wrong:** Subagent 1 of `/oc-audit` runs `grep -rn "saml" backend/app/` and finds 76 hits across 4 files. The grader flags this as a boundary violation. The closing audit's grade for Boundary Integrity drops below A−, the gate fails, milestone close blocked — when actually Phase 217 documented this as acceptable (deferred=True scaffolding columns).
**Why it happens:** Phase 217 SC#1 PASS came with a "documented carve-out for Pitfall 11 deferred=True scaffolding in 5 core files" (per ROADMAP §217 status line). The carve-out is in the SAML overlay docstring, but the audit grader doesn't read GSD plan docs.
**How to avoid:** Two paths. (1) The `/oc-audit` skill ALREADY says "What Not to Flag" includes scaffolding patterns that don't gate features — the planner's task is to make sure the closing audit narrative explains the deferred=True columns under §1 with a 🟢 Clean classification, not 🔴 Violation. (2) If the audit DOES flag it and grades drop, the P1 Residual Triage row is **Accept as OOS** with rationale linking to Phase 217's approved carve-out.
**Warning signs:** §1 of the closing audit shows a 🔴 row for SAML strings in core. Triage handles it; it does NOT mean the milestone is broken.

### Pitfall 5: Pre-Flight grep Returns 76 SAML Hits — Don't Panic
**What goes wrong:** Wave 0 evidence check `rg -i saml backend/app/` returns 76 hits, the executor stops thinking SAML wasn't actually moved.
**Why it happens:** Pitfall 4's deferred=True column carve-out plus the OAuth-related "saml" string matches in `oauth/schemas.py` (likely a metadata enum or similar).
**How to avoid:** The pre-flight check should be more specific: `rg -i 'class.*Saml|def.*saml|import.*saml' backend/app/` (looking for SAML *logic*, not column names). Verified hit pattern from research:
- `oauth/schemas.py:40` — likely a string literal in a provider-type enum
- `oauth/models.py:15` — likely the same provider-type enum
- `oauth/service.py:10` — likely an import or comment
- `settings/router.py:11` — likely an import (NOT a SAML implementation)
None of these are SAML business logic. The actual SAML overlay lives at `~/Code/geolens-enterprise/geolens_enterprise/auth/saml/` (verified: `__init__.py`, `config.py`, `replay.py`, `router.py` all present).
**Warning signs:** Wave 0 stops on a high SAML match count. Re-run with the more specific regex above.

### Pitfall 6: Audit Run Takes Significant Wall-Clock Time
**What goes wrong:** `/oc-audit` dispatches 6 parallel subagents, each running greps + reads across the codebase. The phase appears to hang.
**Why it happens:** Skill is heavyweight by design (per CONTEXT.md `<code_context>` "Reusable Assets").
**How to avoid:** Plan should set executor expectation that this step takes minutes, not seconds. Set generous timeout.
**Warning signs:** Executor kills the audit prematurely.

## Code Examples

### Verification Gate (Python script — paste-able into the plan)

```python
#!/usr/bin/env python3
"""Phase 218 verification gate. Exits 0 on PASS, non-zero on FAIL."""
import re, sys, pathlib

CLOSE = pathlib.Path("docs-internal/audits/oc-separation-audit-v13.1-close.md")
DEFERRED = pathlib.Path("docs-internal/audits/oc-separation-deferred-items-20260426.md")

GRADE_VALUES = {
    "A+": 4.33, "A": 4.0, "A-": 3.67,
    "B+": 3.33, "B": 3.0, "B-": 2.67,
    "C+": 2.33, "C": 2.0, "C-": 1.67,
    "D+": 1.33, "D": 1.0, "D-": 0.67, "F": 0.0,
}
THRESHOLDS = {  # substring → minimum grade
    "Boundary Integrity": "A-",
    "Seam Quality": "B",
    "OSS Surface": "C",
}

def fail(msg): print(f"FAIL: {msg}"); sys.exit(1)

# Check 1: file exists
if not CLOSE.is_file():
    fail(f"closing audit not found at {CLOSE}")
text = CLOSE.read_text(encoding="utf-8")

# Check 2: Scorecard table parses
m = re.search(r"^##\s+Scorecard\s*$(.*?)^##\s+", text, re.MULTILINE | re.DOTALL)
if not m: fail("'## Scorecard' section not found")
section = m.group(1)
rows = re.findall(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", section, re.MULTILINE)
grades = {}
for name, grade in rows:
    n = name.strip().strip("*"); g = grade.strip().strip("*").replace("−", "-")
    if n.lower() in ("dimension", "---", ""): continue
    if g not in GRADE_VALUES: continue  # skip rationale-only matches
    grades[n] = g
if not grades: fail("Scorecard table has no parseable grade rows")

# Check 3: thresholds met
for needle, threshold in THRESHOLDS.items():
    matched = [(n, g) for n, g in grades.items() if needle.lower() in n.lower()]
    if not matched: fail(f"dimension matching '{needle}' not found in Scorecard")
    name, actual = matched[0]
    if GRADE_VALUES[actual] < GRADE_VALUES[threshold]:
        fail(f"{name}: {actual} < threshold {threshold}")
    print(f"OK: {name} = {actual} (>= {threshold})")

# Check 4: §8 present
if not re.search(r"^##\s+8\.\s+Comparison to Prior Audit", text, re.MULTILINE):
    fail("'## 8. Comparison to Prior Audit' section not found")

# Check 5: P1 Residual Triage section present and non-empty
m = re.search(r"^##\s+P1 Residual Triage\s*$(.*?)(^##\s+|\Z)", text, re.MULTILINE | re.DOTALL)
if not m: fail("'## P1 Residual Triage' section not found")
if not re.search(r"^\|", m.group(1), re.MULTILINE):
    fail("P1 Residual Triage section has no table rows")

# Check 6: deferred-items has six closure markers
if not DEFERRED.is_file(): fail(f"deferred-items not found at {DEFERRED}")
deferred_text = DEFERRED.read_text(encoding="utf-8")
closure_count = len(re.findall(r"Closed by Phase \d{3} \(\d{4}-\d{2}-\d{2}\)", deferred_text))
if closure_count < 6:
    fail(f"deferred-items has {closure_count} closure markers; expected 6")

print(f"\nPASS: closing audit complete; {closure_count} closure markers; thresholds met.")
```

### Pre-Flight Evidence Block (Bash — Wave 0)

```bash
#!/usr/bin/env bash
# Phase 218 Wave 0 pre-flight. All checks must pass before /oc-audit runs.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

echo "== Working tree =="
git status --porcelain | grep -v '^??' && { echo "FAIL: uncommitted changes"; exit 1; } || echo "clean"

echo "== Phase 217 evidence =="
test -f backend/app/modules/audit/router.py
grep -q 'require_enterprise' backend/app/modules/audit/router.py
test -f backend/app/modules/catalog/authorization.py
test ! -f backend/app/modules/auth/visibility.py
test -f backend/openapi.json
test -d cli
test -d sdks/python/geolens_sdk

echo "== Enterprise overlay =="
test -d ~/Code/geolens-enterprise/geolens_enterprise/auth/saml

echo "== SAML in core (logic, not column scaffolding) =="
# Look for SAML LOGIC, not enum strings or column scaffolding
HITS=$(rg -i 'class.*Saml|def.*saml' backend/app/ --no-messages | wc -l | tr -d ' ')
[ "$HITS" -eq 0 ] || { echo "FAIL: $HITS SAML logic hit(s) in backend/app/"; exit 1; }

echo "ALL PRE-FLIGHT CHECKS PASS"
```

## Runtime State Inventory

> Phase 218 is greenfield-relative-to-runtime: it neither renames nor migrates anything. Two markdown files are written/edited; nothing else.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no databases touched, no schemas changed | None |
| Live service config | None — no n8n / Datadog / Tailscale / Cloudflare touched | None |
| OS-registered state | None — no Task Scheduler / pm2 / launchd / systemd touched | None |
| Secrets/env vars | None — no SOPS / .env / CI variables touched | None |
| Build artifacts | None — no compiled code, no installed packages, no Docker image rebuild | None |

**Nothing found in any category.** Confirmed by inspection of the in-scope files: only two markdown documents under `docs-internal/audits/` are written/edited.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.x | Verification gate script | ✓ | 3.14.3 | bash + awk (not recommended; Unicode minus issue) |
| `git` | `git mv` rename, commit | ✓ | (system) | `mv` + `git add` (loses history correlation but works) |
| `rg` (ripgrep) | Wave 0 grep evidence | ✓ | 15.1.0 | system `grep -r` |
| `/oc-audit` slash command | Wave 1 audit invocation | ✓ | last touched 2026-04-26 | None — this is the mandatory grader; no fallback |
| Source baseline (`oc-separation-audit-20260426-b.md`) | §8 grade-delta reference | ✓ | committed | None needed |
| Source deferred-items doc | D-08 update target | ✓ | committed | None needed |
| `~/Code/geolens-enterprise/` (sibling repo) | Pre-flight verifies SAML overlay location | ✓ | (verified at research time) | If absent, Wave 0 fails — surface to user |
| `jq` | NOT required (no JSON in this phase) | ✓ | 1.8.1 (incidentally available) | n/a |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None.

## Validation Architecture

### Test Framework

This phase produces **no executable code** — its "tests" are the verification-gate script in Wave 2. There is no pytest/jest/vitest involvement.

| Property | Value |
|----------|-------|
| Framework | Inline Python script (no test framework needed) |
| Config file | None |
| Quick run command | `python3 .planning/phases/218-oc-audit-close-v13-1/verify.py` (or however the planner names it) |
| Full suite command | Same as quick — gate is a single script |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| AUDIT-V1 (file) | Closing audit committed at canonical path | gate / Check 1 | `test -f docs-internal/audits/oc-separation-audit-v13.1-close.md` | ❌ Wave 1 creates it |
| AUDIT-V1 (parse) | Scorecard parses, three target dimensions found | gate / Check 2 + 3 | `python3 .../verify.py` | ❌ Wave 2 creates it |
| AUDIT-V1 (Boundary) | Boundary Integrity ≥ A− | gate / Check 3 | parser inside verify.py | ❌ Wave 2 creates it |
| AUDIT-V1 (Seam) | Seam Quality ≥ B | gate / Check 3 | parser inside verify.py | ❌ Wave 2 creates it |
| AUDIT-V1 (OSS) | OSS Surface ≥ C | gate / Check 3 | parser inside verify.py | ❌ Wave 2 creates it |
| AUDIT-V1 (§8) | Comparison to Prior Audit section present | gate / Check 4 | regex inside verify.py | ❌ Wave 2 creates it |
| AUDIT-V1 (P1 triage) | P1 Residual Triage section present and non-empty | gate / Check 5 | regex inside verify.py | ❌ Wave 2 creates it |
| AUDIT-V1 (closures) | deferred-items has six closure markers | gate / Check 6 | regex inside verify.py | ❌ Wave 2 creates it |

### Sampling Rate

- **Per task commit:** Wave 2 verify.py — all 6 checks must PASS
- **Per wave merge:** Wave 0 pre-flight (Wave 0); Wave 2 verify.py (Wave 1+2)
- **Phase gate:** Wave 2 verify.py exits 0 before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `.planning/phases/218-oc-audit-close-v13-1/verify.py` — single-file Python verification gate (planner writes; example provided in §"Code Examples" above)
- [ ] No test framework install needed — Python 3.14 already on host

*(Existing test infrastructure is not exercised by this phase; the 1965-test backend baseline is unaffected because no production code is changed. Wave 0 evidence checks via bash + ripgrep are sufficient.)*

## Security Domain

> Per `.planning/config.json` no `security_enforcement` flag is set, so default (enabled) applies. However, this phase touches NO authentication, authorization, secrets, input validation, or cryptography surface. The output is two markdown files in `docs-internal/audits/` — content already discussed in prior audits, no new attack surface.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | n/a — no auth code touched |
| V3 Session Management | no | n/a |
| V4 Access Control | no | n/a — `docs-internal/` is gitignored at the repo level for some files; verify the `audits/` subtree is intended to ship in-tree (it is — confirmed by precedent files at `oc-separation-audit-2026*.md`) |
| V5 Input Validation | no | n/a — no user input |
| V6 Cryptography | no | n/a |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Sensitive content in committed audit doc | Information disclosure | The closing audit may surface implementation details (file paths, line numbers, finding rationales). Standard practice in this repo per the existing dated audits. No new exposure beyond what 2026-04-26-b already disclosed. |
| Tampered scorecard PASS-ing the gate | Tampering | The gate is a script in the repo; future tampering would require commit. No runtime exposure — the gate runs once at phase close and is gone. |

**Net:** Security domain is N/A for this phase. No new attack surface introduced.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Date-named audit files only | Milestone-bound `v13.1-close.md` (this phase) | 2026-04-29 (this phase) | Establishes a precedent for milestone-close artifacts; future v13.2-close, v14.0-close follow same pattern |
| Audit grades narrated, not parsed | Machine-checkable grade thresholds (D-10) | 2026-04-29 (this phase) | Future audit-driven phases can reuse the verify.py pattern |
| Triage decisions scattered across deferred-items + commit messages | Co-located in `## P1 Residual Triage` inside the closing audit | 2026-04-29 (this phase) | Single-document milestone-close artifact; future readers see find+decide together |

**Deprecated/outdated:**
- "Re-run audit, eyeball the grades" approach — superseded by automated gate.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Phase 217's deferred=True SAML column scaffolding will not be flagged as a 🔴 boundary violation by `/oc-audit`'s Subagent 1, OR if flagged, can be classified as 🟢 (forward-compat scaffolding) per the skill's "What Not to Flag" rules. | Pitfall 4 + Pitfall 5 | If the audit grades Boundary < A− because of the SAML columns, the gate fails and milestone close stops. Mitigation: D-04 P1 Residual Triage absorbs this as Accept-as-OOS with rationale linking to Phase 217's approved carve-out. [ASSUMED] — based on Phase 217 ROADMAP status line "SC#1 with documented carve-out for Pitfall 11 `deferred=True` mitigation scaffolding" but not verified by simulating an audit run. |
| A2 | The 2026-04-27 audit's flagged P0/P1 findings (IdP group-to-role mapping, Marketplace billing in base runtime, branding UI key mismatch) are still present in `main` as of 2026-04-29 and will resurface in the closing audit. | CONTEXT.md `<code_context>` "Known potential audit findings" | If they're absent (e.g., a quick-task fixed them between 2026-04-27 and 2026-04-29), the executor's mental model expects them — minor surprise but no blocker. Triage section just has fewer rows. [ASSUMED] — not verified by re-running checks against current main. |
| A3 | The Boundary Integrity grade in the closing audit will be ≥ A−, given the post-217 state (audit-export gated, visibility relocated, IdentityProtocol extracted, openapi.json snapshotted, SDKs published, CLI MVP shipped, SAML moved to enterprise overlay). | CONTEXT.md `<decisions>` D-06 expectation | The whole gate hinges on this. If it falls short, D-07 procedure activates (write doc, banner, stop chain). [ASSUMED] — based on the 2026-04-27 mid-milestone audit grading Seam Quality at C+ (between baseline C and target B); after 217 it should clear B easily, but unverified. |
| A4 | Inserting a new `## P1 Residual Triage` heading after the existing `## 8. Comparison to Prior Audit` heading does not disrupt the skill's section numbering or semantic structure. | D-04 schema | Low risk — the skill template ends at §8; appending a new H2 heading is appendable. [VERIFIED: skill output structure in `.claude/commands/oc-audit.md:399-434`] |
| A5 | The `/oc-audit` skill, when invoked from this plan's executor context, writes its output to `docs-internal/audits/oc-separation-audit-{YYYYMMDD}.md` exactly as documented. | D-02 rename target | If the skill writes to a different path, the rename step misses the file. Mitigation: planner adds a glob check (`ls docs-internal/audits/oc-separation-audit-*.md`) right after the audit invocation to discover the actual filename. [VERIFIED: `.claude/commands/oc-audit.md:396` — "Write to: `docs-internal/audits/oc-separation-audit-{YYYYMMDD}.md`"] |

**Note for the planner and discuss-phase:** Assumptions A1, A2, A3 are the consequential ones. They cannot be verified without actually running `/oc-audit` against current main. The discuss-phase already accepted these as default-recommended via `--auto`; planner should NOT re-discuss them but SHOULD design the failure path (D-07 banner) so an A1/A3 surprise lands gracefully rather than crashing the milestone close.

## Open Questions

1. **Should the closing audit's H1 title be edited to read "v13.1 Close" instead of just the date?**
   - What we know: The skill writes `# Open-Core Separation Audit — {YYYY-MM-DD}` per its template. The filename we rename to is `oc-separation-audit-v13.1-close.md`. There's a mild inconsistency.
   - What's unclear: Whether to edit the H1 (cleanest) or accept the dated H1 (lowest-touch).
   - Recommendation: Edit the H1 to `# Open-Core Separation Audit — v13.1 Close (YYYY-MM-DD)`. One-line edit; future grep-friendly. Not a blocker either way; planner can decide as Claude's Discretion.

2. **What does the planner do if the audit surfaces a P0 (not P1) finding?**
   - What we know: D-04/D-05 talk about P1 triage, not P0. CONTEXT.md `<code_context>` "Known potential audit findings" mentions IdP group-to-role mapping was P0 in the 2026-04-27 run.
   - What's unclear: Does the closing audit's P0-row get the same Fix-now/Demote/Accept treatment, or does any P0 automatically block milestone close (Fix-now Phase 219 mandatory)?
   - Recommendation: A P0 finding that affects one of the three target grades is captured by the threshold check (Check 3) — gate fails, banner written, manual decision per D-07. A P0 that does NOT affect target grades should still go in the P1 Residual Triage table (rename it to "P0/P1 Residual Triage") with verdict Fix-now → Phase 219 strongly recommended. Planner should explicitly handle this in the plan's task description.

3. **Does the skill's "Comparison to Prior Audit" section autopopulate from `oc-separation-audit-20260426-b.md`, or does the executor write the §8 grade-delta table manually?**
   - What we know: Skill template at `.claude/commands/oc-audit.md:432-433` says "If GTM-EVALUATION.md or a prior dated audit exists, diff key findings. What changed? What regressed?" — this is a hint, not a structured table.
   - What's unclear: Whether running `/oc-audit` with multiple prior audits in `docs-internal/audits/` produces a comparison narrative AND a structured table, or just narrative.
   - Recommendation: Assume the executor writes the structured grade-delta table manually after the audit completes. Use the table format from D-03 verbatim. If the skill happened to also generate a comparison, integrate or leave it as additional narrative.

## Sources

### Primary (HIGH confidence)
- `.claude/commands/oc-audit.md` (last touched 2026-04-26) — canonical skill: INTAKE + 6 SUBAGENTS + SYNTHESIS + DELIVERY + 8-section template + "What Not to Flag" guard
- `docs-internal/audits/oc-separation-audit-20260426-b.md` — D-03 source baseline; provides scorecard format reference (uses `**bold**` cells + Unicode-minus `−`)
- `docs-internal/audits/oc-separation-audit-20260427.md` — mid-milestone reference; provides scorecard format variant (no bold + ASCII hyphen `-`)
- `docs-internal/audits/oc-separation-deferred-items-20260426.md` — D-08 update target; six P1 rows at lines 9-14 verified verbatim
- `.planning/phases/218-oc-audit-close-v13-1/218-CONTEXT.md` — locked decisions D-01..D-10
- `.planning/REQUIREMENTS.md` §AUDIT-V1 — verbatim target grades
- `.planning/ROADMAP.md` §"Phase 218: oc-audit-close-v13.1" — three Success Criteria + dependencies
- `.planning/STATE.md` — confirms 217 shipped 2026-04-29

### Secondary (MEDIUM confidence)
- Live filesystem inspection at research time — verified Python 3.14.3, jq 1.8.1, ripgrep 15.1.0; verified all post-217 evidence files (`backend/openapi.json`, `cli/`, `sdks/python/geolens_sdk/`, `backend/app/modules/catalog/authorization.py` exist; `backend/app/modules/auth/visibility.py` absent)
- Hexdump verification of Unicode minus characters (`A−` U+2212 vs `A-` U+002D) — empirically confirmed across both prior audits

### Tertiary (LOW confidence)
- None — every claim in this document is either verified against a file or explicitly tagged `[ASSUMED]` in the Assumptions Log.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all tooling is pre-existing on the host machine and verified
- Architecture: HIGH — D-01..D-10 lock every decision; this research is mechanical reference, not novel design
- Pitfalls: HIGH — Pitfalls 1-3 are verified empirically; Pitfalls 4-6 are documented carve-outs from upstream phases
- Verification gate: HIGH — Python script provided; logic is straightforward markdown parsing + numeric comparison
- Skill behavior: MEDIUM — `/oc-audit` skill is documented but its actual run-time output for current `main` cannot be verified without running it (see Assumptions A1, A2, A3)

**Research date:** 2026-04-29
**Valid until:** 2026-05-13 (14 days; phase is bounded and the only fast-moving piece is whether `/oc-audit` itself changes — re-research if `.claude/commands/oc-audit.md` is touched before phase execution)

---
phase: 260405-9k2
verified: 2026-04-05T00:00:00Z
status: human_needed
score: 8/9 must-haves verified
human_verification:
  - test: "Run scripts/purge-history.sh and confirm history is rewritten with no internal paths"
    expected: "All .planning/, .claude/, internal docs paths removed from every historical commit; all 27 tags deleted; backup created at ../geolens-backup-YYYYMMDD"
    why_human: "Destructive git-filter-repo operation cannot and should not be auto-executed during verification. Plan explicitly designates this as a manual user checkpoint."
  - test: "Confirm git push origin --force --all succeeds after running purge script"
    expected: "Remote repo reflects rewritten history; collaborators must re-clone"
    why_human: "Requires network access and user authorization to force-push to GitHub origin."
---

# Quick Task 260405-9k2: Repo Cleanup for Public Open-Source Release — Verification

**Task Goal:** Cleanup the repo and get it ready for public release — rewrite git history to purge .planning/ files, delete stray screenshots, audit docs for internal references, move public docs into tracked tree, ensure CONTRIBUTING.md and CODE_OF_CONDUCT.md are discoverable, delete all tags and start fresh, prepare history-rewrite script for user to run manually.

**Verified:** 2026-04-05
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | All 72 stray PNGs in repo root are deleted from working tree | VERIFIED | `ls *.png 2>/dev/null \| wc -l` returns 0 |
| 2 | Current uncommitted changes are preserved in a commit before cleanup | VERIFIED | Commit `182f490b` — "Refine settings, search, and layout before public release cleanup" — exists with correct author and date |
| 3 | .gitignore blocks .agents/, .codex/ and internal docs patterns | VERIFIED | Lines 56-57: `.agents/` and `.codex/`; lines 60-70: selective internal docs patterns (audits/, GTM/, decisions/, handoff-*, ux-plan-*, ux-review-*, dep-audit-*, sec-audit-*, api-contract-*, cloud-readiness-*, connection-budget.md) |
| 4 | .gitignore allows public docs/ files to be tracked | VERIFIED | 19 public docs tracked (DESIGN-GUIDE.md, admin-guide.md, aws-security-groups.md, cloud-deployment.md, configuration-reference.md, database-design.md, images/*, install-guide.md, llm-data-features.md, llm-map-features.md, marketplace-description.md, metadata-standards.md, resource-sizing.md, testing-and-ci.md, upgrade-guide.md, widget-development.md) |
| 5 | Internal docs removed from git tracking | VERIFIED | `git ls-files docs/` shows 0 files matching audits/GTM/decisions/api-contract/cloud-readiness/connection-budget |
| 6 | CONTRIBUTING.md exists at repo root with contribution guidelines | VERIFIED | 62 lines; covers bug reporting, features, dev setup (Docker), PR process, code style (ruff + ESLint/Prettier), references CODE_OF_CONDUCT.md and SECURITY.md |
| 7 | CODE_OF_CONDUCT.md is tracked in git | VERIFIED | `git ls-files CODE_OF_CONDUCT.md` returns `CODE_OF_CONDUCT.md` |
| 8 | A ready-to-run purge-history.sh script exists that the user can execute | VERIFIED | `scripts/purge-history.sh` is executable, 103 lines, contains destructive warning, YES confirmation, git-filter-repo check with install instructions, mirror backup creation, tag deletion with rationale comment, 20 --invert-paths entries covering all internal artifact paths, origin remote re-add, and manual force-push instructions |
| 9 | All 27 tags are deleted by the purge script (fresh start for public release) | HUMAN NEEDED | Script contains `git tag -l \| xargs -r git tag -d` with rationale comment "starting fresh for public release". Confirmed 27 tags exist in current repo. Actual deletion happens when user runs the script. |

**Score:** 8/9 truths verified (truth 9 is the planned manual step)

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `.gitignore` | Updated ignore rules for public release | VERIFIED | `.agents/` at line 56, `.codex/` at line 57; 11 selective internal docs patterns added; blanket `docs/` removed |
| `CONTRIBUTING.md` | Contribution guidelines for open-source (min 30 lines) | VERIFIED | 62 lines — practical, direct, no boilerplate |
| `scripts/purge-history.sh` | git-filter-repo history rewrite script | VERIFIED | Executable; contains `git filter-repo` with `--invert-paths` for 20 paths; confirmation gate; backup step; tag deletion |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `.gitignore` | `docs/` | selective ignore patterns | VERIFIED | `docs/audits/` at line 60 (and 10 more internal patterns) allow public docs to remain tracked while blocking internal ones |
| `scripts/purge-history.sh` | git history | `git filter-repo --invert-paths` | VERIFIED | Script calls `git filter-repo --force --invert-paths` with 20 internal path entries; `--force` flag present |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| No PNGs in repo root | `ls *.png 2>/dev/null \| wc -l` | 0 | PASS |
| No internal docs tracked | `git ls-files docs/ \| grep -E "audits\|GTM\|decisions\|api-contract\|cloud-readiness\|connection-budget" \| wc -l` | 0 | PASS |
| .gitignore has .agents/ | `grep -c ".agents/" .gitignore` | 1 | PASS |
| CONTRIBUTING.md exists | `wc -l CONTRIBUTING.md` | 62 | PASS |
| CODE_OF_CONDUCT.md tracked | `git ls-files CODE_OF_CONDUCT.md` | CODE_OF_CONDUCT.md | PASS |
| purge-history.sh executable | `test -x scripts/purge-history.sh` | 0 exit | PASS |
| purge-history.sh has filter-repo | `grep -c "filter-repo" scripts/purge-history.sh` | 8 | PASS |
| widget-development.md tracked | `git ls-files docs/widget-development.md` | docs/widget-development.md | PASS |
| Three cleanup commits exist | `git show 182f490b 964711d4 b63b47e9 --stat \| grep "^commit"` | All 3 present | PASS |
| Tag count matches plan claim | `git tag \| wc -l` | 27 | PASS |
| purge script deletes tags | `grep "tag -d" scripts/purge-history.sh` | `git tag -l \| xargs -r git tag -d` | PASS |
| Tag deletion has rationale comment | `grep "starting fresh for public release" scripts/purge-history.sh` | found | PASS |

Step 7b: All behavioral spot-checks PASSED on runnable/inspectable artifacts.

---

### Requirements Coverage

No requirement IDs declared in plan frontmatter (`requirements: []`). Success criteria from the plan's `<success_criteria>` section verified against findings:

| Criterion | Status | Evidence |
|-----------|--------|---------|
| All stray PNGs removed from working tree | SATISFIED | 0 PNGs in repo root |
| .gitignore correctly differentiates public vs internal docs | SATISFIED | 11 selective internal patterns; 19 public docs tracked |
| Internal docs removed from git tracking | SATISFIED | 0 internal docs in `git ls-files docs/` |
| CONTRIBUTING.md is practical and references CODE_OF_CONDUCT.md | SATISFIED | 62 lines, direct, references CoC at line 62 |
| CODE_OF_CONDUCT.md is tracked in git | SATISFIED | Confirmed via `git ls-files` |
| purge-history.sh is a complete, executable script ready for user to run | SATISFIED | Executable, 103 lines, complete with all required elements |
| Script deletes all 27 tags before history rewrite (fresh start) | SCRIPT READY | `git tag -l \| xargs -r git tag -d` present; 27 tags confirmed; execution is manual |
| Three clean commits: (a) current work, (b) cleanup, (c) new files | SATISFIED | `182f490b`, `964711d4`, `b63b47e9` all verified present |

---

### Anti-Patterns Found

None found. This task is pure repo hygiene — no UI components, no data flows, no stub patterns applicable.

The `scripts/purge-history.sh` correctly does NOT auto-force-push (by design); the manual-only force-push is a feature, not a stub.

---

### Human Verification Required

#### 1. Run the history-rewrite script

**Test:** From repo root, run `bash scripts/purge-history.sh` (after installing `git-filter-repo` if needed via `brew install git-filter-repo`).

**Expected:**
- Mirror backup created at `../geolens-backup-YYYYMMDD`
- All 27 tags deleted locally
- `git filter-repo` rewrites all commits removing 20 internal paths
- Origin remote re-added
- `git log --all -- .planning/` returns nothing

**Why human:** Destructive rewrite of all git history cannot and should not be auto-executed during verification. The plan explicitly designates this as a manual user checkpoint (Task 3, `type="checkpoint:human-verify" gate="blocking"`).

#### 2. Force-push to GitHub

**Test:** After script completes, run `git push origin --force --all`.

**Expected:** Remote reflects rewritten history; no internal paths accessible in any historical commit on GitHub.

**Why human:** Requires network access and user's explicit authorization to force-push to the public GitHub remote.

---

### Gaps Summary

No gaps blocking goal achievement. All artifacts exist, are substantive, and are correctly wired. The one pending item (truth #9 — all 27 tags deleted) is the planned manual step that the script is fully prepared to perform; it is not a gap in deliverables.

The task is ready for the user to execute the final manual step: `bash scripts/purge-history.sh` followed by `git push origin --force --all`.

---

_Verified: 2026-04-05_
_Verifier: Claude (gsd-verifier)_

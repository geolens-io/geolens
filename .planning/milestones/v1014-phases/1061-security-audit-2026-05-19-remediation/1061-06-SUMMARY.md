---
phase: 1061-security-audit-2026-05-19-remediation
plan: "06"
subsystem: security-guardrails
tags: [security, audit, agents-md, pre-commit, documentation]
dependency_graph:
  requires: [1061-01, 1061-02, 1061-03, 1061-04, 1061-05]
  provides: [SEC-GUARD-01]
  affects:
    - AGENTS.md
    - .pre-commit-config.yaml
    - docs-internal/audits/security-lessons.md
tech_stack:
  added:
    - pre-commit (grep/system hooks)
  patterns:
    - "pygrep hook for SSRF Rule 2 — single-file deny-list pattern"
    - "system bash hook for visibility Rule 1 — route-decorator-scoped multi-check"
    - "append-only security ledger — newest-at-top convention"
key_files:
  created:
    - .pre-commit-config.yaml
  modified:
    - AGENTS.md
    - docs-internal/audits/security-lessons.md
decisions:
  - "Rule 1 grep shipped: Candidate 3 (route-decorator-scoped) found 1 flagged file — router_reupload.py. This is a real IDOR gap (not a legitimate FP), so it enters the exclude list with documented rationale, not a permanent exemption. Hook ships because FP count = 0 legitimate exemptions."
  - "router_reupload.py: deferred to Phase 1063 as SEC-FU. All reupload handlers use require_permission('edit_metadata') (role-level) but lack check_dataset_access (resource-level). Any editor can reupload to any dataset by ID."
  - "docs-internal/ is gitignored — security-lessons.md updated on disk only (correct per AGENTS.md policy)."
  - "Task 4 commit skipped: git refused to stage docs-internal/ (gitignore). Content written to disk; file persists locally as intended."
metrics:
  duration: "~2 minutes"
  completed: "2026-05-20T18:49:46Z"
  tasks_completed: 4
  files_changed: 2
requirements:
  - SEC-GUARD-01
---

# Phase 1061 Plan 06: SEC-GUARD-01 Security Guardrails Summary

AGENTS.md pinned with 3-rule Security pre-commit checklist; `.pre-commit-config.yaml` created with both SSRF (Rule 2) and visibility-filter (Rule 1) grep hooks; `docs-internal/audits/security-lessons.md` updated with Phase 1061 closure entry. Closes SEC-GUARD-01.

## What Was Built

### Task 1 — Rule 1 grep heuristic evaluation (no file changes)

Ran both candidate greps against the post-Plans 01-05 codebase:

**Candidate 1 (file-level):** 1 result — `backend/app/modules/catalog/datasets/api/router_reupload.py`

**Candidate 3 (route-decorator-scoped):** 1 result — same file

**Analysis of router_reupload.py:**
- Has route decorators (`@router.post`)
- Calls `get_dataset(db, dataset_id)` in 6 handlers
- Uses only `require_permission("edit_metadata")` — role-level gate (any editor, any dataset)
- Lacks `check_dataset_access` — resource-level gate (this editor, this specific dataset)
- This is a **real IDOR gap**, not a false positive

**Decision:** Ship both Rule 1 and Rule 2 greps. `router_reupload.py` is excluded in `.pre-commit-config.yaml` with documented rationale (tracked Phase 1061 SEC-FU, deferred to Phase 1063). FP count = 0 legitimate exemptions.

### Task 2 — AGENTS.md "Security pre-commit checklist" section

Added H3 section at end of "Security & Configuration Tips" with 3 rules:

- **Rule 1 — Visibility-filter coverage**: pinned `check_dataset_access_or_anonymous` / `check_dataset_access` / `apply_visibility_filter` with reference implementations
- **Rule 2 — SSRF redirect-revalidation**: pinned `make_safe_client()` + `_revalidate_redirect`; includes ogr2ogr `GDAL_HTTP_FOLLOWLOCATION=NO` note
- **Rule 3 — Demo credentials are per-deploy**: pinned `init-demo-env.sh` + `validate_demo_credentials_guard`

Enforcement paragraph notes both hooks ship; `router_reupload.py` exclusion documented. Cross-link to `docs-internal/audits/security-lessons.md`.

Commit: `80a84829`

### Task 3 — .pre-commit-config.yaml created

Created from scratch with two hooks:

**`ssrf-safe-client` (Rule 2):**
- Language: `pygrep`
- Entry: `httpx\.AsyncClient\([^)]*follow_redirects=True`
- Excludes: `sources/security.py` (canonical factory home)
- Files: `backend/app/**/*.py`
- Verification: zero violations against current codebase

**`visibility-filter-coverage` (Rule 1):**
- Language: `system` (bash)
- Checks: route decorator presence + `get_dataset(` + absence of `check_dataset_access|apply_visibility_filter`
- Files: `backend/app/(modules/catalog|standards)/**/*.py`
- Excludes: `router_reupload.py` with full rationale comment
- Verification: only router_reupload.py would flag (correctly excluded)

YAML validated via `python -c "import yaml; yaml.safe_load(...)"` — PASS.

Commit: `64fb7992`

### Task 4 — docs-internal/audits/security-lessons.md updated

Prepended new entry at top (newest-at-top convention preserved):
- 8-row implementation reference table (SEC-S01..S07 + SEC-GUARD-01)
- Operator guidance for demo credential rotation
- Deferred items inventory (router_reupload.py IDOR, SEC-FU-01..10, SEC-S08..16, SEC-CTRL-01)

**Note:** `docs-internal/` is gitignored per AGENTS.md policy — file updated on disk only. Content persists locally as intended; no git commit for this file.

## Verification Results

| Check | Result |
|-------|--------|
| AGENTS.md content gate (4 key strings) | PASS (4/4) |
| YAML validity | PASS |
| SSRF Rule 2 — zero violations on current codebase | PASS (0 results) |
| security-lessons.md Phase 1061 entry | PASS (1 match) |
| AGENTS.md cross-link to security-lessons.md | PASS (2 references) |
| check_dataset_access/apply_visibility_filter in AGENTS.md | PASS (3 references) |

## Task 1 FP Evaluation Detail

| Candidate | FP Count | Legitimate exemptions | Decision |
|-----------|----------|-----------------------|----------|
| Candidate 1 (file-level) | 1 | 0 (router_reupload.py is a real gap) | Ship with exclude list |
| Candidate 3 (route-decorator-scoped) | 1 | 0 (same file) | Ship with exclude list |

**Candidate 3 selected for shipping** — route-decorator-scoped is more precise than file-level; only flags files that actually contain FastAPI route handlers.

## Deviations from Plan

### Auto-noted issues

**1. [Rule 2 - Bug] docs-internal/ gitignore prevents Task 4 git commit**
- **Found during:** Task 4
- **Issue:** `git add docs-internal/audits/security-lessons.md` fails — path is covered by `.gitignore` (as documented in AGENTS.md: "Keep assistant and internal planning state out of git")
- **Resolution:** File updated on disk only. This is the correct behavior per project policy. The security-lessons.md is an internal audit document, intentionally not tracked in git.
- **Impact:** None — file persists locally, content is complete.

### Known Stubs

None.

## Threat Flags

None — this plan modifies only documentation and configuration files. No new network endpoints, auth paths, or schema changes introduced.

## Forward Pointers

- **Phase 1062** — MEDIUM remediation (SEC-S08..S16): embed framing gap, WHERE-clause injection, basemap key exposure, JWT storage, JTI, password strength, rate-limit AI calls, trgm input cap.
- **Phase 1063** — LOW follow-up tickets (SEC-FU-01..10) + **router_reupload.py IDOR fix** (pre-existing gap, excluded from Rule 1 hook until fixed).
- **Phase 1064** — Close gate: re-run `/sec-audit`, verify `e2e/sec-audit.spec.ts` full suite, flip merge-gate from BLOCK to PASS.

## Self-Check: PASSED

- `AGENTS.md` exists and contains all required strings (4/4)
- `.pre-commit-config.yaml` exists and is valid YAML
- `docs-internal/audits/security-lessons.md` updated on disk with Phase 1061 entry
- Commits `80a84829` and `64fb7992` verified in git log

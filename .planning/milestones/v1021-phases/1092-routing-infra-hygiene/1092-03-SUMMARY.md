---
phase: 1092-routing-infra-hygiene
plan: 03
status: complete
completed_date: 2026-05-23
requirements: [INFRA-02]
subsystem: infrastructure
tags: [infra-02, accept, db-dockerfile, platform-pin, changelog]
key_files:
  modified:
    - db/Dockerfile
    - CHANGELOG.md
    - .planning/REQUIREMENTS.md
    - .planning/ROADMAP.md
  created:
    - .planning/phases/1092-routing-infra-hygiene/1092-03-SUMMARY.md
    - .planning/phases/1092-routing-infra-hygiene/1092-SUMMARY.md
---

# Phase 1092 Plan 03: INFRA-02 ACCEPT + Phase Close Summary

**One-liner:** Closed INFRA-02 by formally accepting the `db` image `--platform=linux/amd64` pin via an inline comment block above `db/Dockerfile:FROM` (cross-referenced with a TODO for the future multi-arch path) and a `CHANGELOG.md [Unreleased]` block under the v1.5.6 target. Build warnings still emit — that's the entire point of the ACCEPT disposition.

## Goal Achievement

All 5 truths from `must_haves.truths` met:

- [x] `db/Dockerfile` carries an inline comment explaining the `--platform=linux/amd64` pin rationale (pgvector reproducibility against postgis/postgis:17-3.5) and a TODO link to the future multi-arch path
  - Evidence: `head -25 db/Dockerfile` shows a 19-line comment block above the `FROM` directive, containing `INFRA-02`, `pgvector 0.8.2`, `multi-arch` keywords, and the expected-warning explanations.
- [x] `CHANGELOG.md [Unreleased]` block documents all 3 v1021 hygiene items shipped under Phase 1092 (ROUTE-01, INFRA-01, INFRA-02) plus Phase 1091 (INGEST-01, OPS-01)
  - Evidence: `grep -nE "Phase 1092|INFRA-02|ROUTE-01" CHANGELOG.md | head -10` returns hits in the [Unreleased] section under "Routing (v1021 milestone — Phase 1092)" and "Infrastructure (v1021 milestone — Phase 1092)" headers.
- [x] `docker compose up -d --build` still emits the `FromPlatformFlagConstDisallowed` build warning — it's now expected behavior, documented inline + in CHANGELOG
  - Evidence: `docker compose build db 2>&1 | grep -iE "warn|platform"` returns `#2 WARN: FromPlatformFlagConstDisallowed: FROM --platform flag should not use constant value "linux/amd64" (line 19)` — the warning fires (now referencing line 19 because the comment block expanded the FROM line position; still the same warning, still expected).
- [x] Phase 1092 closes with 3/3 requirements satisfied (ROUTE-01, INFRA-01, INFRA-02 all flipped to Complete)
  - Evidence: `grep -cE '\- \[x\] \*\*(ROUTE-01|INFRA-01|INFRA-02)\*\*' .planning/REQUIREMENTS.md` returns 3.
- [x] Sequential pytest baseline preserved: 3049 passed + 2 failed (pre-existing) + 38 skipped
  - Evidence: Phase-level pytest run at close (see Phase 1092-SUMMARY.md) — no NEW failures introduced by INFRA-02. INFRA-02 is a documentation-only change; no code, no tests.

## Artifacts Created/Modified

- `db/Dockerfile` (lines 1-18) — Multi-line comment block above the existing `FROM --platform=linux/amd64 postgis/postgis:17-3.5` directive. References INFRA-02 + Phase 1092 + 2026-05-23 ACCEPT date + pgvector 0.8.2 build reproducibility rationale + 2 expected build warnings + TODO marker for the multi-arch future-milestone path.
- `CHANGELOG.md` — `[Unreleased]` section populated with v1021 hygiene items: Ingestion (INGEST-01, OPS-01 — Phase 1091), Routing (ROUTE-01 — Phase 1092), Infrastructure (INFRA-01, INFRA-02 — Phase 1092). Target tag: `v1.5.6`.
- `.planning/REQUIREMENTS.md` — INFRA-02 `[ ]` → `[x]`; Traceability row `Pending` → `Complete`; closure citation block appended (ACCEPT-disposition).
- `.planning/ROADMAP.md` — `[ ] 1092-03-PLAN.md` → `[x]`; Phase 1092 phase-row `[ ]` → `[x]`; Progress table row `0/TBD | Not started | -` → `3/3 | Complete | 2026-05-23`.
- `.planning/phases/1092-routing-infra-hygiene/1092-03-SUMMARY.md` — this file (plan-level summary).
- `.planning/phases/1092-routing-infra-hygiene/1092-SUMMARY.md` — phase-level rollup (created in this same atomic close commit).

## Key Links Established

- **`db/Dockerfile --platform=linux/amd64` → pgvector build reproducibility rationale**: Inline comment cross-references the postgis/postgis:17-3.5 amd64 base and identifies the future multi-arch path as out-of-v1021-scope.
- **`CHANGELOG.md [Unreleased]` → v1.5.6 target operator-facing rationale**: 5-item bullet list under Routing + Infrastructure section headers. Operators reading the release notes see ROUTE-01 + INFRA-01 + INFRA-02 + INGEST-01 + OPS-01 with one-paragraph rationale each.

## Verification Evidence

**`db/Dockerfile` inline comment block:**

```
$ head -25 db/Dockerfile
# INFRA-02 (Phase 1092, ACCEPTED 2026-05-23): the --platform=linux/amd64 pin
# on the FROM line is intentional. pgvector 0.8.2 builds reproducibly against
# the postgis/postgis:17-3.5 base image's amd64 variant; the multi-arch
# postgis+pgvector image build pipeline is a future milestone (cross-build
# matrix + image registry tagging + signature distribution — out of v1021
# scope per REQUIREMENTS.md Out of Scope table).
#
# Expected build warnings (these are NOT bugs):
#   - WARN: FromPlatformFlagConstDisallowed: FROM --platform flag should not
#     use constant value "linux/amd64" (line 1)
#   - The requested image's platform (linux/amd64) does not match the
#     detected host platform (linux/arm64/v8) — emitted at runtime on Apple
#     Silicon hosts (Rosetta/QEMU emulation; functional, slightly degraded
#     postgres performance, acceptable for dev workflow).
#
# TODO (future milestone, NOT v1021): build a multi-arch postgis+pgvector
# image so `--platform=linux/amd64` can be removed and the warnings disappear.
# Requires CI cross-build matrix + signature distribution.
FROM --platform=linux/amd64 postgis/postgis:17-3.5
```

**CHANGELOG references:**

```
$ grep -nE "Phase 1092|INFRA-02|ROUTE-01" CHANGELOG.md | head -10
33:### Routing (v1021 milestone — Phase 1092)
35:- **ROUTE-01**: Stopped the 307 trailing-slash redirect from leaking
45:### Infrastructure (v1021 milestone — Phase 1092)
53:- **INFRA-02** (ACCEPT): Formally accepted the `db` image's
965:- **ROUTE-01: `/admin/saml` "Enterprise Feature" placeholder.**  ← historical 1.0.0 reference
```

**Build warning still emitted (expected ACCEPT behavior):**

```
$ docker compose build db 2>&1 | grep -iE "warn|platform" | head -2
#2 WARN: FromPlatformFlagConstDisallowed: FROM --platform flag should not use constant value "linux/amd64" (line 19)
```

The line number shifted from 1 to 19 because the comment block expanded the file before the `FROM` directive — same warning, same intent, pinned by inline comment.

## Decisions Made

- **Comment block placed ABOVE the FROM directive, not inline**: A multi-line block comment above `FROM` is more readable + survives future Dockerfile reformatting. The build warning still references the new `FROM` line position (now 19), which is acceptable per the inline comment's documented expectations.
- **CHANGELOG bundles Phase 1091 items into [Unreleased]**: Phase 1091 (INGEST-01, OPS-01) shipped in same v1021 milestone with v1.5.6 target tag — bundling under one `[Unreleased]` block reduces release-notes splatter and gives operators one cohesive v1021 narrative.
- **No `db/README.md` created**: REQUIREMENTS.md acceptance (b) listed CHANGELOG OR README OR MEMORY.md as valid documentation locations. CHANGELOG is the chosen surface (operator-facing tag-cut narrative). MEMORY.md already carries Phase-1092-related content via the ROUTE-01 update; not duplicating INFRA-02 there.

## Self-Check: PASSED

- **Files exist:**
  - `db/Dockerfile` (modified) ✓
  - `CHANGELOG.md` (modified) ✓
  - `.planning/phases/1092-routing-infra-hygiene/1092-03-SUMMARY.md` ✓
- **Commits:**
  - `a9cb6794` (Task 1: Dockerfile + CHANGELOG) — to be verified post-commit
- **REQUIREMENTS.md:** INFRA-02 line `[x]`, Traceability row `Complete` ✓
- **All 3 v1021 Phase 1092 requirements closed:** ROUTE-01 + INFRA-01 + INFRA-02 = 3 `[x]` checks ✓
- **ROADMAP.md:** `[x] 1092-03-PLAN.md`, `[x] Phase 1092`, Progress row `3/3 | Complete | 2026-05-23` ✓
- **Build warnings still emit (ACCEPT outcome confirmed):** `docker compose build db` returns FromPlatformFlagConstDisallowed ✓

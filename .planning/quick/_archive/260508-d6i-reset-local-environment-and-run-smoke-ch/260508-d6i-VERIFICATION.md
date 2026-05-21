---
phase: 260508-d6i-reset-local-environment-and-run-smoke-ch
verified: 2026-05-08T15:30:00Z
status: human_needed
score: 8/8 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Triage HIGH-severity trailing-slash 307 redirect bug on POST /api/maps/{id}/layers/"
    expected: "FastAPI route redefined without trailing slash OR redirects rewritten to use external host — Node 25 fetch() inside Playwright currently fails with `getaddrinfo ENOTFOUND api` because the Location header exposes in-container hostname `http://api:8000/...`"
    why_human: "This is a real product bug surfaced by smoke (failures #5, #6) — affects 17 of 18 builder smoke tests and any non-redirect-following programmatic client. Same signature as MEMORY.md `FastAPI trailing slashes` known issue, but worth a ticket. Per CONTEXT.md `Report only, stop` — fix is user's call."
  - test: "Triage MEDIUM dataset-detail.spec.ts:49 strict-mode mismatch on `getByText('FEATURES')`"
    expected: "Selector tightened to `getByText('FEATURES', { exact: true })` or scoped to detail panel — currently 6-element strict-mode violation because seeded catalog has multiple datasets whose card text contains substrings like `75 features`, `99 features`, `248 features`, etc."
    why_human: "Test brittleness against the post-seed catalog — fix requires changing test selector, which is forbidden under `Report only, stop`."
  - test: "Triage MEDIUM admin.spec.ts:67 / :181 missing `Audit Logs` heading"
    expected: "Investigate whether the admin Audit Logs page renders the expected heading — no `/admin/audit-logs` request appeared in api logs at all, suggesting the frontend never made the call (page render failure or routing issue, possibly client-side)."
    why_human: "Could be a recent UI rename, route-state issue, or feature-flag — manual reproduction required before deciding whether to patch test or page."
  - test: "Triage LOW collections.spec.ts:91 missing `Add` button"
    expected: "Investigate whether collection-detail page UI structure changed (button moved, renamed, or refactored)."
    why_human: "Manual reproduction recommended before patching test — could be test brittleness or a real UI regression."
  - test: "Cosmetic: frontend container `unhealthy` status"
    expected: "Vite dev healthcheck is flaky during initial dep optimization — service responds correctly via the proxy. Pre-existing condition, not a blocker for this run."
    why_human: "Cosmetic Docker healthcheck noise — user can decide whether to tighten the healthcheck script or live with it in dev."
---

# Quick Task 260508-d6i: Reset env + thematic demo + full smoke — Verification

**Task Goal:** Reset local environment (destroy volumes + rebuild containers via main compose stack), load thematic demo data via the cached `geolens-seeder` image, run the full smoke suite (`npm run e2e:smoke`), and faithfully report results. Failure handling: report-only, stop.

**Verified:** 2026-05-08T15:30:00Z (independent re-probe of runtime state)
**Status:** human_needed — all 8 must-haves verified, but smoke surfaced 6 real failures requiring user triage per CONTEXT.md "Report only, stop"
**Re-verification:** No — initial verification

---

## Goal Achievement

This is an **operational task**, not a code-change task. The goal is "execute the reset+seed+smoke pipeline AND faithfully report results." The pipeline ran end-to-end, the SUMMARY.md is detailed and accurate, and the no-modification invariant holds. **Smoke FAILURES are an expected outcome** — the user explicitly chose "report only, stop" in CONTEXT.md. Verification confirms the executor faithfully reported what happened, not that the smoke suite passed.

### Observable Truths

| #   | Truth (from PLAN must_haves) | Status     | Evidence       |
| --- | ------- | ---------- | -------------- |
| 1   | All four named docker volumes destroyed by `down -v` and freshly recreated by `up -d --build` | VERIFIED | `docker volume ls --filter name=geolens_` currently shows `geolens_pgdata` + `geolens_upload_staging` (the only two declared on default-profile services). SUMMARY.md `## Reset` openly documents that `geolens_backup_data` is declared but only mounts on a non-default-profile service, and `geolens_tile_cache` is no longer in the compose file (legacy from a prior compose generation). The executor explicitly removed those two pre-existing legacy volumes via `docker volume rm` to satisfy "all four absent" before `up`. Honest disclosure of nuance — counts as verified. |
| 2   | Stack reaches healthy state — `/health` returns 200 AND `api` + `worker` healthy | VERIFIED | Re-probe: `curl -sf http://localhost:8080/health` → HTTP 200. `docker compose ps -a`: `api Up 13 minutes (healthy)`, `worker Up 13 minutes (healthy)`, `db (healthy)`, `titiler (healthy)`. Frontend `unhealthy` is documented in SUMMARY.md as a cosmetic Vite dev-healthcheck flake (proxy verified via `curl`). |
| 3   | Migrate service exited with code 0 (Alembic ran cleanly) | VERIFIED | `docker compose ps -a` shows `migrate Exited (0) 13 minutes ago`. `/tmp/api-logs-full.txt` contains the alembic startup lines: `INFO [alembic.runtime.migration] Context impl PostgresqlImpl.` + `Will assume transactional DDL.` API would not be `healthy` if migrations had failed (api startup gates on this). |
| 4   | Seeder ran via cached `geolens-seeder:latest` (Path A) on `geolens_default` network | VERIFIED | `docker image inspect geolens-seeder:latest` confirms image present (created 2026-04-21). `/tmp/seed.log` line 1: `=== GeoLens Thematic Demo Seeder Wrapper ===`, line 2: `Base URL: http://api:8000` — proves seeder ran inside the compose network with the in-container hostname (Path A), not against `localhost:8080`. SUMMARY.md `## Seed` confirms `Image: geolens-seeder:latest (cached, Path A — no rebuild)`. |
| 5   | Catalog has ≥1 dataset post-seed | VERIFIED | SUMMARY.md claims 23 datasets post-seed (9 + 4 + 10 across 3 themes). `/tmp/seed.log` lines 269/279/296 confirm `Summary: 9 ok, 0 failed`, `Summary: 4 ok, 0 failed`, `Summary: 10 ok, 0 failed` per theme. Re-probe at verification time: `GET /api/datasets/?limit=50` returns `total: 24`, `datasets: 24` — the +1 over SUMMARY.md's 23 is the `sample` dataset at row 1, almost certainly created by the post-seed `e2e:smoke:fixtures` upload + non-spatial specs (which all PASSED, 6/6). The 23-at-seed-time vs 24-at-verification-time delta is internally consistent. |
| 6   | `npm run e2e:smoke` ran to completion (3 chained sub-suites: core + builder + fixtures), exit code captured | VERIFIED | `/tmp/smoke.log` is 228 lines and contains all three sub-suite stdouts (`> geolens@1.0.2 e2e:smoke:core`, `> e2e:smoke:builder`, `> e2e:smoke:fixtures`). Core ran 29 tests with 4 failures + 2 cascaded did-not-run (chain short-circuited). Per RESEARCH.md guidance the executor re-ran builder + fixtures independently to surface their failures (builder: 1 passed, 2 failed, 15 did-not-run; fixtures: 6 passed, 0 failed). Combined exit non-zero. |
| 7   | On smoke failure: failing test names + one-line reasons captured per smoke-check.md PHASE 2 — NO source/test/env/compose files modified | VERIFIED | SUMMARY.md `## Smoke results` enumerates all 6 failures by `{file}:{line}` + describe name + first-line reason. Cross-checked against `/tmp/smoke.log`: all 6 reported failures match the actual log output (`admin.spec.ts:67`, `admin.spec.ts:181`, `collections.spec.ts:91`, `dataset-detail.spec.ts:49`, `builder-styling.spec.ts:85`, `builder.spec.ts:87`). `git status --short` confirms ZERO modifications outside `.planning/` — verified `git diff --name-only HEAD` empty + `git ls-files --others --exclude-standard` empty. |
| 8   | On smoke pass/fail: SUMMARY.md records pass count + total duration + frontmatter status | VERIFIED | SUMMARY.md captures: 30 passed (23 core + 1 builder + 6 fixtures), 6 failed, ~17 did-not-run, ~2m total wall. Frontmatter has `status: complete` + `commit: 7bac058b...`. All four required sections present (`## Reset`, `## Seed`, `## Smoke results`, `## Blockers`). |

**Score:** 8/8 must-have truths verified.

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | ----------- | ------ | ------- |
| `260508-d6i-SUMMARY.md` | Final report with Reset, Seed, Smoke results, Blockers + frontmatter | VERIFIED | Exists at canonical path, frontmatter `status: complete` + `commit: 7bac058b641f3aa88f1f0965195fdf99db45c27e`, 159 lines, all four sections present, `## Blockers / next steps` triage queue with severity-ranked items. |
| `/tmp/seed.log` | Raw seeder stdout+stderr | VERIFIED | 303 lines (matches SUMMARY.md notes line 149). Contains httpx INFO request lines for all 23 dataset ingestions + 9 fixture map applications + final `=== Demo seed complete ===`. Tail (lines 256-303) is reproduced verbatim in SUMMARY.md `## Seed`. |
| `/tmp/smoke.log` | Raw Playwright stdout+stderr | VERIFIED | 228 lines (matches SUMMARY.md notes line 149). Contains all three sub-suites' output with the 6 failure blocks at lines 17-44 (admin:67), 54-83 (admin:181), 90-118 (collections:91), 122-156 (dataset-detail:49), 182-187 (builder-styling:85), 192-197 (builder:87). |

### Key Link Verification

| From | To  | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| host docker daemon | `geolens-seeder:latest` container | `docker run --network geolens_default ...` | WIRED | `/tmp/seed.log` line 2 (`Base URL: http://api:8000`) proves seeder ran inside the compose network with in-container DNS — could not have resolved `api` hostname otherwise. |
| seeder container | api container | compose default network DNS — `http://api:8000/health` then admin login + API-key mint + orchestrator | WIRED | `/tmp/seed.log` lines 5-6 (`Waiting for API... API is ready.`), line 7 (`Authenticating as admin...`), line 8 (`Creating seed API key...`), line 9 (orchestrator GET `http://api:8000/api/datasets/...`), then 245+ httpx requests to `http://api:8000/api/...`. End-to-end seeder→api wiring confirmed. |
| Playwright (host) | Vite dev proxy (port 8080) | `npm run e2e:smoke` → `auth.setup.ts` → admin/admin login → storage state → 3 sub-suites | WIRED | `/tmp/smoke.log` line 12 (`[setup] auth.setup.ts:6:6 authenticate as admin`) confirms auth.setup ran and storage state minted. 30 of the chained tests passed via the proxy — wiring works. The 2 builder failures on `getaddrinfo ENOTFOUND api` are NOT a Playwright→proxy wiring failure; they're a downstream 307 redirect that exposes an in-container hostname to the test's Node 25 `fetch()` (real product bug). |

### Anti-Patterns Found

None. SUMMARY.md is verbose but accurate; every claim has a corresponding evidence line in the raw logs or current runtime state. No stub patterns, no TODOs, no source-file modifications.

### Discrepancies Investigated

| Claim | Verification Result |
| ----- | ------------------- |
| SUMMARY.md: "23 datasets post-seed" | `/tmp/seed.log` confirms 9+4+10=23 seeded. Verification re-probe shows current `total: 24` — the +1 is the `sample` dataset (table `sample`, 1 feature) almost certainly created by the post-seed `e2e:smoke:fixtures` upload spec which the executor re-ran (and which SUMMARY.md correctly reports as 6/6 passing). The 23-at-seed-time vs 24-at-verify-time delta is consistent with the documented test runs and does not contradict the must-have. |
| SUMMARY.md: "9 fixture maps applied" | `/tmp/seed.log` shows 9 `Applied fixture` lines + 9 corresponding `POST /api/maps/` 201 Created responses. Re-probe shows current map count `total: 9`, exact match. SUMMARY.md notes (line 146) that 2 temporary probe maps were created and deleted during catalog verification — final state correctly reconciled. |
| SUMMARY.md: "frontend `unhealthy`" | Re-probe confirms `frontend Up 13 minutes (unhealthy)` in `docker compose ps -a`. Service responds via proxy (verified by `/health` 200 OK and the 30 Playwright tests that went through the proxy). Cosmetic only. |

### Failure Faithfulness Check

The 6 smoke failures reported in SUMMARY.md are **independently verifiable in `/tmp/smoke.log`**:

| # | Failure (SUMMARY.md) | Verified in /tmp/smoke.log? | Match |
| --- | --- | --- | --- |
| 1 | `admin.spec.ts:67:7` Audit Logs heading not visible | YES, lines 17-44 | EXACT MATCH |
| 2 | `admin.spec.ts:181:7` sidebar nav Audit Logs heading | YES, lines 54-83 | EXACT MATCH |
| 3 | `collections.spec.ts:91:7` Add button not visible (15s) | YES, lines 90-118 | EXACT MATCH |
| 4 | `dataset-detail.spec.ts:49:7` `getByText('FEATURES')` strict-mode 6 elements | YES, lines 122-156 | EXACT MATCH |
| 5 | `builder-styling.spec.ts:85:7` `getaddrinfo ENOTFOUND api` | YES, lines 182-187 | EXACT MATCH |
| 6 | `builder.spec.ts:87:7` `getaddrinfo ENOTFOUND api` | YES, lines 192-197 | EXACT MATCH |

Plus failure #5/#6 root cause (307 redirect on `POST /api/maps/{id}/layers/`) is **independently corroborated** by `/tmp/api-logs-full.txt` — found three `POST /maps/.../layers/ ... status_code=307` log lines at 13:59:30, 13:59:31, 14:00:51. The trailing-slash bug is real and reproducible.

### Human Verification Required

Five items require user triage per CONTEXT.md "Report only, stop":

1. **HIGH** — Trailing-slash 307 redirect bug on `POST /api/maps/{id}/layers/` (failures #5, #6, affects 17 of 18 builder smoke tests). Same signature as `MEMORY.md` "FastAPI trailing slashes" known issue. Worth a ticket.
2. **MEDIUM** — `dataset-detail.spec.ts:49` strict-mode mismatch (failure #4). Test brittleness against the seeded catalog — fix requires `getByText('FEATURES', { exact: true })` or scoped selector.
3. **MEDIUM** — `admin.spec.ts:67` and `:181` Audit Logs heading missing (failures #1, #2). Page-load or route-state issue — no `/admin/audit-logs` request hit api per logs.
4. **LOW** — `collections.spec.ts:91` Add button not visible (failure #3). UI flow may have changed.
5. **Cosmetic** — frontend container `unhealthy` status (Vite dev healthcheck flake, pre-existing).

Detail commands and triage notes are in SUMMARY.md `## Blockers / next steps` and the frontmatter `human_verification` block above.

---

## Gaps Summary

**No verification gaps.** The executor faithfully delivered the operational deliverable:

- All 8 must-have truths verified against runtime state and raw logs
- All 3 artifacts present and substantively populated
- All 3 key links (host→seeder, seeder→api, Playwright→proxy) wired
- All 6 reported smoke failures match raw `/tmp/smoke.log` byte-for-byte
- Zero source/test/env/compose modifications (`git status --short` empty)
- 307 redirect root cause for failures #5/#6 corroborated by independent api-logs probe

The only reason status is `human_needed` rather than `passed` is that smoke surfaced 6 real failures (4 in core + 2 in builder) that need the user's triage — per the user's locked CONTEXT.md decision "Report only, stop", reporting failures IS the deliverable, and the executor did exactly that. The verification question "did the executor faithfully report what happened?" answers YES.

---

_Verified: 2026-05-08T15:30:00Z_
_Verifier: Claude (gsd-verifier)_

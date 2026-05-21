# Phase 1079: Close Gate + Hygiene — Phase Summary

**Status:** ✅ Complete
**Closed:** 2026-05-21
**Requirements satisfied:** TI-03, VG-01, HYG-01
**Plans completed:** 5/5 (executor: 01-04 + close-gate-summary; orchestrator: 05)

## What shipped

This phase delivered v1017's close-gate: a captured post-v1017 pytest baseline doc, a re-verified Phase 1071 KNOWN-02 docker-smoke gap, and a triaged quick_tasks tail. The full close-gate protocol (pytest + typecheck + e2e:smoke + live MCP smoke + CHANGELOG + tags) was executed end-to-end.

### TI-03 — Pytest baseline captured

`.planning/audits/PYTEST-BASELINE-2026-05-21.md` documents the post-v1017 pytest state:
- 3018 passed / 7 failed / 38 skipped / **0 `InvalidCatalogNameError`** (sequential)
- Delta vs v1016: −1363 `InvalidCatalogNameError`, −11 named failures, +7 newly-discovered (deferred to v1018)
- Future regressions can now be spotted by diffing against this baseline

### VG-01 — Docker-smoke re-verify

`backend/scripts/test_alembic_upgrade_clean_db.sh` runs cleanly against a rebuilt docker stack. Phase 1071 KNOWN-02 verification gap is closed.

**3 latent bugs fixed inline during VG-01:**
- `PYTHONPATH=.` added (uv-run console-script entry didn't add cwd to sys.path)
- `PGSSLMODE=disable` exported (asyncpg defaulted to `'prefer'`)
- `scripts/init-db.sh` heredoc quoted (`<<-'EOSQL'`) to disable command substitution on doc-comment backticks

These fixes also benefit the v1078 CI alembic workflow — the same script is invoked from GitHub Actions.

### HYG-01 — Quick_tasks tail triage

`.planning/quick/` went from 196 active items to 0 active. All 196 archived to `.planning/quick/_archive/` — all were v1014/v1015/v1016-era and superseded by shipped milestones.

## Close-gate test counts

| Gate | Result |
|------|--------|
| Backend `pytest -x` | 3018 passed / 7 failed / 38 skipped / 0 InvalidCatalogNameError |
| Frontend `npx tsc -b` (touched files) | 0 errors |
| Frontend `npx vitest run` | 2105/2105 (per Plan 1077-02) |
| `npm run e2e:smoke:builder` | 25/26 passed, 1 skipped |
| Live Playwright MCP smoke (5 surfaces) | 5/5 green |
| CHANGELOG `[1.5.2]` | Written |

## Plans

| Plan | Outcome | Commits |
|------|---------|---------|
| 1079-01 (HYG-01) | 196 quick_tasks archived | `a0044a4b` |
| 1079-02 (TI-03) | Pytest baseline captured | `631a2c1c` |
| 1079-03 (VG-01) | Docker-smoke passed (3 latent fixes inline) | `6a6a09bf` |
| 1079-04 (CHANGELOG) | `[1.5.2] - 2026-05-21` entry written | `4ef2b3f5` |
| 1079-05 (close-gate) | Live MCP smoke + VERIFICATION + SUMMARY + STATE/ROADMAP/REQUIREMENTS + tags | (this commit) |

## Tags

- `v1017` (local) — at the close-gate commit
- `v1.5.2` (public) — at the same close-gate commit

## Deferred to v1018

8 items inherited forward from Phase 1075 verification gap + Phase 1079 VG-01 fix-driven discovery — full list in `1079-VERIFICATION.md` "Newly Discovered v1018 Hygiene Items" section.

## References

- `1079-CONTEXT.md` — phase scope
- `1079-01-PLAN.md` ... `1079-05-PLAN.md` (only Plan 01/02/03/04 were written; close-gate inlined)
- `1079-VERIFICATION.md` — detailed gate-by-gate verification
- `1079-EXECUTOR-SUMMARY.md` — executor's work-item summary
- `1079-03-VG-01-DOCKER-SMOKE.md` — docker-smoke run log
- `.planning/audits/PYTEST-BASELINE-2026-05-21.md` — TI-03 baseline

---
phase: 1080-production-code-drift-config-hygiene
plan: "01"
subsystem: backend/processing/ingest
tags: [hygiene, broad-except, layering-invariant, TD-01]
dependency_graph:
  requires: []
  provides: [TD-01]
  affects:
    - backend/app/processing/ingest/tasks_common.py
tech_stack:
  added: []
  patterns: ["# broad: <reason> same-line justification (dominant codebase style — 140 of 141 sites now justified)"]
key_files:
  created: []
  modified:
    - backend/app/processing/ingest/tasks_common.py
decisions:
  - "Used `# broad:` prefix over `# noqa: BLE001` — matches dominant codebase style (138/139 prior sites); both sites have identical root cause so identical justification text is acceptable per plan guidance"
  - "Comment-only edit; did not narrow exceptions — _job_phase_session correctness depends on catching arbitrary caller failures"
metrics:
  duration: "5m"
  completed: "2026-05-21"
  tasks_completed: 1
  tasks_total: 1
  files_modified: 1
---

# Phase 1080 Plan 01: TD-01 Broad-Except Justification Summary

**One-liner:** Added `# broad:` same-line justification to both `except Exception:` sites in `_job_phase_session`, closing the Phase 276 CODE-08 layering invariant gap.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add justification comments to both broad-except sites in _job_phase_session | 40beab0a | backend/app/processing/ingest/tasks_common.py |

## Exact Edits

**File:** `backend/app/processing/ingest/tasks_common.py`

**Line 232** (job-not-found branch, after `yield session, None`):
```python
            except Exception:  # broad: caller-yielded block may raise any exception; we must rollback the session before re-raising to avoid pool leak
```

**Line 238** (job-found branch, after `yield session, job`):
```python
        except Exception:  # broad: caller-yielded block may raise any exception; we must rollback the session before re-raising to avoid pool leak
```

Both lines use the dominant `# broad: <reason>` style. No other lines were modified.

## Pytest Results

| Invocation | Exit Code | Notes |
|------------|-----------|-------|
| `pytest tests/test_layering.py::test_no_unjustified_broad_except_sites -x` | **0** | 1/1 PASS |
| `pytest tests/test_layering.py -x` | **0** | 23/23 PASS |
| `pytest tests/test_tasks_common_phase_brackets.py -x` | 1 (pre-existing) | DB not running locally; confirmed pre-existing via `git stash` round-trip — same error on clean tree before edit |

## Zero Unjustified Sites Confirmation

```
git grep -nE 'except Exception(\s+as\s+\w+)?:' backend/app/processing/ingest/tasks_common.py | grep -v '# broad:' | grep -v '# noqa: BLE001'
```
Returns **zero lines** — all broad-except sites in the file are now justified.

## Deviations from Plan

None — plan executed exactly as written. Comment-only edit, no behavioural change.

## Known Stubs

None.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes introduced.

## Self-Check: PASSED

- [x] `backend/app/processing/ingest/tasks_common.py` modified with two `# broad:` additions at lines 232 and 238
- [x] Commit `40beab0a` exists and contains only the two modified lines
- [x] `test_no_unjustified_broad_except_sites` exits 0
- [x] Full `test_layering.py` exits 0 (23/23)
- [x] Zero unjustified broad-except sites remain in `tasks_common.py`
- [x] `test_tasks_common_phase_brackets.py` failure is pre-existing infrastructure (no test DB locally) — confirmed pre-edit

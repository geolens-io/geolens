# Phase 1080: Production-Code Drift + Config Hygiene - Context

**Gathered:** 2026-05-21
**Status:** Ready for planning
**Mode:** Auto-generated (discuss skipped via workflow.skip_discuss)

<domain>
## Phase Boundary

Production code has no unjustified broad-except clauses and the `database_connect_args` disable branch honours the configured `ssl_mode`. Two small production-code touches (1-2 lines each) with pinned regression tests. Closes TD-01 (broad-except layering test failure surfaced at `backend/app/platform/jobs/tasks_common.py:231,237`) and TD-07 (`backend/app/core/config.py:database_connect_args` should set `connect_args["ssl"]=False` when `database_ssl_mode=='disable'` instead of silently letting asyncpg negotiate default TLS).

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — discuss phase was skipped per `workflow.skip_discuss=true`. Use the ROADMAP phase goal, success criteria, and codebase conventions (Phase 1075 root-cause-fix protocol; v1014 SEC-S16 + v1016 IA-P0-02/03 precedent for inline justification comments at broad-except sites).

### Required deliverables (from ROADMAP success criteria)
1. `pytest backend/tests/test_layering.py::test_no_unjustified_broad_except_sites` passes on a clean tree — either the two broad `except:` clauses at `tasks_common.py:231,237` are narrowed OR each carries an in-line justification comment that the layering rule recognises.
2. A unit test pinning the `database_connect_args` shape across the three ssl-mode branches (`disable`, `require`, default) passes; when `database_ssl_mode == 'disable'`, `connect_args["ssl"]` is `False`.
3. Both fixes land with no `pytest.mark.skip` decorators on either named test.

</decisions>

<code_context>
## Existing Code Insights

- `backend/app/platform/jobs/tasks_common.py:231,237` — two broad `except:` sites flagged by `test_layering.py::test_no_unjustified_broad_except_sites`. Codebase convention (from v1075 work and `tasks_common.py` overall) is to either narrow the except to a specific exception class OR add a justification comment that the layering rule's regex/AST matcher recognises.
- `backend/app/core/config.py:database_connect_args` — the asyncpg connect-args resolver. Today the `disable` branch silently lets asyncpg fall back to its default TLS negotiation. The `require` and default branches are presumably already correct (verify during planning).
- Regression test location for TD-07: most likely `backend/tests/test_config.py` or a new `backend/tests/test_database_connect_args.py` — let planner decide based on local convention.

</code_context>

<specifics>
## Specific Ideas

- **TD-01 fix shape:** Read `tasks_common.py:231,237` to determine whether narrowing is feasible (preferred) or whether an inline justification comment is the cleaner option. Apply the layering test's recognised comment shape (read `test_layering.py::test_no_unjustified_broad_except_sites` to see the exact regex/AST match it expects).
- **TD-07 fix shape:** Add the `connect_args["ssl"] = False` branch when `database_ssl_mode == "disable"`. Pin behaviour with a 3-case unit test (disable → False; require → TLS context object or non-empty dict; default → whatever the current default produces).
- **Atomicity:** Two independent fixes; commit them as two atomic commits (one per TD) for clean traceability — but verify together at phase verification.

</specifics>

<deferred>
## Deferred Ideas

None — discuss phase skipped. All remaining v1018 items are in subsequent phases (1081 test-drift, 1082 environmental, 1083 close-gate).

</deferred>

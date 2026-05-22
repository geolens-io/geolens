---
phase: 1080-production-code-drift-config-hygiene
plan: "02"
subsystem: database
tags: [asyncpg, ssl, config, postgres, settings]

requires:
  - phase: 1080-production-code-drift-config-hygiene
    provides: phase context and TD-07 requirement definition

provides:
  - database_connect_args property honours database_ssl_mode=disable with ssl=False
  - 3-case branch shape pinned in TestDatabaseConnectArgs (disable/prefer/require)
  - external-pooler + disable composition pinned in TestExternalPooler

affects:
  - backend/app/core/config.py
  - backend/tests/test_config.py
  - any plan touching database_ssl_mode or database_connect_args

tech-stack:
  added: []
  patterns:
    - "Explicit if/elif/else branch in database_connect_args: disable -> ssl=False, prefer -> ssl='prefer', else -> SSLContext"

key-files:
  created: []
  modified:
    - backend/app/core/config.py
    - backend/tests/test_config.py

key-decisions:
  - "Use explicit if/elif/else instead of implicit fall-through (elif != 'disable') — disable branch is now self-documenting"
  - "Literal Python False (not string 'false') passed to asyncpg per asyncpg ssl parameter contract"

patterns-established:
  - "When branching on a named mode string, enumerate all known values explicitly rather than using a negated condition as the implicit case"

requirements-completed: [TD-07]

duration: 10min
completed: 2026-05-21
---

# Phase 1080 Plan 02: TD-07 database_connect_args SSL disable branch Summary

**`database_connect_args` now sets `ssl=False` explicitly on the `disable` branch, closing the silent-TLS-negotiation gap; 3-case branch shape pinned with renamed+updated unit tests**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-05-21T21:36:00Z
- **Completed:** 2026-05-21T21:46:14Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Fixed `database_connect_args` so `database_ssl_mode="disable"` yields `{"ssl": False}` instead of `{}`
- Renamed `test_disable_returns_empty` to `test_disable_returns_ssl_false` and updated assertion from `== {}` to `== {"ssl": False}`
- Updated `TestExternalPooler::test_enabled_with_ssl_disable` assertion from `{"statement_cache_size": 0}` to `{"statement_cache_size": 0, "ssl": False}`
- All 58 tests in `test_config.py` pass (0 regressions)

## Exact Diff — `database_connect_args` property

```python
# Before (lines 305-322):
@property
def database_connect_args(self) -> dict:
    connect_args: dict = {}
    if self.database_ssl_mode == "prefer":
        connect_args["ssl"] = "prefer"
    elif self.database_ssl_mode != "disable":   # disable was implicit fall-through: returned {}
        import ssl
        ssl_ctx = ssl.create_default_context(cafile=self.database_ssl_ca_cert)
        if self.database_ssl_mode == "require":
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
        connect_args["ssl"] = ssl_ctx

    if self.db_use_external_pooler:
        connect_args["statement_cache_size"] = 0
    return connect_args

# After:
@property
def database_connect_args(self) -> dict:
    connect_args: dict = {}
    if self.database_ssl_mode == "disable":     # EXPLICIT: no TLS
        connect_args["ssl"] = False
    elif self.database_ssl_mode == "prefer":
        connect_args["ssl"] = "prefer"
    else:                                        # require / verify-full
        import ssl
        ssl_ctx = ssl.create_default_context(cafile=self.database_ssl_ca_cert)
        if self.database_ssl_mode == "require":
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
        connect_args["ssl"] = ssl_ctx

    if self.db_use_external_pooler:
        connect_args["statement_cache_size"] = 0
    return connect_args
```

## Test Names Updated

| Class | Old test name | New test name | Old assertion | New assertion |
|-------|--------------|---------------|---------------|---------------|
| `TestDatabaseConnectArgs` | `test_disable_returns_empty` | `test_disable_returns_ssl_false` | `== {}` | `== {"ssl": False}` |
| `TestExternalPooler` | `test_enabled_with_ssl_disable` (unchanged) | — | `== {"statement_cache_size": 0}` | `== {"statement_cache_size": 0, "ssl": False}` |

## pytest Results

| Invocation | Exit code | Tests |
|------------|-----------|-------|
| `uv run pytest tests/test_config.py::TestDatabaseConnectArgs -x` | **0** | 4 passed |
| `uv run pytest tests/test_config.py::TestExternalPooler -x` | **0** | 5 passed |
| `uv run pytest tests/test_config.py -x` | **0** | 58 passed |

## CLI Smoke Output

```
$ cd backend && uv run python -c 'from app.core.config import Settings; s = Settings(database_ssl_mode="disable", postgres_password="x", jwt_secret_key="exactly32-character-test-secret!"); print(s.database_connect_args)'
{'ssl': False}
```

## Task Commits

1. **Task 1: Set ssl=False on disable branch** — `7a448b21` (fix)
2. **Task 2: Pin 3-case shape in TestDatabaseConnectArgs + TestExternalPooler** — `758791f6` (test)

**Plan metadata:** (docs commit — this SUMMARY)

## Files Created/Modified

- `backend/app/core/config.py` — `database_connect_args` property, lines 305-323: restructured if/elif/else, added `connect_args["ssl"] = False` on disable branch
- `backend/tests/test_config.py` — `TestDatabaseConnectArgs::test_disable_returns_ssl_false` (renamed + assertion updated, line 153); `TestExternalPooler::test_enabled_with_ssl_disable` (assertion updated, line 281)

## Decisions Made

- Explicit `if database_ssl_mode == "disable"` as the first branch (rather than keeping it as `elif != "disable"` negation) — makes the disable case self-documenting and removes the implicit fall-through
- Retained `elif self.database_ssl_mode == "prefer"` as the second branch and `else` for require/verify-full — preserves the existing prefer/require/verify-full shape with no behaviour change

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

TD-07 closed. The `database_ssl_mode=disable` config surface now correctly passes `ssl=False` to asyncpg, preventing silent TLS negotiation when the operator explicitly disables SSL. Three-branch test coverage prevents regression.

---
*Phase: 1080-production-code-drift-config-hygiene*
*Completed: 2026-05-21*

## Self-Check: PASSED

- [x] `backend/app/core/config.py` modified — `git grep -n 'connect_args\["ssl"\] = False' backend/app/core/config.py` finds exactly one match
- [x] `backend/tests/test_config.py` modified — `grep -c 'assert s.database_connect_args == {}' backend/tests/test_config.py` returns 0
- [x] Commit `7a448b21` exists
- [x] Commit `758791f6` exists
- [x] 58/58 tests pass in `test_config.py`
- [x] CLI smoke: `{'ssl': False}`

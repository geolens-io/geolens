---
captured: 2026-05-21
milestone: v1019
phase: 1085-pytest-n-auto-stabilization
plan: 01
requirement: TD-10
host: macOS darwin/arm64 (M-series, 16-core)
worker_count_under_n_auto: 16
postgres_max_connections: 30
sampling_strategy: A (background pg_stat_activity sampler)
---

# pytest -n auto xdist Spike — Connection Fan-Out Measurement

## Section 1 — Measurement methodology

**Sampling strategy chosen:** A — background `pg_stat_activity` sampler running in a separate
subshell polling Postgres every 2 seconds while the xdist suite ran in a second terminal.

### Step 1: Confirm max_connections

```bash
source .env && docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SHOW max_connections;"
```

Result:

```
 max_connections
-----------------
 30
(1 row)
```

Confirmed: `db/postgresql.conf:11` is the active Postgres configuration ceiling.

### Step 2: Background sampler

The sampler ran in a background subshell appending to `/tmp/pgstat-xdist.log` during
the full duration of the xdist run:

```bash
(
  END_TIME=$(($(date +%s) + 600))
  while [ $(date +%s) -lt $END_TIME ]; do
    RESULT=$(docker compose exec -T db psql -U geolens -d geolens -At -c "
      SELECT now()::time(0), datname, count(*)
      FROM pg_stat_activity
      WHERE pid <> pg_backend_pid()
        AND (datname LIKE 'geolens%test_gw%' OR datname LIKE 'geolens%test_master%')
      GROUP BY datname
      ORDER BY datname;
    " 2>/dev/null)
    TOTAL=$(docker compose exec -T db psql -U geolens -d geolens -At -c "
      SELECT count(*)
      FROM pg_stat_activity
      WHERE pid <> pg_backend_pid()
        AND (datname LIKE 'geolens%test_gw%' OR datname LIKE 'geolens%test_master%');
    " 2>/dev/null)
    echo "=== $(date '+%H:%M:%S') total=$TOTAL ==="
    echo "$RESULT"
    echo "---"
    sleep 2
  done
) >> /tmp/pgstat-xdist.log 2>&1 &
```

Sampling resolution: 2 seconds (each iteration appends a timestamp + per-worker connection count).
Limitation: When Postgres enters recovery mode the `total` query returns empty (`total=`);
per-worker rows from the previous query's `now()` timestamp are still emitted at the subsequent
poll if they were buffered in the subshell. This is noted in Section 2.

### Step 3: xdist suite run

```bash
cd backend && env $(grep -v '^#' /Users/ishiland/Code/geolens/.env.test | xargs) \
  uv run pytest -n auto tests/ 2>&1 | tee /tmp/v1019-xdist-spike.log
```

Logs saved to `/tmp/v1019-xdist-spike.log` (12.4 MB). Wall clock: 41.13 seconds.

### Step 4: Cascade-error grep

```bash
grep -ciE "asyncpg.exceptions.CannotConnectNowError|too many clients already|InvalidCatalogNameError|asyncpg.exceptions.ConnectionFailureError|TooManyConnectionsError" /tmp/v1019-xdist-spike.log
```

Result: **2453** (see Section 3 for breakdown).

### Reproducibility

To re-run this spike against a fresh stack:

1. `docker compose ps db` — confirm `geolens-db-1` healthy on `127.0.0.1:5434`
2. `ls /Users/ishiland/Code/geolens/.env.test` — confirm env file exists
3. Start the background sampler (exact command above) → note PID
4. Run the xdist suite (exact command above)
5. Kill sampler once pytest exits: `kill <PID>`
6. Analyze `/tmp/pgstat-xdist.log` and `/tmp/v1019-xdist-spike.log`

---

## Section 2 — Observed numbers

| Metric                                               | Value                                               |
|------------------------------------------------------|-----------------------------------------------------|
| `postgres_max_connections`                           | **30**                                              |
| xdist worker count (`-n auto`)                       | **16** (gw0..gw15, all 16 seen in `pg_stat_activity`) |
| per-worker pool ceiling (`pool_size + max_overflow`) | **7** (5 + 2, `backend/tests/conftest.py:354-360`) |
| per-worker peak concurrent conn (observed)           | **4** (gw4 at 21:39:31 snapshot)                   |
| total peak concurrent conn (observed post-recovery)  | **29** (row-sum at 21:39:31; total query blank — Postgres in recovery) |
| total peak (pre-recovery, last clean snapshot)       | **27** (total=27 at 21:39:26 snapshot)              |
| theoretical peak (`workers × per-worker pool`)       | **112** (16 × 7)                                    |
| headroom at observed post-recovery peak              | **1** (30 − 29)                                     |
| cascade reproduction confirmed                       | **YES** — 628 TooManyConnectionsError, 1824 CannotConnectNowError, 1 InvalidCatalogNameError |

### Timeline reconstruction from `/tmp/pgstat-xdist.log`

| Time     | Event                                                                                         |
|----------|-----------------------------------------------------------------------------------------------|
| 21:38:43 | Sampler starts. Workers initializing. `total=0` (no test-DB activity yet).                    |
| 21:38:58 | Still `total=0`. Workers creating per-worker test DBs and running migrations.                 |
| 21:39:05 | 4 workers appear briefly (`gw0=1, gw4=1, gw6=1, gw7=1`). Postgres immediately enters recovery mode — `total` query returns blank for next 10 consecutive 2s samples. |
| 21:39:05–21:39:23 | **8 consecutive recovery-mode samples.** Postgres accepting no new connections. All 16 workers hammering `pool_timeout=30s` queue. `TooManyConnectionsError` + `CannotConnectNowError` cascading. |
| 21:39:26 | Postgres back online. **Snapshot: total=27, 13 workers active, per-worker max=3 (gw0, gw11, gw9).** |
| 21:39:31 | **Snapshot: row-sum=29, 15 workers active, gw4=4 connections.** `total` query still blank (secondary recovery or Postgres not fully stable). |
| 21:39:34 | `total=21` — connections draining. Workers finishing tests and disposing engines.              |
| 21:39:36 | `total=0`, only `gw14=2` visible. Run complete; engines being disposed.                       |

### Note on observed vs theoretical peak

The sampler's 2-second granularity missed the exact moment max_connections=30 was breached
(the `total=` blank entries confirm Postgres was in recovery mode during that window). The
pre-cascade peak was certainly ≥30 because Postgres cannot enter recovery mode (OOM-style
connection overflow) without first hitting `max_connections`. The observed 29-connection row-sum
at 21:39:31 is a POST-cascade snapshot while connections were being re-established after Postgres
recovered.

---

## Section 3 — Cascade reproduction

**YES — cascade definitively reproduced.**

```
grep -c "TooManyConnectionsError"    /tmp/v1019-xdist-spike.log  →  628
grep -c "CannotConnectNowError"      /tmp/v1019-xdist-spike.log  →  1824
grep -c "InvalidCatalogNameError"    /tmp/v1019-xdist-spike.log  →  1
grep -c "ConnectionFailureError"     /tmp/v1019-xdist-spike.log  →  0
Total cascade-error lines:                                        →  2453
```

Final test summary: `2 failed, 1669 passed, 23 skipped, 1369 errors in 41.13s`

The 1369 errors are all asyncpg cascade errors — not test logic failures. Of 3062 collected
items, 1369 (~45%) errored due to the connection fan-out cascade. This is a severe, consistent
failure, not an intermittent flake. The run completed in 41s (vs sequential 539s) but with
only 1669/3062 tests passing — the cascade rendered the parallel run largely useless.

---

## Section 4 — Three fix shapes (analysis)

### Shape (a): Per-worker pool sizing in `backend/tests/conftest.py`

**Mechanism:** Read `PYTEST_XDIST_WORKER` env var at `client` fixture creation time. If running
under xdist (`worker_id != "master"`), use a smaller pool. If sequential, keep current sizing.

**Math:**
```
safe_total = max_connections − admin_headroom = 30 − 4 = 26
per_worker_safe = floor(26 / 16) = 1
```
With `pool_size=1, max_overflow=0`: `16 × 1 = 16 connections` — 14 below the ceiling.
With `pool_size=1, max_overflow=1`: `16 × 2 = 32 connections` — exceeds ceiling by 2 (risky).

Recommendation: `pool_size=1, max_overflow=0` for xdist workers.

**Trade-offs:**
- Pros: Smallest blast radius (one file, conftest-only). Scales naturally per host — the
  formula `floor((max_connections - headroom) / worker_count)` adapts to different
  `max_connections` values if ever bumped. Sequential mode uses existing 5+2 sizing (no change).
  Does not require container restart or Makefile coordination.
- Cons: `pool_size=1` serializes any test that attempts multiple concurrent DB operations within
  one test function. Existing tests are async and use `override_get_db` which opens a single
  session per request — `pool_size=1` is sufficient for single-request test patterns. Any future
  test that creates multiple concurrent connections within a single test will fail with a pool
  exhaustion error (surfaced as `TimeoutError` after `pool_timeout=30s`) rather than a silent
  data race — this is preferable to the current silent cascade.
- Touch surface: `backend/tests/conftest.py` lines 354-360 + import of `os.environ` already
  present in conftest.

### Shape (b): `max_connections` bump in `db/postgresql.conf`

**Mechanism:** Raise `max_connections` from 30 to a value that accommodates 16 workers × 7
connections + production margin.

**Math:**
```
target = ceil(16 × 7 × 1.2) = 134 → round to 150
```
With `max_connections=150`: `16 × 7 = 112 theoretical peak` — 38 below new ceiling.

**Trade-offs:**
- Pros: No change to test code. `-n auto` runs safely without conftest logic.
- Cons: `postgresql.conf` is a shared config — the `max_connections=30` setting was deliberately
  sized by PERF-05 (Phase 274) for the v13.13 production worst-case envelope (API=16 + Worker=13
  + Admin=1 = 30). Bumping to 150 on the dev container perturbs that envelope and makes
  local dev diverge from production sizing. The `shared_buffers=512MB` setting was tuned for
  max_connections=30; Postgres reserves ~400B per connection in shared memory — 150 connections
  adds ~48KB overhead (negligible) but the logical separation of concerns is broken. Requires
  `docker compose up -d --build db` (rebuild the db image) to apply the new conf. Also does NOT
  fix the fan-out if a CI environment has a different Postgres container with max_connections=30
  — the fix is not portable.
- Touch surface: `db/postgresql.conf:11` + docker rebuild.

### Shape (c): Cap `-n` in `Makefile` / CI invocation

**Mechanism:** Add a `test-parallel` Make target that runs `pytest -n 4` instead of `pytest -n auto`.

**Math:**
```
-n 4:  4 × 7 = 28 connections — 2 below ceiling (barely safe)
-n 8:  8 × 7 = 56 connections — 26 over ceiling (still triggers cascade)
-n 3:  3 × 7 = 21 connections — 9 below ceiling (safe with headroom)
```
`-n 4` is the maximum cap that stays under max_connections=30 with the current pool_size=7.

**Trade-offs:**
- Pros: Simple — one line in Makefile. No conftest or postgresql.conf changes.
- Cons: Masks the underlying contention instead of fixing it. A developer running
  `pytest -n auto` directly (outside Make) still triggers the cascade. On a 16-core host,
  `-n 4` uses 25% of available parallelism — significant speed regression. The fix is fragile:
  if `pool_size` or `max_overflow` changes in conftest without updating the Makefile cap, the
  cascade returns silently. Does not satisfy TD-10's intent of making `-n auto` reliable.
- Touch surface: `Makefile` (new target) — optionally `pyproject.toml` addopts if `-n` default
  is forced globally, but that would break `-n auto` invocations outside Make.

---

## Section 5 — Chosen fix shape

**Chosen shape: (a) — per-worker pool sizing in `backend/tests/conftest.py`**

The measured numbers confirm the cascade is severe (2453 cascade error lines, 45% test error
rate) and that the root cause is the fan-out of 16 workers × 7-connection pool exceeding
max_connections=30. Shape (a) fixes the problem at its source — the pool sizing — without
touching the production Postgres configuration (shape b) or masking the issue with a reduced
worker cap that leaves direct `pytest -n auto` invocations broken (shape c). With `pool_size=1,
max_overflow=0` per xdist worker, the total connection ceiling is 16 × 1 = 16, giving 14
connections of headroom below `max_connections=30` — well clear of the 30-connection ceiling
even accounting for 4 admin/teardown connections. Sequential mode (`PYTEST_XDIST_WORKER=master`
or unset) retains the existing `pool_size=5, max_overflow=2` sizing unchanged.

**Plan 02 will touch:** `backend/tests/conftest.py` (lines 354-360 — `create_async_engine` call
inside the `client` fixture; add `PYTEST_XDIST_WORKER`-conditional pool sizing).

---

## Section 6 — Sequential-mode invariant

The chosen fix (shape a) MUST NOT break `uv run pytest backend/tests/` (sequential mode).

**How the fix preserves sequential mode:**

The `client` fixture already reads `PYTEST_XDIST_WORKER` via the module-level `_WORKER_ID`
constant (conftest.py:22) and `pytest_configure` hook (conftest.py:25-40). In sequential mode,
`PYTEST_XDIST_WORKER` is unset — the env var defaults to `"master"`. Plan 02 will gate the
pool-size reduction on `worker_id not in ("master", None)`, keeping `pool_size=5, max_overflow=2`
for all sequential invocations:

```python
_worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
_is_xdist_worker = _worker_id != "master"
pool_size = 1 if _is_xdist_worker else 5
max_overflow = 0 if _is_xdist_worker else 2
```

**Regression pin Plan 02 will add:**

A small `tests/test_conftest_pool_sizing.py` unit test that:
1. With `PYTEST_XDIST_WORKER` unset (or `"master"`): asserts that the effective pool sizing
   resolves to `pool_size=5, max_overflow=2` (sequential mode unchanged).
2. With `PYTEST_XDIST_WORKER=gw0`: asserts that the effective pool sizing resolves to
   `pool_size=1, max_overflow=0` (xdist mode reduced).

This test is pure-unit (no DB required) and runs in both sequential and xdist modes, pinning the
conditional logic so a future refactor of conftest cannot silently revert the pool ceiling fix.

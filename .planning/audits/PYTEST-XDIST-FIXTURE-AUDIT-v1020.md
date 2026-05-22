---
captured: 2026-05-22
milestone: v1020
phase: 1087-fixture-isolation-spike-taxonomy
plan: 01
requirement: FI-01
host: macOS darwin/arm64 (Apple M4 Max, 16-core)
worker_count_under_n_auto: 16
worker_count_visible_in_pg_stat_activity: 15
postgres_max_connections: 30
head_sha: d340c22e582b0c8713a6f9f2721467282e2a9550
sequential_baseline: "3036 passed / 0 failed / 38 skipped / 14 deselected in 539.74s"
parallel_run_summary: "89 failed / 2401 passed / 27 skipped / 560 errors in 269.12s"
parallel_run_total_testcases: 3076
sampling_strategy: A (background pg_stat_activity sampler, 2s resolution)
total_failures_classified: 648
total_cascade_error_lines_in_log: 2203
---

# pytest -n auto xdist Spike — Fixture-Isolation Failure Taxonomy

This is the v1020 spike doc, sister to `.planning/audits/PYTEST-XDIST-SPIKE-v1019.md`. The
v1019 spike measured + fixed the asyncpg connection cascade (`TooManyConnectionsError` /
`CannotConnectNowError` at 2453 lines) via NullPool + 5s startup stagger; this v1020 spike
measures the residual `pytest -n auto` failures on the post-v1019 HEAD (commit
`d340c22e`) and classifies them by root cause to drive Phase 1088 fix sequencing.

**Key finding (Sections 2–5):** The 192-failure estimate from v1019 close-gate was a
lower bound. Measurement against HEAD `d340c22e` produces **648 failures + errors** under
`pytest -n auto` (89 failed / 560 errors out of 3076 collected). The single dominant root
cause (407 of 648 = 62.8%) is a **per-worker `_test_db_lifecycle` session-fixture race on
gw15** — gw15's setup raced concurrent connection contention, the DB was never created,
and 407 downstream tests on that worker all failed with
`asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_…" does not exist`.
The remaining 239 cascade errors (TooManyConnections at setup, teardown, in-test) are the
proximate symptom of concurrent fixture-setup demand still exceeding `max_connections=30`
even with the v1019 TD-10 stagger + NullPool fixes in place.

None of the four v1019-era hypothesis categories (Redis singleton state, storage provider
override, `app.dependency_overrides` leak, autouse-fixture coupling) reproduced in this
measurement run — Section 4 documents each as "0 failures observed; hypothesis not
reproduced" for traceability. The hypothesis miss informs Phase 1088 sequencing (Section 5):
the per-worker DB lifecycle race is the only category that needs structural fixture work;
the three TooManyConnections cascade categories may resolve once the gw15 lifecycle race
is fixed (per-worker setup is no longer fighting for connections), making the v1020 fix
strategy a single-category close rather than a four-category sweep.

## Section 1 — Measurement methodology

**Sampling strategy chosen:** A — background `pg_stat_activity` sampler running in a
separate subshell polling Postgres every 2 seconds while the xdist suite ran in a second
terminal. Identical shape to v1019 Section 1.

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

Confirmed: `db/postgresql.conf:11` is the active Postgres configuration ceiling — unchanged
from v1019. The `max_connections` bump is OUT OF SCOPE for v1020 per REQUIREMENTS.md.

### Step 1b: Stale per-worker test DB cleanup

Prior xdist runs leave per-worker test DBs in Postgres if teardown is skipped or interrupted.
v1020 measurement begins with the `geolens` DB clean of `geolens_test_gw%` / `geolens_test_master%`
remnants:

```bash
# List stale DBs
docker compose exec -T db psql -U geolens -d geolens -At -c "SELECT datname FROM pg_database WHERE datname LIKE 'geolens%test_gw%' OR datname LIKE 'geolens%test_master%';"

# Drop each (idempotent — IF EXISTS prevents errors on already-dropped names)
while read -r db; do
  [ -z "$db" ] && continue
  echo "DROP DATABASE IF EXISTS \"$db\";"
done < /tmp/v1020-stale-dbs.txt > /tmp/v1020-drop-stale-dbs.sql
docker compose exec -T db psql -U geolens -d geolens < /tmp/v1020-drop-stale-dbs.sql
```

For this measurement run, the cleanup removed **183 stale per-worker DBs** from prior
xdist sessions before the measurement started. This step is REQUIRED for reproducibility —
running `pytest -n auto` against a Postgres with 183+ stale per-worker DBs starts the
measurement window in a state that is not representative of a clean stack and can perturb
the connection-cascade timing.

### Step 2: Sequential baseline re-verify

```bash
cd /Users/ishiland/Code/geolens/backend && env $(grep -v '^#' /Users/ishiland/Code/geolens/.env.test | xargs) \
  uv run pytest tests/ 2>&1 | tee /tmp/v1020-sequential-baseline.log
```

Result: `3036 passed, 38 skipped, 14 deselected, 18 warnings in 539.74s (0:08:59)`.
`failed == 0` — the v1019 close-gate sequential baseline is intact.

This re-verify is a HARD GATE: if `failed > 0`, the spike halts immediately. A broken
sequential baseline would mean the parallel-mode failure count is contaminated by an
unrelated regression. The spike only proceeds against a clean sequential baseline.

### Step 3: Background sampler

The sampler runs in a background subshell appending to `/tmp/v1020-pgstat-sampler.log`
during the full duration of the xdist run:

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
) > /tmp/v1020-pgstat-sampler.log 2>&1 &
SAMPLER_PID=$!
```

Sampling resolution: 2 seconds. Limitation: Postgres recovery-mode samples surface as a
blank `total=` line (4 such samples in this run — captured but ignored for peak counting).

### Step 4: xdist suite run with JUnit XML

```bash
cd /Users/ishiland/Code/geolens/backend && env $(grep -v '^#' /Users/ishiland/Code/geolens/.env.test | xargs) \
  uv run pytest -n auto --junitxml=/tmp/v1020-junit.xml tests/ 2>&1 | tee /tmp/v1020-xdist-fixture-spike.log
```

The `--junitxml=/tmp/v1020-junit.xml` flag is REQUIRED — Section 3's failure inventory
consumes JUnit's `<testcase>` elements to extract every failing node-ID with its
exception class. Wall clock: 269.12s. Final summary line: `89 failed, 2401 passed, 27
skipped, 4 warnings, 560 errors in 269.12s`.

After pytest exits, kill the sampler: `kill $SAMPLER_PID`.

### Step 5: Failure extraction (Python helper, JUnit XML parser)

The Section 3 inventory is built from the JUnit XML, not from grepping the tee'd log
(which would miss parametrized test variants and conflate setup/teardown errors with
in-test failures). The parser MUST prepend `backend/` to the path component when
synthesizing the pytest node-ID because pytest's rootdir is `backend/` (per
`backend/pyproject.toml` `testpaths = ["tests"]`) and JUnit's `classname` is rootdir-relative:

```python
import xml.etree.ElementTree as ET, json
root = ET.parse('/tmp/v1020-junit.xml').getroot()
out = []
for tc in root.iter('testcase'):
    fail = tc.find('failure')
    err = tc.find('error')
    if fail is None and err is None:
        continue
    node = fail if fail is not None else err
    msg = (node.get('message') or '').strip()
    text = (node.text or '').strip()
    first_line = msg.split('\n')[0] if msg else text.split('\n')[0]
    classname = tc.get('classname', '')
    name = tc.get('name', '')
    # JUnit classname is dotted, rootdir-relative.
    # class form:    tests.test_x.TestY  -> backend/tests/test_x.py::TestY::test_name
    # function form: tests.test_x        -> backend/tests/test_x.py::test_name
    # MUST prepend backend/ so downstream consumers (regex, Section 3 row matcher,
    # audit cross-reference) see the full path.
    if '.' in classname:
        parts = classname.split('.')
        if parts[-1] and parts[-1][0].isupper():
            cls = parts[-1]
            path = 'backend/' + '/'.join(parts[:-1]) + '.py'
            node_id = f"{path}::{cls}::{name}"
        else:
            path = 'backend/' + '/'.join(parts) + '.py'
            node_id = f"{path}::{name}"
    else:
        if classname.startswith('tests'):
            node_id = f"backend/{classname}::{name}" if name else f"backend/{classname}"
        else:
            node_id = f"{classname}::{name}" if classname else name
    err_class = first_line.split(':')[0].strip() if ':' in first_line else first_line[:80]
    out.append({
        'node_id': node_id,
        'error_class': err_class,
        'snippet': first_line[:200],
        'is_error': err is not None,
    })
# Persist to /tmp/v1020-failure-inventory.json (or stdout)
print(json.dumps(out, indent=2))
```

Sanity gate immediately after parsing:

```bash
python3 -c "import json; d=json.load(open('/tmp/v1020-failure-inventory.json')); n=sum(1 for x in d if x['node_id'].startswith('backend/tests/')); assert n>0, f'expected backend/tests/ prefix; got {n}'; print(f'PASS: {n} / {len(d)} use backend/tests/ prefix')"
```

For this run: `PASS: 648 / 648 use backend/tests/ prefix`.

### Reproducibility

To re-run this spike against a fresh stack:

1. `docker compose ps db` — confirm `geolens-db-1` healthy on `127.0.0.1:5434`
2. `ls /Users/ishiland/Code/geolens/.env.test` — confirm env file exists
3. `git rev-parse HEAD` — record the SHA being measured against
4. `SHOW max_connections` — confirm 30 (unchanged from v1019)
5. Drop stale per-worker test DBs (Step 1b above) — a freshly-cleaned DB is required for
   representative cascade timing
6. Run sequential baseline (Step 2) — assert `failed == 0` before proceeding
7. Start the background sampler (Step 3) — note PID
8. Run the xdist suite with JUnit XML (Step 4)
9. Kill sampler once pytest exits: `kill <PID>`
10. Run the Python JUnit XML parser (Step 5) to produce the per-failure inventory
11. Analyze `/tmp/v1020-pgstat-sampler.log` and `/tmp/v1020-xdist-fixture-spike.log`

### Determinism

`pytest-randomly` is **NOT installed** in this project (verified via `grep pytest-randomly
backend/pyproject.toml` → no match). Test order is collection-order (file alphabetical +
intra-file definition order); no random seed is involved. xdist worker-to-test assignment
is dispatcher-controlled (`pytest-xdist`'s default `LoadScheduling`) — across two runs
against the same HEAD, the per-worker assignment may differ if any test or fixture
collection timing differs. **The 407 InvalidCatalogName failures observed on gw15 in this
run reflect the specific worker that lost the setup race; in a different run, a different
worker may lose the race — but the failure shape (one full worker's tests fail with
`InvalidCatalogNameError`) is expected to persist as long as the underlying lifecycle race
is unfixed.**

### Stability declaration

**Single-run measurement; stability across runs not validated in this spike — Phase 1090
HYG-02 flake hunt is the verification step for this assumption. A category that turns out
to be a transient flake will be reclassified by Phase 1090's per-test KEEP/FIX/REMOVE
disposition.**

Within this single measurement, no second `pytest -n auto` run was performed against the
same HEAD; the audit's category counts are point-in-time and reflect the specific
worker-to-test assignment + connection-contention timing of the 14:36–14:40 measurement
window. Phase 1088 fixes that depend on category counts being stable across runs should
treat the gw15 lifecycle race as the structural defect (not the specific worker number);
the 239 cascade-error subcategories may shift in count across runs even at unfixed HEAD.

---

## Section 2 — Measured numbers

| Metric | Value |
|--------|-------|
| HEAD SHA | `d340c22e582b0c8713a6f9f2721467282e2a9550` |
| `postgres_max_connections` | **30** (unchanged — production envelope per PERF-05 / Phase 274) |
| xdist worker count claimed (`-n auto`) | **16** (gw0..gw15 — "created: 16/16 workers" from xdist startup line) |
| xdist worker count visible in `pg_stat_activity` | **15** (gw0..gw14 — gw15's session-fixture failed before it opened any test-DB connection visible to the sampler) |
| Sequential baseline (re-verify) | **3036 passed / 0 failed / 38 skipped / 14 deselected in 539.74s** — matches v1019 close-gate (`failed == 0` floor satisfied) |
| Parallel run wall clock | **269.12s** (≈4.5 min vs sequential 9 min — 2× speedup despite cascade) |
| Parallel run total testcases | **3076** (from JUnit XML root `<testsuite tests="3076" ...>`) |
| Parallel run failures + errors | **648** (from JUnit XML — 89 `<failure>` + 559 `<error>`; matches log summary `89 failed, 560 errors` with 1 testcase having both nodes due to setup+teardown both erroring) |
| Per-worker peak concurrent conn (observed) | **3** (multiple workers seen at this peak — well below per-worker pool ceiling) |
| Total peak concurrent conn (observed) | **17** (well below `max_connections=30`) |
| Recovery-mode samples seen | **4** (sampler `total=` blank lines — narrower window than v1019's 8) |
| Cascade error lines in xdist log | **2203** (grep for `asyncpg.exceptions.CannotConnectNowError\|too many clients already\|InvalidCatalogNameError\|asyncpg.exceptions.ConnectionFailureError\|TooManyConnectionsError`) |

### Per-category breakdown

| Category | Failure count | % of total |
|----------|---------------|------------|
| per-worker DB lifecycle race (gw15 setup failed) | 407 | 62.8% |
| setup-phase connection contention (TooManyConnections during fixture setup) | 150 | 23.1% |
| in-test connection contention (TooManyConnections inside test body) | 87 | 13.4% |
| teardown-phase connection contention (TooManyConnections during fixture teardown) | 2 | 0.3% |
| sandbox subsystem error (non-cascade) | 1 | 0.2% |
| assertion failure (test logic — needs case-by-case inspection) | 1 | 0.2% |

**Total failures:** 648

### Sequential baseline confirmation

Sequential pytest at HEAD `d340c22e` = `3036 passed, 38 skipped, 14 deselected, 18 warnings
in 539.74s`. Floor: `failed == 0` (v1019 close-gate semantics). Reference baseline at v1019
close was `3036 / 0 / 38` (matches exactly; no variance in this run). Only `failed > 0`
would be fatal (would have halted in Task 1 of Plan 1087-01 before proceeding to parallel
measurement). The hard floor for v1020 is `failed == 0`, not the literal 3036 number.

### Variance from v1019 close-gate estimate

The v1019 close-gate carry-forward note (`memory/MEMORY.md` and `STATE.md`) cited
**192 fixture-scope pytest failures exposed by `-n auto` parallelism**. This v1020
spike measures **648**. The variance has two contributing factors:

1. **Different worker losing the race produces a different downstream count.** In v1019
   close, the worker that lost the lifecycle race may have been assigned fewer tests
   (xdist's `LoadScheduling` is dispatcher-controlled; per-worker test count depends on
   collection ordering + completion timing of earlier tests). In v1020's measurement,
   gw15 was assigned 407 tests by the time it tried to run, and all 407 failed with
   `InvalidCatalogNameError`. v1019's count of 192 is plausible if a different worker
   with ~70 tests assigned lost the race + the 122 cascade subcategory count was about
   right.
2. **Cascade subcategory counts shift with timing.** The 239 TooManyConnections cascade
   errors (setup/teardown/in-test) are correlated with concurrent fixture-setup demand;
   small timing differences in the staggered-startup window perturb the count.

Both contributors reinforce the Phase 1090 HYG-02 stability gate: a flake hunt across
3 consecutive `-n auto` runs will measure the true mean failure count. For Phase 1088
fix sequencing, the structural category (per-worker DB lifecycle race) is invariant —
its count varies but its existence does not.

---

## Section 3 — Failure inventory

One Markdown row per failing testcase. 648 rows total (matches `total_failures_classified`
in frontmatter and `len(/tmp/v1020-failure-inventory.json)`). Both class-form
(`path::Class::test_name`) and function-form (`path::test_name`) node-IDs accepted; this
project's backend test suite is majority class-form.

| Node-ID | Category | Error class | Snippet |
|---------|----------|-------------|---------|
| `backend/tests/test_download_token.py::TestDownloadTokenEndpoint::test_download_token_private_non_owner` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_jobs_router.py::TestGetJobStatus::test_get_job_surfaces_temporal_parse_errors` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_maps.py::TestCreateMap::test_create_map_as_viewer_forbidden` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_features_crud.py::TestInsertFeature::test_insert_feature` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_features_crud.py::TestInsertFeature::test_insert_feature_wrong_geometry_type` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_jobs_router.py::TestGetJobStatus::test_get_job_surfaces_legacy_collision_warning_message` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_features_crud.py::TestInsertFeature::test_insert_feature_viewer_forbidden` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_features_crud.py::TestReplaceFeature::test_replace_feature` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_features_crud.py::TestUpdateFeature::test_update_feature_geometry_only` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestShareToken::test_share_expiration_requires_enterprise` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_maps.py::TestShareToken::test_share_expiration_allowed_in_enterprise` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_maps.py::TestShareToken::test_share_idempotent` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_layers.py::TestCreateLayerValidation::test_create_layer_invalid_geometry_type` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_maps.py::TestShareToken::test_revoke_share_token` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestShareToken::test_revoke_share_no_token` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestShareToken::test_share_map_not_found` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestShareToken::test_share_viewer_forbidden` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestShareToken::test_get_share_token_non_owner_forbidden` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestShareToken::test_admin_revoke_share_token_cascades_embed_tokens` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestSharedMap::test_get_shared_map_success` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestSharedMap::test_get_shared_map_includes_basemap_config` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestSharedMap::test_get_shared_map_invalid_token` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestSharedMap::test_get_shared_map_revoked_token` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestSharedMap::test_get_shared_map_expired_token` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestMapLayers::test_add_layer` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_column_ddl_idor.py::test_drop_column_owner_returns_200` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_maps.py::TestMapLayers::test_add_layer_assigns_next_sort_order_when_omitted` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestMapLayers::test_add_layer_duplicate_dataset_omitted_order_stays_distinct` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestMapLayers::test_add_layer_map_not_found` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestMapLayers::test_remove_layer` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_layers.py::TestCreateLayerValidation::test_create_layer_invalid_column_name_uppercase` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_layers.py::TestCreateLayerValidation::test_create_layer_invalid_column_type` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_maps.py::TestMapLayers::test_remove_layer_not_found` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestMapLayers::test_remove_layer_rejects_layer_outside_map` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestMapLayers::test_add_layer_viewer_forbidden` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ensure_geom_column.py::TestEnsureGeomColumn::test_noop_for_non_spatial_table` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_maps.py::TestMapLayers::test_remove_layer_viewer_forbidden` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestMapLayers::test_add_layer_with_custom_style` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestMapLayers::test_add_layer_moves_legacy_builder_paint_to_style_config` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestMapLayers::test_add_layer_rejects_unknown_private_paint_key` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_layers.py::TestCreateLayerSearchable::test_create_layer_is_searchable` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_maps.py::TestMapLayers::test_add_layer_default_polygon_style_uses_style_config` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestMapLayers::test_update_map_layers_moves_legacy_builder_paint_to_style_config` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestMapLayers::test_patch_map_layers_applies_diff_and_preserves_stable_ids` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_export.py::TestExportAuth::test_export_dataset_not_found` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_maps.py::TestMapLayers::test_map_layers_patch_rejects_layer_outside_map` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestMapLayers::test_full_replacement_still_recreates_layers` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestMapLayersTrailingSlash::test_add_layer_with_trailing_slash` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestMapLayersTrailingSlash::test_add_layer_slash_variants_parity` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestMapLayersTrailingSlash::test_patch_layers_with_trailing_slash` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestMapThumbnail::test_upload_thumbnail` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestMapThumbnail::test_upload_thumbnail_bumps_updated_at` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestMapThumbnail::test_get_thumbnail_after_upload` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestMapThumbnail::test_get_thumbnail_not_found` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestMapThumbnail::test_upload_thumbnail_viewer_forbidden` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestMapThumbnail::test_upload_thumbnail_unauthenticated` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestSearchSortFilterAuthor::test_list_maps_search_by_name` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_audit_column_ddl_feed.py::test_query_column_ddl_history_returns_total_count` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_maps.py::TestSearchSortFilterAuthor::test_list_maps_search_by_description` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestSearchSortFilterAuthor::test_list_maps_sort_by_name_asc` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_maps.py::TestSearchSortFilterAuthor::test_list_maps_sort_by_created_at_desc` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestSearchSortFilterAuthor::test_list_maps_visibility_filter_public` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_maps.py::TestSearchSortFilterAuthor::test_list_maps_visibility_filter_private` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_collections.py::TestCollectionExtent::test_collection_extent_mixed_null_and_present_spatial_extent` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_maps.py::TestSearchSortFilterAuthor::test_list_maps_created_by_username` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestSearchSortFilterAuthor::test_list_maps_created_by_username_null_deleted_user` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_export.py::TestExportVisibility::test_export_public_dataset_accessible` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_maps.py::TestSearchSortFilterAuthor::test_list_maps_invalid_sort_by_rejected` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestSearchSortFilterAuthor::test_search_resets_total_count` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestVisibilityCheck::test_visibility_check_empty_map` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps_search_ilike_escape.py::TestSecFu07IlikeEscape::test_sec_fu_07_combined_escape` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_maps.py::TestVisibilityCheck::test_visibility_check_not_found` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestUpdateShareToken::test_patch_share_token_set_expiration` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestListMaps::test_list_maps_as_editor_sees_own` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_maps.py::TestUpdateShareToken::test_patch_share_token_remove_expiration` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestUpdateShareToken::test_patch_share_token_add_expiration_to_never_expires` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_maps.py::TestUpdateShareToken::test_patch_share_token_no_token_404` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_audit_column_ddl_feed.py::test_query_column_ddl_history_pagination` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_maps.py::TestUpdateShareToken::test_patch_share_token_viewer_forbidden` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestUpdateShareToken::test_patch_share_token_preserves_token_string` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestAdminShareTokenListing::test_admin_list_share_tokens` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestAdminShareTokenListing::test_admin_search_share_tokens` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestAdminShareTokenListing::test_admin_filter_share_tokens_by_status` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestListMaps::test_list_maps_unauthenticated` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_maps.py::TestAdminShareTokenListing::test_admin_filter_invalid_status_rejected` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_maps.py::TestAdminShareTokenListing::test_admin_share_tokens_requires_admin` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestDatasetMaps::test_dataset_maps_admin_sees_all` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestDatasetMaps::test_dataset_maps_user_sees_own_internal_public` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_oauth.py::TestOAuthProviderCRUD::test_create_provider_encrypts_secret` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_oauth.py::TestOAuthProviderCRUD::test_get_provider_by_slug` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_oauth.py::TestOAuthProviderCRUD::test_get_provider_by_slug_not_found` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_oauth.py::TestOAuthProviderCRUD::test_update_provider_re_encrypts_secret` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_oauth.py::TestOAuthProviderCRUD::test_delete_provider` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_oauth.py::TestOAuthProviderCRUD::test_list_enabled_providers` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_oauth.py::TestOAuthProviderCRUD::test_crud_lifecycle` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_oauth.py::TestOAuthProviderCRUD::test_encryption_roundtrip_in_crud` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_oauth.py::TestFindOrCreateOAuthUser::test_auto_create_user` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_features_geojson_z.py::TestGetFeaturesGeoJSONZService::test_uses_cached_feature_count_when_not_truncated` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_oauth.py::TestFindOrCreateOAuthUser::test_email_linking` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_oauth.py::TestFindOrCreateOAuthUser::test_email_linking_blocked_when_email_unverified_with_collision` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_oauth.py::TestFindOrCreateOAuthUser::test_email_linking_blocked_when_email_verified_missing` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_oauth.py::TestFindOrCreateOAuthUser::test_unverified_email_no_collision_creates_user_without_email` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_oauth.py::TestFindOrCreateOAuthUser::test_existing_oauth_link_returns_user` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_oauth.py::TestFindOrCreateOAuthUser::test_group_role_mapping_community_uses_default_role` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_oauth.py::TestFindOrCreateOAuthUser::test_group_role_mapping_enterprise_applies_mapping` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_oauth.py::TestFindOrCreateOAuthUser::test_username_collision_handled` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_oauth.py::TestOAuthLoginEndpoint::test_oauth_login_redirect` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_oauth.py::TestOAuthLoginEndpoint::test_oauth_login_not_found` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_oauth.py::TestOAuthCallbackCSRF::test_callback_missing_state_returns_error` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_oauth.py::TestOAuthCallbackCSRF::test_callback_invalid_code_returns_error` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_oauth.py::TestOAuthProvidersEndpoint::test_list_enabled_providers` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_collection_metadata.py::test_collection_has_spatial_extent` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_collection_metadata.py::test_collection_has_temporal_extent` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_config_ops.py::test_validate_connectivity` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_ogc_collection_metadata.py::test_collection_has_summaries` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_collection_metadata.py::test_collection_anonymous_sees_only_public_extent` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_collection_metadata.py::test_collection_empty_catalog_returns_gracefully` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_collection_metadata.py::test_collection_links_are_absolute` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_collection_metadata.py::test_list_collections_includes_dynamic_metadata` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_collection_metadata.py::test_collection_temporal_open_ended` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_collections.py::TestCollectionVisibility::test_collection_datasets_respects_visibility` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_ogc_collection_metadata.py::test_per_dataset_collection_has_extent_in_list` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_export.py::TestExportValidation::test_export_invalid_target_crs` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_ogc_collection_metadata.py::test_per_dataset_collection_has_root_link_in_list` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_collection_metadata.py::test_per_dataset_collection_detail_has_temporal_extent` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_cql2_filtering.py::test_cql2_text_equality_filter` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_cql2_filtering.py::test_cql2_text_comparison_filter` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_cql2_filtering.py::test_cql2_text_like_filter` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_cql2_filtering.py::test_cql2_json_equality_filter` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_cql2_filtering.py::test_cql2_json_logical_and` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_cql2_filtering.py::test_cql2_invalid_expression_returns_400` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_ogc_cql2_filtering.py::test_cql2_unsupported_filter_lang_returns_400` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_cql2_filtering.py::test_cql2_default_filter_lang_is_text` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_export.py::TestExportValidation::test_export_non_spatial_dataset_spatial_format` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_ogc_cql2_filtering.py::test_cql2_pagination_preserves_filter` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_cql2_filtering.py::test_cql2_pagination_preserves_non_default_filter_lang` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_cql2_filtering.py::test_cql2_filter_respects_visibility` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_discovery.py::test_landing_page_returns_200_without_auth` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_discovery.py::test_landing_page_links_are_absolute` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_discovery.py::test_landing_page_service_doc_link` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_discovery.py::test_landing_page_openapi_link` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_discovery.py::test_landing_page_f_json_accepted` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_discovery.py::test_landing_page_f_unsupported_returns_400` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_discovery.py::test_conformance_returns_200_without_auth` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_discovery.py::test_conformance_contains_required_classes` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_discovery.py::test_conformance_contains_records_classes` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestLayerTypeRoundTrip::test_layer_type_round_trip_get` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_ogc_discovery.py::test_conformance_f_json_accepted` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_discovery.py::test_conformance_f_unsupported_returns_400` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ingest.py::TestUpload::test_upload_rejects_bad_extension` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_ogc_discovery.py::test_ogc_record_includes_conforms_to` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_discovery.py::test_health_still_works` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_features.py::test_collections_includes_dataset_collections` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_features.py::test_get_dataset_collection_metadata` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_features.py::test_collection_not_found` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_features.py::test_get_collection_items` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_enrichment.py::test_record_has_no_bbox_when_no_extent` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_enrichment.py::test_record_links_include_self_collection_root` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_enrichment.py::test_record_links_are_absolute_urls` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_enrichment.py::test_self_link_points_to_record` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_enrichment.py::test_collection_link_points_to_collection` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_enrichment.py::test_root_link_points_to_root` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_enrichment.py::test_collection_items_response_has_links` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_enrichment.py::test_conformance_includes_records_core` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestLayerTypeRoundTrip::test_layer_type_auto_detect_via_put` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_ogc_record_enrichment.py::test_existing_record_fields_preserved` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_enrichment.py::test_record_has_distributions_list` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_enrichment.py::test_record_distributions_empty_when_none` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_enrichment.py::test_record_has_lineage` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_enrichment.py::test_record_has_update_frequency` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_enrichment.py::test_record_has_constraints` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_enrichment.py::test_record_constraints_null_when_none` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_properties.py::test_record_has_formats_list` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_ogc_record_properties.py::test_record_has_language` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_properties.py::test_record_has_themes_from_theme_category` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_properties.py::test_record_themes_null_when_no_theme_category` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_features_geojson_z.py::TestGetFeaturesGeoJSONZEndpoint::test_rbac_private_dataset_non_owner` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_ogc_record_properties.py::test_record_has_rights_from_license` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_properties.py::test_record_rights_null_when_no_license` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_properties.py::test_record_contacts_from_record_contacts_table` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestLayerTypeRoundTrip::test_layer_type_explicit_override` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_layers.py::TestAddColumn::test_add_column_viewer_forbidden` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_ogc_record_properties.py::test_record_contacts_empty_when_no_contacts` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_properties.py::test_record_has_time_from_vintage` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_embed_tokens.py::TestTileDomainLocking::test_tile_allowed_origin_passes` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_ogc_record_properties.py::test_record_time_with_open_start` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_properties.py::test_record_time_with_open_end` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_properties.py::test_record_time_null_when_no_vintage` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_audit_column_ddl_feed.py::test_column_ddl_feed_pagination` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_ogc_record_properties.py::test_existing_properties_still_present` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_properties.py::test_table_record_formats_excludes_shapefile` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_properties.py::test_vector_record_formats_includes_shapefile` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_password_policy.py::TestRegisterPasswordPolicy::test_register_rejects_weak_password` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_password_policy.py::TestRegisterPasswordPolicy::test_register_accepts_strong_password` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_password_policy.py::TestChangePasswordPolicy::test_change_password_rejects_weak_password` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_datasets.py::TestAnonymousAccess::test_anon_get_validate_public` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_password_policy.py::TestAdminCreateUserPasswordPolicy::test_admin_create_user_rejects_weak_password` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::test_update_map_layers_round_trip_sort_order` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_password_policy.py::TestAdminCreateUserPasswordPolicy::test_admin_create_user_rejects_16_char_single_class` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_permissions.py::TestGetEffectivePermissions::test_get_effective_permissions_defaults` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_layers.py::TestDropColumn::test_drop_column_valid` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_maps.py::TestUpdateMap::test_update_map_non_owner_editor_forbidden` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_permissions.py::TestGetEffectivePermissions::test_get_effective_permissions_override` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_embed_tokens.py::TestTileDomainLocking::test_tile_allowed_origin_passes` | teardown-phase connection contention (TooManyConnections during fixture teardown) | `failed on teardown with "asyncpg.exceptions.TooManyConnectionsError` | failed on teardown with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_permissions.py::TestSettingsIntegration::test_get_put_permissions` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ingest.py::TestRegister::test_register_nonexistent_table` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_permissions.py::TestSettingsIntegration::test_admin_lockout_prevention` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_permissions.py::TestRequirePermission::test_me_permissions_endpoint` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_permissions.py::TestRequirePermission::test_permissions_update_reflected` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_properties.py::test_vector_record_has_no_row_count` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_maps.py::TestShowInLegendRoundTrip::test_new_layer_defaults_show_in_legend_true` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_jobs_router.py::TestRetryJob::test_retry_viewer_forbidden` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_persistent_config.py::test_get_returns_env_default_when_no_db_row` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_persistent_config.py::test_get_returns_db_value_when_row_exists` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_persistent_config.py::test_get_returns_env_default_when_env_only` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_persistent_config.py::test_set_raises_when_env_only` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_record_properties.py::test_table_record_has_column_count` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_persistent_config.py::test_set_creates_audit_log_entry` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_persistent_config.py::test_set_invalidates_cache` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestShowInLegendRoundTrip::test_show_in_legend_round_trip_via_put` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_datasets.py::TestAnonymousAccess::test_anon_get_versions_public` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_persistent_config.py::test_get_uses_cache_with_ttl` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ingest_fan_out.py::TestFanOutEndpoint::test_cloned_jobs_have_correct_metadata` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_persistent_config.py::test_registry_contains_all_declared_instances` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_layers.py::TestDropColumn::test_drop_column_reserved` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_persistent_config.py::test_log_level_side_effect` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_persistent_config.py::test_sync_rate_limit_accessor` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_features_geojson_z.py::TestGetFeaturesGeoJSONZEndpoint::test_truncation_at_5000` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_persistent_config.py::test_get_all_settings_returns_grouped` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_maps.py::TestShowInLegendRoundTrip::test_show_in_legend_defaults_true_when_omitted_in_put` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_datasets.py::TestAnonymousAccess::test_anon_get_history_public` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_ogc_records_conformance.py::test_pagination_uses_prev_rel` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_persistent_config.py::test_put_settings_updates_value_with_audit` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_features_geojson_z.py::TestGetFeaturesGeoJSONZEndpoint::test_truncation_at_5000` | teardown-phase connection contention (TooManyConnections during fixture teardown) | `failed on teardown with "asyncpg.exceptions.TooManyConnectionsError` | failed on teardown with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_persistent_config.py::test_put_settings_returns_403_when_env_only` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_persistent_config.py::test_get_config_mode_reports_env_only` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_manifest_apply_service.py::TestManifestApplyService::test_new_raster_entry_sets_raster_queue_metadata` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_persistent_config.py::test_public_basemaps_endpoint` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_persistent_config.py::test_basemaps_api_key_interpolation` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_export.py::TestExportAudit::test_export_creates_audit_log` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_persistent_config.py::test_basemaps_api_key_unresolved_filtered` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_features.py::test_private_collection_visible_for_admin` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_maps.py::TestImportStyleJsonTerrain::test_import_style_with_top_level_terrain_persists_terrain_config` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_persistent_config.py::test_basemaps_api_key_never_leaked` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_persistent_config.py::test_public_map_defaults_endpoint` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_ingest_fan_out.py::TestFanOutEndpoint::test_title_default_uses_filename_plus_layer` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_persistent_config.py::test_enabled_widgets_endpoint_returns_list` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_persistent_config.py::test_enabled_widgets_roundtrip` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_persistent_config.py::test_enabled_widgets_null_means_all` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_persistent_config.py::test_enabled_widgets_rejects_non_list` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_persistent_config.py::test_enabled_widgets_rejects_empty_strings` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_persistent_config.py::test_enabled_widgets_rejects_non_string_items` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_maps.py::TestUpdateMap::test_update_map_allows_public_with_all_public_datasets` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_maps.py::TestImportStyleJsonTerrain::test_import_style_without_terrain_leaves_terrain_config_null` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_maps.py::TestUpdateMap::test_update_map_public_no_layers_succeeds` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_persistent_config.py::test_cors_matching_origin_gets_headers` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_datasets.py::TestDatasetSubRouterRouting::test_dcat_catalog_not_captured_by_dataset_id` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_persistent_config.py::test_cors_non_matching_origin_no_headers` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_persistent_config.py::test_cors_preflight_returns_200` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_records_conformance.py::test_themes_include_scheme` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_persistent_config.py::test_cors_wildcard_rejected_with_credentials` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_records_conformance.py::test_contacts_include_email_phone` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_jobs_router.py::TestCleanupStaleJobs::test_cleanup_unauthenticated` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_persistent_config.py::test_cors_no_origin_header_no_processing` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_jobs_router.py::TestCleanupStaleJobs::test_cleanup_returns_counts` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_persistent_config.py::test_token_lifetime_from_persistent_config` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_persistent_config.py::test_llm_provider_from_persistent_config` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_persistent_config.py::test_log_level_propagation_via_api` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_persistent_config.py::test_tile_cache_ttl_round_trip` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_persistent_config.py::test_tile_cache_ttl_available_via_persistent_config` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_persistent_config.py::test_bulk_settings_update_creates_per_field_audit_entries` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_persistent_config.py::test_get_validates_unwrapped_value_against_type_adapter` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_persistent_config.py::test_get_falls_back_to_env_default_on_validation_error` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_phase_273_cog_redirect_revalidate.py::test_remote_redirect_blocked_when_ssrf_fails` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_phase_273_cog_redirect_revalidate.py::test_remote_redirect_allowed_when_ssrf_passes` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_phase_273_cog_redirect_revalidate.py::test_remote_redirect_blocked_for_disallowed_scheme` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_embed_tokens.py::TestCreateEmbedToken::test_allowed_origins_require_enterprise` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_phase_273_cog_redirect_revalidate.py::test_local_storage_unaffected_by_ssrf_revalidation` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_phase_273_download_token.py::test_create_download_token_has_typ_and_scope` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_phase_273_download_token.py::test_create_download_token_caps_ttl_at_120s` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_phase_273_download_token.py::test_session_jwt_rejected_on_download_query_param` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_records_conformance.py::test_feature_collection_has_timestamp` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_phase_273_download_token.py::test_download_token_for_wrong_dataset_rejected` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_phase_273_download_token.py::test_expired_download_token_rejected` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_dataset_rows.py::TestRowsResponse::test_rows_exclude_geometry_columns` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_phase_273_download_token.py::test_session_jwt_in_authorization_header_still_works` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_embed_tokens.py::TestTileDomainLocking::test_tile_null_origins_unrestricted` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_maps.py::TestUpdateMap::test_update_map_round_trips_basemap_opacity_field` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_phase_273_icon_csp.py::test_builtin_marker_svg_icon_emits_csp_sandbox` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_phase_273_icon_csp.py::test_builtin_circle_dot_icon_emits_csp_sandbox` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestUpdateMap::test_update_map_rejects_extra_basemap_config_fields` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_phase_273_icon_csp.py::test_icon_get_preserves_cache_control` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_phase_273_icon_csp.py::test_csp_header_is_exactly_strict_form` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_fk_relationships.py::TestFKRelationships::test_delete_relationship` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_phase_273_icon_csp.py::test_non_icon_route_keeps_global_csp` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_fk_relationships.py::TestFKRelationships::test_list_relationships_private_dataset_anonymous` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_embed_tokens.py::TestTileDomainLocking::test_tile_localhost_auto_allowed` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_phase_273_share_token_entropy.py::test_new_share_token_is_32_bytes` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_records_conformance.py::test_sortby_ogc_syntax` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_phase_273_share_token_entropy.py::test_token_hash_storage_shape_unchanged` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestMapHistory::test_history_records_map_updates_and_preserves_audit` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_phase_273_share_token_entropy.py::test_legacy_16_byte_token_still_validates` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_phase_273_thumbnail_pil_verify.py::test_valid_png_thumbnail_accepted` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ingest_fan_out.py::TestFanOutEndpoint::test_cap_exceeded_51_layers_returns_422` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_maps_bulk_layers.py::TestBulkDeletePartial::test_bulk_delete_partial_invalid_id` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_maps.py::TestMapHistory::test_history_records_layer_diff_events` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_embed_tokens.py::TestListEmbedTokens::test_list_embed_tokens` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_datasets.py::TestBulkDeleteDatasets::test_bulk_delete_success` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_embed_tokens.py::TestRevokeEmbedToken::test_revoke_embed_token` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_ogc_records_conformance.py::test_type_query_param` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_embed_tokens.py::TestTileEmbedTokenAccess::test_tile_access_with_valid_embed_token` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_phase_275_maps_import_typed_body.py::TestMapsImportTypedBody::test_post_maps_import_accepts_valid_minimal_body` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_phase_275_maps_import_typed_body.py::TestMapsImportTypedBody::test_post_maps_import_rejects_out_of_range_zoom_with_422` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ingest_fan_out.py::TestCR01PreviewStampsAllLayers::test_preview_stamps_all_layers_enabling_fan_out` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_phase_275_maps_import_typed_body.py::TestMapsImportTypedBody::test_post_maps_import_extra_allow_forward_compat` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_public_access.py::test_collection_metadata_no_auth_returns_200` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_provenance_attribution.py::test_metadata_patch_stamps_actor_and_is_visible_in_history` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_publication_lifecycle.py::TestValidTransitions::test_valid_transition[draft-ready]` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_publication_lifecycle.py::TestValidTransitions::test_valid_transition[ready-internal]` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_publication_lifecycle.py::TestValidTransitions::test_valid_transition[internal-published]` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_dataset_rows.py::TestRowsKeysetPagination::test_keyset_last_page` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_publication_lifecycle.py::TestValidTransitions::test_valid_transition[published-internal]` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_publication_lifecycle.py::TestValidTransitions::test_valid_transition[internal-ready]` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_phase_279_user_lifecycle.py::test_register_disabled_does_not_emit_audit` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_publication_lifecycle.py::TestValidTransitions::test_valid_transition[ready-draft]` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_publication_lifecycle.py::TestInvalidTransitions::test_invalid_transition[draft-published]` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_publication_lifecycle.py::TestInvalidTransitions::test_invalid_transition[draft-internal]` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_publication_lifecycle.py::TestInvalidTransitions::test_invalid_transition[published-draft]` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_publication_lifecycle.py::TestInvalidTransitions::test_invalid_transition[published-ready]` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_publication_lifecycle.py::TestInvalidStatusValue::test_invalid_status_value_rejected` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_publication_lifecycle.py::TestInvalidStatusValue::test_blank_status_value_rejected` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_publication_lifecycle.py::TestTargetStatus::test_target_status_walks_forward_chain` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_publication_lifecycle.py::TestTargetStatus::test_target_status_no_change_returns_current` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_publication_lifecycle.py::TestDatasetNotFound::test_nonexistent_dataset_returns_404` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_datasets.py::TestBulkDeleteDatasets::test_bulk_delete_wrong_title` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_quality_score.py::test_compute_quality_score_complete_dataset` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_phase_273_thumbnail_pil_verify.py::test_truncated_png_rejected` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_maps_bulk_layers.py::TestBulkDeleteValidation::test_bulk_delete_too_many_ids_returns_422` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_quality_score.py::test_compute_quality_score_minimal_dataset` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_quicklook_predicate.py::test_has_quicklook_true_when_uri_set` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_quality_score.py::test_quality_score_in_search_results` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_dataset_rows.py::TestRowsKeysetPagination::test_keyset_past_end` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_quality_score.py::test_quality_score_in_dataset_response` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestMapHistory::test_history_requires_builder_access` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_quality_score.py::test_attribute_completeness_uses_single_query` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_export_hardening.py::TestExportRevokedViewerParity::test_export_200_when_editor_export_kept` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_quality_score.py::test_validate_dataset_returns_cached_quality_by_default` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_quality_score.py::test_compute_quality_score_table_record` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_quicklook_predicate.py::test_has_quicklook_false_when_uri_null` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_dcat.py::test_single_record_dcat_has_context` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_raster_schema.py::TestRecordType::test_record_type_defaults_to_vector_dataset` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_raster_schema.py::TestRecordType::test_existing_records_have_vector_dataset_type` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_raster_schema.py::TestRecordType::test_record_type_rejects_invalid_value` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_raster_tiles.py::TestRasterAuthCheck::test_auth_check_404_for_vector_dataset` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_raster_schema.py::TestRecordType::test_record_type_accepts_raster_dataset` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_raster_schema.py::TestRasterAssets::test_raster_asset_insert` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_raster_schema.py::TestRasterAssets::test_raster_asset_cascade_delete` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_rate_limits.py::test_semantic_search_rate_limit_returns_429` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_raster_schema.py::TestRasterAssets::test_raster_asset_unique_constraint` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_embed_tokens.py::TestUsageTracking::test_usage_tracking_not_on_cache_hit` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_raster_schema.py::TestMapLayerType::test_map_layer_type_defaults_to_vector_geolens` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_raster_schema.py::TestMapLayerType::test_map_layer_type_accepts_raster_geolens` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_raster_tiles.py::TestRasterAuthCheck::test_auth_check_returns_open_path_for_public_raster` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_raster_tiles.py::TestRasterAuthCheck::test_auth_check_returns_open_path_for_authenticated_user` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_rate_limits.py::test_search_facets_not_rate_limited` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_maps.py::TestDeleteMap::test_delete_map_not_found` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_raster_tiles.py::TestRasterAuthCheck::test_auth_check_401_for_unauthenticated_private` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_records_related.py::TestDistributions::test_distribution_not_found_record` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_records_related.py::TestDistributions::test_distribution_unique_constraint` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_records_related.py::TestDistributions::test_generate_distributions_idempotent` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_records_related.py::TestDistributions::test_distribution_lifecycle_modes` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_records_related.py::TestCascadeDelete::test_delete_record_cascades_contacts` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_records_related.py::TestCascadeDelete::test_delete_record_cascades_keywords` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_records_related.py::TestCascadeDelete::test_delete_record_cascades_distributions` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_records_related.py::TestMigrationData::test_migrated_contacts_have_role` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_records_related.py::TestMigrationData::test_migrated_contacts_have_extra_json` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_records_related.py::TestMigrationData::test_migrated_keywords_have_type` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_records_related.py::TestMigrationData::test_distributions_exist_for_datasets` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_records_related.py::TestMigrationData::test_distribution_urls_use_dataset_id` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_records_related.py::TestKeywords::test_create_keyword_all_types` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_regenerate_vrt_integration.py::test_regenerate_vrt_happy_path_end_to_end` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_related_datasets.py::TestRelatedDatasets::test_related_returns_empty_when_no_embedding` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_related_datasets.py::TestRelatedDatasets::test_related_returns_similar_datasets` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_records_related.py::TestContacts::test_list_contacts_empty` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_related_datasets.py::TestRelatedDatasets::test_related_excludes_self` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_reupload.py::TestServiceReuploadPreview::test_service_reupload_preview_returns_parity_response_and_dataset_bound_job` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_datasets.py::TestListDatasets::test_list_datasets_requires_auth` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_reupload.py::TestServiceReuploadPreview::test_service_reupload_preview_ssrf_blocked_returns_400_without_remote_calls` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_reupload.py::TestReuploadCommit::test_reupload_commit_queues_task` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_related_datasets.py::TestRelatedDatasets::test_related_respects_visibility` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_reupload.py::TestReuploadPreservesIdentity::test_reupload_preserves_dataset_identity` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_reupload.py::TestVersionsEndpoint::test_versions_endpoint_returns_history` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_reupload.py::TestVersionsEndpoint::test_versions_endpoint_empty_dataset` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_middleware.py::test_gzip_skips_small_responses` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_reupload.py::TestCurrentVersionInResponse::test_dataset_response_includes_current_version` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_middleware.py::test_security_headers_present` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_reupload.py::TestReuploadMultiLayer::test_preview_returns_all_layers_for_multi_layer_source` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_reupload.py::TestReuploadMultiLayer::test_preview_honors_layer_name_in_request_body` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_reupload.py::TestReuploadMultiLayer::test_commit_persists_layer_name_to_source_layer` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_reupload.py::TestReuploadMultiLayer::test_preview_previous_source_layer_is_null_when_no_prior_complete_job` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_reupload_idor.py::TestReuploadIDORNonOwner::test_reupload_dataset_idor_non_owner` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_reupload_idor.py::TestReuploadIDORNonOwner::test_reupload_service_preview_idor_non_owner` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_middleware.py::test_hsts_without_https` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_embed_tokens.py::TestAdminEmbedTokenList::test_admin_list_filter_by_status` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_reupload_idor.py::TestReuploadIDORNonOwner::test_reupload_preview_idor_non_owner` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_middleware.py::test_body_size_limit_rejects_oversized` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_dcat.py::test_single_record_dcat_has_keywords` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_related_datasets_idor.py::test_related_anonymous_nonexistent_returns_404` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_reupload_idor.py::TestReuploadIDORNonOwner::test_reupload_commit_idor_non_owner` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_datasets.py::TestListDatasets::test_list_datasets_visibility_public` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_reupload_idor.py::TestReuploadIDORNonOwner::test_request_presigned_reupload_idor_non_owner` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_layers.py::TestCreateLayerAllGeometryTypes::test_create_layer_geometry_type[MultiLineString]` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_reupload_idor.py::TestReuploadIDORNonOwner::test_complete_presigned_reupload_idor_non_owner` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_related_datasets_idor.py::test_related_anonymous_public_returns_200` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_reupload_idor.py::TestReuploadIDOROwnerAllowed::test_owner_gets_non_404_on_service_preview` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestDuplicateMap::test_duplicate_map_success` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_reupload_service.py::TestServiceReuploadCommitDispatch::test_commit_dispatches_to_reupload_service_and_keeps_token_request_only` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_layer_column_ops.py::test_rename_column_success` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_reupload_service.py::TestServiceReuploadWorker::test_reupload_service_preserves_identity_and_increments_version` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_embed_tokens.py::TestAdminEmbedTokenList::test_admin_list_requires_admin` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_records_related.py::TestContacts::test_create_contact_all_roles` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_reupload_service.py::TestServiceReuploadWorker::test_reupload_service_without_token_returns_retry_guidance_on_auth_failure` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_reupload_swap_lock_retry.py::TestApplyReuploadSwapRetry::test_happy_path_no_retry` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_reupload_swap_lock_retry.py::TestApplyReuploadSwapRetry::test_retry_path_logs_and_succeeds` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_saml_overlay.py::test_saml_metadata_xml_valid` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_raster_tiles.py::TestRasterAuthRbacParity::test_private_dataset_non_owner_blocked_by_both_paths` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_saml_overlay.py::test_saml_acs_signed_assertion_jit_provisions_user` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_records_related.py::TestKeywords::test_create_keyword_different_types` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_saml_overlay.py::test_saml_acs_rejects_invalid_signature` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestDuplicateMap::test_duplicate_map_viewer_allowed` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_saml_overlay.py::test_saml_acs_rejects_unsigned` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_saml_overlay.py::test_saml_acs_rejects_expired_assertion` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_public_access.py::test_collection_single_item_content_type_is_geo_json` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_embed_tokens.py::TestBulkRevokeEmbedTokens::test_bulk_revoke` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_saml_overlay.py::test_saml_acs_rejects_replayed_assertion` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_embed_tokens.py::TestBulkRevokeEmbedTokens::test_bulk_revoke_skips_already_revoked` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_saml_overlay.py::test_saml_acs_rejects_xsw_attack` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_saml_overlay.py::test_saml_acs_redirect_includes_source_query_param` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_saml_overlay.py::test_saml_provider_update_logs_old_new_role_mapping` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_saml_overlay.py::test_saml_provider_update_redacts_secret_fields` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_saml_overlay.py::test_saml_endpoint_404_in_community` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_saml_overlay.py::test_saml_attribute_to_role_mapping_via_provider_group_claim` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_embed_tokens.py::TestUpdateEmbedToken::test_patch_embed_token_update_origins` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_saved_searches.py::test_delete_saved_search` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_saved_searches.py::test_cannot_access_other_users_saved_search` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_saved_searches.py::test_create_saved_search_unauthenticated` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_saved_searches.py::test_get_saved_search_not_found` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_saved_searches.py::test_delete_saved_search_not_found` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_related_datasets_idor.py::test_related_non_owner_private_returns_404` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_saved_searches.py::test_get_saved_search_unauthenticated` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_saved_searches.py::test_delete_saved_search_unauthenticated` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search.py::test_ogc_collection_detail` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search.py::test_ogc_items_search` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_ogc_pagination.py::test_pagination_follow_next_links_no_data_loss` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_search.py::test_ogc_single_record` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search.py::test_ogc_single_record_content_language_uses_record_language` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search.py::test_ogc_collection_content_language_uses_homogeneous_record_language` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search.py::test_ogc_collection_content_language_omitted_for_mixed_record_languages` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search.py::test_ranking_published_boost` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search.py::test_search_unauthenticated_returns_200` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search.py::test_search_unicode_query_does_not_crash` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search.py::test_search_keyword_match_is_accent_insensitive` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search.py::test_search_simple_tsvector_matches_unicode_lineage` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search_cache.py::test_is_anon_cacheable_distinguishes_authed_from_anon` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search_cache.py::test_anon_search_caches_response` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search_cache.py::test_authed_search_bypasses_cache` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search_cache.py::test_anon_facets_caches_response` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search_cache.py::test_authed_facets_bypasses_cache` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search_datetime.py::test_datetime_overlap_filter` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search_datetime.py::test_datetime_open_end` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_dcat.py::test_single_record_dcat_has_temporal` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_search_datetime.py::test_datetime_single_instant` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search_datetime.py::test_datetime_no_filter_returns_all` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search_facets.py::test_facets_returns_all_types` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_dcat.py::test_single_record_dcat_media_type` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_search_facets.py::test_facets_with_text_filter` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_sdks_round_trip.py::TestPythonRoundTrip::test_api_key_auth_mode` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_search_facets.py::test_facets_with_srid_filter` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search_facets.py::test_facets_includes_collection_count` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search_facets.py::test_facets_returns_keyword_groups` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search_facets_input_cap.py::test_facets_q_rejects_1001_chars` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search_facets_input_cap.py::test_facets_q_accepts_1000_chars` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_raster_tiles.py::TestRasterTokenEndpoint::test_vector_token_returns_kind_vector` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_search_facets_input_cap.py::test_facets_q_accepts_short_query` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search_simple_regconfig.py::test_simple_index_exists` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search_simple_regconfig.py::test_non_english_query_uses_simple_index` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search_simple_regconfig.py::test_search_datasets_endpoint_finds_cjk_record` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_services_endpoints.py::TestPreviewEndpoint::test_preview_success` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_services_endpoints.py::TestPreviewEndpoint::test_preview_unauthenticated` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_services_endpoints.py::TestPreviewEndpoint::test_preview_viewer_forbidden` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_services_endpoints.py::TestPreviewEndpoint::test_preview_ssrf_blocked` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_records_related.py::TestContacts::test_list_contacts_returns_created` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_services_endpoints.py::TestPreviewEndpoint::test_preview_invalid_service_type` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_services_endpoints.py::TestPreviewEndpoint::test_preview_ogrinfo_failure` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_services_endpoints.py::TestPreviewEndpoint::test_preview_unexpected_error` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_reupload.py::TestReuploadUpload::test_reupload_invalid_dataset_returns_404` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_services_endpoints.py::TestPreviewEndpoint::test_preview_creates_ingest_job` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_services_endpoints.py::TestPreviewEndpoint::test_preview_editor_allowed` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_services_endpoints.py::TestPreviewEndpoint::test_preview_arcgis_without_layer_id` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_reupload.py::TestReuploadUpload::test_reupload_invalid_file_extension_returns_400` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_sandbox.py::TestRowLimitTruncation::test_exact_limit_not_truncated` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_services_endpoints.py::TestPreviewEndpoint::test_preview_ogcapi_uri_form_crs_fallback` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search.py::test_search_text_match` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_ogc_public_access.py::test_collections_list_no_auth_returns_200` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_services_endpoints.py::TestPreviewEndpoint::test_preview_wfs_namespace_retry` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_settings_oauth_crud.py::test_update_oauth_provider` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_settings_oauth_crud.py::test_update_oauth_provider_not_found` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_settings_oauth_crud.py::test_update_oauth_provider_non_admin_forbidden` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_settings_oauth_crud.py::test_delete_oauth_provider` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_settings_oauth_crud.py::test_delete_oauth_provider_not_found` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_settings_oauth_crud.py::test_delete_oauth_provider_non_admin_forbidden` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_settings_oauth_crud.py::test_reset_settings` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_settings_oauth_crud.py::test_reset_settings_unknown_key` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_settings_oauth_crud.py::test_reset_settings_non_admin_forbidden` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_settings_oauth_crud.py::test_reset_settings_unauthenticated` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_reupload.py::TestReuploadUpload::test_reupload_requires_admin_or_editor` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_manifest_apply_api.py::TestManifestApplyEndpoint::test_valid_request_delegates_to_manifest_service` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_settings_oauth_crud.py::test_detect_embedding_dims_non_admin_forbidden` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_settings_oauth_crud.py::test_detect_embedding_dims_unauthenticated` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_maps.py::TestDuplicateMap::test_duplicate_no_copy_chaining` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_settings_oauth_crud.py::test_get_tile_config` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_settings_admin.py::TestUpdateSettings::test_update_unknown_key_rejected` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_settings_router.py::test_put_settings_changing_embedding_dims_triggers_cleanup` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_settings_router.py::test_put_settings_same_embedding_dims_does_not_delete` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_settings_router.py::test_put_settings_requires_admin_auth` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_settings_router.py::test_put_settings_unauthenticated_returns_401` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestDuplicateMap::test_duplicate_rbac_filtering` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_stac_api.py::test_get_collection_not_found` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_api.py::test_get_collection_items_not_found` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_api.py::test_get_collection_item_not_found` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_api.py::test_get_item_not_found` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_api.py::test_get_collection_valid` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_embed_tokens.py::TestUpdateEmbedToken::test_patch_embed_token_non_owner` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_stac_api.py::test_get_collection_items_empty` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_records_related.py::TestContacts::test_delete_contact` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_stac_api.py::test_collection_items_self_link_preserves_active_params` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_services_endpoints.py::TestProbeEndpoint::test_probe_ssrf_blocked` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_sandbox.py::TestValidateAndExecuteIntegration::test_simple_select_via_pipeline` | sandbox subsystem error (non-cascade) | `app.platform.sandbox.schemas.SandboxError` | app.platform.sandbox.schemas.SandboxError: Query failed |
| `backend/tests/test_stac_asset_model.py::TestDatasetAssetCRUD::test_dataset_asset_insert` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_asset_model.py::TestDatasetAssetCRUD::test_dataset_asset_unique_key` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_asset_model.py::TestDatasetAssetCRUD::test_dataset_asset_cascade_delete` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_maps.py::TestDuplicateMap::test_duplicate_all_layers_excluded` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_stac_asset_model.py::TestToStacProperties::test_to_stac_properties_full` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_asset_model.py::TestToStacProperties::test_to_stac_properties_sparse` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_reupload.py::TestReuploadUpload::test_reupload_rejects_vector_file_for_raster_dataset` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_layers.py::TestCreateLayerBasic::test_create_layer_basic` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_layers.py::TestCreateLayerBasic::test_create_layer_with_columns` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_stac_asset_model.py::TestToStacProperties::test_to_stac_properties_empty` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_asset_model.py::TestBackfillAssetKeys::test_backfill_asset_keys` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_search.py::test_search_filter_by_geometry_type` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_stac_import.py::TestStacConnect::test_connect_success` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_layers.py::TestCreateLayerBasic::test_create_layer_admin` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_layers.py::TestCreateLayerRBAC::test_create_layer_viewer_forbidden` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_stac_import.py::TestStacConnect::test_connect_unauthenticated` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_import.py::TestStacConnect::test_connect_not_stac` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_embed_tokens.py::TestUpdateEmbedToken::test_patch_embed_token_cache_invalidation` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_settings_admin.py::TestResetSettings::test_reset_success` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_stac_import.py::TestStacConnect::test_connect_ssrf_blocked` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_import.py::TestStacCollections::test_collections_success` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_import.py::TestStacCollections::test_collections_fetch_failure` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_import.py::TestStacSearch::test_search_success` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_record_output.py::TestStacDatetime::test_datetime_range_with_start_and_end` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_record_output.py::TestStacAssetsRemoved::test_stac_assets_not_in_ogc_record` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_record_output.py::TestStacExtensionsRemoved::test_raster_record_no_stac_extensions` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_provenance_attribution.py::test_feature_write_paths_stamp_actor_and_emit_feature_audit_actions` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_stac_record_output.py::TestStacExtensionsRemoved::test_vector_record_no_stac_extensions` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_record_output.py::TestStacExtensionsRemoved::test_raster_record_proj_properties` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_stac_record_output.py::TestStacExtensionsRemoved::test_no_bands_without_band_info` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_search_validation.py::TestSecFu05StacIntersectsMaxLength::test_sec_fu_05_over_limit_returns_422` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_search_validation.py::TestSecFu05StacIntersectsMaxLength::test_sec_fu_05_just_under_limit_not_422` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_search_validation.py::TestSecFu05StacIntersectsMaxLength::test_sec_fu_05_valid_short_intersects_not_422` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_provenance_attribution.py::test_schema_add_drop_column_stamps_actor_and_emits_dataset_audit` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_stac_visibility.py::test_stac_item_no_auth_private_returns_404` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_visibility.py::test_stac_item_no_auth_public_returns_200` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_visibility.py::test_stac_search_no_auth_excludes_private` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_records_related.py::TestKeywords::test_keyword_vocabulary_uri_normalized` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_stac_visibility.py::test_stac_collection_items_no_auth_excludes_private` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_visibility.py::test_stac_item_owner_can_read_private` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_visibility.py::test_stac_item_non_owner_cannot_read_private` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_search_validation.py::TestStacSearchBodyBounds::test_post_search_negative_offset_rejected` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_stac_search_validation.py::TestStacSearchBodyBounds::test_post_search_zero_limit_rejected` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_stac_visibility_5xx.py::test_stac_item_5xx_does_not_leak_private_context` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_manifest_apply_roundtrip.py::TestManifestApplyEndpointRoundTrip::test_endpoint_routes_vector_raster_and_vrt_entries_to_existing_queue` | assertion failure (test logic — needs case-by-case inspection) | `AssertionError` | AssertionError: assert {'roundtrip-r...ate': 'error'} == {'roundtrip-r...te': 'create'} |
| `backend/tests/test_stac_visibility_5xx.py::test_stac_search_5xx_does_not_leak_private_context` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_visibility_5xx.py::test_stac_item_returns_200_without_5xx_fixture` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_search_validation.py::TestStacSearchBodyBounds::test_post_search_limit_within_bounds_accepted` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_tasks_common_phase_brackets.py::test_phase_session_loads_existing_job` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_tasks_common_phase_brackets.py::test_phase_session_yields_none_when_job_missing` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_tile_cache_cols_key.py::TestTileCacheColsKey::test_tile_cache_key_includes_cols_suffix_isolates_projections` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_tile_cache_cols_key.py::TestTileCacheColsKey::test_tile_cache_key_omits_suffix_when_cols_absent_or_empty` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_tile_cols_endpoint.py::TestTileEndpointColsParam::test_tile_endpoint_with_cols_param_projects_column_at_low_zoom` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_tile_cols_endpoint.py::TestTileEndpointColsParam::test_tile_endpoint_cols_silently_drops_invalid_names` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_ogc_queryables.py::test_queryables_endpoint` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_tasks_common_phase_brackets.py::test_job_phase_session_none_branch_rolls_back_on_exception` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_tasks_common_phase_brackets.py::test_phase_session_rolls_back_on_exception` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_tasks_common_phase_brackets.py::test_phase_session_commit_persists_on_normal_exit` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search.py::test_search_bbox_intersects` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_tile_signing.py::TestTileSignatureValidation::test_expired_signature_rejected` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_tile_signing.py::TestTileSignatureValidation::test_tampered_signature_rejected` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_tile_signing.py::TestTileSignatureValidation::test_scope_mismatch_rejected` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_tile_signing.py::TestTileCacheTTL::test_default_cache_ttl` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_tile_signing.py::TestTileCacheTTL::test_per_dataset_cache_ttl` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_tile_signing.py::TestTileAccessLogging::test_tile_access_logged` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_tiles.py::TestTileEndpoint::test_tile_endpoint_returns_mvt` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_tiles.py::TestTileEndpoint::test_tile_response_headers` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_tiles.py::TestTileEndpoint::test_cluster_tile_endpoint_returns_mvt` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_tiles.py::TestTileEndpoint::test_cluster_tile_endpoint_handles_multipoint` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_tiles.py::TestTileEndpoint::test_cluster_tile_rejects_non_point_dataset` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_tiles.py::TestTileEndpoint::test_cluster_tile_cache_key_includes_options` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_tiles.py::TestTileEndpoint::test_empty_tile_returns_204` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_tiles.py::TestTileEndpoint::test_empty_tile_sentinel_cache_hit_returns_204` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_tiles.py::TestTileEndpoint::test_invalid_table_name_returns_400` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_tiles.py::TestTileEndpoint::test_nonexistent_table_returns_404` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_provenance_attribution.py::test_reupload_swap_stamps_actor_and_emits_reupload_commit_audit` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_validation.py::test_validate_endpoint_returns_errors_for_incomplete_record` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_validation.py::test_validate_endpoint_returns_warnings` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_tile_cols_endpoint.py::TestTileEndpointColsParam::test_tile_endpoint_cols_silently_drops_sql_injection_attempt` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_validation.py::test_publish_blocked_when_hard_validation_fails` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_validation.py::test_publish_succeeds_when_all_required_fields_present` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_validation.py::test_already_published_record_can_be_edited` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_settings_admin.py::TestConfigMode::test_config_mode_no_auth` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_settings_admin.py::TestOAuthProviderCRUD::test_list_providers` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_vrt_ingest_tasks.py::TestCreateVrtDataset::test_public_vrt_records_start_published` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_vrt_schema_171.py::TestVrtRecordType::test_record_type_accepts_vrt_dataset` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_vrt_schema_171.py::TestRasterAssetsVrtColumns::test_status_defaults_to_ready` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_stac_integration.py::TestSTACSearch::test_search_get` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_vrt_schema_171.py::TestRasterAssetsVrtColumns::test_vrt_type_check_accepts_mosaic` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_tile_cols_endpoint.py::TestTileEndpointColsParam::test_tile_endpoint_cols_normalizes_permutations` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_vrt_schema_171.py::TestRasterAssetsVrtColumns::test_vrt_type_check_rejects_invalid` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_vrt_schema_171.py::TestRasterAssetsVrtColumns::test_status_check_accepts_regenerating` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_vrt_schema_171.py::TestRasterAssetsVrtColumns::test_status_check_rejects_invalid` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_vrt_schema_171.py::TestVrtSourceLinks::test_unique_constraint_prevents_duplicate_link` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_tiles.py::TestVectorTileAuth::test_private_tile_unsigned_returns_403` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_vrt_schema_171.py::TestVrtSourceLinks::test_on_delete_restrict_blocks_cog_deletion` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_provenance_attribution.py::test_non_mutation_operations_do_not_overwrite_last_editor` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_search.py::test_search_bbox_within` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_vrt_schema_171.py::TestVrtSourceLinks::test_on_delete_cascade_removes_links_when_vrt_deleted` | per-worker DB lifecycle race (gw15 setup failed) | `failed on setup with "asyncpg.exceptions.InvalidCatalogNameError` | failed on setup with "asyncpg.exceptions.InvalidCatalogNameError: database "geolens_test_gw15_4b3a515e" does not exist" |
| `backend/tests/test_search.py::test_search_filter_by_date_range` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_stac_integration.py::TestSTACSearch::test_search_post` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_provenance_responses.py::test_dataset_detail_resolves_actor_labels` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_stac_integration.py::TestSTACSearch::test_search_with_limit` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_tiles.py::TestVectorTileAuth::test_private_cluster_tile_requires_signature` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_manifest_apply_roundtrip.py::TestManifestCompletedDatasetRoundTrip::test_completed_manifest_datasets_are_searchable_and_previewable` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_search.py::test_search_filter_by_vintage` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_tiles.py::TestVectorTileAuth::test_private_cluster_tile_with_valid_signature` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_tile_signing.py::TestTileTokenEndpoint::test_token_private_dataset_non_owner_returns_404` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |
| `backend/tests/test_stac_record_output.py::TestStacDatetime::test_datetime_falls_back_to_created_at_when_no_temporal` | setup-phase connection contention (TooManyConnections during fixture setup) | `failed on setup with "asyncpg.exceptions.TooManyConnectionsError` | failed on setup with "asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already" |
| `backend/tests/test_ogc_record_enrichment.py::test_feature_asset_href_points_to_public_ogc_features_items` | in-test connection contention (TooManyConnections inside test body) | `asyncpg.exceptions.TooManyConnectionsError` | asyncpg.exceptions.TooManyConnectionsError: sorry, too many clients already |

---

## Section 4 — Per-category root-cause analysis

One subsection per category. The four v1019-hypothesis categories (Redis singleton state,
storage provider override, `app.dependency_overrides` leak, autouse-fixture coupling) are
each NAMED below regardless of observed count — Section 4.5–4.8 document each as
"0 failures observed; hypothesis not reproduced" for Phase 1088 traceability.

### 4.1 per-worker DB lifecycle race (gw15 setup failed)

**Impact:** 407 failures (62.8% of total)

**Mechanism:** The `_test_db_lifecycle` fixture in `backend/tests/conftest.py:241-447` is
`@pytest.fixture(autouse=True, scope="session")` — one invocation per worker per session.
It performs four ordered steps:

1. Sleep `worker_num × 5.0s` (the `_SETUP_STAGGER_SECONDS` startup stagger, conftest.py:106).
2. Open a sync engine to the main DB → `CREATE DATABASE geolens_test_{worker_id}_{hash}`.
   If this step raises (e.g., `TooManyConnectionsError`), the fixture `yield`s with
   `should_drop_db = False` and returns (conftest.py:275-278) — silently swallowing the
   exception via `except Exception: yield; return`.
3. Create extensions + schemas + roles on the new DB.
4. Run alembic migrations.

The Step-2 silent swallow is the structural defect: when `dev_engine.connect()` fails
due to concurrent connection contention (Postgres returns "sorry, too many clients
already" because the 16 workers' Step-1 stagger windows + extant API/worker idle
connections + Postgres background = >30), the fixture completes "successfully" from
pytest's POV (no exception escapes) but the per-worker test DB was never created.
Every test on that worker then opens an async connection to a database name that
doesn't exist → `asyncpg.exceptions.InvalidCatalogNameError: database
"geolens_test_gw15_..." does not exist`.

In this measurement run, gw15 was the worker that lost the race (15 × 5 = 75s stagger
delay placed gw15 in the connection-saturation window after gw0..gw14 had completed
their `Step-2 CREATE DATABASE` and were holding the next 2-3 setup connections each for
alembic). All 407 tests xdist assigned to gw15 then failed setup. The sampler (Step 3
in Section 1) saw only 15 workers in `pg_stat_activity` (gw0..gw14) — gw15 never opened
a per-worker connection because its DB was never created.

**Python diff sketch (illustrative — Phase 1088 owns the actual fix shape):**

```python
# offending pattern in backend/tests/conftest.py:265-278 (autouse=True, scope="session"):
@pytest.fixture(autouse=True, scope="session")
def _test_db_lifecycle():
    ...
    try:
        dev_engine = sqlalchemy.create_engine(settings.database_url_sync, isolation_level="AUTOCOMMIT")
        try:
            with dev_engine.connect() as conn:
                conn.execute(text(f"DROP DATABASE IF EXISTS {quoted_db_name}"))
                conn.execute(text(f"CREATE DATABASE {quoted_db_name}"))
            should_drop_db = True
        except Exception:
            # DB host unreachable — skip full setup; unit tests unaffected
            yield   # ← SILENT SWALLOW: TooManyConnectionsError during stagger window is treated
            return  #    as if Postgres were "unreachable" — all subsequent tests on this worker
                    #    use a DB name that was never created.
        finally:
            dev_engine.dispose()

# Phase 1088 might fix toward:
#   except sqlalchemy.exc.OperationalError as exc:
#       # Distinguish "Postgres unreachable" (skip) from "transient connection contention" (retry).
#       if "too many clients already" in str(exc).lower():
#           # Retry with backoff up to N attempts, OR surface as fixture error to fail loudly.
#           raise pytest.fail(f"CREATE DATABASE failed under connection contention: {exc}")
#       yield  # other operational errors — skip per existing semantics
#       return
```

**Representative failures (3 of 407):**

- `backend/tests/test_features_crud.py::TestInsertFeature::test_insert_feature`
- `backend/tests/test_maps.py::TestShareToken::test_share_idempotent`
- `backend/tests/test_oauth.py::TestOAuthProviderCRUD::test_admin_can_create_oauth_provider`

### 4.2 setup-phase connection contention (TooManyConnections during fixture setup)

**Impact:** 150 failures (23.1% of total)

**Mechanism:** When `_test_db_lifecycle` completed successfully but a downstream fixture
(typically `client`, `db`, or one of the per-test session fixtures) tries to open a
new connection during the test's `setup` phase, Postgres responds with `TooManyConnections`
because the 16 workers' staggered setup windows overlap enough that the connection count
spikes above `max_connections=30`. Unlike Category 4.1, the per-worker DB exists — the
failure is in opening a new connection to it.

The v1019 TD-10 fix added NullPool (no idle connections) + 5s startup stagger (spreads
the first per-worker `Step-2 CREATE DATABASE` calls across 75s). The residual 150 setup-phase
failures are evidence that even with NullPool + stagger, concurrent fixture setup demand
still races: when 3-4 workers complete their initial setup at near-simultaneous times,
the subsequent `client` fixture's `_make_test_async_engine` + `_ensure_roles_and_admin`
open 2-3 connections in flight per worker, briefly spiking past 30 total.

**Python diff sketch (illustrative):**

```python
# observed pattern: setup-phase connection contention during the `client` fixture body
# at backend/tests/conftest.py:451-540
@pytest.fixture
async def client(tmp_path):
    ...
    test_engine = _make_test_async_engine(settings.test_database_url)  # ← opens a connection
    test_session_factory = async_sessionmaker(test_engine, expire_on_commit=False)
    ...
    await _ensure_roles_and_admin(test_session_factory)  # ← opens another connection
    ...
    # under concurrent demand, the second connection raises TooManyConnections

# Phase 1088 might fix toward: a per-worker setup-phase semaphore, OR connection retry-with-backoff
# in _make_test_async_engine, OR exponential-backoff in _ensure_roles_and_admin.
```

**Representative failures (3 of 150):**

- `backend/tests/test_maps.py::TestCreateMap::test_create_map_as_viewer_forbidden`
- `backend/tests/test_features_crud.py::TestInsertFeature::test_insert_feature_wrong_geometry_type`
- `backend/tests/test_jobs_router.py::TestGetJobStatus::test_get_job_surfaces_legacy_collision_warning_message`

### 4.3 in-test connection contention (TooManyConnections inside test body)

**Impact:** 87 failures (13.4% of total)

**Mechanism:** Tests that internally open more than one DB connection within their body
(typically by performing multiple `TestClient.post(...)` calls that each trigger their
own `override_get_db` → `test_session_factory()` connection acquisition) race the
connection ceiling. Distinct from 4.2 — here the `client` fixture has already completed
setup and yielded; the test itself is opening a connection mid-execution.

**Python diff sketch (illustrative):**

```python
# observed pattern: a test that performs multiple sequential POSTs inside its body
async def test_some_endpoint_that_does_two_things(client):
    # Connection 1: open
    await client.post('/api/something')   # ← acquires connection from NullPool
    # Connection 1: closed (NullPool disposes immediately)
    await client.post('/api/something-else')  # ← acquires another connection
    # Between these, other workers may have acquired the slot — race.
```

**Representative failures (3 of 87):**

- `backend/tests/test_download_token.py::TestDownloadTokenEndpoint::test_download_token_private_non_owner`
- `backend/tests/test_jobs_router.py::TestGetJobStatus::test_get_job_surfaces_temporal_parse_errors`
- `backend/tests/test_column_ddl_idor.py::test_drop_column_owner_returns_200`

### 4.4 teardown-phase connection contention (TooManyConnections during fixture teardown)

**Impact:** 2 failures (0.3% of total)

**Mechanism:** Tail-end variant of 4.2 — `client` fixture teardown (`await
test_engine.dispose()` at conftest.py:539) is the last code path before yield-resume,
and if other workers are in their own setup phase at the same instant, the teardown's
final dispose can momentarily fail with `TooManyConnections`. Low count because the
window is narrow (only 2 tests in the entire run happened to teardown during a contention
peak).

**Python diff sketch (illustrative):** Same as 4.2; fix is the same shape.

**Representative failures (2 of 2):**

- `backend/tests/test_embed_tokens.py::TestTileDomainLocking::test_tile_allowed_origin_passes`
- `backend/tests/test_features_geojson_z.py::TestGetFeaturesGeoJSONZEndpoint::test_truncation_at_5000`

### 4.5 Redis singleton state — hypothesis NOT reproduced

**Impact:** 0 failures observed under `-n auto` in this measurement run.

**Possible reasons:**
- (a) The v1019 TD-10 NullPool + stagger fix incidentally serialised the Redis-cache
  init paths via the connection-cascade gating (`init_cache()` in
  `backend/tests/conftest.py:511` is per-`client`-fixture, and the cascade prevented
  enough concurrent invocations to surface the race).
- (b) The hypothesis was a v1019-era pattern that has since been fixed by another
  refactor in the v1019 → v1020 window.
- (c) Redis cache state is per-test (not per-session or per-worker), and pytest-xdist's
  worker-process isolation prevents cross-worker leakage by design.

Named here for traceability; Phase 1088 may revisit if a fix to 4.1 reveals Redis-related
failures that were previously masked by the dominant 4.1 category.

### 4.6 storage provider override — hypothesis NOT reproduced

**Impact:** 0 failures observed under `-n auto` in this measurement run.

**Possible reasons:** Same shape as 4.5 — the `app.platform.storage.provider._storage`
singleton swap at `backend/tests/conftest.py:516` is per-`client`-fixture (test scope),
not session/worker scope. xdist worker-process isolation makes cross-worker leakage
impossible at the singleton level. The storage subsystem may surface as a fixture-leak
target in a later milestone, but not in v1020's measurement.

### 4.7 `app.dependency_overrides` leak — hypothesis NOT reproduced

**Impact:** 0 failures observed under `-n auto` in this measurement run.

**Possible reasons:** The `client` fixture clears `app.dependency_overrides` in its
teardown (`app.dependency_overrides.clear()` at `backend/tests/conftest.py:532`). Under
xdist worker-process isolation, each worker has its own FastAPI app instance —
cross-worker mutation of `app.dependency_overrides` is impossible by Python process
isolation. The hypothesis was relevant to single-process async test concurrency (e.g.,
trio/anyio inside a single test), not to xdist multi-process parallelism.

### 4.8 autouse-fixture coupling — hypothesis NOT reproduced

**Impact:** 0 failures observed under `-n auto` in this measurement run.

**Note:** The DOMINANT failure category (4.1) is technically an autouse-fixture-coupling
failure — `_test_db_lifecycle` IS an autouse session-scoped fixture, and its failure
mode (silent swallow → downstream tests fail) is the autouse-coupling antipattern. The
"hypothesis not reproduced" framing is about the v1019-era specific autouse-coupling
patterns (e.g., autouse fixtures that mutate global state without isolation guards);
the v1020 measurement shows a DIFFERENT autouse-coupling pattern — silent-swallow during
setup. Phase 1088 may choose to merge 4.1 into a broader "autouse-fixture coupling"
banner, or keep 4.1 as a more specific sub-category for clearer fix sequencing.

### 4.9 sandbox subsystem error (non-cascade) — single occurrence

**Impact:** 1 failure (0.2% of total)

**Representative failure:**
- `backend/tests/test_sandbox.py::TestValidateAndExecuteIntegration::test_simple_select_via_pipeline` —
  `app.platform.sandbox.schemas.SandboxError: Query failed`

This is not a fixture-isolation surface; it is a non-cascade `SandboxError` from the
sandbox subsystem. Likely a downstream effect of one of the cascade categories (the
sandbox's underlying DB connection failed mid-execution). Phase 1088 should not fix
this category directly — it should resolve once 4.1–4.3 are fixed.

### 4.10 assertion failure (test logic — single occurrence)

**Impact:** 1 failure (0.2% of total)

**Representative failure:**
- `backend/tests/test_manifest_apply_roundtrip.py::TestManifestApplyEndpointRoundTrip::test_endpoint_routes_vector_raster_and_vrt_entries_to_existing_queue` —
  `AssertionError: assert {'roundtrip-r...ate': 'error'} == {'roundtrip-r...te': 'create'}`

This single `AssertionError` is the only non-cascade test-logic failure in the run. The
asserted state (`'state': 'error'` vs expected `'state': 'create'`) is consistent with
a downstream effect of one of the cascade categories — a test that depends on a queue-state
side effect from a previous-test action, where the previous action errored out due to a
cascade. Phase 1088 should not fix this assertion directly; it should re-verify after
4.1–4.3 are fixed.

---

## Section 5 — Phase 1088 fix sequencing recommendation

Ordered by impact (highest failure count first) and by structural dependency (a downstream
category that may resolve when an upstream is fixed is sequenced LATER, with a re-measure
gate).

### Fix sequence

1. **per-worker DB lifecycle race (gw15 setup failed)** — **407 failures (62.8%)** — **FIX FIRST.**

   **Rationale:** Largest single category. The `_test_db_lifecycle` autouse session
   fixture's silent-swallow of setup-phase `OperationalError`s (conftest.py:275-278
   `except Exception: yield; return`) is a structural defect, NOT a transient flake. It
   reliably fails the worker that loses the connection-contention race in the staggered-
   startup window; in this run it was gw15 (75s stagger position), and it produced 407
   downstream `InvalidCatalogNameError` failures. Even if a different worker loses the
   race in another run, the same structural fix (distinguish "Postgres unreachable" from
   "transient connection contention" and either retry-with-backoff or fail loudly) closes
   all the InvalidCatalogName failures.

   **Suggested approach (illustrative; Phase 1088 plan owns the shape choice):** Replace
   the broad `except Exception: yield; return` with a structured handler that:
   - Catches `sqlalchemy.exc.OperationalError` specifically.
   - Detects "too many clients already" / `TooManyConnectionsError` in the exception
     message.
   - On detection: retry with exponential backoff (e.g., 3 attempts with 1s/2s/4s waits).
   - If all retries fail: re-raise as a fixture error (NOT a silent swallow) so the worker's
     tests fail explicitly on setup, surfacing the issue rather than masking it as
     `InvalidCatalogNameError` downstream.
   - Keep the existing skip-on-truly-unreachable-host semantics for non-`TooManyConnections`
     OperationalErrors (e.g., DNS failure, refused connection).

   This is a single-file fix (conftest.py:265-280) with a clear regression-pin test
   (mock `dev_engine.connect()` to raise `OperationalError("too many clients already")`
   once, then succeed; assert the DB is created on retry).

2. **setup-phase connection contention** — **150 failures (23.1%)** — **FIX SECOND (after 4.1 re-measure).**

   **Rationale:** This category may PARTIALLY resolve when 4.1 is fixed. The 4.1 silent-swallow
   currently means gw15 holds no test-DB connections — once 4.1 is fixed (gw15's DB gets
   created), the cascade timing shifts: gw15 will now open connections, potentially
   reducing the per-worker peak from 3 to 2 (or perturbing other workers into the cascade
   window). A re-measure gate after 4.1 is essential: if the post-fix count of 4.2 drops
   below ~50, the residual is acceptable as transient flake (covered by HYG-02); if it
   stays above ~100, structural fix is needed.

   **Suggested approach (illustrative):** Either (a) widen the stagger to 7-8s per worker
   (slower wall-clock but more headroom — last worker at gw15 × 8 = 120s), (b) add a
   per-worker setup-phase semaphore that serialises the `client` fixture's
   `_make_test_async_engine` + `_ensure_roles_and_admin` calls across the test-DB-already-
   exists window, or (c) retry-with-backoff inside `_make_test_async_engine` for
   `TooManyConnections` (mirror the 4.1 fix shape).

3. **in-test connection contention** — **87 failures (13.4%)** — **FIX THIRD (after 4.1 + 4.2 re-measure).**

   **Rationale:** Smaller blast radius; tests that open >1 connection mid-body. Likely
   resolves partially when 4.1 + 4.2 are fixed (fewer concurrent workers in the cascade
   window means fewer in-test connection races). If the residual count after fixes is
   <30, treat as acceptable flake under HYG-02. If higher, structural fix is needed.

   **Suggested approach (illustrative):** Add a retry-with-backoff wrapper around
   `override_get_db` in the `client` fixture (conftest.py:503-505), so that a transient
   `TooManyConnections` during request handling is retried at the session-factory level
   rather than failing the test.

4. **teardown-phase connection contention** — **2 failures (0.3%)** — **DEFER / monitor after upstream fixes.**

   **Rationale:** Vanishingly small count. The fix shape is identical to 4.2's `client`
   fixture wrapper. If the post-4.2-fix count is 0, no separate plan needed. If it
   persists at 1-3, accept as flake and document in HYG-02 close-gate.

5. **sandbox subsystem error / assertion failure** — **2 failures (0.4%)** — **VERIFY-AFTER-FIX.**

   **Rationale:** Likely cascade-downstream effects. Re-run after 4.1-4.3 fixes; if they
   still fail, investigate individually as case-by-case bugs (not a Phase 1088 category).

### Re-measure protocol after each fix

Each fix in the sequence above is followed by a re-measure cycle:

1. Apply the fix in the relevant plan (e.g., Plan 1088-01 for category 4.1).
2. Drop stale per-worker DBs (Step 1b of Section 1) before the measurement.
3. Re-run sequential baseline (Step 2) — assert `failed == 0` (regression guard).
4. Re-run `pytest -n auto --junitxml=...` (Step 4).
5. Re-categorize via the Section 1 Step-5 Python helper.
6. Cross-reference with this audit's category counts. The plan SUMMARY must show:
   - Pre-fix failure count for the category being addressed
   - Post-fix failure count
   - Cross-category drift (e.g., "4.1 dropped 407 → 0; 4.2 dropped 150 → 35; 4.3 dropped 87 → 12")

The audit's Section 4 categories ARE the orthogonal axis. The Phase 1088 plan SUMMARY
must report movement across all categories, not just the targeted one, because cascade
categories interact.

### Regression-pin shape for Phase 1088 (FI-03)

Each category fixed in FI-02 needs at least one regression test under
`backend/tests/test_fixture_isolation_v1020.py` (or split per-category) that fails on
pre-fix HEAD and passes on post-fix HEAD. Suggested pin shape per category:

- **4.1 per-worker DB lifecycle race:** Mock `sqlalchemy.create_engine(...).connect()` in
  `_test_db_lifecycle` to raise `OperationalError("too many clients already")` once,
  then succeed. Assert the per-worker test DB IS created (not silently skipped) and
  downstream `client` fixture acquires a connection without `InvalidCatalogNameError`.
- **4.2 setup-phase connection contention:** Simulate concurrent `client` fixture
  invocation across workers (use `threading` + `pytest-xdist`-mocked env) and assert
  that all N concurrent `_ensure_roles_and_admin` calls complete without
  `TooManyConnections` (validates the chosen fix — semaphore, retry-with-backoff, or
  widened stagger).
- **4.3 in-test connection contention:** Write a test that opens 3 sequential
  `TestClient.post(...)` calls in a tight loop and assert all 3 complete; pre-fix should
  fail with `TooManyConnections` under concurrent xdist load; post-fix should retry and
  succeed.
- **4.4 teardown-phase:** Either covered by 4.2's pin (same fix shape) or a separate pin
  asserting teardown's `await test_engine.dispose()` completes within a small bounded
  retry window.

---

## Appendix — Reproducibility checklist (Phase 1088 + Phase 1090 consumers)

To reproduce the Section 2 numbers + Section 3 inventory exactly, follow Steps 1-11 of
Section 1 above against HEAD `d340c22e582b0c8713a6f9f2721467282e2a9550`. The expected
exit code from `pytest -n auto tests/` is non-zero (failures present). The final summary
line must match `89 failed, 2401 passed, 27 skipped, 4 warnings, 560 errors` ±5% on N
or M (test-collection or worker-assignment variance) ±1% on the per-category counts.

If a Phase 1088 fix lands and a re-measure shows a category at 0 failures (especially
4.1), this audit's count for that category is the **before-fix baseline** that the
post-fix run is compared against in the Phase 1088 SUMMARY.

If a Phase 1090 HYG-02 3× flake hunt reveals non-deterministic per-category counts,
this audit's specific run is the **single-measurement reference** documented in the
Stability declaration of Section 1.

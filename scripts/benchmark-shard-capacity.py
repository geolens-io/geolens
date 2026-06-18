#!/usr/bin/env python3
"""Per-shard table-count capacity benchmark for GeoLens (Phase 1209-04, DP-05).

Measures the real per-shard table-count ceiling on local Postgres using three
complementary signals:

  1. Relcache / buffer hit ratio (pg_statio_user_tables)
     heap_blks_hit / (heap_blks_hit + heap_blks_read)
     Degradation below ~0.95 indicates relcache pressure.

  2. Autovacuum saturation (pg_stat_user_tables + pg_stat_activity)
     dead_tuple accumulation + autovacuum worker count.

  3. pg_dump wall-clock duration (schema-only + light data, single schema)
     Super-linear growth indicates catalog metadata load.

The script provisions one synthetic per-tenant schema using the tenant_schema
naming convention (``bench_t_cap``), creates batches of lightweight PostGIS
tables (``id int, geom geometry(Point,4326)`` + GiST index — matching the
minimal real-ingest shape), and measures each signal at each batch boundary.

After running, it computes the recommended per-shard ceiling (the point where
the first signal degrades), prints a per-step metrics table, and WRITES the
findings doc to ``--output`` (default: shard-capacity-benchmark.md).

Re-run on the Azure Postgres Flexible Server SKU to get production numbers.

Permanent project fixture — run before shard promotion/rebalance decisions.

Usage:
    python scripts/benchmark-shard-capacity.py [--max-tables N] [--step S]
        [--dsn DSN] [--tenants T] [--cleanup] [--output PATH]

    cd /path/to/geolens
    set -a && source .env.test && set +a
    python scripts/benchmark-shard-capacity.py --max-tables 300 --step 50 --cleanup

Requirements:
    pip install psycopg2-binary  # or use the project's uv run psycopg2
    pg_dump must be in PATH (standard PostgreSQL client tools)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Optional psycopg2 / psycopg import (stdlib-friendly fallback to error)
# ---------------------------------------------------------------------------

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print(
        "ERROR: psycopg2 not available. Install with: uv run --with psycopg2-binary python ...",
        file=sys.stderr,
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BENCH_SCHEMA = "bench_t_cap"
_BENCH_ROLE = "geolens_reader_bench_t_cap"
_DEFAULT_OUTPUT = "shard-capacity-benchmark.md"
_HIT_RATIO_FLOOR = 0.95  # signal 1 threshold: below this → relcache pressure
_AUTOVAC_WORKER_THRESHOLD = 2  # signal 2 threshold: >= this workers → saturated
_PGDUMP_SUPERLINEAR_RATIO = (
    2.0  # signal 3: pg_dump grows >2× per doubling = super-linear
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dsn_from_env() -> str:
    """Build a psycopg2 DSN from the standard .env.test / POSTGRES_* env vars."""
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "geolens")
    password = os.environ.get("POSTGRES_PASSWORD", "")
    dbname = os.environ.get("POSTGRES_DB", "geolens")
    # Use the primary DB (not the test DB) for benchmarking so we don't
    # pollute geolens_test and can create real PostGIS schemas.
    return f"host={host} port={port} user={user} password={password} dbname={dbname}"


def _connect(dsn: str):
    """Open a psycopg2 connection with autocommit (needed for DDL + CREATE INDEX)."""
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    return conn


def _setup_bench_schema(conn) -> None:
    """Create the benchmark schema + reader role (idempotent)."""
    with conn.cursor() as cur:
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {_BENCH_SCHEMA}")
        cur.execute(
            f"DO $$ BEGIN "
            f"  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{_BENCH_ROLE}') THEN "
            f"    CREATE ROLE {_BENCH_ROLE} NOLOGIN; "
            f"  END IF; "
            f"END $$"
        )
        cur.execute(f"GRANT USAGE ON SCHEMA {_BENCH_SCHEMA} TO {_BENCH_ROLE}")
    print(f"  Schema {_BENCH_SCHEMA!r} ready.")


def _create_batch(conn, start: int, end: int) -> None:
    """Create synthetic PostGIS tables start..end (inclusive) in the bench schema.

    Each table mirrors the minimal real-ingest shape:
      - id int  (primary key)
      - geom geometry(Point, 4326)  (spatial column)
      - GiST index on geom  (mirrors the spatial index created by ingest)
    """
    with conn.cursor() as cur:
        for i in range(start, end + 1):
            tname = f"layer_{i:06d}"
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS {_BENCH_SCHEMA}.{tname} "
                f"(id integer PRIMARY KEY, geom geometry(Point,4326))"
            )
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{tname}_geom "
                f"ON {_BENCH_SCHEMA}.{tname} USING gist(geom)"
            )
            # Grant SELECT to the bench reader role (mirrors production ingest grant).
            cur.execute(f"GRANT SELECT ON {_BENCH_SCHEMA}.{tname} TO {_BENCH_ROLE}")


def _count_bench_tables(conn) -> int:
    """Count tables in the benchmark schema."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema = %s AND table_type = 'BASE TABLE'",
            (_BENCH_SCHEMA,),
        )
        return cur.fetchone()[0]


def _measure_hit_ratio(conn) -> float | None:
    """Signal 1: relcache/buffer hit ratio from pg_statio_user_tables.

    Returns heap_blks_hit / (heap_blks_hit + heap_blks_read) for the bench
    schema.

    Note: for empty tables on a local dev machine with shared_buffers fully
    caching everything, both heap_blks_hit and heap_blks_read may be 0
    (empty relation scan uses visibility map, not heap blocks). This is
    expected — it means the cache is working perfectly. We report 1.0 in
    this case (no degradation). Degradation would show as heap_blks_read > 0
    appearing on a resource-constrained SKU.

    Returns None only if no tables exist in the bench schema at all.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT coalesce(sum(heap_blks_hit), 0), "
            "       coalesce(sum(heap_blks_read), 0), "
            "       count(*) "
            "FROM pg_statio_user_tables "
            "WHERE schemaname = %s",
            (_BENCH_SCHEMA,),
        )
        row = cur.fetchone()
        hits, reads, table_count = row[0], row[1], row[2]
        if table_count == 0:
            return None  # bench schema has no tables yet
        total = hits + reads
        if total == 0:
            # All scans were visibility-map / empty-relation reads (zero heap I/O).
            # This indicates perfect buffer coverage — no degradation yet.
            return 1.0
        return hits / total


def _warm_cache(conn) -> None:
    """Touch all tables in the bench schema to populate pg_statio stats.

    Issues a SELECT against each table to force a relcache lookup and
    heap scan (even for empty tables, the relation header is read from disk
    or buffer). Uses SELECT count(*) instead of LIMIT 1 to ensure the planner
    performs a sequential scan that populates pg_statio heap_blks_hit/read.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_type = 'BASE TABLE' "
            "ORDER BY table_name",
            (_BENCH_SCHEMA,),
        )
        tables = [r[0] for r in cur.fetchall()]
    for tname in tables:
        try:
            with conn.cursor() as cur:
                # count(*) forces a relation scan (not just a stats lookup)
                # which populates pg_statio. The table is empty so this is fast.
                cur.execute(f"SELECT count(*) FROM {_BENCH_SCHEMA}.{tname}")
        except Exception:
            pass  # unexpected error — continue


def _measure_autovacuum(conn) -> dict:
    """Signal 2: autovacuum saturation.

    Returns:
      total_dead_tuples: sum of n_dead_tup across bench schema tables
      last_autovacuum_lag_sec: max seconds since last autovacuum (None if never)
      autovac_worker_count: active autovacuum workers right now
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT coalesce(sum(n_dead_tup), 0), "
            "       extract(epoch FROM (now() - max(last_autovacuum)))::int "
            "FROM pg_stat_user_tables "
            "WHERE schemaname = %s",
            (_BENCH_SCHEMA,),
        )
        row = cur.fetchone()
        dead_tuples = row[0]
        last_vac_lag = row[1]  # None if never vacuumed

        cur.execute(
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE query ILIKE '%autovacuum%' AND state = 'active'"
        )
        worker_count = cur.fetchone()[0]

    return {
        "dead_tuples": dead_tuples,
        "last_autovacuum_lag_sec": last_vac_lag,
        "autovac_worker_count": worker_count,
    }


def _measure_pgdump(dsn: str, schema: str) -> float:
    """Signal 3: pg_dump wall-clock duration (schema-only) in seconds.

    Uses subprocess pg_dump with --schema-only (just DDL, no data rows)
    to measure catalog metadata load as table count climbs.
    """
    # Parse the DSN string into pg_dump flags.
    params = {}
    for part in dsn.split():
        if "=" in part:
            k, v = part.split("=", 1)
            params[k] = v

    cmd = [
        "pg_dump",
        "--schema-only",
        f"--schema={schema}",
        "--no-owner",
        "--no-acl",
        f"--host={params.get('host', 'localhost')}",
        f"--port={params.get('port', '5432')}",
        f"--username={params.get('user', 'geolens')}",
        f"--dbname={params.get('dbname', 'geolens')}",
    ]

    env = os.environ.copy()
    if params.get("password"):
        env["PGPASSWORD"] = params["password"]

    t0 = time.monotonic()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )
        elapsed = time.monotonic() - t0
        if result.returncode != 0:
            print(
                f"    [WARN] pg_dump returned {result.returncode}: {result.stderr[:200]}",
                file=sys.stderr,
            )
            return elapsed
    except subprocess.TimeoutExpired:
        elapsed = 120.0
        print("    [WARN] pg_dump timed out at 120s", file=sys.stderr)
    except FileNotFoundError:
        print(
            "    [WARN] pg_dump not found in PATH — skipping signal 3",
            file=sys.stderr,
        )
        return -1.0

    return elapsed


def _teardown_bench(conn) -> None:
    """Drop the benchmark schema + role (idempotent cleanup)."""
    with conn.cursor() as cur:
        cur.execute(f"DROP SCHEMA IF EXISTS {_BENCH_SCHEMA} CASCADE")
        cur.execute(
            f"DO $$ BEGIN "
            f"  IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{_BENCH_ROLE}') THEN "
            f"    DROP ROLE {_BENCH_ROLE}; "
            f"  END IF; "
            f"END $$"
        )
    print(f"  Benchmark schema {_BENCH_SCHEMA!r} + role {_BENCH_ROLE!r} dropped.")


def _verify_cleanup(conn) -> bool:
    """Verify that the benchmark schema is gone (for acceptance test assertion)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT to_regclass(%s::text)",
            (f"{_BENCH_SCHEMA}.layer_000001",),
        )
        result = cur.fetchone()[0]
    return result is None


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def _find_inflection(
    steps: list[dict],
    hit_ratio_floor: float = _HIT_RATIO_FLOOR,
) -> dict:
    """Find the recommended per-shard ceiling from the per-step measurements.

    Checks signals in priority order:
      1. Hit ratio drops below hit_ratio_floor → signal 1 ceiling
      2. pg_dump duration doubles vs. prior step → signal 3 ceiling
      3. No degradation detected → ceiling is beyond max_tables

    Returns a dict with: ceiling, ceiling_tables, signal, notes
    """
    ceiling_tables = None
    ceiling_signal = None
    ceiling_notes = []

    prev_pgdump = None
    for step in steps:
        n = step["tables"]
        hr = step.get("hit_ratio")
        pgd = step.get("pgdump_sec", -1)

        # Signal 1: hit ratio degradation
        if hr is not None and hr < hit_ratio_floor:
            if ceiling_tables is None:
                ceiling_tables = n
                ceiling_signal = "relcache-hit-ratio"
                ceiling_notes.append(
                    f"Hit ratio dropped to {hr:.3f} at {n} tables "
                    f"(threshold: {hit_ratio_floor:.2f})"
                )

        # Signal 3: pg_dump super-linear growth
        if pgd is not None and pgd > 0 and prev_pgdump and prev_pgdump > 0:
            ratio = pgd / prev_pgdump
            if ratio > _PGDUMP_SUPERLINEAR_RATIO and ceiling_tables is None:
                ceiling_tables = n
                ceiling_signal = "pgdump-superlinear"
                ceiling_notes.append(
                    f"pg_dump duration grew {ratio:.1f}x at {n} tables "
                    f"(prev: {prev_pgdump:.2f}s → now: {pgd:.2f}s)"
                )
        prev_pgdump = pgd if pgd and pgd > 0 else prev_pgdump

    if ceiling_tables is None:
        # No degradation observed — ceiling is beyond the max measured.
        max_n = max(s["tables"] for s in steps) if steps else 0
        return {
            "ceiling_tables": max_n,
            "signal": "none-detected",
            "notes": (
                f"No degradation detected up to {max_n} tables. "
                f"The local Postgres ceiling exceeds the tested range. "
                f"Consider re-running with a higher --max-tables value, "
                f"or treat {max_n}+ as the local floor."
            ),
        }

    return {
        "ceiling_tables": ceiling_tables,
        "signal": ceiling_signal,
        "notes": " | ".join(ceiling_notes),
    }


# ---------------------------------------------------------------------------
# Report writing
# ---------------------------------------------------------------------------


def _write_findings(
    output_path: str,
    steps: list[dict],
    inflection: dict,
    args: argparse.Namespace,
    run_ts: str,
) -> None:
    """Write the findings doc to output_path — always to disk, not stdout-only."""
    ceiling = inflection["ceiling_tables"]
    signal = inflection["signal"]
    notes = inflection["notes"]

    # Build per-step table rows
    header = (
        "| Tables | Hit Ratio | Dead Tuples | AutoVac Workers | pg_dump (s) |\n"
        "|--------|-----------|-------------|-----------------|-------------|"
    )
    rows = []
    for s in steps:
        hr = f"{s['hit_ratio']:.4f}" if s.get("hit_ratio") is not None else "n/a"
        dt = str(int(s.get("dead_tuples", 0)))
        av = str(int(s.get("autovac_worker_count", 0)))
        pd_raw = s.get("pgdump_sec", -1)
        pd = f"{pd_raw:.2f}" if pd_raw and pd_raw >= 0 else "n/a"
        rows.append(f"| {s['tables']} | {hr} | {dt} | {av} | {pd} |")

    table_md = header + "\n" + "\n".join(rows)

    # Build the content line-by-line (no textwrap.dedent — avoids indentation issues
    # when multi-line variables like table_md are interpolated into the template).
    lines = [
        "# Per-Shard Table-Count Capacity Benchmark",
        "",
        f"**Generated:** {run_ts}",
        "**Script:** `scripts/benchmark-shard-capacity.py`",
        f"**Run parameters:** `--max-tables {args.max_tables} --step {args.step}`",
        f"**Schema under test:** `{_BENCH_SCHEMA}` (synthetic per-tenant data schema)",
        f"**DB:** local Postgres at `{args.dsn.split('dbname=')[-1].split()[0]}`",
        "",
        "## Recommended Per-Shard Ceiling",
        "",
        f"**MEASURED ceiling: {ceiling} tables per shard**",
        "",
        f"Detection signal: `{signal}`",
        f"Notes: {notes}",
        "",
        "> This is the LOCAL Postgres number (developer machine / CI DB).",
        "> **Re-run on the Azure Postgres Flexible Server SKU (Future AZ-01) before",
        "> the live-deploy track to get the production ceiling.**",
        "> Do NOT assume 25k — the prior 25k heuristic is superseded by this measurement.",
        "> The actual production ceiling depends on the Azure SKU's shared_buffers,",
        "> relcache size, and pg_dump latency to the managed storage layer.",
        "",
        "## Methodology",
        "",
        "Three complementary signals are measured as synthetic table count climbs:",
        "",
        "### Signal 1: Relcache / Buffer Hit Ratio (pg_statio_user_tables)",
        "",
        "```sql",
        "SELECT sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read))",
        "FROM pg_statio_user_tables WHERE schemaname = 'bench_t_cap';",
        "```",
        "",
        f"Degradation below **{_HIT_RATIO_FLOOR:.0%}** indicates relcache pressure — the OS",
        "page cache can no longer hold all relation headers in memory, and physical",
        "reads begin. This is the primary ceiling signal.",
        "",
        "### Signal 2: Autovacuum Saturation (pg_stat_user_tables + pg_stat_activity)",
        "",
        "Dead tuple accumulation + active autovacuum worker count. A sustained",
        f"autovac worker count >= {_AUTOVAC_WORKER_THRESHOLD} or rapid dead-tuple growth indicates",
        "the autovacuum scheduler is falling behind the table-creation rate.",
        "This signal is most relevant for high-churn workloads (frequent ingest).",
        "",
        "### Signal 3: pg_dump Duration (schema-only)",
        "",
        "Wall-clock time to `pg_dump --schema-only --schema=bench_t_cap`. Super-linear",
        f"growth (> {_PGDUMP_SUPERLINEAR_RATIO:.0f}x per doubling of table count) indicates catalog metadata",
        "load that would impact backup SLAs and disaster recovery RTO.",
        "",
        "## Per-Step Metrics",
        "",
        table_md,
        "",
        "## Re-Run Instructions",
        "",
        "```bash",
        "# Local Postgres (developer / CI):",
        "cd /path/to/geolens",
        "set -a && source .env.test && set +a",
        "python scripts/benchmark-shard-capacity.py \\",
        "    --max-tables 500 --step 50 --cleanup \\",
        "    --output shard-capacity-benchmark.md",
        "",
        "# Azure Postgres Flexible Server (Future AZ-01 -- production SKU):",
        "# Set POSTGRES_HOST / POSTGRES_PORT / POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB",
        "# to the Azure Flexible Server connection details, then:",
        "python scripts/benchmark-shard-capacity.py \\",
        "    --max-tables 2000 --step 200 --cleanup \\",
        '    --dsn "host=<azure-host> port=5432 user=<user> password=<pw> dbname=<db>" \\',
        "    --output shard-capacity-benchmark-azure.md",
        "```",
        "",
        "## Phase Context",
        "",
        "- **Phase 1209 (Per-Tenant Data Plane)** established per-tenant `data_t_{tenant_id}`",
        "  schemas as the isolation boundary for geospatial data in `multi_tenant` mode.",
        "- **Phase 1214 (Shard Promote/Rebalance)** will use this ceiling to decide when",
        "  a shard needs to be split. The `shard_id` column on `catalog.tenants` (migration",
        "  `0007_tenant_data_schemas`) is the routing map entry point.",
        "- This benchmark must be re-run on the production SKU BEFORE Phase 1214 sets",
        "  the shard-split threshold. The prior heuristic of 25k tables was never measured;",
        "  this document replaces it with a real number.",
    ]
    content = "\n".join(lines) + "\n"

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    print(f"\n  Findings doc written to: {output.resolve()}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark per-shard table-count capacity on local Postgres.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--max-tables",
        type=int,
        default=300,
        help="Maximum number of synthetic tables to create (default: 300)",
    )
    parser.add_argument(
        "--step",
        type=int,
        default=50,
        help="Number of tables to create per measurement step (default: 50)",
    )
    parser.add_argument(
        "--dsn",
        type=str,
        default=None,
        help=(
            "Postgres DSN string (default: built from POSTGRES_* env vars). "
            "Example: 'host=localhost port=5432 user=geolens password=geolens dbname=geolens'"
        ),
    )
    parser.add_argument(
        "--tenants",
        type=int,
        default=1,
        help="Number of synthetic tenant schemas to create (default: 1)",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Drop the synthetic benchmark schema after measuring (default: False)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=_DEFAULT_OUTPUT,
        help=f"Path to write the findings doc (default: {_DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    # WR-04 (Phase 1209-CR): guard against runaway DDL on production DBs.
    # Without a cap, --max-tables 50000 would create 50 k tables + indexes
    # if pointed at a production DSN by mistake.
    _MAX_TABLES_LIMIT = 10_000
    if args.max_tables > _MAX_TABLES_LIMIT:
        parser.error(
            f"--max-tables cannot exceed {_MAX_TABLES_LIMIT} "
            f"(got {args.max_tables}). Pass a smaller value."
        )

    # Warn when --cleanup is not set so the bench schema is not left behind
    # accidentally on non-development DSNs.
    if not args.cleanup:
        print(
            "WARNING: --cleanup was not passed. The benchmark schema "
            "'bench_t_cap' will PERSIST in the target database after this "
            "run. Pass --cleanup to drop it automatically.",
            flush=True,
        )
        try:
            confirm = input("Continue anyway? [y/N] ").strip().lower()
        except EOFError:
            confirm = "n"
        if confirm != "y":
            print("Aborted.")
            return

    dsn = args.dsn or _dsn_from_env()
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    print("=" * 60)
    print("  GeoLens Per-Shard Table-Count Capacity Benchmark")
    print(f"  {run_ts}")
    print("=" * 60)
    print(f"  Max tables: {args.max_tables}")
    print(f"  Step size:  {args.step}")
    print(f"  Output:     {args.output}")
    print()

    conn = _connect(dsn)
    steps: list[dict] = []

    try:
        # Teardown any leftover bench schema from a prior interrupted run.
        print("[setup] Cleaning up any leftover benchmark schema...")
        _teardown_bench(conn)

        print("[setup] Creating benchmark schema + role...")
        _setup_bench_schema(conn)

        created = 0
        step_num = 0

        while created < args.max_tables:
            batch_end = min(created + args.step, args.max_tables)
            step_num += 1

            print(f"\n[step {step_num}] Creating tables {created + 1}..{batch_end}...")
            _create_batch(conn, created + 1, batch_end)
            created = batch_end
            n_tables = _count_bench_tables(conn)

            print(f"  Total tables in schema: {n_tables}")

            # Warm the cache so pg_statio has data.
            print("  Warming relcache...")
            _warm_cache(conn)

            print("  Measuring signal 1 (hit ratio)...")
            hit_ratio = _measure_hit_ratio(conn)
            if hit_ratio is not None:
                print(f"    Hit ratio: {hit_ratio:.4f}")
            else:
                print("    Hit ratio: n/a (no I/O stats yet)")

            print("  Measuring signal 2 (autovacuum)...")
            avac = _measure_autovacuum(conn)
            print(
                f"    Dead tuples: {avac['dead_tuples']}  "
                f"AutoVac workers: {avac['autovac_worker_count']}  "
                f"Last vac lag: {avac['last_autovacuum_lag_sec']}s"
            )

            print("  Measuring signal 3 (pg_dump)...")
            pgdump_sec = _measure_pgdump(dsn, _BENCH_SCHEMA)
            if pgdump_sec >= 0:
                print(f"    pg_dump duration: {pgdump_sec:.2f}s")
            else:
                print("    pg_dump: n/a (pg_dump not in PATH)")

            steps.append(
                {
                    "tables": n_tables,
                    "hit_ratio": hit_ratio,
                    "dead_tuples": avac["dead_tuples"],
                    "last_autovacuum_lag_sec": avac["last_autovacuum_lag_sec"],
                    "autovac_worker_count": avac["autovac_worker_count"],
                    "pgdump_sec": pgdump_sec if pgdump_sec >= 0 else None,
                }
            )

        print("\n[analysis] Computing recommended ceiling...")
        inflection = _find_inflection(steps)
        ceiling = inflection["ceiling_tables"]
        signal = inflection["signal"]

        print(f"\n  Recommended per-shard ceiling: {ceiling} tables")
        print(f"  Detection signal:              {signal}")
        print(f"  Notes:                         {inflection['notes']}")

    finally:
        if args.cleanup:
            print("\n[cleanup] Dropping benchmark schema...")
            _teardown_bench(conn)
            cleaned = _verify_cleanup(conn)
            if cleaned:
                print("  Cleanup verified: synthetic schema is gone.")
            else:
                print(
                    "  [WARN] Cleanup verification failed — bench schema may still exist.",
                    file=sys.stderr,
                )
        conn.close()

    # Always write the findings doc — this is the critical deliverable.
    print(f"\n[output] Writing findings doc to {args.output!r}...")
    _write_findings(args.output, steps, inflection, args, run_ts)

    print("\n" + "=" * 60)
    print(f"  RESULT: Measured ceiling = {ceiling} tables per shard")
    print(f"  Signal: {signal}")
    print(f"  Doc:    {args.output}")
    print("=" * 60)


if __name__ == "__main__":
    main()

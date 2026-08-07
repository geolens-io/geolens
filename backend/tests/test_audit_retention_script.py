"""Functional guard for ``scripts/audit_retention.sh`` (#1248).

The audit-log retention procedure used to live in ``RUNBOOK.md`` as prose
bash+psql. Five review rounds found a real defect in that prose every round,
and prose cannot be executed, so nothing caught the sixth. This module runs the
script for real against a throwaway Postgres database with a stubbed export
endpoint, and pins the properties those five rounds were about:

* the export and the delete agree on one frozen cutoff, boundary row included;
* a per-tenant run never touches another tenant's rows, and an unresolvable
  slug aborts instead of falling through to an unscoped delete;
* archive filenames are unique per run, so a second run cannot truncate the
  first archive;
* a failed, truncated, non-JSON, or out-of-window export blocks the delete
  entirely — every one of those tests asserts the row count is *unchanged*, so
  a regression that deletes un-archived rows fails here;
* the external-Postgres connection path works, since an operator on a managed
  database has no ``db`` container to exec into.

The script talks to the database with ``psql`` and to the API with ``curl``.
``curl`` is replaced by a stub on ``PATH`` that serves the export out of the
same database, which is what makes the count/window verification meaningful
rather than tautological.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import uuid
from pathlib import Path
from urllib.parse import quote

import pytest

from app.core.config import settings

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "audit_retention.sh"

CONFIRM_PHRASE = "yes, this deployment has no per-tenant host routing"

# Generous next to the ~2s a real run takes here; small enough that a
# non-advancing split loop fails the suite rather than hanging it.
_SCRIPT_TIMEOUT_SECONDS = 120

_REQUIRED_TOOLS = ("psql", "jq")
_MISSING_TOOLS = [tool for tool in _REQUIRED_TOOLS if shutil.which(tool) is None]

# A silent skip here would make this the only gate on the script and have it
# report green while asserting nothing, so CI is not allowed to skip: a missing
# tool on a runner is a CI configuration bug and has to look like one.
if _MISSING_TOOLS and os.environ.get("CI"):
    raise RuntimeError(
        f"{', '.join(_MISSING_TOOLS)} missing on a CI runner; "
        "scripts/audit_retention.sh cannot be exercised without them."
    )

pytestmark = pytest.mark.skipif(
    bool(_MISSING_TOOLS),
    reason=f"requires {', '.join(_REQUIRED_TOOLS)} on PATH",
)

# Only the columns the script reads. test_scratch_schema_matches_the_models
# pins these against the real ORM models, so a rename cannot leave this DDL
# passing while the script breaks against a live database.
_SCRATCH_DDL = """
CREATE SCHEMA IF NOT EXISTS catalog;
CREATE TABLE catalog.tenants (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug varchar(63) NOT NULL UNIQUE
);
CREATE TABLE catalog.audit_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid,
    action varchar(50) NOT NULL,
    resource_type varchar(50) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
"""

# Stands in for `GET /admin/audit-logs/export/json`. It honours date_from,
# date_to and max_rows, returns newest-first like the real streaming generator,
# and is scoped to one tenant by RETENTION_SHIM_TENANT the way the real export
# is scoped by the host it is called against. RETENTION_SHIM_MODE injects the
# failure shapes the script must refuse to delete after.
_CURL_STUB = r'''#!/usr/bin/env python3
import json
import os
import subprocess
import sys
from urllib.parse import urlparse, parse_qs

argv = sys.argv[1:]
url = None
out = None
headers = []
i = 0
while i < len(argv):
    if argv[i] == "-o":
        out = argv[i + 1]
        i += 2
        continue
    if argv[i] == "-H":
        value = argv[i + 1]
        # Real curl reads headers from a file when the value starts with '@'.
        if value.startswith("@"):
            with open(value[1:]) as fh:
                headers.extend(line.rstrip("\n") for line in fh if line.strip())
        else:
            headers.append(value)
        i += 2
        continue
    if argv[i].startswith("http"):
        url = argv[i]
    i += 1

_argv_log = os.environ.get("RETENTION_ARGV_LOG")
if _argv_log:
    with open(_argv_log, "a") as fh:
        fh.write(json.dumps({"prog": "curl", "argv": argv}) + "\n")

if not any(h.startswith("Authorization: Bearer ") for h in headers):
    sys.stderr.write("curl stub: no Authorization header reached the request\n")
    sys.exit(1)

mode = os.environ.get("RETENTION_SHIM_MODE", "ok")
if mode == "http_error":
    if "--fail" in argv or "-f" in argv:
        sys.stderr.write("curl: (22) The requested URL returned error: 401\n")
        sys.exit(22)
    # Without --fail this is what real curl does: exit 0 and save the error
    # body as if it were the archive.
    with open(out, "w") as fh:
        fh.write('{"detail":"Not authenticated"}')
    sys.exit(0)

params = parse_qs(urlparse(url).query)
tenant = os.environ.get("RETENTION_SHIM_TENANT", "")
scope = "TRUE" if not tenant else "tenant_id = '%s'::uuid" % tenant
sql = """
SELECT coalesce(json_agg(t), '[]'::json) FROM (
  SELECT id::text AS id,
         to_char(created_at AT TIME ZONE 'UTC',
                 'YYYY-MM-DD"T"HH24:MI:SS.US"+00:00"') AS timestamp,
         action, resource_type
  FROM catalog.audit_logs
  WHERE created_at >= '%s'::timestamptz
    AND created_at <= '%s'::timestamptz
    AND %s
  ORDER BY created_at DESC
  LIMIT %d
) t
""" % (
    params["date_from"][0],
    params["date_to"][0],
    scope,
    int(params["max_rows"][0]),
)
# The script exports PGPASSWORD for its own psql when the URL carries a
# password, and this stub inherits it. Harmless for real curl, fatal for a stub
# that talks to Postgres, so the stub authenticates with credentials of its own
# that the script never touches.
_stub_env = os.environ.copy()
_stub_env["PGUSER"] = os.environ["RETENTION_STUB_PGUSER"]
_stub_env["PGPASSWORD"] = os.environ["RETENTION_STUB_PGPASSWORD"]
proc = subprocess.run(
    ["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-tA", "-c", sql],
    capture_output=True,
    text=True,
    env=_stub_env,
)
if proc.returncode != 0:
    sys.stderr.write(proc.stderr)
    sys.exit(1)
rows = json.loads(proc.stdout.strip())

if mode == "not_array":
    with open(out, "w") as fh:
        fh.write('{"detail":"Not authenticated"}')
    sys.exit(0)
if mode == "truncate" and rows:
    rows = rows[:-1]
if mode == "outside_window" and rows:
    rows[0]["timestamp"] = "1999-01-01T00:00:00.000000+00:00"
if mode == "drop_id":
    for row in rows:
        row.pop("id", None)

with open(out, "w") as fh:
    json.dump(rows, fh)
'''


# Records every psql command line, then hands off to the real binary. Used
# only by the argv-inspection tests, from a directory those tests prepend to
# PATH, so no other test pays for the extra hop.
_PSQL_RECORDER = r"""#!/usr/bin/env python3
import json
import os
import sys

log = os.environ["RETENTION_ARGV_LOG"]
with open(log, "a") as fh:
    fh.write(
        json.dumps(
            {
                "prog": "psql",
                "argv": sys.argv[1:],
                # The covert channel itself, so a test can prove the secret was
                # delivered and not merely absent from argv.
                "pgpassword": os.environ.get("PGPASSWORD"),
            }
        )
        + "\n"
    )

real = os.environ["RETENTION_REAL_PSQL"]
os.execv(real, [real] + sys.argv[1:])
"""


def _pg_env(dbname: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "PGHOST": settings.postgres_host,
            "PGPORT": str(settings.postgres_port),
            "PGUSER": settings.postgres_user,
            "PGPASSWORD": settings.postgres_password.get_secret_value(),
            "PGDATABASE": dbname,
        }
    )
    return env


def _psql(sql: str, dbname: str, check: bool = True) -> str:
    proc = subprocess.run(
        ["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-tA", "-c", sql],
        env=_pg_env(dbname),
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise AssertionError(f"psql failed: {proc.stderr.strip()}\nSQL: {sql}")
    return proc.stdout.strip()


@pytest.fixture(scope="module")
def scratch_db() -> str:
    """A database of this module's own, never the shared per-worker one.

    The single-tenant mode deletes every audit row before the cutoff. Pointed
    at the per-worker test database that would silently destroy rows other
    test files wrote, so the run gets a database nobody else can see.
    """
    admin_db = settings.postgres_db
    worker = os.environ.get("PYTEST_XDIST_WORKER", "master")
    name = f"geolens_auditret_{worker}_{uuid.uuid4().hex[:8]}"
    _psql(f'CREATE DATABASE "{name}"', admin_db)
    try:
        _psql(_SCRATCH_DDL, name)
        yield name
    finally:
        _psql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)', admin_db, check=False)


@pytest.fixture
def clean_audit_table(scratch_db: str) -> str:
    _psql("TRUNCATE catalog.audit_logs; TRUNCATE catalog.tenants CASCADE", scratch_db)
    return scratch_db


@pytest.fixture(scope="module")
def curl_stub_dir(tmp_path_factory) -> Path:
    bindir = tmp_path_factory.mktemp("stub-bin")
    stub = bindir / "curl"
    stub.write_text(_CURL_STUB)
    stub.chmod(0o755)
    return bindir


def _seed_tenant(db: str, slug: str) -> str:
    return _psql(
        f"INSERT INTO catalog.tenants (slug) VALUES ('{slug}') RETURNING id", db
    )


def _seed_rows(db: str, *, days_ago: list[int], tenant_id: str | None = None) -> None:
    tenant = "NULL" if tenant_id is None else f"'{tenant_id}'::uuid"
    values = ",".join(
        f"('audit.test', 'dataset', now() - interval '{d} days', {tenant})"
        for d in days_ago
    )
    _psql(
        "INSERT INTO catalog.audit_logs (action, resource_type, created_at, tenant_id) "
        f"VALUES {values}",
        db,
    )


def _row_count(db: str, tenant_id: str | None = None) -> int:
    where = "" if tenant_id is None else f" WHERE tenant_id = '{tenant_id}'::uuid"
    return int(_psql(f"SELECT count(*) FROM catalog.audit_logs{where}", db))


def _run_script(
    db: str,
    curl_stub_dir: Path,
    *args: str,
    shim_mode: str = "ok",
    shim_tenant: str = "",
    env_overrides: dict[str, str] | None = None,
    extra_path_dirs: list[Path] | None = None,
    path_override: str | None = None,
) -> subprocess.CompletedProcess:
    env = _pg_env(db)
    env["PATH"] = f"{curl_stub_dir}{os.pathsep}{env['PATH']}"
    env["ADMIN_TOKEN"] = "stub-token"
    env["RETENTION_SHIM_MODE"] = shim_mode
    env["RETENTION_SHIM_TENANT"] = shim_tenant
    env["RETENTION_STUB_PGUSER"] = settings.postgres_user
    env["RETENTION_STUB_PGPASSWORD"] = settings.postgres_password.get_secret_value()
    for extra in reversed(extra_path_dirs or []):
        env["PATH"] = f"{extra}{os.pathsep}{env['PATH']}"
    if path_override is not None:
        env["PATH"] = path_override
    if env_overrides:
        env.update(env_overrides)
    try:
        return subprocess.run(
            ["bash", str(SCRIPT), "--api-url", "https://example.invalid/api", *args],
            env=env,
            capture_output=True,
            text=True,
            # The window-splitting loop advances by moving WINDOW_FROM forward;
            # a regression that fails to advance re-exports the same rows
            # forever. Bounding the run turns that into a test failure instead
            # of a hung CI job.
            timeout=_SCRIPT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"{SCRIPT} did not finish within {_SCRIPT_TIMEOUT_SECONDS}s; the "
            "window-splitting loop is most likely not advancing."
        ) from exc


def _archives(archive_dir: Path) -> list[Path]:
    return sorted(archive_dir.glob("audit-archive-*.json"))


def _assert_windows_within_cap(stdout: str, max_rows: int) -> None:
    """No window the script asks the endpoint for may exceed the cap.

    This reads the sizes off the script's own per-window log rather than off
    the archives, and the difference matters. The real endpoint silently
    returns only the newest ``max_rows`` rows of an over-cap range, and the
    stub models that with a LIMIT -- so archive *lengths* can never exceed the
    cap no matter how badly the splitter behaves, and asserting on them would
    be vacuous. What can actually go wrong is the script sizing a window above
    the cap in the first place, which this reads directly.

    Measured caveat: in every scenario a faithful stub can produce, this is
    SHADOWED by the script's own archive/database row-count check, which fires
    first -- an over-cap window comes back truncated and the counts disagree.
    So treat this as defence in depth that states the intended property, not as
    the live gate. Verified by removing the over-cap handling entirely: the run
    failed on "archive row count mismatch ... counts 5 ... holds 4" before this
    assertion was reached.
    """
    sizes = [
        int(n) for n in re.findall(r"window \d+: \S+ \.\. \S+ \((\d+) rows\)", stdout)
    ]
    assert sizes, f"no per-window log lines found in:\n{stdout}"
    for size in sizes:
        assert size <= max_rows, (
            f"script requested a {size}-row window, above the {max_rows} cap"
        )


def _archived_rows(archive_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for path in _archives(archive_dir):
        rows.extend(json.loads(path.read_text()))
    return rows


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_archives_then_deletes_the_window(clean_audit_table, curl_stub_dir, tmp_path):
    db = clean_audit_table
    _seed_rows(db, days_ago=[200, 150, 120, 100, 95])
    _seed_rows(db, days_ago=[10, 5, 1])

    archive_dir = tmp_path / "archives"
    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(archive_dir),
    )

    assert result.returncode == 0, result.stderr
    # Proves the external-Postgres path was the one exercised, not a fallback.
    assert "Connecting via PG* environment variables" in result.stdout
    assert len(_archived_rows(archive_dir)) == 5
    assert _row_count(db) == 3


def test_dry_run_archives_without_deleting(clean_audit_table, curl_stub_dir, tmp_path):
    db = clean_audit_table
    _seed_rows(db, days_ago=[200, 150, 120])

    archive_dir = tmp_path / "archives"
    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(archive_dir),
        "--dry-run",
    )

    assert result.returncode == 0, result.stderr
    assert len(_archived_rows(archive_dir)) == 3
    assert _row_count(db) == 3


def test_external_db_url_strips_the_sqlalchemy_driver_suffix(
    clean_audit_table, curl_stub_dir, tmp_path
):
    """A privileged credential copied out of app config carries +asyncpg.

    libpq's URI parser accepts only postgresql:// and postgres://, so the
    suffix has to be stripped or the operator on a managed database cannot run
    the procedure at all.
    """
    db = clean_audit_table
    _seed_rows(db, days_ago=[200, 150])

    # No password in the URL: --db-url refuses one outright. The ambient
    # PGPASSWORD from _pg_env authenticates, which is the documented pairing.
    db_url = (
        f"postgresql+asyncpg://{settings.postgres_user}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{db}"
    )
    archive_dir = tmp_path / "archives"
    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(archive_dir),
        "--db-url",
        db_url,
    )

    assert result.returncode == 0, result.stderr
    assert "Connecting via --db-url" in result.stdout
    assert _row_count(db) == 0


def test_boundary_row_at_the_cutoff_is_archived_and_deleted(
    clean_audit_table, curl_stub_dir, tmp_path
):
    """The export's date_to is inclusive, so every step must use <=.

    A row landing exactly on the cutoff must be in the archive and in the
    delete. A delete using < would leave it; a count using < while the export
    used <= could displace an older row out of the archive at the cap and
    delete it anyway.
    """
    db = clean_audit_table
    _seed_rows(db, days_ago=[200, 150])
    _seed_rows(db, days_ago=[10])
    boundary = _psql(
        "INSERT INTO catalog.audit_logs (action, resource_type, created_at) "
        "VALUES ('audit.boundary', 'dataset', now() - interval '120 days') "
        "RETURNING to_char(created_at AT TIME ZONE 'UTC', "
        '\'YYYY-MM-DD"T"HH24:MI:SS.US"Z"\')',
        db,
    )

    archive_dir = tmp_path / "archives"
    result = _run_script(
        db,
        curl_stub_dir,
        "--cutoff",
        boundary,
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(archive_dir),
    )

    assert result.returncode == 0, result.stderr
    actions = [row["action"] for row in _archived_rows(archive_dir)]
    assert "audit.boundary" in actions
    # The 200-, 150- and 120-day rows are all at or before the cutoff; only the
    # 10-day row survives.
    assert _row_count(db) == 1
    surviving = _psql("SELECT DISTINCT action FROM catalog.audit_logs", db)
    assert surviving == "audit.test"


def test_window_over_the_export_cap_is_split_and_fully_archived(
    clean_audit_table, curl_stub_dir, tmp_path
):
    """One export call cannot return more than max_rows rows.

    Narrowing date_to alone does not help — the endpoint always returns the
    newest rows in the range — so the script has to partition the window. Every
    row must end up in some archive before any of them is deleted.
    """
    db = clean_audit_table
    _seed_rows(db, days_ago=list(range(100, 110)))

    archive_dir = tmp_path / "archives"
    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(archive_dir),
        "--max-rows",
        "3",
    )

    assert result.returncode == 0, result.stderr
    assert len(_archives(archive_dir)) > 1
    # Adjacent windows share their boundary instant, so a row can be archived
    # twice; what must never happen is a row archived zero times.
    archived = {row["timestamp"] for row in _archived_rows(archive_dir)}
    assert len(archived) == 10
    _assert_windows_within_cap(result.stdout, 3)
    assert _row_count(db) == 0


def test_max_rows_one_splits_a_two_row_window(
    clean_audit_table, curl_stub_dir, tmp_path
):
    """--max-rows 1 over two rows at distinct timestamps (#1260 review).

    The first sub-window boundary is the oldest row's own timestamp, so the
    window end equals the window start. That is a perfectly splittable window,
    not the unsplittable case: only one row sits at that instant. The loop has
    to export it and step to the next distinct timestamp.
    """
    db = clean_audit_table
    _seed_rows(db, days_ago=[200])
    _seed_rows(db, days_ago=[150])
    assert (
        int(_psql("SELECT count(DISTINCT created_at) FROM catalog.audit_logs", db)) == 2
    )

    archive_dir = tmp_path / "archives"
    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(archive_dir),
        "--max-rows",
        "1",
    )

    assert result.returncode == 0, result.stderr
    assert len(_archives(archive_dir)) == 2
    assert len({row["id"] for row in _archived_rows(archive_dir)}) == 2
    _assert_windows_within_cap(result.stdout, 1)
    assert _row_count(db) == 0


def test_cap_cutting_through_a_timestamp_tie_backs_off(
    clean_audit_table, curl_stub_dir, tmp_path
):
    """The export cap can land inside a group of rows sharing one instant.

    Two rows at t1 and three at t2 with --max-rows 4: the 4th oldest row is at
    t2, so the naive boundary [t1, t2] selects all five and looks unsplittable.
    It is not. [t1, t1] holds two and [t2, t2] holds three, both under the cap,
    so the split has to back off to the last distinct timestamp before the tie
    rather than give up. Scaled-down form of the 2-at-t1 plus 99-at-t2 case
    from the #1260 review.
    """
    db = clean_audit_table
    # One INSERT per group, so now() is evaluated once per group and each group
    # shares an instant.
    _seed_rows(db, days_ago=[200, 200])
    _seed_rows(db, days_ago=[150, 150, 150])
    assert (
        int(_psql("SELECT count(DISTINCT created_at) FROM catalog.audit_logs", db)) == 2
    )

    archive_dir = tmp_path / "archives"
    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(archive_dir),
        "--max-rows",
        "4",
    )

    assert result.returncode == 0, result.stderr
    assert len({row["id"] for row in _archived_rows(archive_dir)}) == 5
    _assert_windows_within_cap(result.stdout, 4)
    assert _row_count(db) == 0


def test_more_rows_at_one_instant_than_max_rows_deletes_nothing(
    clean_audit_table, curl_stub_dir, tmp_path
):
    """The genuinely unsplittable case still refuses.

    No choice of bounds makes a window exportable when one instant holds more
    rows than a single export call can return.
    """
    db = clean_audit_table
    # One INSERT statement, so now() is evaluated once and both rows land on
    # the identical timestamp.
    _seed_rows(db, days_ago=[200, 200])
    assert (
        int(_psql("SELECT count(DISTINCT created_at) FROM catalog.audit_logs", db)) == 1
    )

    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(tmp_path / "archives"),
        "--max-rows",
        "1",
    )

    assert result.returncode != 0
    assert "share the instant" in result.stderr
    assert _row_count(db) == 2


def test_repeated_runs_do_not_overwrite_an_earlier_archive(
    clean_audit_table, curl_stub_dir, tmp_path
):
    """Two runs of the same scope on the same day must not share a filename.

    The prose version wrote a name derived from the date alone, so the second
    ``curl -o`` truncated the first archive — possibly after those rows were
    already deleted.
    """
    db = clean_audit_table
    _seed_rows(db, days_ago=[200, 150])
    archive_dir = tmp_path / "archives"

    common = (
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(archive_dir),
        "--dry-run",
    )
    first = _run_script(db, curl_stub_dir, *common)
    second = _run_script(db, curl_stub_dir, *common)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert len(_archives(archive_dir)) == 2
    for path in _archives(archive_dir):
        assert len(json.loads(path.read_text())) == 2


# ---------------------------------------------------------------------------
# Tenant scoping
# ---------------------------------------------------------------------------


def test_per_tenant_run_leaves_other_tenants_untouched(
    clean_audit_table, curl_stub_dir, tmp_path
):
    db = clean_audit_table
    tenant_a = _seed_tenant(db, "alpha")
    tenant_b = _seed_tenant(db, "beta")
    _seed_rows(db, days_ago=[200, 150, 120], tenant_id=tenant_a)
    _seed_rows(db, days_ago=[5], tenant_id=tenant_a)
    _seed_rows(db, days_ago=[200, 150], tenant_id=tenant_b)

    archive_dir = tmp_path / "archives"
    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--tenant-slug",
        "alpha",
        "--archive-dir",
        str(archive_dir),
        shim_tenant=tenant_a,
    )

    assert result.returncode == 0, result.stderr
    assert len(_archived_rows(archive_dir)) == 3
    assert _row_count(db, tenant_a) == 1
    assert _row_count(db, tenant_b) == 2


def test_right_sized_slice_of_another_tenant_deletes_nothing(
    clean_audit_table, curl_stub_dir, tmp_path
):
    """--tenant-slug alpha paired with tenant beta's API host (#1260 review).

    Both tenants have three rows in the window, so the count check passes, and
    beta's rows are genuinely inside the same time range, so the timestamp
    check passes too. Without comparing row ids the script would archive
    beta's history and permanently delete alpha's, unarchived. The export
    schema carries no tenant id, so identity is the only signal available.
    """
    db = clean_audit_table
    tenant_a = _seed_tenant(db, "alpha")
    tenant_b = _seed_tenant(db, "beta")
    _seed_rows(db, days_ago=[200, 150, 120], tenant_id=tenant_a)
    _seed_rows(db, days_ago=[199, 149, 119], tenant_id=tenant_b)

    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--tenant-slug",
        "alpha",
        "--archive-dir",
        str(tmp_path / "archives"),
        # The stub is the wrong tenant's host, which is the whole scenario.
        shim_tenant=tenant_b,
    )

    assert result.returncode != 0
    assert "does not hold the rows this window would delete" in result.stderr
    assert _row_count(db, tenant_a) == 3
    assert _row_count(db, tenant_b) == 3


def test_archive_without_row_ids_deletes_nothing(
    clean_audit_table, curl_stub_dir, tmp_path
):
    """An export with no `id` field cannot be verified, so the run stops.

    The script and the API version together in this repo, so a server that
    does not send ids is an upgrade error, not a compatibility mode to fall
    back through.
    """
    db = clean_audit_table
    _seed_rows(db, days_ago=[200, 150])

    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(tmp_path / "archives"),
        shim_mode="drop_id",
    )

    assert result.returncode != 0
    assert 'has a row with no "id"' in result.stderr
    assert _row_count(db) == 2


def test_archives_are_not_world_readable(clean_audit_table, curl_stub_dir, tmp_path):
    """Archives hold usernames, IPs and activity for the whole window.

    Under the usual umask 022 `curl -o` would create them 0644, readable by
    every local account on the host.
    """
    db = clean_audit_table
    _seed_rows(db, days_ago=[200, 150])

    archive_dir = tmp_path / "archives"
    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(archive_dir),
        "--dry-run",
    )

    assert result.returncode == 0, result.stderr
    archives = _archives(archive_dir)
    assert archives, "expected at least one archive"
    for path in archives:
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600, f"{path} is {oct(mode)}, expected 0o600"
    assert stat.S_IMODE(archive_dir.stat().st_mode) == 0o700


def test_unresolvable_tenant_slug_deletes_nothing(
    clean_audit_table, curl_stub_dir, tmp_path
):
    db = clean_audit_table
    _seed_rows(db, days_ago=[200, 150])

    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--tenant-slug",
        "no-such-tenant",
        "--archive-dir",
        str(tmp_path / "archives"),
    )

    assert result.returncode != 0
    assert "no tenant found" in result.stderr
    assert _row_count(db) == 2


def test_no_scope_flag_is_refused(clean_audit_table, curl_stub_dir, tmp_path):
    db = clean_audit_table
    _seed_rows(db, days_ago=[200, 150])

    result = _run_script(
        db, curl_stub_dir, "--days", "90", "--archive-dir", str(tmp_path / "archives")
    )

    assert result.returncode != 0
    assert _row_count(db) == 2


def test_wrong_single_tenant_confirmation_is_refused(
    clean_audit_table, curl_stub_dir, tmp_path
):
    """The unscoped branch needs the exact phrase, typed by the operator.

    Nothing reads GEOLENS_TENANCY_MODE: a config-derived signal can be absent,
    stale, or injected by an orchestrator in a way the script cannot detect.
    """
    db = clean_audit_table
    _seed_rows(db, days_ago=[200, 150])

    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        "yes",
        "--archive-dir",
        str(tmp_path / "archives"),
    )

    assert result.returncode != 0
    assert "refusing to run unscoped" in result.stderr
    assert _row_count(db) == 2


# ---------------------------------------------------------------------------
# Export failures must block the delete
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("shim_mode", "expected_message"),
    [
        ("http_error", "export request failed"),
        ("not_array", "is not a JSON array"),
        ("truncate", "archive row count mismatch"),
        ("outside_window", "contains a row outside"),
    ],
)
def test_a_bad_export_deletes_nothing(
    clean_audit_table, curl_stub_dir, tmp_path, shim_mode, expected_message
):
    """Each of these once produced a "successful" run that deleted live rows.

    ``http_error`` is curl without --fail saving ``{"detail": ...}`` as the
    archive; ``not_array`` is a 200 carrying a proxy error page; ``truncate``
    is an export short of the window; ``outside_window`` is a right-sized
    archive holding the wrong rows.
    """
    db = clean_audit_table
    _seed_rows(db, days_ago=[200, 150, 120])

    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(tmp_path / "archives"),
        shim_mode=shim_mode,
    )

    assert result.returncode != 0
    assert expected_message in result.stderr
    assert _row_count(db) == 3


# ---------------------------------------------------------------------------
# Secrets must not reach child command lines
# ---------------------------------------------------------------------------

# Deliberately awkward: every character here has to be percent-encoded in a URI,
# and the literal '%' exercises the decoder's own escape.
_NASTY_PASSWORD = "p@ss/w:rd%x"
_NASTY_PASSWORD_ENCODED = "p%40ss%2Fw%3Ard%25x"


@pytest.fixture
def password_db():
    """Own database and own login role whose password needs encoding."""
    admin_db = settings.postgres_db
    worker = os.environ.get("PYTEST_XDIST_WORKER", "master")
    suffix = uuid.uuid4().hex[:8]
    name = f"geolens_auditpw_{worker}_{suffix}"
    role = f"geolens_auditpw_role_{worker}_{suffix}"

    _psql(f'CREATE DATABASE "{name}"', admin_db)
    _psql(f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{_NASTY_PASSWORD}'", admin_db)
    try:
        _psql(_SCRATCH_DDL, name)
        _psql(
            f"""
            GRANT USAGE ON SCHEMA catalog TO "{role}";
            GRANT SELECT, DELETE ON catalog.audit_logs TO "{role}";
            GRANT SELECT ON catalog.tenants TO "{role}";
            """,
            name,
        )
        yield name, role
    finally:
        _psql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)', admin_db, check=False)
        _psql(f'DROP ROLE IF EXISTS "{role}"', admin_db, check=False)


@pytest.fixture
def argv_recorder(tmp_path):
    """A `psql` on PATH that logs its command line, then execs the real one."""
    bindir = tmp_path / "recorder-bin"
    bindir.mkdir()
    shim = bindir / "psql"
    shim.write_text(_PSQL_RECORDER)
    shim.chmod(0o755)
    log = tmp_path / "argv.log"
    log.touch()
    return bindir, log


def _recorded(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def test_no_secret_reaches_a_child_command_line(
    password_db, argv_recorder, curl_stub_dir, tmp_path
):
    """Passwords and bearer tokens must never appear in argv (#1260 review).

    Command lines are world-readable through `ps` and /proc/<pid>/cmdline, so a
    URI handed straight to psql, or `-H "Authorization: Bearer ..."` handed to
    curl, publishes a BYPASSRLS credential and an admin token to every local
    account. Environment and 0600 files are owner-only and carry them instead.

    Absence alone would also be satisfied by dropping the secret entirely, so
    this asserts delivery too: the run succeeds against a password-protected
    role, and the recorded child environment carries the decoded password.
    """
    db, role = password_db
    _seed_rows(db, days_ago=[200, 150])
    recorder_dir, log = argv_recorder

    db_url = (
        f"postgresql://{role}:{_NASTY_PASSWORD_ENCODED}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{db}"
    )
    archive_dir = tmp_path / "archives"
    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(archive_dir),
        extra_path_dirs=[recorder_dir],
        env_overrides={
            "GEOLENS_RETENTION_DB_URL": db_url,
            "RETENTION_ARGV_LOG": str(log),
            "RETENTION_REAL_PSQL": shutil.which("psql"),
        },
    )

    assert result.returncode == 0, result.stderr
    calls = _recorded(log)
    assert calls, "the recorder captured no child processes"
    assert any(c["prog"] == "psql" for c in calls)
    assert any(c["prog"] == "curl" for c in calls)

    for call in calls:
        flat = " ".join(call["argv"])
        assert _NASTY_PASSWORD not in flat, f"password in {call['prog']} argv: {flat}"
        assert _NASTY_PASSWORD_ENCODED not in flat, (
            f"encoded password in {call['prog']} argv: {flat}"
        )
        assert "stub-token" not in flat, f"bearer token in {call['prog']} argv: {flat}"

    # Delivery: the decoded password reached psql by the environment. Only the
    # script's own psql calls are in scope -- the curl stub also runs psql, with
    # credentials of its own that the script never sets.
    script_psql = [
        c
        for c in calls
        if c["prog"] == "psql" and any(a.startswith("postgresql://") for a in c["argv"])
    ]
    assert script_psql, "the script made no psql call carrying the connection URL"
    assert all(c["pgpassword"] == _NASTY_PASSWORD for c in script_psql), [
        c["pgpassword"] for c in script_psql
    ]
    # The non-secret remainder of the URL stays in argv, which keeps ps useful.
    assert all(
        any(a.startswith(f"postgresql://{role}@") for a in c["argv"])
        for c in script_psql
    )
    assert _row_count(db) == 0


def test_a_wrong_password_in_the_url_fails_to_connect(
    password_db, curl_stub_dir, tmp_path
):
    """Negative control for the test above.

    Without this, a server that did not enforce password authentication would
    let the success there pass whether or not the password was ever delivered.
    """
    db, role = password_db
    _seed_rows(db, days_ago=[200, 150])

    db_url = (
        f"postgresql://{role}:definitely-not-the-password"
        f"@{settings.postgres_host}:{settings.postgres_port}/{db}"
    )
    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(tmp_path / "archives"),
        env_overrides={"GEOLENS_RETENTION_DB_URL": db_url},
    )

    assert result.returncode != 0
    assert "password authentication failed" in result.stderr.lower()
    assert _row_count(db) == 2


def test_a_malformed_percent_encoded_password_is_refused(
    password_db, curl_stub_dir, tmp_path
):
    """A stray '%' cannot be decoded, and guessing would mangle the password.

    Refusing names the workaround instead, rather than silently connecting with
    a wrong password or, worse, a half-decoded one.
    """
    db, role = password_db
    _seed_rows(db, days_ago=[200, 150])

    db_url = (
        f"postgresql://{role}:not%valid"
        f"@{settings.postgres_host}:{settings.postgres_port}/{db}"
    )
    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(tmp_path / "archives"),
        env_overrides={"GEOLENS_RETENTION_DB_URL": db_url},
    )

    assert result.returncode != 0
    assert "not valid percent-encoding" in result.stderr
    assert "PGPASSWORD" in result.stderr
    assert _row_count(db) == 2


def test_db_url_from_the_environment_avoids_the_scripts_own_argv(
    password_db, curl_stub_dir, tmp_path
):
    """The half --db-url cannot fix: the script's own command line.

    psql children are short-lived, but the script itself runs for the whole
    retention pass with whatever was typed on its command line. The env var is
    the way out, and passing a password through --db-url warns about it.
    """
    db, role = password_db
    _seed_rows(db, days_ago=[200, 150])

    db_url = (
        f"postgresql://{role}:{_NASTY_PASSWORD_ENCODED}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{db}"
    )
    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(tmp_path / "archives"),
        env_overrides={
            "GEOLENS_RETENTION_DB_URL": db_url,
        },
    )

    assert result.returncode == 0, result.stderr
    assert "Connecting via GEOLENS_RETENTION_DB_URL" in result.stdout
    assert _row_count(db) == 0


def test_a_password_on_the_command_line_is_refused(
    password_db, curl_stub_dir, tmp_path
):
    """--db-url must not carry a password at all.

    Moving it out of psql's command line achieves nothing while it sits in the
    script's own, which is world-readable and outlives every psql child. There
    is no way to retract that from inside, so the only fix is to decline the
    input and name the two carriers that do work.
    """
    db, role = password_db
    _seed_rows(db, days_ago=[200])

    db_url = (
        f"postgresql://{role}:{_NASTY_PASSWORD_ENCODED}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{db}"
    )
    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(tmp_path / "archives"),
        "--db-url",
        db_url,
    )

    assert result.returncode != 0
    assert "refusing a password in --db-url" in result.stderr
    # Both documented ways out are named, so the message is actionable alone.
    assert "GEOLENS_RETENTION_DB_URL" in result.stderr
    assert "PGPASSWORD" in result.stderr
    assert _row_count(db) == 1


def test_a_query_string_password_on_the_command_line_is_refused(
    password_db, curl_stub_dir, tmp_path
):
    """`?password=` is the second spelling of the same secret (#1260 review).

    libpq's URI grammar lets any connection keyword ride in the query string,
    `password` included, so a userinfo-only check leaves the refusal trivially
    bypassable.
    """
    db, role = password_db

    db_url = (
        f"postgresql://{role}@{settings.postgres_host}:{settings.postgres_port}"
        f"/{db}?password={_NASTY_PASSWORD_ENCODED}"
    )
    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(tmp_path / "archives"),
        "--db-url",
        db_url,
    )

    assert result.returncode != 0
    assert "refusing a password in --db-url" in result.stderr
    assert "?password=" in result.stderr


@pytest.mark.parametrize(
    ("keyword", "label"),
    [
        ("password", "plain"),
        # libpq percent-decodes the keyword, so these are the same parameter.
        ("%70assword", "leading byte encoded"),
        ("passwor%64", "trailing byte encoded"),
    ],
)
def test_a_query_string_password_is_extracted_and_delivered(
    password_db, argv_recorder, curl_stub_dir, tmp_path, keyword, label
):
    """Through the env var, a query password is moved to PGPASSWORD and works.

    Same delivery proof as the userinfo form: nothing secret in any child
    command line, and the run authenticates, so the password demonstrably
    arrived. The encoded spellings are here because matching "password=" as
    literal text would miss them while libpq would not.
    """
    db, role = password_db
    _seed_rows(db, days_ago=[200, 150])
    recorder_dir, log = argv_recorder

    db_url = (
        f"postgresql://{role}@{settings.postgres_host}:{settings.postgres_port}"
        f"/{db}?{keyword}={_NASTY_PASSWORD_ENCODED}"
    )
    archive_dir = tmp_path / "archives"
    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(archive_dir),
        extra_path_dirs=[recorder_dir],
        env_overrides={
            "GEOLENS_RETENTION_DB_URL": db_url,
            "RETENTION_ARGV_LOG": str(log),
            "RETENTION_REAL_PSQL": shutil.which("psql"),
        },
    )

    assert result.returncode == 0, result.stderr
    calls = _recorded(log)
    for call in calls:
        flat = " ".join(call["argv"])
        assert _NASTY_PASSWORD not in flat, f"password in {call['prog']} argv: {flat}"
        assert _NASTY_PASSWORD_ENCODED not in flat, (
            f"encoded password in {call['prog']} argv: {flat}"
        )

    script_psql = [
        c
        for c in calls
        if c["prog"] == "psql" and any(a.startswith("postgresql://") for a in c["argv"])
    ]
    assert script_psql, "the script made no psql call carrying the connection URL"
    assert all(c["pgpassword"] == _NASTY_PASSWORD for c in script_psql)
    # The parameter is gone and, being the only one, took its "?" with it.
    assert all(
        not any("?" in a for a in c["argv"] if a.startswith("postgresql://"))
        for c in script_psql
    )
    assert _row_count(db) == 0


def test_a_wrong_query_string_password_fails_to_connect(
    password_db, curl_stub_dir, tmp_path
):
    """Negative control for the extraction above."""
    db, role = password_db
    _seed_rows(db, days_ago=[200])

    db_url = (
        f"postgresql://{role}@{settings.postgres_host}:{settings.postgres_port}"
        f"/{db}?password=definitely-not-the-password"
    )
    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(tmp_path / "archives"),
        env_overrides={"GEOLENS_RETENTION_DB_URL": db_url},
    )

    assert result.returncode != 0
    assert "password authentication failed" in result.stderr.lower()
    assert _row_count(db) == 1


def test_other_query_parameters_survive_the_extraction(
    password_db, argv_recorder, curl_stub_dir, tmp_path
):
    """Removing a middle parameter must not corrupt the rest of the query."""
    db, role = password_db
    _seed_rows(db, days_ago=[200])
    recorder_dir, log = argv_recorder

    db_url = (
        f"postgresql://{role}@{settings.postgres_host}:{settings.postgres_port}"
        f"/{db}?application_name=retention"
        f"&password={_NASTY_PASSWORD_ENCODED}&connect_timeout=10"
    )
    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(tmp_path / "archives"),
        extra_path_dirs=[recorder_dir],
        env_overrides={
            "GEOLENS_RETENTION_DB_URL": db_url,
            "RETENTION_ARGV_LOG": str(log),
            "RETENTION_REAL_PSQL": shutil.which("psql"),
        },
    )

    assert result.returncode == 0, result.stderr
    urls = [
        a
        for c in _recorded(log)
        if c["prog"] == "psql"
        for a in c["argv"]
        if a.startswith("postgresql://")
    ]
    assert urls
    for url in urls:
        assert "password" not in url
        assert url.endswith("?application_name=retention&connect_timeout=10"), url
        assert "&&" not in url and "?&" not in url and not url.endswith("&")


def test_a_password_in_both_places_is_refused(password_db, curl_stub_dir, tmp_path):
    """Over-specified, and libpq resolves it in a surprising direction.

    Measured against libpq 18: the query parameter wins and the userinfo one is
    silently ignored, so an operator who changed the wrong half would connect
    with a credential they thought they had replaced. Refused rather than
    guessed at, and refused for both carriers.
    """
    db, role = password_db
    _seed_rows(db, days_ago=[200])

    db_url = (
        f"postgresql://{role}:{_NASTY_PASSWORD_ENCODED}"
        f"@{settings.postgres_host}:{settings.postgres_port}"
        f"/{db}?password={_NASTY_PASSWORD_ENCODED}"
    )
    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(tmp_path / "archives"),
        env_overrides={"GEOLENS_RETENTION_DB_URL": db_url},
    )

    assert result.returncode != 0
    assert "carries a password twice" in result.stderr
    assert _row_count(db) == 1


# ---------------------------------------------------------------------------
# The window has to be immutable
# ---------------------------------------------------------------------------


def test_a_future_cutoff_is_refused(clean_audit_table, curl_stub_dir, tmp_path):
    """The whole procedure assumes the window cannot change while it runs.

    Audit rows are written with created_at = now(), so a window ending in the
    future keeps gaining rows between the count, the export and the delete, and
    no count taken of it stays true. Exporting makes it concrete by writing its
    own audit.export rows inside the window, which the endpoint excludes from
    its output while a database-side query does not (#1260 review).
    """
    db = clean_audit_table
    _seed_rows(db, days_ago=[200, 150])

    future = _psql(
        "SELECT to_char((now() + interval '1 day') AT TIME ZONE 'UTC', "
        '\'YYYY-MM-DD"T"HH24:MI:SS.US"Z"\')',
        db,
    )
    result = _run_script(
        db,
        curl_stub_dir,
        "--cutoff",
        future,
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(tmp_path / "archives"),
    )

    assert result.returncode != 0
    assert "is not in the past" in result.stderr
    # The reason, not just the refusal: a reader has to learn why.
    assert "created_at = now()" in result.stderr
    assert _row_count(db) == 2


def test_a_cutoff_just_barely_in_the_future_is_refused(
    clean_audit_table, curl_stub_dir, tmp_path
):
    """The guard is `>= now()`, so far-future values are not all it catches.

    The exact boundary -- a cutoff equal to the script's own now() at the
    instant it checks -- cannot be reached from outside. Any timestamp captured
    before the script starts is already in the past by the time the script
    evaluates it, which is why the obvious version of this test passes for the
    wrong reason: it exercises a *past* cutoff. The `>=` in the source pins the
    boundary itself; this pins the region beside it, at a distance chosen to be
    immune to timing rather than to look tight.
    """
    db = clean_audit_table
    _seed_rows(db, days_ago=[200])

    soon = _psql(
        "SELECT to_char((now() + interval '60 seconds') AT TIME ZONE 'UTC', "
        '\'YYYY-MM-DD"T"HH24:MI:SS.US"Z"\')',
        db,
    )
    result = _run_script(
        db,
        curl_stub_dir,
        "--cutoff",
        soon,
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(tmp_path / "archives"),
    )

    assert result.returncode != 0
    assert "is not in the past" in result.stderr
    assert _row_count(db) == 1


def test_days_always_resolves_to_a_past_cutoff(
    clean_audit_table, curl_stub_dir, tmp_path
):
    """--days N for N >= 1 cannot trip the guard, so it needs no second check.

    This is the assertion that keeps that true rather than a second guard in
    the --days branch.
    """
    db = clean_audit_table
    _seed_rows(db, days_ago=[200])

    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "1",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(tmp_path / "archives"),
        "--dry-run",
    )

    assert result.returncode == 0, result.stderr
    assert "is not in the past" not in result.stderr


# ---------------------------------------------------------------------------
# Archives must not be committable
# ---------------------------------------------------------------------------


def test_default_archive_directory_is_gitignored():
    """Second line of defence behind the RUNBOOK's explicit --archive-dir.

    The default is ./audit-archives and the RUNBOOK tells operators to run the
    script from the repository root, so without this entry a later `git add .`
    would stage an export of usernames, IPs and activity.
    """

    def ignored(path: str) -> bool:
        return (
            subprocess.run(
                ["git", "check-ignore", "-q", path],
                cwd=REPO_ROOT,
                capture_output=True,
            ).returncode
            == 0
        )

    # Ask git rather than grep .gitignore: the property is that the path is
    # ignored, and a matching line could still be overridden by a later
    # negation. The second assertion is the positive control -- without it, a
    # check-ignore that always returned 0 would look identical to a pass.
    assert ignored("audit-archives/audit-archive-example.json")
    assert not ignored("backend/tests/test_audit_retention_script.py")


# ---------------------------------------------------------------------------
# Host tool requirements
# ---------------------------------------------------------------------------


@pytest.fixture
def path_without_psql(tmp_path, curl_stub_dir):
    """A PATH holding what the script needs, minus psql and docker.

    Symlinks rather than a copied PATH so the omission is explicit: anything
    not listed here genuinely is not on the PATH the script sees.
    """
    bindir = tmp_path / "minimal-bin"
    bindir.mkdir()
    for tool in (
        # bash runs the script; env/python3 back the curl stub's shebang.
        "bash",
        "env",
        "python3",
        "jq",
        "grep",
        "sed",
        "cat",
        "tr",
        "date",
        "mktemp",
        "basename",
        "dirname",
        "sort",
        "cmp",
        "comm",
        "wc",
        "rm",
    ):
        found = shutil.which(tool)
        if found:
            (bindir / tool).symlink_to(found)
    # curl comes from the stub directory, which also must not contain psql.
    assert not (curl_stub_dir / "psql").exists()
    return f"{curl_stub_dir}{os.pathsep}{bindir}"


def test_bundled_branch_does_not_require_a_host_psql(
    clean_audit_table, curl_stub_dir, tmp_path, path_without_psql
):
    """The documented default is Docker-only and never runs psql on the host.

    It execs psql *inside* the db container, so requiring the binary here
    aborted a correct install over something it does not use (#1260 review).
    The run still fails, at docker, which is the requirement this branch really
    has -- and failing there keeps the test from ever reaching a live stack.
    """
    result = _run_script(
        clean_audit_table,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(tmp_path / "archives"),
        path_override=path_without_psql,
        # Unset so the bundled branch is selected rather than the PG* one.
        env_overrides={"PGHOST": "", "PGSERVICE": ""},
    )

    assert "'psql' is required" not in result.stderr, result.stderr
    assert "'docker' is required" in result.stderr


def test_direct_connection_branch_still_requires_psql(
    clean_audit_table, curl_stub_dir, tmp_path, path_without_psql
):
    """The other half of the same rule: the branches that do run psql say so."""
    result = _run_script(
        clean_audit_table,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(tmp_path / "archives"),
        path_override=path_without_psql,
    )

    assert result.returncode != 0
    assert "'psql' is required" in result.stderr


# ---------------------------------------------------------------------------
# Row-level security
# ---------------------------------------------------------------------------


@pytest.fixture
def rls_db(curl_stub_dir):
    """A database whose audit table is RLS-protected, plus a non-bypass login.

    Its own database and its own role, both dropped afterwards, because the
    shared Postgres at :5434 is cluster-global: enabling RLS or leaving a role
    behind on the module-scoped scratch database would reach every other test.

    The policy uses the two-argument ``current_setting(..., true)`` so a session
    with no ``app.current_tenant`` gets NULL rather than an error. That is what
    reproduces the *silent* failure: the credential reads the table, matches
    nothing, and every count comes back 0.
    """
    admin_db = settings.postgres_db
    worker = os.environ.get("PYTEST_XDIST_WORKER", "master")
    suffix = uuid.uuid4().hex[:8]
    name = f"geolens_auditrls_{worker}_{suffix}"
    role = f"geolens_auditrls_role_{worker}_{suffix}"
    password = "rls-test-password"

    _psql(f'CREATE DATABASE "{name}"', admin_db)
    _psql(f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{password}'", admin_db)
    try:
        _psql(_SCRATCH_DDL, name)
        _psql(
            f"""
            ALTER TABLE catalog.audit_logs ENABLE ROW LEVEL SECURITY;
            CREATE POLICY tenant_isolation ON catalog.audit_logs
                USING (tenant_id = current_setting('app.current_tenant', true)::uuid);
            GRANT USAGE ON SCHEMA catalog TO "{role}";
            GRANT SELECT, DELETE ON catalog.audit_logs TO "{role}";
            GRANT SELECT ON catalog.tenants TO "{role}";
            """,
            name,
        )
        yield name, role, password
    finally:
        _psql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)', admin_db, check=False)
        _psql(f'DROP ROLE IF EXISTS "{role}"', admin_db, check=False)


def test_credential_that_cannot_bypass_rls_fails_loudly(
    rls_db, curl_stub_dir, tmp_path
):
    """A runtime login must not produce a silent, successful no-op (#1260 review).

    catalog.audit_logs carries a tenant_isolation policy, so the app's own
    least-privilege credential reads zero rows through it. The connectivity
    preflight cannot catch that: a ``LIMIT 0`` succeeds for a session RLS would
    filter to nothing. Without a per-query guard the run counts 0, reports
    "Nothing to archive or delete" and exits 0 while the table is untouched and
    growing.
    """
    db, role, password = rls_db
    _seed_rows(db, days_ago=[200, 150, 120])

    quoted = quote(password, safe="")
    runtime_url = (
        f"postgresql://{role}:{quoted}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{db}"
    )
    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(tmp_path / "archives"),
        env_overrides={"GEOLENS_RETENTION_DB_URL": runtime_url},
    )

    assert result.returncode != 0
    assert "row-level security" in (result.stderr + result.stdout).lower()
    assert "Nothing to archive or delete" not in result.stdout
    assert _row_count(db) == 3


def test_privileged_credential_still_works_against_the_same_rls_table(
    rls_db, curl_stub_dir, tmp_path
):
    """The RLS guard is a no-op for a session that can bypass it.

    Same database and same policy as the test above, so the credential is the
    only variable. A guard that failed closed for everyone would be useless.
    """
    db, _role, _password = rls_db
    _seed_rows(db, days_ago=[200, 150, 120])
    _seed_rows(db, days_ago=[5])

    archive_dir = tmp_path / "archives"
    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(archive_dir),
    )

    assert result.returncode == 0, result.stderr
    assert len(_archived_rows(archive_dir)) == 3
    assert _row_count(db) == 1


def test_row_security_set_does_not_leak_into_parsed_values(
    clean_audit_table, curl_stub_dir, tmp_path
):
    """`SET` must stay invisible under -tA, or every parsed value is corrupt.

    psql prints a "SET" command tag that -q suppresses. If it ever reached
    stdout it would be read as the first value of every query, so the cutoff
    and every count would be garbage. This pins the observable consequence
    rather than the flag.
    """
    db = clean_audit_table
    _seed_rows(db, days_ago=[200, 150, 120, 100, 95])

    result = _run_script(
        db,
        curl_stub_dir,
        "--days",
        "90",
        "--confirm-single-tenant",
        CONFIRM_PHRASE,
        "--archive-dir",
        str(tmp_path / "archives"),
        "--dry-run",
    )

    assert result.returncode == 0, result.stderr
    assert "Rows at or before the cutoff in scope: 5" in result.stdout
    assert "SET" not in [line.strip() for line in result.stdout.splitlines()]
    # A leaked tag would land in the cutoff string the run echoes back.
    cutoff_line = next(
        line for line in result.stdout.splitlines() if "Retention cutoff" in line
    )
    assert re.search(r": \d{4}-\d{2}-\d{2}T[\d:.]+Z$", cutoff_line), cutoff_line


# ---------------------------------------------------------------------------
# Drift guard
# ---------------------------------------------------------------------------


def test_scratch_schema_matches_the_models():
    """The stand-in DDL above must keep describing the real tables.

    Renaming a column the script reads would otherwise leave this module green
    while the script broke against a live database.
    """
    from app.modules.audit.models import AuditLog
    from app.modules.tenancy.models import Tenant

    assert AuditLog.__table__.schema == "catalog"
    assert AuditLog.__tablename__ == "audit_logs"
    assert {"id", "tenant_id", "created_at"} <= set(AuditLog.__table__.c.keys())

    assert Tenant.__table__.schema == "catalog"
    assert Tenant.__tablename__ == "tenants"
    assert {"id", "slug"} <= set(Tenant.__table__.c.keys())


def test_export_curl_invocation_keeps_fail():
    """--fail on the export call, asserted directly rather than by behaviour.

    The stub models curl faithfully: drop --fail and it exits 0 with the error
    body on disk, which the JSON-array check then catches. That layering is
    deliberate, and it also means no behavioural test goes red when --fail is
    removed. This one does.
    """
    body = SCRIPT.read_text()
    invocation = body.split("curl -sS", 1)
    assert len(invocation) == 2, "expected a `curl -sS` export invocation"
    # Up to the -o, i.e. the flags curl is actually called with.
    flags = invocation[1].split("-o ", 1)[0]
    assert "--fail" in flags


def test_script_is_executable_and_syntactically_valid():
    assert os.access(SCRIPT, os.X_OK), f"{SCRIPT} must be executable"
    proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr

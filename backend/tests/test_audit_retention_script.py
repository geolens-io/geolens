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
i = 0
while i < len(argv):
    if argv[i] == "-o":
        out = argv[i + 1]
        i += 2
        continue
    if argv[i].startswith("http"):
        url = argv[i]
    i += 1

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
proc = subprocess.run(
    ["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-tA", "-c", sql],
    capture_output=True,
    text=True,
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
) -> subprocess.CompletedProcess:
    env = _pg_env(db)
    env["PATH"] = f"{curl_stub_dir}{os.pathsep}{env['PATH']}"
    env["ADMIN_TOKEN"] = "stub-token"
    env["RETENTION_SHIM_MODE"] = shim_mode
    env["RETENTION_SHIM_TENANT"] = shim_tenant
    return subprocess.run(
        ["bash", str(SCRIPT), "--api-url", "https://example.invalid/api", *args],
        env=env,
        capture_output=True,
        text=True,
    )


def _archives(archive_dir: Path) -> list[Path]:
    return sorted(archive_dir.glob("audit-archive-*.json"))


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

    password = quote(settings.postgres_password.get_secret_value(), safe="")
    db_url = (
        f"postgresql+asyncpg://{settings.postgres_user}:{password}"
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
    assert _row_count(db) == 0


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

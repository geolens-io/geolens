"""fix(#1778): S3 offsite backups were never pruned.

upload_to_s3 only ever ran `aws s3 cp` — nothing in backup-entrypoint.sh ever
removed an object from `backups/<prefix>/` — so with BACKUP_S3_ENABLED=true
the bucket grew without bound while RUNBOOK's Retention section documents a
fixed "N daily / N weekly" policy with no stated exemption for the offsite
copies. prune_s3_prefix() mirrors prune_old_backups' keep-newest-N-by-
timestamp policy and prune_orphaned_companions' pairing rule against the S3
prefix, gated behind the same BACKUP_S3_ENABLED an operator already opted
into (no new env var).

These tests run the REAL prune_s3_prefix function — extracted from
scripts/backup-entrypoint.sh at test time so the harness cannot drift —
against a stub `aws` CLI that serves a canned `aws s3 ls` listing and records
every `aws s3 rm` call.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)
SCRIPT = REPO_ROOT / "scripts" / "backup-entrypoint.sh"

_AWS_STUB = """#!/bin/sh
case "$1 $2" in
    "configure set")
        exit 0
        ;;
    "s3 ls")
        if [ "${AWS_STUB_LS_EXIT:-0}" != "0" ]; then
            exit "${AWS_STUB_LS_EXIT}"
        fi
        cat "${AWS_STUB_LS_FILE}"
        ;;
    "s3 rm")
        echo "$3" >> "${AWS_STUB_DELETED_FILE}"
        exit "${AWS_STUB_RM_EXIT:-0}"
        ;;
    *)
        exit 0
        ;;
esac
"""

# Four dumps (oldest to newest: 08-01..08-04) with companions on the oldest
# (should be pruned as orphans once their dump ages out) and the newest
# (should survive, a positive control that pruning doesn't over-delete).
_LS_LISTING = "\n".join(
    [
        "2026-08-01 02:00:00        100 geolens_20260801_020000.dump",
        "2026-08-01 02:05:00         50 globals-20260801_020000.sql",
        "2026-08-01 02:05:00         80 staging-20260801_020000.tar.gz",
        "2026-08-02 02:00:00        100 geolens_20260802_020000.dump",
        "2026-08-03 02:00:00        100 geolens_20260803_020000.dump",
        "2026-08-04 02:00:00        100 geolens_20260804_020000.dump",
        "2026-08-04 02:05:00         50 globals-20260804_020000.sql",
    ]
)


def _extract_function(name: str) -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    match = re.search(
        rf"^{re.escape(name)}\(\) \{{.*?^\}}", source, re.DOTALL | re.MULTILINE
    )
    assert match, (
        f"{name}() not found in {SCRIPT}; if the function was renamed or "
        f"moved, update this test."
    )
    return match.group(0)


def _extract_prune_s3_prefix() -> str:
    # fix(#1778 review round 2, P1): prune_s3_prefix calls
    # s3_newest_complete_ts (the S3 analogue of the local newest-complete-set
    # protection) — a separate function, so it must be extracted alongside
    # prune_s3_prefix or the harness fails with "command not found".
    return f"{_extract_function('s3_newest_complete_ts')}\n{_extract_function('prune_s3_prefix')}"


def _extract_run_backup_definitions() -> str:
    """Everything before the "# Entry point" section: variable defaults
    (BACKUP_DIR/DAILY_DIR/WEEKLY_DIR/STAGING_DIR/... — all env-overridable,
    which is what makes this fixture possible), the retention-value
    validation, and every function run_backup() calls (backup_staging,
    backup_globals, upload_to_s3, prune_old_backups,
    prune_orphaned_companions, prune_s3_prefix, run_backup itself). Cutting
    before "# Entry point" is what excludes the cron/sleep-loop dispatch —
    everything kept here is a definition or an idempotent setup step (mkdir,
    a retention check) driven entirely by the env this harness controls.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    marker_idx = source.index("# Entry point")
    header_idx = source.rindex("# ---", 0, marker_idx)
    return source[:header_idx]


# Real commands run_backup() shells out to, none of which exist on a bare
# test runner. Each stub does the minimal real filesystem work the calling
# code depends on (pg_dump must actually create the file its caller `mv`s
# into place) and nothing else.
_PG_DUMP_STUB = """#!/bin/sh
prev=""
for arg in "$@"; do
    if [ "$prev" = "-f" ]; then
        printf 'fake dump bytes\\n' > "$arg"
    fi
    prev="$arg"
done
exit 0
"""

_PG_RESTORE_STUB = """#!/bin/sh
cat > /dev/null
exit 0
"""

_PG_DUMPALL_STUB = """#!/bin/sh
echo '-- fake globals dump'
exit 0
"""


def _run(
    tmp_path: Path,
    keep: str = "2",
    ls_listing: str | None = _LS_LISTING,
    ls_exit: int = 0,
    rm_exit: int = 0,
    with_credentials: bool = True,
) -> tuple[subprocess.CompletedProcess, list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ls_file = tmp_path / "ls_output.txt"
    ls_file.write_text((ls_listing + "\n") if ls_listing else "")
    deleted_file = tmp_path / "deleted.txt"
    deleted_file.write_text("")

    aws_stub = bin_dir / "aws"
    aws_stub.write_text(_AWS_STUB)
    aws_stub.chmod(0o755)

    creds = (
        'S3_BUCKET="test-bucket"\n'
        'S3_ACCESS_KEY_ID="test-key"\n'
        'S3_SECRET_ACCESS_KEY="test-secret"\n'
        if with_credentials
        else ""
    )
    harness = (
        "set -euo pipefail\n"
        'log() { echo "$@" >&2; }\n'
        f"{creds}"
        f"{_extract_prune_s3_prefix()}\n"
        f'prune_s3_prefix "daily" "{keep}"\n'
    )
    result = subprocess.run(
        ["bash", "-c", harness],
        capture_output=True,
        text=True,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "AWS_STUB_LS_FILE": str(ls_file),
            "AWS_STUB_DELETED_FILE": str(deleted_file),
            "AWS_STUB_LS_EXIT": str(ls_exit),
            "AWS_STUB_RM_EXIT": str(rm_exit),
        },
    )
    deleted = [line for line in deleted_file.read_text().splitlines() if line.strip()]
    return result, deleted


class TestPruneS3Prefix:
    def test_prunes_oldest_dumps_beyond_retention(self, tmp_path: Path):
        """With keep=2, the naive count would prune 08-01 AND 08-02 (the two
        oldest of four). But 08-04 is the newest COMPLETE set (fixture has
        globals for 08-01 and 08-04 only) and is held back in addition to
        the retention window (see test_protects_newest_complete_set_from_count_based_pruning
        below), so only 3 dumps are ever candidates and just 1 is pruned."""
        result, deleted = _run(tmp_path, keep="2")
        assert result.returncode == 0, result.stderr
        assert "s3://test-bucket/backups/daily/geolens_20260801_020000.dump" in deleted
        assert (
            "s3://test-bucket/backups/daily/geolens_20260802_020000.dump" not in deleted
        )
        assert (
            "s3://test-bucket/backups/daily/geolens_20260803_020000.dump" not in deleted
        )
        assert (
            "s3://test-bucket/backups/daily/geolens_20260804_020000.dump" not in deleted
        )

    def test_prunes_orphaned_companions_of_pruned_dumps(self, tmp_path: Path):
        result, deleted = _run(tmp_path, keep="2")
        assert result.returncode == 0, result.stderr
        assert "s3://test-bucket/backups/daily/globals-20260801_020000.sql" in deleted
        assert (
            "s3://test-bucket/backups/daily/staging-20260801_020000.tar.gz" in deleted
        )

    def test_keeps_companion_of_a_surviving_dump(self, tmp_path: Path):
        """Positive control: the 08-04 globals companion must NOT be treated
        as orphaned just because pruning ran — its dump is still kept."""
        result, deleted = _run(tmp_path, keep="2")
        assert result.returncode == 0, result.stderr
        assert (
            "s3://test-bucket/backups/daily/globals-20260804_020000.sql" not in deleted
        )

    def test_within_retention_deletes_nothing(self, tmp_path: Path):
        result, deleted = _run(tmp_path, keep="10")
        assert result.returncode == 0, result.stderr
        assert deleted == []

    def test_protects_newest_complete_set_from_count_based_pruning(
        self, tmp_path: Path
    ):
        """fix(#1778 review round 2, P1): a partial upload cycle (the dump
        uploads, the globals upload fails) must not destroy the only
        complete offsite set. 08-01 is the only complete pair (dump +
        globals); 08-02 is a partial cycle (dump only). With
        BACKUP_RETENTION_DAILY=1, the naive count would see 2 dumps, keep 1
        (08-02, the newest), and prune 08-01's dump — then its now-orphaned
        globals right behind it in the same cycle, leaving nothing a
        disaster-recovery restore could rebuild roles from. Protecting the
        newest COMPLETE set means 08-01 is excluded from the count
        entirely, leaving only 1 real candidate (08-02) against keep=1: no
        pruning at all. Everything survives."""
        listing = "\n".join(
            [
                "2026-08-01 02:00:00        100 geolens_20260801_020000.dump",
                "2026-08-01 02:05:00         50 globals-20260801_020000.sql",
                "2026-08-02 02:00:00        100 geolens_20260802_020000.dump",
            ]
        )
        result, deleted = _run(tmp_path, keep="1", ls_listing=listing)
        assert result.returncode == 0, result.stderr
        assert deleted == [], (
            "the only complete offsite set (or the partial dump beside it) "
            f"was pruned: {deleted}"
        )

    def test_older_complete_set_still_prunes_beyond_the_protected_budget(
        self, tmp_path: Path
    ):
        """Positive control for the fix above: protection is scoped to the
        SINGLE newest complete set, not every complete set — pruning must
        still work normally once there is more than one candidate beyond
        it. 08-01 and 08-03 are both complete (dump + globals); 08-02 is a
        partial cycle (dump only, the newest complete set's globals upload
        having failed on an intervening cycle). With keep=1, 08-03 (newest
        complete) is protected and excluded from the count, leaving 08-01
        and 08-02 as the 2 real candidates against keep=1: the older one,
        08-01, is pruned — dump and its now-orphaned globals both."""
        listing = "\n".join(
            [
                "2026-08-01 02:00:00        100 geolens_20260801_020000.dump",
                "2026-08-01 02:05:00         50 globals-20260801_020000.sql",
                "2026-08-02 02:00:00        100 geolens_20260802_020000.dump",
                "2026-08-03 02:00:00        100 geolens_20260803_020000.dump",
                "2026-08-03 02:05:00         50 globals-20260803_020000.sql",
            ]
        )
        result, deleted = _run(tmp_path, keep="1", ls_listing=listing)
        assert result.returncode == 0, result.stderr
        assert "s3://test-bucket/backups/daily/geolens_20260801_020000.dump" in deleted
        assert "s3://test-bucket/backups/daily/globals-20260801_020000.sql" in deleted
        assert (
            "s3://test-bucket/backups/daily/geolens_20260802_020000.dump" not in deleted
        )
        assert (
            "s3://test-bucket/backups/daily/geolens_20260803_020000.dump" not in deleted
        )
        assert (
            "s3://test-bucket/backups/daily/globals-20260803_020000.sql" not in deleted
        )

    def test_empty_prefix_does_not_abort_under_set_e(self, tmp_path: Path):
        """The prefix has zero objects (fresh install, or weekly/ before the
        first Sunday cycle). Before the fix this used `grep` to filter the S3
        listing; under this script's `set -euo pipefail`, `grep` matching
        nothing exits 1 and would abort the whole cycle on this ordinary,
        expected case — not just skip pruning."""
        result, deleted = _run(tmp_path, keep="2", ls_listing="")
        assert result.returncode == 0, result.stderr
        assert deleted == []

    def test_listing_failure_is_reported_and_fails(self, tmp_path: Path):
        result, _deleted = _run(tmp_path, keep="2", ls_exit=1)
        assert result.returncode != 0
        assert "could not list" in result.stderr

    def test_missing_credentials_refuses_without_calling_aws(self, tmp_path: Path):
        result, deleted = _run(tmp_path, keep="2", with_credentials=False)
        assert result.returncode != 0
        assert deleted == []
        assert "S3_BUCKET" in result.stderr

    def test_rm_failure_is_reported_and_fails(self, tmp_path: Path):
        """fix(#1778 review, P2): `aws s3 rm` failing inside either deletion
        loop (retention pruning, then orphaned-companion pruning) used to
        just log an ERROR and continue — both loops run in a `| while`
        subshell, so a `local` failure flag set there never reached this
        function's own scope, and the pipeline (and therefore this function)
        still exited 0. Both loops now use `< <(...)` process substitution
        so the loop body runs in THIS shell, and a failed deletion must make
        this function return nonzero — the same treatment a listing failure
        already gets."""
        result, deleted = _run(tmp_path, keep="2", rm_exit=1)
        assert result.returncode != 0
        # The deletions were attempted (and reported) — this is not the
        # missing-credentials early return, which never calls `aws` at all.
        assert deleted != []
        assert "could not delete" in result.stderr


def _run_full_cycle(
    tmp_path: Path, rm_exit: int = 0
) -> tuple[subprocess.CompletedProcess, Path]:
    """Runs the REAL run_backup() end to end (extracted from
    scripts/backup-entrypoint.sh, same technique as _run above), stubbing
    only the external commands it shells out to: aws (S3), pg_dump,
    pg_restore, pg_dumpall. Everything else (mkdir, retention pruning,
    file writes) is the real filesystem, real awk/sed/find/cut, real bash
    control flow.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    backup_dir = tmp_path / "backups"
    staging_dir = tmp_path / "no-such-staging-mount"  # never created: skips cleanly

    ls_file = tmp_path / "ls_output.txt"
    ls_file.write_text(_LS_LISTING + "\n")
    deleted_file = tmp_path / "deleted.txt"
    deleted_file.write_text("")

    for name, content in (
        ("aws", _AWS_STUB),
        ("pg_dump", _PG_DUMP_STUB),
        ("pg_restore", _PG_RESTORE_STUB),
        ("pg_dumpall", _PG_DUMPALL_STUB),
    ):
        stub = bin_dir / name
        stub.write_text(content)
        stub.chmod(0o755)

    harness = f"{_extract_run_backup_definitions()}\nrun_backup\n"
    result = subprocess.run(
        ["bash", "-c", harness],
        capture_output=True,
        text=True,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "BACKUP_DIR": str(backup_dir),
            "STAGING_DIR": str(staging_dir),
            "POSTGRES_DB": "geolens",
            "POSTGRES_HOST": "db",
            "POSTGRES_USER": "geolens",
            "POSTGRES_PASSWORD": "test-password",
            # Matches _LS_LISTING's 4 dumps: keep=2 forces the S3 retention
            # loop to actually attempt deletions, not just list an
            # already-within-budget prefix.
            "BACKUP_RETENTION_DAILY": "2",
            "BACKUP_RETENTION_WEEKLY": "2",
            "BACKUP_S3_ENABLED": "true",
            "S3_BUCKET": "test-bucket",
            "S3_ACCESS_KEY_ID": "test-key",
            "S3_SECRET_ACCESS_KEY": "test-secret",
            "AWS_STUB_LS_FILE": str(ls_file),
            "AWS_STUB_DELETED_FILE": str(deleted_file),
            "AWS_STUB_LS_EXIT": "0",
            "AWS_STUB_RM_EXIT": str(rm_exit),
        },
    )
    return result, backup_dir / ".last-success"


class TestRunBackupS3PruneFailureMarksCycleFailed:
    """fix(#1778 review, P2): the fix in TestPruneS3Prefix.
    test_rm_failure_is_reported_and_fails proves prune_s3_prefix() itself
    now returns nonzero on a failed deletion. These tests prove that
    failure actually reaches run_backup()'s caller-visible signal — the
    `.last-success` freshness marker the compose healthcheck reads — by
    running a REAL (stub-backed) backup cycle end to end, not just the
    prune function in isolation.
    """

    def test_rm_failure_leaves_last_success_untouched(self, tmp_path: Path):
        result, marker = _run_full_cycle(tmp_path, rm_exit=1)
        assert result.returncode != 0, result.stderr
        assert not marker.exists(), (
            "run_backup touched .last-success despite a failed S3 deletion — "
            "the healthcheck would report this cycle healthy"
        )
        # The real log() (unlike _run's test-only override above) writes to
        # stdout, not stderr.
        assert "could not delete" in result.stdout

    def test_successful_cycle_still_touches_last_success(self, tmp_path: Path):
        """Positive control: the fix must not make an otherwise-healthy
        cycle report unhealthy."""
        result, marker = _run_full_cycle(tmp_path, rm_exit=0)
        assert result.returncode == 0, result.stderr
        assert marker.exists()

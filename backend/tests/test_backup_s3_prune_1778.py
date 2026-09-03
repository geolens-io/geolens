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
against a stub `aws` CLI that serves a canned `aws s3api list-objects-v2`
JSON listing and records
every `aws s3 rm` call.
"""

from __future__ import annotations

import json
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
    "s3api list-objects-v2")
        # fix(#1778 review round 6, P2): the real script now calls this
        # instead of `aws s3 ls` (see s3_list_prefix's comment) — the
        # stub still ignores the actual --bucket/--prefix/--output args
        # and always serves the canned response, same as the old `s3 ls`
        # case did for the s3:// URI argument.
        if [ "${AWS_STUB_LS_EXIT:-0}" != "0" ]; then
            # fix(#1778 review round 3): a real listing failure writes to
            # stderr; an empty-prefix "success with no objects" writes
            # NOTHING to either stream. AWS_STUB_LS_STDERR lets each test
            # choose which one it is driving, independent of the exit
            # code value.
            [ -n "${AWS_STUB_LS_STDERR:-}" ] && printf '%s\n' "${AWS_STUB_LS_STDERR}" >&2
            exit "${AWS_STUB_LS_EXIT}"
        fi
        cat "${AWS_STUB_LS_FILE}"
        ;;
    "s3 rm")
        echo "$3" >> "${AWS_STUB_DELETED_FILE}"
        # fix(#1778 review round 3, P2) test support: a uniform
        # AWS_STUB_RM_EXIT can't tell "the dump's own deletion failed" apart
        # from "a companion's deletion was wrongly attempted" — both would
        # just be one more failed rm. AWS_STUB_RM_FAIL_PATTERN fails only
        # the object whose name contains it, so the two are distinguishable.
        if [ -n "${AWS_STUB_RM_FAIL_PATTERN:-}" ]; then
            case "$3" in
                *"${AWS_STUB_RM_FAIL_PATTERN}"*) exit 1 ;;
                *) exit 0 ;;
            esac
        fi
        exit "${AWS_STUB_RM_EXIT:-0}"
        ;;
    "s3 cp")
        # fix(#1778 review round 5, P2) test support: records every upload
        # destination so a test can prove a DAILY artifact reached
        # upload_to_s3 even when the WEEKLY copy step that runs before it
        # (inside backup_staging/backup_globals) failed. Opt-in via
        # AWS_STUB_UPLOADED_FILE so existing callers that never set it are
        # unaffected.
        [ -n "${AWS_STUB_UPLOADED_FILE:-}" ] && echo "$4" >> "${AWS_STUB_UPLOADED_FILE}"
        exit 0
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
        "geolens_20260801_020000.dump",
        "globals-20260801_020000.sql",
        "staging-20260801_020000.tar.gz",
        "geolens_20260802_020000.dump",
        "geolens_20260803_020000.dump",
        "geolens_20260804_020000.dump",
        "globals-20260804_020000.sql",
    ]
)


def _ls_json(listing: str | None) -> str:
    """fix(#1778 review round 6, P2) test support: the real script now
    calls `aws s3api list-objects-v2 --output json` instead of `aws s3
    ls` — the stub's canned response is JSON, built here from the same
    plain "one bare key per line" fixtures every test already used
    (previously interpreted as `aws s3 ls`'s bare filename column).
    Deliberately does NOT prefix each key with "backups/<prefix>/" the
    way a real bucket listing would — s3_list_prefix's `key.startswith`
    strip is then simply a no-op on these already-bare keys, which
    still exercises exactly what these tests care about: that a key's
    exact characters (including spaces) survive the round trip.
    """
    names = [line for line in (listing or "").splitlines() if line.strip()]
    return json.dumps({"Contents": [{"Key": name} for name in names]})


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
    # prune_s3_prefix calls two separate functions that must be extracted
    # alongside it or the harness fails with "command not found":
    # s3_newest_complete_ts (fix(#1778 review round 2, P1) — the S3 analogue
    # of the local newest-complete-set protection) and s3_list_prefix
    # (fix(#1778 review round 3, updated round 6 for the aws s3api
    # list-objects-v2 switch) — distinguishes an empty prefix from a
    # genuine listing failure).
    return (
        f"{_extract_function('s3_list_prefix')}\n"
        f"{_extract_function('s3_newest_complete_ts')}\n"
        f"{_extract_function('prune_s3_prefix')}"
    )


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

# fix(#1778 review round 3, P1): same portable shim
# scripts/tests/test-backup-restore-roundtrip.sh already uses to force a
# Sunday cycle without depending on the day the test happens to run — only
# `+%u` is faked, every other format (the real timestamp naming the dump)
# passes through to a real `date` binary.
_DATE_STUB = """#!/bin/sh
case "$*" in "+%u") echo 7; exit 0;; esac
for real in /bin/date /usr/bin/date; do [ -x "$real" ] && exec "$real" "$@"; done
exit 127
"""


def _run(
    tmp_path: Path,
    keep: str = "2",
    ls_listing: str | None = _LS_LISTING,
    ls_exit: int = 0,
    ls_stderr: str = "",
    rm_exit: int = 0,
    rm_fail_pattern: str = "",
    with_credentials: bool = True,
) -> tuple[subprocess.CompletedProcess, list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ls_file = tmp_path / "ls_output.txt"
    ls_file.write_text(_ls_json(ls_listing))
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
            "AWS_STUB_LS_STDERR": ls_stderr,
            "AWS_STUB_RM_FAIL_PATTERN": rm_fail_pattern,
            "AWS_STUB_RM_EXIT": str(rm_exit),
        },
    )
    deleted = [line for line in deleted_file.read_text().splitlines() if line.strip()]
    return result, deleted


def _run_prune_s3_prefix_with_real_log(
    tmp_path: Path, ls_exit: int, ls_stderr: str
) -> subprocess.CompletedProcess:
    """Like _run() above, but keeps the SCRIPT's real log() — a plain
    `echo "[$timestamp] $*"` with no redirect, i.e. stdout — instead of
    _run's own test-only `log() { echo "$@" >&2; }` override. That override
    sends every log call to stderr regardless of whether the call site in
    the script does, which would make
    test_listing_failure_diagnostic_reaches_stderr below pass on both fixed
    and pre-fix code and prove nothing about fix(#1778 review round 3, P2).
    Uses _extract_run_backup_definitions() purely for its real log() (same
    extraction _run_full_cycle uses); S3 credentials are exported directly
    so prune_s3_prefix can run standalone without a full run_backup cycle.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ls_file = tmp_path / "ls_output.txt"
    ls_file.write_text(_ls_json(None))
    deleted_file = tmp_path / "deleted.txt"
    deleted_file.write_text("")

    aws_stub = bin_dir / "aws"
    aws_stub.write_text(_AWS_STUB)
    aws_stub.chmod(0o755)

    harness = (
        f"{_extract_run_backup_definitions()}\n"
        'S3_BUCKET="test-bucket"\n'
        'S3_ACCESS_KEY_ID="test-key"\n'
        'S3_SECRET_ACCESS_KEY="test-secret"\n'
        'prune_s3_prefix "daily" "2"\n'
    )
    return subprocess.run(
        ["bash", "-c", harness],
        capture_output=True,
        text=True,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "BACKUP_DIR": str(tmp_path / "backups"),
            "AWS_STUB_LS_FILE": str(ls_file),
            "AWS_STUB_DELETED_FILE": str(deleted_file),
            "AWS_STUB_LS_EXIT": str(ls_exit),
            "AWS_STUB_LS_STDERR": ls_stderr,
            "AWS_STUB_RM_FAIL_PATTERN": "",
            "AWS_STUB_RM_EXIT": "0",
        },
    )


class TestS3ListPrefixDiagnosticReachesStderr:
    """fix(#1778 review round 3, P2): scripts/backup-entrypoint.sh:563 —
    s3_list_prefix's caller captures its stdout via
    `ls_output="$(s3_list_prefix ...)"`. A `log` call with no explicit
    `>&2` at the call site (the script's real log() is a plain
    unredirected `echo`) would be swallowed into that command substitution
    instead of reaching the container's stdout/stderr log at all — the
    operator would see only the generic "offsite objects were not pruned"
    line from prune_s3_prefix, with the actual aws CLI error nowhere.
    """

    def test_listing_failure_diagnostic_reaches_stderr(self, tmp_path: Path):
        result = _run_prune_s3_prefix_with_real_log(
            tmp_path,
            ls_exit=1,
            ls_stderr="An error occurred (AccessDenied) when calling the ListObjectsV2 operation",
        )
        assert result.returncode != 0
        assert "could not list" in result.stderr, (
            "the listing-failure diagnostic did not reach stderr — got "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )


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
                "geolens_20260801_020000.dump",
                "globals-20260801_020000.sql",
                "geolens_20260802_020000.dump",
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
                "geolens_20260801_020000.dump",
                "globals-20260801_020000.sql",
                "geolens_20260802_020000.dump",
                "geolens_20260803_020000.dump",
                "globals-20260803_020000.sql",
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
        first Sunday cycle) and `aws s3 ls` exits 0 with empty output.
        Before the fix this used `grep` to filter the S3 listing; under this
        script's `set -euo pipefail`, `grep` matching nothing exits 1 and
        would abort the whole cycle on this ordinary, expected case — not
        just skip pruning."""
        result, deleted = _run(tmp_path, keep="2", ls_listing="")
        assert result.returncode == 0, result.stderr
        assert deleted == []

    def test_empty_prefix_aws_cli_exit_1_is_not_a_failure(self, tmp_path: Path):
        """fix(#1778 review round 3): documented AWS CLI behavior — `aws s3
        ls` on a prefix with NO objects exits 1 with EMPTY stdout AND empty
        stderr. This is the ordinary shape for backups/weekly/ before the
        first Sunday cycle (CI's "Backup Restore Round-trip" bundled-mode
        job: one cycle in, weekly/ has nothing yet), not a failure. Before
        this fix, any nonzero exit was treated as a hard listing failure and
        aborted the cycle outright, even though the daily upload it ran
        alongside had already succeeded."""
        result, deleted = _run(
            tmp_path, keep="2", ls_listing="", ls_exit=1, ls_stderr=""
        )
        assert result.returncode == 0, result.stderr
        assert deleted == []
        assert "could not list" not in result.stderr

    def test_listing_failure_is_reported_and_fails(self, tmp_path: Path):
        """A GENUINE listing failure (bad creds, unreachable endpoint,
        missing s3:ListBucket) writes to stderr — that's what distinguishes
        it from the empty-prefix exit 1 above, which writes nothing to
        either stream."""
        result, _deleted = _run(
            tmp_path,
            keep="2",
            ls_exit=1,
            ls_stderr="An error occurred (AccessDenied) when calling the ListObjectsV2 operation",
        )
        assert result.returncode != 0
        assert "could not list" in result.stderr

    def test_listing_failure_with_unusual_exit_code_and_no_output_still_fails(
        self, tmp_path: Path
    ):
        """A non-1 exit code (an aws CLI crash, a network-level abort) with
        empty output must still be treated as a failure — the "no failure"
        carve-out is scoped to exit 1 specifically, matching the documented
        empty-prefix behavior, not to "any exit code with empty output"."""
        result, _deleted = _run(
            tmp_path, keep="2", ls_listing="", ls_exit=255, ls_stderr=""
        )
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

    def test_failed_dump_deletion_does_not_orphan_its_companions(self, tmp_path: Path):
        """fix(#1778 review round 3, P2): with keep=2, 08-01 is the single
        retention candidate (08-04 is protected as the newest complete set;
        see test_protects_newest_complete_set_from_count_based_pruning) and
        is pruned along with its globals/staging companions. Here the
        08-01 DUMP's own `aws s3 rm` fails — AWS_STUB_RM_FAIL_PATTERN
        targets only that one object, so if its companions' rm calls are
        even attempted, they succeed and show up in `deleted`. Before this
        fix, a failed dump deletion still dropped the dump's timestamp from
        the kept set, so the very next loop read its companions as orphaned
        and deleted them — a complete backup set losing its dump-deletion
        race would end up with globals/staging but no dump, or worse here,
        losing everything but the (still-present) dump."""
        result, deleted = _run(
            tmp_path,
            keep="2",
            rm_fail_pattern="geolens_20260801_020000.dump",
        )
        assert result.returncode != 0, (
            "the dump deletion failure must still be reported"
        )
        assert (
            "s3://test-bucket/backups/daily/geolens_20260801_020000.dump" in deleted
        ), "the dump deletion itself was never attempted"
        assert (
            "s3://test-bucket/backups/daily/globals-20260801_020000.sql" not in deleted
        ), "a companion was pruned as an orphan after its dump's rm failed"
        assert (
            "s3://test-bucket/backups/daily/staging-20260801_020000.tar.gz"
            not in deleted
        ), "a companion was pruned as an orphan after its dump's rm failed"

    def test_dump_key_containing_a_space_is_pruned_by_its_real_name(
        self, tmp_path: Path
    ):
        """fix(#1778 review round 5, P2): `s3_list_prefix`'s output was
        parsed with `awk '{print $NF}'` — the LAST whitespace-separated
        field — everywhere a listing line was turned into an object key.
        POSTGRES_DB="geo lens" produces a dump named "geo
        lens_<ts>.dump"; $NF truncates that to "lens_<ts>.dump", so
        retention pruning issues `aws s3 rm` against a key that was never
        actually in the bucket — the real object survives, accumulates
        forever, and every cycle reports success at deleting something it
        never touched. With keep=2 and 3 dump-only entries (no globals, so
        none is a "complete" set eligible for protection), 08-01 is the
        single prune candidate."""
        listing = "\n".join(
            [
                "geo lens_20260801_020000.dump",
                "geo lens_20260802_020000.dump",
                "geo lens_20260803_020000.dump",
            ]
        )
        result, deleted = _run(tmp_path, keep="2", ls_listing=listing)
        assert result.returncode == 0, result.stderr
        assert (
            "s3://test-bucket/backups/daily/geo lens_20260801_020000.dump" in deleted
        ), f"the real (space-containing) key was never targeted: {deleted}"
        assert (
            "s3://test-bucket/backups/daily/lens_20260801_020000.dump" not in deleted
        ), f"a truncated key was targeted instead of the real one: {deleted}"

    def test_orphaned_companion_key_with_a_space_is_deleted_by_its_real_name(
        self, tmp_path: Path
    ):
        """fix(#1778 review round 5, P2): the final orphan-companion loop
        parsed the SAME listing with the same `awk '{print $NF}'` bug. No
        globals-*.sql/staging-*.tar.gz name in this script embeds a space
        today (POSTGRES_DB only ever reaches the *.dump filename), but the
        parsing bug is generic to any key in that position, so this pins it
        directly against a stubbed listing rather than waiting for it to
        recur naturally. The companion's timestamp (20260901_030000) never
        matches the one kept dump (20260801_020000), so it is an orphan
        regardless of the fix — only the rm TARGET should change."""
        listing = "\n".join(
            [
                "geolens_20260801_020000.dump",
                "globals extra-20260901_030000.sql",
            ]
        )
        result, deleted = _run(tmp_path, keep="2", ls_listing=listing)
        assert result.returncode == 0, result.stderr
        assert (
            "s3://test-bucket/backups/daily/globals extra-20260901_030000.sql"
            in deleted
        ), f"the real (space-containing) companion key was never targeted: {deleted}"
        assert (
            "s3://test-bucket/backups/daily/extra-20260901_030000.sql" not in deleted
        ), f"a truncated companion key was targeted instead: {deleted}"

    def test_dump_key_with_leading_and_internal_spaces_is_pruned_by_its_real_name(
        self, tmp_path: Path
    ):
        """fix(#1778 review round 6, P2): round 5's fixed-column `read -r
        _d _t _s name` fixed INTERNAL spaces (it let the last variable
        absorb the rest of the line) but `read` ALSO strips LEADING
        whitespace off the field it assigns — POSTGRES_DB=" geo" produces
        a dump named " geo_<ts>.dump" (leading space), which round 5's own
        fix still silently turned into "geo_<ts>.dump". This is exactly
        why round 6 replaced the whitespace-column listing with JSON
        (s3_list_prefix now shells out to `aws s3api list-objects-v2`) —
        there is no whitespace-splitting step left to lose the leading
        space. With keep=2 and 3 dump-only entries, 08-01 is the single
        prune candidate."""
        listing = "\n".join(
            [
                " geo_20260801_020000.dump",
                " geo_20260802_020000.dump",
                " geo_20260803_020000.dump",
            ]
        )
        result, deleted = _run(tmp_path, keep="2", ls_listing=listing)
        assert result.returncode == 0, result.stderr
        assert "s3://test-bucket/backups/daily/ geo_20260801_020000.dump" in deleted, (
            f"the real (leading-space) key was never targeted: {deleted}"
        )
        assert (
            "s3://test-bucket/backups/daily/geo_20260801_020000.dump" not in deleted
        ), f"a leading-space-stripped key was targeted instead: {deleted}"


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
    ls_file.write_text(_ls_json(_LS_LISTING))
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


def _run_weekly_copy_failure_cycle(
    tmp_path: Path, weekly_dir_writable: bool = False
) -> tuple[subprocess.CompletedProcess, Path, Path]:
    """Runs a REAL Sunday run_backup() cycle (same extraction technique as
    _run_full_cycle) with BACKUP_S3_ENABLED=false, so this isolates the
    LOCAL retention path from the S3 path _run_full_cycle above already
    covers. WEEKLY_DIR is made read-only by default so the weekly dump
    copy's `cp` genuinely fails — the "nearly full volume" case
    fix(#1778 review round 3, P1) describes — via the shell (not a mock),
    the same way the CI-failure fix a commit ago used a real `aws s3 ls`
    rather than stubbing the distinction. Three pre-existing daily dumps
    with no globals companions (so none is a "complete" set eligible for
    newest_complete_ts protection) are seeded old enough that
    BACKUP_RETENTION_DAILY=1 must prune some of them once today's dump is
    added, proving retention still runs.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, content in (
        ("date", _DATE_STUB),
        ("pg_dump", _PG_DUMP_STUB),
        ("pg_restore", _PG_RESTORE_STUB),
        ("pg_dumpall", _PG_DUMPALL_STUB),
    ):
        stub = bin_dir / name
        stub.write_text(content)
        stub.chmod(0o755)

    backup_dir = tmp_path / "backups"
    daily_dir = backup_dir / "daily"
    weekly_dir = backup_dir / "weekly"
    staging_dir = tmp_path / "no-such-staging-mount"

    daily_dir.mkdir(parents=True)
    for ts in ("20260101_020000", "20260102_020000", "20260103_020000"):
        (daily_dir / f"geolens_{ts}.dump").write_text("old dump bytes\n")

    extra_setup = "" if weekly_dir_writable else 'chmod 555 "$WEEKLY_DIR"\n'
    harness = f"{_extract_run_backup_definitions()}\n{extra_setup}run_backup\n"
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
            "BACKUP_RETENTION_DAILY": "1",
            "BACKUP_RETENTION_WEEKLY": "4",
            "BACKUP_S3_ENABLED": "false",
        },
    )
    weekly_dir.chmod(0o755)  # let tmp_path teardown clean up regardless
    return result, daily_dir, backup_dir / ".last-success"


class TestWeeklyCopyFailureStillPrunesDaily:
    """fix(#1778 review round 3, P1): scripts/backup-entrypoint.sh:155 — a
    Sunday cycle whose weekly copy fails (typically a nearly full volume)
    used to `return` immediately, skipping prune_old_backups/prune_s3_prefix
    for BOTH daily/ and weekly/ entirely. The next cycle then ran out of
    space before it could ever prune either. The fix marks the cycle failed
    and falls through to retention, matching how the staging/globals paths
    already behaved.
    """

    def test_weekly_copy_failure_still_prunes_daily_and_reports_failed(
        self, tmp_path: Path
    ):
        result, daily_dir, marker = _run_weekly_copy_failure_cycle(tmp_path)
        assert result.returncode != 0, (
            "a failed weekly copy must fail the cycle: " + result.stdout
        )
        assert not marker.exists(), (
            ".last-success was touched despite a failed weekly copy"
        )
        remaining = sorted(p.name for p in daily_dir.glob("*.dump"))
        assert "geolens_20260101_020000.dump" not in remaining, (
            "daily retention did not prune the oldest dump after a failed "
            f"weekly copy — daily/ still holds: {remaining}"
        )

    def test_successful_weekly_copy_is_unaffected(self, tmp_path: Path):
        """Positive control: with WEEKLY_DIR writable, the same cycle (same
        retention config, same pre-seeded old dumps) succeeds outright —
        proving the failure above comes from the read-only weekly copy, not
        from some other part of the fixture."""
        result, daily_dir, marker = _run_weekly_copy_failure_cycle(
            tmp_path, weekly_dir_writable=True
        )
        assert result.returncode == 0, result.stdout
        assert marker.exists()
        remaining = sorted(p.name for p in daily_dir.glob("*.dump"))
        assert "geolens_20260101_020000.dump" not in remaining


def _run_weekly_staging_globals_upload_cycle(
    tmp_path: Path, weekly_dir_writable: bool = False
) -> tuple[subprocess.CompletedProcess, list[str]]:
    """fix(#1778 review round 5, P2) regression harness: a real Sunday
    run_backup() cycle with BACKUP_S3_ENABLED=true and a non-empty
    STAGING_DIR (so backup_staging does not take its early "not mounted" /
    "empty" skip), while WEEKLY_DIR is read-only by default so the weekly
    copy step inside both backup_staging and backup_globals fails — the
    same "nearly full volume" shape TestWeeklyCopyFailureStillPrunesDaily
    above drives against the dump copy. Every `aws s3 cp` destination is
    recorded via AWS_STUB_UPLOADED_FILE so the test can prove the DAILY
    staging archive and globals dump still reached upload_to_s3 despite the
    weekly-copy failure.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, content in (
        ("date", _DATE_STUB),
        ("pg_dump", _PG_DUMP_STUB),
        ("pg_restore", _PG_RESTORE_STUB),
        ("pg_dumpall", _PG_DUMPALL_STUB),
        ("aws", _AWS_STUB),
    ):
        stub = bin_dir / name
        stub.write_text(content)
        stub.chmod(0o755)

    backup_dir = tmp_path / "backups"
    weekly_dir = backup_dir / "weekly"
    staging_dir = tmp_path / "staging"
    staging_dir.mkdir()
    (staging_dir / "object.bin").write_text("staged object bytes\n")

    ls_file = tmp_path / "ls_output.txt"
    ls_file.write_text(_ls_json(None))
    deleted_file = tmp_path / "deleted.txt"
    deleted_file.write_text("")
    uploaded_file = tmp_path / "uploaded.txt"
    uploaded_file.write_text("")

    extra_setup = "" if weekly_dir_writable else 'chmod 555 "$WEEKLY_DIR"\n'
    harness = f"{_extract_run_backup_definitions()}\n{extra_setup}run_backup\n"
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
            "BACKUP_RETENTION_DAILY": "7",
            "BACKUP_RETENTION_WEEKLY": "4",
            "BACKUP_S3_ENABLED": "true",
            "S3_BUCKET": "test-bucket",
            "S3_ACCESS_KEY_ID": "test-key",
            "S3_SECRET_ACCESS_KEY": "test-secret",
            "AWS_STUB_LS_FILE": str(ls_file),
            "AWS_STUB_DELETED_FILE": str(deleted_file),
            "AWS_STUB_UPLOADED_FILE": str(uploaded_file),
            "AWS_STUB_LS_EXIT": "0",
        },
    )
    weekly_dir.chmod(0o755)  # let tmp_path teardown clean up regardless
    uploaded = [line for line in uploaded_file.read_text().splitlines() if line.strip()]
    return result, uploaded


class TestWeeklyCopyFailureStillUploadsDailyArtifact:
    """fix(#1778 review round 5, P2): scripts/backup-entrypoint.sh:351 — on
    a Sunday with WEEKLY_DIR unwritable but DAILY_DIR fine, backup_staging
    returned after publishing the daily archive but before printing its
    path, so `staging_archive="$(backup_staging "$timestamp")"` came back
    empty and the valid daily artifact was never handed to upload_to_s3 —
    not even under the daily/ prefix. backup_globals had the identical
    shape for the globals dump. Both now fall through to their final printf
    regardless of the weekly-copy outcome, matching how run_backup's own
    weekly dump copy already behaves (dump_ok only gates a copy the dump
    itself failed to survive, never a copy that just couldn't reach
    WEEKLY_DIR).
    """

    def test_daily_artifacts_still_upload_despite_weekly_copy_failure(
        self, tmp_path: Path
    ):
        result, uploaded = _run_weekly_staging_globals_upload_cycle(tmp_path)
        assert result.returncode != 0, (
            "a failed weekly copy must still fail the cycle: " + result.stdout
        )
        assert any("daily/staging-" in line for line in uploaded), (
            f"the daily staging archive was never uploaded — uploads: {uploaded}"
        )
        assert any("daily/globals-" in line for line in uploaded), (
            f"the daily globals dump was never uploaded — uploads: {uploaded}"
        )

    def test_successful_weekly_copy_uploads_both_daily_and_weekly(self, tmp_path: Path):
        """Positive control: with WEEKLY_DIR writable, the same cycle
        succeeds and uploads reach both prefixes."""
        result, uploaded = _run_weekly_staging_globals_upload_cycle(
            tmp_path, weekly_dir_writable=True
        )
        assert result.returncode == 0, result.stdout
        assert any("daily/staging-" in line for line in uploaded)
        assert any("daily/globals-" in line for line in uploaded)
        assert any("weekly/staging-" in line for line in uploaded)
        assert any("weekly/globals-" in line for line in uploaded)

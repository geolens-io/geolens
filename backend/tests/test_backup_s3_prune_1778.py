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


def _extract_prune_s3_prefix() -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    match = re.search(
        r"^prune_s3_prefix\(\) \{.*?^\}", source, re.DOTALL | re.MULTILINE
    )
    assert match, (
        f"prune_s3_prefix() not found in {SCRIPT}; if the function was "
        f"renamed or moved, update this test."
    )
    return match.group(0)


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
        result, deleted = _run(tmp_path, keep="2")
        assert result.returncode == 0, result.stderr
        assert "s3://test-bucket/backups/daily/geolens_20260801_020000.dump" in deleted
        assert "s3://test-bucket/backups/daily/geolens_20260802_020000.dump" in deleted
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

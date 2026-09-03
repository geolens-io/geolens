"""fix(#843): backup_staging must tolerate tar's live-write-skew exit (1).

GNU tar exits 1 ("some files differ", e.g. "file changed as we read it") when
api/worker write to the staging volume mid-archive; the archive is still fully
written and every quiescent file in it is sound. Only exit >= 2 is a fatal tar
error. Before the fix, exit 1 deleted the archive and failed the cycle, so the
fix(#712) freshness healthcheck sat unhealthy on any busy install.

These tests run the REAL backup_staging function — extracted from
scripts/backup-entrypoint.sh at test time so the harness cannot drift — against
a stub tar forced to each exit code.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)
SCRIPT = REPO_ROOT / "scripts" / "backup-entrypoint.sh"


def _extract_backup_staging() -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"^backup_staging\(\) \{.*?^\}", source, re.DOTALL | re.MULTILINE)
    assert match, (
        f"backup_staging() not found in {SCRIPT}; if the function was renamed "
        f"or moved, update this test."
    )
    return match.group(0)


def _run_cycle(
    tmp_path: Path, tar_exit: int, verify_exit: int = 0
) -> tuple[subprocess.CompletedProcess, Path]:
    staging = tmp_path / "staging"
    daily = tmp_path / "daily"
    weekly = tmp_path / "weekly"
    bin_dir = tmp_path / "bin"
    for d in (staging, daily, weekly, bin_dir):
        d.mkdir()
    (staging / "object.bin").write_bytes(b"payload")

    # Stub tar mirrors real tar's exit-1 behavior: the archive IS written.
    # Invocation shape is `tar czf <archive>.tmp -C <dir> .` for the write and
    # `tar tzf <archive>.tmp` for the fix(#1778) verification step that runs
    # afterwards — dispatch on $1 so the two calls can be driven independently.
    tar_stub = bin_dir / "tar"
    tar_stub.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "czf" ]; then\n'
        '    echo stub-archive > "$2"\n'
        f"    exit {tar_exit}\n"
        "fi\n"
        f"exit {verify_exit}\n"
    )
    tar_stub.chmod(0o755)

    harness = (
        "set -euo pipefail\n"
        'log() { echo "$@" >&2; }\n'
        f'STAGING_DIR="{staging}"\n'
        f'DAILY_DIR="{daily}"\n'
        f'WEEKLY_DIR="{weekly}"\n'
        f"{_extract_backup_staging()}\n"
        'backup_staging "20260728_000000"\n'
    )
    result = subprocess.run(
        ["bash", "-c", harness],
        capture_output=True,
        text=True,
        env={"PATH": f"{bin_dir}:/usr/bin:/bin"},
    )
    archive = daily / "staging-20260728_000000.tar.gz"
    return result, archive


class TestBackupStagingTarSkew:
    def test_tar_success_archives_and_prints_path(self, tmp_path: Path):
        result, archive = _run_cycle(tmp_path, tar_exit=0)
        assert result.returncode == 0, result.stderr
        assert archive.exists()
        assert str(archive) in result.stdout

    def test_tar_live_write_skew_keeps_archive_and_succeeds(self, tmp_path: Path):
        """Exit 1 = files changed mid-archive: warn, keep the archive, continue."""
        result, archive = _run_cycle(tmp_path, tar_exit=1)
        assert result.returncode == 0, result.stderr
        assert archive.exists()
        assert str(archive) in result.stdout
        assert "WARNING" in result.stderr
        assert "ERROR" not in result.stderr

    def test_tar_fatal_error_removes_archive_and_fails(self, tmp_path: Path):
        """Exit >= 2 = fatal tar error: the cycle must still fail."""
        result, archive = _run_cycle(tmp_path, tar_exit=2)
        assert result.returncode != 0
        assert not archive.exists()
        assert "ERROR: object-storage archive failed" in result.stderr

    def test_tar_writes_to_tmp_name_before_publishing(self, tmp_path: Path):
        """fix(#1778): `tar czf` must target `<archive>.tmp`, not the final
        name directly — before the fix it wrote straight to `staging-*.tar.gz`,
        so a container killed mid-write (OOM, `compose stop`, disk full) left
        a truncated archive sitting under its final name, indistinguishable
        from a good one until restore.sh tried to extract it."""
        source = _extract_backup_staging()
        assert 'tar czf "${archive}.tmp"' in source
        assert 'tar czf "$archive"' not in source

    def test_tar_verification_failure_discards_archive_and_fails(self, tmp_path: Path):
        """fix(#1778): `tar tzf` failing on the freshly written .tmp — a
        truncated gzip member neither tar exit code above catches — must
        discard the archive and fail the cycle, the tar-side analogue of the
        dump's `pg_restore -f /dev/null` verification."""
        result, archive = _run_cycle(tmp_path, tar_exit=0, verify_exit=2)
        assert result.returncode != 0
        assert not archive.exists()
        assert not (archive.parent / (archive.name + ".tmp")).exists()
        assert "failed verification" in result.stderr

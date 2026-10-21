"""Backup retention keeps one backup per calendar day and per ISO week.

Every container start runs a backup cycle, so counting dump files let a few
restarts on one day push older days out of the daily window, and several
Sunday cycles fill the weekly window with one week. These tests run the real
functions from scripts/backup-entrypoint.sh against a temporary directory,
with stubs only for the Postgres and AWS clients.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import time
from pathlib import Path

import pytest
import yaml

from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)
SCRIPT = REPO_ROOT / "scripts" / "backup-entrypoint.sh"

_RETENTION_FUNCTIONS = (
    "log",
    "dump_listing_arrays",
    "newest_complete_ts",
    "backup_period_key",
    "mark_retained",
    "prune_old_backups",
    "prune_orphaned_companions",
)


def _extract_function(name: str) -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    match = re.search(
        rf"^{re.escape(name)}\(\) \{{.*?^\}}", source, re.DOTALL | re.MULTILINE
    )
    assert match, f"{name}() not found in {SCRIPT}"
    return match.group(0)


def _prune(
    directory: Path, keep: int, period: str, good: str = ""
) -> subprocess.CompletedProcess:
    harness = "\n".join(
        ["set -euo pipefail", *(_extract_function(n) for n in _RETENTION_FUNCTIONS)]
    )
    harness += (
        f'\nprune_old_backups "$1" "{keep}" {period} "{good}"\n'
        'prune_orphaned_companions "$1"\n'
    )
    result = subprocess.run(
        ["bash", "-c", harness, "_", str(directory)],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def _seed(directory: Path, names: list[str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).write_text("bytes\n")


def _names(directory: Path) -> set[str]:
    return {p.name for p in directory.iterdir()}


class TestDailyRetention:
    def test_several_runs_on_one_day_keep_one_daily(self, tmp_path: Path):
        daily = tmp_path / "daily"
        _seed(
            daily,
            [
                "geolens_20261009_020000.dump",
                "geolens_20261010_020000.dump",
                "geolens_20261010_150000.dump",
                "geolens_20261011_012721.dump",
                "geolens_20261011_020001.dump",
                "geolens_20261011_205402.dump",
            ],
        )
        _prune(daily, keep=7, period="day")
        assert _names(daily) == {
            "geolens_20261009_020000.dump",
            "geolens_20261010_150000.dump",
            "geolens_20261011_205402.dump",
        }

    def test_keeps_the_newest_n_days(self, tmp_path: Path):
        daily = tmp_path / "daily"
        _seed(daily, [f"geolens_202610{day:02d}_020000.dump" for day in range(1, 11)])
        _seed(daily, ["geolens_20261010_210000.dump"])
        _prune(daily, keep=7, period="day")
        assert _names(daily) == {
            *(f"geolens_202610{day:02d}_020000.dump" for day in range(4, 10)),
            "geolens_20261010_210000.dump",
        }

    def test_days_without_a_backup_do_not_count(self, tmp_path: Path):
        daily = tmp_path / "daily"
        names = [
            "geolens_20260101_020000.dump",
            "geolens_20260301_020000.dump",
            "geolens_20260601_020000.dump",
        ]
        _seed(daily, names)
        _prune(daily, keep=7, period="day")
        assert _names(daily) == set(names)

    def test_companions_go_with_a_same_day_run_they_pair_with(self, tmp_path: Path):
        daily = tmp_path / "daily"
        _seed(
            daily,
            [
                "geolens_20261011_020001.dump",
                "globals-20261011_020001.sql",
                "staging-20261011_020001.tar.gz",
                "geolens_20261011_205402.dump",
                "globals-20261011_205402.sql",
                "staging-20261011_205402.tar.gz",
            ],
        )
        _prune(daily, keep=1, period="day")
        assert _names(daily) == {
            "geolens_20261011_205402.dump",
            "globals-20261011_205402.sql",
            "staging-20261011_205402.tar.gz",
        }

    def test_a_newer_partial_run_is_kept_beside_the_complete_set(self, tmp_path: Path):
        daily = tmp_path / "daily"
        _seed(
            daily,
            [
                "geolens_20261010_020000.dump",
                "globals-20261010_020000.sql",
                "geolens_20261011_020000.dump",
                "globals-20261011_020000.sql",
                "geolens_20261011_205402.dump",
            ],
        )
        _prune(daily, keep=1, period="day")
        assert _names(daily) == {
            "geolens_20261011_020000.dump",
            "globals-20261011_020000.sql",
            "geolens_20261011_205402.dump",
        }

    def test_newest_complete_set_survives_outside_the_window(self, tmp_path: Path):
        daily = tmp_path / "daily"
        _seed(daily, ["geolens_20260101_020000.dump", "globals-20260101_020000.sql"])
        _seed(daily, [f"geolens_202602{day:02d}_020000.dump" for day in range(1, 9)])
        _prune(daily, keep=7, period="day")
        remaining = _names(daily)
        assert "geolens_20260101_020000.dump" in remaining
        assert "globals-20260101_020000.sql" in remaining
        assert "geolens_20260201_020000.dump" not in remaining
        assert len([n for n in remaining if n.endswith(".dump")]) == 8

    def test_last_dump_with_records_survives_newer_runs_on_its_day(
        self, tmp_path: Path
    ):
        daily = tmp_path / "daily"
        good_set = [
            "geolens_20261019_020001.dump",
            "globals-20261019_020001.sql",
            "staging-20261019_020001.tar.gz",
        ]
        _seed(daily, good_set)
        _seed(daily, ["geolens_20261019_102717.dump", "globals-20261019_102717.sql"])
        _prune(daily, keep=1, period="day", good="20261019_020001")
        assert _names(daily) == {
            *good_set,
            "geolens_20261019_102717.dump",
            "globals-20261019_102717.sql",
        }

    def test_last_dump_with_records_takes_its_own_slot(self, tmp_path: Path):
        daily = tmp_path / "daily"
        _seed(
            daily,
            [
                "geolens_20261009_020000.dump",
                "globals-20261009_020000.sql",
                "geolens_20261010_020000.dump",
                "geolens_20261011_020000.dump",
            ],
        )
        _prune(daily, keep=1, period="day", good="20261011_020000")
        assert _names(daily) == {
            "geolens_20261009_020000.dump",
            "globals-20261009_020000.sql",
            "geolens_20261011_020000.dump",
        }

    def test_files_retention_did_not_write_are_left_alone(self, tmp_path: Path):
        daily = tmp_path / "daily"
        foreign = ["notes.txt", "manual.dump", "before-upgrade.sql", "geolens.dump.bak"]
        _seed(daily, foreign)
        _seed(daily, [f"geolens_202610{day:02d}_020000.dump" for day in range(1, 4)])
        _prune(daily, keep=1, period="day")
        assert _names(daily) == {*foreign, "geolens_20261003_020000.dump"}


class TestWeeklyRetention:
    def test_runs_on_two_sundays_keep_two_weeklies(self, tmp_path: Path):
        weekly = tmp_path / "weekly"
        _seed(
            weekly,
            [
                "geolens_20261004_020000.dump",
                "geolens_20261011_012721.dump",
                "geolens_20261011_020001.dump",
                "geolens_20261011_205402.dump",
            ],
        )
        _prune(weekly, keep=4, period="week")
        assert _names(weekly) == {
            "geolens_20261004_020000.dump",
            "geolens_20261011_205402.dump",
        }

    def test_keeps_the_newest_m_weeks(self, tmp_path: Path):
        weekly = tmp_path / "weekly"
        sundays = [
            "20260906",
            "20260913",
            "20260920",
            "20260927",
            "20261004",
            "20261011",
        ]
        _seed(weekly, [f"geolens_{d}_020000.dump" for d in sundays])
        _prune(weekly, keep=4, period="week")
        assert _names(weekly) == {f"geolens_{d}_020000.dump" for d in sundays[2:]}

    def test_iso_week_runs_monday_to_sunday_across_new_year(self, tmp_path: Path):
        weekly = tmp_path / "weekly"
        _seed(
            weekly,
            [
                "geolens_20261227_020000.dump",  # Sunday, ISO 2026-W52
                "geolens_20261228_020000.dump",  # Monday, ISO 2026-W53
                "geolens_20270103_020000.dump",  # Sunday, ISO 2026-W53
                "geolens_20270104_020000.dump",  # Monday, ISO 2027-W01
            ],
        )
        _prune(weekly, keep=4, period="week")
        assert _names(weekly) == {
            "geolens_20261227_020000.dump",
            "geolens_20270103_020000.dump",
            "geolens_20270104_020000.dump",
        }


_PG_DUMP_STUB = """#!/bin/sh
prev=""
for arg in "$@"; do
    if [ "$prev" = "-f" ]; then
        printf 'fake dump bytes\\n' > "$arg"
    fi
    prev="$arg"
done
"""

_PG_RESTORE_STUB = "#!/bin/sh\ncat > /dev/null\n"

_PG_DUMPALL_STUB = "#!/bin/sh\necho '-- fake globals dump'\n"

_SUNDAY_DATE_STUB = """#!/bin/sh
case "$*" in "+%u") echo 7; exit 0;; esac
for real in /bin/date /usr/bin/date; do [ -x "$real" ] && exec "$real" "$@"; done
exit 127
"""

_AWS_STUB = """#!/bin/sh
case "$1 $2" in
    "s3 cp") exit "${AWS_STUB_CP_EXIT:-0}" ;;
    "s3api list-objects-v2") echo '{}' ;;
esac
exit 0
"""

# Answers the catalog record count with $PSQL_STUB_COUNT; unset fails the query.
_PSQL_STUB = """#!/bin/sh
[ -n "${PSQL_STUB_COUNT+set}" ] || exit 2
echo "$PSQL_STUB_COUNT"
"""

_REFUSING_LN_STUB = "#!/bin/sh\necho 'ln: Operation not permitted' >&2\nexit 1\n"


def _cycle(
    tmp_path: Path,
    *,
    s3_enabled: bool = False,
    cp_exit: int = 0,
    refuse_links: bool = False,
    record_count: int | None = 1,
) -> tuple[subprocess.CompletedProcess, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stubs = {
        "pg_dump": _PG_DUMP_STUB,
        "pg_restore": _PG_RESTORE_STUB,
        "pg_dumpall": _PG_DUMPALL_STUB,
        "date": _SUNDAY_DATE_STUB,
        "aws": _AWS_STUB,
        "psql": _PSQL_STUB,
    }
    if refuse_links:
        stubs["ln"] = _REFUSING_LN_STUB
    for name, content in stubs.items():
        stub = bin_dir / name
        stub.write_text(content)
        stub.chmod(0o755)

    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "object.tif").write_text("raster bytes\n")
    backup_dir = tmp_path / "backups"

    source = SCRIPT.read_text(encoding="utf-8")
    marker_idx = source.index("# Entry point")
    definitions = source[: source.rindex("# ---", 0, marker_idx)]
    # A permissive caller umask proves the script sets its own.
    harness = f"umask 022\n{definitions}\nrun_backup\n"
    result = subprocess.run(
        ["bash", "-c", harness],
        capture_output=True,
        text=True,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "BACKUP_DIR": str(backup_dir),
            "STAGING_DIR": str(staging),
            "POSTGRES_DB": "geolens",
            "POSTGRES_HOST": "db",
            "POSTGRES_USER": "geolens",
            "POSTGRES_PASSWORD": "test-password",
            "BACKUP_S3_ENABLED": "true" if s3_enabled else "false",
            "S3_BUCKET": "test-bucket",
            "S3_ACCESS_KEY_ID": "test-key",
            "S3_SECRET_ACCESS_KEY": "test-secret",
            "AWS_STUB_CP_EXIT": str(cp_exit),
            **({} if record_count is None else {"PSQL_STUB_COUNT": str(record_count)}),
        },
    )
    return result, backup_dir


def _weekly_pairs(backup_dir: Path) -> list[tuple[Path, Path]]:
    weekly = sorted((backup_dir / "weekly").iterdir())
    assert {p.suffix for p in weekly} == {".dump", ".sql", ".gz"}, weekly
    return [(backup_dir / "daily" / p.name, p) for p in weekly]


class TestBackupCycleFiles:
    def test_weekly_entries_are_hard_links_to_the_daily_files(self, tmp_path: Path):
        result, backup_dir = _cycle(tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr
        for daily, weekly in _weekly_pairs(backup_dir):
            assert os.stat(daily).st_ino == os.stat(weekly).st_ino, weekly.name
        assert "writing a full copy" not in result.stdout + result.stderr

    def test_falls_back_to_a_copy_when_links_are_refused(self, tmp_path: Path):
        result, backup_dir = _cycle(tmp_path, refuse_links=True)
        assert result.returncode == 0, result.stdout + result.stderr
        for daily, weekly in _weekly_pairs(backup_dir):
            assert os.stat(daily).st_ino != os.stat(weekly).st_ino, weekly.name
            assert daily.read_bytes() == weekly.read_bytes()
        assert "writing a full copy" in result.stderr
        assert not list((backup_dir / "weekly").glob("*.tmp"))

    def test_everything_written_is_owner_only(self, tmp_path: Path):
        result, backup_dir = _cycle(tmp_path, s3_enabled=True)
        assert result.returncode == 0, result.stdout + result.stderr
        paths = [backup_dir, *backup_dir.rglob("*")]
        assert len([p for p in paths if p.is_file()]) >= 8
        for path in paths:
            mode = stat.S_IMODE(path.stat().st_mode)
            expected = 0o700 if path.is_dir() else 0o600
            assert mode == expected, f"{path} is {oct(mode)}"


class TestOffsiteMarker:
    def test_written_after_a_fully_uploaded_cycle(self, tmp_path: Path):
        result, backup_dir = _cycle(tmp_path, s3_enabled=True)
        assert result.returncode == 0, result.stdout + result.stderr
        assert (backup_dir / ".last-offsite-success").is_file()

    def test_not_written_when_an_upload_fails(self, tmp_path: Path):
        result, backup_dir = _cycle(tmp_path, s3_enabled=True, cp_exit=1)
        assert result.returncode != 0
        assert not (backup_dir / ".last-offsite-success").exists()

    def test_not_written_when_offsite_is_off(self, tmp_path: Path):
        result, backup_dir = _cycle(tmp_path)
        assert result.returncode == 0, result.stdout + result.stderr
        assert (backup_dir / ".last-success").is_file()
        assert not (backup_dir / ".last-offsite-success").exists()


def _seed_earlier_good_set(backup_dir: Path, count: str) -> tuple[str, set[str]]:
    ts = time.strftime("%Y%m%d") + "_000000"
    names = {f"geolens_{ts}.dump", f"globals-{ts}.sql", f"staging-{ts}.tar.gz"}
    _seed(backup_dir / "daily", sorted(names))
    (backup_dir / ".last-good-dump").write_text(f"{ts} {count}".strip() + "\n")
    return ts, names


class TestLastDumpWithRecords:
    @pytest.mark.parametrize(
        ("marked_count", "record_count"),
        [("10", 0), ("10", 4), ("", 0), ("10", None)],
        ids=["empty", "under-half", "empty-old-marker", "check-failed"],
    )
    def test_the_days_good_set_survives(
        self, tmp_path: Path, marked_count: str, record_count: int | None
    ):
        good_ts, good_set = _seed_earlier_good_set(tmp_path / "backups", marked_count)
        marker_before = (tmp_path / "backups" / ".last-good-dump").read_text()
        result, backup_dir = _cycle(tmp_path, record_count=record_count)
        assert result.returncode == 0, result.stdout + result.stderr
        assert good_set <= _names(backup_dir / "daily")
        assert (backup_dir / ".last-good-dump").read_text() == marker_before
        assert f"retention keeps {good_ts}" in result.stderr

    def test_the_warning_names_both_counts(self, tmp_path: Path):
        good_ts, _ = _seed_earlier_good_set(tmp_path / "backups", "10")
        result, _ = _cycle(tmp_path, record_count=4)
        assert f"4 catalog records, under half of the 10 in {good_ts}" in result.stderr

    @pytest.mark.parametrize(
        ("marked_count", "record_count"),
        [("10", 5), ("", 1)],
        ids=["half", "old-marker"],
    )
    def test_a_database_with_enough_records_takes_over(
        self, tmp_path: Path, marked_count: str, record_count: int
    ):
        _, good_set = _seed_earlier_good_set(tmp_path / "backups", marked_count)
        result, backup_dir = _cycle(tmp_path, record_count=record_count)
        assert result.returncode == 0, result.stdout + result.stderr
        new_ts, count = (backup_dir / ".last-good-dump").read_text().split()
        assert count == str(record_count)
        assert f"geolens_{new_ts}.dump" in _names(backup_dir / "daily")
        assert not good_set & _names(backup_dir / "daily")


def _healthcheck_command(compose_file: str) -> str:
    compose = yaml.safe_load((REPO_ROOT / compose_file).read_text(encoding="utf-8"))
    test = compose["services"]["backup"]["healthcheck"]["test"]
    assert test[0] == "CMD-SHELL"
    return test[1]


def _probe(backups: Path) -> int:
    command = _healthcheck_command("docker-compose.prod.yml")
    command = command.replace("${BACKUP_MAX_AGE_MINUTES:-1560}", "1560")
    command = command.replace("/backups/", f"{backups}/")
    return subprocess.run(
        ["sh", "-c", command], env={"PATH": "/usr/bin:/bin"}
    ).returncode


def _mark(backups: Path, name: str, age_hours: float) -> None:
    marker = backups / name
    marker.touch()
    then = time.time() - age_hours * 3600
    os.utime(marker, (then, then))


class TestBackupHealthcheck:
    def test_both_compose_files_share_one_probe(self):
        assert _healthcheck_command("docker-compose.yml") == _healthcheck_command(
            "docker-compose.prod.yml"
        )

    @pytest.mark.parametrize(
        ("last_success_age", "offsite_age", "healthy"),
        [
            (1, None, True),
            (1, 2, True),
            (1, 27, False),
            (27, None, False),
            (27, 1, False),
            (None, None, False),
        ],
        ids=[
            "offsite-never-enabled",
            "offsite-fresh",
            "offsite-stale",
            "local-stale",
            "local-stale-offsite-fresh",
            "no-backup-yet",
        ],
    )
    def test_probe(
        self,
        tmp_path: Path,
        last_success_age: float | None,
        offsite_age: float | None,
        healthy: bool,
    ):
        if last_success_age is not None:
            _mark(tmp_path, ".last-success", last_success_age)
        if offsite_age is not None:
            _mark(tmp_path, ".last-offsite-success", offsite_age)
        assert (_probe(tmp_path) == 0) is healthy

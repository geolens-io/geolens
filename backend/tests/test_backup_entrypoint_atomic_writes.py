"""fix(#1778): the weekly pg_dump copy must land under its final name
atomically, like the daily dump and the weekly globals copy already did.

Before the fix, `cp "$filepath" "${WEEKLY_DIR}/${filename}"` wrote straight to
the final name: a container killed mid-`cp` (OOM, `compose stop`, ENOSPC)
left a truncated `.dump` in weekly/ under its final name, counted as a good
backup by the retention pruner and reachable months later by an operator
doing a real restore.

This is a structural (source-text) check rather than an executed harness,
matching the file's own pattern for its sibling artifacts (the daily dump and
weekly globals copy, which this asserts against as a positive control) — the
function calls `pg_dump`/`pg_restore` against a live Postgres and is exercised
end-to-end by scripts/tests/test-backup-restore-roundtrip.sh instead.
"""

from __future__ import annotations

from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)
SCRIPT = REPO_ROOT / "scripts" / "backup-entrypoint.sh"


def _read() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_weekly_dump_copy_writes_to_tmp_before_publishing() -> None:
    source = _read()
    assert 'cp "$filepath" "${WEEKLY_DIR}/${filename}.tmp"' in source
    assert 'mv "${WEEKLY_DIR}/${filename}.tmp" "${WEEKLY_DIR}/${filename}"' in source
    # The old direct-to-final-name form must be gone, not just supplemented.
    assert 'cp "$filepath" "${WEEKLY_DIR}/${filename}"\n' not in source


def test_weekly_object_storage_copy_writes_to_tmp_before_publishing() -> None:
    # Positive control: the sibling weekly globals copy already used this
    # pattern before this fix, confirming the assertion shape is meaningful.
    source = _read()
    assert 'cp "$globals_file" "${weekly_copy}.tmp"' in source, (
        "positive control failed: the weekly globals copy's existing "
        ".tmp-then-rename pattern is missing"
    )
    assert 'cp "$archive" "${WEEKLY_DIR}/$(basename "$archive").tmp"' in source
    assert 'cp "$archive" "${WEEKLY_DIR}/$(basename "$archive")"\n' not in source


def test_startup_sweep_covers_every_tmp_artifact_pattern() -> None:
    # The top-of-cycle sweep removes orphaned .tmp files left by a killed
    # prior cycle. Every artifact that now writes through .tmp-then-rename
    # needs a matching glob here, or its orphan accumulates forever.
    source = _read()
    sweep_start = source.index("rm -f")
    sweep_end = source.index("\n\n", sweep_start)
    sweep = source[sweep_start:sweep_end]
    for pattern in (
        '"${DAILY_DIR}"/*.dump.tmp',
        '"${DAILY_DIR}"/globals-*.sql.tmp',
        '"${WEEKLY_DIR}"/globals-*.sql.tmp',
        '"${WEEKLY_DIR}"/*.dump.tmp',
        '"${DAILY_DIR}"/staging-*.tar.gz.tmp',
        '"${WEEKLY_DIR}"/staging-*.tar.gz.tmp',
    ):
        assert pattern in sweep, f"startup sweep is missing {pattern}"

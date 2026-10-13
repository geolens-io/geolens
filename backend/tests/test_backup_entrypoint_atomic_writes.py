"""Weekly backup entries must appear under their final name only when complete.

A weekly entry is a hard link to the finished daily file, which is atomic. When
the filesystem refuses links, the fallback copy goes through a .tmp name and a
rename, so a container killed mid-copy (OOM, `compose stop`, ENOSPC) never
leaves a truncated file under a final weekly name for retention or a restore
to mistake for a good backup.

This is a structural (source-text) check; the behaviour is exercised in
test_backup_retention_periods.py and scripts/tests/test-backup-restore-roundtrip.sh.
"""

from __future__ import annotations

import re

from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)
SCRIPT = REPO_ROOT / "scripts" / "backup-entrypoint.sh"


def _read() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _function(name: str) -> str:
    match = re.search(
        rf"^{re.escape(name)}\(\) \{{.*?^\}}", _read(), re.DOTALL | re.MULTILINE
    )
    assert match, f"{name}() not found"
    return match.group(0)


def test_weekly_copy_links_or_copies_through_tmp() -> None:
    body = _function("publish_weekly_copy")
    assert 'ln "$src" "$dst"' in body
    assert 'cp "$src" "${dst}.tmp" && mv "${dst}.tmp" "$dst"' in body


def test_every_weekly_artifact_goes_through_publish_weekly_copy() -> None:
    source = _read()
    for artifact in ('"$filepath"', '"$archive"', '"$globals_file"'):
        assert f"publish_weekly_copy {artifact}" in source, artifact
    assert not re.search(r'\bcp "[^"]+" "\$\{WEEKLY_DIR\}', source)


def test_startup_sweep_covers_every_tmp_artifact_pattern() -> None:
    # The top-of-cycle sweep removes orphaned .tmp files left by a killed
    # prior cycle. Every artifact that can write through .tmp-then-rename
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

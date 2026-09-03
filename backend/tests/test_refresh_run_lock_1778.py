"""Codebase audit 2026-08-30, cancelling a re-upload (tracked in #1778).

Phase 1 held the ``dataset_refresh_runs`` row lock across the staging
download, so ``POST /jobs/{id}/cancel`` returned 409 ``job_finishing`` for the
whole multi-GB download and the rollback discarded the job cancellation it had
already committed.
"""

from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"


def _source(rel: str) -> str:
    return (APP / rel).read_text()


class TestRunLockReleasedBeforeDownload:
    """``claim_run_for_job`` is committed before ``resolve_file_path`` runs."""

    MODULES = [
        "processing/ingest/tasks_raster_replace.py",
        "processing/ingest/tasks_reupload.py",
    ]

    @pytest.mark.parametrize("module", MODULES)
    def test_a_commit_separates_the_claim_from_the_download(self, module: str) -> None:
        lines = _source(module).splitlines()
        claim = next(
            i for i, line in enumerate(lines) if "await claim_run_for_job(" in line
        )
        download = next(
            i
            for i, line in enumerate(lines)
            if i > claim and "await resolve_file_path(" in line
        )
        between = [
            line
            for line in lines[claim + 1 : download]
            if "await session.commit()" in line
        ]
        assert between, (
            f"{module}: the pending -> running run transition is not committed "
            "between the claim and the staging download. transition_run's "
            "UPDATE ... RETURNING keeps the dataset_refresh_runs row locked "
            "for the whole download, and cancel_job transitions that same row "
            "under a 2s lock_timeout."
        )

"""Phase 275 / API-11 + API-12 regression: runbooks + methodology."""

from __future__ import annotations

from pathlib import Path

import pytest

# Resolve repo root from this test file's location:
#   backend/tests/test_phase_275_runbooks.py -> parents[2] -> repo root
REPO_ROOT = Path(__file__).resolve().parents[2]

# Phase 278 TEST-09: lift the gitignored slash-command target to a module-level
# constant so the conditional skip can be expressed as a decorator (skipif),
# not a runtime check. Path is fully derivable from REPO_ROOT — no side effects.
_OC_AUDIT_COMMAND_PATH = REPO_ROOT / ".claude/commands/oc-audit.md"
_OC_AUDIT_COMMAND_PRESENT = _OC_AUDIT_COMMAND_PATH.exists()


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def test_edition_deactivation_includes_pg_dump() -> None:
    """API-11 / L-51: deactivation runbook documents pg_dump pre-step."""
    body = _read("docs/edition-deactivation.md")
    assert "pg_dump" in body, (
        "docs/edition-deactivation.md must document a pg_dump pre-step before "
        "alembic downgrade — the downgrade is destructive without backup. (L-51)"
    )
    assert "alembic downgrade" in body, (
        "docs/edition-deactivation.md must reference alembic downgrade so the "
        "pre-step warning has clear context."
    )
    # The original docs.getgeolens.com link must be preserved
    assert "docs.getgeolens.com/guides/operations/edition-deactivation" in body, (
        "Original docs.getgeolens.com link missing — preservation regression"
    )


def test_pg_dump_command_block_is_self_contained() -> None:
    """API-11: the pg_dump example must be runnable as-is, not partial."""
    body = _read("docs/edition-deactivation.md")
    # The command block uses POSTGRES_* env vars from .env.example
    for required in ("POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_DB"):
        assert required in body, f"pg_dump example missing env var: {required}"
    # The file should suggest verification with pg_restore
    assert "pg_restore" in body, (
        "pg_dump pre-step should include pg_restore --list verification step"
    )


def test_oc_audit_methodology_doc_exists() -> None:
    """API-12 / L-53: docs/oc-audit-methodology.md exists and documents dual-path."""
    path = REPO_ROOT / "docs/oc-audit-methodology.md"
    assert path.exists(), "docs/oc-audit-methodology.md missing — API-12 deliverable"
    body = path.read_text(encoding="utf-8")
    # Both output paths must be cited
    assert "docs-internal/audits" in body, (
        "Methodology must cite ad-hoc audit path docs-internal/audits/"
    )
    assert ".planning/audits" in body, (
        "Methodology must cite milestone-close path .planning/audits/"
    )
    # Both audit types must be named
    assert "Ad-hoc audits" in body, "Methodology must name 'Ad-hoc audits' explicitly"
    assert "Milestone-close audits" in body, (
        "Methodology must name 'Milestone-close audits' explicitly"
    )


@pytest.mark.skipif(
    not _OC_AUDIT_COMMAND_PRESENT,
    reason=".claude/commands/oc-audit.md not present (gitignored)",
)
def test_oc_audit_command_references_methodology() -> None:
    """API-12: .claude/commands/oc-audit.md links to the methodology doc.

    Note: `.claude/` is gitignored in this repo (Claude Code slash-command config
    is user-local), so this test reads the local file. The cross-reference is a
    developer-experience concern; CI without the local Claude config skips via
    the @pytest.mark.skipif decorator above (Phase 278 TEST-09).
    """
    body = _OC_AUDIT_COMMAND_PATH.read_text(encoding="utf-8")
    assert "oc-audit-methodology" in body, (
        ".claude/commands/oc-audit.md must cross-link to docs/oc-audit-methodology.md"
    )

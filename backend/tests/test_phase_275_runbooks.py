"""Phase 275 / API-11 + API-12 regression: public docs stay externalized."""

from __future__ import annotations

from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def test_deferred_runbooks_are_not_linked_from_readme() -> None:
    """API-11 / L-51: deferred runbooks are absent from launch README."""
    body = _read("README.md")
    assert "Edition deactivation" not in body
    assert "Edition reactivation" not in body
    assert "SAML configuration" not in body
    assert "docs/edition-deactivation.md" not in body
    assert "docs/edition-reactivation.md" not in body
    assert "docs/saml.md" not in body


def test_pg_dump_command_block_is_self_contained() -> None:
    """API-11: backup profile stays discoverable from compose."""
    readme = _read("README.md")
    compose = _read("docker-compose.yml")
    assert "--profile backup" in compose
    assert "pg_dump" in compose
    assert "Edition deactivation" not in readme


def test_oc_audit_methodology_doc_exists() -> None:
    """API-12 / L-53: internal audit methodology stays out of public docs."""
    readme = _read("README.md")
    assert "oc-audit-methodology.md" not in readme
    assert "docs-internal/audits" not in readme

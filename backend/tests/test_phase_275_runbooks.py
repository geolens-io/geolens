"""Phase 275 / API-11 + API-12 regression: public docs stay externalized."""

from __future__ import annotations

from pathlib import Path

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


def test_shipping_source_does_not_cite_docs_internal() -> None:
    """GAP-015: no ``backend/app/`` source cites unpublished ``docs-internal/``.

    ``docs-internal/`` is gitignored, so any such reference in shipping source
    is a dangling pointer for public readers and leaks internal audit naming
    (violates AGENTS.md). Mirrors the README guard above, extended across the
    whole shipping package.
    """
    import app

    app_root = Path(app.__file__).resolve().parent
    offenders = []
    for py_file in app_root.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        if "docs-internal/" in text:
            offenders.append(str(py_file.relative_to(app_root)))

    assert not offenders, (
        "Shipping source must not cite unpublished docs-internal/ paths "
        f"(GAP-015). Offenders: {offenders}. State the rationale inline or "
        "cite a public CHANGELOG/PR number instead."
    )

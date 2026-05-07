"""Phase 275 / API-06 regression: frontend/README.md is not Vite boilerplate.

Locks the M-26 finding closed: contributors who clone the repo and open
``frontend/`` first must see a GeoLens-specific orientation, not the
unmodified Vite + React + TypeScript starter README.
"""

from __future__ import annotations

from pathlib import Path

# backend/tests/test_phase_275_frontend_readme.py -> repo root is parents[2]
_REPO_ROOT = Path(__file__).resolve().parents[2]
_FRONTEND_README = _REPO_ROOT / "frontend" / "README.md"


def _read_frontend_readme() -> str:
    return _FRONTEND_README.read_text(encoding="utf-8")


def test_frontend_readme_starts_with_geolens() -> None:
    """API-06 / M-26: H1 should identify the file as GeoLens-specific."""
    body = _read_frontend_readme()
    first_line = body.splitlines()[0].strip()
    assert first_line.startswith("# GeoLens"), (
        f"frontend/README.md H1 should start with '# GeoLens'; got: {first_line!r}"
    )


def test_frontend_readme_no_boilerplate() -> None:
    """API-06 / M-26: Vite + React + TypeScript starter content must be gone."""
    body = _read_frontend_readme()
    boilerplate_signals = [
        # The starter's H1
        "# React + TypeScript + Vite",
        # The starter's plugin discussion
        "@vitejs/plugin-react-swc",
        # The starter's ESLint upgrade discussion
        "tseslint.configs.recommendedTypeChecked",
        "tseslint.configs.strictTypeChecked",
        "tseslint.configs.stylisticTypeChecked",
        # The starter's react-x advice
        "eslint-plugin-react-x",
        "eslint-plugin-react-dom",
        # The starter's React Compiler section
        "The React Compiler is not enabled on this template",
    ]
    found = [s for s in boilerplate_signals if s in body]
    assert not found, (
        f"Vite starter boilerplate still present in frontend/README.md: {found}"
    )


def test_frontend_readme_links_to_root_docs() -> None:
    """API-06: orientation must point contributors at the canonical docs."""
    body = _read_frontend_readme()
    assert "../README.md" in body or "/README.md" in body, (
        "frontend/README.md must cross-link to root README.md instead of duplicating install steps"
    )
    assert "CONTRIBUTING" in body, (
        "frontend/README.md must mention CONTRIBUTING (root or .github/) for dev setup"
    )


def test_frontend_readme_describes_actual_stack() -> None:
    """API-06: the file should describe what shipped, not what a starter ships."""
    body = _read_frontend_readme()
    # Match the actual stack documented in the root README Architecture table
    for term in ("React 19", "Vite", "MapLibre GL", "TanStack Query", "Tailwind"):
        assert term in body, f"frontend/README.md missing real-stack term: {term}"

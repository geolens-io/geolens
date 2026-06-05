"""Phase 275 / API-04 + API-09 + API-13 regression: README accuracy locks."""

from __future__ import annotations

import re

from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def test_readme_api_reference_link_is_external() -> None:
    """API-04 / M-21: API Reference table row points to docs.getgeolens.com."""
    body = _read("README.md")
    assert "docs.getgeolens.com/guides/api/" in body, (
        "README.md API Reference link must point to docs.getgeolens.com/guides/api/"
    )
    assert "(#see-it-in-action)" not in body, (
        "API Reference still points at in-page anchor — fix the link"
    )


def test_readme_surfaces_examples_manifests_directory() -> None:
    """API-04 / L-17: examples/manifests/ must be discoverable from the README."""
    body = _read("README.md")
    assert "examples/manifests" in body, (
        "README.md must reference examples/manifests/ (covers public-cog discoverability)"
    )


def test_readme_documents_cold_build_time() -> None:
    """API-13 / M-73: cold-build time documented for first-time users."""
    body = _read("README.md")
    assert ("5-10 minutes" in body) or ("Cold-build time" in body), (
        "README.md must document cold-build time (M-73): 'First build takes 5-10 minutes'"
    )


def test_readme_python_badge_widened() -> None:
    """API-09 / L-23: badge clarifies backend 3.13 vs SDK 3.10+ split."""
    body = _read("README.md")
    # Allow either underscore-encoded badge URL or human-readable label
    assert (
        ("3.13_backend" in body) or ("3.13 backend" in body) or ("backend 3.13" in body)
    ), "README.md Python badge should reflect backend 3.13 / SDK 3.10+ split"


def test_code_of_conduct_has_inline_pledge() -> None:
    """API-09 / L-24: CODE_OF_CONDUCT.md gains a pledge above the link."""
    body = _read("CODE_OF_CONDUCT.md")
    assert "## Our Pledge" in body, "CODE_OF_CONDUCT.md missing '## Our Pledge' section"
    assert re.search(r"[Ww]e pledge", body), (
        "CODE_OF_CONDUCT.md '## Our Pledge' lacks the pledge sentence"
    )


def test_all_readmes_are_utf8() -> None:
    """API-09 / L-25: non-English READMEs preserve UTF-8."""
    for filename in (
        "README.md",
        "README.es.md",
        "README.fr.md",
        "README.de.md",
    ):
        raw = (REPO_ROOT / filename).read_bytes()
        try:
            decoded = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AssertionError(f"{filename} is not valid UTF-8: {exc}")
        # Round-trip check: re-encoding should produce identical bytes
        assert decoded.encode("utf-8") == raw, f"{filename} round-trip mismatch"


def test_readme_fr_has_accent_marks() -> None:
    """API-09 / L-25: README.fr.md restores accent marks (no bare 'donnees')."""
    body = _read("README.fr.md")
    assert "données" in body, (
        "README.fr.md missing 'données' (UTF-8 restoration regression)"
    )
    # Bare "donnees" indicates ASCII-stripping regression
    assert not re.search(r"\bdonnees\b", body), (
        "README.fr.md still contains ASCII-stripped 'donnees' — restore to 'données'"
    )

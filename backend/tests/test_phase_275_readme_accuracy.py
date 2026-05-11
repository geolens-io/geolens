"""Phase 275 / API-04 + API-09 + API-13 regression: README accuracy locks."""

from __future__ import annotations

import ast
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def _natural_earth_count() -> int:
    """Read scripts/seed-natural-earth.py and count DATASETS list entries."""
    src = _read("scripts/seed-natural-earth.py")
    tree = ast.parse(src)
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.AnnAssign):
            target = getattr(node, "target", None)
            if isinstance(target, ast.Name) and target.id == "DATASETS":
                if isinstance(node.value, ast.List):
                    return len(node.value.elts)
    raise AssertionError("DATASETS list not found in seed-natural-earth.py")


def test_readme_natural_earth_count_matches_seed_script() -> None:
    """API-04 / M-22: README must not cite a stale Natural Earth count."""
    body = _read("README.md")
    # The script ships 109 datasets at plan-authoring time. The exact number
    # may grow; the test asserts no STALE numeric counts are claimed.
    for stale in ("130 Natural Earth datasets", "123 Natural Earth datasets"):
        assert stale not in body, f"Stale count found in README.md: {stale}"
    # Sanity: the seed script still has its DATASETS list and is parseable.
    count = _natural_earth_count()
    assert count > 0, "DATASETS list in seed-natural-earth.py is empty"


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


def test_readme_signature_maps_list_intact() -> None:
    """API-04 / M-23: 9 signature-map bullets must remain in README.md."""
    body = _read("README.md")
    # Manhattan Skyline is the canary added in Phase 269 H-13
    assert "Manhattan Skyline" in body, (
        "Manhattan Skyline bullet missing from README.md"
    )
    # Sanity-check there are at least 9 signature-map bullet lines
    # (search the section between 'signature stories include:' and 'All data is bundled')
    match = re.search(
        r"signature stories include:(.*?)All data is bundled",
        body,
        re.DOTALL,
    )
    assert match, "Could not locate signature-map list in README.md"
    bullets = re.findall(r"^- \*\*", match.group(1), re.MULTILINE)
    assert len(bullets) >= 9, (
        f"Signature-map list shrunk: expected >=9 bullets, found {len(bullets)}"
    )

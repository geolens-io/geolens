"""GAP-012 regression: the gitleaks allowlist must stay narrow.

The audit found the config blanket-allowlisted the whole backend/tests/ and
sdks/ trees plus any value containing the substring "padding", so a future real
secret in those paths would bypass the gitleaks pre-commit hook and local scans
silently — in a public repo where every commit publishes immediately.

These tests pin the narrowing: the tree-wide test/SDK path allowlists and the
bare "padding" regex/stopword must NOT come back, while the anchored known-fake
fixture exceptions must remain so the live scan stays green.

Static analysis of .gitleaks.toml only — no gitleaks binary required. The
behavioral proof (a new secret under backend/tests/ is now caught) lives in the
phase validation; here we guard the config that makes it true.
"""

from __future__ import annotations

import tomllib

from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)
GITLEAKS_PATH = REPO_ROOT / ".gitleaks.toml"


def _config() -> dict:
    with GITLEAKS_PATH.open("rb") as f:
        return tomllib.load(f)


def test_gitleaks_config_is_valid_toml() -> None:
    cfg = _config()
    assert cfg.get("title") == "GeoLens gitleaks config"
    assert "allowlist" in cfg


def test_no_tree_wide_test_or_sdk_path_allowlist() -> None:
    """backend/tests/ and sdks/ must not be blanket-allowlisted by path."""
    paths = _config()["allowlist"].get("paths", [])
    forbidden = {"^backend/tests/", "^sdks/"}
    leaked = forbidden.intersection(paths)
    assert not leaked, (
        f"GAP-012: tree-wide path allowlist(s) {leaked} re-added — a real secret "
        f"under those trees would bypass scanning. Use anchored value regexes."
    )


def test_no_bare_padding_regex_or_stopword() -> None:
    """The substring 'padding' must not be a bare regex or stopword."""
    allow = _config()["allowlist"]
    assert "padding" not in allow.get("stopwords", []), (
        "GAP-012: bare 'padding' stopword re-added — any value containing the "
        "substring would bypass scanning."
    )
    assert "padding" not in allow.get("regexes", []), (
        "GAP-012: bare 'padding' regex re-added — anchor it to the '-padding-' "
        "placeholder convention instead."
    )


def test_anchored_known_fake_fixtures_remain_allowlisted() -> None:
    """The narrowed, anchored exceptions that keep the scan green must persist."""
    regexes = _config()["allowlist"].get("regexes", [])
    # The CI/test placeholder convention is the hyphenated `-padding-` infix.
    assert any("-padding-" in r for r in regexes), (
        "GAP-012: the anchored '-padding-' placeholder allowlist is missing; the "
        "live gitleaks scan would flag the legitimate CI/test fixtures."
    )
    # The fake JWT used by test_preview_token_sec021.py must stay anchored.
    assert any("eyJhbGciOi" in r for r in regexes), (
        "GAP-012: the anchored fake-JWT allowlist for test_preview_token_sec021 "
        "is missing; the scan would flag that fixture."
    )

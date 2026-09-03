"""fix(#1778): regression locks for the doc-accuracy findings from the
2026-08-30 codebase audit — EGRESS.md's air-gap claim, CONTRIBUTING.md's
backend/frontend style-check recipes, and ARCHITECTURE.md's E2E policy line.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)

_CODE_SPAN = re.compile(r"`([^`]+)`")


def _read(rel_path: str) -> str:
    return (REPO_ROOT / rel_path).read_text(encoding="utf-8")


def _doc_mentions_host(body: str, host: str) -> bool:
    """True if a backtick-quoted code span in `body` names exactly `host`.

    fix(#1778 review, CodeQL py/incomplete-url-substring-sanitization):
    the previous `host in body` check is the exact shape that query flags —
    a substring-containment test against a hostname-shaped literal, which a
    same-prefix host (`host.evil.com`) or same-suffix host (`evil-host`)
    could also satisfy. Extract each backtick code span, parse it with
    urlsplit (a bare `host` and a full `scheme://host/path` both parse
    correctly since a leading `//` is prepended when no scheme is present),
    and compare `.hostname` for exact equality instead.
    """
    for token in _CODE_SPAN.findall(body):
        candidate = token if "//" in token else f"//{token}"
        if urlsplit(candidate).hostname == host:
            return True
    return False


def test_egress_default_posture_does_not_overclaim_no_outbound_calls() -> None:
    body = _read("EGRESS.md")
    # The default basemaps (openfreemap-positron/dark/bright, openstreetmap)
    # are enabled out of the box and fetched by the browser, so "no outbound
    # internet calls" full stop is false; only the server side makes none.
    assert "**no outbound internet calls**" not in body
    assert "no server-side outbound calls" in body
    assert _doc_mentions_host(body, "tiles.openfreemap.org")


def test_egress_basemaps_row_is_default_on_not_optional() -> None:
    body = _read("EGRESS.md")
    matrix_lines = [line for line in body.splitlines() if line.startswith("| Basemaps")]
    assert matrix_lines, "EGRESS.md must have a Basemaps row in the egress matrix"
    assert "Default-on" in matrix_lines[0]


def test_contributing_backend_lint_recipe_runs_on_host() -> None:
    body = _read(".github/CONTRIBUTING.md")
    # ruff is a dev-only dependency group (backend/pyproject.toml) not
    # installed in the api container's runtime venv — `docker compose exec
    # api ruff check .` fails with "ruff: not found".
    assert "docker compose exec api ruff" not in body
    assert "cd backend && uv run ruff check" in body


def test_contributing_does_not_prescribe_prettier() -> None:
    body = _read(".github/CONTRIBUTING.md")
    # Prettier is not a frontend dependency and has no config anywhere in
    # the repo (frontend/package.json, .prettierrc, prettier.config.*).
    assert "prettier" not in body.lower()


def test_architecture_e2e_policy_matches_contributing() -> None:
    architecture = _read(".github/ARCHITECTURE.md")
    contributing = _read(".github/CONTRIBUTING.md")
    # CI has run e2e:smoke:core on PRs that touch the stack since #825;
    # ARCHITECTURE.md previously said E2E was "local-only by policy",
    # contradicting CONTRIBUTING.md's own documented PR gate.
    assert "local-only by policy" not in architecture
    assert "e2e:smoke:core" in architecture
    assert "e2e:smoke:core" in contributing

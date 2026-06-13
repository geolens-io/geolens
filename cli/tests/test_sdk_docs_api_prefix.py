# SPDX-License-Identifier: Apache-2.0
"""GAP-026 guard: shipped SDK quickstarts/docstrings show base_url WITH /api.

The deployed GeoLens API is served under ``/api`` and the generated SDK paths
are origin-relative (no prefix), so every published quickstart example must use
``https://<host>/api`` as the base URL or copy-paste consumers get 404s on
their first call. This guard scans the hand-maintained SDK docs in the repo and
fails if any ``base_url``/``baseUrl`` example points at a bare origin.

Lives in the CLI suite because that is this phase's test gate; it skips
gracefully when the sibling SDK source tree is absent (e.g. the CLI installed
standalone), so it never breaks an isolated CLI checkout.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Files that ship copy-paste base_url / baseUrl quickstart examples.
_DOC_FILES = (
    "sdks/python/README.md",
    "sdks/python/geolens/__init__.py",
    "sdks/python/geolens/auth.py",
    "sdks/typescript/README.md",
    "sdks/typescript/src/auth.ts",
    "cli/README.md",
)

# Matches an example base URL like:  base_url="https://geolens.example.com..."
# or  baseUrl: 'https://geolens.example.com...'  capturing the URL literal.
_BASE_URL_EXAMPLE = re.compile(
    r"""base_?url\s*[=:]\s*['"](?P<url>https?://[^'"]+)['"]""",
    re.IGNORECASE,
)


def _doc_paths() -> list[Path]:
    paths = [_REPO_ROOT / rel for rel in _DOC_FILES]
    present = [p for p in paths if p.is_file()]
    if not present:
        pytest.skip("SDK source tree not present (CLI installed standalone)")
    return present


def test_sdk_quickstart_base_urls_include_api_prefix() -> None:
    offenders: list[str] = []
    for path in _doc_paths():
        text = path.read_text(encoding="utf-8")
        for match in _BASE_URL_EXAMPLE.finditer(text):
            url = match.group("url").rstrip("/")
            # Only the example.com placeholder URLs are quickstart samples we
            # control; ignore any real/other hosts defensively.
            if "example.com" not in url:
                continue
            segments = url.split("/")
            if "api" not in segments:
                rel = path.relative_to(_REPO_ROOT)
                offenders.append(f"{rel}: {match.group('url')}")
    assert not offenders, (
        "GAP-026: SDK quickstart base_url examples must include the /api "
        "prefix:\n" + "\n".join(offenders)
    )

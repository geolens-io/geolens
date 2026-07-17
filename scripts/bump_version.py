"""Single-source version bump across EVERY version site in the repo.

`make bump VERSION=X.Y.Z` rewrites all of the following atomically:

  - backend/pyproject.toml                 ([project] version) — the canonical
                                           distribution version the running app
                                           derives at runtime (REL-03)
  - backend/app/api/main.py                (_FALLBACK_APP_VERSION constant — the
                                           source-checkout fallback when the
                                           distribution metadata is absent)
  - backend/openapi.json                   (info.version — what the API reports
                                           and what sync_sdk_versions.py reads)
  - frontend/package.json                  (.version)
  - package.json                           (root .version — private/unpublished)
  - cli/pyproject.toml                     ([project] version)
  - mcp/pyproject.toml                     ([project] version)
  - sdks/python/pyproject.toml             ([project] version)
  - sdks/python/.openapi-python-client.yaml (package_version_override)
  - sdks/typescript/package.json           (.version)
  - docs-contract.json                     (.version — the cross-surface doc
                                           contract; check_docs_contract.py
                                           asserts it equals backend/pyproject)

The version MUST be a plain X.Y.Z semver (no suffixes) — the drift gate
(`make version-check`) is a static equality check, and the SDK sync script
forbids build/hash/timestamp suffixes.

This script is the WRITE side of the version contract; check_version_coherence.py
is the READ/verify side. They enumerate the same set of sites.

Usage:
    uv run python scripts/bump_version.py X.Y.Z
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

BACKEND_PYPROJECT = REPO_ROOT / "backend" / "pyproject.toml"
MAIN_PY = REPO_ROOT / "backend" / "app" / "api" / "main.py"
OPENAPI_PATH = REPO_ROOT / "backend" / "openapi.json"
FRONTEND_PACKAGE = REPO_ROOT / "frontend" / "package.json"
ROOT_PACKAGE = REPO_ROOT / "package.json"
CLI_PYPROJECT = REPO_ROOT / "cli" / "pyproject.toml"
MCP_PYPROJECT = REPO_ROOT / "mcp" / "pyproject.toml"
PY_SDK_PYPROJECT = REPO_ROOT / "sdks" / "python" / "pyproject.toml"
PY_SDK_GEN_CONFIG = REPO_ROOT / "sdks" / "python" / ".openapi-python-client.yaml"
TS_SDK_PACKAGE = REPO_ROOT / "sdks" / "typescript" / "package.json"
DOCS_CONTRACT = REPO_ROOT / "docs-contract.json"


def _rel(p: Path) -> str:
    return str(p.relative_to(REPO_ROOT))


def _bump_project_version(path: Path, version: str) -> None:
    # First `version = "..."` line under [project] (pyproject is hand-maintained,
    # one [project] table). Anchored to the start of a line.
    text = path.read_text()
    pattern = re.compile(r'^version = "[^"]*"$', re.MULTILINE)
    new_text, count = pattern.subn(f'version = "{version}"', text, count=1)
    if count != 1:
        sys.exit(f"ERROR: expected 1 'version = \"...\"' line in {_rel(path)}, found {count}.")
    path.write_text(new_text)
    print(f"  {_rel(path)} -> {version}")


def _bump_package_json(path: Path, version: str) -> None:
    text = path.read_text()
    had_trailing_newline = text.endswith("\n")
    data = json.loads(text)
    data["version"] = version
    new_text = json.dumps(data, indent=2)
    if had_trailing_newline:
        new_text += "\n"
    path.write_text(new_text)
    print(f"  {_rel(path)} -> {version}")


def _bump_openapi(path: Path, version: str) -> None:
    text = path.read_text()
    had_trailing_newline = text.endswith("\n")
    spec = json.loads(text)
    if "info" not in spec or not isinstance(spec["info"], dict):
        sys.exit(f"ERROR: {_rel(path)} has no info object.")
    spec["info"]["version"] = version
    new_text = json.dumps(spec, indent=2)
    if had_trailing_newline:
        new_text += "\n"
    path.write_text(new_text)
    print(f"  {_rel(path)} (info.version) -> {version}")


def _bump_main_fallback(path: Path, version: str) -> None:
    text = path.read_text()
    pattern = re.compile(r'^_FALLBACK_APP_VERSION = "[^"]*"$', re.MULTILINE)
    new_text, count = pattern.subn(f'_FALLBACK_APP_VERSION = "{version}"', text, count=1)
    if count != 1:
        sys.exit(f"ERROR: expected 1 '_FALLBACK_APP_VERSION = \"...\"' line in {_rel(path)}, found {count}.")
    path.write_text(new_text)
    print(f"  {_rel(path)} (_FALLBACK_APP_VERSION) -> {version}")


def _bump_yaml_override(path: Path, version: str) -> None:
    text = path.read_text()
    pattern = re.compile(r"^package_version_override: .*$", re.MULTILINE)
    new_text, count = pattern.subn(f"package_version_override: {version}", text, count=1)
    if count != 1:
        sys.exit(f"ERROR: expected 1 'package_version_override:' line in {_rel(path)}, found {count}.")
    path.write_text(new_text)
    print(f"  {_rel(path)} (package_version_override) -> {version}")


def _bump_top_level_json_version(path: Path, version: str) -> None:
    # Targeted regex on the top-level `"version": "..."` line (first occurrence)
    # so the hand-maintained file keeps its exact formatting — a full json
    # round-trip would reflow the long _comment and nested structures.
    text = path.read_text()
    pattern = re.compile(r'^(\s*)"version": "[^"]*"', re.MULTILINE)
    new_text, count = pattern.subn(rf'\g<1>"version": "{version}"', text, count=1)
    if count != 1:
        sys.exit(f"ERROR: expected a top-level '\"version\": \"...\"' line in {_rel(path)}, found {count}.")
    path.write_text(new_text)
    print(f"  {_rel(path)} (.version) -> {version}")


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        sys.exit("Usage: bump_version.py X.Y.Z")
    version = argv[0].strip()
    if not SEMVER_RE.match(version):
        sys.exit(f"ERROR: version '{version}' is not X.Y.Z (plain semver, no suffixes).")

    print(f"Bumping all version sites to {version}:")
    _bump_project_version(BACKEND_PYPROJECT, version)
    _bump_main_fallback(MAIN_PY, version)
    _bump_openapi(OPENAPI_PATH, version)
    _bump_package_json(FRONTEND_PACKAGE, version)
    _bump_package_json(ROOT_PACKAGE, version)
    _bump_project_version(CLI_PYPROJECT, version)
    _bump_project_version(MCP_PYPROJECT, version)
    _bump_project_version(PY_SDK_PYPROJECT, version)
    _bump_yaml_override(PY_SDK_GEN_CONFIG, version)
    _bump_package_json(TS_SDK_PACKAGE, version)
    _bump_top_level_json_version(DOCS_CONTRACT, version)
    print(f"Done. Run `make version-check` to confirm coherence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

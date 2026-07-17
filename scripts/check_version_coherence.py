"""Version-coherence gate: assert EVERY version site agrees (REL-04).

Reads the version from every place the project records one and exits non-zero
if any disagree, printing the offending site(s). This is the READ/verify side of
the version contract; scripts/bump_version.py is the WRITE side — they enumerate
the same set of sites.

Sites checked:
  - backend/pyproject.toml                  [project].version (canonical)
  - backend/app/api/main.py                 _FALLBACK_APP_VERSION constant
  - backend/openapi.json                    info.version
  - frontend/package.json                   .version
  - package.json                            (root) .version
  - cli/pyproject.toml                      [project].version
  - mcp/pyproject.toml                      [project].version
  - sdks/python/pyproject.toml              [project].version
  - sdks/python/.openapi-python-client.yaml package_version_override
  - sdks/typescript/package.json            .version

The canonical version is backend/pyproject.toml — the distribution version the
running app derives at runtime via importlib.metadata (REL-03). Every other
site must equal it.

Usage:
    uv run python scripts/check_version_coherence.py
Exit code 0 = coherent; 1 = drift (offenders printed to stderr).
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

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


def _rel(p: Path) -> str:
    return str(p.relative_to(REPO_ROOT))


def _pyproject_version(path: Path) -> str:
    data = tomllib.loads(path.read_text())
    return data["project"]["version"]


def _package_json_version(path: Path) -> str:
    return json.loads(path.read_text())["version"]


def _openapi_version(path: Path) -> str:
    return json.loads(path.read_text())["info"]["version"]


def _main_fallback_version(path: Path) -> str:
    m = re.search(r'^_FALLBACK_APP_VERSION = "([^"]*)"$', path.read_text(), re.MULTILINE)
    if not m:
        sys.exit(f"ERROR: no _FALLBACK_APP_VERSION line in {_rel(path)}.")
    return m.group(1)


def _yaml_override_version(path: Path) -> str:
    m = re.search(r"^package_version_override: (.*)$", path.read_text(), re.MULTILINE)
    if not m:
        sys.exit(f"ERROR: no package_version_override line in {_rel(path)}.")
    return m.group(1).strip()


def main() -> int:
    sites: dict[str, str] = {}
    sites[f"{_rel(BACKEND_PYPROJECT)} ([project].version)"] = _pyproject_version(BACKEND_PYPROJECT)
    sites[f"{_rel(MAIN_PY)} (_FALLBACK_APP_VERSION)"] = _main_fallback_version(MAIN_PY)
    sites[f"{_rel(OPENAPI_PATH)} (info.version)"] = _openapi_version(OPENAPI_PATH)
    sites[f"{_rel(FRONTEND_PACKAGE)} (.version)"] = _package_json_version(FRONTEND_PACKAGE)
    sites[f"{_rel(ROOT_PACKAGE)} (.version)"] = _package_json_version(ROOT_PACKAGE)
    sites[f"{_rel(CLI_PYPROJECT)} ([project].version)"] = _pyproject_version(CLI_PYPROJECT)
    sites[f"{_rel(MCP_PYPROJECT)} ([project].version)"] = _pyproject_version(MCP_PYPROJECT)
    sites[f"{_rel(PY_SDK_PYPROJECT)} ([project].version)"] = _pyproject_version(PY_SDK_PYPROJECT)
    sites[f"{_rel(PY_SDK_GEN_CONFIG)} (package_version_override)"] = _yaml_override_version(PY_SDK_GEN_CONFIG)
    sites[f"{_rel(TS_SDK_PACKAGE)} (.version)"] = _package_json_version(TS_SDK_PACKAGE)

    # Canonical = backend distribution version (what the app derives at runtime).
    canonical = sites[f"{_rel(BACKEND_PYPROJECT)} ([project].version)"]

    offenders = {site: v for site, v in sites.items() if v != canonical}

    if offenders:
        sys.stderr.write(
            f"FAIL: version drift detected. Canonical (backend/pyproject.toml) = {canonical!r}.\n"
            f"Run `make bump VERSION={canonical}` to resync, or correct the offending site:\n"
        )
        for site, v in offenders.items():
            sys.stderr.write(f"  - {site}: {v!r} != {canonical!r}\n")
        return 1

    print(f"OK: all {len(sites)} version sites agree on {canonical}.")
    for site, v in sites.items():
        print(f"  {site}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

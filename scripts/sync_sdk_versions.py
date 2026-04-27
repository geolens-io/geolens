"""Sync both SDK package versions to backend/openapi.json info.version.

Idempotent: same input always produces the same output. Run as part of
`make sdks` so the drift gate (`make sdks-check`) catches version drift in
the same diff that catches code drift (CONTEXT.md D-08).

Touches three files:
  - sdks/python/pyproject.toml          ([project] version)
  - sdks/python/.openapi-python-client.yaml  (package_version_override)
  - sdks/typescript/package.json        (.version)

NEVER add timestamps, build numbers, hashes, or environment-derived suffixes.
The drift gate is a static equality check — every variation breaks CI.

Usage:
    uv run python scripts/sync_sdk_versions.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OPENAPI_PATH = REPO_ROOT / "backend" / "openapi.json"
PY_PYPROJECT = REPO_ROOT / "sdks" / "python" / "pyproject.toml"
PY_GEN_CONFIG = REPO_ROOT / "sdks" / "python" / ".openapi-python-client.yaml"
TS_PACKAGE = REPO_ROOT / "sdks" / "typescript" / "package.json"


def _read_openapi_version() -> str:
    if not OPENAPI_PATH.exists():
        sys.stderr.write(
            f"backend/openapi.json missing at {OPENAPI_PATH}.\n"
            "Run `make openapi` first.\n"
        )
        sys.exit(1)
    spec = json.loads(OPENAPI_PATH.read_text())
    version = spec.get("info", {}).get("version")
    if not version or not isinstance(version, str):
        sys.stderr.write(
            "backend/openapi.json has no info.version string. Cannot sync.\n"
        )
        sys.exit(1)
    return version


def _replace_pyproject_version(text: str, version: str) -> str:
    # Match: version = "..." (only inside [project] section).
    # Simple line-based replacement — pyproject.toml is hand-maintained and
    # only one [project] section exists.
    pattern = re.compile(r'^version = "[^"]*"$', re.MULTILINE)
    new_text, count = pattern.subn(f'version = "{version}"', text)
    if count != 1:
        sys.stderr.write(
            f"Expected exactly 1 'version = \"...\"' line in {PY_PYPROJECT}, "
            f"found {count}.\n"
        )
        sys.exit(1)
    return new_text


def _replace_yaml_version(text: str, version: str) -> str:
    pattern = re.compile(r"^package_version_override: .*$", re.MULTILINE)
    new_text, count = pattern.subn(
        f"package_version_override: {version}", text
    )
    if count != 1:
        sys.stderr.write(
            f"Expected exactly 1 'package_version_override:' line in "
            f"{PY_GEN_CONFIG}, found {count}.\n"
        )
        sys.exit(1)
    return new_text


def _replace_package_json_version(text: str, version: str) -> dict:
    # JSON parse round-trip preserves field order in Python 3.7+ dicts.
    data = json.loads(text)
    data["version"] = version
    return data


def main() -> int:
    version = _read_openapi_version()

    # Python pyproject.toml
    py_text = PY_PYPROJECT.read_text()
    new_py_text = _replace_pyproject_version(py_text, version)
    if new_py_text != py_text:
        PY_PYPROJECT.write_text(new_py_text)
        print(f"Updated {PY_PYPROJECT.relative_to(REPO_ROOT)} version → {version}")

    # openapi-python-client config
    yaml_text = PY_GEN_CONFIG.read_text()
    new_yaml_text = _replace_yaml_version(yaml_text, version)
    if new_yaml_text != yaml_text:
        PY_GEN_CONFIG.write_text(new_yaml_text)
        print(f"Updated {PY_GEN_CONFIG.relative_to(REPO_ROOT)} package_version_override → {version}")

    # TypeScript package.json — preserve trailing newline if present
    ts_text = TS_PACKAGE.read_text()
    had_trailing_newline = ts_text.endswith("\n")
    ts_data = _replace_package_json_version(ts_text, version)
    new_ts_text = json.dumps(ts_data, indent=2)
    if had_trailing_newline:
        new_ts_text += "\n"
    if new_ts_text != ts_text:
        TS_PACKAGE.write_text(new_ts_text)
        print(f"Updated {TS_PACKAGE.relative_to(REPO_ROOT)} version → {version}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

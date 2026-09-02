"""Version-coherence gate: assert EVERY version site agrees (REL-04).

Reads the version from every place the project records one and exits non-zero
if any disagree, printing the offending site(s). This is the READ/verify side of
the version contract; scripts/bump_version.py is the WRITE side. One site the
bump writes is verified elsewhere rather than here: docs-contract.json's
`.version` is asserted against backend/pyproject.toml by
scripts/check_docs_contract.py, so the two enumerations differ by that entry —
no coverage gap, but do not read this list as the bump's mirror image.

Also asserts CHANGELOG.md carries a `## [<version>]` section for the canonical
version. .github/workflows/release.yml extracts the release body by matching
that exact header and silently falls back to a raw `git log` list when it finds
nothing — a fallback whose own filter drops every `docs(`/`chore(` subject, so a
release whose headline change landed as `chore(db): upgrade ... PostgreSQL 18`
would publish notes that never mention it. Nothing else in CI reads CHANGELOG.md.

Also asserts the reference-style link block at the bottom of CHANGELOG.md
agrees with the canonical version (fix(#1716)): a `[<version>]:` compare link
must exist for the canonical version, and `[Unreleased]:` must compare from
`v<version>...HEAD`, not an older tag. Both edits used to be manual and
unenforced, so a release could ship with an unlinked heading while
`[Unreleased]` kept claiming every change in the release that just shipped
(seen on v1.17.0, #1714). scripts/bump_version.py now writes both lines
mechanically; this is the backstop.

Sites checked:
  - backend/pyproject.toml                  [project].version (canonical)
  - backend/app/api/main.py                 _FALLBACK_APP_VERSION constant
  - backend/openapi.json                    info.version
  - frontend/package.json                   .version
  - package.json                            (root) .version
  - cli/pyproject.toml                      [project].version
  - mcp/pyproject.toml                      [project].version
  - mcp/server.json                         .version + packages[].version (the
                                            MCP Registry manifest)
  - sdks/python/pyproject.toml              [project].version
  - sdks/python/.openapi-python-client.yaml package_version_override
  - sdks/typescript/package.json            .version
  - backend/uv.lock                         package 'geolens-backend'.version
  - mcp/uv.lock                             package 'geolens-mcp'.version and
                                            package 'geolens'.version (the
                                            editable sdks/python path dep)
  - package-lock.json (root)                .version + packages."".version
  - frontend/package-lock.json              .version + packages."".version
  - sdks/typescript/package-lock.json       .version + packages."".version

The lockfiles are checked because every one of them lagged a release at least
once while `make bump` rewrote only the manifests (fix(#877)). Each site is read
structurally — the package's OWN entry, not "the version string appears in the
file" — since any dependency could coincidentally sit at the same version.

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
MCP_SERVER_JSON = REPO_ROOT / "mcp" / "server.json"
PY_SDK_PYPROJECT = REPO_ROOT / "sdks" / "python" / "pyproject.toml"
PY_SDK_GEN_CONFIG = REPO_ROOT / "sdks" / "python" / ".openapi-python-client.yaml"
TS_SDK_PACKAGE = REPO_ROOT / "sdks" / "typescript" / "package.json"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

# The reference-style link block at the bottom of CHANGELOG.md, e.g.:
#   [Unreleased]: https://github.com/geolens-io/geolens/compare/v1.17.0...HEAD
#   [1.17.0]: https://github.com/geolens-io/geolens/compare/v1.16.1...v1.17.0
# scripts/bump_version.py writes this same shape.
CHANGELOG_REPO_URL = "https://github.com/geolens-io/geolens"
_LINK_DEF_RE = re.compile(r"^\[([^\]]+)\]: (\S+)$", re.MULTILINE)
_COMPARE_LINK_RE = re.compile(
    rf"^{re.escape(CHANGELOG_REPO_URL)}/compare/"
    rf"v(?P<from>\d+\.\d+\.\d+)\.\.\.(?P<to>v\d+\.\d+\.\d+|HEAD)$"
)

# Lockfiles that embed the package's own version (fix(#877)). A uv.lock records
# it for every LOCAL package it resolves — the project itself plus any editable
# path dependency in this repo (mcp/ depends on sdks/python) — so both of mcp's
# entries move on a bump. bump_version.py stamps this same set.
UV_LOCKS: tuple[tuple[Path, tuple[str, ...]], ...] = (
    (REPO_ROOT / "backend" / "uv.lock", ("geolens-backend",)),
    (REPO_ROOT / "mcp" / "uv.lock", ("geolens-mcp", "geolens")),
)
PACKAGE_LOCKS: tuple[Path, ...] = (
    REPO_ROOT / "package-lock.json",
    REPO_ROOT / "frontend" / "package-lock.json",
    REPO_ROOT / "sdks" / "typescript" / "package-lock.json",
)


def _rel(p: Path) -> str:
    return str(p.relative_to(REPO_ROOT))


def _pyproject_version(path: Path) -> str:
    data = tomllib.loads(path.read_text())
    return data["project"]["version"]


def _package_json_version(path: Path) -> str:
    return json.loads(path.read_text())["version"]


def _server_json_versions(path: Path) -> list[tuple[str, str]]:
    """(label, version) for the server release and every package it declares."""
    data = json.loads(path.read_text())
    found = [(".version", data["version"])]
    packages = data.get("packages")
    if not packages:
        sys.exit(f"ERROR: no 'packages' entries in {_rel(path)}.")
    for package in packages:
        found.append((f"packages['{package['identifier']}'].version", package["version"]))
    return found


def _openapi_version(path: Path) -> str:
    return json.loads(path.read_text())["info"]["version"]


def _main_fallback_version(path: Path) -> str:
    m = re.search(
        r'^_FALLBACK_APP_VERSION = "([^"]*)"$', path.read_text(), re.MULTILINE
    )
    if not m:
        sys.exit(f"ERROR: no _FALLBACK_APP_VERSION line in {_rel(path)}.")
    return m.group(1)


def _yaml_override_version(path: Path) -> str:
    m = re.search(r"^package_version_override: (.*)$", path.read_text(), re.MULTILINE)
    if not m:
        sys.exit(f"ERROR: no package_version_override line in {_rel(path)}.")
    return m.group(1).strip()


def _uv_lock_package_version(path: Path, name: str) -> str:
    """The version uv.lock records for one LOCAL `[[package]]` entry."""
    for pkg in tomllib.loads(path.read_text()).get("package", []):
        if pkg.get("name") != name:
            continue
        source = pkg.get("source", {})
        # Only a local entry (this project, or an in-repo path dep) carries the
        # repo's version; a registry entry would be an unrelated published one.
        if not any(k in source for k in ("editable", "virtual", "directory")):
            sys.exit(
                f"ERROR: '{name}' in {_rel(path)} is not a local package (source={source}); "
                f"it no longer tracks this repo's version — update the UV_LOCKS list."
            )
        return pkg["version"]
    sys.exit(f"ERROR: no '{name}' [[package]] entry in {_rel(path)}.")


def _package_lock_versions(path: Path) -> tuple[str, str]:
    """(top-level .version, packages[""].version) — npm records both."""
    data = json.loads(path.read_text())
    root = data.get("packages", {}).get("")
    if "version" not in data or not isinstance(root, dict) or "version" not in root:
        sys.exit(
            f'ERROR: {_rel(path)} lacks a top-level "version" and/or a packages.""'
            f' "version" (expected the lockfileVersion 3 shape).'
        )
    return data["version"], root["version"]


def _changelog_section(version: str) -> str | None:
    """The lines under `## [version]`, or None if that header is absent.

    Deliberately the same extraction .github/workflows/release.yml performs:

        awk "/^## \\[${VERSION}\\]/{found=1; next} /^## \\[/{if(found) exit} found{print}"

    The gate is only worth anything if it answers the question release.yml
    actually asks, so the two must agree on where a section starts and ends.
    """
    out: list[str] = []
    found = False
    for line in CHANGELOG.read_text().splitlines():
        if not found:
            if re.match(rf"^## \[{re.escape(version)}\]", line):
                found = True
            continue
        if line.startswith("## ["):
            break
        out.append(line)
    return "\n".join(out) if found else None


def _changelog_links() -> dict[str, str]:
    """Reference-style link definitions (`[label]: url`), keyed by label.

    Returns an empty dict for a CHANGELOG with no link block at all, so a
    caller doing a plain `.get()` fails with the FAIL messages below instead
    of a traceback.
    """
    return dict(_LINK_DEF_RE.findall(CHANGELOG.read_text()))


def _check_changelog_links(canonical: str) -> list[str]:
    """FAIL messages for the CHANGELOG's reference-style compare links.

    An empty list means both checks passed: a `[<canonical>]:` compare link
    exists, and `[Unreleased]:` compares from `v<canonical>...HEAD` rather
    than an older tag. A CHANGELOG with no link block at all (an empty dict
    from `_changelog_links()`) fails both checks with a plain message here,
    not a traceback.
    """
    links = _changelog_links()
    failures: list[str] = []

    unreleased_url = links.get("Unreleased")
    if unreleased_url is None:
        failures.append(
            f"{_rel(CHANGELOG)} has no '[Unreleased]:' compare link definition."
        )
    else:
        m = _COMPARE_LINK_RE.match(unreleased_url)
        if not m or m.group("to") != "HEAD":
            failures.append(
                f"{_rel(CHANGELOG)}'s '[Unreleased]:' link is not a "
                f"'{CHANGELOG_REPO_URL}/compare/vX.Y.Z...HEAD' link. Got: {unreleased_url!r}"
            )
        elif m.group("from") != canonical:
            failures.append(
                f"{_rel(CHANGELOG)}'s '[Unreleased]:' link compares from "
                f"v{m.group('from')}, not v{canonical} - it still claims every change "
                f"since the last release as unreleased. Repoint it to "
                f"'{CHANGELOG_REPO_URL}/compare/v{canonical}...HEAD'."
            )

    version_url = links.get(canonical)
    if version_url is None:
        failures.append(
            f"{_rel(CHANGELOG)} has no '[{canonical}]:' compare link definition. "
            f"Add '[{canonical}]: {CHANGELOG_REPO_URL}/compare/vPREV...v{canonical}' "
            f"to the link block (run `make bump VERSION={canonical}` to write it)."
        )
    else:
        m = _COMPARE_LINK_RE.match(version_url)
        if not m or m.group("to") != f"v{canonical}":
            failures.append(
                f"{_rel(CHANGELOG)}'s '[{canonical}]:' link does not compare "
                f"...v{canonical}. Got: {version_url!r}"
            )

    return failures


def main() -> int:
    sites: dict[str, str] = {}
    sites[f"{_rel(BACKEND_PYPROJECT)} ([project].version)"] = _pyproject_version(
        BACKEND_PYPROJECT
    )
    sites[f"{_rel(MAIN_PY)} (_FALLBACK_APP_VERSION)"] = _main_fallback_version(MAIN_PY)
    sites[f"{_rel(OPENAPI_PATH)} (info.version)"] = _openapi_version(OPENAPI_PATH)
    sites[f"{_rel(FRONTEND_PACKAGE)} (.version)"] = _package_json_version(
        FRONTEND_PACKAGE
    )
    sites[f"{_rel(ROOT_PACKAGE)} (.version)"] = _package_json_version(ROOT_PACKAGE)
    sites[f"{_rel(CLI_PYPROJECT)} ([project].version)"] = _pyproject_version(
        CLI_PYPROJECT
    )
    sites[f"{_rel(MCP_PYPROJECT)} ([project].version)"] = _pyproject_version(
        MCP_PYPROJECT
    )
    for label, found in _server_json_versions(MCP_SERVER_JSON):
        sites[f"{_rel(MCP_SERVER_JSON)} ({label})"] = found
    sites[f"{_rel(PY_SDK_PYPROJECT)} ([project].version)"] = _pyproject_version(
        PY_SDK_PYPROJECT
    )
    sites[f"{_rel(PY_SDK_GEN_CONFIG)} (package_version_override)"] = (
        _yaml_override_version(PY_SDK_GEN_CONFIG)
    )
    sites[f"{_rel(TS_SDK_PACKAGE)} (.version)"] = _package_json_version(TS_SDK_PACKAGE)
    for lock, package_names in UV_LOCKS:
        for name in package_names:
            sites[f"{_rel(lock)} (package '{name}'.version)"] = (
                _uv_lock_package_version(lock, name)
            )
    for lock in PACKAGE_LOCKS:
        top, root = _package_lock_versions(lock)
        sites[f"{_rel(lock)} (.version)"] = top
        sites[f'{_rel(lock)} (packages."".version)'] = root

    # Canonical = backend distribution version (what the app derives at runtime).
    canonical = sites[f"{_rel(BACKEND_PYPROJECT)} ([project].version)"]

    # fix(#1019): print every site BEFORE any check can return. Both CHANGELOG
    # failure paths used to sit above this listing, so a `make version-check`
    # that failed on the CHANGELOG never said whether the lockfiles and
    # manifests had stamped — which is the whole reason you run it mid-bump.
    # For the same reason both halves are now collected and reported together
    # instead of returning on the first.
    print(
        f"Version sites ({len(sites)}), "
        f"canonical (backend/pyproject.toml) = {canonical}:"
    )
    for site, v in sites.items():
        print(f"  [{'ok' if v == canonical else 'DRIFT'}] {site}: {v}")

    failed = False

    offenders = {site: v for site, v in sites.items() if v != canonical}
    if offenders:
        failed = True
        sys.stderr.write(
            f"FAIL: version drift detected. Canonical (backend/pyproject.toml) = {canonical!r}.\n"
            f"Run `make bump VERSION={canonical}` to resync, or correct the offending site:\n"
        )
        for site, v in offenders.items():
            sys.stderr.write(f"  - {site}: {v!r} != {canonical!r}\n")

    # Mirror release.yml's awk: take the lines between this version's header and
    # the next `## [` one. Matching the header alone is not enough — an empty
    # section extracts to an empty body, and release.yml's `[ -z "$NOTES" ]`
    # takes the same git-log fallback as a missing one.
    body = _changelog_section(canonical)
    if body is None:
        failed = True
        sys.stderr.write(
            f"FAIL: {_rel(CHANGELOG)} has no '## [{canonical}]' section.\n"
            f"release.yml extracts the release body by matching that exact header and\n"
            f"silently falls back to a raw git-log list when it is missing. Rename the\n"
            f"'## [Unreleased]' header to '## [{canonical}] - <date>' (keeping a fresh\n"
            f"empty Unreleased above it) and add the matching link reference.\n"
        )
    elif not body.strip():
        failed = True
        sys.stderr.write(
            f"FAIL: {_rel(CHANGELOG)}'s '## [{canonical}]' section is empty.\n"
            f"release.yml treats an empty section exactly like a missing one and\n"
            f"falls back to the raw git-log list. Write the release notes under that\n"
            f"header before tagging.\n"
        )
    else:
        lines = len([ln for ln in body.strip().splitlines() if ln.strip()])
        print(
            f"  [ok] {_rel(CHANGELOG)}: '## [{canonical}]' section present ({lines} lines)."
        )

    # fix(#1716): the reference-style compare links at the bottom of the file
    # are not part of the `## [version]` section check above, and nothing else
    # in CI reads them — a release can land with a correct header and section
    # while `[Unreleased]` still compares from the previous tag and the new
    # version has no link at all (v1.17.0, #1714). scripts/bump_version.py
    # writes both lines mechanically; this asserts they landed.
    link_failures = _check_changelog_links(canonical)
    if link_failures:
        failed = True
        for msg in link_failures:
            sys.stderr.write(f"FAIL: {msg}\n")
    else:
        print(
            f"  [ok] {_rel(CHANGELOG)}: '[Unreleased]:' and '[{canonical}]:' "
            f"compare links agree with {canonical}."
        )

    if failed:
        return 1

    print(f"OK: all {len(sites)} version sites agree on {canonical}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

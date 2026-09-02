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
  - mcp/server.json                        (.version and packages[].version — the
                                           MCP Registry manifest. The registry
                                           rejects a publish whose package version
                                           is not the one live on PyPI, so both
                                           fields move with the release)
  - sdks/python/pyproject.toml             ([project] version)
  - sdks/python/.openapi-python-client.yaml (package_version_override)
  - sdks/typescript/package.json           (.version)
  - docs-contract.json                     (.version — the cross-surface doc
                                           contract; check_docs_contract.py
                                           asserts it equals backend/pyproject)
  - CHANGELOG.md                           (the reference-style compare links at
                                           the bottom of the file: `[Unreleased]`
                                           is repointed to compare/vX.Y.Z...HEAD
                                           and a new `[X.Y.Z]:` link is inserted
                                           comparing from the previous version,
                                           fix(#1716))

Every lockfile that embeds the package's own version is stamped too (fix(#877) —
each of these had to be hand-stamped on past releases, and each was missed at
least once):

  - backend/uv.lock                        (the `geolens-backend` entry)
  - mcp/uv.lock                            (`geolens-mcp` + the `geolens`
                                           editable path entry for sdks/python)
  - package-lock.json                      (root)
  - frontend/package-lock.json
  - sdks/typescript/package-lock.json      (each package-lock records its own
                                           version TWICE: top-level and
                                           packages."")

The lockfiles are rewritten in place rather than by re-running `uv lock` /
`npm install --package-lock-only`: a version bump changes no requirement, so the
resolution is unchanged, and an in-place stamp needs neither uv/npm on PATH nor a
network round-trip that could drag unrelated dependency churn into a release
commit.

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
MCP_SERVER_JSON = REPO_ROOT / "mcp" / "server.json"
PY_SDK_PYPROJECT = REPO_ROOT / "sdks" / "python" / "pyproject.toml"
PY_SDK_GEN_CONFIG = REPO_ROOT / "sdks" / "python" / ".openapi-python-client.yaml"
TS_SDK_PACKAGE = REPO_ROOT / "sdks" / "typescript" / "package.json"
DOCS_CONTRACT = REPO_ROOT / "docs-contract.json"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
CHANGELOG_REPO_URL = "https://github.com/geolens-io/geolens"

# --- Lockfiles (fix(#877)) ---------------------------------------------------
# A uv.lock records the version of every LOCAL package it resolves: the project
# itself, plus any editable path dependency inside this repo. mcp/ depends on
# sdks/python, so its lock carries that package's version as well and both move
# on a bump. Names are the `[project].name` of the owning pyproject — a rename
# makes the bump fail loudly with "found 0" rather than skip a site.
UV_LOCKS: tuple[tuple[Path, tuple[str, ...]], ...] = (
    (REPO_ROOT / "backend" / "uv.lock", ("geolens-backend",)),
    (REPO_ROOT / "mcp" / "uv.lock", ("geolens-mcp", "geolens")),
)
PACKAGE_LOCKS: tuple[Path, ...] = (
    REPO_ROOT / "package-lock.json",
    REPO_ROOT / "frontend" / "package-lock.json",
    REPO_ROOT / "sdks" / "typescript" / "package-lock.json",
)

# `  "version": "..."` plus whatever follows the closing quote (a comma, maybe a
# CR) so the line rebuilds byte-for-byte.
_JSON_VERSION_LINE = re.compile(r'^(\s*"version": )"[^"]*"(.*)$')
# The root entry of a lockfileVersion-3 `packages` map.
_PACKAGE_LOCK_ROOT_ENTRY = re.compile(r'^\s*"": \{\s*$')


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


def _bump_server_json(path: Path, version: str) -> None:
    # The MCP Registry manifest records the version twice: once for the server
    # release and once for the PyPI package it points at. A missing `packages`
    # list means the file was restructured, so fail rather than stamp half of it.
    text = path.read_text()
    had_trailing_newline = text.endswith("\n")
    data = json.loads(text)
    packages = data.get("packages")
    if not packages:
        sys.exit(f"ERROR: expected at least one entry under 'packages' in {_rel(path)}, found none.")
    data["version"] = version
    for package in packages:
        package["version"] = version
    new_text = json.dumps(data, indent=2)
    if had_trailing_newline:
        new_text += "\n"
    path.write_text(new_text)
    print(f"  {_rel(path)} (.version + packages[].version) -> {version}")


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


def _bump_uv_lock(path: Path, package_names: tuple[str, ...], version: str) -> None:
    # uv writes every entry as `[[package]]` / `name` / `version` / `source`, so
    # anchoring on the header + name pins the one version line that belongs to
    # this package — a same-named dependency string elsewhere can't match. The
    # source is part of the match on purpose: only a LOCAL entry (this project or
    # an in-repo path dep) tracks the repo version, so a package that ever became
    # a registry dependency fails here loudly instead of being stamped wrong.
    text = path.read_text()
    for name in package_names:
        pattern = re.compile(
            rf'^(\[\[package\]\]\nname = "{re.escape(name)}"\nversion = )"[^"]*"'
            rf"(\nsource = \{{ (?:editable|virtual|directory) )",
            re.MULTILINE,
        )
        text, count = pattern.subn(rf'\g<1>"{version}"\g<2>', text, count=1)
        if count != 1:
            sys.exit(
                f"ERROR: expected 1 local '{name}' [[package]] entry in {_rel(path)}, found {count}."
            )
    path.write_text(text)
    for name in package_names:
        print(f"  {_rel(path)} (package '{name}'.version) -> {version}")


def _bump_package_lock(path: Path, version: str) -> None:
    # npm records the package's own version twice — top-level and in the
    # `packages` root entry — and keeps them in sync; stamping only one leaves
    # the lock incoherent. Rewritten line-wise instead of via a json round-trip
    # so the diff stays two lines and npm's exact formatting survives.
    lines = path.read_text().split("\n")
    top_idx: int | None = None
    root_idx: int | None = None
    in_root_entry = False
    for i, line in enumerate(lines):
        if _PACKAGE_LOCK_ROOT_ENTRY.match(line):
            in_root_entry = True
            continue
        if not _JSON_VERSION_LINE.match(line):
            continue
        if in_root_entry:
            root_idx = i
            break
        if top_idx is None:
            top_idx = i
    if top_idx is None or root_idx is None:
        sys.exit(
            f'ERROR: {_rel(path)} lacks a top-level "version" and/or a packages.""'
            f' "version" line (expected the lockfileVersion 3 shape).'
        )
    for i in (top_idx, root_idx):
        m = _JSON_VERSION_LINE.match(lines[i])
        assert m is not None  # matched above
        lines[i] = f'{m.group(1)}"{version}"{m.group(2)}'
    path.write_text("\n".join(lines))
    print(f'  {_rel(path)} (.version + packages."".version) -> {version}')


# `[Unreleased]:` in whatever shape it currently reads, so a malformed line
# gets repaired rather than silently ignored.
_UNRELEASED_LINE_RE = re.compile(r"^\[Unreleased\]: .*$", re.MULTILINE)
# A `## [<version>]` section heading, optionally followed by ` - <date>`.
_CHANGELOG_HEADER_RE = re.compile(r"^## \[([^\]]+)\]")


def _changelog_prev_version(text: str, version: str) -> str | None:
    """The version whose `## [...]` section immediately follows `version`'s.

    None if `version`'s section is the last one in the file — the initial
    release, with no preceding version to compare from.
    """
    found = False
    for line in text.splitlines():
        m = _CHANGELOG_HEADER_RE.match(line)
        if not m:
            continue
        label = m.group(1)
        if found:
            if label == "Unreleased":
                continue
            return label
        if label == version:
            found = True
    return None


def _bump_changelog_links(path: Path, version: str) -> None:
    """Repoint `[Unreleased]` and ensure `[X.Y.Z]:` compares from the right tag.

    The previous version is read from the CHANGELOG's own section structure
    (the `## [...]` heading immediately below `## [version]`), not from the
    current `[Unreleased]` link text — check_version_coherence.py verifies
    the link against that same structural rule, so the two agree by
    construction. Repairs whichever half is missing or wrong rather than
    bailing out as soon as `[Unreleased]` already points at `version`: a
    partial or hand-edited state — `[Unreleased]` repointed but the
    `[X.Y.Z]:` link missing or stale — used to be left unrepaired
    (fix(#1716 review)). A true no-op (both lines already correct) still
    writes nothing.
    """
    text = path.read_text()

    unreleased_m = _UNRELEASED_LINE_RE.search(text)
    if not unreleased_m:
        sys.exit(
            f"ERROR: no '[Unreleased]: ...' line in {_rel(path)}. Add the "
            f"reference-style link block before bumping."
        )

    prev_version = _changelog_prev_version(text, version)
    if prev_version is None:
        sys.exit(
            f"ERROR: {_rel(path)} has no '## [...]' section below '## [{version}]' "
            f"to read the previous version from. Add the release's CHANGELOG "
            f"section (and the section for the version before it) before bumping."
        )

    expected_unreleased = f"[Unreleased]: {CHANGELOG_REPO_URL}/compare/v{version}...HEAD"
    expected_version_link = (
        f"[{version}]: {CHANGELOG_REPO_URL}/compare/v{prev_version}...v{version}"
    )

    changed = False
    if unreleased_m.group(0) != expected_unreleased:
        text = text[: unreleased_m.start()] + expected_unreleased + text[unreleased_m.end() :]
        changed = True

    version_line_re = re.compile(rf"^\[{re.escape(version)}\]: .*$", re.MULTILINE)
    version_m = version_line_re.search(text)
    if version_m is None:
        text = text.replace(
            expected_unreleased, f"{expected_unreleased}\n{expected_version_link}", 1
        )
        changed = True
    elif version_m.group(0) != expected_version_link:
        text = text[: version_m.start()] + expected_version_link + text[version_m.end() :]
        changed = True

    if not changed:
        print(f"  {_rel(path)} (compare links) already correct for {version}, skipping.")
        return

    path.write_text(text)
    print(
        f"  {_rel(path)} ([Unreleased] -> compare/v{version}...HEAD, "
        f"[{version}] -> compare/v{prev_version}...v{version})"
    )


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
    _bump_server_json(MCP_SERVER_JSON, version)
    _bump_project_version(PY_SDK_PYPROJECT, version)
    _bump_yaml_override(PY_SDK_GEN_CONFIG, version)
    _bump_package_json(TS_SDK_PACKAGE, version)
    _bump_top_level_json_version(DOCS_CONTRACT, version)
    for lock, package_names in UV_LOCKS:
        _bump_uv_lock(lock, package_names, version)
    for lock in PACKAGE_LOCKS:
        _bump_package_lock(lock, version)
    _bump_changelog_links(CHANGELOG, version)
    print(f"Done. Run `make version-check` to confirm coherence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

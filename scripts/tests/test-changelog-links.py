#!/usr/bin/env python3
"""Regression test for the CHANGELOG compare-link block (fix(#1716)).

`make bump` used to rewrite every version site except the reference-style
compare links at the bottom of CHANGELOG.md, and `check_version_coherence.py`
(the `make version-check` gate) never read them either. A release could ship
with a correct `## [version]` header and section while `[Unreleased]` still
compared from the previous tag and the new version had no link at all
(v1.17.0, #1714). This pins both halves of the fix:

  - scripts/check_version_coherence.py's `_check_changelog_links()`, which
    `main()` now folds into the gate's pass/fail decision.
  - scripts/bump_version.py's `_bump_changelog_links()`, which writes both
    lines mechanically.

Pure stdlib, no repo state: each case builds its own CHANGELOG in a tmpdir.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _load(name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cvc = _load("cvc", "scripts/check_version_coherence.py")
bv = _load("bv", "scripts/bump_version.py")

PASS = FAIL = 0


def ok(msg: str) -> None:
    global PASS
    PASS += 1
    print(f"ok {PASS + FAIL} - {msg}")


def bad(msg: str) -> None:
    global FAIL
    FAIL += 1
    print(f"not ok {PASS + FAIL} - {msg}")


def _write(text: str) -> pathlib.Path:
    # `_rel()` in both modules does `path.relative_to(REPO_ROOT)` for its
    # FAIL/print messages, so a tmp CHANGELOG needs REPO_ROOT repointed at its
    # own tmpdir in both modules, not left at the real repo root.
    d = pathlib.Path(tempfile.mkdtemp())
    f = d / "CHANGELOG.md"
    f.write_text(text)
    cvc.REPO_ROOT = d
    bv.REPO_ROOT = d
    return f


REPO = "https://github.com/geolens-io/geolens"

# A realistic tail: two release sections plus their link block, in the exact
# shape the real CHANGELOG.md uses (no blank lines between consecutive link
# definitions).
CORRECT = (
    "## [Unreleased]\n\n"
    "## [1.5.0] - 2026-07-26\n\n### Added\n- a thing\n\n"
    "## [1.4.13]\n- old\n\n"
    f"[Unreleased]: {REPO}/compare/v1.5.0...HEAD\n"
    f"[1.5.0]: {REPO}/compare/v1.4.13...v1.5.0\n"
    f"[1.4.13]: {REPO}/compare/v1.4.12...v1.4.13\n"
)

MISSING_VERSION_LINK = (
    "## [Unreleased]\n\n## [1.5.0] - 2026-07-26\n\n### Added\n- a thing\n\n"
    f"[Unreleased]: {REPO}/compare/v1.5.0...HEAD\n"
    f"[1.4.13]: {REPO}/compare/v1.4.12...v1.4.13\n"
)

STALE_UNRELEASED = (
    "## [Unreleased]\n\n## [1.5.0] - 2026-07-26\n\n### Added\n- a thing\n\n"
    f"[Unreleased]: {REPO}/compare/v1.4.13...HEAD\n"
    f"[1.5.0]: {REPO}/compare/v1.4.13...v1.5.0\n"
    f"[1.4.13]: {REPO}/compare/v1.4.12...v1.4.13\n"
)

NO_LINK_BLOCK = "## [Unreleased]\n\n## [1.5.0] - 2026-07-26\n\n### Added\n- a thing\n"

# --- 1. correct block passes -------------------------------------------------
cvc.CHANGELOG = _write(CORRECT)
failures = cvc._check_changelog_links("1.5.0")
if failures == []:
    ok("correct compare-link block reports no failures")
else:
    bad(f"correct block reported failures: {failures!r}")

# --- 2. missing [X.Y.Z]: link fails ------------------------------------------
cvc.CHANGELOG = _write(MISSING_VERSION_LINK)
failures = cvc._check_changelog_links("1.5.0")
if any("[1.5.0]:" in f and "no" in f for f in failures):
    ok("a missing '[1.5.0]:' link definition is reported")
else:
    bad(f"missing version link was not reported: {failures!r}")
if not any("Unreleased" in f for f in failures):
    ok("the correct '[Unreleased]:' link is not also flagged")
else:
    bad(f"a correct '[Unreleased]:' link was wrongly flagged: {failures!r}")

# --- 3. stale [Unreleased] fails ---------------------------------------------
cvc.CHANGELOG = _write(STALE_UNRELEASED)
failures = cvc._check_changelog_links("1.5.0")
if any("Unreleased" in f and "v1.4.13" in f and "v1.5.0" in f for f in failures):
    ok("an '[Unreleased]:' link still comparing from the previous tag is reported")
else:
    bad(f"stale '[Unreleased]:' link was not reported: {failures!r}")
if len(failures) == 1:
    ok("the correct '[1.5.0]:' link is not also flagged")
else:
    bad(
        f"expected exactly 1 failure for a stale-Unreleased-only case, got: {failures!r}"
    )

# --- 4. no link block at all gives a clear error, not a traceback -----------
cvc.CHANGELOG = _write(NO_LINK_BLOCK)
try:
    failures = cvc._check_changelog_links("1.5.0")
except Exception as exc:  # noqa: BLE001 - the point is that nothing raises here
    bad(f"a CHANGELOG with no link block raised {exc!r} instead of returning failures")
else:
    if len(failures) == 2 and all(isinstance(f, str) and f for f in failures):
        ok("a CHANGELOG with no link block at all reports two clear failures")
    else:
        bad(f"expected 2 plain-string failures for no link block, got: {failures!r}")

# --- 5. bump writes both lines ------------------------------------------------
before = (
    "## [Unreleased]\n\n## [1.4.13]\n- old\n\n"
    f"[Unreleased]: {REPO}/compare/v1.4.13...HEAD\n"
    f"[1.4.13]: {REPO}/compare/v1.4.12...v1.4.13\n"
)
bump_path = _write(before)
bv._bump_changelog_links(bump_path, "1.5.0")
after = bump_path.read_text()
expected_unreleased = f"[Unreleased]: {REPO}/compare/v1.5.0...HEAD"
expected_version = f"[1.5.0]: {REPO}/compare/v1.4.13...v1.5.0"
if expected_unreleased in after and expected_version in after:
    ok("bump writes both the repointed [Unreleased] and the new [1.5.0] link")
else:
    bad(f"bump did not write the expected lines. Got:\n{after}")
if f"{expected_unreleased}\n{expected_version}\n" in after:
    ok("bump preserves the block's ordering and blank-line shape")
else:
    bad(f"bump changed the block's shape. Got:\n{after}")
if "[1.4.13]: " in after:
    ok("bump leaves the older [1.4.13] link untouched")
else:
    bad(f"bump dropped an unrelated link. Got:\n{after}")

# --- 6. bump is idempotent ----------------------------------------------------
once = bump_path.read_text()
bv._bump_changelog_links(bump_path, "1.5.0")
twice = bump_path.read_text()
if once == twice:
    ok("running bump twice for the same version changes nothing further")
else:
    bad(
        f"a second bump for the same version changed the file:\nfirst:\n{once}\nsecond:\n{twice}"
    )
if twice.count("[1.5.0]: ") == 1:
    ok("running bump twice produces no second [1.5.0] link")
else:
    bad(f"expected exactly one '[1.5.0]: ' line, got {twice.count('[1.5.0]: ')}")

# --- 7. bump against a CHANGELOG with no link block gives a clear error ------
no_block_path = _write(NO_LINK_BLOCK)
try:
    bv._bump_changelog_links(no_block_path, "1.5.0")
except SystemExit as exc:
    if isinstance(exc.code, str) and exc.code.startswith("ERROR:"):
        ok(
            "bump against a CHANGELOG with no link block exits with a clear ERROR message"
        )
    else:
        bad(f"bump's error path did not produce a clear message: {exc.code!r}")
else:
    bad("bump against a CHANGELOG with no link block did not raise SystemExit")

print(f"1..{PASS + FAIL}")
print(f"# {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)

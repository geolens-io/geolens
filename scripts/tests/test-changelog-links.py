#!/usr/bin/env python3
"""Regression test for the CHANGELOG compare-link block (fix(#1716)).

`make bump` used to rewrite every version site except the reference-style
compare links at the bottom of CHANGELOG.md, and `check_version_coherence.py`
(the `make version-check` gate) never read them either. A release could ship
with a correct `## [version]` header and section while `[Unreleased]` still
compared from the previous tag and the new version had no link at all
(v1.17.0, #1714). This pins both halves of the fix:

  - scripts/check_version_coherence.py's `_check_changelog_links()`, which
    `main()` now folds into the gate's pass/fail decision. It validates the
    `[X.Y.Z]:` link's `from` tag against the version whose `## [...]` section
    immediately follows `## [X.Y.Z]` in the file, not merely the link's
    shape - a first pass of this check only checked the `to` tag, which let
    `compare/vX.Y.Z...vX.Y.Z` (empty comparison) or an arbitrary wrong source
    pass (review finding on #1765).
  - scripts/bump_version.py's `_bump_changelog_links()`, which writes both
    lines mechanically, deriving the previous version the same structural
    way so the two agree by construction. It repairs whichever half is
    missing or wrong rather than skipping entirely once `[Unreleased]`
    already points at the target version - a first pass returned early in
    that case and left a partial hand-edit unrepaired (review finding on
    #1765).

Two more review rounds on #1765 added:

  - `_changelog_links()` in both scripts now resolves a duplicate reference
    label (compared case-insensitively, matching CommonMark) to the FIRST
    definition rather than whichever `dict()` happened to keep last, and a
    dedicated check fails outright when a duplicate exists at all - a stale
    first `[Unreleased]:` followed by a correct duplicate used to pass
    silently while the rendered CHANGELOG still used the stale one.
    bump_version.py refuses to bump a CHANGELOG with a duplicate label for
    the same reason.
  - `bump_version.py`'s `main()` now validates the CHANGELOG edit (via
    `_validate_changelog_links()`) BEFORE writing any other version site,
    so a CHANGELOG that can't be safely bumped aborts with nothing touched
    instead of leaving every other site already bumped while only the
    CHANGELOG failed, last.

Pure stdlib, no repo state: each case builds its own CHANGELOG in a tmpdir.
"""

from __future__ import annotations

import importlib.util
import json
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
# definitions). `## [1.4.13]` is a real section heading (not just a link
# line) so `_changelog_prev_version("1.5.0")` can derive it structurally.
CORRECT = (
    "## [Unreleased]\n\n"
    "## [1.5.0] - 2026-07-26\n\n### Added\n- a thing\n\n"
    "## [1.4.13]\n- old\n\n"
    f"[Unreleased]: {REPO}/compare/v1.5.0...HEAD\n"
    f"[1.5.0]: {REPO}/compare/v1.4.13...v1.5.0\n"
    f"[1.4.13]: {REPO}/compare/v1.4.12...v1.4.13\n"
)

# Same section structure as CORRECT (so PREV still derives to 1.4.13), just
# missing the `[1.5.0]:` link definition.
MISSING_VERSION_LINK = (
    "## [Unreleased]\n\n## [1.5.0] - 2026-07-26\n\n### Added\n- a thing\n\n"
    "## [1.4.13]\n- old\n\n"
    f"[Unreleased]: {REPO}/compare/v1.5.0...HEAD\n"
    f"[1.4.13]: {REPO}/compare/v1.4.12...v1.4.13\n"
)

# Same section structure as CORRECT, `[Unreleased]` still pointing at the
# previous tag instead of the canonical one.
STALE_UNRELEASED = (
    "## [Unreleased]\n\n## [1.5.0] - 2026-07-26\n\n### Added\n- a thing\n\n"
    "## [1.4.13]\n- old\n\n"
    f"[Unreleased]: {REPO}/compare/v1.4.13...HEAD\n"
    f"[1.5.0]: {REPO}/compare/v1.4.13...v1.5.0\n"
    f"[1.4.13]: {REPO}/compare/v1.4.12...v1.4.13\n"
)

# Same section structure as CORRECT, `[1.5.0]:` compares from an arbitrary
# wrong tag instead of the one the CHANGELOG's own section order implies.
WRONG_SOURCE = (
    "## [Unreleased]\n\n## [1.5.0] - 2026-07-26\n\n### Added\n- a thing\n\n"
    "## [1.4.13]\n- old\n\n"
    f"[Unreleased]: {REPO}/compare/v1.5.0...HEAD\n"
    f"[1.5.0]: {REPO}/compare/v1.0.0...v1.5.0\n"
    f"[1.4.13]: {REPO}/compare/v1.4.12...v1.4.13\n"
)

# The exact bug pattern named in review: an empty self-comparison. Its `to`
# tag is right, so a check that only validates `to` would pass this.
EMPTY_COMPARISON = (
    "## [Unreleased]\n\n## [1.5.0] - 2026-07-26\n\n### Added\n- a thing\n\n"
    "## [1.4.13]\n- old\n\n"
    f"[Unreleased]: {REPO}/compare/v1.5.0...HEAD\n"
    f"[1.5.0]: {REPO}/compare/v1.5.0...v1.5.0\n"
    f"[1.4.13]: {REPO}/compare/v1.4.12...v1.4.13\n"
)

NO_LINK_BLOCK = "## [Unreleased]\n\n## [1.5.0] - 2026-07-26\n\n### Added\n- a thing\n"

# The initial release in the file: no preceding `## [...]` section exists to
# derive a PREV tag from, so the conventional link is `releases/tag/vX.Y.Z`
# rather than a compare link.
FIRST_RELEASE_OK = (
    "## [Unreleased]\n\n## [1.2.0] - 2026-05-01\n\n### Added\n- first\n\n"
    f"[Unreleased]: {REPO}/compare/v1.2.0...HEAD\n"
    f"[1.2.0]: {REPO}/releases/tag/v1.2.0\n"
)

FIRST_RELEASE_BAD = (
    "## [Unreleased]\n\n## [1.2.0] - 2026-05-01\n\n### Added\n- first\n\n"
    f"[Unreleased]: {REPO}/compare/v1.2.0...HEAD\n"
    f"[1.2.0]: {REPO}/compare/v1.0.0...v1.2.0\n"
)

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

# --- 5. wrong source fails with a message naming both tags ------------------
cvc.CHANGELOG = _write(WRONG_SOURCE)
failures = cvc._check_changelog_links("1.5.0")
if any("1.4.13" in f and "1.5.0" in f for f in failures):
    ok("a '[1.5.0]:' link comparing from the wrong tag is reported, naming both tags")
else:
    bad(f"wrong-source version link was not reported: {failures!r}")
if len(failures) == 1:
    ok("the correct '[Unreleased]:' link is not also flagged for the wrong-source case")
else:
    bad(f"expected exactly 1 failure for a wrong-source-only case, got: {failures!r}")

# --- 5b. the empty-comparison variant of the same bug also fails ------------
cvc.CHANGELOG = _write(EMPTY_COMPARISON)
failures = cvc._check_changelog_links("1.5.0")
if any("1.4.13" in f and "1.5.0" in f for f in failures):
    ok("a '[1.5.0]:' link comparing v1.5.0...v1.5.0 (empty range) is reported")
else:
    bad(f"empty-comparison version link was not reported: {failures!r}")

# --- 6. correct source passes (explicit, beyond case 1) ---------------------
cvc.CHANGELOG = _write(CORRECT)
failures = cvc._check_changelog_links("1.5.0")
if failures == []:
    ok("a '[1.5.0]:' link comparing from the structurally-correct tag passes")
else:
    bad(f"correct-source block reported failures: {failures!r}")

# --- 7. the first release in the file is accepted or clearly reported -------
cvc.CHANGELOG = _write(FIRST_RELEASE_OK)
failures = cvc._check_changelog_links("1.2.0")
if failures == []:
    ok("the initial release's 'releases/tag/vX.Y.Z' link passes with no PREV section")
else:
    bad(f"initial-release link wrongly reported failures: {failures!r}")

cvc.CHANGELOG = _write(FIRST_RELEASE_BAD)
failures = cvc._check_changelog_links("1.2.0")
if any("first" in f.lower() for f in failures):
    ok("an invalid link on the initial release gives a clear message")
else:
    bad(f"invalid initial-release link was not clearly reported: {failures!r}")

# --- 8. bump writes both lines ------------------------------------------------
# The realistic pre-bump state: the maintainer has already renamed the top
# section from Unreleased to 1.5.0 (with a fresh empty Unreleased above it),
# but the link block at the bottom is still the pre-bump one.
PRE_BUMP = (
    "## [Unreleased]\n\n## [1.5.0] - 2026-07-26\n\n### Added\n- a thing\n\n"
    "## [1.4.13]\n- old\n\n"
    f"[Unreleased]: {REPO}/compare/v1.4.13...HEAD\n"
    f"[1.4.13]: {REPO}/compare/v1.4.12...v1.4.13\n"
)
bump_path = _write(PRE_BUMP)
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

# --- 9. bump is idempotent ----------------------------------------------------
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

# --- 10. partial state: [Unreleased] already repointed, [X.Y.Z]: missing ----
# Review finding: the old idempotency check returned early as soon as
# [Unreleased] pointed at the target, leaving this state unrepaired.
partial_missing_path = _write(
    "## [Unreleased]\n\n## [1.5.0] - 2026-07-26\n\n### Added\n- a thing\n\n"
    "## [1.4.13]\n- old\n\n"
    f"[Unreleased]: {REPO}/compare/v1.5.0...HEAD\n"
    f"[1.4.13]: {REPO}/compare/v1.4.12...v1.4.13\n"
)
bv._bump_changelog_links(partial_missing_path, "1.5.0")
repaired = partial_missing_path.read_text()
if expected_version in repaired:
    ok(
        "bump adds the missing [1.5.0] link even though [Unreleased] already pointed at it"
    )
else:
    bad(f"bump left a missing [1.5.0] link unrepaired. Got:\n{repaired}")
if repaired.count(f"[Unreleased]: {REPO}/compare/") == 1:
    ok("bump does not duplicate the [Unreleased] line while repairing")
else:
    bad(f"bump duplicated or dropped the [Unreleased] line. Got:\n{repaired}")

# --- 11. partial state: [Unreleased] already repointed, [X.Y.Z]: wrong -----
partial_wrong_path = _write(
    "## [Unreleased]\n\n## [1.5.0] - 2026-07-26\n\n### Added\n- a thing\n\n"
    "## [1.4.13]\n- old\n\n"
    f"[Unreleased]: {REPO}/compare/v1.5.0...HEAD\n"
    f"[1.5.0]: {REPO}/compare/v1.0.0...v1.5.0\n"
    f"[1.4.13]: {REPO}/compare/v1.4.12...v1.4.13\n"
)
bv._bump_changelog_links(partial_wrong_path, "1.5.0")
repaired = partial_wrong_path.read_text()
if expected_version in repaired and f"{REPO}/compare/v1.0.0...v1.5.0" not in repaired:
    ok(
        "bump corrects a wrong [1.5.0] link even though [Unreleased] already pointed at it"
    )
else:
    bad(f"bump left a wrong [1.5.0] link unrepaired. Got:\n{repaired}")
if repaired.count("[1.5.0]: ") == 1:
    ok("bump does not duplicate the [1.5.0] line while repairing it")
else:
    bad(f"bump duplicated the [1.5.0] line. Got:\n{repaired}")

# --- 12. a true no-op writes nothing -----------------------------------------
noop_path = _write(CORRECT)
before_noop = noop_path.read_text()
bv._bump_changelog_links(noop_path, "1.5.0")
after_noop = noop_path.read_text()
if before_noop == after_noop:
    ok("bump against an already-correct block changes nothing")
else:
    bad(f"bump changed an already-correct block. Got:\n{after_noop}")

# --- 13. bump against a CHANGELOG with no link block gives a clear error ----
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

# --- 14. bump against a CHANGELOG with no section for the target version ---
no_target_header_path = _write(
    "## [Unreleased]\n\n## [1.4.13]\n- old\n\n"
    f"[Unreleased]: {REPO}/compare/v1.4.13...HEAD\n"
    f"[1.4.13]: {REPO}/compare/v1.4.12...v1.4.13\n"
)
try:
    bv._bump_changelog_links(no_target_header_path, "1.5.0")
except SystemExit as exc:
    if isinstance(exc.code, str) and exc.code.startswith("ERROR:"):
        ok("bump against a CHANGELOG with no '## [1.5.0]' section gives a clear error")
    else:
        bad(f"bump's missing-section error path was unclear: {exc.code!r}")
else:
    bad(
        "bump against a CHANGELOG with no target-version section did not raise SystemExit"
    )

# --- 15. the bump writes the source from the same rule the gate checks -----
# Integration: feed bump's own output back into the gate and confirm it
# agrees, so the two can't silently drift apart from each other.
agreement_path = _write(PRE_BUMP)
bv._bump_changelog_links(agreement_path, "1.5.0")
cvc.CHANGELOG = agreement_path
failures = cvc._check_changelog_links("1.5.0")
if failures == []:
    ok("check_version_coherence.py accepts exactly what bump_version.py writes")
else:
    bad(f"the gate rejected bump's own output: {failures!r}")

# --- 16. duplicate labels: stale first, correct duplicate second -----------
# The exact bug named in review: a first (stale) [Unreleased] followed by a
# correct duplicate. A dict()-of-findall keeps the LAST value (correct), so
# it would wrongly pass; Markdown renders the FIRST (stale) one.
DUPLICATE_STALE_FIRST = (
    "## [Unreleased]\n\n## [1.5.0] - 2026-07-26\n\n### Added\n- a thing\n\n"
    "## [1.4.13]\n- old\n\n"
    f"[Unreleased]: {REPO}/compare/v1.4.13...HEAD\n"
    f"[1.5.0]: {REPO}/compare/v1.4.13...v1.5.0\n"
    f"[Unreleased]: {REPO}/compare/v1.5.0...HEAD\n"
    f"[1.4.13]: {REPO}/compare/v1.4.12...v1.4.13\n"
)
cvc.CHANGELOG = _write(DUPLICATE_STALE_FIRST)
failures = cvc._check_changelog_links("1.5.0")
dup_failures = [f for f in failures if "more than once" in f]
if len(dup_failures) == 1 and "Unreleased" in dup_failures[0]:
    lines_in_file = DUPLICATE_STALE_FIRST.splitlines()
    first_line = next(
        i
        for i, line in enumerate(lines_in_file, start=1)
        if line.startswith("[Unreleased]:")
    )
    second_line = next(
        i
        for i, line in enumerate(lines_in_file, start=1)
        if line.startswith("[Unreleased]:") and i != first_line
    )
    if str(first_line) in dup_failures[0] and str(second_line) in dup_failures[0]:
        ok("a duplicate '[Unreleased]:' label is reported naming both line numbers")
    else:
        bad(
            f"duplicate message missing line numbers {first_line}/{second_line}: {dup_failures[0]!r}"
        )
else:
    bad(f"duplicate '[Unreleased]:' label was not reported: {failures!r}")
# The resolved (first, stale) value must also fail the normal staleness
# check - this is the actual bug: the gate must not silently prefer the
# correct duplicate over the stale first definition.
if any("compares from" in f and "v1.4.13" in f for f in failures):
    ok(
        "the FIRST (stale) definition is what the staleness check evaluates, not the duplicate"
    )
else:
    bad(f"the gate used the duplicate's value instead of the first one: {failures!r}")

# --- 17. duplicate labels: correct first, stale duplicate second -----------
# Even when the first (winning) definition is correct, the duplicate itself
# is still a CHANGELOG bug and must be reported.
DUPLICATE_CORRECT_FIRST = (
    "## [Unreleased]\n\n## [1.5.0] - 2026-07-26\n\n### Added\n- a thing\n\n"
    "## [1.4.13]\n- old\n\n"
    f"[Unreleased]: {REPO}/compare/v1.5.0...HEAD\n"
    f"[1.5.0]: {REPO}/compare/v1.4.13...v1.5.0\n"
    f"[Unreleased]: {REPO}/compare/v1.4.13...HEAD\n"
    f"[1.4.13]: {REPO}/compare/v1.4.12...v1.4.13\n"
)
cvc.CHANGELOG = _write(DUPLICATE_CORRECT_FIRST)
failures = cvc._check_changelog_links("1.5.0")
if len(failures) == 1 and "more than once" in failures[0]:
    ok("a duplicate label is reported even when the winning (first) value is correct")
else:
    bad(f"expected exactly 1 duplicate-label failure, got: {failures!r}")

# --- 18. duplicate labels are compared case-insensitively -------------------
DUPLICATE_CASE_INSENSITIVE = (
    "## [Unreleased]\n\n## [1.5.0] - 2026-07-26\n\n### Added\n- a thing\n\n"
    "## [1.4.13]\n- old\n\n"
    f"[Unreleased]: {REPO}/compare/v1.5.0...HEAD\n"
    f"[1.5.0]: {REPO}/compare/v1.4.13...v1.5.0\n"
    f"[UNRELEASED]: {REPO}/compare/v1.5.0...HEAD\n"
    f"[1.4.13]: {REPO}/compare/v1.4.12...v1.4.13\n"
)
cvc.CHANGELOG = _write(DUPLICATE_CASE_INSENSITIVE)
failures = cvc._check_changelog_links("1.5.0")
if any("more than once" in f for f in failures):
    ok("'[Unreleased]:' and '[UNRELEASED]:' are detected as the same duplicated label")
else:
    bad(f"a case-only duplicate label was not detected: {failures!r}")

# --- 19. bump refuses to run on a duplicate label ---------------------------
for name, fixture in (
    ("stale-first", DUPLICATE_STALE_FIRST),
    ("correct-first", DUPLICATE_CORRECT_FIRST),
    ("case-insensitive", DUPLICATE_CASE_INSENSITIVE),
):
    dup_path = _write(fixture)
    try:
        bv._bump_changelog_links(dup_path, "1.5.0")
    except SystemExit as exc:
        if (
            isinstance(exc.code, str)
            and exc.code.startswith("ERROR:")
            and "once" in exc.code
        ):
            ok(f"bump refuses to run on a duplicate label ({name})")
        else:
            bad(f"bump's duplicate-label error path was unclear ({name}): {exc.code!r}")
    else:
        bad(f"bump did not refuse to run on a duplicate label ({name})")

# --- 20. atomicity: a missing CHANGELOG section aborts main() with nothing --
# --- touched, not just the CHANGELOG (review finding: the CHANGELOG edit
# --- used to run LAST, after every manifest/lockfile write had already
# --- happened).
bv_main_module = bv  # alias for readability below


def _write_full_repo_fixture(
    root: pathlib.Path, version: str
) -> dict[str, pathlib.Path]:
    """Minimal, valid content for every non-CHANGELOG site main() rewrites."""

    def write(rel: str, content: str) -> pathlib.Path:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    paths: dict[str, pathlib.Path] = {}
    paths["BACKEND_PYPROJECT"] = write(
        "backend/pyproject.toml", f'[project]\nname = "x"\nversion = "{version}"\n'
    )
    paths["MAIN_PY"] = write(
        "backend/app/api/main.py", f'_FALLBACK_APP_VERSION = "{version}"\n'
    )
    paths["OPENAPI_PATH"] = write(
        "backend/openapi.json", json.dumps({"info": {"version": version}}) + "\n"
    )
    paths["FRONTEND_PACKAGE"] = write(
        "frontend/package.json",
        json.dumps({"name": "frontend", "version": version}) + "\n",
    )
    paths["ROOT_PACKAGE"] = write(
        "package.json",
        json.dumps({"name": "root", "version": version, "private": True}) + "\n",
    )
    paths["CLI_PYPROJECT"] = write(
        "cli/pyproject.toml", f'[project]\nname = "cli"\nversion = "{version}"\n'
    )
    paths["MCP_PYPROJECT"] = write(
        "mcp/pyproject.toml", f'[project]\nname = "mcp"\nversion = "{version}"\n'
    )
    paths["MCP_SERVER_JSON"] = write(
        "mcp/server.json",
        json.dumps(
            {
                "version": version,
                "packages": [{"identifier": "geolens-mcp", "version": version}],
            }
        )
        + "\n",
    )
    paths["PY_SDK_PYPROJECT"] = write(
        "sdks/python/pyproject.toml",
        f'[project]\nname = "sdk"\nversion = "{version}"\n',
    )
    paths["PY_SDK_GEN_CONFIG"] = write(
        "sdks/python/.openapi-python-client.yaml",
        f"package_version_override: {version}\n",
    )
    paths["TS_SDK_PACKAGE"] = write(
        "sdks/typescript/package.json",
        json.dumps({"name": "ts-sdk", "version": version}) + "\n",
    )
    paths["DOCS_CONTRACT"] = write(
        "docs-contract.json",
        json.dumps({"version": version, "_comment": "x"}, indent=2) + "\n",
    )
    paths["BACKEND_UV_LOCK"] = write(
        "backend/uv.lock",
        f'[[package]]\nname = "geolens-backend"\nversion = "{version}"\nsource = {{ editable = "." }}\n',
    )
    paths["MCP_UV_LOCK"] = write(
        "mcp/uv.lock",
        (
            f'[[package]]\nname = "geolens-mcp"\nversion = "{version}"\n'
            f'source = {{ editable = "." }}\n\n'
            f'[[package]]\nname = "geolens"\nversion = "{version}"\n'
            f'source = {{ editable = "../sdks/python" }}\n'
        ),
    )
    lock_json = (
        "{\n"
        '  "name": "x",\n'
        f'  "version": "{version}",\n'
        '  "lockfileVersion": 3,\n'
        '  "packages": {\n'
        '    "": {\n'
        '      "name": "x",\n'
        f'      "version": "{version}"\n'
        "    }\n"
        "  }\n"
        "}\n"
    )
    paths["ROOT_PACKAGE_LOCK"] = write("package-lock.json", lock_json)
    paths["FRONTEND_PACKAGE_LOCK"] = write("frontend/package-lock.json", lock_json)
    paths["TS_PACKAGE_LOCK"] = write("sdks/typescript/package-lock.json", lock_json)
    return paths


def _patch_bv_sites(root: pathlib.Path, changelog_path: pathlib.Path) -> None:
    bv_main_module.REPO_ROOT = root
    bv_main_module.BACKEND_PYPROJECT = root / "backend" / "pyproject.toml"
    bv_main_module.MAIN_PY = root / "backend" / "app" / "api" / "main.py"
    bv_main_module.OPENAPI_PATH = root / "backend" / "openapi.json"
    bv_main_module.FRONTEND_PACKAGE = root / "frontend" / "package.json"
    bv_main_module.ROOT_PACKAGE = root / "package.json"
    bv_main_module.CLI_PYPROJECT = root / "cli" / "pyproject.toml"
    bv_main_module.MCP_PYPROJECT = root / "mcp" / "pyproject.toml"
    bv_main_module.MCP_SERVER_JSON = root / "mcp" / "server.json"
    bv_main_module.PY_SDK_PYPROJECT = root / "sdks" / "python" / "pyproject.toml"
    bv_main_module.PY_SDK_GEN_CONFIG = (
        root / "sdks" / "python" / ".openapi-python-client.yaml"
    )
    bv_main_module.TS_SDK_PACKAGE = root / "sdks" / "typescript" / "package.json"
    bv_main_module.DOCS_CONTRACT = root / "docs-contract.json"
    bv_main_module.UV_LOCKS = (
        (root / "backend" / "uv.lock", ("geolens-backend",)),
        (root / "mcp" / "uv.lock", ("geolens-mcp", "geolens")),
    )
    bv_main_module.PACKAGE_LOCKS = (
        root / "package-lock.json",
        root / "frontend" / "package-lock.json",
        root / "sdks" / "typescript" / "package-lock.json",
    )
    bv_main_module.CHANGELOG = changelog_path


scratch_root = pathlib.Path(tempfile.mkdtemp())
scratch_changelog = scratch_root / "CHANGELOG.md"
# No '## [1.5.0]' section at all - main() must abort before writing anything.
scratch_changelog.write_text(
    "## [Unreleased]\n\n## [1.4.13]\n- old\n\n"
    f"[Unreleased]: {REPO}/compare/v1.4.13...HEAD\n"
    f"[1.4.13]: {REPO}/compare/v1.4.12...v1.4.13\n"
)
fixture_paths = _write_full_repo_fixture(scratch_root, "1.4.13")
_patch_bv_sites(scratch_root, scratch_changelog)

all_paths = list(fixture_paths.values()) + [scratch_changelog]
before_snapshot = {p: p.read_bytes() for p in all_paths}

try:
    bv_main_module.main(["1.5.0"])
except SystemExit:
    pass
else:
    bad("main() did not abort for a CHANGELOG missing the target version's section")

after_snapshot = {p: p.read_bytes() for p in all_paths}
if before_snapshot == after_snapshot:
    ok("a missing CHANGELOG section aborts main() with the scratch tree byte-identical")
else:
    changed = [str(p) for p in all_paths if before_snapshot[p] != after_snapshot[p]]
    bad(f"main() modified sites despite the precondition failure: {changed}")

# Sanity check the fixture itself: a VALID CHANGELOG must let main() succeed
# and actually rewrite every site, so the byte-identical result above is
# proof of the abort, not an artifact of a fixture that never gets touched.
scratch_changelog.write_text(
    "## [Unreleased]\n\n## [1.5.0] - 2026-07-26\n\n### Added\n- a thing\n\n"
    "## [1.4.13]\n- old\n\n"
    f"[Unreleased]: {REPO}/compare/v1.4.13...HEAD\n"
    f"[1.4.13]: {REPO}/compare/v1.4.12...v1.4.13\n"
)
try:
    rc = bv_main_module.main(["1.5.0"])
except SystemExit as exc:
    bad(f"main() raised SystemExit on a valid fixture: {exc.code!r}")
else:
    if rc == 0:
        ok("the same fixture succeeds and returns 0 once the section exists")
    else:
        bad(f"main() returned {rc!r} instead of 0 on a valid fixture")
after_success_snapshot = {p: p.read_bytes() for p in all_paths}
if all(before_snapshot[p] != after_success_snapshot[p] for p in fixture_paths.values()):
    ok("a successful run does rewrite every manifest and lockfile site")
else:
    unchanged = [
        str(p)
        for p in fixture_paths.values()
        if before_snapshot[p] == after_success_snapshot[p]
    ]
    bad(f"a successful run left some sites unchanged: {unchanged}")

print(f"1..{PASS + FAIL}")
print(f"# {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)

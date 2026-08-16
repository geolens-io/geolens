#!/usr/bin/env python3
"""Regression test for the CHANGELOG half of the version-coherence gate.

The gate is only worth anything if it answers the question
`.github/workflows/release.yml` actually asks. That workflow extracts the
release body with awk:

    awk "/^## \\[${V}\\]/{found=1; next} /^## \\[/{if(found) exit} found{print}"

and falls back to a filtered `git log` — which drops every `docs(`/`chore(`
subject — whenever the result is empty. So the two extractions must agree, and
"header exists" is not the same question as "section has content".

Pure stdlib, no repo state: each case builds its own CHANGELOG in a tmpdir.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import subprocess
import sys
import tempfile

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "scripts" / "check_version_coherence.py"
RELEASE_YML = REPO_ROOT / ".github" / "workflows" / "release.yml"

_spec = importlib.util.spec_from_file_location("cvc", GATE)
cvc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cvc)

PASS = FAIL = 0


def ok(msg: str) -> None:
    global PASS
    PASS += 1
    print(f"ok {PASS + FAIL} - {msg}")


def bad(msg: str) -> None:
    global FAIL
    FAIL += 1
    print(f"not ok {PASS + FAIL} - {msg}")


# The awk program release.yml runs, read back from the workflow so this test
# breaks if the workflow's extraction is edited without updating the gate.
def _release_yml_awk() -> str:
    text = RELEASE_YML.read_text()
    m = re.search(r'NOTES=\$\(awk "(.+?)" CHANGELOG\.md\)', text)
    if not m:
        sys.exit("ERROR: could not find the NOTES awk program in release.yml")
    # Taken verbatim. Inside shell double quotes a backslash is only special
    # before $ ` " \ or newline, so the `\[` / `\]` in the workflow reach awk
    # unchanged as ERE-escaped brackets — unescaping them here would build a
    # different (and invalid) program than the one that actually runs.
    return m.group(1)


AWK_TEMPLATE = _release_yml_awk()

CASES = {
    "normal section": "## [Unreleased]\n\n## [1.5.0] - 2026-07-26\n\n### Added\n- a thing\n\n## [1.4.13]\n- old\n",
    "empty section": "## [Unreleased]\n\n## [1.5.0] - 2026-07-26\n\n## [1.4.13]\n- old\n",
    "whitespace-only section": "## [1.5.0]\n   \n\t\n\n## [1.4.13]\n- old\n",
    "missing section": "## [Unreleased]\n\n## [1.4.13]\n- old\n",
    "last section in file": "## [Unreleased]\n\n## [1.5.0]\n- tail content\n",
    "section followed by link refs": "## [1.5.0]\n- a\n\n[1.5.0]: https://x/compare/v1.4.13...v1.5.0\n",
    "subsection headers inside": "## [1.5.0]\n### Added\n- a\n## [1.4.0]\n- b\n",
}


def awk_extract(changelog: pathlib.Path, version: str) -> str:
    prog = AWK_TEMPLATE.replace("${CHANGELOG_VERSION}", version)
    out = subprocess.run(
        ["awk", prog, str(changelog)], capture_output=True, text=True, check=False
    ).stdout
    # release.yml captures with $(...), which strips trailing newlines.
    return out.rstrip("\n")


# --- 1. the gate's extraction must match release.yml's, case for case --------
for name, text in CASES.items():
    d = pathlib.Path(tempfile.mkdtemp())
    f = d / "CHANGELOG.md"
    f.write_text(text)
    cvc.CHANGELOG = f

    from_awk = awk_extract(f, "1.5.0")
    section = cvc._changelog_section("1.5.0")
    from_gate = "" if section is None else section.rstrip("\n")

    if from_awk == from_gate:
        ok(f"extraction matches release.yml awk: {name}")
    else:
        bad(f"extraction differs ({name}): awk={from_awk!r} gate={from_gate!r}")

    # The gate must reject exactly the inputs that send release.yml to its
    # git-log fallback. fix(#715 review): `$(...)` strips trailing newlines but
    # KEEPS spaces and tabs, so a bare `[ -z "$NOTES" ]` was false for a
    # whitespace-only section and published blank notes — a verdict the gate
    # did not share. release.yml now strips whitespace before the test, which
    # is what makes .strip() the right model here rather than a convenient one.
    awk_falls_back = from_awk.strip() == ""
    gate_rejects = section is None or not section.strip()
    if awk_falls_back == gate_rejects:
        ok(f"gate verdict tracks the release.yml fallback: {name}")
    else:
        bad(
            f"verdict mismatch ({name}): release.yml falls back={awk_falls_back}, "
            f"gate rejects={gate_rejects}"
        )

# --- 2. a prerelease tag must resolve to its GA section ----------------------
# bump_version.py's SEMVER_RE only accepts plain X.Y.Z, so `## [1.5.0-rc.1]`
# can never exist; release.yml has to strip the suffix or every RC publishes
# the git-log fallback.
if not re.search(
    r'SEMVER_RE = re\.compile\(r"\^\\d\+\\\.\\d\+\\\.\\d\+\$"\)',
    (REPO_ROOT / "scripts" / "bump_version.py").read_text(),
):
    bad("bump_version.py's SEMVER_RE changed — recheck the prerelease assumption")
else:
    ok("bump_version.py still refuses prerelease suffixes (no RC changelog header)")

release_text = RELEASE_YML.read_text()
# The emptiness test itself, not just the extraction: a plain `[ -z "$NOTES" ]`
# disagrees with this gate on whitespace-only sections.
if """[ -z "$(printf '%s' "$NOTES" | tr -d '[:space:]')" ]""" in release_text:
    ok("release.yml strips whitespace before deciding the notes are empty")
else:
    bad("release.yml no longer whitespace-strips before its emptiness test")

if 'CHANGELOG_VERSION="${VERSION%%-*}"' in release_text:
    ok("release.yml strips the prerelease suffix before the CHANGELOG lookup")
else:
    bad("release.yml no longer normalizes prerelease tags to their GA section")

d = pathlib.Path(tempfile.mkdtemp())
f = d / "CHANGELOG.md"
f.write_text("## [Unreleased]\n\n## [1.5.0] - 2026-07-26\n\n### Added\n- a thing\n")
for tag in ("v1.5.0", "v1.5.0-rc.1", "v1.5.0-beta.2"):
    version = tag.lstrip("v")
    changelog_version = version.split("-", 1)[0]  # ${VERSION%%-*}
    if awk_extract(f, changelog_version).strip():
        ok(f"{tag} resolves to real release notes, not the git-log fallback")
    else:
        bad(f"{tag} still falls back to the git log")

# --- 4. the fallback must announce itself (#1530) ---------------------------
# Three separate occasions had the fallback fire when it should not have: every
# prerelease tag (#715), a whitespace-only section (#715 review), and a
# CHANGELOG edit that deleted the `## [1.13.1]` header (#1518). Each was fixed
# by sharpening the matching. The residual defect is that a fallback release is
# indistinguishable from a curated one once published, so it keeps being found
# by accident rather than reported. These assertions pin the announcement, not
# the matching.
_fallback = release_text.split("# Fallback: generate from git log", 1)
if len(_fallback) != 2:
    bad("release.yml no longer has the git-log fallback this test describes")
else:
    # Scope to the fallback branch: a warning elsewhere in the file would
    # satisfy a whole-file search while the fallback stayed silent.
    # Anchor the terminator to a line of its own — a bare "fi" substring also
    # matches inside "fix(#NNNN)", which truncated the branch before the very
    # lines these cases check and made them fail against a correct workflow.
    _end = re.search(r"^\s*fi\s*$", _fallback[1], re.MULTILINE)
    branch = _fallback[1][: _end.start()] if _end else _fallback[1]

    if "::warning" in branch:
        ok("the git-log fallback emits a ::warning annotation")
    else:
        bad("the git-log fallback is silent — no ::warning in its branch")

    if "GITHUB_STEP_SUMMARY" in branch:
        ok("the git-log fallback writes to the job summary")
    else:
        bad("the git-log fallback does not report in the job summary")

    # The published body has to carry it too. A warning only reaches whoever
    # opens the workflow log; the marker reaches whoever reads the release.
    if "NOTES=" in branch and "commit subjects" in branch:
        ok("the git-log fallback marks the published notes as auto-generated")
    else:
        bad("the published notes carry no marker that they are auto-generated")

print(f"1..{PASS + FAIL}")
print(f"# {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)

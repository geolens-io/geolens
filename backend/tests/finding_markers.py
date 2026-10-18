"""Detector for unscoped finding markers and provenance prefixes in ``backend/app``
comments and docstrings.

Stdlib only and importable without ``app.core.config``, so the pre-commit
hook runs ``main()`` directly. AGENTS.md > Contracts and Comments.
"""

from __future__ import annotations

import ast
import io
import json
import re
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

# A coded finding id (`SEC-002`, `T-1214-17`, `PERF-N5`, `IA-P0-01`). The
# numeric tail excludes `AUTO-GENERATED` and a `^[A-Z]+$` regex; the uppercase
# segments exclude GHSA ids and `X-Esri-Authorization`.
MARKER_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-[A-Z]?[0-9]+[A-Z0-9]*\b")

# An agent or tool name used as a comment tag. No general shape covers this
# half, so it is a denylist and says so.
AGENT_TAG_RE = re.compile(r"(?i)\b(ponytail)\s*:")

# Internal-cadence and planning-note references, which MARKER_RE's hyphenated
# shape cannot see. Two digits minimum, so a local "Phase 1: validate" step
# label stays prose; a lettered lane or wave is a planning label either way.
CADENCE_RE = re.compile(
    r"\b(?:Phase|Pitfall|Milestone|Wave|Sprint|Lane)\s+#?\d{2,}\b"
    r"|\b(?:Lane|Wave)\s+[A-H]\b"
)

# A private planning note by name: a quick-task id, a numbered
# ``NNN-NN-NAME.md`` note, a ``*-PLAN.md`` or ``RESEARCH.md`` file, or a
# ``*-FOLLOWUP`` note. Published docs (AGENTS.md, ADR-002.md) match none.
PLANNING_NOTE_RE = re.compile(
    r"\bquick-\d{6}\b|\b\d{2,4}-\d{2,4}-[A-Z][A-Z0-9-]*\.md\b"
    r"|\b[\w-]*(?:PLAN|RESEARCH)\.md\b|\b[A-Z0-9][\w-]*-FOLLOWUP\b"
)

# A commit-style provenance prefix (`fix(#1234):`, `feat(#88 review)`). It
# carries its own issue number, so the anchor rule below never applies.
PROVENANCE_RE = re.compile(r"\b(?:fix|feat|refactor|perf|chore|test)\(#\d+[^)\n]*\)")

# What makes a marker scoped: an issue or PR number a reader can look up.
# Two digits minimum, so `Pitfall #5` and a `#1f2937` colour do not count.
ANCHOR_RE = re.compile(r"#\d{2,6}\b|\bGH-\d{2,6}\b|\bCVE-\d{4}-\d{4,7}\b")

# Tokens carrying the marker SHAPE that name a published standard, so they
# resolve for any reader. A literal list, not a prefix family: `ISO-8601` is
# vocabulary and `ISO-01` is a finding id, and no `ISO-` rule separates them.
TECHNICAL_VOCABULARY = frozenset(
    {
        # Encodings, hashes, curves, coordinate reference systems.
        "AES-128",
        "AES-256",
        "EPSG-3857",
        "EPSG-4326",
        "IEEE-754",
        "ISO-3166-1",
        "ISO-639-1",
        "ISO-8601",
        "NAMEDATALEN-1",
        "P-256",
        "P-384",
        "SHA-1",
        "SHA-256",
        "SHA-384",
        "SHA-512",
        "UTF-7",
        "UTF-8",
        "UTF-16",
        "UTF-32",
        "WGS-84",
        # NIST SP 800-53 control ids, cited in the audit-sink and config-export
        # prose. `AU-5` is the one present; the rest are its immediate family.
        "AC-3",
        "AU-5",
        "AU-9",
        "CM-6",
        "IA-5",
        "SC-8",
        "SI-4",
        # Arithmetic, not an id: "keys 0..N-1", "commit N-1 renames".
        "N-1",
        # A committed, publicly readable design record (.github/ADR-002.md),
        # as resolvable as a CVE id or a GH-NNNN issue.
        "ADR-002",
    }
)


class MarkerScanError(RuntimeError):
    """A source file the detector could not read. Always names the file."""


@dataclass(frozen=True)
class Unit:
    """One run of comment lines, or one docstring, with its first line number."""

    kind: str
    lineno: int
    text: str


@dataclass(frozen=True)
class Hit:
    """A documentation line carrying an unanchored marker or a provenance prefix."""

    module: str
    lineno: int
    kind: str
    markers: tuple[str, ...]

    def describe(self) -> str:
        return f"{self.module}:{self.lineno} ({self.kind}) {', '.join(self.markers)}"


# Legacy references are scoped within three lines. Plain explanations without
# finding tags are preferred; an anchor does not make a tag necessary.
ANCHOR_WINDOW = 2


def _comment_units(source: str, module: str) -> list[Unit]:
    """Group comment tokens into runs of consecutive lines."""
    units: list[Unit] = []
    run: list[tokenize.TokenInfo] = []

    def flush() -> None:
        if run:
            units.append(
                Unit("comment", run[0].start[0], "\n".join(t.string for t in run))
            )
            run.clear()

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError) as exc:
        raise MarkerScanError(f"{module}: could not tokenize: {exc}") from exc
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        if run and token.start[0] != run[-1].start[0] + 1:
            flush()
        run.append(token)
    flush()
    return units


def _docstring_units(source: str, module: str) -> list[Unit]:
    """Every bare string expression statement, docstring or attribute doc."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise MarkerScanError(f"{module}: could not parse: {exc}") from exc
    units: list[Unit] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr):
            continue
        value = node.value
        if isinstance(value, ast.JoinedStr):
            # An f-string statement has no static text to read. No site in
            # app/ has one; report rather than skip if that ever changes.
            raise MarkerScanError(
                f"{module}:{node.lineno}: f-string expression statement is not readable"
            )
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            units.append(Unit("docstring", node.lineno, value.value))
    return units


def iter_units(source: str, module: str) -> list[Unit]:
    """All documentation units in one module, comments and docstrings alike."""
    return _comment_units(source, module) + _docstring_units(source, module)


def markers_in(
    text: str, vocabulary: frozenset[str] = TECHNICAL_VOCABULARY
) -> tuple[str, ...]:
    """Finding markers in one unit, vocabulary removed, sorted and deduped."""
    found = {t for t in MARKER_RE.findall(text) if t not in vocabulary}
    found.update(m.group(1) for m in AGENT_TAG_RE.finditer(text))
    found.update(CADENCE_RE.findall(text))
    found.update(PLANNING_NOTE_RE.findall(text))
    return tuple(sorted(found))


def scan_module(module: str, source: str) -> list[Hit]:
    """Unanchored marker-bearing lines in one module's documentation."""
    hits = []
    for unit in iter_units(source, module):
        lines = unit.text.splitlines()
        anchored = [ANCHOR_RE.search(line) is not None for line in lines]
        for offset, line in enumerate(lines):
            markers = markers_in(line)
            low = max(0, offset - ANCHOR_WINDOW)
            if markers and any(anchored[low : offset + ANCHOR_WINDOW + 1]):
                markers = ()
            found = markers + tuple(PROVENANCE_RE.findall(line))
            if found:
                hits.append(Hit(module, unit.lineno + offset, unit.kind, found))
    return hits


def scan_tree(app_root: Path = APP_ROOT) -> tuple[list[Hit], int, int]:
    """Scan every module under ``app_root``. Returns (hits, modules, units)."""
    hits: list[Hit] = []
    modules = 0
    units = 0
    for path in sorted(app_root.rglob("*.py")):
        module = path.relative_to(app_root).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise MarkerScanError(f"{module}: could not read: {exc}") from exc
        modules += 1
        units += len(iter_units(source, module))
        hits.extend(scan_module(module, source))
    return hits, modules, units


# Floors, so a collapsed glob or a moved APP_ROOT fails loudly instead of
# reporting zero findings and passing (#1552). `main` carries 431 modules and
# 9601 units.
MIN_SCANNED_MODULES = 350
MIN_SCANNED_UNITS = 7000


def check(app_root: Path = APP_ROOT) -> list[str]:
    """Every way the tree violates the gate, as printable lines."""
    hits, modules, units = scan_tree(app_root)
    problems: list[str] = []

    if modules < MIN_SCANNED_MODULES:
        problems.append(
            f"scanned {modules} modules under {app_root}, floor is "
            f"{MIN_SCANNED_MODULES} — the scan is not seeing the tree"
        )
    if units < MIN_SCANNED_UNITS:
        problems.append(
            f"read {units} comment/docstring units, floor is {MIN_SCANNED_UNITS}"
            " — the scan is not seeing the documentation"
        )

    if hits:
        problems.append(
            f"{len(hits)} documentation lines carry unanchored finding markers "
            "or fix(#N)-style provenance prefixes. Remove unnecessary tags and "
            "keep the explanation; provenance belongs in Git and the PR. Anchor "
            "only an essential marker reference, or — if it names a published "
            "standard — add it to TECHNICAL_VOCABULARY:"
        )
        problems.extend(f"    {hit.describe()}" for hit in hits)

    return problems


# Field/Query ``description=``/``summary=`` strings are literals, not
# docstrings, so nothing above sees them, though they reach openapi.json and
# the SDKs (#1946). Only openapi.json is scanned; make sdks-check already
# gates drift between it and the ~900 generated SDK files.
OPENAPI_PATH = Path(__file__).resolve().parents[1] / "openapi.json"

# Keys FastAPI publishes as reader-facing prose, not identifiers.
_OPENAPI_TEXT_KEYS = frozenset({"description", "summary"})

# main carries 4444 description/summary strings; a walk that silently sees
# none of the spec (a moved file, a renamed key) must fail loudly, not pass
# empty.
MIN_OPENAPI_DESCRIPTIONS = 3500

# Published text is held to more than source: a source comment may number
# its own steps ("Phase 1: validate"), but in openapi.json any numbered phase
# or pitfall is a planning reference.
_CADENCE_RE = re.compile(r"\b(?:Phase|Pitfall|Milestone|Wave|Sprint|Lane)\s+#?\d+\b")

# The literal ``CONTEXT.md`` too: published text has no reason to cite a repo
# file, and the private planning notes share that name.
_PLANNING_DOC_RE = re.compile(
    r"\bCONTEXT\.md\b|\b\d{2,4}-\d{2,4}-[A-Z][A-Z0-9-]*\.md\b"
)


def _openapi_markers(line: str) -> tuple[str, ...]:
    """Marker-shaped tokens in one description line: the shared detector's
    hyphenated shape, plus a bare reference it cannot see."""
    found = set(markers_in(line))
    found.update(_CADENCE_RE.findall(line))
    found.update(_PLANNING_DOC_RE.findall(line))
    return tuple(sorted(found))


def _openapi_descriptions(node: object, path: str = "$") -> list[tuple[str, str, str]]:
    """Every description/summary string in a parsed OpenAPI document, with
    its JSON path and which key it came from."""
    found: list[tuple[str, str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}"
            if key in _OPENAPI_TEXT_KEYS and isinstance(value, str):
                found.append((child, key, value))
            else:
                found.extend(_openapi_descriptions(value, child))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_openapi_descriptions(value, f"{path}[{index}]"))
    return found


def scan_openapi(spec: object) -> list[Hit]:
    """Unanchored marker-bearing lines in every ``description``/``summary``
    in ``spec``."""
    hits: list[Hit] = []
    for json_path, key, text in _openapi_descriptions(spec):
        lines = text.splitlines()
        anchored = [ANCHOR_RE.search(line) is not None for line in lines]
        for offset, line in enumerate(lines):
            markers = _openapi_markers(line)
            if not markers:
                continue
            low = max(0, offset - ANCHOR_WINDOW)
            high = offset + ANCHOR_WINDOW + 1
            if any(anchored[low:high]):
                continue
            hits.append(Hit(json_path, offset + 1, f"openapi-{key}", markers))
    return hits


def check_openapi(openapi_path: Path = OPENAPI_PATH) -> list[str]:
    """Every unanchored marker reaching the published OpenAPI surface."""
    try:
        spec = json.loads(openapi_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"could not read {openapi_path}: {exc}"]

    problems: list[str] = []
    description_count = len(_openapi_descriptions(spec))
    if description_count < MIN_OPENAPI_DESCRIPTIONS:
        problems.append(
            f"read {description_count} description/summary strings from"
            f" {openapi_path}, floor is {MIN_OPENAPI_DESCRIPTIONS} — the scan"
            " is not seeing the spec"
        )

    hits = scan_openapi(spec)
    if hits:
        problems.append(
            f"{openapi_path} publishes finding markers with no #issue anchor —"
            " an integrator reading the generated SDK docstring has nothing to"
            " resolve them against. Rewrite the Field/Query description to"
            " state the constraint itself, then run `make sdks`:"
        )
        problems.extend(f"    {hit.describe()}" for hit in hits)

    return problems


def main() -> int:
    """Print every violation and return 1, or return 0 on a clean tree."""
    problems = check() + check_openapi()
    if not problems:
        return 0
    print(
        "FAIL: unscoped finding markers in backend/app comments/docstrings or"
        " backend/openapi.json descriptions"
    )
    for line in problems:
        print(f"  {line}")
    print("  See AGENTS.md > Contracts and Comments.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

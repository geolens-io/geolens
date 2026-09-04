"""Structural guard for the CodeQL alert-suppression pack.

AGENTS.md ("Standing CodeQL policy", decided 2026-08-03) says that if the
validated-identifier ``py/sql-injection`` class fires again on an
ingest-adjacent PR, the repo adopts the alert-suppression query pack instead
of dismissing the alerts by hand a second time. It fired again on
2026-08-11: 12 open alerts, all in the two ingest metadata modules below,
every one at a ``text()`` call whose SQL interpolates a table or schema
identifier that ``_qtable`` in ``app/processing/ingest/metadata_sql.py``
validates against a safe-identifier pattern before it is interpolated.

**THE INVARIANT: no dynamic ``text()`` site in these two modules is
unmarked.** The set of sites is computed from the source, not listed here.
Any ``text(...)`` call whose first argument is not a plain string literal is
a site: an f-string, a name bound to an f-string built earlier, a
concatenation, anything the parser cannot prove constant. Every site must
carry a ``# codeql[py/sql-injection]`` marker on its own line directly above.

That predicate deliberately over-covers. Only 12 of the 16 sites it finds
have ever produced an alert; the other four interpolate ``_qtable`` exactly
the same way and simply have no taint path reaching them today. Shaping the
predicate the other way round, so a site counts only when it matches the
shapes CodeQL flagged in August, turns it into a blocklist: it goes quiet
the first time this class appears in a shape nobody enumerated. Marking a
site that never alerts costs one comment line and suppresses nothing.
Missing one costs another manual dismissal round, which is the thing the
standing policy exists to end.

**The markers alone do nothing.** GitHub code scanning does not honour SARIF
``suppressions[]``: the property is absent from the supported-properties
list in GitHub's SARIF reference, ``github/codeql-action`` carries no
suppression handling, and GitHub staff confirmed the gap on the public
community thread in May 2025. Three moving parts have to line up, so this
module asserts all three rather than the comments alone:

1. the markers, in the two modules (``test_every_dynamic_text_site_...``);
2. the workflow config that makes the CodeQL CLI emit ``suppressions[]``
   for them at all, plus the step that acts on it (``test_codeql_workflow_...``);
3. the repo-local suppression query itself, which must NOT recognise
   ``# noqa`` (``test_suppression_query_does_not_honour_noqa``).

Point 3 is the security-critical one. The stock ``codeql/python-queries``
``AlertSuppression.ql`` treats every ``# noqa`` comment as a **bare** ``lgtm``
annotation covering that whole line, and a bare annotation suppresses every
rule, not one. ``backend/`` carries 332 ``# noqa`` comments. Shipping the
stock query would quietly turn each of those lines into a blanket
auto-dismissal zone for any alert that ever lands there, including
``processing/analysis/tasks.py``, whose raw-SQL line already carries
``# noqa: S608``. The repo-local query is the stock one minus that class, so
only an explicit, reviewed ``codeql[...]`` marker can ever suppress anything.

None of this needs a database or an app import.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

# The two ingest modules the 2026-08-11 alert batch landed in. Both build SQL
# by interpolating identifiers that _qtable/_sql_quote_ident validate first.
GUARDED_MODULES = (
    "backend/app/processing/ingest/metadata_projection.py",
    "backend/app/processing/ingest/metadata_extent.py",
)

CODEQL_WORKFLOW = REPO_ROOT / ".github/workflows/codeql.yml"
SUPPRESSION_PACK_DIR = REPO_ROOT / ".github/codeql/python-suppression"
SUPPRESSION_QUERY = SUPPRESSION_PACK_DIR / "AlertSuppression.ql"

# Matches the marker the CodeQL CLI's alert-suppression query looks for. The
# upstream regex is `(?i)\bcodeql\s*\[[^\]]*\]` found anywhere in the comment
# text, so trailing prose after the bracket is allowed and is what carries the
# per-site justification naming _qtable.
MARKER_RE = re.compile(r"\bcodeql\s*\[\s*py/sql-injection\s*\]", re.IGNORECASE)

# Any rule id, for the placement test below. #1708 introduced markers for
# py/path-injection and py/full-ssrf, so a rule-specific pattern would leave
# every future rule's markers unguarded the day they are added.
ANY_MARKER_RE = re.compile(r"\bcodeql\s*\[\s*[^\]]+\]", re.IGNORECASE)


def _dynamic_text_sites(source: str) -> list[int]:
    """Return the 1-based start line of every non-constant ``text()`` argument.

    A ``text("literal")`` call is static SQL and cannot carry an injection.
    Everything else (f-string, name, concatenation, call) is dynamic and
    must be marked. Resolution is deliberately not attempted: an argument this
    function cannot prove is a plain string literal counts as a site.
    """
    sites: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and node.args):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name != "text":
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            continue
        sites.append(arg.lineno)
    return sorted(sites)


@pytest.mark.parametrize("rel_path", GUARDED_MODULES)
def test_every_dynamic_text_site_carries_a_suppression_marker(rel_path: str) -> None:
    """Every dynamic ``text()`` site has a marker on its own line above it.

    "On its own line" is not a style preference. The CodeQL suppression query
    only recognises a ``codeql[...]`` comment when no AST node starts before it
    on that line, and the comment covers the line that follows it. A trailing
    marker on the flagged line itself is silently inert, so the placement is
    asserted rather than assumed.
    """
    path = REPO_ROOT / rel_path
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()

    unmarked: list[str] = []
    for lineno in _dynamic_text_sites(source):
        if lineno < 2:
            unmarked.append(f"{rel_path}:{lineno} (no line above it to mark)")
            continue
        above = lines[lineno - 2]
        if not (above.lstrip().startswith("#") and MARKER_RE.search(above)):
            unmarked.append(f"{rel_path}:{lineno} -> above is {above.strip()!r}")

    assert not unmarked, (
        "Dynamic text() sites without a `# codeql[py/sql-injection]` marker on "
        "their own line directly above:\n  " + "\n  ".join(unmarked) + "\n"
        "Add the marker with its justification, or make the SQL static. See "
        "AGENTS.md > Standing CodeQL policy."
    )


def test_every_codeql_marker_in_backend_app_binds_to_the_line_it_covers() -> None:
    """Every ``# codeql[...]`` marker under ``backend/app/`` is placed where it works.

    The sibling test above enumerates SITES and demands a marker. This one
    enumerates MARKERS and demands they be placed where the query can see
    them, which is the half that covers rules with no site enumeration:
    #1708 added six ``py/path-injection`` markers and one ``py/full-ssrf``
    marker, and there is no equivalent of ``_dynamic_text_sites`` that could
    find those sinks generically.

    A marker is inert unless it sits alone on its line and the statement it
    covers follows immediately. Prose inserted between a marker and its call
    is the exact regression this pins — it reads as a helpful clarification
    and silently reopens the alert, with nothing failing until the alert
    turns up on the default branch's dashboard after the merge.
    """
    misplaced: list[str] = []
    for path in sorted((REPO_ROOT / "backend/app").rglob("*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        rel = path.relative_to(REPO_ROOT)
        for i, line in enumerate(lines):
            if not ANY_MARKER_RE.search(line):
                continue
            if not line.lstrip().startswith("#"):
                misplaced.append(f"{rel}:{i + 1} — trailing marker on a code line")
                continue
            following = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if not following or following.startswith("#"):
                misplaced.append(
                    f"{rel}:{i + 1} — covers {following!r}, not a statement"
                )

    assert not misplaced, (
        "CodeQL markers that do not bind to the line they are meant to "
        "suppress:\n  " + "\n  ".join(misplaced) + "\n"
        "A marker must sit alone on the line directly above its call. See "
        "AGENTS.md > Standing CodeQL policy."
    )


# fix(#1770 round 43): alert #113 (py/full-ssrf, critical). Round 41 moved
# the probe adapters' actual sink -- a `client.stream(` call -- out of each
# adapter (`adapters/ogcapi.py`, `adapters/wfs.py`, `adapters/arcgis.py`,
# `adapters/stac.py`) and into one shared helper, `bounded_probe_read`
# (`platform/probe_bounds.py`). The `# codeql[py/full-ssrf]` marker that used
# to sit directly above the adapter's own call stayed there, one hop away
# from the sink CodeQL's dataflow analysis actually reports at -- inert,
# exactly the trap the placement test above exists for, except that test
# only catches prose wedged BETWEEN a marker and the line it covers, not a
# marker sitting confidently above the WRONG line entirely. The two tests
# below close that: one enumerates the sinks a caller-validated URL reaches
# and demands each carries its own marker (a false negative -- an unmarked
# sink); the other demands no `py/full-ssrf` marker exists anywhere that is
# not directly above a real sink (a false positive -- exactly alert #113's
# shape).
SSRF_MARKER_RE = re.compile(r"\bcodeql\s*\[\s*py/full-ssrf\s*\]", re.IGNORECASE)

# The two modules whose sinks a caller-validated URL is expected to reach
# today: `probe_bounds.py`'s single `bounded_probe_read` (round 41-43, the
# probe adapters' own shared read) and `service_endpoints.py`'s single
# `fetch_document` (#1746, the door's own description read). A genuinely new
# sink gets its own marker and its own entry here, not a marker that merely
# resembles one.
SSRF_SINK_MODULES = (
    "backend/app/platform/probe_bounds.py",
    "backend/app/platform/service_endpoints.py",
)

SINK_CALL_RE = re.compile(
    r"\bclient\.(get|post|put|patch|delete|head|options|request|stream|send)\("
)


def _sink_lines(source: str) -> list[int]:
    """1-based line numbers of every ``client.<verb>(`` sink call."""
    return [
        index + 1
        for index, line in enumerate(source.splitlines())
        if SINK_CALL_RE.search(line)
    ]


@pytest.mark.parametrize("rel_path", SSRF_SINK_MODULES)
def test_every_ssrf_sink_in_the_shared_readers_carries_its_own_marker(
    rel_path: str,
) -> None:
    """Every ``client.<verb>(`` sink in the two shared bounded-read helpers
    carries a ``# codeql[py/full-ssrf]`` marker on the line directly above.

    The sink is asserted to exist first (`assert sinks`) so this cannot pass
    vacuously the way it would if `SINK_CALL_RE` ever stopped matching --
    the absence-claim trap: silence here would otherwise look identical to
    "already covered."
    """
    path = REPO_ROOT / rel_path
    lines = (path).read_text(encoding="utf-8").splitlines()
    sinks = _sink_lines("\n".join(lines))
    assert sinks, f"{rel_path}: no client.<verb>( sink found -- positive control failed"
    missing = [
        line_no
        for line_no in sinks
        if line_no < 2 or not SSRF_MARKER_RE.search(lines[line_no - 2])
    ]
    assert not missing, (
        f"{rel_path}: sink(s) at line(s) {missing} carry no "
        "`# codeql[py/full-ssrf]` marker on the line directly above"
    )


def test_no_full_ssrf_marker_sits_above_a_non_sink_line() -> None:
    """No ``# codeql[py/full-ssrf]`` marker anywhere under ``backend/app``
    covers anything other than a real ``client.<verb>(`` sink.

    Tree-wide rather than scoped to `SSRF_SINK_MODULES`: a marker left
    behind at an OLD call site after the real sink moves elsewhere (alert
    #113's exact shape, at what was `adapters/ogcapi.py:159`) is inert
    there regardless of which module it is in, and this is the check that
    would have caught it before the alert reopened on `main` after merge.
    """
    stray: list[str] = []
    for path in sorted((REPO_ROOT / "backend/app").rglob("*.py")):
        rel = str(path.relative_to(REPO_ROOT))
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not SSRF_MARKER_RE.search(line):
                continue
            following = lines[index + 1] if index + 1 < len(lines) else ""
            if not SINK_CALL_RE.search(following):
                stray.append(f"{rel}:{index + 1}")

    assert not stray, (
        "`# codeql[py/full-ssrf]` marker(s) that do not sit directly above a "
        "`client.<verb>(` sink, so they suppress nothing:\n  " + "\n  ".join(stray)
    )


def _codeql_workflow() -> dict:
    return yaml.safe_load(CODEQL_WORKFLOW.read_text(encoding="utf-8"))


def _codeql_steps() -> list[dict]:
    steps: list[dict] = []
    for job in _codeql_workflow()["jobs"].values():
        steps.extend(job.get("steps", []))
    return steps


def _step_using(steps: list[dict], action: str) -> dict:
    for step in steps:
        if str(step.get("uses", "")).startswith(action):
            return step
    raise AssertionError(f"no step in {CODEQL_WORKFLOW.name} uses {action}")


def test_codeql_workflow_runs_and_acts_on_the_suppression_query() -> None:
    """init must run the local query, and a later step must act on the SARIF.

    Emitting ``suppressions[]`` and honouring it are separate problems, and
    only doing the first is the failure mode that looks like success: the
    markers would sit in the source, the SARIF would carry the suppressions,
    the alerts would stay open, and the next person would dismiss 12 alerts
    by hand while believing the pack was already adopted.
    """
    workflow = _codeql_workflow()
    steps = _codeql_steps()

    # The pack path reaches init through the language matrix, so both halves of
    # that indirection are checked: a matrix entry that names the pack, and an
    # init step that actually forwards it. Asserting only one leaves the other
    # free to drift to a value that resolves to nothing.
    matrix = next(
        job["strategy"]["matrix"]
        for job in workflow["jobs"].values()
        if "strategy" in job
    )
    entries = {entry["language"]: entry for entry in matrix["include"]}
    pack = str(SUPPRESSION_PACK_DIR.relative_to(REPO_ROOT))
    python_queries = str(entries["python"].get("suppression-queries", ""))
    assert pack in python_queries, (
        f"the python matrix entry must point `suppression-queries` at {pack!r}; "
        f"got {python_queries!r}. Without it the CodeQL CLI never runs an "
        "alert-suppression query and the markers are inert."
    )
    assert not entries["javascript-typescript"].get("suppression-queries"), (
        "javascript-typescript must pass an empty `suppression-queries`. No JS "
        "suppression comment has been reviewed, and the action reads a "
        "zero-length input as unset, which is what keeps that analysis stock."
    )

    init = _step_using(steps, "github/codeql-action/init")
    queries = str(init.get("with", {}).get("queries", ""))
    assert "matrix.suppression-queries" in queries, (
        "the Initialize CodeQL step must forward the matrix's "
        f"`suppression-queries` via `queries:`; got {queries!r}"
    )

    analyze = _step_using(steps, "github/codeql-action/analyze")
    assert analyze.get("id"), (
        "the analyze step needs an `id:` so the dismissal step can read its "
        "sarif-id/sarif-output outputs"
    )

    dismiss = _step_using(steps, "advanced-security/dismiss-alerts")
    consumed = " ".join(str(v) for v in dismiss.get("with", {}).values())
    assert f"steps.{analyze['id']}.outputs.sarif-id" in consumed, (
        "the dismissal step must consume the analyze step's sarif-id"
    )
    assert f"steps.{analyze['id']}.outputs.sarif-output" in consumed, (
        "the dismissal step must consume the analyze step's SARIF output path"
    )


def test_suppression_query_does_not_honour_noqa() -> None:
    """The local query must recognise ``codeql[...]`` only, never ``# noqa``.

    This is the reason the query is vendored at all rather than referenced as
    ``codeql/python-queries:AlertSuppression.ql``. See the module docstring.
    """
    assert SUPPRESSION_QUERY.exists(), (
        f"{SUPPRESSION_QUERY.relative_to(REPO_ROOT)} is missing; the "
        "`queries:` input in codeql.yml would fail to resolve"
    )
    query = SUPPRESSION_QUERY.read_text(encoding="utf-8")

    assert "@kind alert-suppression" in query, (
        "the query must declare `@kind alert-suppression` or the CodeQL CLI "
        "treats its results as ordinary alerts instead of suppressions"
    )

    code = "\n".join(
        line for line in query.splitlines() if not line.lstrip().startswith("//")
    )
    assert "noqa" not in code.lower(), (
        "the local suppression query must not recognise `# noqa`. The stock "
        "query maps every noqa to a BARE lgtm annotation covering the whole "
        "line, which suppresses every rule on it. 332 such comments exist "
        "under backend/, and each would become a blanket auto-dismissal zone."
    )


def test_ci_backend_filter_covers_the_codeql_suppression_paths() -> None:
    """A codeql.yml-only PR must still run the suite that asserts against it.

    Same failure this repo fixed in #1088 and #1517: a test reads a file by
    literal path, the paths filter does not list that file, and the only gate
    for a change to it never runs.
    """
    ci = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text())
    filters = yaml.safe_load(
        next(
            step["with"]["filters"]
            for job in ci["jobs"].values()
            for step in job.get("steps", [])
            if isinstance(step.get("with"), dict) and "filters" in step["with"]
        )
    )
    backend = filters["backend"]

    for needed in (".github/workflows/codeql.yml", ".github/codeql/**"):
        assert needed in backend, (
            f"ci.yml's backend paths filter must list {needed!r}: this module "
            "reads it by literal path, so without the entry a change to it "
            "skips the only test that checks it."
        )

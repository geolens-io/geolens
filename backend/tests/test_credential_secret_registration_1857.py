"""Every producer of a registered credential secret registers the right shape.

fix(#1857 item 10). ``register_credential_secret`` feeds the exact-value scrub
that ``scrub_registered_credentials`` runs last over every log line, and what
gets registered decides what gets scrubbed. ``_secret_variants``
(``core/url_redaction.py``) expands a registered HEADER LINE into the bare
token, the basic blob and the basic cleartext, and it recognises a line by the
``": "`` in it. Register the VALUE instead of the line and no expansion
happens, so the raw token travels through every structlog line the process
emits until something else catches it.

That is not hypothetical. The 2026-09-04 audit found exactly it in the worker
(``ogr.py`` registered everything after the ``": "``), and #1844 fixed the one
identifier. Nothing stopped the next producer from doing the same, which is
what this closes: a new call site cannot appear without an entry below, and an
entry says which shape that site registers and why.

WHY THIS IS A CLASSIFICATION AND NOT A SINGLE RULE. "Always register the
builder's result" is wrong, and enforcing it would push a site into
registering a header line that never travels as one. ArcGIS's fallback
transport is a URL query parameter, so its credential has no header form at
all; a fabricated ``Authorization: ...`` line would scrub nothing that appears
in a log, while the bare value it actually sends would go unregistered. Each
site therefore declares its shape and the table asserts it, rather than one
rule pretending the two transports are the same.
"""

import ast
import pathlib

import pytest

APP_ROOT = pathlib.Path(__file__).resolve().parents[1] / "app"

REGISTER_HELPER = "register_credential_secret"
HEADER_LINE_BUILDER = "credential_header_line"

# The argument is a literal call to the header-line builder. Checked
# structurally: this is the shape `_secret_variants` can expand.
BUILDER_CALL = "builder_call"
# The argument is a name the enclosing function received, already holding a
# whole header line. Cannot be proved from the call site, so the entry's
# justification says where the line comes from.
CARRIED_LINE = "carried_line"
# The credential does not travel as a header on this path, so there is no line
# to register and the bare transport value is the correct registration.
QUERY_VALUE = "query_value"

_SHAPES = {BUILDER_CALL, CARRIED_LINE, QUERY_VALUE}

# (module path relative to backend/app, enclosing function) ->
# (exact call count, shape, justification). Asserted EXACT in both directions:
# a new producer fails until it is reviewed and entered here, and an entry
# whose site moved or changed shape fails until it is corrected.
REGISTRATION_POLICY: dict[tuple[str, str], tuple[int, str, str]] = {
    ("core/service_tokens.py", "build_credential_header"): (
        4,
        BUILDER_CALL,
        "the four header methods, one per branch: the ArcGIS Esri header, "
        "bearer, basic and a named API key. Each registers the line it is "
        "about to return, so the registered value is byte-identical to what "
        "goes on the wire",
    ),
    ("processing/ingest/ogr.py", "_sanitize_authorization_token"): (
        1,
        CARRIED_LINE,
        "registers its own parameter, which is a whole header line: the "
        "function's contract is to take a line, validate the token half "
        "against HEADER_TOKEN_CHARSET and hand the same line back. #1844 "
        "changed this from the value after the ': ' to the line, which is the "
        "finding this gate exists to keep from recurring",
    ),
    ("modules/catalog/sources/adapters/arcgis.py", "_query_form_credential"): (
        1,
        QUERY_VALUE,
        "the documented fallback for ArcGIS Server older than 10.5.1, where "
        "the credential travels as a ?token= query parameter and never as a "
        "header. The header form of the same credential is registered by "
        "build_credential_header. Registration here is additionally gated on "
        "the token meeting the header charset and length floor, because a "
        "four-character value registered as a secret rewrites ordinary text "
        "in the same request's logs",
    ),
}


def _app_modules() -> list[tuple[str, ast.Module]]:
    modules = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        rel = path.relative_to(APP_ROOT).as_posix()
        modules.append((rel, ast.parse(path.read_text(encoding="utf-8"))))
    return modules


def _annotate_parents(tree: ast.Module) -> None:
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child._reg_parent = parent  # type: ignore[attr-defined]


def _callee_name(node: ast.Call) -> str | None:
    """The terminal name of a call's callee, plain or dotted."""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _local_names_for(tree: ast.Module, helper: str) -> set[str]:
    """Every name in this module that a call to ``helper`` can be spelled with.

    fix(#1868 audit P2-1): the walk matched the terminal callee name only, so
    ``from ... import register_credential_secret as reg`` followed by
    ``reg(token)`` was collected as nothing at all. Not a violation, not an
    unenumerated site: invisible. That is the same failure direction item 2 of
    this branch exists to close for the argv gate, reintroduced in the gate
    this branch adds, and the ``len(sites) >= 3`` floor does not catch it
    because the three known sites are still found.

    Matched on the IMPORTED name regardless of which module it came from,
    which is the loud direction: a same-named helper somewhere else costs a
    reviewed entry, while narrowing to one source module would let a re-export
    hide a site. The attribute spelling
    (``service_tokens.register_credential_secret(...)``) needs nothing here,
    since the terminal name carries it.

    An alias is COLLECTED rather than refused. The point of the gate is to see
    every site; the entry it then demands is what puts the spelling in front of
    a reviewer, which a blanket refusal would do less usefully by making the
    only remedy "rename it back".
    """
    names = {helper}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == helper and alias.asname:
                    names.add(alias.asname)
    return names


def _enclosing_function(node: ast.AST) -> ast.AST | None:
    current = getattr(node, "_reg_parent", None)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
        current = getattr(current, "_reg_parent", None)
    return None


def _parameter_names(fn: ast.AST) -> set[str]:
    args = getattr(fn, "args", None)
    if args is None:
        return set()
    names = {a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]}
    if args.vararg:
        names.add(args.vararg.arg)
    if args.kwarg:
        names.add(args.kwarg.arg)
    return names


def _observed_shape(
    node: ast.Call, builder_names: set[str] | None = None
) -> tuple[str | None, str]:
    """(shape, description) for one registration call's argument.

    A shape of None is a violation on its own: the argument is neither the
    builder's result nor a plain name, which is what an assembled string, a
    dict lookup or an attribute read looks like. Those are the spellings that
    smuggle a fabricated or partial line past a reader.

    ``builder_names`` is the header-line builder's spellings in the module
    being read, for the same reason the register helper has them: an aliased
    import of the builder would otherwise read as "the result of some call"
    and report, which is the safe direction but the wrong message.
    """
    builder_names = builder_names or {HEADER_LINE_BUILDER}
    if not node.args:
        return None, "called with no positional argument"
    arg = node.args[0]
    if isinstance(arg, ast.Call):
        callee = _callee_name(arg)
        if callee in builder_names:
            return BUILDER_CALL, f"{callee}(...)"
        return None, f"the result of {callee or 'an unresolvable call'}(...)"
    if isinstance(arg, ast.Name):
        return CARRIED_LINE, arg.id
    return None, f"an {type(arg).__name__} expression"


def _collect(
    modules: list[tuple[str, ast.Module]] | None = None,
) -> tuple[dict[tuple[str, str], list[tuple[int, str, str]]], list[str]]:
    """Every registration site, keyed by (module, function), plus hard errors.

    ``modules`` defaults to the whole of ``backend/app``; the fixtures below
    pass their own so a spelling can be measured against the real collector
    rather than against a re-implementation of it.
    """
    sites: dict[tuple[str, str], list[tuple[int, str, str]]] = {}
    errors: list[str] = []
    for rel, tree in modules if modules is not None else _app_modules():
        _annotate_parents(tree)
        register_names = _local_names_for(tree, REGISTER_HELPER)
        builder_names = _local_names_for(tree, HEADER_LINE_BUILDER)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _callee_name(node) not in register_names:
                continue
            fn = _enclosing_function(node)
            fn_name = getattr(fn, "name", "<module>")
            shape, described = _observed_shape(node, builder_names)
            if shape is None:
                errors.append(
                    f"{rel}:{node.lineno} ({fn_name}) registers {described}. "
                    f"Register {HEADER_LINE_BUILDER}(pair) directly, or a "
                    "parameter already holding the whole line. An assembled "
                    "string cannot be read as either at the call site"
                )
                continue
            if shape == CARRIED_LINE and (
                fn is None or described not in _parameter_names(fn)
            ):
                errors.append(
                    f"{rel}:{node.lineno} ({fn_name}) registers the local name "
                    f"{described!r}, which is not a parameter of its function. "
                    "A local can hold anything; a parameter is a contract the "
                    "callers can be read against"
                )
                continue
            sites.setdefault((rel, fn_name), []).append((node.lineno, shape, described))
    return sites, errors


def _policy_violations(
    sites: dict[tuple[str, str], list[tuple[int, str, str]]],
) -> list[str]:
    """Every way the collected sites and REGISTRATION_POLICY can disagree.

    Its own function so the fixtures below can put a synthetic site through the
    same rules the real gate applies, rather than through a paraphrase of them.
    """
    violations: list[str] = []

    for (rel, fn_name), entry in sorted(REGISTRATION_POLICY.items()):
        _count, shape, justification = entry
        if shape not in _SHAPES:
            violations.append(
                f"unknown REGISTRATION_POLICY shape {shape!r} for {rel} ({fn_name})"
            )
        if not justification.strip():
            violations.append(
                f"blank REGISTRATION_POLICY justification for {rel} ({fn_name})"
            )

    for key, found in sorted(sites.items()):
        rel, fn_name = key
        entry = REGISTRATION_POLICY.get(key)
        lines = ",".join(str(lineno) for lineno, _shape, _d in found)
        if entry is None:
            violations.append(
                f"{rel} ({fn_name}) calls {REGISTER_HELPER} at line(s) {lines} "
                "with no REGISTRATION_POLICY entry. Say which shape it "
                "registers and why: the wrong one is scrubbed nowhere and "
                "reads exactly like the right one (#1844, #1857)"
            )
            continue
        expected_count, expected_shape, _why = entry
        if len(found) != expected_count:
            violations.append(
                f"{rel} ({fn_name}) has {len(found)} {REGISTER_HELPER} call(s) "
                f"at line(s) {lines} but REGISTRATION_POLICY expects exactly "
                f"{expected_count} — each one needs its own review"
            )
        for lineno, shape, described in found:
            # fix(#1868 audit P3-5): QUERY_VALUE and CARRIED_LINE are
            # structurally identical at the call site -- both are a plain name
            # -- and the entry is what separates them, which is why the table
            # exists. That is not a reason to check nothing: a QUERY_VALUE site
            # that started registering a fabricated header line would be
            # doing precisely what its own justification argues against, and
            # BUILDER_CALL is distinguishable from a name.
            allowed = (
                {CARRIED_LINE, QUERY_VALUE}
                if expected_shape == QUERY_VALUE
                else {expected_shape}
            )
            if shape not in allowed:
                violations.append(
                    f"{rel}:{lineno} ({fn_name}) registers {described}, which "
                    f"is {shape}, but REGISTRATION_POLICY says {expected_shape}"
                )

    for key in sorted(set(REGISTRATION_POLICY) - set(sites)):
        rel, fn_name = key
        violations.append(
            f"stale REGISTRATION_POLICY entry for {rel} ({fn_name}) — no "
            f"{REGISTER_HELPER} call there; remove the entry"
        )

    return violations


@pytest.mark.architecture
def test_every_credential_registration_is_enumerated_and_shaped():
    """The gate #1844's finding needed and did not have.

    Registering the value rather than the line is invisible at the call site:
    both are one identifier, both read as "the credential", and only one of
    them expands. So the check is on the SHAPE, and on the site existing in a
    table somebody reviewed.
    """
    sites, violations = _collect()
    violations += _policy_violations(sites)

    assert not violations, "\n".join(violations)

    assert len(sites) >= 3, (
        f"only {len(sites)} registration site(s) found; the codebase has at "
        "least 3. The walk has gone blind, fix it before trusting this gate"
    )


# fix(#1868 audit P2-1): the spelling the walk could not read. Written as
# source rather than as a file in app/, because a real one would be a real
# unenumerated producer.
_ALIASED_REGISTRATION = """
from app.core.service_tokens import register_credential_secret as reg


def new_producer(token):
    reg(token)
"""

_ALIASED_BUILDER = """
from app.core.service_tokens import credential_header_line as line
from app.core.service_tokens import register_credential_secret


def new_producer(pair):
    register_credential_secret(line(pair))
"""


@pytest.mark.architecture
def test_an_aliased_import_of_the_helper_is_still_collected():
    """A gate that goes quiet on a spelling it cannot read fails the wrong way.

    Matching the terminal callee name alone collected NOTHING for an aliased
    import: not a violation, not an unenumerated site, invisible. The site
    floor does not help either, because the three known sites are still found.
    That is the same failure direction item 2 of this branch closes for the
    argv gate, and it was reintroduced here.

    The site must now surface as unenumerated, which is the answer that gets a
    new producer reviewed.
    """
    modules = [
        ("processing/ingest/_alias_fixture.py", ast.parse(_ALIASED_REGISTRATION))
    ]

    sites, errors = _collect(modules)

    assert ("processing/ingest/_alias_fixture.py", "new_producer") in sites, (
        f"the aliased call was not collected at all: sites={sites} errors={errors}"
    )
    # And it reaches the unenumerated-producer violation, not just the walk.
    violations = _policy_violations(sites)
    assert any("no REGISTRATION_POLICY entry" in v for v in violations), violations


@pytest.mark.architecture
def test_an_aliased_import_of_the_builder_still_reads_as_the_builder():
    """The other half of the same blindness, in the safe direction.

    An aliased builder used to read as "the result of some call" and report,
    which refuses correct code with a message about the wrong thing. Resolving
    both names through the same helper keeps the refusal for an assembled
    string and drops it for a renamed import.
    """
    modules = [("core/_alias_fixture.py", ast.parse(_ALIASED_BUILDER))]

    sites, errors = _collect(modules)

    assert not errors, errors
    found = sites[("core/_alias_fixture.py", "new_producer")]
    assert [shape for _lineno, shape, _d in found] == [BUILDER_CALL], found


@pytest.mark.architecture
def test_the_shape_check_reports_a_bare_assembled_string():
    """Positive control for the half that is checked mechanically.

    Without this, "every site passes" would also be true of a walk that found
    nothing to object to because it could not object.
    """
    tree = ast.parse(
        "def leak(token):\n"
        "    register_credential_secret(f'Authorization: Bearer {token}')\n"
    )
    _annotate_parents(tree)
    call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _callee_name(node) == REGISTER_HELPER
    )
    shape, described = _observed_shape(call)
    assert shape is None, f"an f-string was accepted as {shape}"
    assert "JoinedStr" in described

    # And the builder's own shape is recognised, so the refusal above is about
    # the argument rather than about the walk failing to read anything.
    tree = ast.parse(
        "def ok(pair):\n    register_credential_secret(credential_header_line(pair))\n"
    )
    _annotate_parents(tree)
    call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _callee_name(node) == REGISTER_HELPER
    )
    assert _observed_shape(call)[0] == BUILDER_CALL

"""Every producer of a registered credential secret registers the right shape.

fix(#1857 item 10). ``register_credential_secret`` feeds the exact-value scrub
that runs last over every log line. ``_secret_variants`` expands a registered
HEADER LINE into the bare token, the basic blob and the basic cleartext, and it
recognises a line by the ``": "`` in it, so registering the VALUE instead
expands to nothing and the raw token travels through every line the process
emits.

Each producer declares which transport it is, rather than one rule demanding
the builder's result everywhere: a credential that travels as a URL query
parameter has no header form, and a fabricated line would scrub nothing while
the real value went unregistered. A new call site fails until it is entered.
"""

import ast
import pathlib

import pytest

APP_ROOT = pathlib.Path(__file__).resolve().parents[1] / "app"

REGISTER_HELPER = "register_credential_secret"
HEADER_LINE_BUILDER = "credential_header_line"

# A literal call to the header-line builder: the shape `_secret_variants`
# expands. Checked structurally.
BUILDER_CALL = "builder_call"
# A parameter already holding a whole line. Not provable here, so the entry's
# justification says where the line comes from.
CARRIED_LINE = "carried_line"
# No header form on this path, so the bare transport value is the registration.
QUERY_VALUE = "query_value"

_SHAPES = {BUILDER_CALL, CARRIED_LINE, QUERY_VALUE}

# (module path relative to backend/app, enclosing function) ->
# (exact call count, shape, justification). Asserted EXACT in both directions.
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
    """Every name in this module a call to ``helper`` can be spelled with.

    Matched on the IMPORTED name whatever module it came from, the loud
    direction: narrowing to one source module would let a re-export hide a
    site. The attribute spelling needs nothing here, since the terminal name
    carries it. An alias is COLLECTED rather than refused, so it reaches the
    entry the table demands (#1857 item 10).
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


def _parameter_names(fn: ast.AST | None) -> set[str]:
    args = getattr(fn, "args", None)
    if args is None:
        return set()
    names = {a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]}
    if args.vararg:
        names.add(args.vararg.arg)
    if args.kwarg:
        names.add(args.kwarg.arg)
    return names


def _rebinding_lines(fn: ast.AST, name: str, before: int) -> list[int]:
    """Lines at or above ``before`` where ``name`` is bound to something else.

    Every binding form writes an ``ast.Name`` in ``Store`` context, so one walk
    covers assignment, augmented and annotated assignment, walrus, and ``for``
    and ``with`` targets, including through tuple unpacking. Nested scopes are
    walked too, which can only over-report; a flagged site costs a review.
    """
    return sorted(
        node.lineno
        for node in ast.walk(fn)
        if isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Store)
        and node.id == name
        and node.lineno <= before
    )


def _carried_name_rejection(fn: ast.AST | None, name: str, lineno: int) -> str | None:
    """Why this name cannot be read as the whole line, or None if it can.

    fix(#1857 item 10, codex review): being a parameter was the whole test, and
    a parameter reassigned before the call is a local again. That is the #1844
    shape exactly, spelled so it still reads like the signature.
    """
    if name not in _parameter_names(fn):
        return (
            f"registers the local name {name!r}, which is not a parameter of "
            "its function. A local can hold anything; a parameter is a "
            "contract the callers can be read against"
        )
    rebound = _rebinding_lines(fn, name, lineno)
    if rebound:
        lines = ",".join(str(n) for n in rebound)
        return (
            f"registers the parameter {name!r}, which is reassigned at line(s) "
            f"{lines} before this call, so it no longer holds what the "
            "signature promises. Splitting the line and registering the value "
            "half is the #1844 finding this gate exists to catch"
        )
    return None


def _observed_shape(
    node: ast.Call, builder_names: set[str] | None = None
) -> tuple[str | None, str]:
    """(shape, description) for one registration call's argument.

    A shape of None is a violation on its own: an assembled string, a dict
    lookup or an attribute read is how a fabricated or partial line gets past a
    reader. ``builder_names`` carries the builder's spellings in this module so
    an aliased import of it does not report as an unresolvable call.
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

    ``modules`` defaults to the whole of ``backend/app``; the fixtures pass
    their own so a spelling is measured against the real collector.
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
            if shape == CARRIED_LINE:
                reason = _carried_name_rejection(fn, described, node.lineno)
                if reason is not None:
                    errors.append(f"{rel}:{node.lineno} ({fn_name}) {reason}")
                    continue
            sites.setdefault((rel, fn_name), []).append((node.lineno, shape, described))
    return sites, errors


def _policy_violations(
    sites: dict[tuple[str, str], list[tuple[int, str, str]]],
) -> list[str]:
    """Every way the collected sites and REGISTRATION_POLICY can disagree.

    Its own function so a fixture goes through the real rules, not a paraphrase.
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
            # QUERY_VALUE and CARRIED_LINE are both a plain name and the
            # entry is what separates them, but BUILDER_CALL is distinguishable
            # and a fabricated line at a query site is the thing to refuse.
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

    Value and line are one identifier apart at the call site and only one
    expands, so the check is on the SHAPE and on the site being in the table.
    """
    sites, violations = _collect()
    violations += _policy_violations(sites)

    assert not violations, "\n".join(violations)

    assert len(sites) >= 3, (
        f"only {len(sites)} registration site(s) found; the codebase has at "
        "least 3. The walk has gone blind, fix it before trusting this gate"
    )


# Source rather than a file in app/, which would be a real unenumerated
# producer (#1857 item 10).
_ALIASED_REGISTRATION = """
from app.core.service_tokens import register_credential_secret as {alias}


def new_producer(token):
    {alias}(token)
"""

_ALIASED_BUILDER = """
from app.core.service_tokens import credential_header_line as line
from app.core.service_tokens import register_credential_secret


def new_producer(pair):
    register_credential_secret(line(pair))
"""


@pytest.mark.architecture
@pytest.mark.parametrize("alias", ["reg", "register"])
def test_an_aliased_import_of_the_helper_is_still_collected(alias):
    """An aliased call must surface as unenumerated, not as nothing.

    Matching the terminal callee name alone collected NOTHING for it, and the
    site floor does not help because the three known sites are still found.
    """
    modules = [
        (
            "processing/ingest/_alias_fixture.py",
            ast.parse(_ALIASED_REGISTRATION.format(alias=alias)),
        )
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
    """The same blindness in the safe direction: correct code must not report.

    Resolving both names the same way keeps the refusal for an assembled
    string and drops it for a renamed import.
    """
    modules = [("core/_alias_fixture.py", ast.parse(_ALIASED_BUILDER))]

    sites, errors = _collect(modules)

    assert not errors, errors
    found = sites[("core/_alias_fixture.py", "new_producer")]
    assert [shape for _lineno, shape, _d in found] == [BUILDER_CALL], found


# fix(#1857 item 10, codex review): the two halves of "is this name the line".
_REASSIGNED_PARAMETER = """
from app.core.service_tokens import register_credential_secret


def sanitize(header_line):
    header_line = header_line.split(": ", 1)[1]
    register_credential_secret(header_line)
    return header_line
"""

_PASSTHROUGH_PARAMETER = """
from app.core.service_tokens import register_credential_secret


def sanitize(header_line):
    if not header_line:
        raise ValueError("empty")
    register_credential_secret(header_line)
    return header_line
"""


@pytest.mark.architecture
def test_a_parameter_reassigned_before_the_call_is_not_the_line():
    """Being a parameter was the whole test, and #1844 is one line away.

    ``header_line = header_line.split(": ", 1)[1]`` registers the value while
    still reading as the signature, which is the finding this gate exists to
    catch, spelled so the gate agreed with it.
    """
    modules = [("processing/ingest/_reassign.py", ast.parse(_REASSIGNED_PARAMETER))]

    sites, errors = _collect(modules)

    assert not sites, f"the reassigned parameter was accepted as a site: {sites}"
    assert len(errors) == 1, errors
    assert "reassigned at line(s) 6" in errors[0], errors[0]
    assert "#1844" in errors[0], errors[0]


@pytest.mark.architecture
def test_a_parameter_passed_through_untouched_stays_a_carried_line():
    """The half that keeps this a measurement.

    Refusing every parameter would also pass the test above, and would refuse
    the one real site that legitimately registers what it was handed.
    """
    modules = [("processing/ingest/_passthrough.py", ast.parse(_PASSTHROUGH_PARAMETER))]

    sites, errors = _collect(modules)

    assert not errors, errors
    found = sites[("processing/ingest/_passthrough.py", "sanitize")]
    assert [shape for _lineno, shape, _d in found] == [CARRIED_LINE], found


@pytest.mark.architecture
def test_the_shape_check_reports_a_bare_assembled_string():
    """Positive control: "every site passes" must not mean "nothing is read"."""
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

    # The builder's shape is recognised, so the refusal above is about the
    # argument rather than about the walk reading nothing.
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

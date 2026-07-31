"""Structural gate: no sync test may depend on an async fixture.

fix(#1082): a sync test that reaches an async fixture does not merely
fail itself. It poisons that fixture's FixtureDef for the rest of the xdist
worker's session, and every later test that touches the fixture errors at
setup with a bare `AssertionError`. One such test produced 951 errors in a
single CI run, none of which named the test that caused them.

The mechanism is in pytest itself (9.1.1, `_pytest/fixtures.py`):

    execute()  1222  self.addfinalizer(...)          # finalizer registered
    execute()  1232  pytest_fixture_setup(...)       # raises at 1320, which is
                                                     # BEFORE the try at 1327
                                                     # that sets cached_result
    finish()   1147  if self.cached_result is None:  # "Already finished. It is
                         return                      #  assumed that finalizers
                                                     #  cannot be added in this
                                                     #  state." -- so _finalizers
                                                     #  is never cleared
    execute()  1221  assert not self._finalizers     # fails forever after

So the FixtureDef is left in a state its own teardown refuses to clean, and
the assertion that notices carries no message, no fixture name, and no test
name. The failure is maximally loud and minimally informative, which is why
this gate exists at the shape instead.

There is no legitimate instance of this shape -- pytest fails it every time --
so this gate has no allowlist. The two remedies are to shadow the fixture with
a sync no-op for the class holding the sync tests (see `TestUserErrorMessage`
in `test_analysis_materialize.py`), or to move the sync test to a class that
already does.

Why a gate rather than a fix at the two call sites: #1030 hit this, diagnosed
it correctly, and shadowed the fixture for the only sync-test class that
existed on its branch. #1057 then added two sync tests to a different class in
the same module. Both PRs were green alone. The remedy was a per-class
enumeration that was complete when written and silently incomplete a week
later, so the thing worth checking in is the rule, not another entry.

Sibling gates in the same neighbourhood, same idea: `test_rule1_structural.py`
(visibility filters) and `test_rule2_structural.py` (GDAL/rasterio safe envs).
This file deliberately fixes nothing it finds -- the first violation belongs
to #1030.

Known gap: this reads the AST, so it sees fixtures requested by parameter name
and nothing else. A fixture pulled at runtime through
`request.getfixturevalue("client")` is invisible to it. That path is not used
in this suite today; if it starts being used, the gate goes quiet rather than
loud, which is the failure direction to watch for.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_TESTS = Path(__file__).parent
_MODULE_SCOPE = "<module>"

# Requested by name but never resolvable to a fixture in this tree.
_PYTEST_BUILTINS = frozenset({"request", "self", "cls"})


def _is_fixture(decorator: ast.expr) -> bool:
    func = decorator.func if isinstance(decorator, ast.Call) else decorator
    return ast.unparse(func).endswith("fixture")


def _is_autouse(decorator: ast.expr) -> bool:
    return isinstance(decorator, ast.Call) and any(
        kw.arg == "autouse" and getattr(kw.value, "value", False) is True
        for kw in decorator.keywords
    )


def _argnames(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    args = fn.args
    names = [a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)]
    return [n for n in names if n not in _PYTEST_BUILTINS]


class _Scopes:
    """Fixtures, autouse names, and sync tests, keyed by scope.

    Scope is `_MODULE_SCOPE` or a class name. A class-level definition shadows
    a module-level one of the same name, which shadows conftest.

    fix(#1082): keying by scope is the load-bearing part of this file and it
    reads like ceremony, so it is worth saying what happens without it. The
    first version of this gate pooled every fixture in a file into one dict and
    every sync test into one list. That is smaller and it is wrong: it reported
    16 sync tests in `test_geometry_detection.py`, whose `_skip_no_db` autouse
    fixture is class-level in `TestConstructPointGeometry` and
    `TestConstructWktGeometry` while those tests live in
    `TestDetectGeometryColumns` and never see it. Two false positives on a
    clean main, which is how a gate gets switched off.

    The same pooling also hid a true positive: two fixtures in one file can
    share a name (a class-level sync override of a module-level async fixture
    is exactly the remedy this gate recommends), and a flat dict keeps only the
    last one.
    """

    def __init__(self, tree: ast.Module) -> None:
        self.fixtures: dict[str, dict[str, tuple[bool, list[str]]]] = {}
        self.autouse: dict[str, list[str]] = {}
        self.sync_tests: dict[str, list[tuple[str, list[str]]]] = {}
        self._visit(tree.body, _MODULE_SCOPE)

    def _visit(self, body: list[ast.stmt], scope: str) -> None:
        for node in body:
            if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                self._visit(node.body, node.name)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if any(_is_fixture(d) for d in node.decorator_list):
                    self.fixtures.setdefault(scope, {})[node.name] = (
                        isinstance(node, ast.AsyncFunctionDef),
                        _argnames(node),
                    )
                    if any(_is_autouse(d) for d in node.decorator_list):
                        self.autouse.setdefault(scope, []).append(node.name)
                elif node.name.startswith("test_") and isinstance(
                    node, ast.FunctionDef
                ):
                    self.sync_tests.setdefault(scope, []).append(
                        (node.name, _argnames(node))
                    )


def _conftest_scopes() -> _Scopes:
    return _Scopes(ast.parse((_TESTS / "conftest.py").read_text(encoding="utf-8")))


_CONFTEST = _conftest_scopes()
_CONFTEST_FIXTURES = _CONFTEST.fixtures.get(_MODULE_SCOPE, {})


def _resolve(name: str, scopes: _Scopes, scope: str) -> tuple[bool, list[str]] | None:
    for candidate in (scope, _MODULE_SCOPE):
        found = scopes.fixtures.get(candidate, {}).get(name)
        if found is not None:
            return found
    return _CONFTEST_FIXTURES.get(name)


def _reaches_async(
    name: str, scopes: _Scopes, scope: str, seen: set[str] | None = None
) -> str | None:
    """Return the async fixture `name` transitively depends on, if any."""
    seen = seen if seen is not None else set()
    if name in seen:
        return None
    seen.add(name)
    resolved = _resolve(name, scopes, scope)
    if resolved is None:
        return None
    is_async, deps = resolved
    if is_async:
        return name
    for dep in deps:
        if hit := _reaches_async(dep, scopes, scope, seen):
            return hit
    return None


def _offenders_in(path: Path) -> list[str]:
    scopes = _Scopes(ast.parse(path.read_text(encoding="utf-8")))
    offenders: list[str] = []
    for scope, tests in scopes.sync_tests.items():
        # Autouse fixtures that apply here: this scope's own, plus the module's
        # when this scope is a class, plus conftest's.
        applicable = list(scopes.autouse.get(scope, []))
        if scope != _MODULE_SCOPE:
            applicable += scopes.autouse.get(_MODULE_SCOPE, [])
        applicable += _CONFTEST.autouse.get(_MODULE_SCOPE, [])
        where = "module scope" if scope == _MODULE_SCOPE else scope
        for test_name, requested in tests:
            for root in (*applicable, *requested):
                hit = _reaches_async(root, scopes, scope)
                if hit is None:
                    continue
                how = "autouse " if root in applicable else ""
                via = "" if hit == root else f" (via {root!r})"
                offenders.append(
                    f"{path.name}::{where}::{test_name} is sync but reaches "
                    f"async {how}fixture {hit!r}{via}"
                )
                break
    return offenders


@pytest.mark.architecture
def test_no_sync_test_depends_on_an_async_fixture() -> None:
    offenders: list[str] = []
    for path in sorted(_TESTS.rglob("test_*.py")):
        offenders.extend(_offenders_in(path))

    if offenders:
        pytest.fail(
            "A sync test reaches an async fixture. pytest errors its setup and "
            "leaves the fixture's FixtureDef un-finalizable, so every later "
            "test on the same xdist worker that touches it errors with a bare "
            "AssertionError naming nothing.\n\n"
            "Shadow the fixture with a sync no-op in the class holding the "
            "sync test, or move the sync test to a class that already does "
            "(see TestUserErrorMessage in test_analysis_materialize.py):\n\n"
            "    @pytest.fixture(autouse=True)\n"
            "    def <fixture_name>(self):\n"
            "        yield\n\n" + "\n".join(offenders)
        )


@pytest.mark.architecture
def test_the_gate_detects_the_shape_that_produced_951_errors() -> None:
    """Pin the detector against the exact #1030/#1057 combination.

    The gate passes on a clean tree, which is indistinguishable from a gate
    that detects nothing. This reconstructs the shape in memory -- a
    module-level async autouse fixture reaching `client` through a conftest
    fixture, and a sync test in a class that does NOT shadow it -- and asserts
    the detector fires, names the async fixture, and does NOT fire for the
    class that does shadow it.
    """
    source = """
import pytest

@pytest.fixture(autouse=True)
async def _release_analysis_job_slots(test_db_session):
    yield

class TestMaterializeWorker:
    async def test_async_one(self, test_db_session): ...
    def test_timeout_message_names_the_budget_that_fired(self, monkeypatch): ...

class TestUserErrorMessage:
    @pytest.fixture(autouse=True)
    def _release_analysis_job_slots(self):
        yield

    def test_db_error_hides_generated_sql(self): ...
"""
    scopes = _Scopes(ast.parse(source))

    unshadowed = _reaches_async(
        "_release_analysis_job_slots", scopes, "TestMaterializeWorker"
    )
    assert unshadowed == "_release_analysis_job_slots"

    # The class-level sync override is what kept these 5 tests green in the
    # same CI run where the other class's 2 errored.
    shadowed = _reaches_async(
        "_release_analysis_job_slots", scopes, "TestUserErrorMessage"
    )
    assert shadowed is None

    # And a sync test that asks for an async conftest fixture directly, with no
    # autouse fixture involved at all.
    direct = _Scopes(ast.parse("def test_x(client): ...\n"))
    assert _reaches_async("client", direct, _MODULE_SCOPE) == "client"

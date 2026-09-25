"""Only the job ledger writes ``ingest_jobs.status``."""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path

import pytest

import app

_APP = Path(app.__file__).parent
_LEDGER = "platform/jobs/ledger.py"

# Helpers that write the ``values`` their caller composes. A caller's values are
# judged at its call; a function that hands a parameter of its own on as those
# values counts as a write, except the heartbeat bodies below, which can't write a
# status because update_ingest_job_for_attempt refuses the ledger's columns.
_VALUES_HELPERS = frozenset(
    {"update_ingest_job_for_attempt", "require_ingest_job_update"}
)
_FORWARDING_BODIES = frozenset(
    {
        "platform/jobs/heartbeat.py::update_ingest_job_for_attempt",
        "platform/jobs/heartbeat.py::require_ingest_job_update",
    }
)

_STATEMENT_BUILDERS = frozenset({"update", "sa_update", "insert", "pg_insert"})
_RAW_WRITE = re.compile(
    r"(?is)\binsert\s+into\s+[\w.\"]*ingest_jobs\b[^;]*\bstatus\b"
    r"|\bingest_jobs\"?\s+(?:as\s+\w+\s+)?set\s+(?:(?!\bwhere\b).)*\bstatus\s*="
)

_Function = ast.FunctionDef | ast.AsyncFunctionDef


def _own_nodes(scope: ast.AST) -> Iterator[ast.AST]:
    """``scope``'s nodes, without the bodies of the functions nested in it."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        yield node
        if not isinstance(node, _Function | ast.ClassDef):
            stack.extend(ast.iter_child_nodes(node))


def _unwrap(node: ast.expr) -> ast.expr:
    return node.value if isinstance(node, ast.Await) else node


def _callee(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _functions_returning_a_job(trees: list[ast.AST]) -> frozenset[str]:
    return frozenset(
        node.name
        for tree in trees
        for node in ast.walk(tree)
        if isinstance(node, _Function)
        and node.returns is not None
        and "IngestJob" in ast.unparse(node.returns)
    )


def _makes_a_job(value: ast.expr, returns_a_job: frozenset[str]) -> bool:
    value = _unwrap(value)
    if "select(IngestJob)" in ast.unparse(value):
        return True
    if not isinstance(value, ast.Call):
        return False
    name = _callee(value)
    if name == "IngestJob" or name in returns_a_job:
        return True
    return (
        name == "get" and bool(value.args) and ast.unparse(value.args[0]) == "IngestJob"
    )


# Calls that read rows out of a statement or result they are handed.
_READS = frozenset(
    {
        "all",
        "execute",
        "first",
        "get",
        "one",
        "one_or_none",
        "scalar",
        "scalar_one",
        "scalar_one_or_none",
        "scalars",
        "unique",
    }
)


def _reads_a_job(
    value: ast.expr, jobs: set[str], returns_a_job: frozenset[str]
) -> bool:
    """Whether ``value`` is a job, or is read out of a name that holds jobs."""
    value = _unwrap(value)
    if _makes_a_job(value, returns_a_job):
        return True
    while isinstance(value, ast.Call) and _callee(value) in _READS:
        first = value.args[0] if value.args else None
        if isinstance(first, ast.Name) and first.id in jobs:
            return True
        if not isinstance(value.func, ast.Attribute):
            return False
        value = _unwrap(value.func.value)
    return isinstance(value, ast.Name) and value.id in jobs


def _job_names(scope: ast.AST, returns_a_job: frozenset[str]) -> set[str]:
    """Names bound in ``scope`` to an IngestJob, or to a query or result of them."""
    names: set[str] = set()
    if isinstance(scope, _Function):
        args = scope.args
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            annotation = ast.unparse(arg.annotation) if arg.annotation else None
            if annotation is None and arg.arg == "job":
                names.add(arg.arg)
            elif annotation is not None and "IngestJob" in annotation:
                names.add(arg.arg)
    bindings: list[tuple[list[ast.expr], ast.expr]] = []
    for node in _own_nodes(scope):
        if isinstance(node, ast.Assign):
            bindings.append((node.targets, node.value))
        elif isinstance(node, ast.AnnAssign | ast.NamedExpr) and node.value:
            bindings.append(([node.target], node.value))
        elif isinstance(node, ast.For | ast.AsyncFor):
            bindings.append(([node.target], node.iter))
    grew = True
    while grew:
        grew = False
        for targets, value in bindings:
            new = {t.id for t in targets if isinstance(t, ast.Name)} - names
            if new and _reads_a_job(value, names, returns_a_job):
                names |= new
                grew = True
    return names


def _statement_root(node: ast.expr, bindings: dict[str, ast.expr]) -> ast.Call | None:
    """The ``update(...)`` or ``insert(...)`` a statement chain starts from."""
    followed: set[str] = set()
    while True:
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _STATEMENT_BUILDERS:
                return node
            node = node.func
        elif isinstance(node, ast.Attribute):
            node = node.value
        elif isinstance(node, ast.Name) and node.id in bindings:
            if node.id in followed:
                return None
            followed.add(node.id)
            node = bindings[node.id]
        else:
            return None


def _may_target_jobs(root: ast.Call | None) -> bool:
    """Whether a statement may write ``ingest_jobs``; an unresolved one may."""
    if root is None or not root.args:
        return True
    model = root.args[0]
    return not (isinstance(model, ast.Name) and model.id != "IngestJob")


def _names_status(
    values: ast.expr,
    bindings: dict[str, ast.expr],
    returns: dict[str, list[ast.expr]],
) -> bool:
    """Whether a values argument carries a ``status`` key; a ``**`` may."""
    values = _unwrap(values)
    if isinstance(values, ast.Dict):
        return any(
            key is None
            or (isinstance(key, ast.Constant) and key.value == "status")
            or (isinstance(key, ast.Attribute) and key.attr == "status")
            for key in values.keys
        )
    if isinstance(values, ast.Call) and _callee(values) == "dict":
        return any(k.arg in ("status", None) for k in values.keywords)
    if isinstance(values, ast.Name) and values.id in bindings:
        return _names_status(bindings[values.id], {}, returns)
    if isinstance(values, ast.Call) and _callee(values) in returns:
        return any(_names_status(value, {}, {}) for value in returns[_callee(values)])
    return False


def _status_writes(
    tree: ast.AST, returns_a_job: frozenset[str]
) -> list[tuple[str, int]]:
    """Every job status write in a module, as (enclosing function, line).

    A write is an ``IngestJob(...)`` construction; a ``.values(...)`` naming
    ``status`` (keyword, dict key or ``**``) on an update or insert that may
    target ``ingest_jobs``; ``.status =`` or ``setattr(..., "status", ...)`` on a
    name bound to an IngestJob; a ``values`` dict with a ``status`` key passed
    to one of ``_VALUES_HELPERS``, or handed on to one from a parameter (as
    itself, ``dict(values)``, ``values.copy()`` or any other expression that
    is not a display) or by a ``**`` expansion; or raw SQL that sets the status.

    A name holds a job when it is bound to ``IngestJob(...)``, a ``select(IngestJob)``,
    ``session.get(IngestJob, ...)`` or a call annotated to return one, or is read out
    of such a name by assignment, ``for`` or ``:=`` (``result.scalar_one_or_none()``,
    ``session.scalar(stmt)``, ``result.scalars()``).

    Known limits: bindings are read within one function, and a helper's
    ``values`` also from a function of the same module that returns it. A
    statement whose target cannot be resolved counts as a job write. An
    unannotated parameter counts as a job only when it is named ``job``. Not
    followed: dynamic dispatch, dicts built in another module, a ``status`` key
    assigned into a bound dict (``values["status"] = ...``), a list of dicts
    passed for an executemany, and tuple targets.
    """
    returns = {
        node.name: [
            ret.value
            for ret in _own_nodes(node)
            if isinstance(ret, ast.Return) and ret.value is not None
        ]
        for node in ast.walk(tree)
        if isinstance(node, _Function)
    }
    writes: list[tuple[str, int]] = []
    scopes = [
        (node, node.name) for node in ast.walk(tree) if isinstance(node, _Function)
    ]
    for scope, name in [*scopes, (tree, "<module>")]:
        bindings = {
            target.id: node.value
            for node in _own_nodes(scope)
            if isinstance(node, ast.Assign | ast.AnnAssign) and node.value is not None
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            if isinstance(target, ast.Name)
        }
        jobs = _job_names(scope, returns_a_job)
        params = (
            {
                arg.arg
                for arg in (
                    *scope.args.posonlyargs,
                    *scope.args.args,
                    *scope.args.kwonlyargs,
                )
            }
            if isinstance(scope, _Function)
            else set()
        )
        for node in _own_nodes(scope):
            if _writes_status(node, bindings, returns, jobs, params - bindings.keys()):
                writes.append((name, node.lineno))
    return writes


def _writes_status(
    node: ast.AST,
    bindings: dict[str, ast.expr],
    returns: dict[str, list[ast.expr]],
    jobs: set[str],
    params: set[str],
) -> bool:
    if isinstance(node, ast.Call):
        callee = _callee(node)
        if callee == "IngestJob":
            return True
        if callee == "values" and isinstance(node.func, ast.Attribute):
            names_status = any(k.arg in ("status", None) for k in node.keywords) or any(
                _names_status(arg, bindings, returns) for arg in node.args
            )
            return names_status and _may_target_jobs(
                _statement_root(node.func.value, bindings)
            )
        if callee in _VALUES_HELPERS:
            if any(k.arg is None for k in node.keywords):
                return True
            values = next((k.value for k in node.keywords if k.arg == "values"), None)
            if values is None:
                return False
            if not isinstance(_unwrap(values), ast.Dict) and any(
                isinstance(name, ast.Name) and name.id in params
                for name in ast.walk(values)
            ):
                return True
            return _names_status(values, bindings, returns)
        return (
            callee == "setattr"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in jobs
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == "status"
        )
    if isinstance(node, ast.Assign | ast.AugAssign | ast.AnnAssign):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return any(
            isinstance(target, ast.Attribute)
            and target.attr == "status"
            and isinstance(target.value, ast.Name)
            and target.value.id in jobs
            for target in targets
        )
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and bool(_RAW_WRITE.search(node.value))
    )


def _tree_writes() -> dict[str, list[tuple[str, int]]]:
    """Every status write in ``backend/app``, by module path."""
    trees = {
        path.relative_to(_APP).as_posix(): ast.parse(path.read_text())
        for path in sorted(_APP.rglob("*.py"))
    }
    returns_a_job = _functions_returning_a_job(list(trees.values()))
    return {
        module: writes
        for module, tree in trees.items()
        if (writes := _status_writes(tree, returns_a_job))
    }


def _allowed(module: str, function: str) -> bool:
    return module == _LEDGER or f"{module}::{function}" in _FORWARDING_BODIES


def test_only_the_ledger_writes_a_job_status() -> None:
    """Nothing outside the ledger writes a job's status, except the heartbeat forwarders."""
    offenders = [
        f"{module}:{line} {function}"
        for module, writes in _tree_writes().items()
        for function, line in writes
        if not _allowed(module, function)
    ]
    assert not offenders, offenders


def test_both_heartbeat_forwarders_still_forward() -> None:
    """The two exempt heartbeat bodies still hand their callers' values on."""
    found = {
        f"{module}::{function}"
        for module, module_writes in _tree_writes().items()
        for function, _line in module_writes
    }
    assert _FORWARDING_BODIES <= found


def test_the_scan_reads_the_tree_and_finds_the_ledgers_writes() -> None:
    """The scan reads the whole tree and sees the ledger's own writes."""
    assert len(list(_APP.rglob("*.py"))) >= 400
    ledger_functions = {function for function, _line in _tree_writes()[_LEDGER]}
    assert {"create", "_move", "_end", "retry"} <= ledger_functions


# The ledger's transitions, which the structural gates find by their
# ``ledger.<name>(`` spelling.
_TRANSITIONS = frozenset(
    {"create", "claim", "stage", "fan_out", "restore", "complete", "fail", "abort"}
)
_LEDGER_MODULE = "app.platform.jobs.ledger"


def _ledger_spellings(module: str, tree: ast.AST) -> list[str]:
    """Imports that name a transition or bind the ledger module other than as ``ledger``."""
    package = ["app", *module.removesuffix(".py").split("/")[:-1]]
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            source = ".".join([*base, *filter(None, [node.module])])
            for alias in node.names:
                if source == _LEDGER_MODULE and alias.name in _TRANSITIONS:
                    found.append(f"{module}:{node.lineno} imports {alias.name}")
                elif f"{source}.{alias.name}" == _LEDGER_MODULE and (
                    alias.asname not in (None, "ledger")
                ):
                    found.append(f"{module}:{node.lineno} binds it as {alias.asname}")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _LEDGER_MODULE and alias.asname != "ledger":
                    found.append(f"{module}:{node.lineno} imports {alias.name}")
    return found


def test_transitions_are_called_through_the_ledger_module() -> None:
    """Outside the ledger, a transition is only ever spelled ``ledger.<name>``."""
    offenders = [
        spelling
        for path in sorted(_APP.rglob("*.py"))
        if (module := path.relative_to(_APP).as_posix()) != _LEDGER
        for spelling in _ledger_spellings(module, ast.parse(path.read_text()))
    ]
    assert not offenders, offenders


@pytest.mark.parametrize(
    "source",
    [
        "from app.platform.jobs.ledger import fail\n",
        "from app.platform.jobs.ledger import Outcome, abort\n",
        "from .ledger import complete\n",
        "from app.platform.jobs import ledger as jobs_ledger\n",
        "import app.platform.jobs.ledger\n",
        "import app.platform.jobs.ledger as L\n",
    ],
)
def test_each_other_spelling_is_seen(source: str) -> None:
    """A transition imported by name, or the module bound under another name, is seen."""
    assert _ledger_spellings("platform/jobs/heartbeat.py", ast.parse(source))


@pytest.mark.parametrize(
    "source",
    [
        "from app.platform.jobs import ledger\n",
        "from app.platform.jobs.ledger import Outcome, StaleIngestAttempt, hold\n",
        "from .ledger import hold\n",
    ],
)
def test_the_module_import_and_other_names_are_allowed(source: str) -> None:
    """Importing the module as ``ledger``, or a name that is no transition, is allowed."""
    assert not _ledger_spellings("platform/jobs/heartbeat.py", ast.parse(source))


def _scan(source: str) -> list[tuple[str, int]]:
    tree = ast.parse(source)
    return _status_writes(tree, _functions_returning_a_job([tree]))


_SHAPES = {
    "constructor": "def f(s):\n    s.add(IngestJob(status='running'))\n",
    "update keyword": "def f(s):\n    s.execute(update(IngestJob).values(status='failed'))\n",
    "update unpacked": "def f(s, v):\n    s.execute(sa_update(IngestJob).values(**v))\n",
    "unresolved target": "def f(s, job):\n    s.execute(sa_update(type(job)).values(status='failed'))\n",
    "statement bound to a name": (
        "def f(s):\n    stmt = update(IngestJob).where(x)\n"
        "    s.execute(stmt.values({'status': 'failed'}))\n"
    ),
    "attribute on a loaded job": (
        "async def f(s, i):\n    job = await s.get(IngestJob, i)\n    job.status = 'failed'\n"
    ),
    "attribute on a job parameter": "def f(job):\n    job.status = 'failed'\n",
    "attribute on a job read from a result": (
        "async def f(db, i):\n"
        "    result = await db.execute(select(IngestJob).where(IngestJob.id == i))\n"
        "    job = result.scalar_one_or_none()\n"
        "    job.status = 'pending'\n"
    ),
    "attribute on a job from a session scalar": (
        "async def f(s, i):\n    stmt = select(IngestJob).where(IngestJob.id == i)\n"
        "    row = await s.scalar(stmt)\n    row.status = 'failed'\n"
    ),
    "attribute on a job in a loop": (
        "async def f(s):\n    result = await s.execute(select(IngestJob))\n"
        "    for row in result.scalars():\n        row.status = 'failed'\n"
    ),
    "attribute on a job bound by a walrus": (
        "async def f(s, stmt):\n    rows = await s.execute(select(IngestJob))\n"
        "    if (row := rows.scalars().first()) is not None:\n"
        "        row.status = 'failed'\n"
    ),
    "update with a column key": (
        "def f(s):\n    s.execute(update(IngestJob).values({IngestJob.status: 'failed'}))\n"
    ),
    "helper values from dict()": (
        "async def f(s, i, a):\n"
        "    await require_ingest_job_update(s, i, a, values=dict(status='failed'))\n"
    ),
    "setattr on an annotated job": (
        "def f(row: IngestJob):\n    setattr(row, 'status', 'failed')\n"
    ),
    "attribute on a created job": (
        "async def create_ingest_job(s) -> IngestJob:\n    ...\n"
        "async def f(s):\n    job = await create_ingest_job(s)\n    job.status = 'running'\n"
    ),
    "helper values display": (
        "async def f(s, i, a):\n"
        "    await update_ingest_job_for_attempt(s, i, a, values={'status': 'failed'})\n"
    ),
    "helper values name": (
        "async def f(s, i, a, st):\n    values = {'status': st}\n"
        "    await require_ingest_job_update(s, i, a, values=values)\n"
    ),
    "helper values annotated name": (
        "async def f(s, i, a, st):\n    values: dict = {'status': st}\n"
        "    await update_ingest_job_for_attempt(s, i, a, values=values)\n"
    ),
    "helper values forwarded from a parameter": (
        "async def f(s, i, a, values):\n"
        "    await update_ingest_job_for_attempt(s, i, a, values=values)\n"
    ),
    "helper values copied from a parameter by dict()": (
        "async def f(s, i, a, values):\n"
        "    await update_ingest_job_for_attempt(s, i, a, values=dict(values))\n"
    ),
    "helper values copied from a parameter by .copy()": (
        "async def f(s, i, a, values):\n"
        "    await require_ingest_job_update(s, i, a, values=values.copy())\n"
    ),
    "helper keywords handed on by **": (
        "async def f(s, i, a, **kw):\n"
        "    await update_ingest_job_for_attempt(s, i, a, **kw)\n"
    ),
    "helper values from a function": (
        "def staged():\n    return {'status': 'pending'}\n"
        "async def f(s, i, a):\n"
        "    await update_ingest_job_for_attempt(s, i, a, values=staged())\n"
    ),
    "raw update": (
        "def f(s):\n"
        "    s.execute(text(\"UPDATE catalog.ingest_jobs SET status = 'failed' WHERE id = :id\"))\n"
    ),
    "raw insert": (
        "def f(s):\n"
        "    s.execute(text('INSERT INTO catalog.ingest_jobs (id, status) VALUES (:i, :s)'))\n"
    ),
}

_NOT_A_JOB_STATUS = {
    "another table's update": (
        "def f(s):\n    s.execute(update(DatasetRefreshRun).values(status='failed'))\n"
    ),
    "another row's attribute": (
        "async def f(s, i):\n    run = await s.get(DatasetRefreshRun, i)\n    run.status = 'x'\n"
    ),
    "another row read beside a job": (
        "async def f(s, job):\n    asset = await lock_asset(s, job.dataset_id)\n"
        "    gen = await s.get(VrtGeneration, job.id)\n"
        "    asset.status = 'ready'\n    gen.status = 'failed'\n"
    ),
    "another table's update with a column key": (
        "def f(s):\n"
        "    s.execute(update(DatasetRefreshRun).values({DatasetRefreshRun.status: 'x'}))\n"
    ),
    "a job column other than status": (
        "def f(s, now):\n    s.execute(update(IngestJob).values(heartbeat_at=now))\n"
    ),
    "a status dict no helper writes": "def f():\n    return {'status': 'ok'}\n",
    "helper values displayed from a parameter's value": (
        "async def f(s, i, a, p):\n"
        "    await update_ingest_job_for_attempt(s, i, a, values={'progress': p})\n"
    ),
    "raw SQL reading the status": (
        'def f(s):\n    s.execute(text("UPDATE catalog.ingest_jobs SET user_metadata = :m '
        "WHERE status = 'running'\"))\n"
    ),
}


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_each_way_of_writing_a_status_is_seen(shape: str) -> None:
    """The scan sees each way a status can be written."""
    assert _scan(_SHAPES[shape]), shape


@pytest.mark.parametrize("shape", sorted(_NOT_A_JOB_STATUS))
def test_writes_that_set_no_job_status_are_not_seen(shape: str) -> None:
    """The scan leaves other tables, other columns and reads alone."""
    assert not _scan(_NOT_A_JOB_STATUS[shape]), shape

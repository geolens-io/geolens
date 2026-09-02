"""One producer of a credential header, enforced structurally (fix(#1746)).

In the shape of ``test_rule2_structural.py``: walk every module under
``backend/app/`` as an AST and assert that the two transports which carry a
service credential get their header from ``build_credential_header`` and
``credential_header_line`` in ``app/core/service_tokens.py`` rather than
composing one of their own.

Why a structural test rather than a code comment. The prefix is composed today
in four separate places, and handing any of them a finished line without
removing its own composition produces ``Authorization: Bearer Authorization:
Basic <blob>``, a working-looking string that fails at the origin with a 401
and reads in a log like a credential problem rather than a bug. Once the four
are collapsed into the builder, nothing except this test stops a fifth
appearing beside them.

The two shapes it watches:

1. **Header-file writes.** Any write in a scope that calls
   ``gdal_header_dir()``. That directory exists for exactly one thing, the
   0600 ``GDAL_HTTP_HEADER_FILE``, so a write in a scope that located it is a
   credential line by construction.
2. **Adapter header assignments.** Any ``headers[...] = ...`` under
   ``modules/catalog/sources/adapters/``, and any dict literal there keyed by
   a credential header name, which is the same composition wearing a literal.

Both allowlists are asserted EXACT in both directions and by count, so an
entry whose site disappears fails loudly instead of going stale. The four
entries below are the four compositions that exist today; lane B2b deletes
them, and this test is what tells it when the last one is gone.

WHAT THIS DOES NOT CLAIM, in the same spirit as the Rule-2 guard. It is a
lexical rule, not dataflow. A line built in one function and written in
another (no such shape exists today), a header dict assembled through
``update()`` from a value computed elsewhere, and a credential reaching an
adapter as a pre-built parameter are all outside what an AST rule can answer.
The provenance check follows names bound to a builder call within the same
scope and no further. False alarms are cheap and visible; a silent miss is the
failure that matters, so anything the resolver cannot classify is reported.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent / "app"

# The single producer, and the joiner that turns its pair into a line.
BUILDER_FUNCTIONS = frozenset({"build_credential_header", "credential_header_line"})

# The helper that locates the 0600 header-file directory. A scope that calls
# it is writing a credential header or nothing at all.
HEADER_DIR_HELPER = "gdal_header_dir"

ADAPTER_PACKAGE = "modules/catalog/sources/adapters/"

# Write calls, by exact name. Substring matching would sweep in unrelated
# helpers: `_tenant_writer_subprocess_env` contains "write".
WRITE_CALL_NAMES = frozenset({"write", "writelines", "write_text", "write_bytes"})

# Dict keys that name a credential header, compared case-insensitively
# because HTTP field names are case-insensitive.
CREDENTIAL_HEADER_KEYS = frozenset({"authorization", "x-esri-authorization"})

# Every allowlist entry is (module, scope) -> (exact count, justification).
HEADER_FILE_WRITE_ALLOWLIST: dict[tuple[str, str], tuple[int, str]] = {
    ("processing/ingest/ogr.py", "run_ogr2ogr_service"): (
        1,
        "fix(#1746 service-auth B2b removes this): composes "
        "`Authorization: Bearer <token>` inline for the commit path",
    ),
    ("modules/catalog/sources/preview.py", "run_service_preview"): (
        1,
        "fix(#1746 service-auth B2b removes this): composes the same line "
        "inline for the preview path",
    ),
}

ADAPTER_HEADER_ALLOWLIST: dict[tuple[str, str], tuple[int, str]] = {
    (f"{ADAPTER_PACKAGE}wfs.py", "probe_wfs"): (
        1,
        "fix(#1746 service-auth B2b removes this): composes the bearer header "
        "for the WFS GetCapabilities probe",
    ),
    (f"{ADAPTER_PACKAGE}ogcapi.py", "probe_ogcapi"): (
        1,
        "fix(#1746 service-auth B2b removes this): composes the bearer header "
        "for the OGC API Features landing-page probe",
    ),
}

# Positive controls. A walker that silently matched nothing would satisfy
# every allowlist assertion in this module, which is the failure mode the
# absence-claim rule exists for.
MIN_APP_MODULES = 100
MIN_HEADER_FILE_WRITE_SITES = 2
MIN_ADAPTER_HEADER_SITES = 2

_MODULE_SCOPE = "<module>"


def _app_modules() -> list[tuple[str, ast.Module]]:
    modules = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        rel = path.relative_to(APP_ROOT).as_posix()
        modules.append((rel, ast.parse(path.read_text(encoding="utf-8"))))
    return modules


def _annotate_parents(tree: ast.Module) -> None:
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child._credential_parent = node  # type: ignore[attr-defined]


def _enclosing_scope(node: ast.AST, tree: ast.Module) -> ast.AST:
    current: ast.AST | None = node
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current
        current = getattr(current, "_credential_parent", None)
    return tree


def _scope_name(scope: ast.AST) -> str:
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return scope.name
    return _MODULE_SCOPE


def _call_name(func: ast.expr) -> str | None:
    """Dotted-tail name of a call target: ``a.b.c(...)`` -> ``c``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _scope_calls(scope: ast.AST, name: str) -> bool:
    return any(
        isinstance(node, ast.Call) and _call_name(node.func) == name
        for node in ast.walk(scope)
    )


def _mentions_builder(expr: ast.AST, bound: frozenset[str]) -> bool:
    """Whether *expr* calls the builder or reads a name bound to one."""
    for node in ast.walk(expr):
        if isinstance(node, ast.Call) and _call_name(node.func) in BUILDER_FUNCTIONS:
            return True
        if isinstance(node, ast.Name) and node.id in bound:
            return True
    return False


def _builder_bound_names(scope: ast.AST) -> frozenset[str]:
    """Names bound to a builder call anywhere in *scope*.

    Deliberately flow-insensitive: a name assigned from the builder counts
    wherever it is used in that scope. Narrowing it would report violations
    for correct code, and this rule's job is to catch a hand-composed prefix,
    not to referee assignment order.
    """
    bound: set[str] = set()
    for node in ast.walk(scope):
        if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            continue
        value = node.value
        if value is None or not _mentions_builder(value, frozenset()):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            for inner in ast.walk(target):
                if isinstance(inner, ast.Name):
                    bound.add(inner.id)
    return frozenset(bound)


def _written_value(call: ast.Call) -> ast.expr | None:
    """The expression a write call puts into the file.

    ``os.write(fd, data)`` carries it second; every other write shape carries
    it first. Reading the wrong index would credit an ``os.write`` for its
    file descriptor, which never comes from the builder.
    """
    func = call.func
    is_os_write = (
        isinstance(func, ast.Attribute)
        and func.attr == "write"
        and isinstance(func.value, ast.Name)
        and func.value.id == "os"
    )
    index = 1 if is_os_write else 0
    if len(call.args) <= index:
        return None
    return call.args[index]


def _is_header_subscript(target: ast.expr) -> bool:
    if not isinstance(target, ast.Subscript):
        return False
    container = target.value
    name = None
    if isinstance(container, ast.Name):
        name = container.id
    elif isinstance(container, ast.Attribute):
        name = container.attr
    return name is not None and "header" in name.lower()


def _credential_header_values(node: ast.AST) -> list[ast.expr]:
    """Every value *node* puts into a header mapping.

    Two shapes: a subscript assignment into a name that reads as a header
    mapping, and a dict literal keyed by a credential header name. The second
    is the first one wearing a literal, and leaving it out would let a
    composition move one line up to evade the rule.
    """
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if node.value is not None and any(
            _is_header_subscript(target) for target in targets
        ):
            return [node.value]
        return []
    if isinstance(node, ast.Dict):
        return [
            value
            for key, value in zip(node.keys, node.values, strict=True)
            if isinstance(key, ast.Constant)
            and isinstance(key.value, str)
            and key.value.lower() in CREDENTIAL_HEADER_KEYS
        ]
    return []


class _Scan:
    """What one pass over a module found."""

    def __init__(self) -> None:
        self.unguarded_writes: Counter[tuple[str, str]] = Counter()
        self.unguarded_headers: Counter[tuple[str, str]] = Counter()
        self.write_sites = 0
        self.header_sites = 0

    def absorb(self, other: _Scan) -> None:
        self.unguarded_writes.update(other.unguarded_writes)
        self.unguarded_headers.update(other.unguarded_headers)
        self.write_sites += other.write_sites
        self.header_sites += other.header_sites


def _scan_module(rel: str, tree: ast.Module) -> _Scan:
    _annotate_parents(tree)
    scan = _Scan()
    is_adapter = rel.startswith(ADAPTER_PACKAGE)
    bound_cache: dict[int, frozenset[str]] = {}
    header_dir_cache: dict[int, bool] = {}

    for node in ast.walk(tree):
        is_write = (
            isinstance(node, ast.Call) and _call_name(node.func) in WRITE_CALL_NAMES
        )
        header_values = _credential_header_values(node) if is_adapter else []
        if not is_write and not header_values:
            continue

        scope = _enclosing_scope(node, tree)
        bound = bound_cache.get(id(scope))
        if bound is None:
            bound = _builder_bound_names(scope)
            bound_cache[id(scope)] = bound
        site = (rel, _scope_name(scope))

        if is_write:
            writes_a_header = header_dir_cache.get(id(scope))
            if writes_a_header is None:
                writes_a_header = _scope_calls(scope, HEADER_DIR_HELPER)
                header_dir_cache[id(scope)] = writes_a_header
            if writes_a_header:
                scan.write_sites += 1
                value = _written_value(node)  # type: ignore[arg-type]
                if value is None or not _mentions_builder(value, bound):
                    scan.unguarded_writes[site] += 1

        for value in header_values:
            scan.header_sites += 1
            if not _mentions_builder(value, bound):
                scan.unguarded_headers[site] += 1

    return scan


def _scan_backend() -> _Scan:
    total = _Scan()
    for rel, tree in _app_modules():
        total.absorb(_scan_module(rel, tree))
    return total


def _allowlist_failures(
    found: Counter[tuple[str, str]],
    allowlist: dict[tuple[str, str], tuple[int, str]],
    label: str,
) -> list[str]:
    failures: list[str] = []
    for site, count in sorted(found.items()):
        expected = allowlist.get(site)
        if expected is None:
            failures.append(
                f"{label}: {site[0]}:{site[1]} composes a credential header "
                f"itself ({count} site(s)). Use build_credential_header() and "
                "credential_header_line() from app/core/service_tokens.py."
            )
        elif expected[0] != count:
            failures.append(
                f"{label}: {site[0]}:{site[1]} has {count} unguarded site(s), "
                f"allowlisted for {expected[0]}."
            )
    for site, (expected_count, justification) in sorted(allowlist.items()):
        if not justification.strip():
            failures.append(f"{label}: {site[0]}:{site[1]} has a blank justification.")
        if site not in found:
            failures.append(
                f"{label}: {site[0]}:{site[1]} is allowlisted for "
                f"{expected_count} site(s) and has none left. Delete the entry."
            )
    return failures


def test_header_file_writes_come_from_the_shared_builder() -> None:
    scan = _scan_backend()
    assert scan.write_sites >= MIN_HEADER_FILE_WRITE_SITES, (
        "the walk found no header-file writes at all, so every assertion "
        "about them is vacuous"
    )
    failures = _allowlist_failures(
        scan.unguarded_writes, HEADER_FILE_WRITE_ALLOWLIST, "GDAL header file"
    )
    assert not failures, "\n".join(failures)


def test_adapter_credential_headers_come_from_the_shared_builder() -> None:
    scan = _scan_backend()
    assert scan.header_sites >= MIN_ADAPTER_HEADER_SITES, (
        "the walk found no adapter credential headers at all, so every "
        "assertion about them is vacuous"
    )
    failures = _allowlist_failures(
        scan.unguarded_headers, ADAPTER_HEADER_ALLOWLIST, "probe adapter"
    )
    assert not failures, "\n".join(failures)


def test_the_walk_actually_covers_the_backend() -> None:
    """The positive control for the two allowlist assertions above."""
    modules = _app_modules()
    assert len(modules) >= MIN_APP_MODULES
    assert any(rel.startswith(ADAPTER_PACKAGE) for rel, _ in modules)
    assert any(_scope_calls(tree, HEADER_DIR_HELPER) for _, tree in modules), (
        f"{HEADER_DIR_HELPER}() is called nowhere, so the header-file rule "
        "matches nothing"
    )


def _scan_synthetic(source: str) -> _Scan:
    """Run the real predicates over a synthetic adapter module."""
    return _scan_module(f"{ADAPTER_PACKAGE}synthetic.py", ast.parse(source))


def test_guard_an_inline_composition_is_flagged() -> None:
    scan = _scan_synthetic(
        "def f(token, fd):\n"
        "    path = gdal_header_dir()\n"
        '    os.write(fd, f"Authorization: Bearer {token}\\n".encode("ascii"))\n'
        '    headers["Authorization"] = f"Bearer {token}"\n'
        '    other = {"Authorization": f"Bearer {token}"}\n'
    )
    assert sum(scan.unguarded_writes.values()) == 1
    assert sum(scan.unguarded_headers.values()) == 2
    assert set(scan.unguarded_writes) == {(f"{ADAPTER_PACKAGE}synthetic.py", "f")}


def test_guard_a_builder_composition_is_clean() -> None:
    scan = _scan_synthetic(
        "def f(auth, fd):\n"
        "    path = gdal_header_dir()\n"
        "    pair = build_credential_header(auth)\n"
        "    line = credential_header_line(pair)\n"
        '    os.write(fd, f"{line}\\n".encode("ascii"))\n'
        "    headers[pair[0]] = pair[1]\n"
        '    other = {"Authorization": credential_header_line(pair)}\n'
    )
    assert scan.write_sites == 1
    assert scan.header_sites == 2
    assert not scan.unguarded_writes
    assert not scan.unguarded_headers


def test_guard_a_second_write_beside_a_builder_one_is_flagged() -> None:
    """An added composition does not ride a clean scope's credit."""
    scan = _scan_synthetic(
        "def f(auth, token, fd, other_fd):\n"
        "    path = gdal_header_dir()\n"
        "    line = credential_header_line(build_credential_header(auth))\n"
        '    os.write(fd, f"{line}\\n".encode("ascii"))\n'
        '    os.write(other_fd, f"X-API-Key: {token}\\n".encode("ascii"))\n'
    )
    assert scan.write_sites == 2
    assert sum(scan.unguarded_writes.values()) == 1


def test_guard_os_write_reads_the_second_argument() -> None:
    """``os.write(fd, data)`` and ``handle.write(data)`` differ by one index."""
    scan = _scan_synthetic(
        "def f(auth, fd):\n"
        "    path = gdal_header_dir()\n"
        "    line = credential_header_line(build_credential_header(auth))\n"
        "    handle.write(line)\n"
        "    os.write(fd, line)\n"
    )
    assert scan.write_sites == 2
    assert not scan.unguarded_writes


def test_guard_a_write_outside_the_header_directory_is_not_judged() -> None:
    """The rule is scoped to the one directory, not to every write.

    Without the ``gdal_header_dir()`` condition this test's module would be a
    violation, and so would every unrelated file write in the backend.
    """
    scan = _scan_synthetic(
        "def f(token, fd):\n"
        '    os.write(fd, f"Authorization: Bearer {token}\\n".encode("ascii"))\n'
    )
    assert scan.write_sites == 0
    assert not scan.unguarded_writes

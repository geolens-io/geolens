"""No code under ``backend/app`` hands CRS text to PROJ outside the raster probe child.

PROJ may open files named in CRS text, and stored CRS text comes from uploaded
files, so it is parsed only in the bounded probe child. This finds every
reference to a PROJ text parser or a ``core.geo`` WKT helper, resolving names
through each module's imports so an alias, a module alias, a relative import
or a ``getattr`` with a literal name is still seen. The sites must match
``ALLOWED_SITES`` exactly, by count, and the probe functions holding one must
be reachable only from the child's ``main``.

Known limits: a parser that arrives with no import trace (a parameter, a dict
value, a factory's return), one imported with ``importlib`` or ``__import__``,
and one fetched by ``getattr`` with a computed name are not seen, nor is a
star import. ``rasterio.open`` and ``rasterio.warp`` read a file's or a CRS
object's CRS rather than text; ``test_rule2_structural.py`` covers the opens.
A local variable that shadows an imported name can raise a false alarm.
"""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"

_CRS_CLASS = "rasterio.crs.CRS"
_REEXPORTS = {"rasterio.CRS": _CRS_CLASS}
PARSERS = frozenset(
    {
        f"{_CRS_CLASS}.{name}"
        for name in (
            "from_wkt",
            "from_user_input",
            "from_string",
            "from_proj4",
            "from_dict",
        )
    }
    | {
        f"app.core.geo.{name}"
        for name in (
            "_parse_crs",
            "wkt_is_geographic",
            "wkt_has_degree_unit",
            "wkt_metres_per_unit",
            "wkt_crs_facts",
        )
    }
)
# Every use of these is a PROJ entry point, and app/ uses neither.
FORBIDDEN_ROOTS = ("pyproj", "osgeo.osr")

_WKT_HELPER = "a core.geo WKT helper, which only the allowed sites may reach"
# (module under app/, enclosing function, parser) -> (count, why it is safe)
ALLOWED_SITES: dict[tuple[str, str, str], tuple[int, str]] = {
    ("core/geo.py", "_parse_crs", f"{_CRS_CLASS}.from_wkt"): (
        1,
        "the one WKT parse, reached only through the helpers below",
    ),
    ("core/geo.py", "wkt_is_geographic", "app.core.geo._parse_crs"): (1, _WKT_HELPER),
    ("core/geo.py", "wkt_has_degree_unit", "app.core.geo._parse_crs"): (
        1,
        _WKT_HELPER,
    ),
    ("core/geo.py", "wkt_metres_per_unit", "app.core.geo._parse_crs"): (
        1,
        _WKT_HELPER,
    ),
    ("core/geo.py", "wkt_crs_facts", "app.core.geo._parse_crs"): (1, _WKT_HELPER),
    ("processing/raster/probe.py", "_metadata", "app.core.geo.wkt_crs_facts"): (
        1,
        "a probe child op",
    ),
    ("processing/raster/probe.py", "_crs_facts", "app.core.geo.wkt_crs_facts"): (
        1,
        "a probe child op",
    ),
    ("processing/raster/probe.py", "_crs_same", f"{_CRS_CLASS}.from_wkt"): (
        2,
        "a probe child op",
    ),
    (
        "modules/catalog/sources/cog_info.py",
        "_georeferencing",
        f"{_CRS_CLASS}.from_user_input",
    ): (1, "parses only the module's own CRS84 URI constant"),
}
# (module, function) -> the module-level string constant its parse must take.
CONSTANT_ARGUMENT = {
    ("modules/catalog/sources/cog_info.py", "_georeferencing"): "_CRS84_URI",
}

PROBE_MODULE = "processing/raster/probe.py"
CHILD_MAIN = "main"
CHILD_OPS = frozenset({"_inspect", "_metadata", "_crs_facts", "_crs_same"})


@dataclass(frozen=True)
class Ref:
    """A resolved name used in one function of one module."""

    module: str
    function: str
    name: str
    call: ast.Call | None


def _module_name(rel: str) -> str:
    parts = rel.removesuffix(".py").split("/")
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(["app", *parts])


def _import_base(node: ast.ImportFrom, rel: str) -> str:
    if not node.level:
        return node.module or ""
    package = _module_name(rel).split(".")
    if not rel.endswith("__init__.py"):
        package.pop()
    package = package[: len(package) - node.level + 1]
    return ".".join([*package, node.module] if node.module else package)


def _bindings(tree: ast.Module, rel: str) -> dict[str, set[str]]:
    """Every name the module binds to something importable, at any scope."""
    module = _module_name(rel)
    names: dict[str, set[str]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.setdefault(node.name, set()).add(f"{module}.{node.name}")
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.setdefault(target.id, set()).add(f"{module}.{target.id}")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    names.setdefault(alias.asname, set()).add(alias.name)
                else:
                    root = alias.name.split(".")[0]
                    names.setdefault(root, set()).add(root)
        elif isinstance(node, ast.ImportFrom):
            base = _import_base(node, rel)
            for alias in node.names:
                name = alias.asname or alias.name
                names.setdefault(name, set()).add(f"{base}.{alias.name}")
    return names


def _literal_getattr(node: ast.AST, names: dict[str, set[str]]) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and "getattr" not in names
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and isinstance(node.args[1].value, str)
    )


def _resolve(node: ast.AST, names: dict[str, set[str]]) -> set[str]:
    if isinstance(node, ast.Name):
        found = names.get(node.id, set())
    elif isinstance(node, ast.Attribute):
        found = {f"{base}.{node.attr}" for base in _resolve(node.value, names)}
    elif _literal_getattr(node, names):
        attr = node.args[1].value
        found = {f"{base}.{attr}" for base in _resolve(node.args[0], names)}
    else:
        return set()
    resolved = set()
    for name in found:
        for alias, real in _REEXPORTS.items():
            if name == alias or name.startswith(f"{alias}."):
                name = real + name[len(alias) :]
        resolved.add(name)
    return resolved


def scan(sources: dict[str, str]) -> list[Ref]:
    """Every outermost name reference that resolves, keyed by module and function."""
    refs: list[Ref] = []
    for rel, source in sources.items():
        tree = ast.parse(source)
        names = _bindings(tree, rel)
        inner: set[int] = set()
        calls: dict[int, ast.Call] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                inner.add(id(node.value))
            elif _literal_getattr(node, names):
                inner.add(id(node.args[0]))
            if isinstance(node, ast.Call):
                calls[id(node.func)] = node

        def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                scope = (*scope, node.name)
            candidate = (
                isinstance(node, (ast.Name, ast.Attribute))
                and isinstance(node.ctx, ast.Load)
            ) or _literal_getattr(node, names)
            if candidate and id(node) not in inner:
                for name in _resolve(node, names):
                    refs.append(
                        Ref(
                            rel,
                            ".".join(scope) or "<module>",
                            name,
                            calls.get(id(node)),
                        )
                    )
            for child in ast.iter_child_nodes(node):
                visit(child, scope)

        visit(tree, ())
    return refs


def parser_target(ref: Ref) -> str | None:
    """The parser a reference reaches, or None when it reaches none."""
    for parser in PARSERS:
        if ref.name == parser or ref.name.startswith(f"{parser}."):
            return parser
    if ref.call is not None and ref.name == _CRS_CLASS:
        return f"{_CRS_CLASS}()"
    for root in FORBIDDEN_ROOTS:
        if ref.name == root or ref.name.startswith(f"{root}."):
            return root
    return None


def parser_sites(refs: list[Ref]) -> Counter:
    return Counter(
        (ref.module, ref.function, target)
        for ref in refs
        if (target := parser_target(ref)) is not None
    )


def constant_argument_violations(sources: dict[str, str], refs: list[Ref]) -> list[str]:
    """Pinned sites whose parse takes anything but their module's string constant."""
    violations = []
    for (module, function), constant in CONSTANT_ARGUMENT.items():
        tree = ast.parse(sources[module])
        literal = any(
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == constant for t in node.targets)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            for node in tree.body
        )
        for ref in refs:
            if (ref.module, ref.function) != (module, function):
                continue
            if parser_target(ref) is None:
                continue
            call = ref.call
            takes_constant = (
                literal
                and call is not None
                and not call.keywords
                and len(call.args) == 1
                and isinstance(call.args[0], ast.Name)
                and call.args[0].id == constant
            )
            if not takes_constant:
                violations.append(
                    f"{module}:{function} parses something besides {constant}"
                )
    return violations


def child_op_violations(refs: list[Ref]) -> list[str]:
    """References to a probe child op from outside the child's own functions."""
    ops = {f"app.processing.raster.probe.{op}" for op in CHILD_OPS}
    allowed = {CHILD_MAIN, *CHILD_OPS}
    return [
        f"{ref.module}:{ref.function} reaches {ref.name}"
        for ref in refs
        if ref.name in ops
        and (ref.module != PROBE_MODULE or ref.function.split(".")[0] not in allowed)
    ]


@pytest.fixture(scope="module")
def app_sources() -> dict[str, str]:
    return {
        path.relative_to(APP_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(APP_ROOT.rglob("*.py"))
    }


@pytest.fixture(scope="module")
def app_refs(app_sources) -> list[Ref]:
    return scan(app_sources)


def test_every_crs_text_parse_is_an_allowed_site(app_refs):
    found = parser_sites(app_refs)
    expected = Counter({site: count for site, (count, _) in ALLOWED_SITES.items()})

    assert found == expected, (
        f"not allowed: {dict(found - expected)}; missing: {dict(expected - found)}"
    )


def test_the_pinned_site_parses_only_its_constant(app_sources, app_refs):
    assert constant_argument_violations(app_sources, app_refs) == []


def test_probe_child_ops_are_reached_only_from_the_childs_main(app_refs):
    assert child_op_violations(app_refs) == []
    assert {
        function for module, function, _ in ALLOWED_SITES if module == PROBE_MODULE
    } <= CHILD_OPS


# Rejected twins: each is a parse the scan must see.
@pytest.mark.parametrize(
    ("module", "source", "scope", "target"),
    [
        (
            "modules/x.py",
            "from rasterio.crs import CRS as C\ndef f(t):\n    return C.from_wkt(t)\n",
            "f",
            f"{_CRS_CLASS}.from_wkt",
        ),
        (
            "modules/x.py",
            "import rasterio.crs as rc\ndef f(t):\n    return rc.CRS.from_wkt(t)\n",
            "f",
            f"{_CRS_CLASS}.from_wkt",
        ),
        (
            "modules/x.py",
            "import rasterio\ndef f(t):\n    return rasterio.CRS.from_user_input(t)\n",
            "f",
            f"{_CRS_CLASS}.from_user_input",
        ),
        (
            "modules/x.py",
            "import rasterio.crs\ndef f(t):\n    return rasterio.crs.CRS.from_string(t)\n",
            "f",
            f"{_CRS_CLASS}.from_string",
        ),
        (
            "modules/x.py",
            "from rasterio.crs import CRS\nparse = CRS.from_wkt\n",
            "<module>",
            f"{_CRS_CLASS}.from_wkt",
        ),
        (
            "modules/x.py",
            "from rasterio.crs import CRS\ndef f(t):\n    return CRS.from_wkt.__call__(t)\n",
            "f",
            f"{_CRS_CLASS}.from_wkt",
        ),
        (
            "modules/x.py",
            'from rasterio.crs import CRS\ndef f(t):\n    return getattr(CRS, "from_wkt")(t)\n',
            "f",
            f"{_CRS_CLASS}.from_wkt",
        ),
        (
            "modules/x.py",
            "from rasterio.crs import CRS\ndef f(t):\n    return CRS(t)\n",
            "f",
            f"{_CRS_CLASS}()",
        ),
        (
            "modules/x.py",
            "from app.core.geo import wkt_is_geographic as g\ndef f(t):\n    return g(t)\n",
            "f",
            "app.core.geo.wkt_is_geographic",
        ),
        (
            "modules/x.py",
            "from app.core import geo\ndef f(t):\n    return geo.wkt_has_degree_unit(t)\n",
            "f",
            "app.core.geo.wkt_has_degree_unit",
        ),
        (
            "core/other.py",
            "from .geo import _parse_crs\ndef f(t):\n    return _parse_crs(t)\n",
            "f",
            "app.core.geo._parse_crs",
        ),
        (
            "modules/x.py",
            "import pyproj\ndef f(t):\n    return pyproj.CRS(t)\n",
            "f",
            "pyproj",
        ),
        (
            "modules/x.py",
            "from osgeo import osr\ndef f(t):\n    osr.SpatialReference().ImportFromWkt(t)\n",
            "f",
            "osgeo.osr",
        ),
    ],
)
def test_the_scan_sees_each_way_of_reaching_a_parser(module, source, scope, target):
    assert parser_sites(scan({module: source})) == Counter({(module, scope, target): 1})


# Accepted twins: none of these parses CRS text.
@pytest.mark.parametrize(
    "source",
    [
        "from rasterio.crs import CRS\ndef f():\n    return CRS.from_epsg(4326)\n",
        "def from_wkt(t):\n    return t\ndef f(t):\n    return from_wkt(t)\n",
        'def f():\n    return "from_wkt"\n',
        "from shapely import wkt\ndef f(t):\n    return wkt.loads(t)\n",
        "import re\ndef f(t):\n    return re.findall(r'VERT_?CRS', t)\n",
    ],
)
def test_the_scan_ignores_what_is_not_a_crs_text_parse(source):
    assert parser_sites(scan({"modules/x.py": source})) == Counter()


_COG_INFO = "modules/catalog/sources/cog_info.py"


@pytest.mark.parametrize(
    ("constant", "argument", "violations"),
    [
        ('"http://www.opengis.net/def/crs/OGC/0/CRS84"', "_CRS84_URI", 0),
        ('"http://www.opengis.net/def/crs/OGC/0/CRS84"', "crs_value", 1),
        ("_uri()", "_CRS84_URI", 1),
    ],
)
def test_the_pinned_site_rejects_anything_but_a_literal_constant(
    constant, argument, violations
):
    source = (
        "from rasterio.crs import CRS\n"
        f"_CRS84_URI = {constant}\n"
        "def _georeferencing(crs_value):\n"
        f"    return CRS.from_user_input({argument})\n"
    )
    sources = {_COG_INFO: source}

    assert len(constant_argument_violations(sources, scan(sources))) == violations


@pytest.mark.parametrize(
    ("module", "function", "violations"),
    [
        (PROBE_MODULE, "main", 0),
        (PROBE_MODULE, "_inspect", 0),
        ("modules/x.py", "main", 1),
    ],
)
def test_a_child_op_reached_from_outside_the_child_is_rejected(
    module, function, violations
):
    source = (
        "from app.processing.raster.probe import _metadata\n"
        f"def {function}(path):\n"
        "    return _metadata(path)\n"
    )

    assert len(child_op_violations(scan({module: source}))) == violations

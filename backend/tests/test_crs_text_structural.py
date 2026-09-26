"""No code under ``backend/app`` hands CRS text to PROJ outside the raster probe child.

PROJ may open files named in CRS text, so stored and uploaded CRS text is read
only in the bounded probe child. Each rule is exact both ways, by count:

- every PROJ text parser or ``core.geo`` WKT helper is at an ``ALLOWED_SITES`` entry;
- every ``rasterio`` import and reference is in a ``RASTERIO_SITES`` function,
  none at module level so nothing re-exports it, and a site outside the child
  uses exactly its ``RASTERIO_NAMES``;
- ``CHILD_FUNCTIONS`` are reached only from each other, and the child's ``main``
  only from its ``__main__`` guard;
- ``cog._wgs84_bbox``, which hands its CRS to ``transform_bounds``, is called
  only from ``WGS84_BBOX_CALLERS``;
- nothing imports or uses ``pyproj`` or ``osgeo``.

What the scan can't see is listed on :func:`scan`.
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
FORBIDDEN_ROOTS = ("pyproj", "osgeo")
_IMPORT_ROOTS = ("rasterio", *FORBIDDEN_ROOTS)

PROBE = "processing/raster/probe.py"
COG = "processing/raster/cog.py"
QUICKLOOK = "processing/raster/quicklook.py"
VRT = "processing/raster/vrt.py"
COG_INFO = "modules/catalog/sources/cog_info.py"
_CHILD = "runs only in the probe child"
_WKT_HELPER = "a core.geo WKT helper; only these sites may reach it"

# (module under app/, enclosing function, parser) -> (count, why it is safe)
ALLOWED_SITES: dict[tuple[str, str, str], tuple[int, str]] = {
    ("core/geo.py", "_parse_crs", f"{_CRS_CLASS}.from_wkt"): (1, "the one WKT parse"),
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
    (PROBE, "_metadata", "app.core.geo.wkt_crs_facts"): (1, _CHILD),
    (PROBE, "_crs_facts", "app.core.geo.wkt_crs_facts"): (1, _CHILD),
    (PROBE, "_crs_facts_many", "app.core.geo.wkt_crs_facts"): (1, _CHILD),
    (PROBE, "_crs_same", f"{_CRS_CLASS}.from_wkt"): (1, _CHILD),
    (COG_INFO, "_georeferencing", f"{_CRS_CLASS}.from_user_input"): (
        1,
        "parses only the module's own CRS84 URI constant",
    ),
}
# (module, function) -> the module-level string constant its parse must take.
CONSTANT_ARGUMENT = {(COG_INFO, "_georeferencing"): "_CRS84_URI"}

# (module under app/, enclosing function) -> (rasterio imports and references,
# why it is safe)
RASTERIO_SITES: dict[tuple[str, str], tuple[int, str]] = {
    ("core/geo.py", "_parse_crs"): (2, "reached only from ALLOWED_SITES"),
    ("core/geo.py", "_proj_knows_epsg"): (2, "from_epsg on an integer code"),
    ("core/geo.py", "crs_facts_for_epsg"): (
        4,
        "from_epsg on a validated integer code, which reads only the PROJ database",
    ),
    (COG_INFO, "_georeferencing"): (3, "from_epsg on a code, the pinned CRS84 parse"),
    (PROBE, "_crs_same"): (4, _CHILD),
    (PROBE, "_category"): (8, _CHILD),
    (COG, "extract_raster_metadata"): (2, _CHILD),
    (COG, "check_cog_compliance"): (2, _CHILD),
    (COG, "_predictor_supported"): (2, _CHILD),
    (COG, "_wgs84_bbox"): (3, "transforms the CRS of a WGS84_BBOX_CALLERS caller"),
    (QUICKLOOK, "generate_quicklook"): (4, _CHILD),
    (VRT, "gdal_safe_open_env"): (2, _CHILD),
}
_FROM_EPSG = f"{_CRS_CLASS}.from_epsg"
# RASTERIO_SITES outside the child -> the rasterio names it uses, by count, so
# swapping one for another that takes text fails even at the same count.
RASTERIO_NAMES: dict[tuple[str, str], dict[str, int]] = {
    ("core/geo.py", "_parse_crs"): {"rasterio.crs": 1, f"{_CRS_CLASS}.from_wkt": 1},
    ("core/geo.py", "_proj_knows_epsg"): {"rasterio.crs": 1, _FROM_EPSG: 1},
    ("core/geo.py", "crs_facts_for_epsg"): {
        "rasterio.crs": 1,
        "rasterio.errors": 1,
        _FROM_EPSG: 1,
        "rasterio.errors.CRSError": 1,
    },
    (COG_INFO, "_georeferencing"): {
        "rasterio.crs": 1,
        _FROM_EPSG: 1,
        f"{_CRS_CLASS}.from_user_input": 1,
    },
    (COG, "_wgs84_bbox"): {
        "rasterio.warp": 1,
        "rasterio.warp.transform": 1,
        "rasterio.warp.transform_bounds": 1,
    },
}

CHILD_MAIN = (PROBE, "main")
CHILD_FUNCTIONS = frozenset(
    {
        CHILD_MAIN,
        *(
            (PROBE, name)
            for name in (
                "_inspect",
                "_metadata",
                "_quicklook",
                "_crs_facts",
                "_crs_facts_many",
                "_crs_same",
                "_category",
            )
        ),
        *(
            (COG, name)
            for name in (
                "extract_raster_metadata",
                "check_cog_compliance",
                "_predictor_supported",
            )
        ),
        (QUICKLOOK, "generate_quicklook"),
        (VRT, "gdal_safe_open_env"),
    }
)
_MAIN_GUARD = "__main__"

WGS84_BBOX = (COG, "_wgs84_bbox")
# (module under app/, enclosing function) -> (references, why its CRS isn't text)
WGS84_BBOX_CALLERS: dict[tuple[str, str], tuple[int, str]] = {
    (COG, "extract_raster_metadata"): (1, _CHILD),
}


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


def _imported(node: ast.Import | ast.ImportFrom, rel: str) -> list[str]:
    """The rasterio, pyproj or osgeo modules an import statement loads."""
    if isinstance(node, ast.Import):
        modules = [alias.name for alias in node.names]
    else:
        modules = [_import_base(node, rel)]
    return [m for m in modules if any(_under(m, root) for root in _IMPORT_ROOTS)]


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


def _is_main_guard(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
        and len(node.test.comparators) == 1
        and isinstance(node.test.comparators[0], ast.Constant)
        and node.test.comparators[0].value == "__main__"
    )


def scan(sources: dict[str, str]) -> list[Ref]:
    """Every outermost name reference that resolves, and every import of an
    ``_IMPORT_ROOTS`` module, keyed by module and function.

    Names resolve through each module's imports, so aliases, module aliases,
    relative imports and ``getattr`` with a literal name are seen. Module-level
    code inside ``if __name__ == "__main__":`` is keyed ``__main__``.

    Not seen: a parser with no import trace (a parameter, a dict value, a
    factory's return, ``importlib``, ``__import__``), a computed ``getattr``
    name, a star import from an app module, ``runpy`` running the probe module
    in this process, and text standing in for a CRS object inside an allowed
    function (``crs == text``, or text handed to ``_wgs84_bbox``). A local
    variable that shadows an imported name can raise a false alarm.
    """
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
            elif not scope and _is_main_guard(node):
                scope = (_MAIN_GUARD,)
            function = ".".join(scope) or "<module>"
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                refs.extend(
                    Ref(rel, function, name, None) for name in _imported(node, rel)
                )
            candidate = (
                isinstance(node, (ast.Name, ast.Attribute))
                and isinstance(node.ctx, ast.Load)
            ) or _literal_getattr(node, names)
            if candidate and id(node) not in inner:
                for name in _resolve(node, names):
                    refs.append(Ref(rel, function, name, calls.get(id(node))))
            for child in ast.iter_child_nodes(node):
                visit(child, scope)

        visit(tree, ())
    return refs


def _under(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(f"{prefix}.")


def parser_target(ref: Ref) -> str | None:
    """The parser or forbidden library a reference reaches, or None."""
    for parser in PARSERS:
        if _under(ref.name, parser):
            return parser
    if ref.call is not None and ref.name == _CRS_CLASS:
        return f"{_CRS_CLASS}()"
    for root in FORBIDDEN_ROOTS:
        if _under(ref.name, root):
            return root
    return None


def parser_sites(refs: list[Ref]) -> Counter:
    return Counter(
        (ref.module, ref.function, target)
        for ref in refs
        if (target := parser_target(ref)) is not None
    )


def rasterio_sites(refs: list[Ref]) -> Counter:
    return Counter(
        (ref.module, ref.function) for ref in refs if _under(ref.name, "rasterio")
    )


def rasterio_name_differences(refs: list[Ref]) -> dict[tuple[str, str], str]:
    """``RASTERIO_NAMES`` sites whose rasterio names differ from their pins."""
    differences = {}
    for site, pinned in RASTERIO_NAMES.items():
        found = Counter(
            ref.name
            for ref in refs
            if (ref.module, ref.function) == site and _under(ref.name, "rasterio")
        )
        if found != Counter(pinned):
            differences[site] = _differences(found, Counter(pinned))
    return differences


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


def child_reach_violations(refs: list[Ref]) -> list[str]:
    """References to a child function from anywhere the child doesn't run."""
    dotted = {
        f"{_module_name(module)}.{function}": (module, function)
        for module, function in CHILD_FUNCTIONS
    }
    violations = []
    for ref in refs:
        target = next(
            (site for name, site in dotted.items() if _under(ref.name, name)), None
        )
        if target is None:
            continue
        caller = (ref.module, ref.function.split(".")[0])
        if target == CHILD_MAIN:
            allowed = caller == (PROBE, _MAIN_GUARD)
        else:
            allowed = caller in CHILD_FUNCTIONS
        if not allowed:
            violations.append(f"{ref.module}:{ref.function} reaches {ref.name}")
    return violations


def bbox_caller_differences(refs: list[Ref]) -> tuple[dict, dict]:
    """Callers of ``_wgs84_bbox`` that aren't pinned, and pins it lacks, by count."""
    name = f"{_module_name(WGS84_BBOX[0])}.{WGS84_BBOX[1]}"
    found = Counter(
        (ref.module, ref.function.split(".")[0])
        for ref in refs
        if _under(ref.name, name)
    )
    expected = Counter({site: count for site, (count, _) in WGS84_BBOX_CALLERS.items()})
    return dict(found - expected), dict(expected - found)


@pytest.fixture(scope="module")
def app_sources() -> dict[str, str]:
    return {
        path.relative_to(APP_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(APP_ROOT.rglob("*.py"))
    }


@pytest.fixture(scope="module")
def app_refs(app_sources) -> list[Ref]:
    return scan(app_sources)


def _differences(found: Counter, expected: Counter) -> str:
    return f"not allowed: {dict(found - expected)}; missing: {dict(expected - found)}"


def test_every_crs_text_parse_is_an_allowed_site(app_refs):
    found = parser_sites(app_refs)
    expected = Counter({site: count for site, (count, _) in ALLOWED_SITES.items()})

    assert found == expected, _differences(found, expected)


def test_the_pinned_site_parses_only_its_constant(app_sources, app_refs):
    assert constant_argument_violations(app_sources, app_refs) == []


def test_every_rasterio_reference_is_in_an_allowed_function(app_refs):
    found = rasterio_sites(app_refs)
    expected = Counter({site: count for site, (count, _) in RASTERIO_SITES.items()})

    assert found == expected, _differences(found, expected)


def test_rasterio_sites_outside_the_child_use_only_their_pinned_names(app_refs):
    assert rasterio_name_differences(app_refs) == {}


def test_every_rasterio_site_outside_the_child_pins_its_names():
    assert set(RASTERIO_NAMES) == set(RASTERIO_SITES) - CHILD_FUNCTIONS
    for site, names in RASTERIO_NAMES.items():
        assert sum(names.values()) == RASTERIO_SITES[site][0], site


def test_no_rasterio_site_is_module_level():
    assert [site for site in RASTERIO_SITES if site[1] == "<module>"] == []


def test_child_functions_are_reached_only_from_the_child(app_refs):
    assert child_reach_violations(app_refs) == []


def test_the_bbox_transform_is_called_only_by_its_pinned_callers(app_refs):
    assert bbox_caller_differences(app_refs) == ({}, {})


def test_every_site_said_to_run_in_the_child_is_a_child_function():
    said = {(m, f) for (m, f, _), (_, why) in ALLOWED_SITES.items() if why == _CHILD}
    said |= {site for site, (_, why) in RASTERIO_SITES.items() if why == _CHILD}
    said |= {site for site, (_, why) in WGS84_BBOX_CALLERS.items() if why == _CHILD}

    assert said <= CHILD_FUNCTIONS


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
    ],
)
def test_the_scan_sees_each_way_of_reaching_a_parser(module, source, scope, target):
    assert parser_sites(scan({module: source})) == Counter({(module, scope, target): 1})


# Rejected twins: pyproj and osgeo, imported or used.
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "import pyproj\ndef f(t):\n    return pyproj.CRS(t)\n",
            {("<module>", "pyproj"): 1, ("f", "pyproj"): 1},
        ),
        (
            "from osgeo import osr\ndef f(t):\n    osr.SpatialReference().ImportFromWkt(t)\n",
            {("<module>", "osgeo"): 1, ("f", "osgeo"): 1},
        ),
        (
            "from osgeo import gdal\ndef f(path):\n    return gdal.Open(path)\n",
            {("<module>", "osgeo"): 1, ("f", "osgeo"): 1},
        ),
        ("from osgeo import osr\n", {("<module>", "osgeo"): 1}),
    ],
    ids=["pyproj", "osr", "gdal", "import-alone"],
)
def test_the_scan_sees_pyproj_and_osgeo_imported_or_used(source, expected):
    found = parser_sites(scan({"modules/x.py": source}))

    assert found == Counter(
        {("modules/x.py", scope, target): n for (scope, target), n in expected.items()}
    )


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


# Rejected twins: rasterio outside an allowed function, however it is reached.
@pytest.mark.parametrize(
    "source",
    [
        "from rasterio.warp import transform_bounds\ndef f(a):\n"
        "    return transform_bounds(a.crs_wkt, 'EPSG:4326', 0, 0, 1, 1)\n",
        "import rasterio\nfrom app.processing.raster.vrt import gdal_safe_open_env\n"
        "def f(path):\n    with gdal_safe_open_env():\n        return rasterio.open(path)\n",
        "from rasterio.crs import CRS\ndef f(a):\n"
        "    return CRS.from_epsg(4326) == a.crs_wkt\n",
        "from rasterio.crs import CRS\ndef f(code):\n    return CRS.from_epsg(code)\n",
    ],
    ids=[
        "warp-on-stored-text",
        "open-under-the-safe-env",
        "compare-with-text",
        "from-epsg-outside-its-helper",
    ],
)
def test_rasterio_outside_an_allowed_function_is_seen(source):
    assert rasterio_sites(scan({"modules/x.py": source})) == Counter(
        {("modules/x.py", "<module>"): 1, ("modules/x.py", "f"): 1}
    )


def test_a_module_that_could_re_export_rasterio_is_seen():
    sources = {
        "core/x.py": "import rasterio\n",
        "modules/y.py": "from app.core.x import rasterio as r\n"
        "def f(path):\n    return r.open(path)\n",
    }

    assert rasterio_sites(scan(sources)) == Counter({("core/x.py", "<module>"): 1})


@pytest.mark.parametrize(
    ("body", "differs"),
    [
        ("    from rasterio.crs import CRS\n    return CRS.from_epsg(epsg)\n", False),
        (
            "    from rasterio.warp import transform_bounds\n"
            "    return transform_bounds(epsg, 'EPSG:4326', 0, 0, 1, 1)\n",
            True,
        ),
        ("    from rasterio.crs import CRS\n    return CRS.from_string(epsg)\n", True),
    ],
    ids=["from-epsg", "a-transform-that-takes-text", "a-text-parser"],
)
def test_a_same_count_swap_at_a_pinned_site_is_seen(body, differs):
    site = ("core/geo.py", "_proj_knows_epsg")
    refs = scan({site[0]: f"def {site[1]}(epsg):\n{body}"})

    assert (site in rasterio_name_differences(refs)) is differs


@pytest.mark.parametrize(
    ("module", "source", "violations"),
    [
        (
            "modules/x.py",
            "from app.processing.raster.cog import extract_raster_metadata\n"
            "def f(path):\n    return extract_raster_metadata(path)\n",
            1,
        ),
        (
            "modules/x.py",
            "from app.processing.raster.probe import main\n"
            "def f():\n    return main(['crs-facts'])\n",
            1,
        ),
        (
            PROBE,
            "def main(argv):\n    return 0\nmain([])\n",
            1,
        ),
        (
            PROBE,
            "import sys\ndef main(argv):\n    return 0\n"
            "if __name__ == '__main__':\n    sys.exit(main(sys.argv[1:]))\n",
            0,
        ),
        (
            PROBE,
            "from app.processing.raster.cog import extract_raster_metadata\n"
            "def _metadata(path):\n    return extract_raster_metadata(path)\n",
            0,
        ),
    ],
    ids=[
        "cog-read-from-a-handler",
        "main-from-a-handler",
        "main-outside-its-guard",
        "main-in-its-guard",
        "cog-read-from-a-child-op",
    ],
)
def test_a_child_function_reached_from_outside_the_child_is_rejected(
    module, source, violations
):
    assert len(child_reach_violations(scan({module: source}))) == violations


@pytest.mark.parametrize(
    ("module", "function", "expected"),
    [
        ("modules/x.py", "f", {("modules/x.py", "f"): 1}),
        (COG, "extract_raster_metadata", {}),
    ],
    ids=["a-handler-with-stored-text", "the-childs-metadata-read"],
)
def test_the_bbox_transform_rejects_a_caller_it_does_not_pin(
    module, function, expected
):
    source = (
        "from types import SimpleNamespace\n"
        "from app.processing.raster.cog import _wgs84_bbox\n"
        f"def {function}(asset, bounds):\n"
        "    return _wgs84_bbox(SimpleNamespace(crs=asset.crs_wkt, bounds=bounds))\n"
    )

    unpinned, _ = bbox_caller_differences(scan({module: source}))

    assert unpinned == expected


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
    sources = {COG_INFO: source}

    assert len(constant_argument_violations(sources, scan(sources))) == violations

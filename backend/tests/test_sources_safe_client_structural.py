"""Rule-2 httpx guard for ``modules/catalog/sources/``, the package that fetches
user-supplied URLs for a living.

AGENTS.md Rule 2 says every ``httpx`` client that follows redirects must come
from ``make_safe_client()``. Two things enforce that today and neither covers
this package's real risk:

* the ``ssrf-safe-client`` pre-commit hook fires only on a file that contains
  BOTH ``httpx.AsyncClient(`` and the literal ``follow_redirects=True``. A
  module that constructs a bare client and never writes that literal, or one
  that calls ``httpx.post(...)`` (which follows no redirects but also gets no
  IP pinning, no per-hop revalidation and no connect-time re-resolution), is
  invisible to it;
* ``test_rule2_structural.py`` walks the GDAL and rasterio half only.

So a bare ``httpx.post(...)`` next to the ArcGIS sign-in would trip nothing
that exists. This module closes that, in the spirit of
``test_rule1_structural.py`` (#822) and its rasterio sibling (#936): walk every
module under ``backend/app/modules/catalog/sources/`` as an AST and assert one
property.

**THE INVARIANT: in this package, every outbound httpx call comes from a
client this repository built, and every exception is named with a count.**

A call is recognizable when its head resolves, through the bindings this
resolver follows, to an ``httpx`` client constructor or to one of httpx's
module-level request helpers. Bindings followed: ``import httpx [as X]``,
``from httpx import AsyncClient/Client [as Y]``, and module-level aliases
assigned from either (``AC = httpx.AsyncClient``, ``hx = httpx``). A
``from httpx import *`` is a violation on sight, because it defeats the
resolver rather than being resolved by it.

What this does NOT claim, stated plainly: a client that arrives as a
parameter, comes out of a dict or is returned by a factory in another module
carries no lexical trace here, and no AST rule can recognize it. That is the
same provenance boundary the rasterio guard documents. It is covered from the
other side: every caller in this package that takes a ``client`` parameter is
handed one by a function in this package, and those constructions are exactly
what this test enumerates.

The allowlist is asserted EXACT in both directions and by count, so an entry
whose site disappears (or becomes safe) fails loudly instead of going stale,
and a second unguarded construction added to an already-justified function
fails instead of riding the entry.
"""

import ast
from pathlib import Path

import pytest

SOURCES_ROOT = (
    Path(__file__).resolve().parents[1] / "app" / "modules" / "catalog" / "sources"
)
APP_ROOT = Path(__file__).resolve().parents[1]

# httpx names that OPEN a connection pool of their own.
_CLIENT_CONSTRUCTORS = frozenset({"AsyncClient", "Client"})

# httpx's module-level one-shot helpers. Each builds a throwaway client
# internally, so none of them can be given the guard transport.
_REQUEST_HELPERS = frozenset(
    {
        "request",
        "stream",
        "get",
        "options",
        "head",
        "post",
        "put",
        "patch",
        "delete",
    }
)

# (module path relative to backend/, enclosing function, exact call count,
# justification). Keep this list short and each entry argued.
_ALLOWLIST: dict[tuple[str, str], tuple[int, str]] = {
    ("app/modules/catalog/sources/cog_info.py", "fetch_cog_info"): (
        1,
        "Fetches the INTERNAL Titiler service by a URL this repository builds "
        "(build_titiler_cog_url), never a caller-supplied one. The caller's "
        "URL travels as a query VALUE and is gated twice before it gets here: "
        "validate_url_for_ssrf at every call site, and Titiler's own "
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS clamp. The function's own docstring "
        "carries both gates.",
    ),
}


def _iter_modules() -> list[Path]:
    return sorted(path for path in SOURCES_ROOT.rglob("*.py"))


def _rel(path: Path) -> str:
    return str(path.relative_to(APP_ROOT.parent / "backend"))


class _Visitor(ast.NodeVisitor):
    """Resolves httpx bindings per module and records every recognizable call."""

    def __init__(self) -> None:
        self.module_aliases: set[str] = set()
        self.constructor_aliases: set[str] = set()
        self.star_imports: list[int] = []
        self.findings: list[tuple[str, str, int]] = []
        self._scope: list[str] = []

    # -- binding resolution -------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "httpx" or alias.name.startswith("httpx."):
                self.module_aliases.add(alias.asname or alias.name.split(".")[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "httpx":
            for alias in node.names:
                if alias.name == "*":
                    self.star_imports.append(node.lineno)
                elif alias.name in _CLIENT_CONSTRUCTORS:
                    self.constructor_aliases.add(alias.asname or alias.name)
                elif alias.name in _REQUEST_HELPERS:
                    self.constructor_aliases.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        # `AC = httpx.AsyncClient`, `hx = httpx`, and chains of either.
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            value = node.value
            if isinstance(value, ast.Name):
                if value.id in self.module_aliases:
                    self.module_aliases.add(target.id)
                elif value.id in self.constructor_aliases:
                    self.constructor_aliases.add(target.id)
            elif (
                isinstance(value, ast.Attribute)
                and isinstance(value.value, ast.Name)
                and value.value.id in self.module_aliases
                and (
                    value.attr in _CLIENT_CONSTRUCTORS or value.attr in _REQUEST_HELPERS
                )
            ):
                self.constructor_aliases.add(target.id)
        self.generic_visit(node)

    # -- scope tracking -----------------------------------------------------

    def _enter(self, node) -> None:
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._enter(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter(node)

    # -- the calls themselves -----------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        head = node.func
        symbol: str | None = None
        if isinstance(head, ast.Name) and head.id in self.constructor_aliases:
            symbol = head.id
        elif isinstance(head, ast.Attribute) and isinstance(head.value, ast.Name):
            if head.value.id in self.module_aliases and (
                head.attr in _CLIENT_CONSTRUCTORS or head.attr in _REQUEST_HELPERS
            ):
                symbol = f"{head.value.id}.{head.attr}"
        if symbol is not None:
            enclosing = self._scope[-1] if self._scope else "<module>"
            self.findings.append((enclosing, symbol, node.lineno))
        self.generic_visit(node)


def _scan() -> tuple[dict[tuple[str, str], list[tuple[str, int]]], list[str]]:
    """Return findings keyed by (module, function) plus any star-import errors."""
    findings: dict[tuple[str, str], list[tuple[str, int]]] = {}
    errors: list[str] = []
    for path in _iter_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        visitor = _Visitor()
        visitor.visit(tree)
        for lineno in visitor.star_imports:
            errors.append(
                f"{_rel(path)}:{lineno} `from httpx import *` defeats the "
                "binding resolver; import the names you use."
            )
        for enclosing, symbol, lineno in visitor.findings:
            findings.setdefault((_rel(path), enclosing), []).append((symbol, lineno))
    return findings, errors


def test_the_package_being_scanned_is_actually_there():
    """Positive control. A resolver that scans nothing passes everything."""
    modules = _iter_modules()
    assert len(modules) >= 10, modules
    assert any(path.name == "arcgis_signin.py" for path in modules)
    assert any(path.parent.name == "adapters" for path in modules)


def test_the_resolver_recognizes_a_direct_httpx_call():
    """Second positive control, on the resolver rather than on the corpus.

    Every assertion below is an ABSENCE claim, and an absence claim from a
    resolver nobody has shown to resolve anything is worth nothing.
    """
    tree = ast.parse(
        "import httpx as hx\n"
        "from httpx import AsyncClient as AC\n"
        "Alias = hx.AsyncClient\n"
        "def outer():\n"
        "    hx.post('https://example.test')\n"
        "    AC(follow_redirects=True)\n"
        "    Alias()\n"
        "    hx.Timeout(1.0)\n"
    )
    visitor = _Visitor()
    visitor.visit(tree)
    assert [(scope, symbol) for scope, symbol, _line in visitor.findings] == [
        ("outer", "hx.post"),
        ("outer", "AC"),
        ("outer", "Alias"),
    ]


def test_no_star_import_hides_an_httpx_binding():
    _findings, errors = _scan()
    assert errors == []


def test_every_httpx_client_in_sources_comes_from_make_safe_client():
    findings, _errors = _scan()
    unexpected = {
        key: sites for key, sites in findings.items() if key not in _ALLOWLIST
    }
    assert not unexpected, (
        "Outbound httpx in modules/catalog/sources/ must come from "
        "make_safe_client() in app/platform/security.py, which pins the "
        "validated IP, re-resolves per redirect hop and re-runs "
        "validate_url_for_ssrf on every Location. Unguarded call sites:\n"
        + "\n".join(
            f"  {module}:{line} in {func}() -> {symbol}"
            for (module, func), sites in sorted(unexpected.items())
            for symbol, line in sites
        )
    )


@pytest.mark.parametrize("key", sorted(_ALLOWLIST))
def test_each_allowlisted_site_still_exists_with_its_exact_count(key):
    findings, _errors = _scan()
    expected_count, justification = _ALLOWLIST[key]
    assert justification.strip(), f"{key} needs a justification, not an empty string"
    sites = findings.get(key)
    assert sites is not None, (
        f"{key[0]}:{key[1]}() no longer makes a direct httpx call. Delete the "
        "allowlist entry rather than leaving it to rot."
    )
    assert len(sites) == expected_count, (
        f"{key[0]}:{key[1]}() makes {len(sites)} direct httpx calls, and the "
        f"allowlist justifies {expected_count}. A second unguarded call does "
        "not inherit the first one's argument."
    )

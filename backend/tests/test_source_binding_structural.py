"""Only ``platform/dataset_origin.py`` writes a dataset's origin pointer.

``origin_uri`` and ``origin_ref`` change only through ``set_dataset_origin`` and
``set_postgis_origin``, which run ``build_origin_ref``'s allowlist (ADR-002
invariant 4) and clear the stored probe verdict. This walks every module under
``backend/app/`` and fails on any other write it can see:

- ORM attributes: assignment, ``del``, item writes, ``|=`` and mutating methods
  on the stored dict (reached as ``x.origin_ref``, ``getattr(x, "origin_ref")``
  or an alias of either, bound by assignment, annotation, walrus, unpacking,
  ``for``, ``with`` or another alias, in this scope or any enclosing one: a
  nested function or lambda, ``nonlocal``/``global``, a module-level alias, or
  a class attribute read as ``Class.attr``, ``self.attr`` or ``cls.attr``; and
  through ``dict.update`` or ``operator.setitem``), ``setattr``/``set_attribute``/``set_committed_value``/
  ``__setattr__`` by name, and ``__dict__``/``vars()`` items.
- The model's constructor (under any alias), with the columns as keywords or as
  keys of a ``**`` mapping.
- SQLAlchemy statements: ``update``/``insert`` reached through any name the
  module binds to SQLAlchemy (``import sqlalchemy as X``, a submodule, a
  ``from sqlalchemy... import`` alias, a local name or ``partial`` bound to a
  builder) or a table's own ``update()``/``insert()``, and the methods that name
  written columns (``values``, ``ordered_values``, ``on_conflict_do_update``,
  ``on_duplicate_key_update``, ``from_select``), the legacy ``Query.update()``,
  ``bulk_*_mappings`` and ``execute()`` parameters. Columns count as keywords,
  ``dict(...)`` keywords, string keys, model or ``table.c`` attribute and item
  keys, ``column()``/``literal_column()`` keys and ``(column, value)`` pairs; a
  mapping passed by local name is followed to the keys it gets in the same
  function.
- Raw SQL, including f-strings and ``+`` concatenations of literals: a ``SET``
  of the columns in any statement (``UPDATE``, ``ON CONFLICT DO UPDATE``,
  ``MERGE``), a column list naming them (``INSERT INTO``, ``MERGE``'s
  ``INSERT``, ``COPY ... FROM``), and a positional ``INSERT``, ``MERGE`` insert
  or ``COPY`` into ``datasets``, whatever its quoting, schema, alias or ``ONLY``.
- Bulk loaders (``copy_records_to_table``, ``copy_to_table``, ``to_sql``) into
  ``datasets``, or with a column list naming the columns.

Inside the owner module, each write is counted by the function it sits in, so
a second write site, or a write outside the setter, fails too.

Behind those rules sits a backstop over every module, the owner included: any
name for a column fails unless ``NAME_ALLOWLIST`` records its site (file and
dotted path of enclosing classes and functions) and how many mentions the site
has. A name is a string naming one (f-strings and ``+`` concatenations read as
one text, docstrings aside), a keyword argument named after one, or a column
attribute used other than as a value: as a dict key, in a pair handed to
``values``/``ordered_values``, or as the receiver of any method but the stored
dict's reads and SQLAlchemy's comparisons. A write needs one of those or an
attribute store, so the specific rules give the clearer message and the
backstop catches what they miss. A site with more mentions than recorded fails,
and so does one with fewer, so the list only shrinks.

Out of reach: a column name built at runtime from pieces that never spell it
(``getattr``/``setattr`` with a computed name, a mapping built by ``zip`` or a
comprehension), and the stored dict passed on as a value (an argument, an
attribute, a container) and changed in place where the column is not named.
Not in scope: SQL in database functions and triggers, migrations (outside
``backend/app/``), and ``source_format``, which several publication paths write
beside the setter.
"""

import ast
import re
from collections import Counter
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"
OWNER = "app/platform/dataset_origin.py"
# Every write the owner module makes, by enclosing function. set_postgis_origin
# writes through set_dataset_origin.
OWNER_WRITES = Counter(
    {
        ("set_dataset_origin", "writes .origin_ref"): 1,
        ("set_dataset_origin", "writes .origin_uri"): 1,
    }
)

COLUMNS = frozenset({"origin_ref", "origin_uri"})
_DICT_MUTATORS = frozenset(
    {"update", "pop", "popitem", "setdefault", "clear", "__setitem__", "__delitem__"}
)
# SQLAlchemy's statement builders.
_STATEMENTS = frozenset({"update", "insert"})
# Conventional names, read as SQLAlchemy even without an import in view.
_DEFAULT_SQLALCHEMY_NAMES = frozenset(
    {"sa", "sqlalchemy", "postgresql", "mysql", "sqlite"}
)
# Methods whose arguments name the columns a statement writes. None of them is
# a dict method, except ``values`` called with arguments, which a dict never is.
_WRITE_METHODS = frozenset(
    {
        "values",
        "ordered_values",
        "on_conflict_do_update",
        "on_duplicate_key_update",
        "from_select",
        "bulk_insert_mappings",
        "bulk_update_mappings",
    }
)
# Keyword spellings of the setters' attribute name: set_attribute(key=...).
_KEY_KEYWORDS = frozenset({"key", "name"})
# Bulk loaders that take a table name and, optionally, the columns they fill.
_TABLE_LOADERS = frozenset({"copy_records_to_table", "copy_to_table", "to_sql"})
# Calls that set an attribute named by a string argument.
_SETTERS = frozenset(
    {"setattr", "set_attribute", "set_committed_value", "__setattr__", "delattr"}
)

# Raw SQL is matched after comments and double quotes are dropped, case is
# lowered and whitespace is collapsed, so any identifier quoting matches.
_SQL_COMMENT = re.compile(r"/\*.*?\*/|--[^\n]*", re.DOTALL)
_COLUMN = r"\borigin_(?:ref|uri)\b"
_DATASETS = (
    r"(?:only\s+)?(?:\w+\.)?datasets\b"
    r"(?:\s+(?:as\s+)?(?!(?:values|select|default|overriding|from|using|with)\b)\w+)?"
)
_SQL_WRITES = tuple(
    re.compile(pattern)
    for pattern in (
        # SET in UPDATE, ON CONFLICT DO UPDATE and MERGE, through a JSON path too.
        r"\bset\b(?:(?!\b(?:where|from|returning)\b)[^;])*?"
        + _COLUMN
        + r"(?:\s*\[[^\]]*\]|\s*->>?\s*'[^']*')*\s*=(?!=)",
        r"\bset\s*\([^)]*" + _COLUMN + r"[^)]*\)\s*=",
        # Column lists.
        r"\binsert\s+into\s+(?:(?!\b(?:select|values|default)\b)[^(;])*\([^)]*"
        + _COLUMN,
        r"\binsert\s*\([^)]*" + _COLUMN,
        r"\bcopy\s+[\w.]+\s*\([^)]*" + _COLUMN + r"[^)]*\)\s*from\b",
        # Every column, by position.
        r"\binsert\s+into\s+"
        + _DATASETS
        + r"\s*(?:values\b|select\b|default\s+values\b|overriding\b|with\b|\(\s*select\b)",
        r"\bmerge\s+into\s+"
        + _DATASETS
        + r".*\binsert\s+(?:values\b|default\s+values\b)",
        r"\bcopy\s+" + _DATASETS + r"\s+from\b",
    )
)
# Files that never name a column can still insert into datasets by position.
_POSITIONAL_HINT = re.compile(r"\b(?:into|copy)\b[^;]{0,120}?datasets\b")


def _terminal_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _is_column(node: ast.expr) -> bool:
    return isinstance(node, ast.Attribute) and node.attr in COLUMNS


def _names_a_column(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value in COLUMNS


def _reads_stored(node: ast.AST) -> str | None:
    """The column whose stored value the expression is: ``x.origin_ref`` or ``getattr(x, "origin_ref")``."""
    if _is_column(node):
        return node.attr
    if (
        isinstance(node, ast.Call)
        and _terminal_name(node.func) == "getattr"
        and len(node.args) >= 2
        and _names_a_column(node.args[1])
    ):
        return node.args[1].value
    return None


def _may_write(source: str) -> bool:
    """Whether the text could hold a write, in any case, so it is worth parsing."""
    lowered = source.lower()
    return any(column in lowered for column in COLUMNS) or bool(
        _POSITIONAL_HINT.search(lowered)
    )


def _is_sql_write(text: object) -> bool:
    if not isinstance(text, str):
        return False
    lowered = text.lower()
    if "origin_" not in lowered and "datasets" not in lowered:
        return False
    flat = " ".join(_SQL_COMMENT.sub(" ", lowered).replace('"', "").split())
    return any(pattern.search(flat) for pattern in _SQL_WRITES)


def _string_text(node: ast.AST) -> str | None:
    """The literal text of an f-string or a ``+`` of strings, with gaps for values."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant) else " _ "
            for part in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _string_text(node.left), _string_text(node.right)
        if left is None and right is None:
            return None
        return (left or " _ ") + (right or " _ ")
    return None


def _receivers(call: ast.Call):
    """The calls a method chain is built on, nearest first."""
    node = call.func
    while isinstance(node, (ast.Attribute, ast.Call)):
        if isinstance(node, ast.Call):
            yield node
            node = node.func
        else:
            node = node.value


class _Module:
    """One module's names for the model, SQLAlchemy and its statement builders."""

    def __init__(self, tree: ast.AST) -> None:
        dataset_names = {"Dataset"}
        modules = set(_DEFAULT_SQLALCHEMY_NAMES)
        builders = set(_STATEMENTS)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] == "sqlalchemy":
                        modules.add(alias.asname or "sqlalchemy")
            elif isinstance(node, ast.ImportFrom):
                from_sqlalchemy = (node.module or "").split(".")[0] == "sqlalchemy"
                for alias in node.names:
                    bound = alias.asname or alias.name
                    if alias.name == "Dataset":
                        dataset_names.add(bound)
                    elif from_sqlalchemy and alias.name in _STATEMENTS:
                        builders.add(bound)
                    elif from_sqlalchemy:
                        modules.add(bound)
        self.modules = frozenset(modules)
        self.builders = builders
        self.dataset_names = dataset_names
        # Local names bound to a builder or to the model, until none is new.
        assigns = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)]
        grew = True
        while grew:
            grew = False
            for node in assigns:
                targets = {t.id for t in node.targets if isinstance(t, ast.Name)}
                if self.builder_ref(node.value) and not targets <= builders:
                    builders |= targets
                    grew = True
                elif self._model_ref(node.value) and not targets <= dataset_names:
                    dataset_names |= targets
                    grew = True

    def _model_ref(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return node.id in self.dataset_names
        return (
            isinstance(node, ast.Call)
            and _terminal_name(node.func) == "get_dataset_orm_class"
        )

    def builder_ref(self, node: ast.expr) -> bool:
        """Whether the expression is ``update``/``insert`` itself, under any name."""
        if isinstance(node, ast.Name):
            return node.id in self.builders
        if isinstance(node, ast.Attribute):
            return node.attr in _STATEMENTS and _root_name(node) in self.modules
        return (
            isinstance(node, ast.Call)
            and _terminal_name(node.func) == "partial"
            and bool(node.args)
            and self.builder_ref(node.args[0])
        )

    def is_builder(self, call: ast.Call) -> bool:
        """A statement builder call, or a table's own ``update()``/``insert()``."""
        if self.builder_ref(call.func):
            return True
        # Table.update()/insert() take no arguments; dict.update() with none
        # writes nothing, so reading it as a table is harmless.
        return (
            isinstance(call.func, ast.Attribute)
            and call.func.attr in _STATEMENTS
            and not call.args
            and not call.keywords
        )

    def column_ref(self, node: ast.AST) -> str | None:
        """The column a model or table reference names.

        ``Dataset.origin_ref``, ``t.c.origin_uri``, ``t.columns.origin_ref``, ``t.c["origin_ref"]``,
        ``t.columns["origin_ref"]`` or ``column("origin_ref")``.
        """
        if _is_column(node):
            base = _terminal_name(node.value)
            if base in self.dataset_names or base in {"c", "columns"}:
                return node.attr
        elif isinstance(node, ast.Subscript) and _names_a_column(node.slice):
            if _terminal_name(node.value) in {"c", "columns"}:
                return node.slice.value
        elif (
            isinstance(node, ast.Call)
            and _terminal_name(node.func) in {"column", "literal_column"}
            and node.args
            and _names_a_column(node.args[0])
        ):
            return node.args[0].value
        return None

    def binds_a_write(self, statement: ast.expr) -> bool:
        """Whether execute()'s parameters are row values: the statement writes, or is unknown.

        A statement passed by name, or SQL text that isn't a literal, can't be
        read here, so its parameters are checked.
        """
        if isinstance(statement, (ast.Name, ast.Attribute)):
            return True
        for node in ast.walk(statement):
            if isinstance(node, ast.Call) and self.is_builder(node):
                return True
            if isinstance(node, ast.Call) and _terminal_name(node.func) == "text":
                text = _string_text(node.args[0]) if node.args else None
                if text is None or _is_sql_write(text):
                    return True
        return False


def _bindings(scope: ast.AST):
    """``(target, value)`` for every way the scope itself binds a name to a value.

    Nested functions, lambdas and classes bind in their own scopes.
    """
    for node in _own_nodes(scope):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                yield target, node.value
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value:
            yield node.target, node.value
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            if isinstance(node.iter, (ast.Tuple, ast.List, ast.Set)):
                for element in node.iter.elts:
                    yield node.target, element
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None:
                    yield item.optional_vars, item.context_expr


def _bindings_at(node: ast.AST):
    """``(target, value)`` for the bindings this one node makes."""
    if isinstance(node, ast.Assign):
        for target in node.targets:
            yield target, node.value
    elif isinstance(node, (ast.AnnAssign, ast.NamedExpr, ast.AugAssign)):
        yield node.target, node.value
    elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
        yield node.target, node.iter
    elif isinstance(node, (ast.With, ast.AsyncWith)):
        for item in node.items:
            if item.optional_vars is not None:
                yield item.optional_vars, item.context_expr


def _name_pairs(target: ast.AST, value: ast.AST):
    """``(name, value)`` a binding gives each plain name, unpacking literals."""
    if isinstance(target, ast.Name):
        yield target.id, value
    elif (
        isinstance(target, (ast.Tuple, ast.List))
        and isinstance(value, (ast.Tuple, ast.List))
        and len(target.elts) == len(value.elts)
        and not any(isinstance(e, ast.Starred) for e in target.elts)
    ):
        for inner_target, inner_value in zip(target.elts, value.elts):
            yield from _name_pairs(inner_target, inner_value)


def _holds_stored(value: ast.AST, aliases: set[str]) -> bool:
    """Whether the expression evaluates to the stored dict itself, not a copy."""
    if _reads_stored(value):
        return True
    if isinstance(value, ast.Name):
        return value.id in aliases
    if isinstance(value, ast.BoolOp):
        return any(_holds_stored(part, aliases) for part in value.values)
    if isinstance(value, ast.IfExp):
        return _holds_stored(value.body, aliases) or _holds_stored(
            value.orelse, aliases
        )
    if isinstance(value, ast.NamedExpr):
        return _holds_stored(value.value, aliases)
    return (
        isinstance(value, ast.Call)
        and _terminal_name(value.func) == "nullcontext"
        and bool(value.args)
        and _holds_stored(value.args[0], aliases)
    )


_NESTED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _header_nodes(node: ast.AST) -> list[ast.AST]:
    """A nested definition's parts that run in the enclosing scope.

    Decorators, defaults, annotations, class bases and keywords; only the body
    belongs to the definition's own scope.
    """
    if isinstance(node, ast.ClassDef):
        return [*node.decorator_list, *node.bases, *node.keywords]
    args = node.args
    parts = [*args.defaults, *(d for d in args.kw_defaults if d is not None)]
    if isinstance(node, ast.Lambda):
        return parts
    params = [
        *args.posonlyargs,
        *args.args,
        *args.kwonlyargs,
        *([args.vararg] if args.vararg else []),
        *([args.kwarg] if args.kwarg else []),
    ]
    return [
        *node.decorator_list,
        *parts,
        *(a.annotation for a in params if a.annotation is not None),
        *([node.returns] if node.returns else []),
    ]


def _body_nodes(scope: ast.AST) -> list[ast.AST]:
    if isinstance(scope, ast.Lambda):
        return [scope.body]
    if isinstance(scope, (ast.Module, *_NESTED_SCOPES)):
        return list(scope.body)
    return list(ast.iter_child_nodes(scope))


def _own_nodes(scope: ast.AST):
    """The scope's own nodes: its body, and nested definitions' headers but not bodies.

    A comprehension is walked through, so a walrus in one binds here (PEP 572).
    """
    stack = _body_nodes(scope)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, _NESTED_SCOPES):
            stack.extend(_header_nodes(node))
        else:
            stack.extend(ast.iter_child_nodes(node))


def _target_names(target: ast.AST):
    """Names a binding target binds; ``x[k] = v`` and ``x.a = v`` bind none."""
    if isinstance(target, ast.Name):
        yield target.id
    elif isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            yield from _target_names(element)
    elif isinstance(target, ast.Starred):
        yield from _target_names(target.value)


def _class_aliases(cls: ast.ClassDef, inherited: frozenset[str]) -> frozenset[str]:
    """Class attributes the class body binds to the stored dict."""
    pairs = [
        pair for target, value in _bindings(cls) for pair in _name_pairs(target, value)
    ]
    bound = {name for name, _ in pairs}
    return _alias_fixpoint(pairs, set(inherited) - bound) & bound


def _alias_fixpoint(pairs, names: set[str]) -> frozenset[str]:
    grew = True
    while grew:
        grew = False
        for name, value in pairs:
            if name not in names and _holds_stored(value, names):
                names.add(name)
                grew = True
    return frozenset(names)


class _Scope:
    """One function's (or the module's) names, inside the scopes enclosing it.

    A free name resolves through the enclosing scopes, so an alias of the
    stored dict or a mapping of column keys made outside a nested function
    counts inside it. ``global`` names resolve at module level.
    """

    def __init__(
        self,
        module: _Module,
        scope: ast.AST,
        parent: "_Scope | None" = None,
        class_name: str | None = None,
    ) -> None:
        self.module = module
        self.scope = scope
        self.parent = parent
        self.is_class = isinstance(scope, ast.ClassDef)
        self.root: _Scope = parent.root if parent else self
        # The class a method belongs to, and its first parameter (self/cls).
        self.class_name = class_name
        args = getattr(scope, "args", None)
        positional = [*args.posonlyargs, *args.args] if args else []
        self.receiver = positional[0].arg if class_name and positional else None
        self._stored_aliases: frozenset[str] | None = None
        self.class_aliases: dict[str, frozenset[str]] = (
            parent.class_aliases if parent else {}
        )

    def _declared(self, kind: type) -> set[str]:
        return {
            name
            for node in _own_nodes(self.scope)
            if isinstance(node, kind)
            for name in node.names
        }

    def local_names(self) -> set[str]:
        """Names this scope binds itself, which shadow the enclosing ones."""
        names = {
            name
            for node in _own_nodes(self.scope)
            if not isinstance(node, ast.comprehension)
            for target, _ in _bindings_at(node)
            for name in _target_names(target)
        }
        args = getattr(self.scope, "args", None)
        if args is not None:
            names.update(
                a.arg
                for a in [
                    *args.posonlyargs,
                    *args.args,
                    *args.kwonlyargs,
                    *([args.vararg] if args.vararg else []),
                    *([args.kwarg] if args.kwarg else []),
                ]
            )
        names.update(
            n.name
            for n in _own_nodes(self.scope)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        )
        return names - self._declared(ast.Nonlocal)

    def binds(self, name: str) -> bool:
        return name in self.local_names()

    def _key_column(self, key: ast.AST | None) -> str | None:
        if key is None:
            return None
        if _names_a_column(key):
            return key.value
        return self.module.column_ref(key)

    def mentions(self, node: ast.AST, *, follow: bool = True) -> list[str]:
        found: list[str] = []
        for inner in ast.walk(node):
            if isinstance(inner, ast.Dict):
                found.extend(c for k in inner.keys if (c := self._key_column(k)))
            elif isinstance(inner, ast.Call) and _terminal_name(inner.func) == "dict":
                found.extend(kw.arg for kw in inner.keywords if kw.arg in COLUMNS)
            elif isinstance(inner, ast.Tuple) and inner.elts:
                # ordered_values() takes (column, value) pairs.
                if column := self._key_column(inner.elts[0]):
                    found.append(column)
            elif follow and isinstance(inner, ast.Name):
                found.extend(self.assigned(inner.id))
        return found

    def _assignments(self, name: str):
        for node in _own_nodes(self.scope):
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                if node.value is not None and any(
                    isinstance(t, ast.Name) and t.id == name for t in targets
                ):
                    yield node.value

    def assigned(self, name: str) -> list[str]:
        """Columns a mapping gets as keys in this scope, or where it is bound."""
        if self.parent is not None and not self.binds(name):
            return self.parent.assigned(name)
        found: list[str] = []
        for value in self._assignments(name):
            found.extend(self.mentions(value, follow=False))
        for node in _own_nodes(self.scope):
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.ctx, ast.Store)
                and isinstance(node.value, ast.Name)
                and node.value.id == name
                and (column := self._key_column(node.slice))
            ):
                found.append(column)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == name
            ):
                if node.func.attr == "update":
                    found.extend(kw.arg for kw in node.keywords if kw.arg in COLUMNS)
                    for arg in node.args:
                        found.extend(self.mentions(arg, follow=False))
                elif node.func.attr in {"setdefault", "__setitem__"} and node.args:
                    if column := self._key_column(node.args[0]):
                        found.append(column)
        return found

    def is_query(self, name: str) -> bool:
        """Whether a name holds an ORM ``Query``, here or where it is bound."""
        if self.parent is not None and not self.binds(name):
            return self.parent.is_query(name)
        return any(
            isinstance(value, ast.Call)
            and any(
                _terminal_name(r.func) == "query" for r in [value, *_receivers(value)]
            )
            for value in self._assignments(name)
        )

    def stored_aliases(self) -> frozenset[str]:
        """Names bound to a stored ``origin_ref``/``origin_uri`` value here.

        Through any binding (assignment, annotated assignment, walrus,
        unpacking, a ``for`` over a literal, ``with ... as``), through other
        aliases until none is new, and through enclosing scopes for a name
        this scope doesn't bind itself (or declares ``nonlocal``/``global``).
        """
        if self._stored_aliases is None:
            inherited: set[str] = set()
            if self.parent is not None:
                local = self.local_names()
                inherited = set(self.parent.stored_aliases()) - local
                inherited |= set(self.root.stored_aliases()) & self._declared(
                    ast.Global
                )
            pairs = [
                pair
                for target, value in _bindings(self.scope)
                for pair in _name_pairs(target, value)
            ]
            pairs += self._rebound_by_nested()
            self._stored_aliases = _alias_fixpoint(pairs, inherited)
        return self._stored_aliases

    def _rebound_by_nested(self) -> list[tuple[str, ast.AST]]:
        """Bindings nested functions make to this scope's own names.

        Through ``nonlocal`` for a function's names, through ``global`` for
        the module's.
        """
        declared_as = ast.Nonlocal if self.parent is not None else ast.Global
        own = self.local_names() if self.parent is not None else None
        pairs = []
        for node in ast.walk(self.scope):
            if node is self.scope or not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            declared = {
                name
                for statement in _own_nodes(node)
                if isinstance(statement, declared_as)
                for name in statement.names
            }
            if own is not None:
                declared &= own
            pairs.extend(
                (name, value)
                for target, bound in _bindings(node)
                for name, value in _name_pairs(target, bound)
                if name in declared
            )
        return pairs

    def stored_dict(self, node: ast.AST) -> str | None:
        """What a reference to the stored dict is called, if the node is one."""
        if column := _reads_stored(node):
            return column
        if isinstance(node, ast.Name) and node.id in self.stored_aliases():
            return f"the origin pointer through {node.id}"
        # A class attribute aliasing it, read as Class.attr or self.attr.
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            owner = node.value.id
            if owner == self.receiver:
                owner = self.class_name
            if node.attr in self.class_aliases.get(owner, frozenset()):
                return f"the origin pointer through {owner}.{node.attr}"
        return None

    def call_mentions(self, call: ast.Call, args: list[ast.expr]) -> list[str]:
        found = [kw.arg for kw in call.keywords if kw.arg in COLUMNS]
        for arg in args:
            found.extend(self.mentions(arg))
        return found


def _mutated_dict(call: ast.Call, scope: _Scope) -> str | None:
    """The stored column a dict-mutating call changes in place, if any."""
    func = call.func
    name = _terminal_name(func)
    # operator.setitem(dataset.origin_ref, key, value) and delitem.
    if name in {"setitem", "delitem"} and call.args:
        return scope.stored_dict(call.args[0])
    if not isinstance(func, ast.Attribute) or name not in _DICT_MUTATORS:
        return None
    target = func.value
    # dict.update(dataset.origin_ref, ...) and the like.
    if _terminal_name(target) in {"dict", "MutableDict"} and call.args:
        target = call.args[0]
    return scope.stored_dict(target)


def _table_load_writes(call: ast.Call, name: str) -> list[str]:
    """A bulk load into datasets: every column, or the listed ones."""
    keywords = {kw.arg: kw.value for kw in call.keywords if kw.arg}
    table = (
        call.args[0] if call.args else keywords.get("table_name", keywords.get("name"))
    )
    listed = keywords.get("columns")
    if listed is not None:
        return [
            f"{name}() loads {element.value}"
            for element in getattr(listed, "elts", [])
            if _names_a_column(element)
        ]
    if (
        isinstance(table, ast.Constant)
        and str(table.value).split(".")[-1] == "datasets"
    ):
        return [f"{name}() loads every column of datasets"]
    return []


def _call_writes(call: ast.Call, scope: _Scope) -> list[str]:
    module = scope.module
    func = call.func
    name = _terminal_name(func)
    if column := _mutated_dict(call, scope):
        return [f"mutates {column} with {name}()"]
    named = [
        *call.args[:2],
        *(kw.value for kw in call.keywords if kw.arg in _KEY_KEYWORDS),
    ]
    if name in _SETTERS and any(_names_a_column(arg) for arg in named):
        return [f"{name}() sets a column by name"]
    if name in _TABLE_LOADERS:
        return _table_load_writes(call, name)
    keyword_values = [kw.value for kw in call.keywords]
    keywords = {kw.arg: kw.value for kw in call.keywords if kw.arg}
    if name in module.dataset_names:
        columns = scope.call_mentions(call, [*call.args, *keyword_values])
    elif module.is_builder(call):
        # The table is the argument; a legacy values= keyword holds the row.
        columns = scope.call_mentions(call, keyword_values)
    elif isinstance(func, ast.Attribute) and name in _WRITE_METHODS:
        if name == "values" and not call.args and not call.keywords:
            return []
        columns = scope.call_mentions(call, [*call.args, *keyword_values])
        if name == "from_select":
            listed = call.args[0] if call.args else keywords.get("names")
            columns.extend(
                column
                for element in getattr(listed, "elts", [])
                if (column := scope._key_column(element))
            )
    elif (
        isinstance(func, ast.Attribute)
        and name == "update"
        and (
            any(_terminal_name(r.func) == "query" for r in _receivers(call))
            or (isinstance(func.value, ast.Name) and scope.is_query(func.value.id))
        )
    ):
        # Query.update(), the legacy ORM bulk update.
        columns = scope.call_mentions(call, [*call.args, *keyword_values])
    elif isinstance(func, ast.Attribute) and name == "execute":
        statement = call.args[0] if call.args else keywords.get("statement")
        if statement is None or not module.binds_a_write(statement):
            return []
        # The statement is checked as its own call; the rest are bind parameters.
        params = [
            *call.args[1:],
            *([keywords["params"]] if "params" in keywords else []),
        ]
        columns = [c for arg in params for c in scope.mentions(arg)]
    else:
        return []
    return [f"passes {column} to {name}()" for column in columns]


def _node_writes(node: ast.AST, scope: _Scope) -> list[str]:
    stored = isinstance(getattr(node, "ctx", None), (ast.Store, ast.Del))
    if stored and _is_column(node):
        return [f"writes .{node.attr}"]
    # ref |= {...} on a local bound to the stored dict changes it in place.
    if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.BitOr):
        if not _is_column(node.target) and (held := scope.stored_dict(node.target)):
            return [f"updates {held} in place"]
    if stored and isinstance(node, ast.Subscript):
        holder = node.value
        if column := scope.stored_dict(holder):
            return [f"writes an item of {column}"]
        # obj.__dict__["origin_ref"] or vars(obj)["origin_ref"]
        if _names_a_column(node.slice) and (
            _terminal_name(holder) == "__dict__"
            or (isinstance(holder, ast.Call) and _terminal_name(holder.func) == "vars")
        ):
            return [f"writes {node.slice.value} through __dict__"]
    if isinstance(node, ast.Call):
        return _call_writes(node, scope)
    return []


def binding_writes(source: str) -> list[tuple[int, str | None, str]]:
    """Every write to the binding columns this module's text shows.

    Each is ``(line, enclosing function or None, description)``.
    """
    found: list[tuple[int, str | None, str]] = []
    tree = ast.parse(source)
    module = _Module(tree)

    def visit(
        node: ast.AST, function: str | None, scope: _Scope, in_string: bool
    ) -> None:
        if isinstance(node, _NESTED_SCOPES):
            # The header runs in the enclosing scope, the body in its own.
            for header in _header_nodes(node):
                visit(header, function, scope, in_string)
            if isinstance(node, ast.ClassDef):
                scope.class_aliases[node.name] = _class_aliases(
                    node, scope.stored_aliases()
                )
                inner = _Scope(module, node, scope)
            else:
                if not isinstance(node, ast.Lambda):
                    function = node.name
                # A class body is not visible to the functions defined in it.
                inner = _Scope(
                    module,
                    node,
                    scope.parent if scope.is_class else scope,
                    scope.scope.name if scope.is_class else None,
                )
            for child in _body_nodes(node):
                visit(child, function, inner, in_string)
            return
        found.extend(
            (node.lineno, function, what) for what in _node_writes(node, scope)
        )
        # The outermost literal string expression is matched as one text.
        text = None if in_string else _string_text(node)
        if text is not None:
            if _is_sql_write(text):
                found.append((node.lineno, function, "raw SQL writes the column"))
            in_string = True
        for child in ast.iter_child_nodes(node):
            visit(child, function, scope, in_string)

    visit(tree, None, _Scope(module, tree), False)
    return found


# The backstop: any name for a column outside the binding module. A write needs
# the column's name as text, as a keyword or as an attribute used for something
# other than reading it.
_LITERAL = re.compile(r"\borigin_(?:ref|uri)\b")
# Calls on a column attribute that only read it: the stored dict's read methods
# and SQLAlchemy's comparison operators.
_READ_CALLS = frozenset(
    {
        "get",
        "keys",
        "values",
        "items",
        "copy",
        "is_",
        "is_not",
        "isnot",
        "is_distinct_from",
        "is_not_distinct_from",
        "in_",
        "not_in",
        "notin_",
        "has_key",
        "label",
    }
)
# Every site that names a column, the binding module's included, by file and
# dotted path, with how many mentions it has and why none is a write. The binding
# module's setter writes through attribute stores, which OWNER_WRITES counts.
NAME_ALLOWLIST: dict[tuple[str, str], tuple[int, str]] = {
    (
        "app/modules/catalog/datasets/api/router_refresh.py",
        "_dispatch_postgis_refresh",
    ): (
        2,
        "db.refresh() reloads the columns after the run is reserved",
    ),
    ("app/modules/catalog/datasets/api/router_refresh.py", "_dispatch_stac_refresh"): (
        2,
        "db.refresh() reloads the columns after the run is reserved",
    ),
    ("app/modules/catalog/datasets/api/router_refresh.py", "refresh_dataset"): (
        2,
        "db.refresh() reloads the columns after the run is reserved",
    ),
    ("app/modules/catalog/datasets/domain/helpers.py", "dataset_to_response"): (
        2,
        "builds the API response from the stored columns",
    ),
    ("app/modules/catalog/datasets/domain/models.py", "Dataset"): (
        6,
        "index definitions over the columns",
    ),
    ("app/modules/catalog/datasets/domain/schemas.py", "DatasetResponse"): (
        1,
        "the response field's description",
    ),
    ("app/platform/dataset_origin.py", "build_origin_ref"): (
        1,
        "the allowlist's refusal message names the column",
    ),
    ("app/processing/ingest/previous_version.py", "<module>"): (
        1,
        "an INSERT into dataset_versions that reads origin_ref->>'file_hash'",
    ),
    ("app/processing/ingest/tasks_reupload.py", "_FileReupload.write"): (
        1,
        "hands the upload ref to _write_reupload_catalog, which stamps it through set_dataset_origin",
    ),
    ("app/processing/ingest/tasks_reupload.py", "_ServiceReupload.write"): (
        1,
        "hands the service ref to _write_reupload_catalog, which stamps it through set_dataset_origin",
    ),
    ("app/processing/ingest/tasks_vector.py", "ingest_file"): (
        1,
        "the ref captured at import, stamped through set_dataset_origin at commit",
    ),
    ("app/processing/ingest/tasks_vector.py", "ingest_service"): (
        1,
        "the ref captured at import, stamped through set_dataset_origin at commit",
    ),
}


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {
        child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
    }


def _attribute_use(node: ast.Attribute, parents: dict[ast.AST, ast.AST]) -> str | None:
    """How a Load of ``x.origin_ref`` is used, when it is not a plain read."""
    parent = parents.get(node)
    if isinstance(parent, ast.Dict) and node in parent.keys:
        return "a dict key"
    if isinstance(parent, ast.Tuple):
        call = parents.get(parent)
        if isinstance(call, ast.Call) and _terminal_name(call.func) in {
            "values",
            "ordered_values",
        }:
            return f"a pair handed to {_terminal_name(call.func)}()"
    if isinstance(parent, ast.Attribute):
        called = isinstance(parents.get(parent), ast.Call) and (
            parents[parent].func is parent
        )
        if called and parent.attr not in _READ_CALLS:
            return f"the receiver of .{parent.attr}()"
        if not called and (
            parent.attr in _DICT_MUTATORS or parent.attr.startswith("__")
        ):
            return f"the owner of .{parent.attr}"
    return None


def name_mentions(source: str) -> list[tuple[int, str, str]]:
    """``(line, site, how)`` of every name for a column outside a plain read.

    A string naming one (an f-string or a ``+`` of strings read as one text,
    docstrings aside), a keyword argument named after one, and a column attribute
    used other than as a value. The site is the dotted path of enclosing classes
    and functions (``Strategy.write``), or ``<module>``.
    """
    tree = ast.parse(source)
    parents = _parents(tree)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        )
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    found: list[tuple[int, str, str]] = []

    def visit(node: ast.AST, site: str, in_string: bool) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            site = node.name if site == "<module>" else f"{site}.{node.name}"
        text = None if in_string or id(node) in docstrings else _string_text(node)
        if text is not None:
            if _LITERAL.search(text.lower()):
                found.append((node.lineno, site, "a string naming a column"))
            in_string = True
        if isinstance(node, ast.keyword) and node.arg in COLUMNS:
            found.append((node.value.lineno, site, f"the keyword {node.arg}="))
        if (
            isinstance(node, ast.Attribute)
            and node.attr in COLUMNS
            and isinstance(node.ctx, ast.Load)
            and (use := _attribute_use(node, parents))
        ):
            found.append((node.lineno, site, f".{node.attr} as {use}"))
        for child in ast.iter_child_nodes(node):
            visit(child, site, in_string)

    visit(tree, "<module>", False)
    return found


def site_problems(
    rel: str, source: str, allowlist: dict[tuple[str, str], tuple[int, str]]
) -> list[str]:
    """Sites in one file whose mentions exceed, or fall short of, the allowlist."""
    by_site: dict[str, list[str]] = {}
    for line, site, how in name_mentions(source):
        by_site.setdefault(site, []).append(f"{rel}:{line}: {how}")
    problems = []
    for site, mentions in by_site.items():
        allowed = allowlist.get((rel, site), (0, ""))[0]
        if len(mentions) > allowed:
            problems.append(
                f"{rel} {site}: {len(mentions)} mention(s), {allowed} allowed\n  "
                + "\n  ".join(mentions)
            )
    for (listed_rel, site), (allowed, _) in allowlist.items():
        if listed_rel == rel and len(by_site.get(site, [])) < allowed:
            problems.append(
                f"{rel} {site}: {len(by_site.get(site, []))} mention(s), "
                f"{allowed} allowed; lower the entry"
            )
    return problems


def _app_sources(*, owner: bool = False):
    for path in sorted(APP_ROOT.rglob("*.py")):
        rel = path.relative_to(BACKEND_ROOT).as_posix()
        if owner or rel != OWNER:
            yield rel, path.read_text(encoding="utf-8")


def owner_writes(source: str) -> Counter:
    return Counter((function, what) for _, function, what in binding_writes(source))


def test_only_the_binding_module_writes_origin_columns() -> None:
    violations = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        rel = path.relative_to(BACKEND_ROOT).as_posix()
        source = path.read_text(encoding="utf-8")
        if rel == OWNER or not _may_write(source):
            continue
        for line, _, what in binding_writes(source):
            violations.append(f"{rel}:{line}: {what}")
    assert not violations, (
        "origin_uri/origin_ref are written only by set_dataset_origin or "
        "set_postgis_origin in backend/app/platform/dataset_origin.py:\n"
        + "\n".join(violations)
    )


def tree_problems(
    sources: dict[str, str], allowlist: dict[tuple[str, str], tuple[int, str]]
) -> list[str]:
    """Every site in the tree that breaks the allowlist, and entries for missing files."""
    listed_files = {rel for rel, _ in allowlist}
    problems = [
        problem
        for rel, source in sources.items()
        if "origin_" in source.lower() or rel in listed_files
        for problem in site_problems(rel, source, allowlist)
    ]
    problems += [f"{rel}: no such file" for rel in sorted(listed_files - set(sources))]
    return problems


def test_every_name_for_a_column_is_at_an_allowlisted_site() -> None:
    """The binding module too: only its recorded functions may name a column."""
    problems = tree_problems(dict(_app_sources(owner=True)), NAME_ALLOWLIST)
    assert not problems, (
        "A string, keyword or attribute naming origin_ref/origin_uri can write "
        "them. Write through set_dataset_origin, or record the site in "
        "NAME_ALLOWLIST with its count and why it is no write:\n" + "\n".join(problems)
    )


def _sites(source: str) -> list[tuple[int, str]]:
    return [(line, site) for line, site, _ in name_mentions(source)]


def test_the_backstop_catches_a_name_only_it_sees() -> None:
    source = (
        "COLUMN = 'origin_ref'\n"
        "def write(obj, value):\n"
        "    setattr(obj, COLUMN, value)\n"
    )
    assert binding_writes(source) == []
    assert _sites(source) == [(1, "<module>")]
    assert _sites("NAME = 'origin_' + 'uri'") == [(1, "<module>")]
    assert _sites("KEY = f'{prefix}.origin_uri'") == [(1, "<module>")]


@pytest.mark.parametrize(
    "snippet",
    [
        "dataset.__dict__.update(origin_ref=ref)",
        "vars(dataset).update(origin_uri=uri)",
        "helper(dataset, origin_ref=ref)",
        "update(Dataset).values({Dataset.__table__.columns.origin_ref: ref})",
        "update(Dataset).ordered_values((Dataset.__table__.columns.origin_uri, u))",
        "Dataset.origin_ref.__set__(dataset, ref)",
        "dataset.origin_ref.setdefault('token', t)",
        "Dataset.origin_uri.__delete__(dataset)",
        "write = dataset.origin_ref.update",
    ],
)
def test_the_backstop_catches_an_identifier_write(snippet: str) -> None:
    assert name_mentions(snippet), snippet


@pytest.mark.parametrize(
    "snippet",
    [
        "ref = dataset.origin_ref",
        "same = dataset.origin_uri == uri",
        "where(Dataset.origin_uri.is_(None))",
        "where(Dataset.origin_ref.is_not_distinct_from(ref))",
        "probe(dataset.origin_ref, dataset.origin_uri)",
        "url = dataset.origin_ref.get('url')",
        "list(dataset.origin_ref.keys()), dataset.origin_ref.items()",
        "snapshot = dataset.origin_ref.copy()",
        "url = dataset.origin_ref['url']",
        "pointer = (dataset.origin_uri, dataset.origin_ref, dataset.source_format)",
        "Dataset.origin_ref['url'].astext == base_url",
        "f'{dataset.origin_uri}'",
    ],
)
def test_the_backstop_leaves_a_plain_read_alone(snippet: str) -> None:
    assert name_mentions(snippet) == [], snippet


def test_an_allowlist_entry_clears_only_its_own_site() -> None:
    source = (
        "def keys():\n    return ['origin_ref']\n\n"
        "def other(dataset, ref):\n    helper(dataset, origin_uri=ref)\n"
    )
    assert len(site_problems("app/x.py", source, {})) == 2
    listed = {("app/x.py", "keys"): (1, "a test")}
    problems = site_problems("app/x.py", source, listed)
    assert [p.split(":")[0] for p in problems] == ["app/x.py other"]


def test_same_named_methods_in_two_classes_are_separate_sites() -> None:
    source = (
        "class Upload:\n    def write(self, ref):\n        stamp(origin_ref=ref)\n\n"
        "class Service:\n    def write(self, ref):\n        stamp(origin_ref=ref)\n"
    )
    assert _sites(source) == [(3, "Upload.write"), (7, "Service.write")]
    listed = {("app/x.py", "Upload.write"): (1, "a test")}
    problems = site_problems("app/x.py", source, listed)
    assert [p.split(":")[0] for p in problems] == ["app/x.py Service.write"]


def test_a_second_mention_in_an_allowlisted_method_fails() -> None:
    rel = "app/processing/ingest/tasks_reupload.py"
    source = (BACKEND_ROOT / rel).read_text(encoding="utf-8")
    anchor = (
        '            origin_ref={"filename": self.source_filename, '
        '"file_hash": self.file_hash},\n'
    )
    assert source.count(anchor) == 1
    extra = source.replace(anchor, anchor + "            origin_uri=None,\n")
    assert site_problems(rel, source, NAME_ALLOWLIST) == []
    problems = site_problems(rel, extra, NAME_ALLOWLIST)
    assert len(problems) == 1
    assert problems[0].startswith(f"{rel} _FileReupload.write: 2 mention(s), 1 allowed")


def test_an_allowlisted_site_is_held_to_its_count() -> None:
    one = "def write(ref):\n    stamp(origin_ref=ref)\n"
    two = one + "    keep(origin_uri=ref)\n"
    listed = {("app/x.py", "write"): (1, "a test")}
    assert site_problems("app/x.py", one, listed) == []
    assert "2 mention(s), 1 allowed" in site_problems("app/x.py", two, listed)[0]
    stale = {("app/x.py", "write"): (2, "a test")}
    assert "lower the entry" in site_problems("app/x.py", one, stale)[0]


@pytest.mark.parametrize(
    "body",
    [
        "    dataset.__dict__.update(origin_ref=ref)",
        "    delattr(dataset, 'origin_uri')",
        "    Dataset.origin_ref.__set__(dataset, ref)",
    ],
)
def test_a_new_owner_function_that_names_a_column_fails(body: str) -> None:
    sources = dict(_app_sources(owner=True))
    sources[OWNER] += f"\n\ndef _sneak(dataset, ref):\n{body}\n"
    problems = tree_problems(sources, NAME_ALLOWLIST)
    assert [p.split(":")[0] for p in problems] == [f"{OWNER} _sneak"]


def test_the_backstop_leaves_docstrings_and_other_names_alone() -> None:
    source = (
        '"""Reads origin_ref."""\n'
        "def f():\n"
        '    """Also origin_uri."""\n'
        "    return 'ix_datasets_origin_uri', 'origin_ref_snapshot'\n"
    )
    assert name_mentions(source) == []


def test_the_owner_module_writes_only_inside_its_setter() -> None:
    owner = (BACKEND_ROOT / OWNER).read_text(encoding="utf-8")
    assert owner_writes(owner) == OWNER_WRITES


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (
            "\ndef project_unknown(",
            "\ndef _sneak(dataset):\n    dataset.origin_ref = {}\n\n\n"
            "def project_unknown(",
        ),
        (
            "    dataset.origin_uri = uri\n",
            "    dataset.origin_uri = uri\n    dataset.origin_uri = uri\n",
        ),
    ],
    ids=["second_function", "second_site_in_the_setter"],
)
def test_the_owner_check_sees_an_extra_write(old: str, new: str) -> None:
    owner = (BACKEND_ROOT / OWNER).read_text(encoding="utf-8")
    assert owner.count(old) == 1
    assert owner_writes(owner.replace(old, new)) != OWNER_WRITES


@pytest.mark.parametrize(
    "snippet",
    [
        "dataset.origin_ref = {'kind': 'upload'}",
        "dataset.origin_uri: str = 'x'",
        "dataset.origin_uri += '/1'",
        "a, dataset.origin_uri = 1, 'x'",
        "del dataset.origin_ref",
        "dataset.origin_ref['url'] = 'x'",
        "del dataset.origin_ref['url']",
        "dataset.origin_ref.update(url='x')",
        "dataset.origin_ref.pop('token')",
        "setattr(dataset, 'origin_uri', 'x')",
        "Dataset(origin_ref={'kind': 'upload'})",
        "update(Dataset).values(origin_uri='x')",
        "sa.update(Dataset).values({'origin_ref': ref})",
        "sqlalchemy.insert(Dataset).values(origin_uri='x')",
        "session.execute(update(Dataset).values(origin_ref=ref))",
        "insert(Dataset).values({'origin_ref': ref})",
        "Dataset(**{'origin_uri': 'x'})",
        "session.execute(update(Dataset), [{'id': 1, 'origin_ref': ref}])",
        "text('UPDATE catalog.datasets SET origin_uri = :u WHERE id = :id')",
        "text('INSERT INTO catalog.datasets (id, origin_ref) VALUES (:i, :r)')",
        "text('UPDATE catalog.datasets SET \"origin_ref\" = :ref WHERE id = :id')",
        "text('INSERT INTO catalog.datasets (id, \"origin_uri\") VALUES (:i, :u)')",
        "text('UPDATE catalog.datasets SET ORIGIN_REF = :ref WHERE id = :id')",
        "session.execute(stmt, [{'id': 1, 'origin_ref': ref}])",
        "from app.modules.catalog.datasets.domain.models import Dataset as DatasetModel"
        "\nDatasetModel(origin_ref={'kind': 'upload'})",
        "from app.modules.catalog.datasets.domain import models\n"
        "models.Dataset(origin_uri='x')",
        "DatasetCls = get_processing_port().get_dataset_orm_class()\n"
        "DatasetCls(origin_uri='x')",
        "update(Dataset).values({Dataset.origin_ref: ref})",
        "from app.modules.catalog.datasets.domain.models import Dataset as DatasetModel"
        "\ninsert(DatasetModel).values({DatasetModel.origin_uri: uri})",
        "text(\"UPDATE catalog.datasets SET origin_ref['token'] = :v WHERE id = :i\")",
        "text('UPDATE catalog.datasets SET \"origin_ref\"[\\'url\\'] = :v')",
        "text('UPDATE catalog.datasets SET origin_ref = "
        "jsonb_set(origin_ref, :path, :v) WHERE id = :i')",
        "session.execute(update(Dataset), params=[{'id': 1, 'origin_ref': ref}])",
        "session.execute(stmt, params={'origin_uri': uri})",
        "session.execute(statement=update(Dataset), params=[{'origin_ref': ref}])",
        "insert(Dataset).from_select(['id', 'origin_ref'], select(a, b))",
        "sa.insert(Dataset).from_select([Dataset.id, Dataset.origin_uri], query)",
        "text('UPDATE catalog.datasets SET (title, origin_ref) = (:t, :r) "
        "WHERE id = :i')",
        "text('UPDATE catalog.datasets SET (\"origin_uri\") = ROW(:u)')",
        "insert(Record).from_select(['id', 'origin_ref'], query)",
        "stmt = insert(Dataset)\nstmt.from_select(['id', 'origin_ref'], query)",
        "insert(Dataset).from_select(names=['id', 'origin_uri'], select=query)",
        # Upserts.
        "insert(Dataset).values(id=i).on_conflict_do_update("
        "index_elements=['id'], set_={'origin_ref': ref})",
        "from sqlalchemy.dialects.postgresql import insert as pg_insert\n"
        "pg_insert(Dataset).values(id=i).on_conflict_do_update("
        "index_elements=['id'], set_=dict(origin_ref=ref))",
        "def f(i):\n    stmt = insert(Dataset).values(id=i)\n"
        "    return stmt.on_conflict_do_update(index_elements=['id'], "
        "set_={Dataset.origin_uri: stmt.excluded.origin_uri})",
        "postgresql.insert(Dataset).on_conflict_do_update(set_={'origin_uri': u})",
        "mysql_insert(Dataset).on_duplicate_key_update(origin_ref=ref)",
        "from sqlalchemy.dialects.postgresql import insert as pg_insert\n"
        "session.execute(pg_insert(Dataset), [{'origin_ref': ref}])",
        "session.execute(postgresql.insert(Dataset), [{'origin_uri': u}])",
        # Mappings passed by name.
        "def f(ref):\n    changes = {'origin_ref': ref}\n"
        "    return update(Dataset).values(**changes)",
        "def f(u):\n    changes = {}\n    changes['origin_uri'] = u\n"
        "    return update(Dataset).values(changes)",
        "def f(ref):\n    changes = {'title': 't'}\n"
        "    changes.update(origin_ref=ref)\n"
        "    return update(Dataset).values(**changes)",
        "def f(u):\n    fields = dict(origin_uri=u)\n    return Dataset(**fields)",
        "def f(session, r):\n    rows = [{'id': 1, 'origin_ref': r}]\n"
        "    session.bulk_update_mappings(Dataset, rows)",
        # Tables, ordered values and the legacy Query API.
        "session.execute(Dataset.__table__.update(), [{'origin_ref': ref}])",
        "session.execute(metadata.tables['catalog.datasets'].insert(), "
        "[{'origin_uri': u}])",
        "sa.update(table).values({table.c.origin_ref: ref})",
        "update(Dataset).ordered_values((Dataset.origin_ref, ref), ('title', t))",
        "update(Dataset).ordered_values(('origin_uri', u))",
        "session.query(Dataset).filter(Dataset.id == i).update({'origin_ref': ref})",
        # SQLAlchemy reached through any name the module binds to it.
        "import sqlalchemy as sqla\n"
        "session.execute(sqla.update(Dataset), [{'origin_ref': ref}])",
        "import sqlalchemy.dialects.postgresql as pgd\n"
        "session.execute(pgd.insert(Dataset), [{'origin_uri': u}])",
        "from sqlalchemy import update as sa_update\n"
        "session.execute(sa_update(Dataset), [{'origin_ref': ref}])",
        "from sqlalchemy.dialects import postgresql as pg\n"
        "session.execute(pg.insert(Dataset), [{'origin_ref': ref}])",
        "import sqlalchemy.dialects.postgresql\n"
        "session.execute(sqlalchemy.dialects.postgresql.insert(Dataset), "
        "[{'origin_uri': u}])",
        "import sqlalchemy as sqla\n"
        "session.execute(sqla.sql.expression.update(Dataset), [{'origin_ref': ref}])",
        "from sqlalchemy import sql\n"
        "session.execute(sql.update(Dataset), [{'origin_ref': ref}])",
        "import sqlalchemy as sqla\nu = sqla.update\n"
        "session.execute(u(Dataset), [{'origin_ref': ref}])",
        "import sqlalchemy as sqla\nup = partial(sqla.update, Dataset)\n"
        "session.execute(up(), [{'origin_uri': u}])",
        "Model = Dataset\nModel(origin_ref=ref)",
        # Other spellings of a column reference.
        "update(t).values({t.c['origin_ref']: ref})",
        "update(t).values({t.columns['origin_uri']: u})",
        "update(t).values({literal_column('origin_ref'): ref})",
        "update(t).values({column('origin_uri'): u})",
        "def f(session, ref):\n    q = session.query(Dataset).filter(Dataset.id == 1)\n"
        "    q.update({'origin_ref': ref})",
        # Raw SQL, any target spelling and statement.
        "text('INSERT INTO catalog.datasets AS d (id, origin_ref) VALUES (:i, :r)')",
        'text(\'INSERT INTO "catalog"."datasets" (id, "origin_uri") VALUES (:i, :u)\')',
        "text('INSERT INTO catalog.\"datasets\" AS d VALUES (:id, :title)')",
        "text('INSERT INTO catalog.datasets SELECT * FROM staging')",
        "text('INSERT INTO datasets DEFAULT VALUES')",
        "text('INSERT INTO catalog.datasets OVERRIDING SYSTEM VALUE VALUES (:a)')",
        "text('WITH s AS (SELECT 1) INSERT INTO catalog.datasets SELECT * FROM s')",
        "text('UPDATE ONLY catalog.datasets AS d SET origin_uri = s.u "
        "FROM staging s WHERE s.id = d.id')",
        'text(\'UPDATE "catalog"."datasets" d SET title = s.t, origin_ref = s.r '
        "FROM s WHERE s.id = d.id')",
        "text('MERGE INTO catalog.datasets d USING s ON s.id = d.id "
        "WHEN MATCHED THEN UPDATE SET origin_ref = s.r')",
        "text('MERGE INTO catalog.datasets d USING s ON s.id = d.id "
        "WHEN NOT MATCHED THEN INSERT (id, origin_uri) VALUES (s.id, s.u)')",
        "text('MERGE INTO catalog.datasets AS d USING s ON true "
        "WHEN NOT MATCHED THEN INSERT VALUES (s.a, s.b)')",
        "text('INSERT INTO catalog.datasets (id, title) VALUES (:i, :t) "
        "ON CONFLICT (id) DO UPDATE SET origin_ref = EXCLUDED.origin_ref')",
        "text('COPY catalog.datasets (id, origin_ref) FROM STDIN')",
        'text(\'COPY "catalog"."datasets" FROM STDIN\')',
        "text('UPDATE catalog.datasets SET origin_ref /* json */ = :r')",
        "text(f'INSERT INTO {schema}.datasets (id, origin_ref) VALUES (:i, :r)')",
        "text('INSERT INTO ' + table + ' (id, origin_uri) VALUES (:i, :u)')",
        "session.execute(text(sql), {'origin_ref': ref})",
        # Attribute writes by name.
        "set_attribute(dataset, 'origin_ref', ref)",
        "set_committed_value(dataset, 'origin_uri', u)",
        "set_attribute(instance=dataset, key='origin_ref', value=ref)",
        "delattr(dataset, 'origin_uri')",
        "text('INSERT INTO ONLY catalog.datasets VALUES (:a, :b)')",
        "dataset.__dict__['origin_ref'] = ref",
        "dataset.__setattr__('origin_ref', ref)",
        "object.__setattr__(dataset, 'origin_uri', u)",
        # The stored dict changed in place.
        "dict.update(dataset.origin_ref, token=t)",
        "def f(dataset, t):\n    ref = dataset.origin_ref\n    ref['token'] = t",
        "def f(dataset, t):\n    ref = dataset.origin_ref or {}\n"
        "    ref.update(token=t)",
        "def f(dataset, extra):\n    ref = dataset.origin_ref\n    ref |= extra",
        "getattr(dataset, 'origin_ref').update(token=t)",
        "getattr(dataset, 'origin_ref')['token'] = t",
        "operator.setitem(dataset.origin_ref, 'token', t)",
        # Every way a local name can come to hold the stored dict.
        "def f(dataset, t):\n    ref: dict = dataset.origin_ref\n    ref['token'] = t",
        "def f(dataset, t):\n    if (ref := dataset.origin_ref):\n"
        "        ref['token'] = t",
        "def f(dataset, x, t):\n    ref, other = dataset.origin_ref, x\n"
        "    ref['token'] = t",
        "[ref, other] = [dataset.origin_ref, x]\nref.update(token=t)",
        "def f(dataset, t):\n    for ref in (dataset.origin_ref,):\n"
        "        ref['token'] = t",
        "[ref.update(token=t) for ref in [dataset.origin_ref]]",
        "def f(dataset, t):\n    with dataset.origin_ref as ref:\n"
        "        ref['token'] = t",
        "with nullcontext(dataset.origin_ref) as ref:\n    ref['token'] = t",
        "def f(dataset, t):\n    a = dataset.origin_ref\n    b = a\n    b['token'] = t",
        "ref = dataset.origin_ref if c else {}\nref['token'] = t",
        "b = (a := dataset.origin_ref)\nb['token'] = t",
        # Across scope boundaries.
        "def outer(dataset, t):\n    ref = dataset.origin_ref\n"
        "    def inner():\n        ref.update(token=t)\n    inner()",
        "def outer(dataset, t):\n    ref = dataset.origin_ref\n"
        "    touch = lambda: ref.update(token=t)\n    touch()",
        "def outer(dataset, t):\n    ref = dataset.origin_ref\n"
        "    def touch():\n        nonlocal ref\n        ref |= {'token': t}\n    touch()",
        "def outer(dataset, t):\n    ref = {}\n    def bind():\n        nonlocal ref\n"
        "        ref = dataset.origin_ref\n    bind()\n    ref['token'] = t",
        "ref = None\ndef bind(dataset):\n    global ref\n    ref = dataset.origin_ref\n"
        "def touch(t):\n    ref['token'] = t",
        "ref = dataset.origin_ref\ndef outer():\n    ref = {}\n    def touch(t):\n"
        "        global ref\n        ref |= {'token': t}",
        "ref = dataset.origin_ref\ndef touch(t):\n    ref['token'] = t",
        "class Holder:\n    ref = dataset.origin_ref\n    def touch(self, t):\n"
        "        self.ref['token'] = t",
        "class Holder:\n    ref = dataset.origin_ref\n    @classmethod\n"
        "    def touch(cls, t):\n        cls.ref |= {'token': t}",
        "class Holder:\n    ref = dataset.origin_ref\ndef touch(t):\n"
        "    Holder.ref.update(token=t)",
        "def outer(dataset, t):\n    def touch():\n        ref['token'] = t\n"
        "    ref = dataset.origin_ref\n    touch()",
        # Definition headers run in the enclosing scope, bodies in their own.
        "f = lambda dataset: ((ref := dataset.origin_ref), ref.update(token='x'))",
        "def outer(dataset):\n    def inner(x=(ref := dataset.origin_ref)):\n"
        "        return x\n    ref.update(token='x')",
        "def outer(dataset):\n    def inner(*, x=(ref := dataset.origin_ref)):\n"
        "        return x\n    ref.update(token='x')",
        "def outer(dataset):\n    @register((ref := dataset.origin_ref))\n"
        "    def inner():\n        pass\n    ref.update(token='x')",
        "def outer(dataset):\n    class Holder((ref := dataset.origin_ref).__class__):\n"
        "        pass\n    ref.update(token='x')",
        "def outer(dataset):\n    class Holder(meta=(ref := dataset.origin_ref)):\n"
        "        pass\n    ref.update(token='x')",
        "def outer(dataset):\n    f = lambda x=(ref := dataset.origin_ref): x\n"
        "    ref.update(token='x')",
        "def outer(dataset):\n    [(ref := dataset.origin_ref) for _ in range(1)]\n"
        "    ref.update(token='x')",
        "class Holder:\n    ref = dataset.origin_ref\n    ref['token'] = 't'",
        "def outer(dataset):\n    ref = dataset.origin_ref\n"
        "    def inner(ref=ref.update(token='x')):\n        return ref",
        "def outer(r):\n    changes = {'origin_ref': r}\n    def run():\n"
        "        return update(Dataset).values(**changes)\n    return run()",
        "def outer(session, r):\n    q = session.query(Dataset)\n    def run():\n"
        "        q.update({'origin_ref': r})\n    run()",
        "def f(dataset):\n    ref = getattr(dataset, 'origin_ref')\n"
        "    del ref['token']",
        # Bulk loaders.
        "await conn.copy_records_to_table('datasets', records=rows, "
        "schema_name='catalog')",
        "await conn.copy_records_to_table('staging', records=rows, "
        "columns=['id', 'origin_ref'])",
        "frame.to_sql('datasets', engine, schema='catalog', if_exists='append')",
        "vars(dataset)['origin_uri'] = u",
    ],
)
def test_the_scan_sees_a_write(snippet: str) -> None:
    assert binding_writes(snippet), snippet


@pytest.mark.parametrize(
    "snippet",
    [
        "pointer = (dataset.origin_uri, dataset.origin_ref, dataset.source_format)",
        "Dataset.origin_ref['url'].astext == base_url",
        "_write_reupload_catalog(session, origin_ref={'filename': name})",
        "DatasetResponse(origin_uri=dataset.origin_uri)",
        "origin_ref = {'filename': name}",
        "origin_ref['filename'] = name",
        "payload.update({'origin_ref': ref})",
        "payload.update(origin_uri=uri)",
        "response.values()",
        "session.execute(select(Dataset.origin_ref))",
        "update(Dataset).values({Dataset.title: title})",
        "update(Record).values({Record.origin_ref: ref})",
        "insert(DatasetAsset).values(key=k).on_conflict_do_update("
        "constraint='uq', set_={'href': stmt.excluded.href})",
        "def f(t):\n    changes = {'title': t}\n"
        "    return update(Dataset).values(**changes)",
        "def f(payload, ref):\n    payload['origin_ref'] = ref\n    return payload",
        "session.query(Dataset).filter(Dataset.origin_ref.is_(None))"
        ".update({'title': t})",
        "update(Dataset).where(Dataset.origin_ref == ref).values(title=t)",
        "vars(dataset)['title'] = t",
        "def f(dataset):\n    uri = dataset.origin_uri\n    uri += '/1'\n"
        "    return uri",
        "getattr(dataset, 'origin_ref').get('url')",
        "def f(dataset, x, t):\n    other, ref = dataset.origin_ref, x\n"
        "    ref['token'] = t",
        "def f(dataset, t):\n    ref = dict(dataset.origin_ref)\n    b = ref\n"
        "    b['token'] = t",
        "def f(dataset, payload):\n    for key in dataset.origin_ref:\n"
        "        payload[key] = 1",
        "def outer(dataset, t):\n    ref = dataset.origin_ref\n"
        "    def inner(ref):\n        ref['token'] = t",
        "def outer(dataset, t):\n    ref = dataset.origin_ref\n"
        "    def inner():\n        ref = {}\n        ref['token'] = t",
        "class Holder:\n    ref = {}\n    def touch(self, t):\n"
        "        self.ref['token'] = t",
        "def outer(t):\n    changes = {'title': t}\n    def run():\n"
        "        return update(Dataset).values(**changes)\n    return run()",
        # An alias inside a nested scope stays there.
        "class Holder:\n    ref = dataset.origin_ref\n    def touch(self):\n"
        "        ref.update(title='x')",
        "def outer(dataset):\n    ref = {}\n    def inner():\n"
        "        ref = dataset.origin_ref\n        return ref\n"
        "    ref.update(title='x')\n    return inner",
        "def outer(dataset):\n    ref = {}\n"
        "    peek = lambda: (ref := dataset.origin_ref)\n"
        "    ref.update(title='x')\n    return peek",
        "def outer(dataset):\n    ref = {}\n    class Holder:\n"
        "        ref = dataset.origin_ref\n    ref.update(title='x')\n    return Holder",
        "def outer(r, t):\n    changes = {'title': t}\n    def inner():\n"
        "        changes = {'origin_ref': r}\n        return changes\n"
        "    return update(Dataset).values(**changes)",
        "def outer(r, t):\n    changes = {'title': t}\n    def inner():\n"
        "        changes = {}\n        changes['origin_ref'] = r\n        return changes\n"
        "    return update(Dataset).values(**changes)",
        "frame.to_sql('dataset_stats', engine)",
        "await conn.copy_records_to_table('datasets', records=rows, "
        "columns=['id', 'title'])",
        "import sqlalchemy as sqla\n"
        "session.execute(sqla.select(Dataset.id), [{'origin_ref': ref}])",
        "def f(session, q, ref):\n    result = dict(session.execute(q).one())\n"
        "    result.update({'origin_ref': ref})\n    return result",
        "def f(dataset):\n    ref = dict(dataset.origin_ref or {})\n"
        "    ref['token'] = 1\n    return ref",
        "text('COPY catalog.datasets (id, origin_ref) TO STDOUT')",
        "text('INSERT INTO catalog.datasets (id, title) VALUES (:i, :t)')",
        "text('UPDATE catalog.datasets SET title = :t FROM s WHERE s.origin_ref = :r')",
        "text('MERGE INTO catalog.datasets d USING s ON s.id = d.id "
        "WHEN MATCHED THEN UPDATE SET title = s.t')",
        "text('INSERT INTO catalog.dataset_versions VALUES (:a, :b)')",
        "text('UPDATE catalog.datasets d SET title = s.t "
        "FROM s JOIN x ON x.origin_ref = s.r')",
        "text('SELECT origin_ref FROM catalog.datasets -- SET origin_ref = x')",
        "text(f'SELECT origin_ref FROM {schema}.datasets WHERE id = :i')",
        "setattr(dataset, 'title', t)",
        "insert(Dataset).from_select(['id', 'title'], query)",
        "text('UPDATE catalog.datasets SET (title, summary) = (:t, :s) "
        "WHERE origin_ref = :r')",
        'text("UPDATE catalog.datasets SET last_checked_at = now() '
        "WHERE origin_ref['url'] = :u\")",
        "session.execute(text('SELECT id FROM catalog.datasets "
        "WHERE origin_ref = :origin_ref'), params={'origin_ref': ref})",
        "class DatasetModel(BaseModel):\n    origin_ref: dict | None = None\n"
        "DatasetModel(origin_ref={'kind': 'upload'})",
        "from app.modules.catalog.datasets.domain.schemas import DatasetResponse "
        "as DatasetModel\nDatasetModel(origin_uri=uri)",
        "session.execute(text('SELECT id FROM catalog.datasets "
        "WHERE origin_ref = :origin_ref'), {'origin_ref': ref})",
        "session.execute(select(Dataset.id).where(Dataset.origin_uri == bindparam("
        "'origin_uri')), {'origin_uri': uri})",
        "text('UPDATE catalog.datasets SET last_checked_at = now() "
        "WHERE origin_ref = :ref')",
        "text(\"INSERT INTO v (h) SELECT origin_ref->>'file_hash' FROM d\")",
    ],
)
def test_the_scan_leaves_a_read_alone(snippet: str) -> None:
    assert binding_writes(snippet) == [], snippet


def test_only_the_dataset_model_maps_the_columns() -> None:
    """A write that names the columns can only target catalog.datasets, so the scan needn't resolve the table."""
    mapped = set()
    for path in sorted(APP_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if not _may_write(source):
            continue
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if (
                        isinstance(item, ast.AnnAssign)
                        and isinstance(item.target, ast.Name)
                        and item.target.id in COLUMNS
                        and isinstance(item.value, ast.Call)
                        and _terminal_name(item.value.func)
                        in {"mapped_column", "Column"}
                    ):
                        mapped.add(
                            (path.relative_to(BACKEND_ROOT).as_posix(), node.name)
                        )
            elif (
                isinstance(node, ast.Call)
                and _terminal_name(node.func) == "Column"
                and node.args
                and _names_a_column(node.args[0])
            ):
                mapped.add((path.relative_to(BACKEND_ROOT).as_posix(), "Column"))
    assert mapped == {("app/modules/catalog/datasets/domain/models.py", "Dataset")}


def test_the_file_filter_keeps_upper_case_and_positional_writes() -> None:
    assert _may_write("text('UPDATE catalog.datasets SET ORIGIN_URI = :u')")
    assert not _may_write("text('UPDATE catalog.datasets SET title = :t')")
    assert _may_write("text('INSERT INTO catalog.datasets VALUES (:a, :b)')")

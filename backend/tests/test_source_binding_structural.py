"""Only ``platform/dataset_origin.py`` writes a dataset's origin pointer.

``origin_uri`` and ``origin_ref`` change only through ``set_dataset_origin`` and
``set_postgis_origin``, which run ``build_origin_ref``'s allowlist (ADR-002
invariant 4) and clear the stored probe verdict. This walks every module under
``backend/app/`` and fails on any other write it can see:

- ORM attributes: assignment, ``del``, item writes, ``|=`` and mutating methods
  on the stored dict (reached as ``x.origin_ref``, ``getattr(x, "origin_ref")``
  or a local name bound to either, and through ``dict.update`` or
  ``operator.setitem``), ``setattr``/``set_attribute``/``set_committed_value``/
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

Out of reach: names and SQL built at runtime (a computed attribute, column or
table name, a mapping built with ``zip`` or a comprehension, SQL assembled
across variables, from a list or read from a file), a mapping, statement or
alias of the stored dict that arrives as a parameter, through an attribute or
container, or from another module, SQL in database functions and triggers,
migrations (outside ``backend/app/``), and ``source_format``, which several
publication paths write beside the setter.
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
# Bulk loaders that take a table name and, optionally, the columns they fill.
_TABLE_LOADERS = frozenset({"copy_records_to_table", "copy_to_table", "to_sql"})
# Calls that set an attribute named by a string argument.
_SETTERS = frozenset({"setattr", "set_attribute", "set_committed_value", "__setattr__"})

# Raw SQL is matched after comments and double quotes are dropped, case is
# lowered and whitespace is collapsed, so any identifier quoting matches.
_SQL_COMMENT = re.compile(r"/\*.*?\*/|--[^\n]*", re.DOTALL)
_COLUMN = r"\borigin_(?:ref|uri)\b"
_DATASETS = (
    r"(?:\w+\.)?datasets\b"
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

        ``Dataset.origin_ref``, ``t.c.origin_uri``, ``t.c["origin_ref"]``,
        ``t.columns["origin_ref"]`` or ``column("origin_ref")``.
        """
        if _is_column(node):
            base = _terminal_name(node.value)
            if base in self.dataset_names or base == "c":
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


class _Scope:
    """Column mentions in a write's arguments, following local names one level."""

    def __init__(self, module: _Module, scope: ast.AST) -> None:
        self.module = module
        self.scope = scope
        self._stored_aliases: frozenset[str] | None = None

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
        for node in ast.walk(self.scope):
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                if node.value is not None and any(
                    isinstance(t, ast.Name) and t.id == name for t in targets
                ):
                    yield node.value

    def assigned(self, name: str) -> list[str]:
        """Columns a local mapping gets as keys anywhere in this scope."""
        found: list[str] = []
        for value in self._assignments(name):
            found.extend(self.mentions(value, follow=False))
        for node in ast.walk(self.scope):
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
        """Whether a local name holds an ORM ``Query``."""
        return any(
            isinstance(value, ast.Call)
            and any(
                _terminal_name(r.func) == "query" for r in [value, *_receivers(value)]
            )
            for value in self._assignments(name)
        )

    def stored_aliases(self) -> frozenset[str]:
        """Local names bound to a stored ``origin_ref``/``origin_uri`` value."""
        if self._stored_aliases is None:
            names = set()
            for node in ast.walk(self.scope):
                if not isinstance(node, ast.Assign):
                    continue
                value = node.value
                parts = value.values if isinstance(value, ast.BoolOp) else [value]
                if any(_reads_stored(part) for part in parts):
                    names.update(t.id for t in node.targets if isinstance(t, ast.Name))
            self._stored_aliases = frozenset(names)
        return self._stored_aliases

    def stored_dict(self, node: ast.AST) -> str | None:
        """What a reference to the stored dict is called, if the node is one."""
        if column := _reads_stored(node):
            return column
        if isinstance(node, ast.Name) and node.id in self.stored_aliases():
            return f"the origin pointer through {node.id}"
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
    if name in _SETTERS and any(_names_a_column(arg) for arg in call.args[:2]):
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
    if (
        isinstance(node, ast.AugAssign)
        and isinstance(node.op, ast.BitOr)
        and isinstance(node.target, ast.Name)
    ):
        if node.target.id in scope.stored_aliases():
            return [f"updates the origin pointer through {node.target.id} in place"]
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
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function = node.name
            scope = _Scope(module, node)
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

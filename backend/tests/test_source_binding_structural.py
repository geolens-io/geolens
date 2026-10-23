"""Only ``platform/dataset_origin.py`` writes a dataset's origin pointer.

``origin_uri`` and ``origin_ref`` change only through ``set_dataset_origin`` and
``set_postgis_origin``, which run ``build_origin_ref``'s allowlist (ADR-002
invariant 4) and clear the stored probe verdict. This walks every module under
``backend/app/`` and fails on any other write it can see:

- ORM attributes: assignment, ``del``, item writes and mutating methods on the
  stored dict, ``setattr``/``set_attribute``/``set_committed_value`` by name,
  and ``__dict__``/``vars()`` items.
- The model's constructor (under any alias), with the columns as keywords or as
  keys of a ``**`` mapping.
- SQLAlchemy statements: ``update``/``insert`` (bare, through ``sa``, a dialect
  module or an import alias, or a table's own ``update()``/``insert()``) and the
  methods that name written columns (``values``, ``ordered_values``,
  ``on_conflict_do_update``, ``on_duplicate_key_update``, ``from_select``), the
  legacy ``Query.update()``, ``bulk_*_mappings`` and ``execute()`` parameters.
  Columns count as keywords, ``dict(...)`` keywords, string keys, model or
  ``table.c`` attribute keys, and ``(column, value)`` pairs; a mapping passed by
  local name is followed to the keys it gets in the same function.
- Raw SQL text that sets the columns or inserts them into ``datasets``.

Inside the owner module, each write is counted by the function it sits in, so
a second write site, or a write outside the setter, fails too.

Out of reach: names and SQL built at runtime (string formatting, a computed
attribute name), a mapping that arrives as a parameter or from another module,
and ``source_format``, which several publication paths write beside the setter.
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
# SQLAlchemy's statement builders, called bare, through the module, or through
# a dialect module (postgresql.insert).
_STATEMENTS = frozenset({"update", "insert"})
_SQLALCHEMY_MODULES = frozenset({"sa", "sqlalchemy", "postgresql", "mysql", "sqlite"})
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
# Calls that set an attribute named by a string argument.
_SETTERS = frozenset({"setattr", "set_attribute", "set_committed_value"})
_SQL_WRITE = re.compile(
    r"\bSET\b(?:(?!\bWHERE\b)[^;])*?\borigin_(?:ref|uri)\"?"
    # A JSON subscript or path between the column and ``=`` still writes it.
    r"(?:\s*\[[^\]]*\]|\s*->>?\s*'[^']*')*\s*=(?!=)"
    # A row-valued SET: SET (title, origin_ref) = (...).
    r"|\bSET\s*\([^)]*\borigin_(?:ref|uri)\b[^)]*\)\s*="
    r"|\bINSERT\s+INTO\s+[\w.\"]*datasets\"?\s*\([^)]*\borigin_(?:ref|uri)\b",
    re.IGNORECASE,
)


def _terminal_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_column(node: ast.expr) -> bool:
    return isinstance(node, ast.Attribute) and node.attr in COLUMNS


def _names_a_column(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value in COLUMNS


def _may_write(source: str) -> bool:
    """Whether the text names a column at all, in any case, so it is worth parsing."""
    lowered = source.lower()
    return any(column in lowered for column in COLUMNS)


def _is_sql_write(text: object) -> bool:
    return (
        isinstance(text, str)
        and "origin_" in text.lower()
        and _SQL_WRITE.search(text) is not None
    )


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
    """One module's names for the model and the statement builders."""

    def __init__(self, tree: ast.AST) -> None:
        dataset_names = {"Dataset"}
        statement_names = set(_STATEMENTS)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "Dataset":
                        dataset_names.add(alias.asname or alias.name)
                    if alias.name in _STATEMENTS and (node.module or "").startswith(
                        "sqlalchemy"
                    ):
                        statement_names.add(alias.asname or alias.name)
            elif (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and _terminal_name(node.value.func) == "get_dataset_orm_class"
            ):
                dataset_names.update(
                    t.id for t in node.targets if isinstance(t, ast.Name)
                )
        self.dataset_names = frozenset(dataset_names)
        self.statement_names = frozenset(statement_names)

    def is_builder(self, call: ast.Call) -> bool:
        """``update(...)``/``insert(...)``, or a table's own ``update()``/``insert()``."""
        func = call.func
        if isinstance(func, ast.Name):
            return func.id in self.statement_names
        if not isinstance(func, ast.Attribute) or func.attr not in _STATEMENTS:
            return False
        if _terminal_name(func.value) in _SQLALCHEMY_MODULES:
            return True
        # Table.update()/insert() take no arguments; dict.update() with none
        # writes nothing, so reading it as a table is harmless.
        return not call.args and not call.keywords

    def column_ref(self, node: ast.AST) -> str | None:
        """The column a model or table attribute names: ``Dataset.origin_ref``, ``t.c.origin_uri``."""
        if not _is_column(node):
            return None
        base = node.value
        if _terminal_name(base) in self.dataset_names or _terminal_name(base) == "c":
            return node.attr
        return None

    def binds_a_write(self, statement: ast.expr) -> bool:
        """Whether execute()'s parameters are row values: the statement writes, or is unknown.

        A statement passed by name can't be read here, so its parameters are checked.
        """
        if isinstance(statement, (ast.Name, ast.Attribute)):
            return True
        return any(
            (isinstance(node, ast.Call) and self.is_builder(node))
            or (isinstance(node, ast.Constant) and _is_sql_write(node.value))
            for node in ast.walk(statement)
        )


class _Scope:
    """Column mentions in a write's arguments, following local names one level."""

    def __init__(self, module: _Module, scope: ast.AST) -> None:
        self.module = module
        self.scope = scope

    def mentions(self, node: ast.AST, *, follow: bool = True) -> list[str]:
        found: list[str] = []
        for inner in ast.walk(node):
            if isinstance(inner, ast.Dict):
                for key in inner.keys:
                    if _names_a_column(key):
                        found.append(key.value)
                    elif ref := self.module.column_ref(key):
                        found.append(ref)
            elif isinstance(inner, ast.Call) and _terminal_name(inner.func) == "dict":
                found.extend(kw.arg for kw in inner.keywords if kw.arg in COLUMNS)
            elif isinstance(inner, ast.Tuple) and inner.elts:
                # ordered_values() takes (column, value) pairs.
                first = inner.elts[0]
                if _names_a_column(first):
                    found.append(first.value)
                elif ref := self.module.column_ref(first):
                    found.append(ref)
            elif follow and isinstance(inner, ast.Name):
                found.extend(self.assigned(inner.id))
        return found

    def assigned(self, name: str) -> list[str]:
        """Columns a local mapping gets as keys anywhere in this scope."""
        found: list[str] = []
        for node in ast.walk(self.scope):
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                if node.value is not None and any(
                    isinstance(t, ast.Name) and t.id == name for t in targets
                ):
                    found.extend(self.mentions(node.value, follow=False))
            elif (
                isinstance(node, ast.Subscript)
                and isinstance(node.ctx, ast.Store)
                and isinstance(node.value, ast.Name)
                and node.value.id == name
            ):
                if _names_a_column(node.slice):
                    found.append(node.slice.value)
                elif ref := self.module.column_ref(node.slice):
                    found.append(ref)
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
                    if _names_a_column(node.args[0]):
                        found.append(node.args[0].value)
        return found

    def call_mentions(self, call: ast.Call, args: list[ast.expr]) -> list[str]:
        found = [kw.arg for kw in call.keywords if kw.arg in COLUMNS]
        for arg in args:
            found.extend(self.mentions(arg))
        return found


def _call_writes(call: ast.Call, scope: _Scope) -> list[str]:
    module = scope.module
    func = call.func
    name = _terminal_name(func)
    if (
        isinstance(func, ast.Attribute)
        and func.attr in _DICT_MUTATORS
        and _is_column(func.value)
    ):
        return [f"mutates .{func.value.attr} with .{func.attr}()"]
    if name in _SETTERS and len(call.args) >= 2 and _names_a_column(call.args[1]):
        return [f"{name}(..., {call.args[1].value!r}, ...)"]
    keyword_values = [kw.value for kw in call.keywords]
    if name in module.dataset_names:
        columns = scope.call_mentions(call, [*call.args, *keyword_values])
    elif module.is_builder(call):
        # The table is the argument; a legacy values= keyword holds the row.
        columns = scope.call_mentions(call, keyword_values)
    elif isinstance(func, ast.Attribute) and name in _WRITE_METHODS:
        if name == "values" and not call.args and not call.keywords:
            return []
        columns = scope.call_mentions(call, [*call.args, *keyword_values])
        if name == "from_select" and call.args:
            columns.extend(
                element.value if _names_a_column(element) else element.attr
                for element in getattr(call.args[0], "elts", [])
                if _names_a_column(element) or module.column_ref(element)
            )
    elif (
        isinstance(func, ast.Attribute)
        and name == "update"
        and any(_terminal_name(r.func) == "query" for r in _receivers(call))
    ):
        # Query.update(), the legacy ORM bulk update.
        columns = scope.call_mentions(call, [*call.args, *keyword_values])
    elif isinstance(func, ast.Attribute) and name == "execute":
        keywords = {kw.arg: kw.value for kw in call.keywords if kw.arg}
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
    if stored and isinstance(node, ast.Subscript):
        if _is_column(node.value):
            return [f"writes an item of .{node.value.attr}"]
        # obj.__dict__["origin_ref"] or vars(obj)["origin_ref"]
        holder = node.value
        if _names_a_column(node.slice) and (
            _terminal_name(holder) == "__dict__"
            or (isinstance(holder, ast.Call) and _terminal_name(holder.func) == "vars")
        ):
            return [f"writes {node.slice.value} through __dict__"]
    if isinstance(node, ast.Call):
        return _call_writes(node, scope)
    if isinstance(node, ast.Constant) and _is_sql_write(node.value):
        return ["raw SQL writes the column"]
    return []


def binding_writes(source: str) -> list[tuple[int, str | None, str]]:
    """Every write to the binding columns this module's text shows.

    Each is ``(line, enclosing function or None, description)``.
    """
    found: list[tuple[int, str | None, str]] = []
    tree = ast.parse(source)
    module = _Module(tree)

    def visit(node: ast.AST, function: str | None, scope: _Scope) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function = node.name
            scope = _Scope(module, node)
        found.extend(
            (node.lineno, function, what) for what in _node_writes(node, scope)
        )
        for child in ast.iter_child_nodes(node):
            visit(child, function, scope)

    visit(tree, None, _Scope(module, tree))
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
        # Attribute writes by name.
        "set_attribute(dataset, 'origin_ref', ref)",
        "set_committed_value(dataset, 'origin_uri', u)",
        "dataset.__dict__['origin_ref'] = ref",
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


def test_a_module_naming_a_column_only_in_upper_case_is_still_scanned() -> None:
    assert _may_write("text('UPDATE catalog.datasets SET ORIGIN_URI = :u')")
    assert not _may_write("text('UPDATE catalog.datasets SET title = :t')")

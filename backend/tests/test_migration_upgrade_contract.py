"""Migration upgrades must not break the previous release during a rolling upgrade.

While an upgrade rolls out, processes from the previous release keep serving
against the migrated schema. An ``upgrade()`` that drops or renames a column
or table, or narrows a column, breaks every old process that still reads it.
AGENTS.md ("Code Review Rules") requires expand/contract instead: keep the old
form for one release and drop it in a later minor.

This module parses every ``backend/alembic/versions/*.py`` and inspects the
code ``upgrade()`` can reach: its body plus the module-level functions and
constants it names, transitively. ``downgrade()`` is free to drop. It flags
destructive Alembic operations, SQL text that spells them, and, as a
backstop, any string mentioning ``DROP``/``RENAME`` that no pattern explains.
Existing hits live in ``ALLOWLIST`` with an exact hit count and a reason; the
allowlist only shrinks.

Known limits: SQL assembled at runtime from non-literal pieces is read with
``{}`` in place of each piece, helpers imported from other modules are not
followed (no migration imports one), and a new or tighter CHECK constraint is
left to review.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"

_RULE = (
    "AGENTS.md 'Code Review Rules': keep the old column or table for one "
    "release and drop it in a later minor (expand/contract)"
)

_DESTRUCTIVE_OPS = frozenset({"drop_column", "drop_table", "rename_table"})

_SQL_PATTERNS = {
    "DROP COLUMN": re.compile(r"\bDROP\s+COLUMN\b", re.IGNORECASE),
    "DROP TABLE": re.compile(r"\bDROP\s+TABLE\b", re.IGNORECASE),
    "RENAME COLUMN": re.compile(r"\bRENAME\s+COLUMN\b", re.IGNORECASE),
    "RENAME TO": re.compile(r"\bRENAME\s+TO\b", re.IGNORECASE),
    "SET NOT NULL": re.compile(r"\bSET\s+NOT\s+NULL\b", re.IGNORECASE),
    "ALTER COLUMN ... TYPE": re.compile(
        r"\bALTER\s+(?:COLUMN\s+)?(?:\"[^\"]+\"|\w+)\s+(?:SET\s+DATA\s+)?TYPE\b",
        re.IGNORECASE,
    ),
}

# Drops the previous release never reads: planner objects, row policies and
# triggers rebuilt in the same step, and constraints that only widen a column.
_HARMLESS_DROP = re.compile(
    r"\bDROP\s+(?:INDEX|POLICY|TRIGGER|CONSTRAINT|DEFAULT|NOT\s+NULL)\b",
    re.IGNORECASE,
)

_BACKSTOP = re.compile(r"\b(?:DROP|RENAME)\s", re.IGNORECASE)

# filename -> (exact hit count, why the hit stays)
ALLOWLIST: dict[str, tuple[int, str]] = {
    "0012_type_embedding_vector.py": (
        1,
        "types the unbounded embedding column to the dimension the release "
        "already writes; rows are a regenerable cache",
    ),
    "0014_record_translations.py": (1, "widens language from varchar(10) to 35"),
    "0019_tenant_provisioning_boundary.py": (
        7,
        "DROP SCHEMA/ROLE sit in the body of the function it creates and in "
        "SQL comments; the upgrade drops nothing",
    ),
    "0023_tenant_slug_unique.py": (1, "'Rename or merge' is English in a HINT"),
    "0026_db_audit_naming_cleanup.py": (
        1,
        "renames per-dataset primary-key constraints no release refers to",
    ),
    "0029_api_key_hardening.py": (
        1,
        "shipped in 1.6.1: api_keys.key_epoch got NOT NULL without a default, "
        "so 1.6.0 could not mint keys until it was replaced",
    ),
    "0030_records_spatial_extent_type.py": (
        1,
        "widens spatial_extent from Polygon to Geometry",
    ),
    "0034_linearize_geom_4326.py": (
        1,
        "widens a dataset table's geom_4326 typmod to the generic geometry",
    ),
    "0035_drop_quality_score_numeric.py": (
        1,
        "shipped in 1.10.0: the 1.9 Dataset model still mapped the column, so "
        "1.9 dataset queries failed until it was replaced",
    ),
    "0083_list_order_indexes.py": (1, "renames an index, not a table"),
    "0101_drop_dataset_previous_version_columns.py": (
        4,
        "drops the four datasets.previous_version_* columns that 0088 emptied; "
        "1.27 neither maps nor reads them",
    ),
}


def _render(node: ast.AST) -> str | None:
    """Return the text of a string expression, with ``{}`` for runtime pieces."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant) else "{}"
            for part in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        left = _render(node.left)
        if left is None:
            return None
        if isinstance(node.op, ast.Mod):
            return left
        right = _render(node.right)
        return left + ("{}" if right is None else right)
    return None


def _strings(node: ast.AST) -> list[ast.AST]:
    """Outermost string expressions under ``node`` except docstrings."""
    if _render(node) is not None:
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod):
            return [node, *_strings(node.right)]
        return [node]
    children = list(ast.iter_child_nodes(node))
    if (
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and ast.get_docstring(node, clean=False) is not None
    ):
        children = [c for c in children if c is not node.body[0]]
    found: list[ast.AST] = []
    for child in children:
        found.extend(_strings(child))
    return found


def _reachable_from_upgrade(tree: ast.Module) -> list[ast.AST]:
    """``upgrade()`` plus the module-level definitions it names, transitively."""
    defs: dict[str, ast.AST] = {}
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs[stmt.name] = stmt
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
            for target in targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name):
                        defs[name.id] = stmt
    if "upgrade" not in defs:
        return []
    defs.pop("downgrade", None)
    seen: list[ast.AST] = []
    queue = [defs["upgrade"]]
    while queue:
        node = queue.pop()
        if any(node is s for s in seen):
            continue
        seen.append(node)
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id in defs:
                queue.append(defs[sub.id])
    return seen


def _op_hit(call: ast.Call) -> str | None:
    if not isinstance(call.func, ast.Attribute):
        return None
    attr = call.func.attr
    if attr in _DESTRUCTIVE_OPS:
        return attr
    if attr != "alter_column":
        return None
    for kw in call.keywords:
        if kw.arg in ("new_column_name", "type_"):
            return f"alter_column({kw.arg}=...)"
        if (
            kw.arg == "nullable"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is False
        ):
            return "alter_column(nullable=False)"
        if kw.arg == "nullable" and not isinstance(kw.value, ast.Constant):
            return "alter_column(nullable=<expression>)"
    return None


def _hits(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    hits: list[str] = []
    for root in _reachable_from_upgrade(tree):
        for node in ast.walk(root):
            if isinstance(node, ast.Call) and (op := _op_hit(node)):
                hits.append(f"line {node.lineno}: op.{op}")
        for node in _strings(root):
            text = _render(node) or ""
            hits.extend(
                f"line {node.lineno}: SQL {label} at offset {m.start()}"
                for label, rx in _SQL_PATTERNS.items()
                for m in rx.finditer(text)
            )
            explained = {
                m.start()
                for rx in (*_SQL_PATTERNS.values(), _HARMLESS_DROP)
                for m in rx.finditer(text)
            }
            for m in _BACKSTOP.finditer(text):
                if m.start() not in explained:
                    snippet = " ".join(text[m.start() :].split())[:60]
                    hits.append(f"line {node.lineno}: unrecognized {snippet!r}")
    return sorted(hits, key=lambda h: int(h.split()[1].rstrip(":")))


def _all_hits() -> dict[str, list[str]]:
    return {
        path.name: hits
        for path in sorted(VERSIONS_DIR.glob("*.py"))
        if (hits := _hits(path))
    }


@pytest.mark.architecture
def test_migration_upgrades_keep_the_previous_release_working() -> None:
    assert any(VERSIONS_DIR.glob("0001_*.py")), f"no migrations under {VERSIONS_DIR}"
    problems = []
    for name, hits in _all_hits().items():
        expected = ALLOWLIST.get(name)
        if expected is None:
            problems.append(f"{name}: " + "; ".join(hits))
        elif expected[0] != len(hits):
            problems.append(
                f"{name}: expected {expected[0]} allowlisted hit(s), found "
                f"{len(hits)}: " + "; ".join(hits)
            )
    assert not problems, (
        f"upgrade() breaks the previous release. {_RULE}. If the old release "
        "cannot read the object, explain why in ALLOWLIST.\n" + "\n".join(problems)
    )


@pytest.mark.architecture
def test_allowlist_only_shrinks() -> None:
    hits = _all_hits()
    stale = sorted(name for name in ALLOWLIST if name not in hits)
    assert not stale, f"remove ALLOWLIST entries with no remaining hit: {stale}"


_UPGRADE_CASES = {
    "drop_column": 'op.drop_column("datasets", "a", schema="catalog")',
    "batch drop_table": 'batch_op.drop_table("old")',
    "rename_table": 'op.rename_table("a", "b")',
    "rename column": 'op.alter_column("t", "a", new_column_name="b")',
    "set not null": 'op.alter_column("t", "a", nullable=False)',
    "retype": 'op.alter_column("t", "a", type_=sa.Integer())',
    "implicit concat": 'op.execute("ALTER TABLE t " "drop  column a")',
    "plus concat": 'op.execute("ALTER TABLE t DROP " + "COLUMN a")',
    "percent operand": 'op.execute("ALTER TABLE t %s" % "DROP COLUMN a")',
    "f-string": 'op.execute(sa.text(f"ALTER TABLE {t} RENAME COLUMN a TO b"))',
    "alter type": 'op.execute("ALTER TABLE t ALTER a SET DATA TYPE int")',
    "set not null sql": 'op.execute("ALTER TABLE t ALTER COLUMN a\\n SET NOT NULL")',
    "drop table sql": 'op.execute("DROP TABLE IF EXISTS catalog.old")',
    "backstop": 'op.execute("ALTER TABLE t DROP a")',
    "helper": "_contract()",
    "constant": "op.execute(_SQL)",
}

_HELPERS = """
_SQL = "ALTER TABLE t DROP COLUMN a"


def _contract():
    op.drop_column("t", "a")
"""


@pytest.mark.architecture
@pytest.mark.parametrize("body", _UPGRADE_CASES.values(), ids=_UPGRADE_CASES)
def test_detects_contract_steps_in_upgrade(tmp_path: Path, body: str) -> None:
    path = tmp_path / "9999_case.py"
    path.write_text(f"{_HELPERS}\n\ndef upgrade():\n    {body}\n", encoding="utf-8")
    assert _hits(path), body


@pytest.mark.architecture
def test_counts_each_contract_statement_in_one_string(tmp_path: Path) -> None:
    path = tmp_path / "9999_case.py"
    path.write_text(
        'def upgrade():\n    op.execute("ALTER TABLE t DROP COLUMN a; '
        'ALTER TABLE t DROP COLUMN b")\n',
        encoding="utf-8",
    )
    assert len(_hits(path)) == 2


@pytest.mark.architecture
@pytest.mark.parametrize(
    "line",
    [
        'sql = ["DROP TABLE a", "DROP TABLE b"]',
        'op.drop_column("t", "a"); op.drop_column("t", "b")',
    ],
)
def test_counts_each_contract_step_on_one_line(tmp_path: Path, line: str) -> None:
    path = tmp_path / "9999_case.py"
    path.write_text(f"def upgrade():\n    {line}\n", encoding="utf-8")
    assert len(_hits(path)) == 2


@pytest.mark.architecture
def test_ignores_downgrade_docstrings_and_harmless_drops(tmp_path: Path) -> None:
    path = tmp_path / "9999_case.py"
    path.write_text(
        f"""{_HELPERS}

def upgrade():
    \"\"\"Drop nothing; DROP COLUMN appears only in this docstring.\"\"\"
    op.add_column("t", sa.Column("a", sa.Integer(), nullable=False))
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS catalog.ix_a")
    op.execute("DROP POLICY IF EXISTS p ON t; DROP TRIGGER IF EXISTS g ON t")
    op.execute("ALTER TABLE t ALTER COLUMN a DROP NOT NULL")


def downgrade():
    _contract()
    op.execute(_SQL)
""",
        encoding="utf-8",
    )
    assert _hits(path) == []

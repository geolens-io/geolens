"""Tests for the AST-based WHERE-clause validator.

Tests are grouped into:
  - test_allowlist_*  : expressions that MUST pass validate_where_ast()
  - test_blocklist_*  : expressions that MUST raise ValueError
  - test_wrapper_*    : integration tests for validate_where_clause (service layer)
  - test_endpoint_*   : HTTP-level tests against the export endpoint (require DB + live fixture)

Endpoint tests require a running DB and use the httpx AsyncClient from conftest.
They are skipped automatically when SEC_AUDIT_PUBLIC_DATASET_ID is not set.
"""

from __future__ import annotations

import os

import pytest

from app.processing.export.where_validator import canonical_where, validate_where_ast
from app.processing.export.service import validate_where_clause


# ─────────────────────────────────────────────────────────────────────────────
# Allowlist — these must pass (return None)
# ─────────────────────────────────────────────────────────────────────────────


class TestAllowlist:
    def test_allowlist_simple_gt(self):
        assert validate_where_ast("gid > 100") is None

    def test_allowlist_combined_and(self):
        assert validate_where_ast("state = 'CA' AND pop < 5000") is None

    def test_allowlist_like(self):
        assert validate_where_ast("name LIKE 'A%'") is None

    def test_allowlist_in_list(self):
        assert validate_where_ast("category IN ('a', 'b', 'c')") is None

    def test_allowlist_between(self):
        assert (
            validate_where_ast("created_at BETWEEN '2024-01-01' AND '2024-12-31'")
            is None
        )

    def test_allowlist_is_null(self):
        assert validate_where_ast("col IS NULL") is None

    def test_allowlist_is_not_null(self):
        assert validate_where_ast("col IS NOT NULL") is None

    def test_allowlist_complex_logical(self):
        assert validate_where_ast("(a > 1 OR b < 2) AND NOT c = 'x'") is None

    def test_allowlist_negative_number(self):
        """Unary minus on a numeric literal must pass."""
        assert validate_where_ast("score > -5") is None

    def test_allowlist_string_with_escaped_quote(self):
        """SQL single-quote escaping inside a string literal must pass."""
        assert validate_where_ast("name = 'O''Brien'") is None

    def test_allowlist_double_negation(self):
        assert validate_where_ast("NOT NOT (a > 1)") is None

    def test_allowlist_deeply_nested_parens(self):
        assert validate_where_ast("((((a > 1))))") is None

    def test_allowlist_mixed_case_keywords(self):
        """Keyword case variations must not affect allowlist evaluation."""
        assert validate_where_ast("a IN (1, 2) AND b BETWEEN 0 AND 10") is None

    def test_allowlist_neq_operator(self):
        assert validate_where_ast("status != 'inactive'") is None

    def test_allowlist_gte_and_lte(self):
        assert validate_where_ast("score >= 10 AND score <= 100") is None

    def test_allowlist_in_numeric_list(self):
        assert validate_where_ast("gid IN (1, 2, 3)") is None

    def test_allowlist_multiple_and_or(self):
        assert validate_where_ast("a > 1 AND b > 2 AND c > 3 OR d = 'x'") is None

    def test_allowlist_bool_column(self):
        """Boolean column comparison."""
        assert validate_where_ast("active = true") is None


# ─────────────────────────────────────────────────────────────────────────────
# Blocklist — these must raise ValueError
# ─────────────────────────────────────────────────────────────────────────────


class TestBlocklist:
    def test_blocklist_union_attack(self):
        """UNION grammar must be rejected as multi-statement / non-Select root."""
        with pytest.raises(ValueError, match="WHERE expression"):
            validate_where_ast("gid > 0 UNION SELECT 1, 2, 3")

    def test_blocklist_subquery_in(self):
        """Subquery inside IN clause must be rejected."""
        with pytest.raises(ValueError):
            validate_where_ast("gid IN (SELECT id FROM users)")

    def test_blocklist_subquery_exists(self):
        """EXISTS subquery must be rejected."""
        with pytest.raises(ValueError):
            validate_where_ast("EXISTS (SELECT 1 FROM users WHERE 1=1)")

    def test_blocklist_function_pg_sleep(self):
        with pytest.raises(ValueError):
            validate_where_ast("pg_sleep(10)")

    def test_blocklist_function_pg_read_file(self):
        with pytest.raises(ValueError):
            validate_where_ast("pg_read_file('/etc/passwd') IS NOT NULL")

    def test_blocklist_function_lower(self):
        """Even 'safe' function calls like lower() are rejected (strict allowlist)."""
        with pytest.raises(ValueError):
            validate_where_ast("lower(name) = 'x'")

    def test_blocklist_function_length(self):
        with pytest.raises(ValueError):
            validate_where_ast("length(name) > 5")

    def test_blocklist_multi_statement_drop(self):
        """Semicolon multi-statement with DDL must be rejected."""
        with pytest.raises(ValueError, match="WHERE expression|syntax"):
            validate_where_ast("1=1; DROP TABLE users; --")

    def test_blocklist_multi_statement_select(self):
        with pytest.raises(ValueError, match="WHERE expression|syntax"):
            validate_where_ast("1=1; SELECT 1")

    def test_blocklist_empty_string(self):
        with pytest.raises(ValueError, match="Empty WHERE expression"):
            validate_where_ast("")

    def test_blocklist_blank_whitespace(self):
        with pytest.raises(ValueError, match="Empty WHERE expression"):
            validate_where_ast("   ")

    def test_blocklist_invalid_syntax(self):
        """Invalid SQL syntax must raise ValueError."""
        with pytest.raises(ValueError):
            validate_where_ast("'; --")

    def test_blocklist_select_as_where(self):
        """A bare SELECT statement cannot serve as a WHERE expression."""
        with pytest.raises(ValueError):
            validate_where_ast("SELECT 1")

    def test_blocklist_union_intersect(self):
        """INTERSECT must also be caught as set-operation grammar."""
        with pytest.raises(ValueError):
            validate_where_ast("gid > 0 INTERSECT SELECT 1")

    def test_blocklist_subquery_scalar(self):
        """Scalar subquery must be rejected."""
        with pytest.raises(ValueError):
            validate_where_ast("gid = (SELECT MAX(gid) FROM data)")

    def test_blocklist_function_coalesce(self):
        """COALESCE is a function — must be rejected by strict allowlist."""
        with pytest.raises(ValueError):
            validate_where_ast("COALESCE(col, 0) > 1")

    def test_table_qualified_reference_rejected(self):
        """Pins the fix: sqlglot's postgres dialect parses tbl.col
        into exp.Column with .table populated (not a separate exp.Dot node).
        validate_where_ast inspects Column.table/.db/.catalog and raises
        with the 'table-qualified column reference' message.

        Removed the dead 'Dot' branch from the
        assertion — the validator uses Column.table inspection so 'Dot' never
        appears in the error message. Assert the exact rejection string instead."""
        with pytest.raises(ValueError) as exc:
            validate_where_ast("catalog.records.title = 'x'")
        # Error message names the table-qualified rejection specifically.
        assert "table-qualified" in str(exc.value).lower() or "Disallowed" in str(
            exc.value
        )

        # Two-segment table.column form (the more common attack shape).
        with pytest.raises(ValueError):
            validate_where_ast("records.title = 'x'")


# ─────────────────────────────────────────────────────────────────────────────
# Wrapper integration — validate_where_clause (service.py)
# ─────────────────────────────────────────────────────────────────────────────


_TRAILING = [
    "gid > 0 LIMIT 0",
    "gid > 0 OFFSET 1",
    "gid > 0 ORDER BY gid",
    "gid > 0 GROUP BY gid",
    "gid > 0 GROUP BY gid HAVING gid > 0",
    "gid > 0 FOR UPDATE",
    "gid > 0 FETCH FIRST 1 ROWS ONLY",
    "gid > 0 WINDOW w AS ()",
]


@pytest.mark.parametrize("where", _TRAILING)
def test_text_after_the_condition_is_refused(where):
    with pytest.raises(ValueError, match="Only a single WHERE expression"):
        validate_where_ast(where)


def test_a_render_that_does_not_reproduce_itself_is_refused(monkeypatch):
    from app.processing.export import where_validator

    real = where_validator._render
    monkeypatch.setattr(where_validator, "_render", lambda w: real(w) + " AND TRUE")
    with pytest.raises(ValueError, match="Disallowed expression"):
        canonical_where("pop > 1")


def test_unquoted_non_ascii_column_names_are_accepted():
    assert canonical_where("名前 = 'x' AND café > 1") == "名前 = 'x' AND café > 1"


@pytest.mark.parametrize(
    "where",
    [
        "pop > 10,",
        "pop > 10 |> WHERE pop < 20",
        "gid > 0 AND +'01' = '1'",
        "!!'roads' = terms",
        "name ~~ 'A%' IN (TRUE)",
        "name ~~* 'a%'",
        "name !~~ 'a%'",
        "pop!=-5",
        "pop <>= 5",
    ],
)
def test_operators_outside_the_standard_spellings_are_refused(where):
    columns = [{"name": n} for n in ("pop", "gid", "name", "terms")]
    with pytest.raises(ValueError):
        validate_where_clause(where, columns)


@pytest.mark.parametrize(
    "where",
    [
        "active = flag = active",
        "gid < 2 = active",
        "active = gid < 2",
        "active BETWEEN NOT flag AND flag",
    ],
)
def test_groupings_postgresql_refuses_are_refused(where):
    with pytest.raises(ValueError, match="Disallowed expression"):
        validate_where_ast(where)


_ROWS_SQL = (
    "SELECT coalesce(array_agg(gid ORDER BY gid), '{{}}') FROM (VALUES "
    "(1, true, true, 'ab'), (2, true, false, 'b'), (3, false, true, NULL), "
    "(4, false, false, 'a'), (5, NULL, true, 'Ax'), (6, true, NULL, 'z'), "
    "(7, NULL, NULL, 'a')) AS t(gid, active, flag, name) WHERE {}"
)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "where",
    [
        "gid NOT IN (1) <= active",
        "gid NOT IN (1, 2) > flag",
        "gid NOT IN (1, 2) <> flag",
        "gid NOT BETWEEN 1 AND 2 <= flag",
        "name NOT LIKE 'a%' < active",
        "name NOT ILIKE 'a%' >= flag",
        "active IS NOT TRUE = flag",
        "active IS NOT NULL < flag",
        "gid NOT IN (1) IS NULL",
        "active = NOT flag",
        "active = NOT flag = active",
        "active <> gid NOT IN (1)",
        "active IN (flag, NOT flag)",
        "active BETWEEN flag AND NOT flag",
        "active = flag IS NOT NULL",
        "active IS NULL = flag",
        "NOT active = flag",
        "NOT NOT active <= flag",
        "gid IN (1, 2) = active",
        "active = gid BETWEEN 1 AND 2",
        "gid BETWEEN -2 AND -(-3)",
        "gid = - -2",
        "(gid NOT IN (1)) <= active",
        "gid NOT IN (1, 2) AND NOT active OR flag",
    ],
)
async def test_the_render_selects_the_same_rows_as_the_condition(
    test_db_session, where
):
    from sqlalchemy import text

    async def rows(condition):
        sql = _ROWS_SQL.format(condition).replace(":", "\\:")
        return (await test_db_session.execute(text(sql))).scalar_one()

    assert await rows(canonical_where(where)) == await rows(where)


class TestWrapper:
    _COL_INFO = [{"name": "pop"}, {"name": "gid"}, {"name": "state"}]

    def test_wrapper_returns_the_canonical_render(self):
        for where in ("pop>1000", "state='CA'  AND  pop<5", "(gid = 1)"):
            result = validate_where_clause(where, column_info=self._COL_INFO)
            assert result == canonical_where(where)
        assert validate_where_clause("pop>1000", column_info=self._COL_INFO) == (
            "pop > 1000"
        )

    def test_wrapper_refuses_text_after_the_condition_even_for_known_columns(self):
        # Known columns, so a refusal comes from the single-condition rule.
        columns = [{"name": n} for n in ("gid", "limit", "order", "by", "offset")]
        for where in ("gid > 0 LIMIT 0", "gid > 0 ORDER BY gid", "gid > 0 OFFSET 1"):
            with pytest.raises(ValueError, match="Only a single WHERE expression"):
                validate_where_clause(where, column_info=columns)

    def test_wrapper_happy_path_still_works(self):
        """A canonical expression comes back as it went in."""
        result = validate_where_clause("pop > 1000", column_info=self._COL_INFO)
        assert result == "pop > 1000"

    def test_wrapper_calls_ast_validator_first(self):
        """UNION attack must be rejected by the AST gate before identifier check."""
        with pytest.raises(ValueError) as exc_info:
            validate_where_clause(
                "gid > 0 UNION SELECT 1",
                column_info=self._COL_INFO,
            )
        # Error message should come from the AST validator, not the identifier check
        msg = str(exc_info.value).lower()
        assert "where expression" in msg or "select" in msg or "disallowed" in msg
        assert "unknown column" not in msg

    def test_wrapper_unknown_column_still_caught(self):
        """AST passes for valid-syntax-but-unknown-column; identifier check catches it."""
        with pytest.raises(ValueError, match="Unknown column: foo"):
            validate_where_clause("foo > 1000", column_info=[{"name": "pop"}])

    def test_wrapper_no_column_info_rejected(self):
        with pytest.raises(ValueError, match="Cannot filter"):
            validate_where_clause("pop > 1000", column_info=None)

    def test_wrapper_subquery_rejected_before_identifier_check(self):
        """Subquery must be rejected by AST gate, not identifier loop."""
        with pytest.raises(ValueError) as exc_info:
            validate_where_clause(
                "gid IN (SELECT id FROM users)",
                column_info=self._COL_INFO,
            )
        assert "unknown column" not in str(exc_info.value).lower()

    def test_wrapper_function_call_rejected_before_identifier_check(self):
        with pytest.raises(ValueError) as exc_info:
            validate_where_clause("pg_sleep(10)", column_info=self._COL_INFO)
        assert "unknown column" not in str(exc_info.value).lower()

    def test_wrapper_empty_column_info_list_rejected(self):
        """Empty list is falsy — treated the same as None."""
        with pytest.raises(ValueError, match="Cannot filter"):
            validate_where_clause("pop > 1000", column_info=[])


# ─────────────────────────────────────────────────────────────────────────────
# Endpoint-level HTTP tests (require running DB + SEC_AUDIT_PUBLIC_DATASET_ID)
#
# Fixture-provisioning recipe:
#   1. Start the stack: docker compose up -d db api worker
#   2. In the UI (or via API), create/import a small public dataset with a
#      numeric column (e.g. "gid") and note the public_id UUID.
#   3. Export SEC_AUDIT_PUBLIC_DATASET_ID=<uuid> in your shell.
#   4. Re-run: cd backend && pytest tests/test_export_where_validator.py -k "endpoint"
#
# These tests are skipped automatically when the env var is not set so the
# full test suite remains runnable in CI without fixtures.
# ─────────────────────────────────────────────────────────────────────────────


class TestCanonicalWhere:
    """``canonical_where`` re-renders the validated AST so the
    export cap's bounded COUNT never interpolates the caller's raw bytes."""

    def test_returns_equivalent_canonical_sql(self):
        assert canonical_where("1=1") == "1 = 1"
        assert canonical_where("pop > 25") == "pop > 25"
        assert canonical_where("name = 'O''Brien'") == "name = 'O''Brien'"
        assert canonical_where("category IN ('a', 'b')") == "category IN ('a', 'b')"

    def test_rejects_disallowed_constructs(self):
        with pytest.raises(ValueError):
            canonical_where("pg_sleep(1) IS NOT NULL")
        with pytest.raises(ValueError):
            canonical_where("1=1 UNION SELECT * FROM users")

    def test_output_revalidates(self):
        # The canonical form must itself pass the validator (round-trip safe).
        validate_where_ast(canonical_where("(a > 1 OR b < 2) AND NOT c = 'x'"))


class TestEndpoint:
    """HTTP-level regression tests for the export -where gate.

    Requires a live API (httpx AsyncClient from conftest) + a real public dataset.
    Skipped when SEC_AUDIT_PUBLIC_DATASET_ID is not set.
    """

    @pytest.fixture(autouse=True)
    def require_dataset_id(self):
        dataset_id = os.environ.get("SEC_AUDIT_PUBLIC_DATASET_ID")
        if not dataset_id:
            pytest.skip(
                "Set SEC_AUDIT_PUBLIC_DATASET_ID to a public exportable dataset"
            )
        self.dataset_id = dataset_id

    @pytest.mark.anyio
    async def test_endpoint_rejects_union_attack(self, client, admin_auth_header):
        """GET /datasets/{id}/export?where=<UNION> must return 400."""
        payload = "gid > 0 UNION SELECT 1, 2, 3"
        resp = await client.get(
            f"/datasets/{self.dataset_id}/export",
            params={"format": "csv", "where": payload},
            headers=admin_auth_header,
        )
        assert resp.status_code in (400, 422), (
            f"Expected 400/422 for UNION attack, got {resp.status_code}: {resp.text}"
        )

    @pytest.mark.anyio
    async def test_endpoint_rejects_subquery(self, client, admin_auth_header):
        """GET /datasets/{id}/export?where=<subquery> must return 400."""
        resp = await client.get(
            f"/datasets/{self.dataset_id}/export",
            params={"format": "csv", "where": "gid IN (SELECT 1 FROM users)"},
            headers=admin_auth_header,
        )
        assert resp.status_code in (400, 422), (
            f"Expected 400/422 for subquery, got {resp.status_code}: {resp.text}"
        )

    @pytest.mark.anyio
    async def test_endpoint_rejects_function_call(self, client, admin_auth_header):
        """GET /datasets/{id}/export?where=pg_sleep(10) must return 400."""
        resp = await client.get(
            f"/datasets/{self.dataset_id}/export",
            params={"format": "csv", "where": "pg_sleep(10)"},
            headers=admin_auth_header,
        )
        assert resp.status_code in (400, 422), (
            f"Expected 400/422 for function call, got {resp.status_code}: {resp.text}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Differential: an accepted filter's render selects what PostgreSQL selects for
# the filter as written.
# ─────────────────────────────────────────────────────────────────────────────

_TABLE_SQL = (
    "SELECT coalesce(array_agg(gid ORDER BY gid), '{{}}') FROM (VALUES "
    "(1, 10, 'ab', true, true), (2, -3, 'b', true, false), "
    "(3, 0, NULL, false, true), (4, NULL, 'a', false, false), "
    "(5, 25, 'Ax', NULL, true), (6, 7, 'z%', true, NULL), "
    "(7, 10, '', NULL, NULL)) AS t(gid, pop, name, active, flag) WHERE {}"
)
_TABLE_COLUMNS = [
    {"name": "gid"},
    {"name": "pop"},
    {"name": "name"},
    {"name": "active"},
    {"name": "flag"},
]


class _FilterGenerator:
    """Random filters over ``_TABLE_SQL``'s columns, supported and exotic spellings."""

    def __init__(self, seed: int):
        import random

        self.rng = random.Random(seed)

    def pick(self, *options):
        return self.rng.choice(options)

    def chance(self, p: float) -> bool:
        return self.rng.random() < p

    def gap(self) -> str:
        return "" if self.chance(0.2) else " "

    def number(self) -> str:
        n = str(self.rng.randint(-5, 30))
        if self.chance(0.08):
            return self.pick(f"+{n}", f"{n}.5", f".{abs(int(n))}", f"'{n}'")
        if self.chance(0.1):
            return f"- {abs(int(n))}" if self.chance(0.5) else f"-({n})"
        return n

    def integer(self) -> str:
        if self.chance(0.5):
            col = self.pick("gid", "pop", '"pop"')
            if self.chance(0.08):
                return self.pick(f"-{col}", f"+{col}", f"{col}::text", f"{col} + 1")
            return col
        return self.number()

    def text(self) -> str:
        if self.chance(0.5):
            return "name"
        literal = self.pick("'a%'", "'A%'", "'b'", "'z%'", "''", "'O''x'", "'%'")
        if self.chance(0.05):
            return self.pick("E'a'", "$$a$$", "'a' || 'b'")
        return literal

    def boolean(self, depth: int) -> str:
        if depth > 0 and self.chance(0.3):
            return f"({self.predicate(depth - 1)})"
        return self.pick("active", "flag", "TRUE", "FALSE", "NULL", "true")

    def comparison_op(self) -> str:
        if self.chance(0.06):
            return self.pick("==", "=<", "!=-", "<>=", "^=")
        return self.pick("=", "<>", "!=", "<", "<=", ">", ">=")

    def predicate(self, depth: int) -> str:
        shapes = ["cmp", "text", "bool", "in", "between", "like", "is"]
        if depth > 0:
            shapes += ["not", "and", "or", "paren", "operand", "operand"]
        shape = self.rng.choice(shapes)
        op = self.comparison_op()
        g = self.gap()
        if shape == "cmp":
            return f"{self.integer()}{g}{op}{g}{self.integer()}"
        if shape == "text":
            return f"{self.text()} {op} {self.text()}"
        if shape == "bool":
            return f"{self.boolean(depth)} {op} {self.boolean(depth)}"
        neg = "NOT " if self.chance(0.4) else ""
        if shape == "in":
            items = ", ".join(self.number() for _ in range(self.rng.randint(1, 3)))
            if self.chance(0.2):
                return f"{self.boolean(depth)} {neg}IN (TRUE, flag)"
            return f"{self.integer()} {neg}IN ({items})"
        if shape == "between":
            return f"{self.integer()} {neg}BETWEEN {self.number()} AND {self.number()}"
        if shape == "like":
            op = self.pick("LIKE", "ILIKE", "like", "~~", "~~*", "!~~")
            if op.startswith(("~", "!")):
                neg = ""
            return f"name {neg}{op} {self.text()}"
        if shape == "is":
            subject = self.pick("active", "flag", "name", "pop")
            target = self.pick("NULL", "TRUE", "FALSE", "null")
            if self.chance(0.06):
                return self.pick(f"{subject} ISNULL", f"{subject} IS UNKNOWN")
            return f"{subject} IS {neg}{target}"
        sub = self.predicate(depth - 1)
        if shape == "not":
            return self.pick(f"NOT {sub}", f"not {sub}", "!!active", f"NOT NOT {sub}")
        if shape in ("and", "or"):
            return f"{sub} {shape.upper()} {self.predicate(depth - 1)}"
        if shape == "paren":
            return f"({sub})"
        # A predicate as an operand, the shapes where grouping matters.
        return f"{sub} {self.comparison_op()} {self.boolean(depth)}"

    def filter(self) -> str:
        where = self.predicate(self.rng.randint(0, 3))
        if self.chance(0.05):
            where += self.pick(",", " |> WHERE gid > 1", " LIMIT 1", ";", " , 1")
        return where


async def _run_filter(session, condition: str):
    """``(rows, None)`` or ``(None, sqlstate)`` for a WHERE condition."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    sql = _TABLE_SQL.format(condition).replace(":", "\\:")
    try:
        async with session.begin_nested():
            return (await session.execute(text(sql))).scalar_one(), None
    except DBAPIError as exc:
        return None, getattr(exc.orig, "sqlstate", None) or "unknown"


_SUPPORTED = [
    "pop > 1000",
    "1=1",
    "name = ' :name'",
    "name = 'O''Brien Park'",
    "name != 'Nowhere Road'",
    "pop >= 10",
    "pop >= -3",
    "name IS NOT NULL",
    "gid IN (1, 2, 3)",
    "name LIKE 'A%'",
    "name NOT LIKE 'a%'",
    "gid NOT IN (1)",
    "gid BETWEEN 0 AND 10",
    "gid NOT BETWEEN 2 AND 3",
    "active = true",
    "active IS TRUE",
    "NOT NOT (pop > 1)",
    "((((pop > 1))))",
    "(pop > 1 OR gid < 2) AND NOT name = 'x'",
    "pop <> 10 and gid <= 5 or name = 'b'",
    "\"name\" = 'b'",
    "pop = -5",
    "pop=-5",
    "pop > - 3",
]


@pytest.mark.anyio
async def test_supported_filters_are_accepted_and_select_the_same_rows(
    test_db_session,
):
    for where in _SUPPORTED:
        rendered = validate_where_clause(where, _TABLE_COLUMNS)
        original = await _run_filter(test_db_session, where)
        assert original[1] is None, where
        assert await _run_filter(test_db_session, rendered) == original, where


@pytest.mark.anyio
async def test_accepted_filters_select_what_postgresql_selects(test_db_session):
    generator = _FilterGenerator(seed=4192)
    counts = {"accepted": 0, "refused": 0, "refused_postgres_runs": 0}
    failures = []
    for _ in range(400):
        where = generator.filter()
        original = await _run_filter(test_db_session, where)
        try:
            rendered = validate_where_clause(where, _TABLE_COLUMNS)
        except ValueError:
            counts["refused"] += 1
            counts["refused_postgres_runs"] += original[1] is None
            continue
        counts["accepted"] += 1
        render = await _run_filter(test_db_session, rendered)
        if original[1] == "42601":
            failures.append((where, rendered, "PostgreSQL can't parse the original"))
        elif original[1] is not None:
            # A type error: no rows to compare, but the render must fail too.
            if render[1] is None:
                failures.append((where, rendered, f"original {original[1]}"))
        elif render != original:
            failures.append((where, rendered, f"{original[0]} vs {render}"))
    print(counts)
    assert failures == []
    assert counts["accepted"] >= 100 and counts["refused"] >= 20, counts

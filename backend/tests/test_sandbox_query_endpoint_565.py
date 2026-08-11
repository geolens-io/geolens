"""feat(#565): POST /api/query/ — the raw read-only SQL sandbox endpoint.

Pins the hardening decisions recorded in #565 (and its prerequisite #1011):

- auth required; ``use_ai_chat`` gates the route (viewer 403, anonymous 401);
- ``restrict_tables`` is mandatory, non-empty, and can only narrow access;
- the tableless case (S03's last unshipped fix) stays rejected;
- the writable-CTE regression from #1011 stays rejected through the endpoint;
- the self-join repetition cap refuses the CROSS JOIN shape (and its CTE /
  subquery launderings) with a sanitized error, while a plain pairwise
  self-join keeps working;
- the endpoint's budget (5 s timeout, smaller row limit, repetition cap,
  fail-closed reader role) is actually threaded into the sandbox;
- the single-tenant reader-role binding fails CLOSED here while chat's
  legacy best-effort fallback is unchanged;
- errors carry only ``SandboxError.user_message``; internals never leak;
- every query emits a durable audit event, success and rejection alike;
- per-user and per-IP slowapi limits both fire.

The read_only API-key carve-out (both directions) lives with its siblings in
``test_api_key_scope_875.py``.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

from app.platform.sandbox import SandboxError, validate_and_execute
from app.platform.sandbox.executor import execute_safe
from tests.factories import create_dataset


async def _admin_id(client: AsyncClient, headers: dict) -> uuid.UUID:
    return uuid.UUID((await client.get("/auth/me/", headers=headers)).json()["id"])


async def _make_table(session, owner: uuid.UUID, *, rows: int = 1) -> str:
    """Create a physical data.* table plus its catalog rows; return its name."""
    tbl = f"q565_{uuid.uuid4().hex[:10]}"
    await session.execute(text(f"CREATE TABLE data.{tbl} (gid int, label text)"))
    for i in range(rows):
        await session.execute(
            text(f"INSERT INTO data.{tbl} VALUES (:gid, :label)"),
            {"gid": i + 1, "label": f"row-{i + 1}"},
        )
    await session.commit()
    await create_dataset(session, created_by=owner, table_name=tbl)
    return tbl


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


async def test_anonymous_is_401(client: AsyncClient):
    resp = await client.post(
        "/query/", json={"sql": "SELECT 1", "restrict_tables": ["x"]}
    )
    assert resp.status_code == 401


async def test_viewer_without_use_ai_chat_is_403(
    client: AsyncClient, viewer_auth_header
):
    resp = await client.post(
        "/query/",
        json={"sql": "SELECT 1", "restrict_tables": ["x"]},
        headers=viewer_auth_header,
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Missing permission: use_ai_chat"


# ---------------------------------------------------------------------------
# restrict_tables is mandatory (and the tableless case stays closed)
# ---------------------------------------------------------------------------


async def test_missing_restrict_tables_is_422(client: AsyncClient, admin_auth_header):
    resp = await client.post(
        "/query/", json={"sql": "SELECT 1"}, headers=admin_auth_header
    )
    assert resp.status_code == 422


async def test_empty_restrict_tables_is_422(client: AsyncClient, admin_auth_header):
    resp = await client.post(
        "/query/",
        json={"sql": "SELECT 1", "restrict_tables": []},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422


async def test_blank_restrict_tables_entry_is_422(
    client: AsyncClient, admin_auth_header
):
    resp = await client.post(
        "/query/",
        json={"sql": "SELECT 1", "restrict_tables": ["  "]},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422


async def test_tableless_select_is_rejected(client: AsyncClient, admin_auth_header):
    """S03's one unshipped fix: a query touching no data.* table is refused —
    a raw endpoint is exactly where a tableless probe would otherwise bite."""
    resp = await client.post(
        "/query/",
        json={"sql": "SELECT 1", "restrict_tables": ["anything"]},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Query must reference an accessible dataset"


async def test_restrict_tables_scopes_out_other_visible_tables(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """The scope can only narrow: a table the caller CAN see but did not name
    in restrict_tables is refused with the uniform not-accessible message."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    named = await _make_table(test_db_session, owner)
    unnamed = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": f"SELECT a.gid FROM data.{named} a JOIN data.{unnamed} b ON a.gid = b.gid",
            "restrict_tables": [named],
        },
        headers=headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Table not accessible"


async def test_unknown_table_is_the_same_404(client: AsyncClient, admin_auth_header):
    """Nonexistent and denied tables share one status and one message — no
    existence oracle."""
    resp = await client.post(
        "/query/",
        json={
            "sql": "SELECT gid FROM data.q565_does_not_exist",
            "restrict_tables": ["q565_does_not_exist"],
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Table not accessible"


# ---------------------------------------------------------------------------
# Validation regressions stay closed through the endpoint
# ---------------------------------------------------------------------------


async def test_writable_cte_stays_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """#1011's fixture payload, through the new endpoint."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"WITH x AS (INSERT INTO data.{tbl} (gid) VALUES (1) RETURNING gid) "
                "SELECT gid FROM x"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Only SELECT queries are allowed"


async def test_regrole_oid_cast_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r11): a cast to a reg* OID-alias type resolves an OID
    to a catalog name (role names here) without touching a catalog table."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"SELECT v::regrole FROM data.{tbl} "
                "CROSS JOIN (VALUES (10), (16384), (16385)) AS x(v)"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Query uses a disallowed type cast"
    # Sanitized: no role name or OID leaks in the response.
    assert "regrole" not in resp.text


async def test_schema_qualified_oid_cast_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r12): qualifying the alias type (pg_catalog.regrole)
    changes its AST class from ObjectIdentifier to a USER-DEFINED DataType —
    the name-based check must still reject it."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"SELECT v::pg_catalog.regrole FROM data.{tbl} "
                "CROSS JOIN (VALUES (10), (16384)) AS x(v)"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Query uses a disallowed type cast"


async def test_quoted_cte_name_cannot_mask_a_catalog_table(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r12): a quoted uppercase CTE name does not bind an
    unquoted reference — PostgreSQL folds the reference to lowercase, which
    resolves to the catalog view, so it must fall through to the data.* check."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f'WITH "PG_USER" AS (SELECT gid FROM data.{tbl}) '
                "SELECT usename FROM PG_USER"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Table not accessible"
    assert "usename" not in resp.text


async def test_derived_table_correlated_work_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r12): an ordinary derived table with a correlated scan
    can be flattened by PostgreSQL to run per outer row — N^3 — so its excess
    work must propagate like a CTE's or a LATERAL's."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"SELECT p.n + q.gid FROM (SELECT x.gid, "
                f"(SELECT count(*) FROM data.{tbl} y WHERE y.gid + x.gid IS NOT NULL) n "
                f"FROM data.{tbl} x) p CROSS JOIN data.{tbl} q"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == _REPETITION_MESSAGE


async def test_out_of_scope_cte_name_cannot_mask_a_catalog_table(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1): a CTE named after a catalog relation in an inner
    scope must not let an unqualified outer reference reach pg_catalog. Admin
    can access any dataset, so this is the worst case for the bypass."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                "SELECT p.usename FROM pg_user p CROSS JOIN "
                f"(WITH pg_user AS (SELECT gid FROM data.{tbl}) SELECT 1) x"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Table not accessible"
    assert "usename" not in resp.text


async def test_later_sibling_cte_name_cannot_mask_a_catalog_table(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r2): a CTE named after a catalog relation declared
    LATER in the same WITH is not yet in scope for an earlier sibling, so
    PostgreSQL resolves the earlier reference to pg_catalog — the resolver must
    honor declaration order and reject it."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                "WITH leak AS (SELECT usename FROM pg_user), "
                f"pg_user AS (SELECT gid FROM data.{tbl}) SELECT usename FROM leak"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Table not accessible"
    assert "usename" not in resp.text


# ---------------------------------------------------------------------------
# Self-join repetition cap (#565's live cost vector)
# ---------------------------------------------------------------------------

_REPETITION_MESSAGE = "Query references the same table too many times"


async def test_cross_join_shape_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """The issue's own payload: three references to one table."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"SELECT a.gid FROM data.{tbl} a "
                f"CROSS JOIN data.{tbl} b CROSS JOIN data.{tbl} c"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == _REPETITION_MESSAGE
    # Sanitized: the table name must not echo back.
    assert tbl not in resp.text


async def test_parenthesized_join_group_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r8): a parenthesized FROM group hides the cross join
    in a Subquery-wrapped Table carrying its joins — it must still be costed."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"SELECT a.gid FROM (data.{tbl} a "
                f"CROSS JOIN data.{tbl} b CROSS JOIN data.{tbl} c)"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == _REPETITION_MESSAGE


async def test_parenthesized_group_on_predicate_is_costed(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r9): a parenthesized join group whose ON predicate
    runs a correlated self-join scan is N^3 — the group's ON work must be
    costed, not just its row product."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"SELECT a.gid FROM (data.{tbl} a JOIN data.{tbl} b ON EXISTS "
                f"(SELECT 1 FROM data.{tbl} c WHERE c.gid + a.gid + b.gid = -1))"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == _REPETITION_MESSAGE


async def test_transitive_cte_chain_fanout_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r3): a CTE chain that keeps every per-name count at 2
    but multiplies one physical table to N^8 must be rejected — the fan-out
    bound follows the dependency graph, not surface reference counts."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"WITH a AS (SELECT gid FROM data.{tbl}), "
                "b AS (SELECT x.gid FROM a x CROSS JOIN a y), "
                "c AS (SELECT x.gid FROM b x CROSS JOIN b y) "
                "SELECT x.gid FROM c x CROSS JOIN c y"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == _REPETITION_MESSAGE


async def test_subquery_hidden_self_join_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r4): a triple self-join buried in a scalar subquery
    (or EXISTS/WHERE) runs per outer row, so it must be costed too — a row-only
    bound reported fan-out 1 and let it through."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"SELECT (SELECT count(*) FROM data.{tbl} a "
                f"CROSS JOIN data.{tbl} b CROSS JOIN data.{tbl} c) "
                f"FROM data.{tbl} z"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == _REPETITION_MESSAGE


async def test_join_on_subquery_self_join_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r5): a correlated subquery in JOIN ... ON runs per
    row like a WHERE, so its self-join work must be costed — a join's ON side
    is not a row source."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"SELECT a.gid FROM data.{tbl} a JOIN data.{tbl} b ON a.gid = "
                f"(SELECT count(*) FROM data.{tbl} c "
                f"CROSS JOIN data.{tbl} d CROSS JOIN data.{tbl} e)"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == _REPETITION_MESSAGE


async def test_lateral_self_join_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r6): a repeated table wrapped in a LATERAL source is
    still an N^3 cross join — the LATERAL subquery must be costed as a source."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"SELECT a.gid FROM data.{tbl} a CROSS JOIN data.{tbl} b "
                f"CROSS JOIN LATERAL "
                f"(SELECT c.gid FROM data.{tbl} c WHERE a.gid IS NOT NULL) x"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == _REPETITION_MESSAGE


async def test_lateral_with_internal_correlated_subquery_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r7): a LATERAL whose own body runs a correlated
    subquery over the same table is N^3 — the LATERAL's internal per-row work
    must be added, not just its row count."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"SELECT a.gid FROM data.{tbl} a CROSS JOIN LATERAL "
                f"(SELECT b.gid FROM data.{tbl} b WHERE EXISTS "
                f"(SELECT 1 FROM data.{tbl} c WHERE c.gid = a.gid + b.gid)) x"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == _REPETITION_MESSAGE


async def test_lateral_over_other_table_is_allowed(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """A LATERAL over a DIFFERENT table (fan-out 1) is a legitimate shape."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    t1 = await _make_table(test_db_session, owner)
    t2 = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"SELECT a.gid FROM data.{t1} a CROSS JOIN LATERAL "
                f"(SELECT b.gid FROM data.{t2} b WHERE b.gid = a.gid) x"
            ),
            "restrict_tables": [t1, t2],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


async def test_union_with_cte_resolves(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P2 r5): a WITH on a set operation attaches to the UNION,
    not its branch SELECTs. Resolving CTE references must inspect set-op scopes
    or a valid UNION over a CTE 404s."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"WITH a AS (SELECT gid FROM data.{tbl}) "
                "SELECT gid FROM a UNION ALL SELECT gid FROM a"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


async def test_scalar_subquery_on_another_table_is_allowed(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """A cheap scalar subquery over a DIFFERENT table (fan-out 1) is legit and
    must not be a false positive of the per-row correlation model."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    t1 = await _make_table(test_db_session, owner)
    t2 = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"SELECT z.gid, (SELECT count(*) FROM data.{t2}) AS n FROM data.{t1} z"
            ),
            "restrict_tables": [t1, t2],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


async def test_inlined_cte_correlated_work_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r10): a NOT MATERIALIZED CTE with a correlated scan,
    referenced across a cross join, inlines its work per outer pair — N^3. The
    CTE's excess work must propagate, not just its row count."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"WITH a AS NOT MATERIALIZED (SELECT x.gid, "
                f"(SELECT count(*) FROM data.{tbl} y WHERE y.gid + x.gid IS NOT NULL) n "
                f"FROM data.{tbl} x) SELECT p.n + q.n FROM a p CROSS JOIN a q"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == _REPETITION_MESSAGE


async def test_sibling_scalar_subqueries_are_allowed(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P2 r13): two scalar subqueries over the same table are
    SIBLINGS — PostgreSQL runs them additively (often once), so their work is
    the per-table max, not the sum. Summing them wrongly rejected a legit
    quadratic query at the cap of 2."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"SELECT a.gid, (SELECT count(*) FROM data.{tbl}), "
                f"(SELECT count(*) FROM data.{tbl}) FROM data.{tbl} a"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


async def test_values_cross_join_explosion_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r17): a constant VALUES CTE cross-joined three times is
    a k-way row explosion the base-table fan-out cannot see — it must be
    counted as a fan-out source."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)
    vals = ", ".join(f"({i})" for i in range(20))

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"WITH v(x) AS (VALUES {vals}) SELECT count(*) FROM data.{tbl} f "
                "CROSS JOIN v a CROSS JOIN v b CROSS JOIN v c"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == _REPETITION_MESSAGE


async def test_distinct_values_cross_join_explosion_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r18): three SEPARATELY-written VALUES cross-joined are
    still 256^3 combinations — distinct constant sources must combine in the
    cross-product, not hide under per-node keys."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)
    v = ", ".join(f"({i})" for i in range(10))

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"SELECT 1 FROM data.{tbl} f "
                f"CROSS JOIN (VALUES {v}) a(x) CROSS JOIN (VALUES {v}) b(y) "
                f"CROSS JOIN (VALUES {v}) c(z)"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == _REPETITION_MESSAGE


@pytest.mark.parametrize(
    "expr",
    [
        "replace(gid::text, '1', 'bbbbbbbb')",
        "regexp_replace(gid::text, '1', 'bbbbbbbb')",
    ],
)
async def test_output_amplifying_string_functions_are_rejected(
    client: AsyncClient, admin_auth_header, test_db_session, expr
):
    """fix(#565 codex P1 r18): replace / regexp_replace expand a small input to
    a huge cell (~100 MB) under the 20 KB request limit — also dropped."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": f"SELECT {expr} FROM data.{tbl} LIMIT 1",
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Query uses a disallowed function"


async def test_chained_pipe_concatenation_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r19): `||` (exp.DPipe) is string concatenation — s||s
    chained through MATERIALIZED CTEs doubles a value into hundreds of MB. The
    operator is blocked on the raw surface alongside concat."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"WITH c0 AS MATERIALIZED (SELECT gid::text AS s FROM data.{tbl} "
                "LIMIT 1), c1 AS MATERIALIZED (SELECT s || s AS s FROM c0) "
                "SELECT s FROM c1"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Query uses a disallowed operator"


async def test_concat_function_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """concat / concat_ws double a value the same way — dropped on the raw
    surface too (fix(#565 codex P1 r19))."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": f"SELECT concat(label, label) FROM data.{tbl}",
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Query uses a disallowed function"


async def test_oversized_values_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r17): a huge inline VALUES relation is capped."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)
    vals = ", ".join(f"({i})" for i in range(300))

    resp = await client.post(
        "/query/",
        json={
            "sql": f"SELECT x FROM (VALUES {vals}) t(x)",
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Query uses too many inline VALUES rows"


async def test_output_amplifying_format_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r17): format() with a giant width builds hundreds of
    MB from a one-row query — dropped on this raw surface."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": f"SELECT format('%500000000s', gid::text) FROM data.{tbl} LIMIT 1",
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Query uses a disallowed function"


async def test_lateral_values_nested_subquery_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r16): a LATERAL over VALUES has no inner scope to
    unwrap, but a self-join subquery buried in it still runs per outer row —
    N^3 — so its work must be costed as the lateral's per-row work."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"SELECT f.gid, v.n FROM data.{tbl} f CROSS JOIN LATERAL "
                f"(VALUES ((SELECT count(*) FROM data.{tbl} a "
                f"CROSS JOIN data.{tbl} b WHERE a.gid + f.gid IS NOT NULL))) v(n)"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == _REPETITION_MESSAGE


async def test_dynamic_limit_subquery_is_allowed(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P2 r16): a LIMIT/OFFSET subquery is evaluated once
    (statement-level), so its work is additive with the scan — not multiplied
    by the outer rows. It must not false-reject."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"SELECT x.gid FROM data.{tbl} x LIMIT "
                f"(SELECT count(*) FROM data.{tbl} y CROSS JOIN data.{tbl} z)"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


async def test_aggregate_argument_subquery_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r15): a correlated subquery INSIDE an aggregate
    argument runs per input row (the aggregate consumes per-input values), so
    the ungrouped-aggregate reduction must not zero its multiplier — N^3."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"SELECT sum((SELECT count(*) FROM data.{tbl} b "
                f"CROSS JOIN data.{tbl} c WHERE b.gid = a.gid)) FROM data.{tbl} a"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == _REPETITION_MESSAGE


async def test_bytea_column_is_serialized_as_hex(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P2 r15): a bytea column returns raw bytes that Pydantic's
    JSON serializer 500s on for non-UTF-8 sequences. Result cells are encoded
    as \\x-hex, matching to_jsonb, so a successful query stays a 200."""
    from sqlalchemy import text

    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = f"q565bytea_{uuid.uuid4().hex[:8]}"
    await test_db_session.execute(
        text(f"CREATE TABLE data.{tbl} (gid int, blob bytea)")
    )
    await test_db_session.execute(
        text(f"INSERT INTO data.{tbl} VALUES (1, '\\xdeadbeef'::bytea)")
    )
    await test_db_session.commit()
    await create_dataset(test_db_session, created_by=owner, table_name=tbl)

    resp = await client.post(
        "/query/",
        json={"sql": f"SELECT blob FROM data.{tbl}", "restrict_tables": [tbl]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rows"] == [["\\xdeadbeef"]]


async def test_ungrouped_aggregate_with_projection_subquery_is_allowed(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P2 r14): an ungrouped-aggregate SELECT outputs one row,
    so a projection scalar subquery runs once — its work is additive with the
    scan, not multiplied by input rows. Multiplying wrongly rejected it."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"SELECT count(*), (SELECT count(*) FROM data.{tbl} y "
                f"CROSS JOIN data.{tbl} z) FROM data.{tbl} x"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


async def test_aggregate_does_not_hide_a_correlated_where_self_join(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """The aggregate reduction must NOT under-count a correlated WHERE subquery,
    which runs per INPUT row (before aggregation): a triple self-join there is
    still N^4 and rejected."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"SELECT count(*) FROM data.{tbl} x WHERE EXISTS "
                f"(SELECT 1 FROM data.{tbl} a CROSS JOIN data.{tbl} b "
                f"CROSS JOIN data.{tbl} c WHERE a.gid = x.gid)"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == _REPETITION_MESSAGE


async def test_distinct_table_cross_product_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r20): three DISTINCT tables cross-joined is N×M×K —
    each carries per-table exponent 1, so the max missed it. The cross-product
    degree bounds it."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    t1 = await _make_table(test_db_session, owner)
    t2 = await _make_table(test_db_session, owner)
    t3 = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": f"SELECT count(*) FROM data.{t1} CROSS JOIN data.{t2} CROSS JOIN data.{t3}",
            "restrict_tables": [t1, t2, t3],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == _REPETITION_MESSAGE


async def test_too_many_output_columns_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r20): repeated plain projections amplify response width
    with no function at all — capped by output-column count."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)
    wide = ", ".join(["gid"] * 150)

    resp = await client.post(
        "/query/",
        json={"sql": f"SELECT {wide} FROM data.{tbl}", "restrict_tables": [tbl]},
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Query selects too many columns"


async def test_composite_projection_width_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r21): a single composite ROW projection repeats a value
    many times inside one AST expression, so counting projections missed it —
    the value-slot count catches it."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)
    wide = ", ".join(["gid"] * 150)

    resp = await client.post(
        "/query/",
        json={"sql": f"SELECT ({wide}) FROM data.{tbl}", "restrict_tables": [tbl]},
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Query selects too many columns"


async def test_star_projection_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r21): `SELECT *` / `t.*` expands to an unknown column
    count against a wide table, so the raw endpoint requires explicit columns."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    for sql in (f"SELECT * FROM data.{tbl}", f"SELECT t.* FROM data.{tbl} t"):
        resp = await client.post(
            "/query/",
            json={"sql": sql, "restrict_tables": [tbl]},
            headers=headers,
        )
        assert resp.status_code == 422, sql
        assert resp.json()["detail"] == "Query must select explicit columns, not *"


async def test_always_true_disjunctive_join_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P1 r21): `ON a.gid = b.gid OR TRUE` is a cartesian product —
    an equality merely occurring in the predicate does not constrain it."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    t1 = await _make_table(test_db_session, owner)
    t2 = await _make_table(test_db_session, owner)
    t3 = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"SELECT count(*) FROM data.{t1} a "
                f"JOIN data.{t2} b ON a.gid = b.gid OR TRUE "
                f"JOIN data.{t3} c ON b.gid = c.gid OR TRUE"
            ),
            "restrict_tables": [t1, t2, t3],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == _REPETITION_MESSAGE


async def test_range_column_is_serialized_as_text(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P2 r20): asyncpg Range values cannot be serialized by
    Pydantic and would 500 after a successful, audited query. They are encoded
    as their PostgreSQL text form."""
    from sqlalchemy import text

    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = f"q565rng_{uuid.uuid4().hex[:8]}"
    await test_db_session.execute(
        text(f"CREATE TABLE data.{tbl} (gid int, span int4range)")
    )
    await test_db_session.execute(
        text(f"INSERT INTO data.{tbl} VALUES (1, '[1,3)'::int4range)")
    )
    await test_db_session.commit()
    await create_dataset(test_db_session, created_by=owner, table_name=tbl)

    resp = await client.post(
        "/query/",
        json={"sql": f"SELECT span FROM data.{tbl}", "restrict_tables": [tbl]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rows"] == [["[1,3)"]]


async def test_multi_table_join_is_not_a_false_positive(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """The fan-out bound must not reject a legitimate join across several
    DIFFERENT tables (linear cost, fan-out 1), only self-multiplication."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    t1 = await _make_table(test_db_session, owner)
    t2 = await _make_table(test_db_session, owner)
    t3 = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"SELECT a.gid FROM data.{t1} a "
                f"JOIN data.{t2} b ON a.gid = b.gid "
                f"JOIN data.{t3} c ON b.gid = c.gid"
            ),
            "restrict_tables": [t1, t2, t3],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


async def test_cte_laundered_repetition_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """Hiding each copy behind its own CTE must not dodge the cap — the
    physical table still accumulates one reference per CTE body."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"WITH x1 AS (SELECT gid FROM data.{tbl}), "
                f"x2 AS (SELECT gid FROM data.{tbl}), "
                f"x3 AS (SELECT gid FROM data.{tbl}) "
                "SELECT x1.gid FROM x1, x2, x3"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == _REPETITION_MESSAGE


async def test_cte_fanout_repetition_is_rejected(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """One CTE referenced three times is the same explosion — the CTE NAME is
    capped like a physical table."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": (
                f"WITH x AS (SELECT gid FROM data.{tbl}) "
                "SELECT a.gid FROM x a, x b, x c"
            ),
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == _REPETITION_MESSAGE


async def test_pairwise_self_join_still_works(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """Two references is a legitimate shape (lag/adjacency joins) and stays in."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": f"SELECT a.gid FROM data.{tbl} a JOIN data.{tbl} b ON a.gid = b.gid",
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["rows"] == [[1]]


async def test_chat_path_keeps_no_repetition_cap(test_db_session):
    """Scoping guarantee: the cap is opt-in. validate_and_execute without
    ``max_table_repeats`` (AI chat's call shape) still accepts three
    references to one table — chat behavior must not silently change."""
    admin = (
        await test_db_session.execute(
            text("SELECT id FROM catalog.users WHERE username = 'admin'")
        )
    ).scalar_one()
    tbl = f"q565_{uuid.uuid4().hex[:10]}"
    await test_db_session.execute(text(f"CREATE TABLE data.{tbl} (gid int)"))
    await test_db_session.execute(text(f"INSERT INTO data.{tbl} VALUES (1)"))
    await test_db_session.commit()
    await create_dataset(test_db_session, created_by=admin, table_name=tbl)

    from app.modules.auth.models import User

    user = (
        await test_db_session.execute(select(User).where(User.id == admin))
    ).scalar_one()
    result = await validate_and_execute(
        f"SELECT a.gid FROM data.{tbl} a, data.{tbl} b, data.{tbl} c",
        test_db_session,
        user,
    )
    assert result.rows == [[1]]


# ---------------------------------------------------------------------------
# Budget threading + success shape
# ---------------------------------------------------------------------------


async def test_budget_kwargs_are_threaded(
    client: AsyncClient, admin_auth_header, monkeypatch
):
    """The endpoint must pass its whole budget to the sandbox: 5 s timeout,
    the repetition cap, the mandatory scope, and the fail-closed reader role."""
    from app.platform.sandbox import SandboxResult
    from app.processing.ai import query_router

    captured: dict = {}

    async def _capture(sql, db, user, **kwargs):
        captured["sql"] = sql
        captured.update(kwargs)
        return SandboxResult(rows=[], columns=[], row_count=0, truncated=False)

    monkeypatch.setattr(query_router, "validate_and_execute", _capture)

    resp = await client.post(
        "/query/",
        json={"sql": "SELECT gid FROM data.t", "restrict_tables": ["t", "t "]},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    assert captured["timeout_ms"] == 5_000
    assert captured["max_table_repeats"] == 2
    assert captured["require_reader_role"] is True
    assert captured["row_limit"] == 100  # smaller default than chat's 1000
    assert captured["restrict_tables"] == frozenset({"t"})  # stripped + set
    # fix(#565 codex P1 r11): the connection-pool protections are wired through.
    assert captured["release_session"] is True
    assert captured["capacity_semaphore"] is query_router._query_slots


async def test_at_capacity_returns_429(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    """fix(#565 codex P1 r11): when the global sandbox-query semaphore is full,
    a further query fails fast with query_at_capacity (429), not a slow queue."""
    import asyncio

    from app.processing.ai import query_router

    owner = await _admin_id(client, admin_auth_header)
    tbl = await _make_table(test_db_session, owner)

    # A semaphore with zero free slots: already at capacity.
    exhausted = asyncio.Semaphore(1)
    await exhausted.acquire()
    monkeypatch.setattr(query_router, "_query_slots", exhausted)

    resp = await client.post(
        "/query/",
        json={"sql": f"SELECT gid FROM data.{tbl}", "restrict_tables": [tbl]},
        headers=admin_auth_header,
    )
    assert resp.status_code == 429
    assert "maximum number of queries" in resp.json()["detail"]


def test_capacity_bound_is_pool_derived_and_at_least_one():
    """The bound tracks the configured pool and never drops below 1."""
    from app.processing.ai.query_router import _capacity_bound

    assert _capacity_bound() >= 1


async def test_success_shape_and_truncation(
    client: AsyncClient, admin_auth_header, test_db_session
):
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner, rows=3)

    resp = await client.post(
        "/query/",
        json={
            "sql": f"SELECT gid, label FROM data.{tbl} ORDER BY gid",
            "restrict_tables": [tbl],
            "row_limit": 2,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["columns"] == ["gid", "label"]
    assert body["rows"] == [[1, "row-1"], [2, "row-2"]]
    assert body["row_count"] == 2
    assert body["truncated"] is True


async def test_row_limit_above_cap_is_422(client: AsyncClient, admin_auth_header):
    resp = await client.post(
        "/query/",
        json={"sql": "SELECT 1", "restrict_tables": ["x"], "row_limit": 1001},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422


async def test_no_slash_alias_serves_the_same_route(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """ROUTE-01: the hidden bare form must behave identically (it is also the
    second half of the #875 carve-out pair)."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query",
        json={"sql": f"SELECT gid FROM data.{tbl}", "restrict_tables": [tbl]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


def test_both_query_shapes_keep_the_logging_route_class():
    """fix(#565 codex P2 r3): the no-slash alias must carry the same route
    class as `/query/`, or pre-sandbox-rejection logging would fire on only one
    URL spelling. Registering it on the router (not via the app-level alias
    builder, which re-registers as a plain APIRoute) keeps them in parity."""
    from fastapi.routing import APIRoute, iter_route_contexts

    from app.api.main import app
    from app.processing.ai.query_router import _LoggedRejectionRoute

    classes = {
        ctx.path: type(ctx.route)
        for ctx in iter_route_contexts(app.routes)
        if isinstance(ctx.route, APIRoute) and ctx.path in ("/query/", "/query")
    }
    assert classes.get("/query/") is _LoggedRejectionRoute
    assert classes.get("/query") is _LoggedRejectionRoute


# ---------------------------------------------------------------------------
# Sanitized errors
# ---------------------------------------------------------------------------


async def test_execution_error_is_sanitized(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """A real Postgres error (undefined column) must surface as the generic
    user message only — no column name, no driver text, no __cause__."""
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={
            "sql": f"SELECT no_such_column_565 FROM data.{tbl}",
            "restrict_tables": [tbl],
        },
        headers=headers,
    )
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Query failed"
    assert "no_such_column_565" not in resp.text
    assert "does not exist" not in resp.text


# ---------------------------------------------------------------------------
# Reader role: fail-closed here, best-effort for chat (executor level)
# ---------------------------------------------------------------------------


class TestReaderRoleBinding:
    async def test_missing_role_fails_closed_when_required(
        self, client, test_db_session, monkeypatch
    ):
        from app.platform.sandbox import executor

        monkeypatch.setattr(executor, "_SINGLE_TENANT_READER_ROLE", "w565_no_such_role")
        with pytest.raises(SandboxError) as exc_info:
            await execute_safe(
                test_db_session, "SELECT 1 AS n", require_reader_role=True
            )
        assert exc_info.value.category == "query_failed"
        assert exc_info.value.user_message == "Query failed"

    async def test_missing_role_falls_back_when_not_required(
        self, client, test_db_session, monkeypatch
    ):
        """Chat's legacy compatibility fallback is pinned unchanged."""
        from app.platform.sandbox import executor

        monkeypatch.setattr(executor, "_SINGLE_TENANT_READER_ROLE", "w565_no_such_role")
        result = await execute_safe(test_db_session, "SELECT 1 AS n")
        assert result.rows == [[1]]

    async def test_present_role_executes_under_requirement(
        self, client, test_db_session
    ):
        result = await execute_safe(
            test_db_session, "SELECT 1 AS n", require_reader_role=True
        )
        assert result.rows == [[1]]


# ---------------------------------------------------------------------------
# Durable audit events
# ---------------------------------------------------------------------------


async def _audit_rows(session, action: str):
    from app.modules.audit.models import AuditLog

    await session.commit()  # see the durable helper's own committed session
    rows = (
        await session.execute(
            select(AuditLog)
            .where(AuditLog.action == action)
            .order_by(AuditLog.created_at.desc())
        )
    ).scalars()
    return list(rows)


async def test_success_emits_query_execute_audit(
    client: AsyncClient, admin_auth_header, test_db_session
):
    headers = admin_auth_header
    owner = await _admin_id(client, headers)
    tbl = await _make_table(test_db_session, owner)

    resp = await client.post(
        "/query/",
        json={"sql": f"SELECT gid FROM data.{tbl}", "restrict_tables": [tbl]},
        headers=headers,
    )
    assert resp.status_code == 200

    row = next(
        r
        for r in await _audit_rows(test_db_session, "query.execute")
        if r.details.get("restrict_tables") == [tbl]
    )
    assert row.user_id == owner
    assert row.resource_type == "query"
    assert row.details["sql"] == f"SELECT gid FROM data.{tbl}"
    assert row.details["row_count"] == 1
    assert row.details["truncated"] is False
    assert row.details["timeout_ms"] == 5_000


async def test_rejection_emits_query_reject_audit(
    client: AsyncClient, admin_auth_header, test_db_session
):
    marker = f"q565_reject_{uuid.uuid4().hex[:8]}"
    resp = await client.post(
        "/query/",
        json={"sql": "SELECT 1", "restrict_tables": [marker]},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422

    row = next(
        r
        for r in await _audit_rows(test_db_session, "query.reject")
        if r.details.get("restrict_tables") == [marker]
    )
    assert row.details["category"] == "invalid_query"
    assert row.details["sql"] == "SELECT 1"


async def test_body_validation_rejection_is_not_durably_audited(
    client: AsyncClient, admin_auth_header, test_db_session
):
    """fix(#565 codex P2): a body-validation 422 is a PRE-sandbox rejection —
    it never became a query and bypasses the per-request limiter, so durably
    auditing it would let cheap malformed requests amplify into unbounded audit
    writes. It is logged, not written to the durable trail."""
    before = len(await _audit_rows(test_db_session, "query.reject"))

    resp = await client.post(
        "/query/", json={"sql": "SELECT 1"}, headers=admin_auth_header
    )
    assert resp.status_code == 422

    after = len(await _audit_rows(test_db_session, "query.reject"))
    assert after == before


# ---------------------------------------------------------------------------
# Rate limits: per-user AND per-IP
# ---------------------------------------------------------------------------


async def _hammer(client: AsyncClient, headers: dict, n: int) -> list[int]:
    statuses = []
    for _ in range(n):
        resp = await client.post(
            "/query/",
            json={"sql": "SELECT 1", "restrict_tables": ["x"]},
            headers=headers,
        )
        statuses.append(resp.status_code)
    return statuses


@pytest.mark.parametrize("attr", ["_QUERY_PER_USER_LIMIT", "_QUERY_PER_IP_LIMIT"])
async def test_each_rate_limit_dimension_fires(
    client: AsyncClient, admin_auth_header, monkeypatch, attr
):
    """Both limit callables are live: lower one dimension to 2/minute and the
    endpoint 429s, whichever dimension it is."""
    from app.modules.auth.router import limiter
    from app.processing.ai import query_router

    monkeypatch.setattr(query_router, attr, "2/minute")
    limiter.enabled = True
    if hasattr(limiter, "_storage") and hasattr(limiter._storage, "reset"):
        limiter._storage.reset()
    try:
        statuses = await _hammer(client, admin_auth_header, 4)
        assert statuses.count(429) >= 1, statuses
    finally:
        limiter.enabled = False
        if hasattr(limiter, "_storage") and hasattr(limiter._storage, "reset"):
            limiter._storage.reset()


async def test_rate_limited_requests_are_not_durably_audited(
    client: AsyncClient, admin_auth_header, test_db_session, monkeypatch
):
    """fix(#565 codex P2): a 429 IS the limiter shedding load, so writing a
    durable audit row per throttled request would defeat the throttle. The
    successful call is audited (query.execute); the 429s add no reject rows."""
    from app.modules.auth.router import limiter
    from app.processing.ai import query_router

    owner = await _admin_id(client, admin_auth_header)
    tbl = await _make_table(test_db_session, owner)
    before_reject = len(await _audit_rows(test_db_session, "query.reject"))

    monkeypatch.setattr(query_router, "_QUERY_PER_USER_LIMIT", "1/minute")
    limiter.enabled = True
    if hasattr(limiter, "_storage") and hasattr(limiter._storage, "reset"):
        limiter._storage.reset()
    try:
        statuses = []
        for _ in range(3):
            resp = await client.post(
                "/query/",
                json={"sql": f"SELECT gid FROM data.{tbl}", "restrict_tables": [tbl]},
                headers=admin_auth_header,
            )
            statuses.append(resp.status_code)
    finally:
        limiter.enabled = False
        if hasattr(limiter, "_storage") and hasattr(limiter._storage, "reset"):
            limiter._storage.reset()

    assert statuses.count(429) >= 1, statuses
    after_reject = len(await _audit_rows(test_db_session, "query.reject"))
    assert after_reject == before_reject

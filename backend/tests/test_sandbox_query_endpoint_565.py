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
                f"pg_user AS (SELECT gid FROM data.{tbl}) SELECT * FROM leak"
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

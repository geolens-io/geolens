"""The SQL sandbox and chat's query_data bound how many result bytes leave the database."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select, text

from app.modules.auth.models import User
from app.platform.sandbox import validate_and_execute
from app.platform.sandbox import executor
from app.platform.sandbox.executor import execute_safe
from app.platform.sandbox.schemas import SandboxError, SandboxResult
from app.processing.ai.chat_geojson import safe_rows
from app.processing.ai.chat_service import _handle_query_data
from app.processing.ai.schemas import ChatMapLayer

from tests.factories import create_dataset


async def _admin(session) -> User:
    result = await session.execute(select(User).where(User.username == "admin"))
    return result.scalar_one()


async def _labelled_table(session, owner: uuid.UUID) -> str:
    tbl = f"rb_{uuid.uuid4().hex[:10]}"
    await session.execute(text(f"CREATE TABLE data.{tbl} (gid int, label text)"))
    await session.execute(text(f"INSERT INTO data.{tbl} VALUES (1, 'a'), (2, 'b')"))
    await session.commit()
    await create_dataset(session, created_by=owner, table_name=tbl)
    return tbl


def _layer() -> ChatMapLayer:
    return ChatMapLayer(
        id="layer-1",
        name="Parks",
        dataset_id=str(uuid.uuid4()),
        dataset_table_name="parks",
        geometry_type="MultiPolygon",
    )


class TestExecutorByteCap:
    async def test_rows_past_the_cap_are_cut_and_flagged(self, client, test_db_session):
        result = await execute_safe(
            test_db_session,
            "SELECT n, 'xxxxxxxxxx' AS pad FROM generate_series(1, 100) AS t(n)",
            max_result_bytes=200,
        )
        assert result.columns == ["n", "pad"]
        assert 0 < result.row_count < 100
        assert result.truncated is True
        assert result.rows[0] == [1, "xxxxxxxxxx"]

    async def test_a_first_row_past_the_cap_is_refused(self, client, test_db_session):
        with pytest.raises(SandboxError) as exc_info:
            await execute_safe(
                test_db_session,
                "SELECT format('%20000s', '') AS pad",
                max_result_bytes=10_000,
            )
        assert exc_info.value.category == "result_too_large"

    async def test_a_column_named_like_the_row_alias_is_still_measured(
        self, client, test_db_session
    ):
        with pytest.raises(SandboxError) as exc_info:
            await execute_safe(
                test_db_session,
                "SELECT 'a' AS _l, format('%20000s', '') AS pad",
                max_result_bytes=10_000,
            )
        assert exc_info.value.category == "result_too_large"

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT n, n * 2 AS x FROM generate_series(1, 50) AS t(n) ORDER BY n DESC",
            "SELECT 1 AS x, 2 AS x",
            "SELECT n FROM generate_series(1, 0) AS t(n)",
            "SELECT n FROM generate_series(1, 1100) AS t(n)",
            "SELECT 1 AS _geolens_total_bytes, 2 AS _geolens_row_bytes",
        ],
    )
    async def test_a_result_under_the_cap_is_unchanged(
        self, client, test_db_session, sql
    ):
        bounded = await execute_safe(
            test_db_session, sql, max_result_bytes=executor.DEFAULT_MAX_RESULT_BYTES
        )
        unbounded = await execute_safe(test_db_session, sql)
        assert bounded == unbounded

    @pytest.mark.parametrize(
        ("sql", "expected"),
        [
            (
                "SELECT n FROM generate_series(1, 5) AS t(n) ORDER BY n DESC -- tail",
                [[5], [4], [3], [2], [1]],
            ),
            (
                "WITH c AS (SELECT n FROM generate_series(1, 20) AS t(n)) "
                "SELECT n FROM c ORDER BY n DESC LIMIT 3",
                [[20], [19], [18]],
            ),
            (
                "SELECT 3 AS n UNION ALL SELECT 1 UNION ALL SELECT 2 "
                "ORDER BY n DESC LIMIT 2",
                [[3], [2]],
            ),
        ],
    )
    async def test_the_wrapper_keeps_statement_shape_and_order(
        self, client, test_db_session, sql, expected
    ):
        result = await execute_safe(
            test_db_session, sql, max_result_bytes=executor.DEFAULT_MAX_RESULT_BYTES
        )
        assert result.rows == expected
        assert result.truncated is False

    @pytest.mark.parametrize(
        "literal",
        [
            "geolens_sandbox_result_too_large 9",
            "geolens_result_too_large_0123456789ab 9",
        ],
    )
    async def test_a_caller_marker_string_is_not_a_size_refusal(
        self, client, test_db_session, literal
    ):
        sql = f"SELECT ('{literal}')::int AS n"
        categories = []
        for cap in (None, 10_000):
            with pytest.raises(SandboxError) as exc_info:
                await execute_safe(test_db_session, sql, max_result_bytes=cap)
            categories.append(exc_info.value.category)
        assert categories[1] == categories[0] != "result_too_large"


class TestValidateAndExecuteByteCap:
    async def test_the_cap_is_on_by_default(self, monkeypatch):
        captured: dict[str, object] = {}

        async def _fake(db, sql, **kwargs):
            captured.update(kwargs)
            return SandboxResult(rows=[], columns=[], row_count=0, truncated=False)

        async def _allow(db, user, **kwargs):
            return {"cities"}

        monkeypatch.setattr("app.platform.sandbox.execute_safe", _fake)
        monkeypatch.setattr("app.platform.sandbox.build_table_allowlist", _allow)
        await validate_and_execute("SELECT name FROM data.cities", None, None)
        assert captured["max_result_bytes"] == executor.DEFAULT_MAX_RESULT_BYTES

    @pytest.mark.parametrize(
        "projection",
        [
            "format('%20000s', label)",
            "replace(format('%100s', label), ' ', format('%200s', label))",
        ],
    )
    async def test_an_amplifying_chat_query_is_refused(
        self, client, test_db_session, projection
    ):
        admin = await _admin(test_db_session)
        tbl = await _labelled_table(test_db_session, admin.id)
        with pytest.raises(SandboxError) as exc_info:
            await validate_and_execute(
                f"SELECT {projection} AS v FROM data.{tbl}",
                test_db_session,
                admin,
                max_result_bytes=10_000,
            )
        assert exc_info.value.category == "result_too_large"

    async def test_an_ordinary_chat_query_is_unchanged(self, client, test_db_session):
        admin = await _admin(test_db_session)
        tbl = await _labelled_table(test_db_session, admin.id)
        result = await validate_and_execute(
            f"SELECT gid, upper(label) AS l FROM data.{tbl} ORDER BY gid",
            test_db_session,
            admin,
        )
        assert result.columns == ["gid", "l"]
        assert result.rows == [[1, "A"], [2, "B"]]
        assert result.truncated is False


class TestModelFacingRows:
    def test_a_long_cell_is_cut_with_a_marker(self):
        [[cell]] = safe_rows([["x" * 5000]])
        assert cell == "x" * 1000 + "…"

    def test_rows_past_the_budget_are_dropped_after_the_first(self):
        rows = [["y" * 1000] for _ in range(200)]
        out = safe_rows(rows)
        assert 1 <= len(out) < len(rows)
        assert safe_rows([["y" * 100_000]]) == [["y" * 1000 + "…"]]

    async def test_query_data_flags_rows_it_dropped(self):
        wide = SandboxResult(
            rows=[[i, "z" * 5000, "w" * 5000] for i in range(50)],
            columns=["id", "note", "memo"],
            row_count=50,
            truncated=False,
        )
        with (
            patch(
                "app.processing.ai.chat_service.generate_sql",
                new_callable=AsyncMock,
                return_value="SELECT id, note, memo FROM data.parks",
            ),
            patch(
                "app.processing.ai.chat_service.validate_and_execute",
                new_callable=AsyncMock,
                return_value=wide,
            ),
        ):
            out = await _handle_query_data(
                {"question": "notes"},
                AsyncMock(),
                SimpleNamespace(id=uuid.uuid4(), username="u"),
                [_layer()],
            )
        assert out["row_count"] == 50
        assert out["truncated"] is True
        assert out["rows_truncated"] is True
        assert 1 <= len(out["rows"]) < 50
        assert all(len(row[1]) == len(row[2]) == 1001 for row in out["rows"])

    async def test_dropped_table_rows_leave_a_complete_overlay_untruncated(self):
        point = '{"type": "Point", "coordinates": [1.0, 2.0]}'
        spatial = SandboxResult(
            rows=[[i, "z" * 5000, "w" * 5000, point] for i in range(50)],
            columns=["id", "note", "memo", "geom_4326"],
            row_count=50,
            truncated=False,
        )
        with (
            patch(
                "app.processing.ai.chat_service.generate_sql",
                new_callable=AsyncMock,
                return_value="SELECT id, note, memo, geom_4326 FROM data.parks",
            ),
            patch(
                "app.processing.ai.chat_service.validate_and_execute",
                new_callable=AsyncMock,
                return_value=spatial,
            ),
        ):
            out = await _handle_query_data(
                {"question": "notes"},
                AsyncMock(),
                SimpleNamespace(id=uuid.uuid4(), username="u"),
                [_layer()],
            )
        assert len(out["geojson"]["features"]) == 50
        assert out["truncated"] is False
        assert out["rows_truncated"] is True
        assert 1 <= len(out["rows"]) < 50


async def test_raw_endpoint_maps_an_oversized_result_to_422(
    client, admin_auth_header, monkeypatch
):
    from app.processing.ai import query_router

    monkeypatch.setattr(
        query_router,
        "validate_and_execute",
        AsyncMock(
            side_effect=SandboxError(
                "result_too_large", "Query result is too large to return"
            )
        ),
    )
    resp = await client.post(
        "/query/",
        json={"sql": "SELECT gid FROM data.t", "restrict_tables": ["t"]},
        headers=admin_auth_header,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Query result is too large to return"

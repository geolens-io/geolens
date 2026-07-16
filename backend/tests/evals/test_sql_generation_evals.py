"""Assertion-based AI evals for NL->SQL generation (geosql follow-up, #531/#534).

These call the REAL ``generate_sql()`` against the configured LLM provider and
execute the output through the production sandbox (``validate_and_execute``),
asserting on two layers:

1. **SQL predicates** — structural requirements on the generated SQL (e.g. a
   meters/degrees question must use ``::geography``).
2. **Result assertions** — the executed value compared to ground truth
   computed from the same seeded rows by direct SQL, with tolerance where the
   model has legitimate freedom.

Every case also implicitly asserts the sandbox ACCEPTS the generated SQL — a
model drifting into disallowed constructs fails validation loudly.

These are the first AI regression evals in the repo. They cost real provider
tokens, so they are SKIPPED unless ``RUN_AI_EVALS=1``. Run them on the host
against the dev Postgres with the provider key exported:

    cd backend && set -a && source ../.env.test && set +a && \\
        RUN_AI_EVALS=1 uv run pytest tests/evals/ -v

(``ANTHROPIC_API_KEY`` / the configured provider's key must be in the
environment; the dev stack's ``.env`` has it.)

Flake policy: temperature is 0.0 in ``generate_sql`` and every assertion
leaves the model freedom where it legitimately has it (column order, aliases,
exact SQL shape). A failure here is a signal about prompt/model drift, not
ordinary test flake — investigate before rerunning.
"""

import os
import re
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.core.config import settings
from app.modules.auth.models import User
from app.platform.sandbox import SandboxResult, validate_and_execute
from app.processing.ai.schemas import ChatMapLayer
from app.processing.ai.sql_generator import build_sql_schema_context, generate_sql

from tests.factories import create_dataset

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        os.environ.get("RUN_AI_EVALS") != "1",
        reason="live-provider AI evals; set RUN_AI_EVALS=1 to run",
    ),
]

# name, category, envelope (west, south, east, north) around NYC. Sizes are
# STRICTLY ordered under both degree-area and geography-area (no ties), so
# the top-3 ordering is unambiguous regardless of how the model measures:
# 0.030x0.040 > 0.030x0.020 > 0.012x0.012 > 0.010x0.010 > 0.005x0.004 > 0.002x0.002.
# Insertion order deliberately does NOT match size order — the smallest park
# is first and the largest mid-list, so a bare `SELECT ... LIMIT n` that
# ignores area cannot pass the superlative or top-N evals on row order alone.
_PARKS = [
    ("Elm Commons", "pocket", (-73.900, 40.680, -73.898, 40.682)),
    ("River Bend Park", "community", (-73.930, 40.700, -73.920, 40.710)),
    ("Riverside Walk", "community", (-73.995, 40.740, -73.990, 40.744)),
    ("Central Green", "regional", (-73.980, 40.760, -73.950, 40.800)),
    ("Sunset Park", "community", (-74.010, 40.645, -73.998, 40.657)),
    ("North Meadow", "regional", (-73.970, 40.850, -73.940, 40.870)),
]
_LARGEST = "Central Green"
_TOP3 = ["Central Green", "North Meadow", "Sunset Park"]
_RIVER_NAMES = {"River Bend Park", "Riverside Walk"}


@pytest.fixture
async def eval_dataset(test_db_session):
    """Seed a real data.* table + catalog Dataset so the sandbox allowlist
    resolves it, and precompute geography-based ground truth from the rows.

    The table name is unique per test (catalog.datasets.table_name is unique)
    and the teardown removes both the data table and the catalog rows so the
    shared dev DB is left clean.
    """
    session = test_db_session
    table = f"eval_parks_{uuid.uuid4().hex[:8]}"
    await session.execute(
        text(
            f"CREATE TABLE data.{table} ("
            "gid serial PRIMARY KEY, name text, category text, "
            "geom_4326 geometry(Polygon, 4326))"
        )
    )
    for name, category, (w, s, e, n) in _PARKS:
        await session.execute(
            text(
                f"INSERT INTO data.{table} (name, category, geom_4326) VALUES "
                f"(:name, :category, ST_MakeEnvelope({w}, {s}, {e}, {n}, 4326))"
            ),
            {"name": name, "category": category},
        )
    await session.commit()

    result = await session.execute(
        select(User).where(User.username == settings.geolens_admin_username)
    )
    admin = result.scalar_one()

    dataset = await create_dataset(
        session,
        created_by=admin.id,
        name="Eval Parks",
        table_name=table,
        geometry_type="Polygon",
        feature_count=len(_PARKS),
        column_info=[
            {"name": "gid", "type": "integer"},
            {"name": "name", "type": "text"},
            {"name": "category", "type": "text"},
        ],
    )
    dataset_id, record_id = dataset.id, dataset.record_id

    truth_acres = (
        await session.execute(
            text(
                f"SELECT SUM(ST_Area(geom_4326::geography)) / 4046.8564224 FROM data.{table}"
            )
        )
    ).scalar_one()

    layer = ChatMapLayer(
        id="eval-layer",
        name="Eval Parks",
        dataset_id=str(dataset_id),
        dataset_table_name=table,
        geometry_type="Polygon",
        column_info=dataset.column_info,
        dataset_title="Eval Parks",
        feature_count=len(_PARKS),
    )
    schema_context = build_sql_schema_context([layer])

    yield {
        "admin": admin,
        "schema_context": schema_context,
        "truth_acres": float(truth_acres),
    }

    await session.execute(
        text("DELETE FROM catalog.datasets WHERE id = :id"), {"id": dataset_id}
    )
    await session.execute(
        text("DELETE FROM catalog.records WHERE id = :id"), {"id": record_id}
    )
    await session.execute(text(f"DROP TABLE IF EXISTS data.{table}"))
    await session.commit()


async def _ask(session, ctx, question: str) -> tuple[str, SandboxResult]:
    """Generate SQL for a question and execute it through the sandbox."""
    sql = await generate_sql(session, question, ctx["schema_context"])
    result = await validate_and_execute(sql, session, ctx["admin"])
    return sql, result


def _cells(result: SandboxResult) -> list:
    """All cell values across rows, flattened (column order is model freedom)."""
    return [cell for row in result.rows for cell in row]


def _numbers(result: SandboxResult) -> list[float]:
    # Decimal included: ROUND(...::numeric) is legitimate SQL and arrives as
    # Decimal from the driver, not float.
    return [float(c) for c in _cells(result) if isinstance(c, (int, float, Decimal))]


async def test_count_rows(client, test_db_session, eval_dataset):
    """A plain count must come back exact."""
    _sql, result = await _ask(
        test_db_session, eval_dataset, "How many parks are in this dataset?"
    )
    assert _numbers(result), f"no numeric cell in result: {result}"
    assert _numbers(result)[0] == len(_PARKS)


async def test_area_uses_geography_and_magnitude(client, test_db_session, eval_dataset):
    """The classic degrees/meters trap: an acres question must cast to
    geography, and the executed total must be within 10% of ground truth."""
    sql, result = await _ask(
        test_db_session, eval_dataset, "What is the total area of all parks, in acres?"
    )
    # Either cast syntax is fine — ::geography or CAST(... AS geography) —
    # the eval cares that meters come from geography, not how it's spelled.
    assert re.search(
        r"::\s*geography|\bcast\s*\([^)]*\bas\s+geography\s*\)", sql, re.IGNORECASE
    ), f"no geography cast for a unit question:\n{sql}"
    nums = _numbers(result)
    assert nums, f"no numeric cell in result: {result}"
    truth = eval_dataset["truth_acres"]
    assert any(abs(n - truth) / truth < 0.10 for n in nums), (
        f"no cell within 10% of truth {truth:.0f} acres: {nums}\nSQL: {sql}"
    )


async def test_largest_park(client, test_db_session, eval_dataset):
    """Superlative question resolves to the geometrically largest feature,
    ISOLATED — a query that returns every park must fail even though the
    right answer appears somewhere in it (#537 review)."""
    sql, result = await _ask(
        test_db_session, eval_dataset, "Which park has the largest area?"
    )
    assert result.row_count == 1, (
        f"expected a single-row answer, got {result.row_count} rows\nSQL: {sql}"
    )
    names = [c for c in _cells(result) if isinstance(c, str)]
    assert _LARGEST in names, f"expected {_LARGEST!r} in {names}\nSQL: {sql}"


async def test_name_filter_matches_expected_set(client, test_db_session, eval_dataset):
    """Substring filter finds exactly the two 'river' parks (case-insensitive)."""
    sql, result = await _ask(
        test_db_session, eval_dataset, "List the parks with 'river' in their name."
    )
    names = {
        c for c in _cells(result) if isinstance(c, str) and c in {p[0] for p in _PARKS}
    }
    assert names == _RIVER_NAMES, f"expected {_RIVER_NAMES}, got {names}\nSQL: {sql}"


async def test_top_n_is_limited_and_ordered(client, test_db_session, eval_dataset):
    """Top-N question returns exactly the known top 3, in order. Requires an
    ORDER BY — with the largest park inserted first, a bare LIMIT 3 would
    otherwise pass on insertion order alone (#537 review)."""
    sql, result = await _ask(
        test_db_session,
        eval_dataset,
        "What are the 3 largest parks by area, largest first?",
    )
    assert re.search(r"\border\s+by\b", sql, re.IGNORECASE), f"no ORDER BY:\n{sql}"
    assert re.search(r"\blimit\s+3\b", sql, re.IGNORECASE), f"no LIMIT 3:\n{sql}"
    assert result.row_count == 3, f"expected 3 rows, got {result.row_count}"
    all_names = {p[0] for p in _PARKS}
    row_names = [
        next((c for c in row if isinstance(c, str) and c in all_names), None)
        for row in result.rows
    ]
    assert row_names == _TOP3, f"expected {_TOP3}, got {row_names}\nSQL: {sql}"

"""The semantic arm binds its candidate ids as one array, not one parameter each."""

import uuid

import pytest
from sqlalchemy import func, select

from app.modules.catalog.datasets.domain.models import Record
from app.modules.catalog.search.service_semantic import SemanticArm

# asyncpg refuses a statement with more than 32,767 bind parameters.
_OVER_BIND_LIMIT = 40_000


def _arm(ids: list[str]) -> SemanticArm:
    return SemanticArm(
        query_vector=[0.0],
        model_name="m",
        config_fingerprint="f",
        ordered_ids=tuple(ids),
        window=len(ids),
        exact=True,
    )


def _ids(n: int) -> list[str]:
    return [str(uuid.uuid4()) for _ in range(n)]


@pytest.mark.anyio
async def test_clause_executes_past_the_bind_limit(test_db_session):
    clause = _arm(_ids(_OVER_BIND_LIMIT)).clause()
    count = (
        await test_db_session.execute(
            select(func.count()).select_from(Record).where(clause)
        )
    ).scalar_one()
    assert count == 0

"""Per-user daily AI token budget — `_check_ai_budget` (demo cost audit §3).

Complements the PERF-009 per-*request* loop budget: this caps a user's
*cumulative* input+output tokens over a rolling 24h window across many requests,
so an editor can't sustain heavy tool loops indefinitely. Defaults to 0
(unlimited); an operator opts in via ``MAX_AI_TOKENS_PER_USER_PER_DAY``.

The cap getter is patched (config resolution is covered by test_persistent_config);
real ``catalog.ai_token_usage`` rows exercise the SUM + window + threshold logic.

Verify fail-before: drop the ``created_at >= cutoff`` clause and
`test_budget_window_excludes_old_usage` FAILS (stale usage would trip the cap);
drop the ``used >= cap`` raise and `test_budget_blocks_when_over` FAILS.
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from app.core.persistent_config import MAX_AI_TOKENS_PER_USER_PER_DAY
from app.processing.ai.router import _check_ai_budget
from app.processing.ai.token_usage import AITokenUsage
from tests.factories import get_user_id


def _patch_cap(monkeypatch, cap: int) -> None:
    async def _fake_get(_db):
        return cap

    monkeypatch.setattr(MAX_AI_TOKENS_PER_USER_PER_DAY, "get", _fake_get)


async def _reset_usage(db, user_id: uuid.UUID) -> None:
    await db.execute(delete(AITokenUsage).where(AITokenUsage.user_id == user_id))
    await db.commit()


async def _add_usage(db, user_id, inp, out, *, hours_ago: float = 0.0) -> None:
    db.add(
        AITokenUsage(
            user_id=user_id,
            subsystem="chat",
            model="test",
            input_tokens=inp,
            output_tokens=out,
            created_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        )
    )
    await db.commit()


async def test_budget_blocks_when_over(test_db_session, monkeypatch):
    """Recent usage at/over the cap raises 429; under it passes."""
    uid = await get_user_id(test_db_session, "admin")
    await _reset_usage(test_db_session, uid)
    await _add_usage(test_db_session, uid, 600, 600)  # 1200 tokens, now
    user = SimpleNamespace(id=uid)

    _patch_cap(monkeypatch, 1000)  # 1200 >= 1000
    with pytest.raises(HTTPException) as exc:
        await _check_ai_budget(test_db_session, user)
    assert exc.value.status_code == 429

    _patch_cap(monkeypatch, 100_000)  # well under
    await _check_ai_budget(test_db_session, user)  # must not raise

    await _reset_usage(test_db_session, uid)


async def test_budget_zero_is_unlimited(test_db_session, monkeypatch):
    """cap=0 (default) never blocks, even with usage present."""
    uid = await get_user_id(test_db_session, "admin")
    await _reset_usage(test_db_session, uid)
    await _add_usage(test_db_session, uid, 10_000, 10_000)
    _patch_cap(monkeypatch, 0)
    await _check_ai_budget(test_db_session, SimpleNamespace(id=uid))  # no raise
    await _reset_usage(test_db_session, uid)


async def test_budget_window_excludes_old_usage(test_db_session, monkeypatch):
    """Usage older than 24h does not count toward the daily budget."""
    uid = await get_user_id(test_db_session, "admin")
    await _reset_usage(test_db_session, uid)
    await _add_usage(test_db_session, uid, 999_999, 0, hours_ago=25)  # stale, huge
    await _add_usage(test_db_session, uid, 50, 50, hours_ago=0)  # 100 recent
    user = SimpleNamespace(id=uid)

    _patch_cap(monkeypatch, 1000)  # only recent (100) counts -> under cap
    await _check_ai_budget(test_db_session, user)  # must not raise

    await _add_usage(test_db_session, uid, 600, 600)  # +1200 recent -> now over
    with pytest.raises(HTTPException) as exc:
        await _check_ai_budget(test_db_session, user)
    assert exc.value.status_code == 429

    await _reset_usage(test_db_session, uid)

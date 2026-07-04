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
from app.processing.ai.token_usage import AITokenUsage, record_token_usage
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


async def test_record_token_usage_commits_own_session(monkeypatch):
    """codex P1 #402: accounting must commit in its OWN session, not rely on the
    caller committing.

    The streaming/chat AI paths never commit their request session (``get_db()``
    doesn't commit on success), so the prior savepoint-only write was dropped and
    the cap was bypassable. This asserts ``record_token_usage`` opens a session
    and commits it — the passed caller session is ignored. Revert to the
    savepoint-no-commit version and this fails (commit never called).
    """
    events = {"added": 0, "committed": 0}

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        def add(self, _obj):
            events["added"] += 1

        async def commit(self):
            events["committed"] += 1

    monkeypatch.setattr(
        "app.processing.ai.token_usage.async_session", lambda: _FakeSession()
    )

    # First arg (caller session) is intentionally ignored — pass a sentinel that
    # would blow up if used, proving independence.
    await record_token_usage(
        object(),
        user_id=uuid.uuid4(),
        subsystem="chat",
        model="test",
        input_tokens=1,
        output_tokens=2,
    )
    assert events["added"] == 1
    assert events["committed"] == 1, "usage must be committed in its own session"


def test_max_ai_tokens_validator_rejects_negative():
    """codex P3 #402: the settings API must reject a negative cap (which would
    persist as 'overridden' yet behave as unlimited via the cap>0 guard)."""
    from app.modules.settings.schemas import (
        validate_max_ai_tokens_per_user_per_day as validate,
    )

    assert validate(0) == 0  # unlimited sentinel
    assert validate(50_000) == 50_000
    with pytest.raises(ValueError):
        validate(-1)


async def test_metadata_path_records_usage(monkeypatch):
    """codex P1 #402 (round 2): metadata-assist must count toward the cap.

    The 4 /ai/metadata/* endpoints are budget-gated but previously recorded no
    usage, so the cap was bypassable through them. _generate_structured now
    surfaces provider token counts and records them as subsystem 'metadata'.
    """
    from pydantic import BaseModel

    from app.processing.ai import metadata_service as ms

    class _M(BaseModel):
        pass

    class _FakeProvider:
        async def structured_complete(self, **_kw):
            return _M(), 111, 222

    monkeypatch.setattr(ms, "get_ai_provider", lambda _name: _FakeProvider())

    captured: dict = {}

    async def _fake_record(
        _db, *, user_id, subsystem, model, input_tokens, output_tokens
    ):
        captured.update(
            user_id=user_id,
            subsystem=subsystem,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    monkeypatch.setattr(ms, "record_token_usage", _fake_record)

    uid = uuid.uuid4()
    result = await ms._generate_structured("sys", "prompt", _M, db=None, user_id=uid)

    assert isinstance(result, _M)
    assert captured["subsystem"] == "metadata"
    assert captured["user_id"] == uid
    assert captured["input_tokens"] == 111
    assert captured["output_tokens"] == 222

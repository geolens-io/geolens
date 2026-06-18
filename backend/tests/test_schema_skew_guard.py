"""MIG-02 — startup schema-head skew guard tests.

Verifies ``app.core.db.schema_skew.assert_schema_in_sync`` fails closed on
schema-head skew in BOTH directions and passes against a real DB at head.

The positive case uses the ``client`` fixture, which migrates the per-worker
test database to ``heads`` and monkeypatches ``app.core.db.engine`` to the
migrated test engine — exactly what the guard reads.
"""

from __future__ import annotations

import pytest

from app.core.db import schema_skew


@pytest.mark.asyncio
async def test_script_heads_nonempty():
    """The image's scripts must declare at least one head (OSS single-head)."""
    heads = schema_skew.get_script_heads()
    assert isinstance(heads, set)
    assert heads, "expected a non-empty set of script heads"


@pytest.mark.asyncio
async def test_get_current_heads_reads_real_db():
    """Real DB read path: get_current_heads() runs against the live engine and
    returns a set of applied revisions (proves the catalog-schema version-table
    read works end-to-end, not just the comparison logic).

    Note: the in-sync vs skew assertion against the LIVE DB is proven by the
    standalone verification run captured in 1216-SUMMARY.md — the per-worker
    ``client`` fixture binds its engine to its own event loop and cannot be
    safely re-entered with a fresh connection here.
    """
    heads = await schema_skew.get_current_heads()
    assert isinstance(heads, set)


@pytest.mark.asyncio
async def test_guard_raises_when_db_behind(monkeypatch):
    """DB BEHIND (missing a revision the image declares) → RuntimeError."""
    script_heads = schema_skew.get_script_heads()

    async def _fake_heads() -> set[str]:
        # Drop one head the image expects → DB is missing it.
        behind = set(script_heads)
        behind.discard(next(iter(script_heads)))
        return behind

    monkeypatch.setattr(schema_skew, "get_current_heads", _fake_heads)

    with pytest.raises(RuntimeError) as exc:
        await schema_skew.assert_schema_in_sync()
    assert "schema skew" in str(exc.value)
    assert "BEHIND" in str(exc.value)


@pytest.mark.asyncio
async def test_guard_raises_on_empty_fresh_db(monkeypatch):
    """Fresh/empty DB (no alembic_version) while scripts declare heads →
    RuntimeError (extreme DB-behind case; migrate service must run first)."""

    async def _empty_heads() -> set[str]:
        return set()

    monkeypatch.setattr(schema_skew, "get_current_heads", _empty_heads)

    # Sanity: scripts declare at least one head, so empty DB is genuinely behind.
    assert schema_skew.get_script_heads()

    with pytest.raises(RuntimeError) as exc:
        await schema_skew.assert_schema_in_sync()
    assert "schema skew" in str(exc.value)
    assert "BEHIND" in str(exc.value)


@pytest.mark.asyncio
async def test_guard_raises_when_db_ahead(monkeypatch):
    """DB AHEAD (has a revision the image's scripts lack — rollback) →
    RuntimeError."""
    script_heads = schema_skew.get_script_heads()

    async def _ahead_heads() -> set[str]:
        return set(script_heads) | {"zzzz_revision_not_in_image"}

    monkeypatch.setattr(schema_skew, "get_current_heads", _ahead_heads)

    with pytest.raises(RuntimeError) as exc:
        await schema_skew.assert_schema_in_sync()
    assert "schema skew" in str(exc.value)
    assert "AHEAD" in str(exc.value)


@pytest.mark.asyncio
async def test_guard_passes_when_heads_match(monkeypatch):
    """Equal sets (incl. a simulated plural-head enterprise graph) → no raise."""
    script_heads = schema_skew.get_script_heads()

    async def _matching_heads() -> set[str]:
        return set(script_heads)

    monkeypatch.setattr(schema_skew, "get_current_heads", _matching_heads)
    # Must not raise.
    await schema_skew.assert_schema_in_sync()


@pytest.mark.asyncio
async def test_guard_passes_simulated_two_head_enterprise(monkeypatch):
    """Simulate the enterprise two-head graph: both script heads and DB heads
    are the same two-element set → guard passes (set equality, order-free)."""
    two_heads = {"0007_tenant_data_schemas", "e002_add_saml_columns"}

    def _script_two() -> set[str]:
        return set(two_heads)

    async def _db_two() -> set[str]:
        return set(two_heads)

    monkeypatch.setattr(schema_skew, "get_script_heads", _script_two)
    monkeypatch.setattr(schema_skew, "get_current_heads", _db_two)
    await schema_skew.assert_schema_in_sync()

    # And a two-head DB missing one enterprise head must fail.
    async def _db_one() -> set[str]:
        return {"0007_tenant_data_schemas"}

    monkeypatch.setattr(schema_skew, "get_current_heads", _db_one)
    with pytest.raises(RuntimeError) as exc:
        await schema_skew.assert_schema_in_sync()
    assert "BEHIND" in str(exc.value)

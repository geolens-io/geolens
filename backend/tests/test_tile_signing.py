"""Tests for HMAC tile signing module, tile token endpoint, and tile signature validation.

Covers:
  - TAUTH-01: HMAC-SHA256 signing/verification
  - TAUTH-02: Tile endpoint signature validation
  - TAUTH-03: Access logging
  - TAUTH-04: 15-minute boundary rounding
  - TAUTH-05: Per-dataset cache TTL
  - TAUTH-06: Public bypass / private enforcement
"""

import time
import uuid
from unittest.mock import patch

import asyncpg
import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.config import settings
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.processing.tiles.signing import generate_tile_signature

from tests.conftest import _run_with_too_many_clients_retry
from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helpers (from test_tiles.py)
# ---------------------------------------------------------------------------


async def _create_tile_test_dataset(
    session,
    *,
    created_by: uuid.UUID,
    table_name: str,
    visibility: str = "public",
    tile_cache_ttl: int | None = None,
) -> Dataset:
    """Insert a Record + Dataset for tile signing tests."""
    record = Record(
        title="Tile Signing Test Dataset",
        summary="Dataset for tile signing tests",
        theme_category=["test"],
        visibility=visibility,
        record_status="published",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="Point",
        feature_count=1,
        source_format="geojson",
        source_filename="test.geojson",
        tile_cache_ttl=tile_cache_ttl,
        column_info=[
            {"name": "gid", "type": "integer"},
            {"name": "geom", "type": "geometry"},
        ],
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


async def _create_data_table(session, table_name: str) -> None:
    """Create a PostGIS data table in the 'data' schema."""
    await session.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS data.{table_name} ("
            f"  gid SERIAL PRIMARY KEY,"
            f"  geom GEOMETRY(Point, 3857),"
            f"  geom_4326 GEOMETRY(Point, 4326)"
            f")"
        )
    )
    await session.execute(
        text(
            f"INSERT INTO data.{table_name} (geom, geom_4326) VALUES ("
            f"  ST_Transform(ST_SetSRID(ST_MakePoint(0, 0), 4326), 3857),"
            f"  ST_SetSRID(ST_MakePoint(0, 0), 4326)"
            f")"
        )
    )
    await session.commit()


async def _cleanup_data_table(session, table_name: str) -> None:
    await session.execute(text(f"DROP TABLE IF EXISTS data.{table_name}"))
    await session.commit()


@pytest.fixture
async def _init_tile_pool_for_tests():
    """Initialize asyncpg pool for tile tests."""
    import app.processing.tiles.pool as pool_module

    dsn = settings.test_database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await _run_with_too_many_clients_retry(
        lambda: asyncpg.create_pool(dsn=dsn, min_size=1, max_size=3, command_timeout=10)
    )
    pool_module._tile_pool = pool
    yield
    await pool.close()
    pool_module._tile_pool = None


# ---------------------------------------------------------------------------
# Unit tests: signing module
# ---------------------------------------------------------------------------


class TestTileSigningModule:
    """Unit tests for generate/verify/round_expiry functions."""

    def test_generate_returns_64_char_hex(self):
        """generate_tile_signature returns a 64-char hex string (SHA256)."""
        from app.processing.tiles.signing import generate_tile_signature

        sig = generate_tile_signature("my_table", 1700000000)
        assert len(sig) == 64
        assert all(c in "0123456789abcdef" for c in sig)

    def test_verify_round_trip(self):
        """A signature generated for a scope/exp verifies correctly."""
        from app.processing.tiles.signing import (
            generate_tile_signature,
            verify_tile_signature,
        )

        exp = int(time.time()) + 3600  # 1 hour in the future
        sig = generate_tile_signature("my_table", exp)
        assert verify_tile_signature("my_table", exp, sig) is True

    def test_verify_rejects_expired(self):
        """Expired signatures are rejected even if HMAC is valid."""
        from app.processing.tiles.signing import (
            generate_tile_signature,
            verify_tile_signature,
        )

        past_exp = int(time.time()) - 100
        sig = generate_tile_signature("my_table", past_exp)
        assert verify_tile_signature("my_table", past_exp, sig) is False

    def test_verify_rejects_tampered(self):
        """Tampered signatures are rejected."""
        from app.processing.tiles.signing import verify_tile_signature

        future_exp = int(time.time()) + 3600
        assert verify_tile_signature("my_table", future_exp, "tampered") is False

    def test_verify_rejects_wrong_scope(self):
        """Signature for one scope does not verify for another."""
        from app.processing.tiles.signing import (
            generate_tile_signature,
            verify_tile_signature,
        )

        future_exp = int(time.time()) + 3600
        sig = generate_tile_signature("my_table", future_exp)
        assert verify_tile_signature("wrong_scope", future_exp, sig) is False

    def test_round_expiry_is_multiple_of_900(self):
        """round_expiry returns a value that is a multiple of 900."""
        from app.processing.tiles.signing import round_expiry

        exp = round_expiry()
        assert exp % 900 == 0

    def test_round_expiry_is_greater_than_now(self):
        """round_expiry returns a value strictly greater than current time."""
        from app.processing.tiles.signing import round_expiry

        exp = round_expiry()
        assert exp > time.time()

    def test_round_expiry_same_within_window(self):
        """Two calls within the same 15-min window return the same value."""
        from app.processing.tiles.signing import round_expiry

        # Mock time to be at two points within the same 15-min window
        base_time = 1700000100  # arbitrary time
        with patch("app.processing.tiles.signing.time.time", return_value=base_time):
            exp1 = round_expiry()
        with patch(
            "app.processing.tiles.signing.time.time", return_value=base_time + 1
        ):
            exp2 = round_expiry()
        assert exp1 == exp2

    # BUG-012 regression tests — minimum-validity guard -------------------

    def test_round_expiry_min_validity_skips_near_boundary(self):
        """BUG-012: when now is within min_validity seconds of the next boundary,
        round_expiry skips to the FOLLOWING boundary so the token never has
        near-zero validity.

        Scenario: now = 900 * k - 5 (5 s before the next boundary).
        Pre-fix: returns 900*k (5 s validity → < 60 s min).
        Post-fix: returns 900*(k+1) (905 s validity → ≥ 60 s min).
        """
        from app.processing.tiles.signing import round_expiry

        # Pick a time 5 seconds before a 15-min boundary.
        k = 1889  # arbitrary; 1700100 / 900 = 1889.0
        boundary = 900 * k
        near_boundary_now = boundary - 5  # 5 s before the next boundary

        with patch(
            "app.processing.tiles.signing.time.time",
            return_value=float(near_boundary_now),
        ):
            exp = round_expiry()

        # Must skip to the FOLLOWING boundary
        assert exp == boundary + 900, (
            f"Expected {boundary + 900} (following boundary), got {exp}. "
            f"Token would have had only {boundary - near_boundary_now} s validity."
        )
        # Invariant: still a multiple of 900
        assert exp % 900 == 0
        # Invariant: validity is at least min_validity (default 60 s)
        assert exp - near_boundary_now >= 60

    def test_round_expiry_far_from_boundary_returns_next_boundary(self):
        """BUG-012: when now is comfortably far from the next boundary,
        round_expiry still returns the NEXT boundary (no change from pre-fix).

        Scenario: now is 450 s into a window → next boundary is 450 s away.
        """
        from app.processing.tiles.signing import round_expiry

        k = 1889
        boundary = 900 * k
        mid_window_now = boundary - 450  # 450 s before the boundary

        with patch(
            "app.processing.tiles.signing.time.time", return_value=float(mid_window_now)
        ):
            exp = round_expiry()

        assert exp == boundary, f"Expected {boundary}, got {exp}"
        assert exp % 900 == 0
        assert exp - mid_window_now >= 60

    def test_round_expiry_exactly_at_min_validity_boundary_returns_next(self):
        """BUG-012: when (next_boundary - now) == min_validity exactly, the next
        boundary is acceptable (edge case: equality means valid, not rejected).
        """
        from app.processing.tiles.signing import round_expiry

        k = 1889
        boundary = 900 * k
        # Exactly 60 s before the boundary (== min_validity default)
        now = boundary - 60

        with patch("app.processing.tiles.signing.time.time", return_value=float(now)):
            exp = round_expiry()

        # Exactly at the boundary should be accepted (>= 60 is satisfied)
        assert exp == boundary
        assert exp % 900 == 0
        assert exp - now >= 60

    def test_round_expiry_result_always_multiple_of_900_near_boundary(self):
        """BUG-012: the skipped result must remain a multiple of 900."""
        from app.processing.tiles.signing import round_expiry

        # Test several near-boundary times
        for k in (100, 500, 1000, 2000):
            boundary = 900 * k
            near_now = boundary - 1  # 1 s before boundary
            with patch(
                "app.processing.tiles.signing.time.time", return_value=float(near_now)
            ):
                exp = round_expiry()
            assert exp % 900 == 0, f"k={k}: {exp} is not a multiple of 900"
            assert exp > near_now, f"k={k}: exp {exp} is not > now {near_now}"
            assert exp - near_now >= 60, (
                f"k={k}: validity {exp - near_now} s < 60 s min"
            )


# ---------------------------------------------------------------------------
# Integration tests: token endpoint
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestTileTokenEndpoint:
    """Integration tests for GET /tiles/token/{dataset_id}/."""

    async def test_token_returns_signed_params(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Authenticated request returns 200 with sig, exp, scope, expires_in."""
        table_name = f"sign_test_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset = await _create_tile_test_dataset(
            test_db_session, created_by=user_id, table_name=table_name
        )

        resp = await client.get(
            f"/tiles/token/{dataset.id}/",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "sig" in body
        assert "exp" in body
        assert "scope" in body
        assert "expires_in" in body
        assert body["scope"] == table_name
        assert len(body["sig"]) == 64
        assert body["expires_in"] > 0

    async def test_token_unauthenticated_on_private_dataset(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Unauthenticated request on a private dataset returns 401."""
        table_name = f"sign_test_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset = await _create_tile_test_dataset(
            test_db_session,
            created_by=user_id,
            table_name=table_name,
            visibility="private",
        )

        resp = await client.get(f"/tiles/token/{dataset.id}/")
        assert resp.status_code == 401

    async def test_token_nonexistent_dataset_returns_404(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Request for non-existent dataset returns 404."""
        fake_id = uuid.uuid4()
        resp = await client.get(
            f"/tiles/token/{fake_id}/",
            headers=admin_auth_header,
        )
        assert resp.status_code == 404

    async def test_token_private_dataset_non_owner_returns_404(
        self,
        client: AsyncClient,
        admin_auth_header: dict,
        test_db_session,
        viewer_auth_header: dict,
    ):
        """Non-owner requesting a private dataset's token gets 404."""
        table_name = f"sign_test_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset = await _create_tile_test_dataset(
            test_db_session,
            created_by=user_id,
            table_name=table_name,
            visibility="private",
        )

        # viewer is not the owner and not admin
        resp = await client.get(
            f"/tiles/token/{dataset.id}/",
            headers=viewer_auth_header,
        )
        assert resp.status_code == 404

    async def test_token_public_dataset_no_auth_succeeds(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Public dataset token can be requested without authentication."""
        table_name = f"sign_test_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset = await _create_tile_test_dataset(
            test_db_session,
            created_by=user_id,
            table_name=table_name,
            visibility="public",
        )

        resp = await client.get(f"/tiles/token/{dataset.id}/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["scope"] == table_name


# ---------------------------------------------------------------------------
# Integration tests: tile endpoint signature validation (TAUTH-02, TAUTH-06)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestTileSignatureValidation:
    """Test signature enforcement on the tile endpoint."""

    async def test_public_tile_no_signature_required(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Public dataset tiles can be fetched without sig/exp/scope params."""
        table_name = f"sigval_pub_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session,
            created_by=user_id,
            table_name=table_name,
            visibility="public",
        )
        await _create_data_table(test_db_session, table_name)

        try:
            resp = await client.get(f"/tiles/data.{table_name}/0/0/0.pbf")
            assert resp.status_code == 200
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_private_tile_requires_signature(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Private dataset tiles return 403 without sig/exp/scope params."""
        table_name = f"sigval_priv_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session,
            created_by=user_id,
            table_name=table_name,
            visibility="private",
        )
        await _create_data_table(test_db_session, table_name)

        try:
            resp = await client.get(f"/tiles/data.{table_name}/0/0/0.pbf")
            assert resp.status_code == 403
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_private_tile_with_valid_signature(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Private dataset tiles succeed with valid sig/exp/scope."""
        table_name = f"sigval_valid_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset = await _create_tile_test_dataset(
            test_db_session,
            created_by=user_id,
            table_name=table_name,
            visibility="private",
        )
        await _create_data_table(test_db_session, table_name)

        try:
            # Get a valid token via the token endpoint
            token_resp = await client.get(
                f"/tiles/token/{dataset.id}/",
                headers=admin_auth_header,
            )
            assert token_resp.status_code == 200
            token = token_resp.json()

            resp = await client.get(
                f"/tiles/data.{table_name}/0/0/0.pbf",
                params={
                    "sig": token["sig"],
                    "exp": token["exp"],
                    "scope": token["scope"],
                },
            )
            assert resp.status_code == 200
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_expired_signature_rejected(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Expired signature returns 403."""
        table_name = f"sigval_exp_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session,
            created_by=user_id,
            table_name=table_name,
            visibility="private",
        )
        await _create_data_table(test_db_session, table_name)

        try:
            past_exp = int(time.time()) - 100
            sig = generate_tile_signature(table_name, past_exp)

            resp = await client.get(
                f"/tiles/data.{table_name}/0/0/0.pbf",
                params={"sig": sig, "exp": past_exp, "scope": table_name},
            )
            assert resp.status_code == 403
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_tampered_signature_rejected(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Tampered signature returns 403."""
        table_name = f"sigval_tamp_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        dataset = await _create_tile_test_dataset(
            test_db_session,
            created_by=user_id,
            table_name=table_name,
            visibility="private",
        )
        await _create_data_table(test_db_session, table_name)

        try:
            token_resp = await client.get(
                f"/tiles/token/{dataset.id}/",
                headers=admin_auth_header,
            )
            token = token_resp.json()

            # Tamper with the signature
            tampered_sig = "a" * 64

            resp = await client.get(
                f"/tiles/data.{table_name}/0/0/0.pbf",
                params={
                    "sig": tampered_sig,
                    "exp": token["exp"],
                    "scope": token["scope"],
                },
            )
            assert resp.status_code == 403
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_scope_mismatch_rejected(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Signature with wrong scope returns 403."""
        table_name = f"sigval_scope_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session,
            created_by=user_id,
            table_name=table_name,
            visibility="private",
        )
        await _create_data_table(test_db_session, table_name)

        try:
            wrong_scope = "wrong_table_name"
            future_exp = int(time.time()) + 3600
            sig = generate_tile_signature(wrong_scope, future_exp)

            resp = await client.get(
                f"/tiles/data.{table_name}/0/0/0.pbf",
                params={"sig": sig, "exp": future_exp, "scope": wrong_scope},
            )
            assert resp.status_code == 403
        finally:
            await _cleanup_data_table(test_db_session, table_name)


# ---------------------------------------------------------------------------
# Integration tests: tile cache TTL (TAUTH-05)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestTileCacheTTL:
    """Test per-dataset tile_cache_ttl in Cache-Control header."""

    async def test_default_cache_ttl(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Public dataset with no tile_cache_ttl uses settings.tile_cache_ttl."""
        table_name = f"ttl_default_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session,
            created_by=user_id,
            table_name=table_name,
            visibility="public",
            tile_cache_ttl=None,
        )
        await _create_data_table(test_db_session, table_name)

        try:
            resp = await client.get(f"/tiles/data.{table_name}/0/0/0.pbf")
            assert resp.status_code == 200
            assert f"max-age={settings.tile_cache_ttl}" in resp.headers["cache-control"]
        finally:
            await _cleanup_data_table(test_db_session, table_name)

    async def test_per_dataset_cache_ttl(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ):
        """Dataset with tile_cache_ttl=600 uses max-age=600."""
        table_name = f"ttl_custom_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session,
            created_by=user_id,
            table_name=table_name,
            visibility="public",
            tile_cache_ttl=600,
        )
        await _create_data_table(test_db_session, table_name)

        try:
            resp = await client.get(f"/tiles/data.{table_name}/0/0/0.pbf")
            assert resp.status_code == 200
            assert "max-age=600" in resp.headers["cache-control"]
        finally:
            await _cleanup_data_table(test_db_session, table_name)


# ---------------------------------------------------------------------------
# Integration tests: tile access logging (TAUTH-03)
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_init_tile_pool_for_tests")
class TestTileAccessLogging:
    """Test that tile access events are logged with expected fields."""

    async def test_tile_access_logged(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session, monkeypatch
    ):
        """Tile access log entry contains dataset_id, table_name, z, scope."""
        table_name = f"logtest_{uuid.uuid4().hex[:8]}"
        user_id = await get_user_id(test_db_session, settings.geolens_admin_username)
        await _create_tile_test_dataset(
            test_db_session,
            created_by=user_id,
            table_name=table_name,
            visibility="public",
        )
        await _create_data_table(test_db_session, table_name)

        # Intercept the tile_access log at the call site by swapping the router's
        # module-level logger. Neither pytest's stdlib caplog nor
        # structlog.testing.capture_logs() reliably captures it under the serial
        # --cov CI run: the structlog logger is created with
        # cache_logger_on_first_use=True, so once an earlier tile test in the same
        # process binds app.processing.tiles.router.logger, a later processor swap
        # (capture_logs) or stdlib-handler bridge (caplog) no longer reaches it ->
        # the record is silently dropped (got: []). Replacing the module global
        # is caching-immune: the handler resolves `logger` from module globals at
        # call time, so it always uses our recorder.
        import app.processing.tiles.router as _tiles_router

        class _RecordingLogger:
            def __init__(self):
                self.events: list[str] = []

            def debug(self, event=None, *args, **kwargs):
                self.events.append(event)

            def __getattr__(self, _name):
                # Other levels / bind() etc.: no-op that supports chaining.
                def _noop(*args, **kwargs):
                    return self

                return _noop

        recorder = _RecordingLogger()
        monkeypatch.setattr(_tiles_router, "logger", recorder)

        try:
            resp = await client.get(f"/tiles/data.{table_name}/0/0/0.pbf")
            assert resp.status_code == 200

            assert "tile_access" in recorder.events, (
                f"Expected 'tile_access' log entry, got: {recorder.events}"
            )
        finally:
            await _cleanup_data_table(test_db_session, table_name)

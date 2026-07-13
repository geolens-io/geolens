"""Live RLS regressions for opaque child-token lookup and consumption."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from starlette.requests import Request

from app.modules.auth.dependencies import _resolve_api_key
from app.modules.auth.service import (
    ApiKeyTargetUserNotFoundError,
    AuthService,
    create_api_key_for_user,
)
from app.modules.auth.verification import redeem_verification_token
from app.modules.catalog.maps.service_public import (
    _validate_share_token,
    create_share_token,
    get_active_share_token,
)

pytestmark = [
    pytest.mark.rls,
    pytest.mark.xdist_group("tenancy_global_state"),
]


def _opaque_token_hash(raw_token: str) -> str:
    """Match production lookup hashing for random, high-entropy tokens."""
    # fix(#507): these identifiers are random opaque tokens, not passwords.
    # codeql[py/weak-sensitive-data-hashing]
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _api_key_request(raw_key: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(b"x-api-key", raw_key.encode())],
            "query_string": b"",
        }
    )


async def test_opaque_child_tokens_follow_their_rls_visible_parent(
    multi_tenant_rls,
):
    """Wrong-host credentials neither resolve nor consume another tenant's row."""
    ctx = multi_tenant_rls
    raw_api_key = f"gl_{uuid.uuid4().hex}"
    raw_refresh = f"refresh_{uuid.uuid4().hex}"
    raw_verification = f"verify_{uuid.uuid4().hex}"
    raw_share = f"share_{uuid.uuid4().hex}"
    api_key_id = uuid.uuid4()
    refresh_id = uuid.uuid4()
    verification_id = uuid.uuid4()
    map_id = uuid.uuid4()
    share_id = uuid.uuid4()
    now = datetime.now(UTC)

    child_tables = (
        "api_keys",
        "refresh_tokens",
        "email_verification_tokens",
        "map_share_tokens",
    )
    engine = create_async_engine(ctx.db_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            for table in child_tables:
                await conn.execute(
                    sa.text(f"GRANT SELECT ON catalog.{table} TO geolens_reader")
                )
            await conn.execute(
                sa.text(
                    "GRANT SELECT ON catalog.roles, catalog.user_roles "
                    "TO geolens_reader"
                )
            )
            await conn.execute(
                sa.text(
                    "GRANT UPDATE ON catalog.email_verification_tokens, "
                    "catalog.refresh_tokens, catalog.users TO geolens_reader"
                )
            )

        async with engine.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO catalog.api_keys "
                    "(id, user_id, key_hash, name, is_active, created_at, last_used_at) "
                    "VALUES (:id, :user_id, :token_hash, 'tenant probe', true, "
                    "now(), now())"
                ),
                {
                    "id": api_key_id,
                    "user_id": ctx.user_a_id,
                    "token_hash": _opaque_token_hash(raw_api_key),
                },
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO catalog.refresh_tokens "
                    "(id, user_id, token_hash, expires_at, created_at, revoked) "
                    "VALUES (:id, :user_id, :token_hash, :expires_at, now(), false)"
                ),
                {
                    "id": refresh_id,
                    "user_id": ctx.user_a_id,
                    "token_hash": _opaque_token_hash(raw_refresh),
                    "expires_at": now + timedelta(hours=1),
                },
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO catalog.email_verification_tokens "
                    "(id, user_id, token_hash, expires_at, consumed_at, created_at) "
                    "VALUES (:id, :user_id, :token_hash, :expires_at, NULL, now())"
                ),
                {
                    "id": verification_id,
                    "user_id": ctx.user_a_id,
                    "token_hash": _opaque_token_hash(raw_verification),
                    "expires_at": now + timedelta(hours=1),
                },
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO catalog.maps "
                    "(id, name, visibility, created_by, tenant_id, created_at, "
                    " updated_at) VALUES (:id, 'Tenant token probe', 'private', "
                    " :user_id, :tenant_id, now(), now())"
                ),
                {
                    "id": map_id,
                    "user_id": ctx.user_a_id,
                    "tenant_id": ctx.tenant_a,
                },
            )
            await conn.execute(
                sa.text(
                    "INSERT INTO catalog.map_share_tokens "
                    "(id, map_id, token_hash, token_hint, created_by, expires_at, "
                    " is_active, created_at) VALUES (:id, :map_id, :token_hash, "
                    " 'share-probe', :user_id, :expires_at, true, now())"
                ),
                {
                    "id": share_id,
                    "map_id": map_id,
                    "token_hash": _opaque_token_hash(raw_share),
                    "user_id": ctx.user_a_id,
                    "expires_at": now + timedelta(hours=1),
                },
            )

        async with ctx.tenant_session(ctx.tenant_b) as session:
            assert (
                await _resolve_api_key(_api_key_request(raw_api_key), session) is None
            )
            assert (
                await AuthService(session).get_user_from_refresh_token(raw_refresh)
                is None
            )
            assert await redeem_verification_token(session, raw_verification) is None
            assert await _validate_share_token(session, raw_share) is None
            assert await get_active_share_token(session, map_id) is None
            with pytest.raises(ValueError, match="Map not found"):
                await create_share_token(
                    session,
                    map_id,
                    uuid.UUID(ctx.user_b_id),
                )
            with pytest.raises(ApiKeyTargetUserNotFoundError):
                await create_api_key_for_user(
                    session,
                    uuid.UUID(ctx.user_a_id),
                    "cross-tenant probe",
                )
            with pytest.raises(ValueError, match="User not found"):
                await AuthService(session).revoke_all_tokens(uuid.UUID(ctx.user_a_id))

        async with engine.connect() as conn:
            consumed = await conn.scalar(
                sa.text(
                    "SELECT consumed_at FROM catalog.email_verification_tokens "
                    "WHERE id = :id"
                ),
                {"id": verification_id},
            )
            assert consumed is None
            refresh_revoked = await conn.scalar(
                sa.text("SELECT revoked FROM catalog.refresh_tokens WHERE id = :id"),
                {"id": refresh_id},
            )
            assert refresh_revoked is False

        async with ctx.tenant_session(ctx.tenant_a) as session:
            api_user = await _resolve_api_key(_api_key_request(raw_api_key), session)
            assert api_user is not None and str(api_user.id) == ctx.user_a_id
            refresh_user = await AuthService(session).get_user_from_refresh_token(
                raw_refresh
            )
            assert refresh_user is not None and str(refresh_user.id) == ctx.user_a_id
            assert await redeem_verification_token(
                session, raw_verification
            ) == uuid.UUID(ctx.user_a_id)
            share = await _validate_share_token(session, raw_share)
            assert share not in (None, "expired") and share.id == share_id
    finally:
        async with engine.connect() as conn:
            await conn.execution_options(isolation_level="AUTOCOMMIT")
            await conn.execute(
                sa.text("DELETE FROM catalog.map_share_tokens WHERE id = :id"),
                {"id": share_id},
            )
            await conn.execute(
                sa.text("DELETE FROM catalog.maps WHERE id = :id"), {"id": map_id}
            )
            await conn.execute(
                sa.text("DELETE FROM catalog.api_keys WHERE id = :id"),
                {"id": api_key_id},
            )
            await conn.execute(
                sa.text("DELETE FROM catalog.refresh_tokens WHERE id = :id"),
                {"id": refresh_id},
            )
            await conn.execute(
                sa.text("DELETE FROM catalog.email_verification_tokens WHERE id = :id"),
                {"id": verification_id},
            )
            await conn.execute(
                sa.text(
                    "REVOKE UPDATE ON catalog.email_verification_tokens, "
                    "catalog.refresh_tokens, catalog.users FROM geolens_reader"
                )
            )
            for table in child_tables:
                await conn.execute(
                    sa.text(f"REVOKE SELECT ON catalog.{table} FROM geolens_reader")
                )
            await conn.execute(
                sa.text(
                    "REVOKE SELECT ON catalog.roles, catalog.user_roles "
                    "FROM geolens_reader"
                )
            )
        await engine.dispose()

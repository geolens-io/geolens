"""Integration tests for POST /auth/download-token/{dataset_id}.

Covers:
  1. Happy path — authenticated owner of a public dataset receives 200 + valid token.
  2. Invalid dataset — random UUID returns 404.
  3. Private non-owner — non-owner editor hitting private dataset returns 404.
  4. Anonymous public — unauthenticated request to public dataset returns 200.
  5. Anonymous private — unauthenticated request to private dataset returns 404.

End-to-end mint→consume (TestDownloadTokenConsumption, KNOWN-01 Phase 1071):
  6. Authenticated mint→consume — sub-bearing token consumed by /download/cog (auth path).
  7. Anonymous mint→consume on PUBLIC raster — no-sub token consumed (200/302).
  8. Anonymous mint REJECTED on PRIVATE raster — mint-side gate.
  9. Expired anonymous token REJECTED — exp check fires at consume.
 10. Wrong-scope anonymous token REJECTED — scope check fires at consume.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.modules.audit.models import AuditLog
from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.processing.raster.models import RasterAsset
from tests.conftest import _create_test_user, get_auth_header
from tests.factories import create_dataset


class TestDownloadTokenEndpoint:
    async def test_download_token_happy_path(
        self, client: AsyncClient, admin_auth_header, test_db_session
    ):
        """Owner of a public dataset receives 200 + download-scoped JWT."""
        from app.modules.auth.models import User
        from sqlalchemy import select

        result = await test_db_session.execute(
            select(User).where(User.username == settings.geolens_admin_username)
        )
        admin = result.scalar_one()

        dataset = await create_dataset(
            test_db_session, created_by=admin.id, visibility="public"
        )

        resp = await client.post(
            f"/auth/download-token/{dataset.id}", headers=admin_auth_header
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "token" in body
        assert body["expires_in"] == 120

        # Decode and validate token claims
        payload = jwt.decode(
            body["token"],
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        assert payload["typ"] == "download"
        assert payload["scope"] == f"dataset:{dataset.id}"
        # exp - iat <= 120s
        assert payload["exp"] - payload["iat"] <= 120

    async def test_download_token_invalid_dataset(
        self, client: AsyncClient, admin_auth_header
    ):
        """A non-existent dataset UUID returns 404."""
        fake_id = uuid.uuid4()
        resp = await client.post(
            f"/auth/download-token/{fake_id}", headers=admin_auth_header
        )
        assert resp.status_code == 404

    async def test_download_token_private_non_owner(
        self, client: AsyncClient, admin_auth_header, test_db_session
    ):
        """An editor who does not own a private dataset gets 404."""
        from app.modules.auth.models import User
        from sqlalchemy import select

        result = await test_db_session.execute(
            select(User).where(User.username == settings.geolens_admin_username)
        )
        admin = result.scalar_one()

        # Create private dataset owned by admin
        dataset = await create_dataset(
            test_db_session, created_by=admin.id, visibility="private"
        )

        # Create a separate editor user
        editor_headers, _ = await _create_test_user(
            client, admin_auth_header, "editor"
        )

        resp = await client.post(
            f"/auth/download-token/{dataset.id}", headers=editor_headers
        )
        assert resp.status_code == 404

    async def test_download_token_anonymous_public(
        self, client: AsyncClient, test_db_session, admin_auth_header
    ):
        """Anonymous request to a public dataset returns 200 + valid download token."""
        from app.modules.auth.models import User
        from sqlalchemy import select

        result = await test_db_session.execute(
            select(User).where(User.username == settings.geolens_admin_username)
        )
        admin = result.scalar_one()

        dataset = await create_dataset(
            test_db_session, created_by=admin.id, visibility="public"
        )

        # No auth headers — anonymous
        resp = await client.post(f"/auth/download-token/{dataset.id}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "token" in body
        assert body["expires_in"] == 120

        # Anonymous tokens must also be type=download and scope-bound
        payload = jwt.decode(
            body["token"],
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        assert payload["typ"] == "download"
        assert payload["scope"] == f"dataset:{dataset.id}"

    async def test_download_token_anonymous_private(
        self, client: AsyncClient, test_db_session, admin_auth_header
    ):
        """Anonymous request to a private dataset returns 404."""
        from app.modules.auth.models import User
        from sqlalchemy import select

        result = await test_db_session.execute(
            select(User).where(User.username == settings.geolens_admin_username)
        )
        admin = result.scalar_one()

        dataset = await create_dataset(
            test_db_session, created_by=admin.id, visibility="private"
        )

        resp = await client.post(f"/auth/download-token/{dataset.id}")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# KNOWN-01 (Phase 1071): End-to-end mint→consume regression pin.
# ---------------------------------------------------------------------------
#
# Before Phase 1071 the consumer (_resolve_download_user) rejected any token
# missing a `sub` claim with 401, breaking the anonymous-COG-download flow
# that the mint endpoint had been advertising since v1015 Phase 1065. These
# tests pin the closure: both authenticated and anonymous-public paths must
# work end-to-end, and the consume side must still reject expired and
# wrong-scope tokens regardless of sub-presence.
#
# The local-storage backend will 503 ("temporarily unavailable") on the
# stream step because there is no actual COG file at the raster_asset.asset_uri
# path inside the test environment — but the auth-passed signal is the
# absence of 401/403/400 from any auth/visibility/permission gate. Per the
# existing pattern in tests/test_phase_273_cog_redirect_revalidate.py
# (test_local_storage_unaffected_by_ssrf_revalidation), the contract is
# "status != 401/403", not "status == 200".
# ---------------------------------------------------------------------------


async def _create_local_raster_dataset(
    session,
    *,
    created_by: uuid.UUID,
    visibility: str = "public",
) -> tuple[Record, Dataset, RasterAsset]:
    """Create a Record + Dataset + RasterAsset with storage_backend='local'.

    Mirrors the helper in tests/test_phase_273_cog_redirect_revalidate.py
    so download_cog's record-type + raster-asset + storage-backend branches
    all flow through to the audit emit + storage read.
    """
    record = Record(
        title=f"Local COG Test {uuid.uuid4().hex[:6]}",
        summary="Dataset for KNOWN-01 anonymous-download regression",
        theme_category=["test"],
        visibility=visibility,
        record_status="published",
        record_type="raster_dataset",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=f"known01_cog_test_{uuid.uuid4().hex[:8]}",
        source_format="geotiff",
        source_filename="test.tif",
    )
    session.add(dataset)
    await session.flush()

    raster_asset = RasterAsset(
        dataset_id=dataset.id,
        asset_uri=f"rasters/{dataset.id}/abc123/source.cog.tif",
        storage_backend="local",
    )
    session.add(raster_asset)
    await session.flush()

    await session.commit()
    await session.refresh(dataset)
    await session.refresh(raster_asset)
    return record, dataset, raster_asset


class TestDownloadTokenConsumption:
    """End-to-end mint→consume tests pinning KNOWN-01 closure."""

    async def test_authenticated_mint_then_consume_returns_cog(
        self, client: AsyncClient, admin_auth_header, test_db_session
    ):
        """Admin mints a sub-bearing download token and consumes it on /download/cog.

        Auth-passed signal: status != 401 and != 403 (storage read may 503/200/302
        depending on backend — we don't care about that here).
        """
        result = await test_db_session.execute(
            select(User).where(User.username == settings.geolens_admin_username)
        )
        admin = result.scalar_one()
        _, dataset, _ = await _create_local_raster_dataset(
            test_db_session, created_by=admin.id, visibility="public"
        )

        # Mint authenticated download token (sub-bearing).
        mint_resp = await client.post(
            f"/auth/download-token/{dataset.id}", headers=admin_auth_header
        )
        assert mint_resp.status_code == 200, mint_resp.text
        token = mint_resp.json()["token"]

        # Sanity: token has sub claim.
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        assert payload.get("sub") == str(admin.id)

        # Consume — WITHOUT Authorization header (proves the ?token= path works).
        resp = await client.get(
            f"/datasets/{dataset.id}/download/cog?token={token}",
            follow_redirects=False,
        )
        assert resp.status_code not in (401, 403), (
            f"Authenticated mint→consume should not 401/403 — got {resp.status_code}: {resp.text}"
        )

    async def test_anonymous_mint_then_consume_returns_cog_for_public_dataset(
        self, client: AsyncClient, test_db_session
    ):
        """Anonymous mints a no-sub download token for PUBLIC raster → consumes it.

        This is the KNOWN-01 regression pin. Before Phase 1071 the consume side
        returned 401 because the sub claim was absent; after Phase 1071 it
        returns 200/302/503 (auth-passed).
        """
        result = await test_db_session.execute(
            select(User).where(User.username == settings.geolens_admin_username)
        )
        admin = result.scalar_one()
        _, dataset, _ = await _create_local_raster_dataset(
            test_db_session, created_by=admin.id, visibility="public"
        )

        # Mint anonymously (no auth header).
        mint_resp = await client.post(f"/auth/download-token/{dataset.id}")
        assert mint_resp.status_code == 200, mint_resp.text
        token = mint_resp.json()["token"]

        # Sanity: token has NO sub claim — this is the no-sub anonymous shape.
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        assert "sub" not in payload, (
            f"Anonymous mint should produce no-sub token, got payload: {payload}"
        )

        # Consume anonymously — this MUST not 401 (the KNOWN-01 bug).
        resp = await client.get(
            f"/datasets/{dataset.id}/download/cog?token={token}",
            follow_redirects=False,
        )
        assert resp.status_code != 401, (
            f"KNOWN-01 regression: anonymous no-sub token rejected with 401. "
            f"Body: {resp.text}"
        )
        assert resp.status_code != 403, (
            f"KNOWN-01 over-restriction: anonymous token on PUBLIC dataset got 403. "
            f"Body: {resp.text}"
        )

        # Audit assertion: anonymous download row was emitted with user_id=NULL.
        #
        # WR-03 (Phase 1071 review): session-visibility rationale.
        # test_db_session is created from the same async_session factory that
        # the test app client patches into the app (conftest.py:481). The route
        # handler calls await db.commit() before returning, which flushes the
        # audit row to the shared test database. Because test_db_session shares
        # the same engine (not the same connection/transaction), the committed
        # row is immediately visible to a subsequent query here — no expire_all()
        # or session refresh is needed. The assertion is stable as long as both
        # sessions reach the same physical Postgres instance.
        audit_rows = (
            await test_db_session.execute(
                select(AuditLog).where(
                    AuditLog.action == "dataset.download_cog",
                    AuditLog.resource_id == dataset.id,
                )
            )
        ).scalars().all()
        assert len(audit_rows) >= 1, "Expected dataset.download_cog audit row"
        anon_rows = [r for r in audit_rows if r.user_id is None]
        assert len(anon_rows) >= 1, (
            f"Expected at least one audit row with user_id=None for anonymous download, "
            f"got user_ids: {[r.user_id for r in audit_rows]}"
        )

    async def test_anonymous_mint_rejected_for_private_dataset(
        self, client: AsyncClient, test_db_session
    ):
        """Anonymous attempt to mint a download token for a PRIVATE dataset → 404.

        Documents the mint-side gate (check_dataset_access_or_anonymous returns 404
        for non-public datasets to anonymous callers). The consume-side
        public-visibility guard added in Phase 1071 is defense-in-depth on top
        of this mint-side gate.
        """
        result = await test_db_session.execute(
            select(User).where(User.username == settings.geolens_admin_username)
        )
        admin = result.scalar_one()
        _, dataset, _ = await _create_local_raster_dataset(
            test_db_session, created_by=admin.id, visibility="private"
        )

        mint_resp = await client.post(f"/auth/download-token/{dataset.id}")
        assert mint_resp.status_code == 404, (
            f"Anonymous mint on private dataset must 404 — got {mint_resp.status_code}: {mint_resp.text}"
        )

    async def test_consume_side_blocks_anonymous_token_against_private_dataset(
        self, client: AsyncClient, test_db_session
    ):
        """Defense-in-depth: forge a no-sub token bound to a PRIVATE dataset → 404.

        The mint endpoint refuses to mint for a private dataset anonymously
        (see above), but if a token escaped that gate (replay, attacker
        forgery with the JWT secret, etc.) the consume side's
        check_dataset_access_or_anonymous gate fires FIRST and returns 404
        (the project-wide "don't leak existence of private datasets to
        anonymous callers" convention). The download_cog `visibility !=
        "public"` 403 branch is the second layer of defense if
        check_dataset_access_or_anonymous ever loosens.

        Critically: status MUST NOT be 200/302 (would mean the token granted
        access to a private dataset) and MUST NOT be 401 (would re-introduce
        KNOWN-01's blanket-reject behavior).
        """
        result = await test_db_session.execute(
            select(User).where(User.username == settings.geolens_admin_username)
        )
        admin = result.scalar_one()
        _, dataset, _ = await _create_local_raster_dataset(
            test_db_session, created_by=admin.id, visibility="private"
        )

        # Forge a valid no-sub download token for the private dataset.
        now = datetime.now(UTC)
        forged = jwt.encode(
            {
                "typ": "download",
                "scope": f"dataset:{dataset.id}",
                "exp": now + timedelta(seconds=120),
                "iat": now,
            },
            settings.jwt_secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        )

        resp = await client.get(
            f"/datasets/{dataset.id}/download/cog?token={forged}",
            follow_redirects=False,
        )
        # 404 from check_dataset_access_or_anonymous (anonymous + private).
        assert resp.status_code == 404, (
            f"Forged anonymous token on private dataset must 404 — "
            f"got {resp.status_code}: {resp.text}"
        )
        # Positive-form regression pin: must NOT be 200/302 (over-grant),
        # 401 (KNOWN-01 over-restriction), or 403 (would reveal existence).
        assert resp.status_code not in (200, 302, 401, 403), (
            f"Anonymous-private must not over-grant or over-restrict — "
            f"got {resp.status_code}"
        )

    async def test_expired_anonymous_token_rejected(
        self, client: AsyncClient, test_db_session
    ):
        """An expired no-sub download token is rejected with 401 (exp check)."""
        result = await test_db_session.execute(
            select(User).where(User.username == settings.geolens_admin_username)
        )
        admin = result.scalar_one()
        _, dataset, _ = await _create_local_raster_dataset(
            test_db_session, created_by=admin.id, visibility="public"
        )

        # Forge an already-expired no-sub token for the public dataset.
        now = datetime.now(UTC)
        expired = jwt.encode(
            {
                "typ": "download",
                "scope": f"dataset:{dataset.id}",
                "exp": now - timedelta(seconds=10),
                "iat": now - timedelta(seconds=130),
            },
            settings.jwt_secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        )

        resp = await client.get(
            f"/datasets/{dataset.id}/download/cog?token={expired}",
            follow_redirects=False,
        )
        assert resp.status_code == 401, (
            f"Expired anonymous token must 401 — got {resp.status_code}: {resp.text}"
        )

    async def test_wrong_scope_anonymous_token_rejected(
        self, client: AsyncClient, test_db_session
    ):
        """A no-sub token minted for dataset A is rejected on dataset B's URL.

        Scope check at _resolve_download_user fires regardless of sub-presence.
        Pins the regression that the anonymous path didn't open a scope-evasion
        hole.
        """
        result = await test_db_session.execute(
            select(User).where(User.username == settings.geolens_admin_username)
        )
        admin = result.scalar_one()
        _, dataset_a, _ = await _create_local_raster_dataset(
            test_db_session, created_by=admin.id, visibility="public"
        )
        _, dataset_b, _ = await _create_local_raster_dataset(
            test_db_session, created_by=admin.id, visibility="public"
        )

        # Mint anonymously for dataset A.
        mint_resp = await client.post(f"/auth/download-token/{dataset_a.id}")
        assert mint_resp.status_code == 200, mint_resp.text
        token = mint_resp.json()["token"]

        # Consume against dataset B — scope mismatch → 401.
        resp = await client.get(
            f"/datasets/{dataset_b.id}/download/cog?token={token}",
            follow_redirects=False,
        )
        assert resp.status_code == 401, (
            f"Wrong-scope anonymous token must 401 — got {resp.status_code}: {resp.text}"
        )
        assert "scope" in resp.json()["detail"].lower()

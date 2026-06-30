"""Regression tests for Phase 1181 — Config-ops & settings correctness.

BUG-007: RequestBodyLimitMiddleware must honour admin-raised UPLOAD_MAX_SIZE_MB
         (resolved per-request from cached PersistentConfig, not boot-time env).
BUG-009: Invalid settings values must be rejected 400/422 BEFORE side effects.
BUG-010: config import must be atomic (all-or-nothing).
BUG-011: config import must gate restricted keys.

Each test is marked with the bug ID it exercises.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# BUG-007 — per-request body-limit resolution
# ---------------------------------------------------------------------------


class TestBug007BodyLimitDynamic:
    """RequestBodyLimitMiddleware must read UPLOAD_MAX_SIZE_MB from dynamic
    config on each request, not the boot-time env value."""

    @pytest.mark.anyio
    async def test_body_limit_honours_raised_config(self, client: AsyncClient):
        """If UPLOAD_MAX_SIZE_MB is raised in PersistentConfig at runtime,
        a body that was previously over-limit (old default) but under the new
        limit must be ACCEPTED (not 413).

        Pre-fix: middleware is pinned to boot-time setting — still 413.
        Post-fix: middleware reads cached config — 200/non-413.
        """
        # Patch UPLOAD_MAX_SIZE_MB.get so the middleware sees a raised limit.
        # Effective limit raised to 1000 MB → a 501 MB body should pass.
        high_limit_bytes = 1000 * 1024 * 1024

        # Import the middleware class to patch the resolved limit at the point
        # the middleware resolves it per-request.
        # The middleware must NOT use self.max_bytes (boot-time) for the limit;
        # instead it must call _get_effective_limit() or similar that reads from
        # PersistentConfig cache.  We verify this by checking that patching the
        # cached value changes the enforcement boundary.
        #
        # We send a fake Content-Length that is larger than the current default
        # but within the "raised" limit.  Under the boot-time implementation,
        # this request would return 413.  Under the fixed implementation it
        # passes through because the dynamic limit is higher.
        default_limit_bytes = 500 * 1024 * 1024  # 500 MB default
        over_default = default_limit_bytes + 1  # 1 byte over default

        # Simulate the middleware having loaded the raised limit from config.
        # We patch _get_upload_limit (the helper the fix will introduce) to
        # return the higher limit.
        with patch(
            "app.api.middleware.body_limit._get_upload_limit",
            return_value=high_limit_bytes,
        ):
            resp = await client.post(
                "/health",
                content=b"x",
                headers={"Content-Length": str(over_default)},
            )
        # Should NOT be 413 — the raised limit allows this size.
        assert resp.status_code != 413, (
            "BUG-007: body limit must honour the raised config value; "
            f"got {resp.status_code} instead of non-413"
        )

    @pytest.mark.anyio
    async def test_body_limit_still_blocks_over_new_limit(self, client: AsyncClient):
        """Even with a raised limit, a body over the NEW limit is still 413."""
        high_limit_bytes = 1000 * 1024 * 1024

        with patch(
            "app.api.middleware.body_limit._get_upload_limit",
            return_value=high_limit_bytes,
        ):
            resp = await client.post(
                "/health",
                content=b"x",
                headers={"Content-Length": str(high_limit_bytes + 1)},
            )
        assert resp.status_code == 413, (
            "BUG-007: body over the new (raised) limit must still be 413"
        )


# ---------------------------------------------------------------------------
# BUG-009 — validate-before-side-effects for settings PUT
# ---------------------------------------------------------------------------


class TestBug009ValidateBeforeSideEffects:
    """PUT /settings/ with an invalid value must return 400/422 without
    applying any side effect or storing the garbage value."""

    @pytest.mark.anyio
    async def test_invalid_log_level_rejected_no_500(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """An invalid log_level must return 400/422, not 500.

        Pre-fix: LOG_LEVEL._on_change fires before validation → 500 or
        garbage stored.
        Post-fix: validation gate before set() → clean 400/422.
        """
        resp = await client.put(
            "/settings/",
            json={"settings": {"log_level": "NOTALEVEL"}},
            headers=admin_auth_header,
        )
        assert resp.status_code in (400, 422), (
            f"BUG-009: invalid log_level must return 400/422, got {resp.status_code}"
        )

    @pytest.mark.anyio
    async def test_invalid_log_level_not_stored(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """After a rejected write, the setting is NOT stored/overridden."""
        # Attempt invalid write
        await client.put(
            "/settings/",
            json={"settings": {"log_level": "NOTALEVEL"}},
            headers=admin_auth_header,
        )
        # Fetch current settings — log_level source must not be 'overridden'
        # with an invalid value.
        resp = await client.get("/settings/all/", headers=admin_auth_header)
        assert resp.status_code == 200
        data = resp.json()
        general_tab = data["tabs"].get("general", [])
        ll_items = [i for i in general_tab if i["key"] == "log_level"]
        # The value must NOT be the garbage string we tried to write.
        if ll_items:
            assert ll_items[0]["value"] != "NOTALEVEL", (
                "BUG-009: invalid log_level was stored — must not persist garbage"
            )

    @pytest.mark.anyio
    async def test_invalid_integer_setting_rejected(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """An invalid (non-int) value for an integer setting must return 400/422."""
        resp = await client.put(
            "/settings/",
            json={"settings": {"login_rate_limit": "not_a_number"}},
            headers=admin_auth_header,
        )
        assert resp.status_code in (400, 422), (
            f"BUG-009: invalid integer setting must return 400/422, got {resp.status_code}"
        )

    @pytest.mark.anyio
    async def test_valid_setting_write_succeeds(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """Happy path: a valid settings write still returns 200."""
        resp = await client.put(
            "/settings/",
            json={"settings": {"ai_enabled": True}},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, (
            f"BUG-009 regression: valid settings write must return 200, got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# BUG-010 — atomic config import
# ---------------------------------------------------------------------------


class TestBug010AtomicImport:
    """import_config must be all-or-nothing: a validation failure on any key
    rolls back everything so zero keys are applied."""

    @pytest.mark.anyio
    async def test_partial_invalid_import_applies_nothing(self):
        """An import where one key is invalid leaves ZERO keys applied.

        Pre-fix: per-key commit loop applies valid keys then raises on
        invalid key → partial state.
        Post-fix: pre-validate all, then single commit → atomic.
        """
        from app.platform.config_ops.service import import_config
        from app.platform.config_ops.exceptions import ConfigValidationError

        # Build a session mock that tracks set() calls
        mock_db = AsyncMock(spec=AsyncSession)
        mock_db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=lambda: None)
        )
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()

        # Mixed payload: one valid key + one invalid key
        # login_rate_limit=5 is valid; login_rate_limit=999999 is invalid (>1000)
        data = {
            "settings": {
                "ai_enabled": True,  # valid bool
                "login_rate_limit": 99999,  # invalid — exceeds max allowed
            }
        }

        # We verify atomicity by checking that on validation failure the
        # function raises ConfigValidationError WITHOUT committing.
        with pytest.raises((ConfigValidationError, Exception)):
            await import_config(
                db=mock_db,
                data=data,
                mode="merge",
                user_id=uuid.uuid4(),
                ip_address=None,
            )

        # On failure, commit must NOT have been called (nothing was persisted)
        mock_db.commit.assert_not_called()

    @pytest.mark.anyio
    async def test_fully_valid_import_commits_once(self):
        """A fully valid import applies all keys and commits exactly once."""
        from app.platform.config_ops.service import import_config

        # We need a real DB session to properly test the full path.
        # Use a minimal mock that satisfies the ORM calls.
        mock_db = AsyncMock(spec=AsyncSession)

        # Make execute return an empty result (no existing rows)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()

        data = {
            "settings": {
                "ai_enabled": True,
            }
        }

        # Patch PersistentConfig.set to avoid actual DB writes
        with patch(
            "app.core.persistent_config.PersistentConfig.set",
            new_callable=AsyncMock,
        ):
            with patch(
                "app.core.persistent_config.PersistentConfig.reset",
                new_callable=AsyncMock,
            ):
                await import_config(
                    db=mock_db,
                    data=data,
                    mode="merge",
                    user_id=uuid.uuid4(),
                    ip_address=None,
                )

        # Commit should have been called (data was applied)
        assert mock_db.commit.call_count >= 1, (
            "BUG-010 regression: valid import must commit"
        )


# ---------------------------------------------------------------------------
# BUG-011 - runtime-gated config import
# ---------------------------------------------------------------------------


class TestBug011EditionGatedImport:
    """import_config must enforce the restricted tab gate, matching the
    normal settings PUT path."""

    @pytest.mark.anyio
    async def test_community_skips_enterprise_key_applies_allowed(
        self, community_edition
    ):
        """A caller without restricted access importing a restricted key
        (branding.show_badge) plus an allowed key (ai_enabled) must:
          - SKIP the restricted key (not write it), recorded in
            settings_skipped_restricted, while import still succeeds
          - APPLY the allowed key

        Pre-fix (hard 404): the whole import was rejected, breaking
        export/import round-trips.
        Post-fix (skip-not-reject): allowed keys apply, restricted keys skip.
        """
        from app.platform.config_ops.service import import_config

        mock_db = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()

        # branding.show_badge is on the restricted "branding" tab;
        # ai_enabled is on the "ai" tab, which is allowed.
        data = {
            "settings": {
                "branding.show_badge": False,
                "ai_enabled": True,
            }
        }

        # Spy on which keys are actually applied via cfg.set()
        applied_keys: list[str] = []

        async def spy_set(self, db, value, **kwargs):
            applied_keys.append(self.key)

        with patch(
            "app.core.persistent_config.PersistentConfig.set",
            new=spy_set,
        ):
            with patch(
                "app.core.persistent_config.PersistentConfig.reset",
                new_callable=AsyncMock,
            ):
                result = await import_config(
                    db=mock_db,
                    data=data,
                    mode="merge",
                    user_id=uuid.uuid4(),
                    ip_address=None,
                )

        # The restricted key must have been SKIPPED, not written.
        assert "branding.show_badge" not in applied_keys, (
            "BUG-011: caller without access must NOT write restricted key"
        )
        assert "branding.show_badge" in result.settings_skipped_restricted, (
            "BUG-011: skipped restricted key must be recorded in the result"
        )
        # The allowed key in the same import MUST have been applied.
        assert "ai_enabled" in applied_keys, (
            "BUG-011: allowed keys in the same import must still be applied"
        )
        assert result.settings_applied == 1, (
            "BUG-011: exactly one allowed key (ai_enabled) should be applied"
        )

    @pytest.mark.anyio
    async def test_community_overwrite_does_not_reset_enterprise_keys(
        self, community_edition
    ):
        """OVERWRITE-mode regression (Codex P2 on PR #248): a caller without
        restricted access importing in overwrite mode must NOT reset restricted keys.

        Overwrite mode resets every registered key not present in the import.
        Enterprise-only keys are skipped by the validation gate (never in
        ``validated``), so without an equivalent gate on the reset loop they
        would still be reset() — reverting enterprise branding/appearance to env
        defaults despite being reported as skipped.

        Pre-fix: branding.* (and every other restricted key) is reset.
        Post-fix: restricted keys are excluded from the reset loop, while
        allowed non-imported keys are still reset (overwrite semantics kept).
        """
        from app.core.persistent_config import _registry
        from app.modules.settings.router import _ENTERPRISE_ONLY_TABS
        from app.platform.config_ops.service import import_config

        mock_db = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()

        reset_keys: list[str] = []

        async def spy_reset(self, db, **kwargs):
            reset_keys.append(self.key)

        # Import only an allowed key; every other registered key is a reset
        # candidate in overwrite mode.
        data = {"settings": {"ai_enabled": True}}

        with patch(
            "app.core.persistent_config.PersistentConfig.set",
            new_callable=AsyncMock,
        ):
            with patch(
                "app.core.persistent_config.PersistentConfig.reset",
                new=spy_reset,
            ):
                await import_config(
                    db=mock_db,
                    data=data,
                    mode="overwrite",
                    user_id=uuid.uuid4(),
                    ip_address=None,
                )

        enterprise_keys = {c.key for c in _registry if c.tab in _ENTERPRISE_ONLY_TABS}
        assert enterprise_keys, "expected the registry to define restricted keys"
        leaked = enterprise_keys & set(reset_keys)
        assert not leaked, (
            "overwrite import must NOT reset restricted keys for callers without access; "
            f"reset: {sorted(leaked)}"
        )
        # Overwrite semantics preserved: at least one allowed, non-imported key
        # was still reset (guards against a vacuous pass).
        assert reset_keys, "overwrite mode should still reset allowed non-imported keys"

    @pytest.mark.anyio
    async def test_enterprise_can_import_enterprise_key(self, enterprise_edition):
        """An enterprise-edition caller importing a branding key must succeed."""
        from app.platform.config_ops.service import import_config

        mock_db = AsyncMock(spec=AsyncSession)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        mock_result.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()
        mock_db.rollback = AsyncMock()

        data = {
            "settings": {
                "branding.show_badge": False,
            }
        }

        with patch(
            "app.core.persistent_config.PersistentConfig.set",
            new_callable=AsyncMock,
        ):
            with patch(
                "app.core.persistent_config.PersistentConfig.reset",
                new_callable=AsyncMock,
            ):
                # Should NOT raise for enterprise edition
                await import_config(
                    db=mock_db,
                    data=data,
                    mode="merge",
                    user_id=uuid.uuid4(),
                    ip_address=None,
                )

    @pytest.mark.anyio
    async def test_community_import_leaves_enterprise_value_unchanged(
        self, client: AsyncClient, admin_auth_header: dict
    ):
        """End-to-end: an import that attempts to flip a restricted key
        (branding.show_badge) must leave that key's stored
        value UNCHANGED (skipped), while still applying allowed keys.

        Default test edition is community (no GEOLENS_EDITION env).
        """
        from app.core.persistent_config import BRANDING_SHOW_BADGE

        # Record the current stored value of the restricted key.
        from app.core.dependencies import get_db

        # Read via the public export endpoint is simplest, but branding is an
        # restricted tab and may be hidden in /settings/all. Instead, attempt
        # the import and confirm settings_skipped_restricted lists it.
        import_resp = await client.post(
            "/config-ops/import/?mode=merge",
            json={
                "settings": {
                    "branding.show_badge": False,  # attempt to flip (default True)
                    "ai_enabled": True,  # allowed key
                }
            },
            headers=admin_auth_header,
        )
        assert import_resp.status_code == 200, (
            f"BUG-011: community import must succeed (skip-not-reject); "
            f"got {import_resp.status_code}: {import_resp.json()}"
        )
        result = import_resp.json()
        # The restricted key must be recorded as skipped.
        assert "branding.show_badge" in result.get("settings_skipped_restricted", []), (
            "BUG-011: restricted key must be reported as skipped, not applied"
        )
        # The allowed key must have been applied.
        assert result["settings_applied"] >= 1

        # Confirm the restricted key's stored value is UNCHANGED (no DB row
        # was written for it, so it resolves to its env_default of True).
        async for db in get_db():
            stored = await BRANDING_SHOW_BADGE.get(db)
            break
        assert stored == BRANDING_SHOW_BADGE.env_default, (
            "BUG-011: import must NOT change the restricted key's stored value"
        )

"""fix(#1778): an over-long password is a refusal, never a 500 or a crash-loop.

Codebase audit 2026-08-30, "A password over 72 bytes 500s /auth/login and skips
the login-failure audit row; the same input crash-loops first boot".

bcrypt refuses an input longer than 72 bytes and pwdlib's BcryptHasher raises
ValueError rather than truncating. Register, change-password, admin create and
admin reset all run validate_password_complexity, which caps the value, but
three paths reached the hasher with an unvalidated string:

  - POST /auth/login          - OAuth2PasswordRequestForm applies no bound.
  - POST /auth/change-password/ - ``current_password`` is capped at 256
    CHARACTERS; only ``new_password`` carries the byte bound.
  - seed_initial_admin()      - hashes GEOLENS_ADMIN_PASSWORD at first boot.

Counterfactual for the two request paths: revert the byte check in
verify_password (app/modules/auth/providers/local.py) and both tests below fail
with a raised ValueError instead of the asserted status code. Counterfactual for
the boot path: drop the byte check from validate_admin_credentials_nonempty and
the Settings construction succeeds instead of raising.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import (
    BCRYPT_MAX_PASSWORD_BYTES as CONFIG_BCRYPT_MAX_PASSWORD_BYTES,
)
from app.modules.auth.password_policy import BCRYPT_MAX_PASSWORD_BYTES
from app.modules.auth.providers.local import DUMMY_HASH, verify_password

pytestmark = pytest.mark.anyio

STRONG_PASSWORD = "TestPass1234!"

# 73 bytes: one past what bcrypt will hash. Not a credential for anything --
# no account is ever created with it, because no entry point accepts it.
OVERSIZED_PASSWORD = "A1!" + ("a" * 70)


def test_oversized_fixture_is_one_byte_past_the_limit() -> None:
    """Positive control: the fixture really does cross the bound."""
    assert len(OVERSIZED_PASSWORD.encode("utf-8")) == BCRYPT_MAX_PASSWORD_BYTES + 1


def test_config_restates_the_same_bcrypt_bound() -> None:
    """core/config.py cannot import from app.modules.*, so it restates the
    constant. Pin the two together so they cannot drift."""
    assert CONFIG_BCRYPT_MAX_PASSWORD_BYTES == BCRYPT_MAX_PASSWORD_BYTES


class TestVerifyPasswordBound:
    def test_oversized_input_is_a_non_match_not_an_exception(self) -> None:
        assert verify_password(OVERSIZED_PASSWORD, DUMMY_HASH) is False

    def test_exactly_at_the_limit_still_reaches_the_hasher(self) -> None:
        """72 bytes is hashable, so the guard must not shorten the accepted range."""
        at_limit = "A1!" + ("a" * 69)
        assert len(at_limit.encode("utf-8")) == BCRYPT_MAX_PASSWORD_BYTES
        assert verify_password(at_limit, DUMMY_HASH) is False

    def test_multibyte_value_is_measured_in_bytes(self) -> None:
        """Short in characters, over the bound in UTF-8 bytes."""
        multibyte = "Ab1!" + ("é" * 40)  # 4 + 80 bytes
        assert len(multibyte) < BCRYPT_MAX_PASSWORD_BYTES
        assert len(multibyte.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES
        assert verify_password(multibyte, DUMMY_HASH) is False


class TestLoginWithOversizedPassword:
    """POST /auth/login must answer 401 and audit the attempt."""

    async def _create_user(self, client: AsyncClient, admin_headers: dict) -> str:
        username = f"oversized_{uuid.uuid4().hex[:8]}"
        resp = await client.post(
            "/admin/users/",
            json={
                "username": username,
                "password": STRONG_PASSWORD,
                "role": "viewer",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 201, resp.text
        return username

    async def test_existing_account_gets_401_not_500(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        username = await self._create_user(client, admin_auth_header)
        resp = await client.post(
            "/auth/login",
            data={"username": username, "password": OVERSIZED_PASSWORD},
        )
        assert resp.status_code == 401, resp.text

    async def test_unknown_account_gets_401_not_500(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/auth/login",
            data={
                "username": f"nobody_{uuid.uuid4().hex[:8]}",
                "password": OVERSIZED_PASSWORD,
            },
        )
        assert resp.status_code == 401, resp.text

    async def test_failure_is_audited(
        self, client: AsyncClient, admin_auth_header: dict, test_db_session
    ) -> None:
        """#1230's user.login.failure row is the operator's only view of an
        attempt against an account; the ValueError skipped it entirely."""
        from app.modules.audit.models import AuditLog

        username = await self._create_user(client, admin_auth_header)
        resp = await client.post(
            "/auth/login",
            data={"username": username, "password": OVERSIZED_PASSWORD},
        )
        assert resp.status_code == 401, resp.text

        rows = (
            (
                await test_db_session.execute(
                    select(AuditLog).where(AuditLog.action == "user.login.failure")
                )
            )
            .scalars()
            .all()
        )
        matching = [r for r in rows if (r.details or {}).get("username") == username]
        assert matching, "no user.login.failure audit row for the refused login"
        assert matching[0].details.get("reason") == "invalid_credentials"


class TestChangePasswordWithOversizedCurrentPassword:
    async def test_oversized_current_password_gets_400_not_500(
        self, client: AsyncClient, admin_auth_header: dict
    ) -> None:
        username = f"cpwlong_{uuid.uuid4().hex[:8]}"
        created = await client.post(
            "/admin/users/",
            json={
                "username": username,
                "password": STRONG_PASSWORD,
                "role": "viewer",
            },
            headers=admin_auth_header,
        )
        assert created.status_code == 201, created.text
        login = await client.post(
            "/auth/login",
            data={"username": username, "password": STRONG_PASSWORD},
        )
        assert login.status_code == 200, login.text
        access = login.json()["access_token"]

        resp = await client.post(
            "/auth/change-password/",
            json={
                "current_password": OVERSIZED_PASSWORD,
                "new_password": "AnotherPass99!",
            },
            headers={"Authorization": f"Bearer {access}"},
        )
        assert resp.status_code == 400, resp.text


class TestAdminPasswordBootGuard:
    """An over-long GEOLENS_ADMIN_PASSWORD must be refused at boot, by name."""

    def _settings(self, monkeypatch, value: str):
        from app.core.config import Settings

        monkeypatch.setenv("GEOLENS_ADMIN_PASSWORD", value)
        return Settings()

    def test_oversized_admin_password_refuses_boot(self, monkeypatch) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc:
            self._settings(monkeypatch, OVERSIZED_PASSWORD)
        assert "GEOLENS_ADMIN_PASSWORD" in str(exc.value)
        assert str(BCRYPT_MAX_PASSWORD_BYTES) in str(exc.value)

    def test_admin_password_at_the_limit_boots(self, monkeypatch) -> None:
        at_limit = "A1!" + ("a" * 69)
        assert len(at_limit.encode("utf-8")) == BCRYPT_MAX_PASSWORD_BYTES
        loaded = self._settings(monkeypatch, at_limit)
        assert loaded.geolens_admin_password.get_secret_value() == at_limit

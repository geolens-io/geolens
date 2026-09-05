"""SECRET_ENCRYPTION_KEY decouples stored-secret encryption from JWT_SECRET_KEY.

Before #1871, `OAuthProvider.client_secret_encrypted` and
`OAuthProvider.idp_certificate` were encrypted under one key derived from
`JWT_SECRET_KEY`, so rotating the JWT secret (the documented response to a
token leak) made every stored SSO secret undecryptable.

Every key in this module is generated inside the test. Nothing here reads the
real `.env`, and no key material is printed.
"""

import pathlib
import subprocess
import uuid

import pytest
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from pydantic import SecretStr, ValidationError

from app.core.config import (
    KNOWN_BAD_ADMIN_PASSWORD,
    KNOWN_BAD_JWT_SECRET,
    KNOWN_BAD_POSTGRES_PASSWORD,
    Settings,
)
from app.modules.auth.oauth.encryption import (
    _get_fernet,
    decrypt_secret,
    encrypt_secret,
)

# Mirrors tests/test_config.py's BASE_ENV: every required field as a kwarg, so
# Settings never falls back to the host's .env file.
BASE_ENV = {
    "postgres_password": "testpass",
    "jwt_secret_key": "testsecret-padding-to-32-chars-min",
    "geolens_admin_username": "admin",
    "geolens_admin_password": "adminpass",
    "aws_role_arn": None,
    "aws_web_identity_token_file": None,
    "aws_container_credentials_full_uri": None,
    "aws_container_credentials_relative_uri": None,
}


def _make_settings(**overrides) -> Settings:
    return Settings(**{**BASE_ENV, **overrides})


def _new_key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def secret_settings(monkeypatch):
    """The process-global settings singleton, with both new keys cleared.

    Attribute-level monkeypatching (not a rebind), so the conftest restore of
    the singleton object is unaffected and every attribute reverts on teardown.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "secret_encryption_key", None)
    monkeypatch.setattr(settings, "secret_encryption_key_previous", None)
    return settings


class TestKeyChain:
    def test_round_trips_with_no_dedicated_key(self, secret_settings):
        assert decrypt_secret(encrypt_secret("provider-secret")) == "provider-secret"

    def test_legacy_ciphertext_still_reads_after_a_dedicated_key_is_set(
        self, monkeypatch, secret_settings
    ):
        """The migration case: rows written before the key was configured."""
        legacy_ciphertext = encrypt_secret("written-under-the-jwt-key")

        monkeypatch.setattr(
            secret_settings, "secret_encryption_key", SecretStr(_new_key())
        )

        assert decrypt_secret(legacy_ciphertext) == "written-under-the-jwt-key"

    def test_writes_after_the_dedicated_key_do_not_read_under_the_legacy_key(
        self, monkeypatch, secret_settings
    ):
        monkeypatch.setattr(
            secret_settings, "secret_encryption_key", SecretStr(_new_key())
        )
        ciphertext = encrypt_secret("written-under-the-dedicated-key")

        monkeypatch.setattr(secret_settings, "secret_encryption_key", None)
        with pytest.raises(InvalidToken):
            decrypt_secret(ciphertext)

    def test_jwt_rotation_no_longer_destroys_a_stored_secret(
        self, monkeypatch, secret_settings
    ):
        """The headline scenario this issue exists for."""
        monkeypatch.setattr(
            secret_settings, "secret_encryption_key", SecretStr(_new_key())
        )
        ciphertext = encrypt_secret("survives-a-jwt-rotation")

        monkeypatch.setattr(
            secret_settings,
            "jwt_secret_key",
            SecretStr("a-completely-different-jwt-secret-value"),
        )

        assert decrypt_secret(ciphertext) == "survives-a-jwt-rotation"

    def test_jwt_rotation_without_a_dedicated_key_destroys_it(
        self, monkeypatch, secret_settings
    ):
        """The counterfactual: the behaviour the new setting exists to avoid."""
        ciphertext = encrypt_secret("lost-on-a-jwt-rotation")

        monkeypatch.setattr(
            secret_settings,
            "jwt_secret_key",
            SecretStr("a-completely-different-jwt-secret-value"),
        )

        with pytest.raises(InvalidToken):
            decrypt_secret(ciphertext)

    def test_previous_key_stays_readable_while_the_new_one_writes(
        self, monkeypatch, secret_settings
    ):
        retiring, incoming = _new_key(), _new_key()

        monkeypatch.setattr(
            secret_settings, "secret_encryption_key", SecretStr(retiring)
        )
        old_ciphertext = encrypt_secret("written-under-the-retiring-key")

        monkeypatch.setattr(
            secret_settings, "secret_encryption_key", SecretStr(incoming)
        )
        monkeypatch.setattr(
            secret_settings, "secret_encryption_key_previous", SecretStr(retiring)
        )

        assert decrypt_secret(old_ciphertext) == "written-under-the-retiring-key"
        # New writes go to the incoming key, not the one being retired.
        new_ciphertext = encrypt_secret("written-under-the-incoming-key")
        assert (
            MultiFernet([Fernet(incoming)]).decrypt(new_ciphertext.encode()).decode()
            == "written-under-the-incoming-key"
        )
        with pytest.raises(InvalidToken):
            MultiFernet([Fernet(retiring)]).decrypt(new_ciphertext.encode())

    def test_chain_order_is_dedicated_then_previous_then_legacy(
        self, monkeypatch, secret_settings
    ):
        monkeypatch.setattr(
            secret_settings, "secret_encryption_key", SecretStr(_new_key())
        )
        monkeypatch.setattr(
            secret_settings, "secret_encryption_key_previous", SecretStr(_new_key())
        )

        chain = _get_fernet()
        assert len(chain._fernets) == 3


class TestBootGuard:
    def test_accepts_a_well_formed_key(self):
        settings = _make_settings(secret_encryption_key=_new_key())
        assert settings.secret_encryption_key is not None

    def test_blank_value_means_unset(self):
        """A verbatim-template .env line reaches the app as "" (INST-01 class)."""
        settings = _make_settings(
            secret_encryption_key="", secret_encryption_key_previous="   "
        )
        assert settings.secret_encryption_key is None
        assert settings.secret_encryption_key_previous is None

    @pytest.mark.parametrize(
        "literal",
        [
            KNOWN_BAD_JWT_SECRET,
            KNOWN_BAD_ADMIN_PASSWORD,
            KNOWN_BAD_POSTGRES_PASSWORD,
            "dev-only-change-me-in-production",
        ],
    )
    def test_refuses_a_known_public_literal(self, literal):
        with pytest.raises(ValidationError, match="known-public literal"):
            _make_settings(secret_encryption_key=literal)

    def test_refuses_the_jwt_secret_itself(self):
        shared = _new_key()
        with pytest.raises(ValidationError, match="same value as JWT_SECRET_KEY"):
            _make_settings(jwt_secret_key=shared, secret_encryption_key=shared)

    # fix(#1882): fixed values with explicit ids. A key generated here would be
    # generated once per xdist worker, and pytest-xdist aborts the run when two
    # workers collect different test ids.
    @pytest.mark.parametrize(
        "malformed",
        [
            "0" * 64,
            "not a key at all",
            "A" * 43,
        ],
        ids=["hex_decodes_to_48_bytes", "not_base64", "unpadded_43_chars"],
    )
    def test_refuses_a_malformed_key(self, malformed):
        with pytest.raises(ValidationError, match="not a valid Fernet key"):
            _make_settings(secret_encryption_key=malformed)

    def test_refuses_a_malformed_previous_key(self):
        with pytest.raises(
            ValidationError, match="SECRET_ENCRYPTION_KEY_PREVIOUS is not a valid"
        ):
            _make_settings(
                secret_encryption_key=_new_key(),
                secret_encryption_key_previous="not-a-key",
            )

    def test_refuses_a_previous_key_equal_to_the_current_one(self):
        """fix(#1882 audit): the chain would hold one key twice."""
        shared = _new_key()
        with pytest.raises(ValidationError, match="nothing is being rotated"):
            _make_settings(
                secret_encryption_key=shared, secret_encryption_key_previous=shared
            )

    def test_refuses_a_previous_key_on_its_own(self):
        with pytest.raises(ValidationError, match="without SECRET_ENCRYPTION_KEY"):
            _make_settings(secret_encryption_key_previous=_new_key())

    def test_error_message_never_carries_the_key(self):
        key = _new_key()
        with pytest.raises(ValidationError) as excinfo:
            _make_settings(jwt_secret_key=key, secret_encryption_key=key)
        assert key not in str(excinfo.value)


class TestDeploymentWiring:
    """A setting no template passes reaches no container, and nothing says so."""

    @staticmethod
    def _repo_root():
        for candidate in pathlib.Path(__file__).resolve().parents:
            if (candidate / "docker-compose.yml").is_file():
                return candidate
        # A backend-only container layout ships no compose files to drift.
        pytest.skip("docker-compose.yml not found above this test file")

    @pytest.mark.parametrize(
        "compose_file", ["docker-compose.yml", "docker-compose.prod.yml"]
    )
    @pytest.mark.parametrize(
        "variable", ["SECRET_ENCRYPTION_KEY", "SECRET_ENCRYPTION_KEY_PREVIOUS"]
    )
    def test_both_compose_files_pass_the_keys_through(self, compose_file, variable):
        text = (self._repo_root() / compose_file).read_text()
        assert f'{variable}: "${{{variable}:-}}"' in text, (
            f"{compose_file} never passes {variable} to the api and worker "
            "containers, so setting it in .env would silently do nothing"
        )

    @pytest.mark.parametrize(
        "variable", ["SECRET_ENCRYPTION_KEY", "SECRET_ENCRYPTION_KEY_PREVIOUS"]
    )
    def test_env_example_documents_the_keys_commented_out(self, variable):
        text = (self._repo_root() / ".env.example").read_text()
        # Commented, not blank: an uncommented empty line is a shape an
        # operator may then fill in wrongly, and it is what compose reads.
        assert f"\n# {variable}=\n" in text

    def test_install_script_generates_a_key_the_app_accepts(self):
        """The installer's generator must emit a key Fernet takes.

        Runs the one function, cut out of the file by text. Sourcing
        `install.sh` would run the installer.
        """
        source = (self._repo_root() / "scripts" / "install.sh").read_text()
        start = source.index("generate_fernet_key() {")
        snippet = source[start : source.index("\n}\n", start) + 3]
        generated = subprocess.run(
            ["sh", "-c", snippet + "\ngenerate_fernet_key\n"],
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip()
        if not generated:
            pytest.skip("host has neither openssl nor base64")
        Fernet(generated)  # raises ValueError on a malformed key


@pytest.fixture
async def empty_oauth_providers(test_db_session):
    """Start and end with no provider rows.

    The rotation script sweeps the whole table by design, so a row another test
    left behind under a key that test then discarded would fail this one.
    """
    from sqlalchemy import text

    async def _clear():
        try:
            await test_db_session.execute(text("DELETE FROM catalog.oauth_providers"))
            await test_db_session.commit()
        except Exception:
            await test_db_session.rollback()

    await _clear()
    yield
    await _clear()


class TestRotationScript:
    """`scripts/rotate_secrets.py` moves stored rows onto the newest key."""

    async def _seed_provider(self, db, *, with_certificate: bool = False):
        from app.modules.auth.oauth.models import OAuthProvider

        suffix = uuid.uuid4().hex[:8]
        provider = OAuthProvider(
            slug=f"rotate-{suffix}",
            display_name=f"Rotate {suffix}",
            provider_type="oidc",
            client_id=f"client-{suffix}",
            client_secret_encrypted=encrypt_secret(f"client-secret-{suffix}"),
            idp_certificate=(
                encrypt_secret(f"certificate-{suffix}") if with_certificate else None
            ),
            scopes="openid profile email",
            default_role="viewer",
            enabled=True,
        )
        db.add(provider)
        await db.flush()
        await db.commit()
        return provider.id, f"client-secret-{suffix}", f"certificate-{suffix}"

    async def test_rotation_moves_every_row_onto_the_dedicated_key(
        self, monkeypatch, test_db_session, secret_settings, empty_oauth_providers
    ):
        from sqlalchemy import text

        from scripts.rotate_secrets import rotate_oauth_provider_secrets

        # Written under the JWT-derived key, as every pre-#1871 row was.
        provider_id, plaintext, certificate = await self._seed_provider(
            test_db_session, with_certificate=True
        )

        dedicated = _new_key()
        monkeypatch.setattr(
            secret_settings, "secret_encryption_key", SecretStr(dedicated)
        )

        rewritten = await rotate_oauth_provider_secrets(test_db_session)
        assert rewritten >= 1

        row = (
            await test_db_session.execute(
                text(
                    "SELECT client_secret_encrypted, idp_certificate "
                    "FROM catalog.oauth_providers WHERE id = :id"
                ),
                {"id": provider_id},
            )
        ).one()

        dedicated_only = MultiFernet([Fernet(dedicated)])
        assert dedicated_only.decrypt(row[0].encode()).decode() == plaintext
        assert dedicated_only.decrypt(row[1].encode()).decode() == certificate

    async def test_rotation_is_idempotent(
        self, monkeypatch, test_db_session, secret_settings, empty_oauth_providers
    ):
        from sqlalchemy import text

        from scripts.rotate_secrets import rotate_oauth_provider_secrets

        provider_id, plaintext, _ = await self._seed_provider(test_db_session)
        dedicated = _new_key()
        monkeypatch.setattr(
            secret_settings, "secret_encryption_key", SecretStr(dedicated)
        )

        await rotate_oauth_provider_secrets(test_db_session)
        await rotate_oauth_provider_secrets(test_db_session)

        row = (
            await test_db_session.execute(
                text(
                    "SELECT client_secret_encrypted FROM catalog.oauth_providers "
                    "WHERE id = :id"
                ),
                {"id": provider_id},
            )
        ).one()
        assert (
            MultiFernet([Fernet(dedicated)]).decrypt(row[0].encode()).decode()
            == plaintext
        )

    async def test_an_undecryptable_row_aborts_and_writes_nothing(
        self, monkeypatch, test_db_session, secret_settings, empty_oauth_providers
    ):
        from sqlalchemy import text

        from scripts.rotate_secrets import (
            UndecryptableRowsError,
            rotate_oauth_provider_secrets,
        )

        readable_id, plaintext, _ = await self._seed_provider(test_db_session)

        # A row written under a key this deployment no longer has.
        stranded = MultiFernet([Fernet(_new_key())]).encrypt(b"unreachable").decode()
        await self._seed_provider(test_db_session)
        await test_db_session.execute(
            text(
                "UPDATE catalog.oauth_providers SET client_secret_encrypted = :c "
                "WHERE id != :keep"
            ),
            {"c": stranded, "keep": readable_id},
        )
        await test_db_session.commit()

        before = (
            await test_db_session.execute(
                text(
                    "SELECT client_secret_encrypted FROM catalog.oauth_providers "
                    "WHERE id = :id"
                ),
                {"id": readable_id},
            )
        ).scalar_one()

        monkeypatch.setattr(
            secret_settings, "secret_encryption_key", SecretStr(_new_key())
        )
        with pytest.raises(UndecryptableRowsError):
            await rotate_oauth_provider_secrets(test_db_session)
        await test_db_session.rollback()

        after = (
            await test_db_session.execute(
                text(
                    "SELECT client_secret_encrypted FROM catalog.oauth_providers "
                    "WHERE id = :id"
                ),
                {"id": readable_id},
            )
        ).scalar_one()
        assert after == before
        assert decrypt_secret(after) == plaintext

    async def test_a_provider_saved_mid_sweep_is_not_overwritten(
        self, monkeypatch, test_db_session, secret_settings, empty_oauth_providers
    ):
        """fix(#1882 codex r1): rotation serialises with provider writers.

        The concurrent write is fired after the locking SELECT and before the
        first UPDATE, which is the window that used to lose it.
        """
        from sqlalchemy import text

        import app.core.db as db_module
        from scripts.rotate_secrets import rotate_oauth_provider_secrets

        provider_id, plaintext, _ = await self._seed_provider(test_db_session)
        dedicated = _new_key()
        monkeypatch.setattr(
            secret_settings, "secret_encryption_key", SecretStr(dedicated)
        )

        outcome: list[str] = []

        async def _save_from_another_session() -> None:
            """What an admin save or a config import does to the same row."""
            async with db_module.async_session() as other:
                try:
                    await other.execute(text("SET LOCAL lock_timeout = '750ms'"))
                    await other.execute(
                        text(
                            "UPDATE catalog.oauth_providers "
                            "SET client_secret_encrypted = :secret WHERE id = :id"
                        ),
                        {
                            "secret": encrypt_secret("entered-during-the-rotation"),
                            "id": provider_id,
                        },
                    )
                    await other.commit()
                    outcome.append("wrote")
                except Exception:
                    await other.rollback()
                    outcome.append("blocked")

        original_execute = test_db_session.execute
        statements: list[int] = []

        async def _execute_then_contend(statement, *args, **kwargs):
            result = await original_execute(statement, *args, **kwargs)
            statements.append(1)
            if len(statements) == 1:
                await _save_from_another_session()
            return result

        monkeypatch.setattr(test_db_session, "execute", _execute_then_contend)
        await rotate_oauth_provider_secrets(test_db_session)
        monkeypatch.undo()

        assert outcome == ["blocked"], (
            "the concurrent save landed inside the rotation's read-to-write "
            "window, so the rotation's own UPDATE reverted it"
        )

        stored = (
            await test_db_session.execute(
                text(
                    "SELECT client_secret_encrypted FROM catalog.oauth_providers "
                    "WHERE id = :id"
                ),
                {"id": provider_id},
            )
        ).scalar_one()
        assert (
            MultiFernet([Fernet(dedicated)]).decrypt(stored.encode()).decode()
            == plaintext
        )

        # The blocked writer is only blocked. Retried after the sweep it lands,
        # and nothing reverts it.
        await _save_from_another_session()
        assert outcome == ["blocked", "wrote"]
        await test_db_session.commit()
        stored = (
            await test_db_session.execute(
                text(
                    "SELECT client_secret_encrypted FROM catalog.oauth_providers "
                    "WHERE id = :id"
                ),
                {"id": provider_id},
            )
        ).scalar_one()
        assert decrypt_secret(stored) == "entered-during-the-rotation"

    async def test_dry_run_writes_nothing(
        self, monkeypatch, test_db_session, secret_settings, empty_oauth_providers
    ):
        from sqlalchemy import text

        from scripts.rotate_secrets import rotate_oauth_provider_secrets

        provider_id, _, _ = await self._seed_provider(test_db_session)
        before = (
            await test_db_session.execute(
                text(
                    "SELECT client_secret_encrypted FROM catalog.oauth_providers "
                    "WHERE id = :id"
                ),
                {"id": provider_id},
            )
        ).scalar_one()

        monkeypatch.setattr(
            secret_settings, "secret_encryption_key", SecretStr(_new_key())
        )
        assert await rotate_oauth_provider_secrets(test_db_session, dry_run=True) >= 1

        after = (
            await test_db_session.execute(
                text(
                    "SELECT client_secret_encrypted FROM catalog.oauth_providers "
                    "WHERE id = :id"
                ),
                {"id": provider_id},
            )
        ).scalar_one()
        assert after == before

    async def test_a_failed_write_does_not_print_the_ciphertext(
        self, test_db_session, secret_settings, empty_oauth_providers
    ):
        """fix(#1882 audit): the sweep's engine sets hide_parameters.

        A StatementError renders its bound parameters into the message, and
        the API's DB error handler logs that message. Bound here is the new
        key's ciphertext.
        """
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError
        from sqlalchemy.ext.asyncio import async_sessionmaker

        import app.core.db as db_module
        from scripts.rotate_secrets import make_engine

        provider_id, _, _ = await self._seed_provider(test_db_session)
        ciphertext = encrypt_secret("a-secret-that-must-not-be-logged")

        engine = make_engine(db_module.engine.url.render_as_string(hide_password=False))
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                with pytest.raises(DBAPIError) as excinfo:
                    # provider_type has a CHECK constraint, so this fails with
                    # the ciphertext already bound.
                    await session.execute(
                        text(
                            "UPDATE catalog.oauth_providers "
                            "SET client_secret_encrypted = :secret, "
                            "provider_type = 'not-a-provider-type' WHERE id = :id"
                        ),
                        {"secret": ciphertext, "id": provider_id},
                    )
                await session.rollback()
        finally:
            await engine.dispose()

        rendered = str(excinfo.value)
        assert ciphertext not in rendered
        assert "hidden due to hide_parameters" in rendered

    def test_refuses_to_run_without_a_dedicated_key(self, monkeypatch):
        """Otherwise the "rotation" rewrites every row under the JWT-derived key."""
        from app.core.config import settings
        from scripts.rotate_secrets import main

        monkeypatch.setattr(settings, "secret_encryption_key", None)
        assert main([]) == 2

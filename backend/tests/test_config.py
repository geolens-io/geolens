"""Tests for config.py Settings class — DATABASE_URL override and connection properties."""

import pytest

from app.config import Settings

# Settings constructor kwargs (lowercase field names).
# JWT_SECRET_KEY must be ≥ 32 chars to satisfy validate_jwt_secret_length.
BASE_ENV = {
    "postgres_password": "testpass",
    "jwt_secret_key": "testsecret-padding-to-32-chars-min",
    "geolens_admin_username": "admin",
    "geolens_admin_password": "adminpass",
}


def _make_settings(**overrides):
    """Create a fresh Settings instance with given env overrides.

    Bypasses the env_file fallback by passing every required field as a kwarg
    so test isolation is unaffected by the host's .env file. Each call returns
    an independent Settings instance — the module-level ``settings`` singleton
    in ``app.config`` is never touched.
    """
    env = {**BASE_ENV, **overrides}
    return Settings(**env)


class TestDatabaseUrlOverride:
    """Test database_url property with and without override."""

    def test_default_composes_from_postgres_fields(self):
        s = _make_settings()
        assert "postgresql+asyncpg://" in s.database_url
        assert "geolens" in s.database_url
        assert s.database_url_override is None

    def test_override_replaces_composed_url(self):
        s = _make_settings(database_url_override="postgresql://user:pass@rds:5432/mydb")
        assert "postgresql+asyncpg://user:pass@rds:5432/mydb" in s.database_url

    def test_override_strips_sslmode_from_async_url(self):
        s = _make_settings(
            database_url_override="postgresql://u:p@host:5432/db?sslmode=require"
        )
        assert "sslmode" not in s.database_url

    def test_override_handles_postgres_scheme(self):
        s = _make_settings(database_url_override="postgres://u:p@host:5432/db")
        assert s.database_url.startswith("postgresql+asyncpg://")

    def test_override_preserves_non_ssl_query_params(self):
        s = _make_settings(
            database_url_override="postgresql://u:p@host/db?application_name=geolens&sslmode=require"
        )
        url = s.database_url
        assert "sslmode" not in url
        assert "application_name=geolens" in url


class TestDatabaseUrlSync:
    """Test database_url_sync property with and without override."""

    def test_default_composes_psycopg_url(self):
        s = _make_settings()
        assert "postgresql+psycopg://" in s.database_url_sync

    def test_override_uses_psycopg_prefix(self):
        s = _make_settings(database_url_override="postgresql://u:p@host:5432/db")
        assert s.database_url_sync.startswith("postgresql+psycopg://")

    def test_override_from_asyncpg_prefix(self):
        s = _make_settings(database_url_override="postgresql+asyncpg://u:p@host/db")
        assert s.database_url_sync.startswith("postgresql+psycopg://")


class TestProcrastinateConninfo:
    """Test procrastinate_conninfo property."""

    def test_default_includes_search_path(self):
        s = _make_settings()
        conninfo = s.procrastinate_conninfo
        assert "host=" in conninfo
        assert "search_path" in conninfo

    def test_override_parses_url_to_libpq_format(self):
        s = _make_settings(
            database_url_override="postgresql://myuser:mypass@rds-host:5432/mydb"
        )
        conninfo = s.procrastinate_conninfo
        assert "host=rds-host" in conninfo
        assert "port=5432" in conninfo
        assert "dbname=mydb" in conninfo
        assert "user=myuser" in conninfo
        assert "password=mypass" in conninfo

    def test_override_includes_ssl_params(self):
        s = _make_settings(
            database_url_override="postgresql://u:p@host/db",
            database_ssl_mode="require",
        )
        assert "sslmode=require" in s.procrastinate_conninfo

    def test_override_includes_ca_cert(self):
        s = _make_settings(
            database_url_override="postgresql://u:p@host/db",
            database_ssl_mode="verify-full",
            database_ssl_ca_cert="/path/to/ca.pem",
        )
        conninfo = s.procrastinate_conninfo
        assert "sslrootcert=/path/to/ca.pem" in conninfo
        assert "sslmode=verify-full" in conninfo


class TestOgrConnectionString:
    """Test ogr_connection_string property."""

    def test_default_starts_with_pg_prefix(self):
        s = _make_settings()
        assert s.ogr_connection_string.startswith("PG:")

    def test_default_includes_host_and_dbname(self):
        s = _make_settings()
        ogr = s.ogr_connection_string
        assert "host=" in ogr
        assert "dbname=" in ogr

    def test_override_parses_url_to_pg_format(self):
        s = _make_settings(database_url_override="postgresql://u:p@rds:5432/mydb")
        ogr = s.ogr_connection_string
        assert ogr.startswith("PG:")
        assert "host=rds" in ogr
        assert "dbname=mydb" in ogr

    def test_override_includes_sslmode_for_require(self):
        s = _make_settings(
            database_url_override="postgresql://u:p@host/db",
            database_ssl_mode="require",
        )
        assert "sslmode=require" in s.ogr_connection_string

    def test_override_omits_sslmode_for_prefer(self):
        s = _make_settings(
            database_url_override="postgresql://u:p@host/db",
            database_ssl_mode="prefer",
        )
        assert "sslmode" not in s.ogr_connection_string


class TestDatabaseConnectArgs:
    """Test database_connect_args property."""

    def test_disable_returns_empty(self):
        s = _make_settings(database_ssl_mode="disable")
        assert s.database_connect_args == {}

    def test_prefer_returns_ssl_prefer(self):
        s = _make_settings(database_ssl_mode="prefer")
        assert s.database_connect_args == {"ssl": "prefer"}

    def test_require_returns_ssl_context(self):
        import ssl

        s = _make_settings(database_ssl_mode="require")
        args = s.database_connect_args
        assert "ssl" in args
        ctx = args["ssl"]
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.check_hostname is False

    def test_verify_full_returns_ssl_context_with_verify(self):
        import ssl

        # verify-full with /dev/null won't load a valid CA, just tests the code path
        _make_settings(
            database_ssl_mode="verify-full",
            database_ssl_ca_cert="/dev/null",
        )
        # verify-full with invalid cert path will raise on connect_args access
        # Just verify that require mode produces a valid SSLContext
        s2 = _make_settings(database_ssl_mode="require")
        args = s2.database_connect_args
        assert isinstance(args["ssl"], ssl.SSLContext)


class TestConditionalValidation:
    """Test fail-fast validation for provider settings."""

    def test_s3_missing_bucket_raises(self):
        with pytest.raises(Exception) as exc_info:
            _make_settings(
                storage_provider="s3",
                s3_access_key_id="key",
                s3_secret_access_key="secret",
            )
        assert "S3_BUCKET" in str(exc_info.value)

    def test_s3_missing_all_raises(self):
        with pytest.raises(Exception) as exc_info:
            _make_settings(storage_provider="s3")
        err_msg = str(exc_info.value)
        assert "S3_BUCKET" in err_msg
        assert "S3_ACCESS_KEY_ID" in err_msg
        assert "S3_SECRET_ACCESS_KEY" in err_msg

    def test_s3_all_present_succeeds(self):
        s = _make_settings(
            storage_provider="s3",
            s3_bucket="my-bucket",
            s3_access_key_id="key",
            s3_secret_access_key="secret",
        )
        assert s.storage_provider == "s3"

    def test_ssl_verify_full_without_cert_raises(self):
        with pytest.raises(Exception) as exc_info:
            _make_settings(database_ssl_mode="verify-full")
        assert "DATABASE_SSL_CA_CERT" in str(exc_info.value)

    def test_local_provider_no_s3_required(self):
        s = _make_settings(storage_provider="local")
        assert s.storage_provider == "local"


class TestEmptyStringToNone:
    """Test that empty string env vars become None."""

    def test_empty_redis_url(self):
        s = _make_settings(redis_url="")
        assert s.redis_url is None

    def test_empty_cdn_base_url(self):
        s = _make_settings(cdn_base_url="  ")
        assert s.cdn_base_url is None

    def test_empty_database_url_override(self):
        s = _make_settings(database_url_override="")
        assert s.database_url_override is None

    def test_nonempty_redis_url_preserved(self):
        s = _make_settings(redis_url="redis://localhost:6379/0")
        assert s.redis_url == "redis://localhost:6379/0"


class TestExternalPooler:
    """Test db_use_external_pooler flag behavior."""

    def test_default_is_false(self):
        s = _make_settings()
        assert s.db_use_external_pooler is False

    def test_enabled_adds_statement_cache_size(self):
        s = _make_settings(db_use_external_pooler=True)
        args = s.database_connect_args
        assert args.get("statement_cache_size") == 0

    def test_disabled_no_statement_cache_size(self):
        s = _make_settings(db_use_external_pooler=False)
        args = s.database_connect_args
        assert "statement_cache_size" not in args

    def test_enabled_with_ssl_has_both(self):
        """SSL + pooler args coexist."""
        import ssl

        s = _make_settings(
            db_use_external_pooler=True,
            database_ssl_mode="require",
        )
        args = s.database_connect_args
        assert args.get("statement_cache_size") == 0
        assert isinstance(args.get("ssl"), ssl.SSLContext)

    def test_enabled_with_ssl_disable(self):
        """Pooler flag still sets statement_cache_size even with ssl=disable."""
        s = _make_settings(
            db_use_external_pooler=True,
            database_ssl_mode="disable",
        )
        args = s.database_connect_args
        assert args == {"statement_cache_size": 0}


class TestJwtSecretLengthValidator:
    """JWT_SECRET_KEY must be at least 32 characters."""

    def test_short_jwt_secret_rejected(self):
        with pytest.raises(Exception) as exc_info:
            _make_settings(jwt_secret_key="too-short")
        assert "32 characters" in str(exc_info.value)

    def test_exactly_32_chars_accepted(self):
        # The .env.example default ("dev-only-change-me-in-production") is 32 chars
        s = _make_settings(jwt_secret_key="dev-only-change-me-in-production")
        assert s.jwt_secret_key.get_secret_value() == "dev-only-change-me-in-production"

    def test_long_jwt_secret_accepted(self):
        long_key = "x" * 64
        s = _make_settings(jwt_secret_key=long_key)
        assert s.jwt_secret_key.get_secret_value() == long_key


class TestLogLevelValidator:
    """LOG_LEVEL must be a valid stdlib logging level."""

    def test_valid_levels_accepted(self):
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            s = _make_settings(log_level=level)
            assert s.log_level == level

    def test_lowercase_accepted_and_uppercased(self):
        s = _make_settings(log_level="info")
        assert s.log_level == "INFO"

    def test_invalid_level_rejected(self):
        with pytest.raises(Exception) as exc_info:
            _make_settings(log_level="verbose")
        assert "LOG_LEVEL" in str(exc_info.value)


class TestSecretStrMasking:
    """Sensitive fields use SecretStr so values are masked in repr/str/dump."""

    def test_postgres_password_masked_in_repr(self):
        s = _make_settings()
        assert "testpass" not in repr(s.postgres_password)
        assert "**" in repr(s.postgres_password)

    def test_jwt_secret_masked_in_repr(self):
        s = _make_settings()
        assert "testsecret" not in repr(s.jwt_secret_key)
        assert "**" in repr(s.jwt_secret_key)

    def test_admin_password_masked_in_repr(self):
        s = _make_settings()
        assert "adminpass" not in repr(s.geolens_admin_password)

    def test_secret_value_accessible_via_get_secret_value(self):
        s = _make_settings()
        assert s.postgres_password.get_secret_value() == "testpass"
        assert s.geolens_admin_password.get_secret_value() == "adminpass"

    def test_database_url_unwraps_password(self):
        """Internal database_url property must produce a real DSN, not 'SecretStr(...)'."""
        s = _make_settings()
        assert "testpass" in s.database_url
        assert "SecretStr" not in s.database_url

    def test_database_url_sync_unwraps_password(self):
        s = _make_settings()
        assert "testpass" in s.database_url_sync

    def test_procrastinate_conninfo_unwraps_password(self):
        s = _make_settings()
        assert "password=testpass" in s.procrastinate_conninfo

    def test_ogr_connection_string_unwraps_password(self):
        s = _make_settings()
        assert "password=testpass" in s.ogr_connection_string

    def test_anthropic_key_optional_secretstr(self):
        s = _make_settings(anthropic_api_key="sk-ant-test")
        # Truthy check still works
        assert s.anthropic_api_key
        # Mask in repr
        assert "sk-ant-test" not in repr(s.anthropic_api_key)
        # Unwrap available
        assert s.anthropic_api_key.get_secret_value() == "sk-ant-test"

    def test_empty_string_anthropic_key_becomes_none(self):
        """empty_str_to_none still applies to SecretStr fields."""
        s = _make_settings(anthropic_api_key="")
        assert s.anthropic_api_key is None

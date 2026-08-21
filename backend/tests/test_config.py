"""Tests for config.py Settings class — DATABASE_URL override and connection properties."""

from urllib.parse import parse_qs, urlsplit

import pytest

from app.core import config as config_module
from app.core.config import MIN_SIGNABLE_JOB_LIFETIME_SECONDS, Settings

# Settings constructor kwargs (lowercase field names).
# JWT_SECRET_KEY must be ≥ 32 chars to satisfy validate_jwt_secret_length.
BASE_ENV = {
    "postgres_password": "testpass",
    "jwt_secret_key": "testsecret-padding-to-32-chars-min",
    "geolens_admin_username": "admin",
    "geolens_admin_password": "adminpass",
}

# Pinned off for every _make_settings() call: these are read from the ambient
# environment, so a developer or runner that happens to export them (anything
# running inside EKS or ECS) would otherwise satisfy the s3 credential
# requirement and flip the expectations in TestConditionalValidation. Kept out
# of BASE_ENV because that dict is also replayed through monkeypatch.setenv,
# which takes str values only.
_AMBIENT_AWS_OFF = {
    "aws_role_arn": None,
    "aws_web_identity_token_file": None,
    "aws_container_credentials_full_uri": None,
    "aws_container_credentials_relative_uri": None,
}


def _make_settings(**overrides):
    """Create a fresh Settings instance with given env overrides.

    Bypasses the env_file fallback by passing every required field as a kwarg
    so test isolation is unaffected by the host's .env file. Each call returns
    an independent Settings instance — the module-level ``settings`` singleton
    in ``app.config`` is never touched.
    """
    env = {**BASE_ENV, **_AMBIENT_AWS_OFF, **overrides}
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

    def test_override_normalizes_psycopg_scheme_for_async_engine(self):
        s = _make_settings(
            database_url_override="postgresql+psycopg://u:p@host:5432/db"
        )
        assert s.database_url.startswith("postgresql+asyncpg://")

    def test_override_preserves_non_ssl_query_params(self):
        s = _make_settings(
            database_url_override="postgresql://u:p@host/db?application_name=geolens&sslmode=require"
        )
        url = s.database_url
        assert "sslmode" not in url
        assert "application_name=geolens" in url

    @pytest.mark.parametrize(
        "url",
        [
            "not-a-postgres-url",
            "mysql://user:pass@host/db",
            "postgresql:///missing-host",
            "postgresql://user:pass@host",
            "postgresql://user:pass@host/",
            "postgresql://user:pass@host-one,host-two/db",
            "postgresql://user:pass@host/db?host=/var/run/postgresql",
            "postgresql:///db?host=",
            "postgresql:///db?host=/one&host=/two",
            "postgresql://user:pass@host:not-a-port/db",
            "postgresql://user:pass@host:65536/db",
        ],
    )
    def test_invalid_or_non_postgres_override_rejected(self, url):
        with pytest.raises(Exception):
            _make_settings(database_url_override=url)

    @pytest.mark.parametrize(
        "url",
        [
            "postgres://u:p@host/db",
            "postgresql://u:p@host/db",
            "postgresql+asyncpg://u:p@host/db",
            "postgresql+psycopg://u:p@host/db",
            "postgresql+asyncpg://u:p@/db?host=/var/run/postgresql",
            "postgresql:///db?host=/cloudsql/project:region:instance",
        ],
    )
    def test_supported_postgres_schemes_accepted(self, url):
        assert _make_settings(database_url_override=url).database_url_override

    def test_unix_socket_host_survives_async_url_normalization(self):
        s = _make_settings(
            database_url_override=(
                "postgresql+asyncpg://u:p@/db?host=/var/run/postgresql&sslmode=disable"
            )
        )

        parsed = urlsplit(s.database_url)
        assert parsed.scheme == "postgresql+asyncpg"
        assert parse_qs(parsed.query)["host"] == ["/var/run/postgresql"]
        assert "sslmode" not in parse_qs(parsed.query)

    def test_boot_error_redacts_invalid_dsn_credentials(self, monkeypatch, capsys):
        for field, value in BASE_ENV.items():
            monkeypatch.setenv(field.upper(), value)
        monkeypatch.setenv(
            "DATABASE_URL_OVERRIDE",
            "mysql://user:must-not-appear@host/database",
        )

        with pytest.raises(SystemExit):
            config_module._create_settings()

        stderr = capsys.readouterr().err
        assert "DATABASE_URL_OVERRIDE" in stderr
        assert "must-not-appear" not in stderr


class TestSingleTenantRuntimeDatabaseRole:
    _RUNTIME_PASSWORD = "runtime-password-with-at-least-32-characters"

    def test_unset_preserves_legacy_connection(self):
        assert _make_settings().geolens_runtime_db_role is None

    def test_matching_runtime_override_is_accepted(self):
        settings = _make_settings(
            geolens_runtime_db_role="geolens_app",
            postgres_password=self._RUNTIME_PASSWORD,
            database_url_override=(
                f"postgresql://geolens_app:{self._RUNTIME_PASSWORD}@db/geolens"
            ),
        )

        assert settings.geolens_runtime_db_role == "geolens_app"

    @pytest.mark.parametrize(
        ("role", "url"),
        [
            ("GeoLens-App", "postgresql://GeoLens-App:secret@db/geolens"),
            ("geolens-app", "postgresql://geolens-app:secret@db/geolens"),
            ("9geolens", "postgresql://9geolens:secret@db/geolens"),
        ],
    )
    def test_role_name_must_be_a_safe_postgres_identifier(self, role, url):
        with pytest.raises(Exception, match="lowercase PostgreSQL identifier"):
            _make_settings(
                geolens_runtime_db_role=role,
                postgres_password=self._RUNTIME_PASSWORD,
                database_url_override=url,
            )

    def test_role_requires_a_dedicated_override(self):
        with pytest.raises(Exception, match="requires DATABASE_URL_OVERRIDE"):
            _make_settings(geolens_runtime_db_role="geolens_app")

    def test_override_username_must_match_role(self):
        with pytest.raises(Exception, match="username must match"):
            _make_settings(
                geolens_runtime_db_role="geolens_app",
                postgres_password=self._RUNTIME_PASSWORD,
                database_url_override=(
                    f"postgresql://geolens:{self._RUNTIME_PASSWORD}@db/geolens"
                ),
            )

    def test_runtime_password_must_be_long_and_match_override(self):
        with pytest.raises(Exception, match="at least 32 characters"):
            _make_settings(
                geolens_runtime_db_role="geolens_app",
                postgres_password="too-short",
                database_url_override=("postgresql://geolens_app:too-short@db/geolens"),
            )

        with pytest.raises(Exception, match="password must match"):
            _make_settings(
                geolens_runtime_db_role="geolens_app",
                postgres_password=self._RUNTIME_PASSWORD,
                database_url_override=(
                    "postgresql://geolens_app:another-runtime-password-"
                    "with-at-least-32-characters@db/geolens"
                ),
            )

    def test_multi_tenant_mode_uses_its_existing_role_topology(self):
        with pytest.raises(Exception, match="single-tenant role path"):
            _make_settings(
                geolens_tenancy_mode="multi_tenant",
                geolens_runtime_db_role="geolens_app",
                postgres_password=self._RUNTIME_PASSWORD,
                database_url_override=(
                    f"postgresql://geolens_app:{self._RUNTIME_PASSWORD}@db/geolens"
                ),
            )


class TestMigrationDatabaseRole:
    def test_unset_role_preserves_legacy_managed_override_username(self):
        settings = _make_settings(
            postgres_user="bundled_bootstrap",
            # Compose deliberately forwards an empty value in legacy mode;
            # Settings must normalize it to None instead of binding the URL
            # login to POSTGRES_USER.
            geolens_migration_db_role="",
            database_url_override=(
                "postgresql://provider_legacy:external-secret@managed/geolens"
            ),
        )

        assert settings.geolens_migration_db_role is None
        assert urlsplit(settings.database_url).username == "provider_legacy"

    def test_matching_bundled_postgres_user_is_accepted_without_override(self):
        settings = _make_settings(geolens_migration_db_role="geolens")

        assert settings.geolens_migration_db_role == "geolens"

    def test_matching_migration_override_is_accepted(self):
        settings = _make_settings(
            geolens_migration_db_role="geolens_migrator",
            database_url_override=(
                "postgresql://geolens_migrator:migration-secret@db/geolens"
            ),
        )

        assert settings.geolens_migration_db_role == "geolens_migrator"

    def test_migration_override_username_must_match_role(self):
        with pytest.raises(Exception, match="username must match"):
            _make_settings(
                geolens_migration_db_role="geolens_migrator",
                database_url_override=(
                    "postgresql://different_migrator:migration-secret@db/geolens"
                ),
            )

    def test_bundled_postgres_user_must_match_role(self):
        with pytest.raises(Exception, match="username must match"):
            _make_settings(geolens_migration_db_role="different_migrator")

    def test_migration_role_must_be_a_safe_postgres_identifier(self):
        with pytest.raises(Exception, match="lowercase PostgreSQL identifier"):
            _make_settings(
                geolens_migration_db_role="unsafe-migrator",
                database_url_override=(
                    "postgresql://unsafe-migrator:migration-secret@db/geolens"
                ),
            )


class TestTileDatabaseUrlOverride:
    """The tile pool can use a dedicated login without changing other consumers."""

    def test_unset_falls_back_to_runtime_url(self):
        s = _make_settings(
            database_url_override="postgresql://app:pass@host:5432/geolens"
        )
        assert s.tile_database_url == s.database_url

    def test_postgresql_override_normalizes_for_asyncpg(self):
        s = _make_settings(
            tile_database_url_override=(
                "postgresql://tile:pass@host:5432/geolens?sslmode=require"
            )
        )
        assert s.tile_database_url.startswith("postgresql+asyncpg://tile:pass@")
        assert "sslmode" not in s.tile_database_url

    def test_postgres_override_normalizes_for_asyncpg(self):
        s = _make_settings(
            tile_database_url_override="postgres://tile:pass@host:5432/geolens"
        )
        assert s.tile_database_url.startswith("postgresql+asyncpg://tile:pass@")


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

    def test_unix_socket_host_survives_sync_url_normalization(self):
        s = _make_settings(
            database_url_override=(
                "postgresql+asyncpg://u:p@/db?host=/var/run/postgresql"
            )
        )
        parsed = urlsplit(s.database_url_sync)
        assert parsed.scheme == "postgresql+psycopg"
        assert parse_qs(parsed.query)["host"] == ["/var/run/postgresql"]


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

    def test_override_includes_search_path(self):
        # BUG-002: the override branch previously dropped the search_path
        # option, so procrastinate could not resolve its unqualified objects on
        # managed Postgres (DATABASE_URL_OVERRIDE) and the job queue broke. The
        # override branch must mirror the default branch and pin the catalog
        # schema. (Fails on main — the override conninfo had no search_path.)
        s = _make_settings(database_url_override="postgresql://u:p@host:5432/db")
        conninfo = s.procrastinate_conninfo
        assert "options='-c search_path=catalog,public'" in conninfo

    def test_override_preserves_caller_options(self):
        # An operator can still pass extra libpq options via ?options=; our
        # search_path is appended (and applied last so procrastinate's schema
        # always wins) rather than discarding the caller's value.
        s = _make_settings(
            database_url_override=(
                "postgresql://u:p@host/db?options=-c%20statement_timeout%3D5000"
            )
        )
        conninfo = s.procrastinate_conninfo
        assert "statement_timeout=5000" in conninfo
        assert "search_path=catalog,public" in conninfo

    def test_unix_socket_override_includes_query_host(self):
        s = _make_settings(
            database_url_override=(
                "postgresql+asyncpg://u:p@/db?host=/var/run/postgresql"
            )
        )
        assert "host=/var/run/postgresql" in s.procrastinate_conninfo


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

    def test_override_includes_ca_cert_for_verify_full(self):
        """Measured on EKS against RDS with rds.force_ssl=1: sslmode=verify-full
        without sslrootcert sent libpq to ~/.postgresql/root.crt, which the
        image does not ship, and every vector ingest died in ogr2ogr with
        "root certificate file ... does not exist" while the api stayed
        healthy — asyncpg gets the CA as an SSLContext and never consults it."""
        s = _make_settings(
            database_url_override="postgresql://u:p@host/db",
            database_ssl_mode="verify-full",
            database_ssl_ca_cert="/etc/ssl/rds/ca.pem",
        )
        ogr = s.ogr_connection_string
        assert "sslmode=verify-full" in ogr
        assert "sslrootcert=/etc/ssl/rds/ca.pem" in ogr

    def test_ca_cert_matches_the_procrastinate_sibling(self):
        """The two libpq DSN builders must not drift apart again."""
        s = _make_settings(
            database_url_override="postgresql://u:p@host/db",
            database_ssl_mode="verify-full",
            database_ssl_ca_cert="/etc/ssl/rds/ca.pem",
        )
        for token in ("sslmode=verify-full", "sslrootcert=/etc/ssl/rds/ca.pem"):
            assert token in s.ogr_connection_string
            assert token in s.procrastinate_conninfo

    def test_no_ca_cert_emits_no_sslrootcert(self):
        s = _make_settings(
            database_url_override="postgresql://u:p@host/db",
            database_ssl_mode="require",
        )
        assert "sslrootcert" not in s.ogr_connection_string

    def test_override_omits_sslmode_for_prefer(self):
        s = _make_settings(
            database_url_override="postgresql://u:p@host/db",
            database_ssl_mode="prefer",
        )
        assert "sslmode" not in s.ogr_connection_string

    def test_unix_socket_override_includes_query_host(self):
        s = _make_settings(
            database_url_override=(
                "postgresql+asyncpg://u:p@/db?host=/var/run/postgresql"
            )
        )
        assert "host=/var/run/postgresql" in s.ogr_connection_string


class TestDatabaseConnectArgs:
    """Test database_connect_args property."""

    def test_disable_returns_ssl_false(self):
        s = _make_settings(database_ssl_mode="disable")
        assert s.database_connect_args == {"ssl": False}

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

        import certifi

        s = _make_settings(
            database_ssl_mode="verify-full",
            database_ssl_ca_cert=certifi.where(),
        )
        args = s.database_connect_args
        assert isinstance(args["ssl"], ssl.SSLContext)
        # verify-full does NOT override check_hostname or verify_mode — defaults apply
        assert args["ssl"].check_hostname is True
        assert args["ssl"].verify_mode == ssl.CERT_REQUIRED


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

    def test_s3_ambient_irsa_credentials_allow_missing_keys(self):
        """EKS IRSA: the runtime injects a web-identity token, boto3 and GDAL
        resolve the role themselves, and no static key pair should be needed."""
        s = _make_settings(
            storage_provider="s3",
            s3_bucket="my-bucket",
            aws_role_arn="arn:aws:iam::123456789012:role/geolens",
            aws_web_identity_token_file=(
                "/var/run/secrets/eks.amazonaws.com/serviceaccount/token"
            ),
        )
        assert s.storage_provider == "s3"
        assert s.has_ambient_aws_credentials is True
        assert s.s3_access_key_id is None

    def test_s3_ambient_container_credentials_allow_missing_keys(self):
        s = _make_settings(
            storage_provider="s3",
            s3_bucket="my-bucket",
            aws_container_credentials_full_uri="http://169.254.170.23/v1/creds",
        )
        assert s.has_ambient_aws_credentials is True

    def test_s3_role_arn_without_token_file_is_not_ambient(self):
        """Both halves of the web-identity pair are required — a lone
        AWS_ROLE_ARN resolves no credentials, so it must not unlock the keys."""
        with pytest.raises(Exception) as exc_info:
            _make_settings(
                storage_provider="s3",
                s3_bucket="my-bucket",
                aws_role_arn="arn:aws:iam::123456789012:role/geolens",
            )
        assert "S3_ACCESS_KEY_ID" in str(exc_info.value)

    def test_s3_half_configured_key_pair_raises_even_with_ambient(self):
        """A half-set static pair is always a mistake; ambient must not mask it."""
        with pytest.raises(Exception) as exc_info:
            _make_settings(
                storage_provider="s3",
                s3_bucket="my-bucket",
                s3_access_key_id="key",
                aws_role_arn="arn:aws:iam::123456789012:role/geolens",
                aws_web_identity_token_file="/var/run/secrets/token",
            )
        err = str(exc_info.value)
        assert "S3_SECRET_ACCESS_KEY" in err
        assert "S3_ACCESS_KEY_ID" not in err

    def test_s3_missing_keys_error_points_at_the_ambient_option(self):
        with pytest.raises(Exception) as exc_info:
            _make_settings(storage_provider="s3", s3_bucket="my-bucket")
        assert "eks.amazonaws.com/role-arn" in str(exc_info.value)

    def test_ssl_verify_full_without_cert_raises(self):
        with pytest.raises(Exception) as exc_info:
            _make_settings(database_ssl_mode="verify-full")
        assert "DATABASE_SSL_CA_CERT" in str(exc_info.value)

    def test_local_provider_no_s3_required(self):
        s = _make_settings(storage_provider="local")
        assert s.storage_provider == "local"

    def test_tile_pool_min_must_not_exceed_max(self):
        with pytest.raises(Exception) as exc_info:
            _make_settings(tile_pool_min_size=11, tile_pool_max_size=10)
        assert "TILE_POOL_MIN_SIZE" in str(exc_info.value)


class TestSettingsConstraints:
    """Invalid enum and numeric configuration must fail during Settings parsing."""

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("jwt_algorithm", "none"),
            ("geolens_edition", "enterpise"),
            ("storage_provider", "typo"),
            ("database_ssl_mode", "typo"),
            ("s3_addressing_style", "typo"),
        ],
    )
    def test_invalid_enum_rejected(self, field, value):
        with pytest.raises(Exception):
            _make_settings(**{field: value})

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("postgres_port", 0),
            ("postgres_port", 65536),
            ("access_token_expire_minutes", 0),
            ("refresh_token_expire_days", 0),
            ("password_min_length", 7),
            ("upload_max_size_mb", 0),
            ("presigned_multipart_threshold_mb", 0),
            ("embedding_dims", 0),
            ("embedding_dims", 4097),
            ("worker_shutdown_timeout", 0),
            ("worker_concurrency", 0),
            ("db_pool_size", 0),
            ("db_max_overflow", -2),
            ("db_pool_timeout", 0),
            ("db_pool_recycle", -2),
            ("tile_pool_min_size", 0),
            ("tile_pool_max_size", 0),
            ("ingest_http_timeout_seconds", 0),
            # fix(#1013): zero is the dangerous one for these two —
            # statement_timeout = '0' disables the timeout entirely rather than
            # erroring, so a zero accepted here would silently produce the
            # unbounded statement the budget exists to prevent.
            ("analysis_materialize_timeout_seconds", 0),
            ("analysis_materialize_timeout_seconds", -1),
            ("analysis_materialize_timeout_seconds", "not-a-number"),
            ("analysis_registration_timeout_seconds", 0),
            ("analysis_registration_timeout_seconds", -1),
            ("analysis_registration_timeout_seconds", "not-a-number"),
            # fix(#1012): 0 is a documented sentinel (leave work_mem alone),
            # so only negatives are rejected.
            ("analysis_materialize_work_mem_mb", -1),
            ("ingest_jobs_retention_days", -1),
            ("smtp_port", 0),
            ("smtp_port", 65536),
        ],
    )
    def test_out_of_range_numeric_value_rejected(self, field, value):
        with pytest.raises(Exception):
            _make_settings(**{field: value})

    def test_undividable_work_mem_budget_is_refused_at_boot(self):
        """fix(#1012 review): a budget too small to split into legal shares has
        no honest run-time outcome.

        Issuing PostgreSQL's 64kB minimum exceeds the budget; skipping the
        override leaves the cluster's own work_mem — usually LARGER — in force
        for every slot, overshooting by more. So it fails at boot.
        """
        with pytest.raises(Exception) as exc_info:
            _make_settings(analysis_materialize_work_mem_mb=1, worker_concurrency=32)
        message = str(exc_info.value)
        assert "32kB per slot" in message, message
        assert "64kB minimum" in message, message

        # And above PostgreSQL's own work_mem maximum, for the same reason:
        # every materialize would fail at SET LOCAL and be recorded as a
        # failed job.
        with pytest.raises(Exception) as exc_info:
            _make_settings(
                analysis_materialize_work_mem_mb=2097152, worker_concurrency=1
            )
        assert "work_mem maximum" in str(exc_info.value), str(exc_info.value)

        # The documented escape hatches both boot.
        assert (
            _make_settings(
                analysis_materialize_work_mem_mb=0, worker_concurrency=32
            ).analysis_materialize_work_mem_mb
            == 0
        )
        assert (
            _make_settings(
                analysis_materialize_work_mem_mb=64, worker_concurrency=32
            ).worker_concurrency
            == 32
        )

    def test_documented_zero_and_negative_sentinels_remain_supported(self):
        s = _make_settings(
            tile_cache_ttl=0,
            ingest_jobs_retention_days=0,
            db_max_overflow=-1,
            db_pool_recycle=-1,
            analysis_materialize_work_mem_mb=0,
        )
        assert s.tile_cache_ttl == 0
        assert s.ingest_jobs_retention_days == 0
        assert s.db_max_overflow == -1
        assert s.db_pool_recycle == -1
        assert s.analysis_materialize_work_mem_mb == 0

    def test_worker_queues_are_trimmed_and_normalized(self):
        s = _make_settings(worker_queues=" priority, ingest ,raster ")
        assert s.worker_queues == "priority,ingest,raster"

    @pytest.mark.parametrize("queues", ["", " , ", "ingest,ingest"])
    def test_empty_or_duplicate_worker_queues_rejected(self, queues):
        with pytest.raises(Exception):
            _make_settings(worker_queues=queues)


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

    def test_empty_tile_database_url_override(self):
        s = _make_settings(tile_database_url_override="")
        assert s.tile_database_url_override is None

    def test_empty_geolens_edition_uses_auto_detection(self):
        s = _make_settings(geolens_edition="")
        assert s.geolens_edition is None

    @pytest.mark.parametrize("value", ["", "   "])
    def test_empty_embedding_dims_uses_default(self, value):
        s = _make_settings(embedding_dims=value)
        assert s.embedding_dims == 1536

    def test_geolens_edition_is_normalized_case_insensitively(self):
        s = _make_settings(geolens_edition=" Enterprise ")
        assert s.geolens_edition == "enterprise"

    def test_nonempty_redis_url_preserved(self):
        s = _make_settings(redis_url="redis://localhost:6379/0")
        assert s.redis_url == "redis://localhost:6379/0"

    def test_empty_notification_secrets_become_none(self):
        s = _make_settings(smtp_password="", notification_webhook_secret=" ")
        assert s.smtp_password is None
        assert s.notification_webhook_secret is None


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
        assert args == {"statement_cache_size": 0, "ssl": False}


class TestJwtSecretLengthValidator:
    """JWT_SECRET_KEY must be at least 32 characters and not a known-bad value."""

    def test_short_jwt_secret_rejected(self):
        with pytest.raises(Exception) as exc_info:
            _make_settings(jwt_secret_key="too-short")
        assert "32 characters" in str(exc_info.value)

    def test_exactly_32_chars_unique_value_accepted(self):
        # 32-char string that is NOT in KNOWN_BAD_JWT_SECRETS
        unique_32 = "exactly32-character-test-secret!"
        assert len(unique_32) == 32
        s = _make_settings(jwt_secret_key=unique_32)
        assert s.jwt_secret_key.get_secret_value() == unique_32

    def test_long_jwt_secret_accepted(self):
        long_key = "x" * 64
        s = _make_settings(jwt_secret_key=long_key)
        assert s.jwt_secret_key.get_secret_value() == long_key

    def test_known_bad_jwt_secret_rejected(self):
        """Phase 268 H-28: .env.example default is exactly 32 chars but is a
        public, version-controlled value. The validator must reject it."""
        with pytest.raises(Exception) as exc_info:
            _make_settings(jwt_secret_key="dev-only-change-me-in-production")
        assert "publicly-known example value" in str(exc_info.value)

    def test_short_known_bad_jwt_secrets_hit_length_check_first(self):
        """Short known-bad values like 'change-me' fail the length check
        (which fires before the known-bad check), so operators see the
        actionable 'must be 32 chars' guidance instead."""
        for short_value in ("change-me", "secret", "changeme"):
            with pytest.raises(Exception) as exc_info:
                _make_settings(jwt_secret_key=short_value)
            assert "32 characters" in str(exc_info.value)


class TestKnownBadCredentialsGuard:
    """Refuse to boot with known-public credential literals from git history."""

    def test_known_bad_jwt_secret_rejected(self):
        with pytest.raises(Exception) as exc_info:
            _make_settings(
                jwt_secret_key="demo-only-do-not-use-in-production-change-me"
            )
        assert "JWT_SECRET_KEY" in str(exc_info.value)

    def test_known_bad_admin_password_rejected(self):
        with pytest.raises(Exception) as exc_info:
            _make_settings(geolens_admin_password="demodemo")
        assert "GEOLENS_ADMIN_PASSWORD" in str(exc_info.value)

    def test_known_bad_postgres_password_rejected(self):
        with pytest.raises(Exception) as exc_info:
            _make_settings(postgres_password="geolens-demo-2026")
        assert "POSTGRES_PASSWORD" in str(exc_info.value)


class TestEmptyAdminCredentialsGuard:
    """Refuse to boot with empty admin credentials (verbatim .env.example)."""

    @pytest.mark.parametrize("username", ["", "   "])
    def test_empty_admin_username_rejected(self, username):
        with pytest.raises(Exception) as exc_info:
            _make_settings(geolens_admin_username=username)
        assert "GEOLENS_ADMIN_USERNAME" in str(exc_info.value)

    @pytest.mark.parametrize("password", ["", "   "])
    def test_empty_admin_password_rejected(self, password):
        with pytest.raises(Exception) as exc_info:
            _make_settings(geolens_admin_password=password)
        assert "GEOLENS_ADMIN_PASSWORD" in str(exc_info.value)


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


class TestPrivacyUrlValidator:
    """PRIV-1: PRIVACY_URL is rendered as a raw <a href> on the login page,
    so an unsafe value must fail boot rather than reach the browser. This is
    the ONLY validation an ENV_ONLY_CONFIG deployment ever runs for it — the
    admin-write validator never sees an env-sourced value in that mode.
    """

    def test_unset_stays_none(self):
        s = _make_settings(privacy_url="")
        assert s.privacy_url is None

    def test_safe_url_accepted(self):
        s = _make_settings(privacy_url="https://example.com/privacy")
        assert s.privacy_url == "https://example.com/privacy"

    def test_query_and_fragment_preserved(self):
        value = "https://docs.google.com/document/d/abc/edit?usp=sharing#h.xyz"
        s = _make_settings(privacy_url=value)
        assert s.privacy_url == value

    @pytest.mark.parametrize(
        "value",
        [
            "https://[::1]/x",
            "https://10.0.0.1:8443/x",
            "https://[2001:db8::1]:8443/x",
        ],
    )
    def test_ip_literal_host_accepted(self, value):
        s = _make_settings(privacy_url=value)
        assert s.privacy_url == value

    @pytest.mark.parametrize(
        "value",
        [
            "https://例え.テスト/privacy",
            "https://xn--r8jz45g.xn--zckzah/privacy",
        ],
    )
    def test_internationalized_host_accepted_unchanged(self, value):
        """Stored and served exactly as entered, in either its native
        Unicode spelling or its already-punycode form -- not rewritten to a
        canonical form, matching what a browser does with the same input.
        """
        s = _make_settings(privacy_url=value)
        assert s.privacy_url == value

    @pytest.mark.parametrize(
        "value",
        [
            "not-a-url",
            "javascript:alert(document.cookie)",
            "data:text/html,<script>alert(1)</script>",
            "//evil.example.com/p",
            "https://user:pass@example.com/privacy",
            "https://example.com:not-a-port/x",
            "https://:443/x",
            "https://exa mple.com/x",
            "https://exam_ple.com/x",
            "https://-bad.com/x",
            "https://999.999.999.999/x",
            "https://1.2.3.4.5/x",
            "https://192.168.1/x",
            "https://0x7f.1/x",
            "https://a..b/x",
            "https://́.example.com/x",
            "https://xn--a.com/x",
            "https://xn--.com/x",
            "https://[v1.foo]/x",
            "https://[fe80::1%25eth0]/x",
            "https://[fe80::1%eth0]/x",
            "https://[1.2.3.4]/x",
            "https://xn--lsa.example/x",
            "https://﹇.com/x",
            "https://192.168.1./x",
            "https://999.999.999.999./x",
            "https://999。999。999。999/x",
            "https://192.168.1。/x",
        ],
    )
    def test_unsafe_value_fails_boot(self, value):
        with pytest.raises(Exception) as exc_info:
            _make_settings(privacy_url=value)
        assert "PRIVACY_URL" in str(exc_info.value)

    @pytest.mark.parametrize(
        "host, accepted",
        [
            ("例え.テスト", True),
            ("́.example.com", False),  # a bare combining mark as a label
        ],
    )
    def test_ulabel_and_alabel_forms_get_the_same_verdict(self, host, accepted):
        """PRIV-1 (codex r7): a host's native Unicode (U-label) spelling and
        its IDNA-encoded ("xn--...", A-label) spelling must always agree --
        which one the operator happened to type is never why one is
        accepted and the other rejected. Skips the A-form comparison for a
        host IDNA itself cannot encode (there is no A-form to compare).
        """
        u_url = f"https://{host}/x"
        if accepted:
            s = _make_settings(privacy_url=u_url)
            assert s.privacy_url == u_url
        else:
            with pytest.raises(Exception):
                _make_settings(privacy_url=u_url)

        try:
            a_host = host.encode("idna").decode("ascii")
        except UnicodeError:
            return

        a_url = f"https://{a_host}/x"
        if accepted:
            s = _make_settings(privacy_url=a_url)
            assert s.privacy_url == a_url
        else:
            with pytest.raises(Exception):
                _make_settings(privacy_url=a_url)

    @pytest.mark.parametrize(
        "value",
        [
            "https://10.0.0.1./x",
            "https://example.com./x",
            "https://１２７.０.０.１/x",
            "https://例え。テスト/x",
        ],
    )
    def test_uts46_mapped_host_accepted(self, value):
        """Browser-valid hosts that only pass because UTS46 mapping runs
        before every other check, stored exactly as entered (never
        rewritten to a canonical or mapped form): a single trailing DNS
        root dot on a canonical IPv4 host and on an ordinary DNS name, a
        fullwidth-digit IPv4 host, and an internationalized DNS name
        written with ideographic full stops instead of ASCII dots.
        """
        s = _make_settings(privacy_url=value)
        assert s.privacy_url == value


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


class TestPendingJobTimeoutBounds:
    """fix(#1235 review r5, r6): both ends, enforced at config load.

    Each end had the same shape — a value the settings model accepted under
    which no upload could ever succeed, so the deployment booted clean and
    failed only when a user tried. Above 604800 boto signs URLs whose
    `X-Amz-Expires` exceeds the SigV4 maximum and S3 rejects every request; at
    or below the signing margin the job's whole lifetime is shorter than the
    shortest URL worth issuing, so every presign answers 409.
    """

    def test_the_sigv4_ceiling_is_accepted(self):
        s = _make_settings(pending_job_timeout_seconds=604800)
        assert s.pending_job_timeout_seconds == 604800

    def test_past_the_sigv4_ceiling_is_refused(self):
        with pytest.raises(Exception) as excinfo:
            _make_settings(pending_job_timeout_seconds=604801)
        assert "pending_job_timeout_seconds" in str(excinfo.value)

    def test_a_timeout_at_the_signing_margin_is_refused(self):
        """fix(#1235 review r6): the dead zone is excluded by the bound, not
        discovered by the operator when every upload starts failing."""
        with pytest.raises(Exception) as excinfo:
            _make_settings(
                pending_job_timeout_seconds=MIN_SIGNABLE_JOB_LIFETIME_SECONDS
            )
        assert "pending_job_timeout_seconds" in str(excinfo.value)

    def test_just_past_the_signing_margin_is_accepted(self):
        """The bound excludes the dead zone and nothing beyond it."""
        s = _make_settings(
            pending_job_timeout_seconds=MIN_SIGNABLE_JOB_LIFETIME_SECONDS + 1
        )
        assert s.pending_job_timeout_seconds == MIN_SIGNABLE_JOB_LIFETIME_SECONDS + 1

    def test_zero_is_still_refused(self):
        """The original gt=0 intent survives inside the higher floor."""
        with pytest.raises(Exception):
            _make_settings(pending_job_timeout_seconds=0)


class TestLibpqValueQuoting:
    """codex review on #1617: an unescaped value with whitespace ends the
    keyword/value pair early and produces a malformed libpq DSN. Applied to
    every interpolated value in both builders, not only the reported one."""

    def test_ordinary_values_stay_bare(self):
        # Byte-identical to what deployments already pass to GDAL's PG driver.
        assert config_module.libpq_value("/etc/ssl/rds/ca.pem") == "/etc/ssl/rds/ca.pem"
        assert config_module.libpq_value("geolens") == "geolens"

    def test_value_with_space_is_quoted(self):
        assert config_module.libpq_value("/etc/company certs/ca.pem") == (
            "'/etc/company certs/ca.pem'"
        )

    def test_quotes_and_backslashes_are_escaped(self):
        assert config_module.libpq_value("pa'ss\\word") == "'pa\\'ss\\\\word'"

    def test_empty_value_is_quoted(self):
        assert config_module.libpq_value("") == "''"

    def test_ca_path_with_space_survives_into_both_builders(self):
        s = _make_settings(
            database_url_override="postgresql://u:p@host/db",
            database_ssl_mode="verify-full",
            database_ssl_ca_cert="/etc/company certs/ca.pem",
        )
        for dsn in (s.ogr_connection_string, s.procrastinate_conninfo):
            assert "sslrootcert='/etc/company certs/ca.pem'" in dsn

    def test_percent_encoded_credentials_are_decoded_like_sqlalchemy(self):
        """Found while testing the quoting above. urlparse does NOT decode, so
        these two builders were sending the literal `pass%20word` as the
        password while the API path — which hands the DSN to SQLAlchemy, which
        does decode — authenticated correctly. Any password needing
        percent-encoding (a `@` is the common one) therefore worked for the API
        and failed for vector ingest and the job queue."""
        s = _make_settings(
            database_url_override="postgresql://u%40corp:p%40ss%20word@host/my%20db",
        )
        for dsn in (s.ogr_connection_string, s.procrastinate_conninfo):
            assert "user=u@corp" in dsn
            assert "password='p@ss word'" in dsn

    def test_database_name_is_NOT_decoded_because_sqlalchemy_does_not(self):
        """codex review on #1617: SQLAlchemy decodes username and password but
        leaves the database name percent-encoded — `make_url(...).database` on
        `/my%20db` returns `my%20db`. Decoding it here would point ogr2ogr and
        Procrastinate at a different database than the API, so a healthy API
        could sit alongside every queued job and vector ingest writing
        somewhere else. Whatever the API uses, these two must use."""
        s = _make_settings(database_url_override="postgresql://u:p@host/my%20db")
        for dsn in (s.ogr_connection_string, s.procrastinate_conninfo):
            assert "dbname=my%20db" in dsn
            assert "dbname='my db'" not in dsn

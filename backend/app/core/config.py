import sys
from pathlib import Path

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def reveal(secret: SecretStr | None) -> str | None:
    """Unwrap an optional SecretStr to its raw value, or return None."""
    return secret.get_secret_value() if secret is not None else None


_PROJECT_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"

# Phase 268 H-19 / Phase 1061 SEC-S06: known-public demo credentials committed
# in the old .env.demo. Any deployment using these literal strings is
# trivially exploitable — the values are world-known via the public repo.
# Phase 1061 extends the validator to refuse ALL THREE literals unconditionally
# (i.e., even when GEOLENS_DEMO_MODE=true) so operators must run
# scripts/init-demo-env.sh to generate per-deploy random values first.
DEMO_JWT_SECRET = "demo-only-do-not-use-in-production-change-me"
DEMO_ADMIN_PASSWORD = "demodemo"
DEMO_POSTGRES_PASSWORD = "geolens-demo-2026"  # Phase 1061 SEC-S06

# Phase 268 H-28: known-public example values that the JWT length validator
# would otherwise accept. Any of these strings on a real deployment lets an
# attacker forge tokens trivially. The validator rejects them in all modes
# (no demo opt-in — these are documentation defaults, not demo credentials).
KNOWN_BAD_JWT_SECRETS = frozenset(
    {
        "dev-only-change-me-in-production",  # .env.example default (32 chars)
        "change-me",
        "secret",
        "changeme",
        "please-change-me",
        "your-secret-key",
    }
)


class Settings(BaseSettings):
    postgres_user: str = "geolens"
    postgres_password: SecretStr
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "geolens"
    postgres_db_test: str = "geolens_test"

    jwt_secret_key: SecretStr
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # SEC-S16 (Phase 1062-01): password complexity policy.
    # PASSWORD_MIN_LENGTH controls the minimum character count (default 12).
    # PASSWORD_REQUIRE_CLASSES controls how many of the four character classes
    # (lowercase, uppercase, digit, symbol) must be present (default 3).
    # Operators can relax both in dev/test via environment variables.
    password_min_length: int = 12
    password_require_classes: int = Field(default=3, ge=1, le=4)
    geolens_admin_username: str
    geolens_admin_password: SecretStr
    registration_enabled: bool = False

    cors_allowed_origins: str = ""
    upload_max_size_mb: int = 500
    upload_staging_dir: str = "/app/staging"
    upload_allowed_extensions: str = (
        ".zip,.gpkg,.geojson,.json,.csv,.tif,.tiff,.xlsx,.xls"
    )
    presigned_multipart_threshold_mb: int = 100
    procrastinate_schema: str = "catalog"

    public_app_url: str | None = None
    public_api_url: str | None = None
    public_base_url: str | None = None

    log_json: bool = False
    log_level: str = "INFO"

    # Phase 268 H-19: explicit opt-in for the public-demo overlay. When false
    # (default), the application refuses to boot if known-public demo
    # credentials (.env.demo defaults) are detected. Set GEOLENS_DEMO_MODE=true
    # only under docker-compose.demo.yml.
    geolens_demo_mode: bool = False

    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-sonnet-4-20250514"

    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o"
    openai_base_url: str | None = None

    embedding_model: str = "text-embedding-3-small"
    embedding_dims: int = 1536
    embedding_base_url: str | None = None

    storage_provider: str = "local"
    s3_endpoint: str | None = None
    s3_bucket: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_region: str = "us-east-1"
    s3_allow_http: bool = False
    s3_addressing_style: str = "auto"

    redis_url: str | None = None
    cdn_base_url: str | None = None
    tile_signing_secret: SecretStr | None = None
    tile_cache_ttl: int = 300

    database_url_override: str | None = None
    database_ssl_mode: str = "prefer"
    database_ssl_ca_cert: str | None = None
    database_pool_pre_ping: bool = True

    # CONF-03 (Phase 277 / M-38): replaces raw os.environ.get("WORKER_SHUTDOWN_TIMEOUT") in worker.py
    worker_shutdown_timeout: int = 30

    # CONF-04 (Phase 277 / M-39): replaces raw os.environ.get("ENV_ONLY_CONFIG") in core/public_urls.py
    # Security-relevant: when true, the PersistentConfig DB layer is bypassed for reads
    # and writes return 403. Keep in sync with .env.example.
    env_only_config: bool = False

    db_use_external_pooler: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 3  # DBM-04 (Phase 271): connection-budget headroom
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800

    tile_pool_min_size: int = 2
    tile_pool_max_size: int = 10

    # SEED-02 (Phase 1054): GDAL_HTTP_TIMEOUT for ogr2ogr service ingest, raised
    # from the 120s hardcoded default that timed out 50% of AGO layers in M001-7n8vpc.
    # Set INGEST_HTTP_TIMEOUT_SECONDS in the api service env to override.
    ingest_http_timeout_seconds: int = 300

    @field_validator(
        "anthropic_api_key",
        "openai_api_key",
        "openai_base_url",
        "embedding_base_url",
        "redis_url",
        "cdn_base_url",
        "public_app_url",
        "public_api_url",
        "public_base_url",
        "database_url_override",
        "s3_endpoint",
        "s3_bucket",
        "s3_access_key_id",
        "s3_secret_access_key",
        "s3_addressing_style",
        "database_ssl_ca_cert",
        "tile_signing_secret",
        mode="before",
    )
    @classmethod
    def empty_str_to_none(cls, v: str | None) -> str | None:
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @field_validator("jwt_secret_key", mode="after")
    @classmethod
    def validate_jwt_secret_length(cls, v: SecretStr) -> SecretStr:
        raw = v.get_secret_value()
        if len(raw) < 32:
            raise ValueError(
                "JWT_SECRET_KEY must be at least 32 characters. "
                "Generate one with: openssl rand -hex 32"
            )
        # Phase 268 H-28: reject known-public example values that pass the
        # length check but are committed in .env.example / docs.
        if raw in KNOWN_BAD_JWT_SECRETS:
            raise ValueError(
                "JWT_SECRET_KEY is set to a publicly-known example value. "
                "Anyone who reads the public repo can forge JWTs against "
                "this deployment. Generate a real secret with: "
                "openssl rand -hex 32"
            )
        return v

    @field_validator("log_level", mode="after")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}, got {v!r}")
        return upper

    @model_validator(mode="after")
    def validate_provider_settings(self) -> "Settings":
        if self.storage_provider == "s3":
            missing: list[str] = []
            if not self.s3_bucket:
                missing.append("S3_BUCKET")
            if not self.s3_access_key_id:
                missing.append("S3_ACCESS_KEY_ID")
            if not self.s3_secret_access_key:
                missing.append("S3_SECRET_ACCESS_KEY")
            if missing:
                raise ValueError("STORAGE_PROVIDER=s3 requires: " + ", ".join(missing))

        if self.database_ssl_mode == "verify-full" and not self.database_ssl_ca_cert:
            raise ValueError(
                "DATABASE_SSL_MODE=verify-full requires DATABASE_SSL_CA_CERT"
            )

        return self

    @model_validator(mode="after")
    def validate_demo_credentials_guard(self) -> "Settings":
        """Refuse to boot with known-public .env.demo template values.

        Phase 268 H-19 (original): refused boot with .env.demo defaults
        UNLESS GEOLENS_DEMO_MODE=true was explicitly set.

        Phase 1061 SEC-S06 (extended): refuses boot with the LITERAL
        committed .env.demo values REGARDLESS of GEOLENS_DEMO_MODE. The
        audit's headline scenario is an operator deploying
        docker-compose.demo.yml verbatim to a public-internet host with
        GEOLENS_DEMO_MODE=true — that previously succeeded, leaking
        known-public JWT / admin / postgres credentials (committed in
        .env.demo, world-readable from the repo). Now the operator must
        first run scripts/init-demo-env.sh to generate per-deploy random
        values; the literal committed strings are always refused.

        Note: GEOLENS_DEMO_MODE=true still relaxes other policies (e.g.,
        admin auto-seeding, reset interval) — this validator only blocks
        the specific known-public literal strings.
        """
        jwt_value = self.jwt_secret_key.get_secret_value()
        admin_value = self.geolens_admin_password.get_secret_value()
        pg_value = self.postgres_password.get_secret_value()

        hint = (
            " Run `scripts/init-demo-env.sh` to generate per-deploy random "
            "credentials, or set the value manually with `openssl rand -hex 32`."
        )

        if jwt_value == DEMO_JWT_SECRET:
            raise ValueError(
                "JWT_SECRET_KEY is set to the known-public .env.demo template "
                "value. This value is committed to the public repository and "
                "anyone with read access can forge JWTs against this deployment."
                + hint
            )

        if admin_value == DEMO_ADMIN_PASSWORD:
            raise ValueError(
                "GEOLENS_ADMIN_PASSWORD is set to the known-public .env.demo "
                "template value ('demodemo'). This is committed to the public "
                "repository and anyone with read access can log in as admin."
                + hint
            )

        if pg_value == DEMO_POSTGRES_PASSWORD:
            raise ValueError(
                "POSTGRES_PASSWORD is set to the known-public .env.demo template "
                "value. This is committed to the public repository."
                + hint
            )

        return self

    @property
    def allowed_extensions_list(self) -> list[str]:
        return [ext.strip() for ext in self.upload_allowed_extensions.split(",")]

    @property
    def cors_origins_list(self) -> list[str]:
        if not self.cors_allowed_origins:
            return []
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @staticmethod
    def _strip_ssl_from_url(url: str) -> str:
        from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

        parts = urlsplit(url)
        params = parse_qs(parts.query, keep_blank_values=True)
        params.pop("sslmode", None)
        new_query = urlencode(params, doseq=True)
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, new_query, parts.fragment)
        )

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            url = self.database_url_override
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            elif url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+asyncpg://", 1)
            return self._strip_ssl_from_url(url)
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_connect_args(self) -> dict:
        connect_args: dict = {}
        if self.database_ssl_mode == "prefer":
            connect_args["ssl"] = "prefer"
        elif self.database_ssl_mode != "disable":
            import ssl

            ssl_ctx = ssl.create_default_context(cafile=self.database_ssl_ca_cert)
            if self.database_ssl_mode == "require":
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE
            connect_args["ssl"] = ssl_ctx

        if self.db_use_external_pooler:
            connect_args["statement_cache_size"] = 0

        return connect_args

    @property
    def database_url_sync(self) -> str:
        if self.database_url_override:
            url = self.database_url_override
            if url.startswith("postgresql+asyncpg://"):
                url = url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
            elif url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+psycopg://", 1)
            elif url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+psycopg://", 1)
            return url
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def test_database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db_test}"
        )

    @property
    def test_database_url_sync(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db_test}"
        )

    @property
    def procrastinate_conninfo(self) -> str:
        if self.database_url_override:
            from urllib.parse import urlparse

            raw = self.database_url_override
            for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://"):
                if raw.startswith(prefix):
                    raw = raw.replace(prefix, "postgresql://", 1)
                    break
            if raw.startswith("postgres://"):
                raw = raw.replace("postgres://", "postgresql://", 1)
            parsed = urlparse(raw)
            parts = []
            if parsed.hostname:
                parts.append(f"host={parsed.hostname}")
            if parsed.port:
                parts.append(f"port={parsed.port}")
            if parsed.path and parsed.path != "/":
                parts.append(f"dbname={parsed.path.lstrip('/')}")
            if parsed.username:
                parts.append(f"user={parsed.username}")
            if parsed.password:
                parts.append(f"password={parsed.password}")
            if self.database_ssl_mode != "disable":
                parts.append(f"sslmode={self.database_ssl_mode}")
            if self.database_ssl_ca_cert:
                parts.append(f"sslrootcert={self.database_ssl_ca_cert}")
            return " ".join(parts)
        return (
            f"host={self.postgres_host} port={self.postgres_port} "
            f"dbname={self.postgres_db} user={self.postgres_user} "
            f"password={self.postgres_password.get_secret_value()} "
            f"options='-c search_path={self.procrastinate_schema},public'"
        )

    @property
    def ogr_connection_string(self) -> str:
        if self.database_url_override:
            from urllib.parse import urlparse

            raw = self.database_url_override
            for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://"):
                if raw.startswith(prefix):
                    raw = raw.replace(prefix, "postgresql://", 1)
                    break
            if raw.startswith("postgres://"):
                raw = raw.replace("postgres://", "postgresql://", 1)
            parsed = urlparse(raw)
            parts = ["PG:"]
            if parsed.hostname:
                parts.append(f"host={parsed.hostname}")
            if parsed.port:
                parts.append(f"port={parsed.port}")
            if parsed.path and parsed.path != "/":
                parts.append(f"dbname={parsed.path.lstrip('/')}")
            if parsed.username:
                parts.append(f"user={parsed.username}")
            if parsed.password:
                parts.append(f"password={parsed.password}")
            if self.database_ssl_mode not in ("disable", "prefer"):
                parts.append(f"sslmode={self.database_ssl_mode}")
            return " ".join(parts)
        return (
            f"PG:host={self.postgres_host} "
            f"port={self.postgres_port} "
            f"dbname={self.postgres_db} "
            f"user={self.postgres_user} "
            f"password={self.postgres_password.get_secret_value()}"
        )

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT_ENV),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


def _create_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as e:
        missing = []
        value_errors = []
        for error in e.errors():
            if error["type"] == "missing":
                field_name = str(error["loc"][0])
                missing.append(field_name.upper())
            elif error["type"] == "value_error":
                value_errors.append(error["msg"])
        if missing:
            print(
                f"\nFATAL: Required environment variables not set: "
                f"{', '.join(sorted(missing))}\n"
                f"Copy .env.example to .env and fill in the required values.\n",
                file=sys.stderr,
            )
            sys.exit(1)
        if value_errors:
            for msg in value_errors:
                clean = msg.replace("Value error, ", "")
                print(f"\nFATAL: {clean}\n", file=sys.stderr)
            sys.exit(1)
        raise


settings = _create_settings()

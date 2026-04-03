import sys

from pydantic import ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    postgres_user: str = "geolens"
    postgres_password: str
    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_db: str = "geolens"
    postgres_db_test: str = "geolens_test"

    # Auth / JWT
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    geolens_admin_username: str
    geolens_admin_password: str
    registration_enabled: bool = False

    # CORS (comma-separated origins, empty = same-origin only)
    cors_allowed_origins: str = ""

    # Upload settings
    upload_max_size_mb: int = 500
    upload_staging_dir: str = "/app/staging"
    upload_allowed_extensions: str = (
        ".zip,.gpkg,.geojson,.json,.csv,.tif,.tiff,.xlsx,.xls"
    )

    # Multipart upload threshold in MB (files above this use multipart presigned URLs)
    presigned_multipart_threshold_mb: int = 100

    # Procrastinate (PG-based job queue)
    procrastinate_schema: str = "catalog"

    # Public URLs
    public_app_url: str | None = None
    public_api_url: str | None = None
    public_base_url: str | None = None  # Legacy alias for public_api_url

    # Logging
    log_json: bool = False
    log_level: str = "INFO"

    # AI map generation (optional — feature disabled when key is absent)
    anthropic_api_key: str | None = None
    llm_model: str = "claude-sonnet-4-20250514"

    # OpenAI-compatible provider (used when anthropic_api_key is not set)
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"
    openai_base_url: str | None = None  # For Groq, Together, Ollama, etc.

    # Embedding model (OpenAI-compatible API)
    embedding_model: str = "text-embedding-3-small"
    embedding_dims: int = 1536
    embedding_base_url: str | None = None  # Separate endpoint for embeddings

    # --- Infrastructure Provider Settings (v5.0) ---

    # Storage provider: "local" (default) or "s3" (S3-compatible)
    storage_provider: str = "local"
    s3_endpoint: str | None = None
    s3_bucket: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_region: str = "us-east-1"
    s3_allow_http: bool = False
    s3_addressing_style: str = "auto"

    # Cache provider: in-memory (default) or Redis/Valkey via URL
    redis_url: str | None = None

    # CDN origin URL for tile delivery
    cdn_base_url: str | None = None

    # Tile signing secret (falls back to jwt_secret_key if not set)
    tile_signing_secret: str | None = None

    # Tile cache TTL in seconds
    tile_cache_ttl: int = 300

    # Database override: full connection URL for managed PostgreSQL (RDS, Cloud SQL)
    database_url_override: str | None = None
    database_ssl_mode: str = "prefer"
    database_ssl_ca_cert: str | None = None
    database_pool_pre_ping: bool = True

    # External connection pooler (PgBouncer, RDS Proxy) -- disables prepared statements
    db_use_external_pooler: bool = False

    # Connection pool tuning (ignored when db_use_external_pooler is True)
    db_pool_size: int = 10
    db_max_overflow: int = 5
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800

    # Tile pool tuning (dedicated asyncpg pool for tile queries)
    tile_pool_min_size: int = 2
    tile_pool_max_size: int = 10

    # AWS Marketplace metering (container products)
    aws_marketplace_product_code: str | None = None
    aws_marketplace_public_key_version: int = 1

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
        "aws_marketplace_product_code",
        mode="before",
    )
    @classmethod
    def empty_str_to_none(cls, v: str | None) -> str | None:
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @model_validator(mode="after")
    def validate_provider_settings(self) -> "Settings":
        """Fail fast if provider is selected but required settings are missing."""
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

    @property
    def allowed_extensions_list(self) -> list[str]:
        return [ext.strip() for ext in self.upload_allowed_extensions.split(",")]

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS_ALLOWED_ORIGINS into a list of origin strings."""
        if not self.cors_allowed_origins:
            return []
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @staticmethod
    def _strip_ssl_from_url(url: str) -> str:
        """Remove sslmode param from URL -- asyncpg reads SSL from connect_args only."""
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
        """Async database URL. DATABASE_URL_OVERRIDE takes precedence."""
        if self.database_url_override:
            url = self.database_url_override
            # Ensure asyncpg driver prefix
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            elif url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+asyncpg://", 1)
            return self._strip_ssl_from_url(url)
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_connect_args(self) -> dict:
        """SSL + pooler connect_args for asyncpg."""
        import ssl

        args: dict = {}

        # SSL configuration
        if self.database_ssl_mode == "disable":
            pass
        elif self.database_ssl_mode in ("require", "verify-full"):
            ctx = ssl.create_default_context()
            if self.database_ssl_ca_cert:
                ctx.load_verify_locations(self.database_ssl_ca_cert)
            if self.database_ssl_mode == "require":
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            args["ssl"] = ctx
        else:
            # "prefer" — asyncpg will attempt SSL, fall back to plain
            args["ssl"] = "prefer"

        # External pooler: disable asyncpg prepared statement cache
        if self.db_use_external_pooler:
            args["statement_cache_size"] = 0

        return args

    @property
    def test_database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db_test}"
        )

    @property
    def database_url_sync(self) -> str:
        """Sync database URL for Alembic. DATABASE_URL_OVERRIDE takes precedence."""
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
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def test_database_url_sync(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db_test}"
        )

    @property
    def procrastinate_conninfo(self) -> str:
        """libpq-style connection string for Procrastinate's PsycopgConnector."""
        if self.database_url_override:
            from urllib.parse import urlparse

            # Normalize driver prefix to plain postgresql:// for urlparse
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
            f"password={self.postgres_password} "
            f"options='-c search_path={self.procrastinate_schema},public'"
        )

    @property
    def ogr_connection_string(self) -> str:
        """PG: format connection string for ogr2ogr."""
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
            f"password={self.postgres_password}"
        )

    model_config = {"env_file": ".env", "extra": "ignore"}


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
                # Strip "Value error, " prefix that pydantic adds
                clean = msg.replace("Value error, ", "")
                print(f"\nFATAL: {clean}\n", file=sys.stderr)
            sys.exit(1)
        raise


settings = _create_settings()

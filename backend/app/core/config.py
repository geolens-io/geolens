import sys
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def reveal(secret: SecretStr | None) -> str | None:
    """Unwrap an optional SecretStr to its raw value, or return None."""
    return secret.get_secret_value() if secret is not None else None


_PROJECT_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"

# Known-public credential literals that leaked through the project's git
# history. The values live in `git log` forever, so refuse them at boot — a
# deployment using these strings is trivially exploitable by anyone with read
# access to the repo.
KNOWN_BAD_JWT_SECRET = "demo-only-do-not-use-in-production-change-me"
KNOWN_BAD_ADMIN_PASSWORD = "demodemo"
KNOWN_BAD_POSTGRES_PASSWORD = "geolens-demo-2026"

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
    # FRONT-01 (Phase 1223): when True the root route redirects anonymous
    # visitors to the login page as the product landing surface.
    # Default False — self-hosters see zero change on upgrade.
    landing_first: bool = False
    # DEMO-03 (Phase 1226): when True, logged-in users see a persistent
    # "demo account" banner.  Default False — self-hosters see zero change.
    demo_mode: bool = False

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

    # SEC-005: explicit deployment environment. Controls security-sensitive
    # behaviors — API docs exposure (/docs, /redoc) and the Secure flag on the
    # OAuth session cookie (SessionMiddleware https_only). Previously these were
    # keyed off LOG_JSON, an innocuously-documented log-format flag.
    #   "production"  -> hardened posture (docs hidden, Secure cookie)
    #   "development" -> open posture (docs shown, no Secure cookie)
    #   unset (None)  -> fall back to LOG_JSON for backward compatibility
    # Set ENVIRONMENT=production on any public, TLS-terminated deployment.
    environment: Literal["development", "production"] | None = None

    # TSEAM-03 (Phase 1207-02): orthogonal tenancy MODE axis.
    # Edition stays binary (community|enterprise); mode controls the tenancy
    # posture of the deployment.
    #   "single_tenant" (default) -> Community/Enterprise byte-identical behavior;
    #                                tenant_id is NULL everywhere, no isolation.
    #   "multi_tenant"            -> Requires the cloud overlay + 1208 RLS layer;
    #                                boot guard (GUARD-01) fails loud without them.
    # An invalid value raises a Pydantic ValidationError at boot.
    geolens_tenancy_mode: Literal["single_tenant", "multi_tenant"] = "single_tenant"

    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-sonnet-4-20250514"

    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o"
    # Light model for SQL generation / metadata (cheaper, high-volume). When unset,
    # the light model defaults to openai_model so it always points at a model the
    # provider actually serves — important for Azure OpenAI / gateways where the
    # model name must match a real deployment (a hardcoded default 404s there).
    openai_model_light: str | None = None
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

    # Azure Blob Storage (STOR-01 / Phase 1210)
    azure_storage_container: str | None = None
    azure_storage_connection_string: SecretStr | None = (
        None  # for Azurite: "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;..."
    )
    azure_storage_account_url: str | None = (
        None  # for live: "https://<account>.blob.core.windows.net"
    )
    # CR-04 (Phase 1210): storage account access key for account_url + key auth.
    # When connection_string is absent and only account_url is provided,
    # AzureBlobStorageProvider needs an explicit key to authenticate (otherwise
    # BlobServiceClient(account_url=..., credential=None) falls through to Entra ID
    # which silently fails for most deployments). Set via AZURE_STORAGE_ACCOUNT_KEY.
    # Revealed only at the SDK boundary in init_storage(); never logged.
    azure_storage_account_key: SecretStr | None = None

    # IN-01 (Phase 1210): env-overridable Titiler base URL.  The module docstring
    # in titiler_url.py promised an env override but it was never wired up.
    # Default matches the Docker Compose service name; override via TITILER_BASE_URL
    # for non-compose deployments (e.g. bare-metal, alternative service names).
    titiler_base_url: str = "http://titiler:8000"

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

    # fix(R-02, video-reshoot 2026-07-09): finished ingest_jobs rows previously
    # lived forever, so the admin Jobs page accumulated stale test junk with no
    # cleanup affordance. Terminal jobs (complete/failed/cancelled/fanned_out)
    # older than this many days are purged by the 5-minute lifespan sweeper.
    # 0 disables the purge (keep history forever).
    ingest_jobs_retention_days: int = 30

    # ---------------------------------------------------------------------------
    # Outbound Notification channels (Phase 1229 NOTIF-02 / NOTIF-03 / NOTIF-05)
    # ---------------------------------------------------------------------------
    # All defaults are OFF / None so existing deployments are byte-identical on
    # upgrade (NOTIF-04). Secrets are SecretStr so they never render in logs or
    # repr(). Plan 02 channel implementations read these fields directly at
    # send time; Plan 03 reads bool(smtp_host) / bool(notification_webhook_url)
    # for a status GET. These are REAL wired fields — not inert knobs.
    #
    # NOT registered in persistent_config.py: notification secrets must NOT live
    # in the app_settings DB table (persistent_config.py:80-83 prohibition).
    # ---------------------------------------------------------------------------

    # Master toggle: when False (default), notify() is a fast no-op regardless
    # of whether SMTP / webhook env vars are set. Set NOTIFICATIONS_ENABLED=true
    # to activate channels.
    notifications_enabled: bool = False

    # SMTP channel (NOTIF-02): configure with SMTP_HOST + SMTP_USERNAME +
    # SMTP_PASSWORD + SMTP_FROM_ADDRESS to send email notifications.
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from_address: str | None = None
    smtp_use_tls: bool = True

    # Webhook channel (NOTIF-03): configure with NOTIFICATION_WEBHOOK_URL to POST
    # JSON notifications to a generic incoming-webhook endpoint (Slack, Teams,
    # custom). NOTIFICATION_WEBHOOK_SECRET is used for HMAC signing (optional).
    notification_webhook_url: str | None = None
    notification_webhook_secret: SecretStr | None = None

    # EVENT-05 per-event opt-in toggles (default OFF). Each toggle enables the
    # corresponding notification; the whole feature is still gated behind
    # notifications_enabled=True + at least one configured channel (SMTP or webhook).
    # Set e.g. NOTIFY_ON_SIGNUP=true to enable signup/lead-capture alerts.
    # NOT registered in persistent_config.py (these are env knobs, not DB settings).
    notify_on_signup: bool = False
    notify_on_ingest_complete: bool = False
    notify_on_ingest_failed: bool = False
    notify_on_health_alert: bool = False

    # Admin recipient for event notifications (non-secret — appears in Notification.data["to"]).
    # Falls back to smtp_from_address when not set (see events.py build_event_notification).
    # Add NOTIFICATION_ADMIN_EMAIL=admin@example.com to direct all event alerts to one address.
    notification_admin_email: str | None = None

    @field_validator(
        "anthropic_api_key",
        "openai_api_key",
        "openai_model_light",
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
        "azure_storage_container",
        "azure_storage_connection_string",
        "azure_storage_account_url",
        "azure_storage_account_key",
        # Phase 1229 notification str | None fields — blank env values normalize to None
        "smtp_host",
        "smtp_username",
        "smtp_from_address",
        "notification_webhook_url",
        # Phase 1230 EVENT-05 recipient field — blank env value normalizes to None
        "notification_admin_email",
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
        elif self.storage_provider == "azure":
            if not self.azure_storage_container:
                raise ValueError(
                    "STORAGE_PROVIDER=azure requires AZURE_STORAGE_CONTAINER"
                )
            if (
                not self.azure_storage_connection_string
                and not self.azure_storage_account_url
            ):
                raise ValueError(
                    "STORAGE_PROVIDER=azure requires either "
                    "AZURE_STORAGE_CONNECTION_STRING or AZURE_STORAGE_ACCOUNT_URL"
                )

        if self.database_ssl_mode == "verify-full" and not self.database_ssl_ca_cert:
            raise ValueError(
                "DATABASE_SSL_MODE=verify-full requires DATABASE_SSL_CA_CERT"
            )

        return self

    @model_validator(mode="after")
    def validate_known_bad_credentials(self) -> "Settings":
        jwt_value = self.jwt_secret_key.get_secret_value()
        admin_value = self.geolens_admin_password.get_secret_value()
        pg_value = self.postgres_password.get_secret_value()

        hint = " Generate a fresh value with `openssl rand -hex 32`."

        if jwt_value == KNOWN_BAD_JWT_SECRET:
            raise ValueError(
                "JWT_SECRET_KEY is set to a known-public literal from the "
                "project's git history. Anyone with repo read access can forge "
                "JWTs against this deployment." + hint
            )

        if admin_value == KNOWN_BAD_ADMIN_PASSWORD:
            raise ValueError(
                "GEOLENS_ADMIN_PASSWORD is set to a known-public literal "
                "('demodemo') from the project's git history." + hint
            )

        if pg_value == KNOWN_BAD_POSTGRES_PASSWORD:
            raise ValueError(
                "POSTGRES_PASSWORD is set to a known-public literal from the "
                "project's git history." + hint
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

    @property
    def is_production(self) -> bool:
        """Whether to enforce the production security posture (API docs hidden,
        Secure session cookie).

        SEC-005: driven by the explicit ENVIRONMENT setting. When ENVIRONMENT is
        unset, fall back to LOG_JSON (the de-facto production switch before this
        setting) so no existing deployment silently loses its hardened posture.
        An explicit ENVIRONMENT (development or production) decouples fully —
        LOG_JSON no longer affects security.
        """
        if self.environment is not None:
            return self.environment == "production"
        return self.log_json

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
        if self.database_ssl_mode == "disable":
            connect_args["ssl"] = False
        elif self.database_ssl_mode == "prefer":
            connect_args["ssl"] = "prefer"
        else:
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
        """Sync DSN for psycopg consumers (Alembic offline, helper scripts).

        Unlike the async sibling, this property does NOT strip ?sslmode= from
        the override URL: psycopg parses sslmode natively, while asyncpg gets
        SSL via connect_args["ssl"] and would conflict with a URL-borne flag.
        """
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
            from urllib.parse import parse_qs, urlparse

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
            # BUG-002: the non-override branch sets
            # options='-c search_path=<schema>,public' so procrastinate's
            # unqualified objects resolve in the catalog schema. The override
            # branch dropped it entirely, breaking the job queue on managed
            # Postgres (UndefinedTable/UndefinedFunction on every defer and
            # worker start). Re-add it, preserving any caller-supplied
            # ?options= — our search_path is applied last so it always wins.
            search_path_opt = f"-c search_path={self.procrastinate_schema},public"
            caller_options = parse_qs(parsed.query).get("options", [""])[0]
            combined_options = (
                f"{caller_options} {search_path_opt}".strip()
                if caller_options.strip()
                else search_path_opt
            )
            parts.append(f"options='{combined_options}'")
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

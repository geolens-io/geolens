import ipaddress
import sys
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import idna
from pydantic import (
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


def reveal(secret: SecretStr | None) -> str | None:
    """Unwrap an optional SecretStr to its raw value, or return None."""
    return secret.get_secret_value() if secret is not None else None


def libpq_ssl_parts(mode: str, ca_cert: str | None) -> list[str]:
    """Return the libpq TLS keyword/value pairs for one connection string.

    Shared so the override and component-field branches of both DSN builders
    cannot drift: a deployment that configures PostgreSQL through POSTGRES_HOST
    rather than DATABASE_URL_OVERRIDE gets the same TLS posture. `disable` and
    `prefer` emit nothing because libpq already defaults to prefer, and the CA
    is emitted only for verify-full (see ogr_connection_string).
    """
    parts: list[str] = []
    if mode not in ("disable", "prefer"):
        parts.append(f"sslmode={mode}")
    if mode == "verify-full" and ca_cert:
        parts.append(f"sslrootcert={libpq_value(ca_cert)}")
    return parts


def libpq_value(value: object) -> str:
    """Render one value for a libpq keyword/value connection string.

    libpq splits `keyword=value` pairs on whitespace, so a value containing a
    space — a CA path under a directory with one, a generated password — ends
    the pair early and produces a malformed DSN. The documented escape is to
    single-quote the value and backslash-escape any single quote or backslash
    inside it.

    Quoting is applied only when the value actually needs it. GDAL parses the
    remainder of a `PG:` string itself before handing it to libpq, so leaving
    ordinary values bare keeps the emitted DSN byte-identical to what every
    existing deployment already passes through that driver.
    """
    text = str(value)
    if text and not re.search(r"""[\s'\\]""", text):
        return text
    escaped = text.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def validate_privacy_url_shape(v: str) -> str:
    r"""PRIV-1: shape check for the login/register privacy-policy link.

    Security control, not a formatting nit: the value renders as an
    unauthenticated ``<a href>``, so a ``javascript:``/``data:``/
    scheme-relative value here is XSS. Does not reuse the admin settings'
    path-stripping ``_normalize_absolute_url`` -- a real policy page needs
    its query string/fragment, which pass through untouched here.

    Shared by three entry points that must agree on "safe": this module's
    env-value boot validator, the admin-write validator in
    ``app.modules.settings.schemas``, and the read-path defense in
    ``app.modules.settings.router_public`` (a value stored before this
    check existed must not reach the login page unvalidated). Lives here
    rather than ``app.core.public_urls`` to avoid a circular import through
    that module's ``settings`` singleton; the hostname check below is a
    self-contained allowlist rather than a call to its
    ``canonical_host_error``, which answers a near-identical question.

    Deliberately stricter than a browser everywhere below (fail-closed, not
    a gap): STD3 rules reject ``_`` and a leading/trailing hyphen (a
    browser's UTS46 call disables both checks). A percent-encoded host byte
    (``exa%6dple.com``) is refused outright, never decoded -- decoding
    first raises the same ``%2e``/``%00`` ambiguity ``is_usable_public_origin``
    already refuses elsewhere. A backslash in the authority is rejected via
    the userinfo check below (Python's ``urlsplit`` reads it as userinfo;
    a browser's WHATWG parser treats it as a path separator instead, but
    both reject it). Userinfo (``user:pass@``) anywhere is refused outright,
    never stripped and retried. Whitespace anywhere in the raw string is
    refused outright (a browser silently strips/re-encodes it instead). An
    IPvFuture literal (``[v1.foo]``) or a scoped/zoned IPv6 literal
    (``[fe80::1%eth0]``) is refused, though neither is a browser rejection.
    A non-canonical IPv4 spelling (``0x7f.1``, ``192.168.1``, or a
    fullwidth-digit equivalent) is refused -- only the exact canonical
    dotted-quad is accepted, since a form a browser silently rewrites on
    navigation would no longer match what was stored.
    """
    stripped = v.strip()
    # Whitespace anywhere (not just the ends `.strip()` removed) is a known
    # scheme-check bypass: WHATWG strips tabs/newlines and drops a bare
    # space from a host before tokenizing, so `urlsplit` reads the same
    # string differently than a browser does.
    if any(c.isspace() for c in stripped):
        raise ValueError("must not contain whitespace")
    try:
        parsed = urlsplit(stripped)
    except ValueError as exc:
        # CPython 3.13+ already raises here for some malformed bracketed
        # authorities (e.g. IPv4-in-brackets), but not every shape
        # `_is_valid_privacy_url_host` rejects -- an early-exit, not a
        # substitute for that check.
        raise ValueError(f"is not a valid URL ({exc})") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("must be an absolute http(s) URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("must not include embedded credentials")
    # A netloc can be non-empty and still have no real host, e.g. "https://:443/x"
    # (netloc ":443", hostname None) -- a link a browser cannot resolve.
    if not parsed.hostname:
        raise ValueError("must include a hostname")
    if not _is_valid_privacy_url_host(
        parsed.hostname, bracketed=parsed.netloc.startswith("[")
    ):
        raise ValueError("must have a valid DNS hostname or IP literal")
    # Accessing .port validates syntax and the 1-65535 range; a bad port
    # otherwise sits unparsed in netloc and passes silently.
    try:
        parsed.port
    except ValueError:
        raise ValueError("must not include a malformed port") from None
    return stripped


def _is_unscoped_ipv6_literal(hostname: str) -> bool:
    """A plain IPv6 literal with no ``%`` zone ID. Split out of
    ``_is_valid_privacy_url_host`` purely to keep that function's
    cyclomatic complexity under the repo's ruff limit; see its docstring
    for why a bracketed authority is restricted to this and nothing else.
    """
    if "%" in hostname:
        return False
    try:
        ipaddress.IPv6Address(hostname)
        return True
    except ValueError:
        return False


def _is_valid_privacy_url_host(hostname: str, *, bracketed: bool) -> bool:
    """Hostname validity = idna (UTS46) + our IP/numeric rules.

    ``bracketed`` records whether the URL wrote this host inside ``[...]``
    (``urlsplit().hostname`` strips brackets, so the caller must pass this
    separately via ``parsed.netloc.startswith("[")``). Per RFC 3986 a
    bracketed authority is always an IP literal, so it is accepted ONLY as
    a plain, unscoped ``ipaddress.IPv6Address`` (no ``%`` zone ID) --
    otherwise ``[v1.foo]`` (IPvFuture, no browser implements it),
    ``[1.2.3.4]`` (invalid IPv4-in-brackets), and ``[fe80::1%eth0]`` (a
    zone ID no browser resolves from stored config) would each be wrongly
    accepted by the checks below.

    An unbracketed literal that parses via ``ipaddress.ip_address`` is
    accepted outright. Everything else is UTS46-mapped to ASCII first via
    ``idna.encode(hostname, uts46=True, std3_rules=True)`` (idna is pinned
    in pyproject.toml for a CVE) -- the same order a browser's host parser
    uses. This one call replaces a former hand-rolled DNS-label regex,
    Unicode-label check, and punycode round-trip, and covers STD3
    restrictions, hyphen placement, the 63/253-char length limits (idna
    accepts 253, rejects 254, matching the length check kept below as a
    second line of defense), empty labels, and the disallowed/combining-mark
    set for both a raw Unicode label and an operator "xn--" label. It also
    performs the Unicode-to-ASCII mapping a browser applies before deciding
    whether a host "ends in a number" (e.g. fullwidth "１" maps to "1").

    On that MAPPED result (never the raw hostname -- a fullwidth digit
    passes ``str.isdigit()`` too but breaks ``ipaddress.IPv4Address``): if
    the last label is numeric or 0x-hex, a browser reads it as an attempted
    IPv4 address (WHATWG "ends in a number"), accepted only as the exact
    canonical dotted-quad -- "999.999.999.999" and "1.2.3.4.5" fail a
    browser's IPv4 parse outright, "192.168.1" silently becomes
    192.168.0.1 under a browser's legacy 3-part parser, so all three are
    rejected rather than treated as an ordinary DNS name. Checked with one
    trailing root dot already stripped, or "999.999.999.999." would skip
    this case and be accepted as an ordinary (nonsensical) DNS name.
    Everything else idna accepts is an ordinary DNS name.
    """
    if bracketed:
        return _is_unscoped_ipv6_literal(hostname)
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        pass
    # UTS46-map FIRST, THEN look for "ends in a number" -- a browser's own
    # order. Checking the raw hostname breaks two ways: an ideographic full
    # stop (U+3002) is not ASCII ".", so rsplit never splits it; and
    # str.isdigit() is true for fullwidth digits, which ipaddress.IPv4Address
    # then can't parse, rejecting a host a browser accepts as 127.0.0.1.
    try:
        ascii_host = idna.encode(hostname, uts46=True, std3_rules=True).decode("ascii")
    except idna.IDNAError:
        return False
    # A single trailing dot is the valid DNS root separator; idna.encode
    # leaves it in rather than raising, so strip it here before the
    # ends-in-a-number check. Two+ dots is an empty label, already refused
    # above by idna.encode.
    h = ascii_host.removesuffix(".")
    if not h:
        return False
    last = h.rsplit(".", 1)[-1]
    # ascii_host is lowercase and pure ASCII (idna's ToASCII + the
    # .decode("ascii") above), so a plain ASCII class is safe here --
    # str.isdigit() would also match non-ASCII digit code points. "0x"
    # with no hex digits after it still reads as "a number" to a browser.
    if re.fullmatch(r"[0-9]+|0x[0-9a-f]*", last):
        try:
            return str(ipaddress.IPv4Address(h)) == h
        except ValueError:
            return False
    # Second line of defense: idna.encode already enforces 253 (254 raises
    # "Domain too long"), but a future idna release relaxing that should
    # not silently loosen ours.
    return len(ascii_host) <= 253


_PROJECT_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"

# Known-public credential literals that leaked through the project's git
# history and live in `git log` forever; refuse them at boot (Rule 3) since
# any deployment using one is trivially exploitable by anyone who can read
# the repo.
KNOWN_BAD_JWT_SECRET = "demo-only-do-not-use-in-production-change-me"
KNOWN_BAD_ADMIN_PASSWORD = "demodemo"
KNOWN_BAD_POSTGRES_PASSWORD = "geolens-demo-2026"

# Phase 268 H-28: documentation-default values the JWT length validator would
# otherwise accept; rejected in all modes, no demo opt-in, since any of these
# on a real deployment lets an attacker forge tokens trivially.
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

# fix(#1871): every literal this repo treats as public knowledge, in one place,
# so a new secret-bearing setting refuses all of them rather than the subset
# whoever added it remembered (Rule 3).
KNOWN_PUBLIC_CREDENTIALS = frozenset(
    {KNOWN_BAD_JWT_SECRET, KNOWN_BAD_ADMIN_PASSWORD, KNOWN_BAD_POSTGRES_PASSWORD}
    | KNOWN_BAD_JWT_SECRETS
)

# fix(#1871): shown by every SECRET_ENCRYPTION_KEY* boot failure. A Fernet key
# is url-safe base64 of 32 random bytes, so `openssl rand -hex 32` (the hint on
# JWT_SECRET_KEY) does NOT produce one.
FERNET_KEY_HINT = (
    " Generate a fresh value with `openssl rand -base64 32 | tr '+/' '-_'`."
)

# fix(#1778): bcrypt's input limit, restated here since `core/` may not import
# `app.modules.*` (test_layering.py); canonical definition is beside the
# hasher in app/modules/auth/password_policy.py, pinned equal by test_password_policy.py.
BCRYPT_MAX_PASSWORD_BYTES = 72


# fix(#1235): shortest presigned-upload window worth issuing; must be this
# exact number since it's `pending_job_timeout_seconds`'s lower bound.
# Lives here, not by its consumer `require_signable_job_lifetime` in
# processing/ingest/presigned.py, because core must never import processing.
MIN_SIGNABLE_JOB_LIFETIME_SECONDS = 60

# fix(#1236): the SigV4 ceiling. No presigned URL can outlive `created_at`
# plus this many seconds, whatever `pending_job_timeout_seconds` was set to
# when it was signed; the post-expiry sweep in
# `_sweep_expired_presigned_staging` (platform/jobs/router.py) uses it as the
# age past which a marked-reaped row is safe to consider settled for good.
MAX_PRESIGNED_URL_LIFETIME_SECONDS = 604800


class Settings(BaseSettings):
    postgres_user: str = "geolens"
    postgres_password: SecretStr
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "geolens"
    postgres_db_test: str = "geolens_test"

    jwt_secret_key: SecretStr
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=15, gt=0)
    refresh_token_expire_days: int = Field(default=7, gt=0)
    # fix(#621): how long a just-rotated refresh token stays usable so
    # concurrent refreshes (multi-tab) don't strand the losers of the
    # rotation race. 0 restores instant single-use revocation.
    refresh_rotation_grace_seconds: int = Field(default=30, ge=0)

    # fix(#1871): Fernet key for secrets stored at rest (SSO client secrets,
    # SAML IdP certificates). Unset, they are encrypted under a key derived
    # from JWT_SECRET_KEY, so a JWT rotation makes every one of them unreadable.
    secret_encryption_key: SecretStr | None = None
    # The key it replaced. Read-only, until rotate_secrets.py has swept the rows.
    secret_encryption_key_previous: SecretStr | None = None

    # SEC-S16: password_require_classes counts how many of the four character
    # classes (lowercase, uppercase, digit, symbol) must be present.
    password_min_length: int = Field(default=12, ge=8)
    password_require_classes: int = Field(default=3, ge=1, le=4)
    geolens_admin_username: str
    geolens_admin_password: SecretStr
    registration_enabled: bool = False
    # FRONT-01 (Phase 1223): when True the root route redirects anonymous
    # visitors to the login page as the product landing surface.
    # Default False — self-hosters see zero change on upgrade.
    landing_first: bool = False
    # fix(#838): with ENV_ONLY_CONFIG=true the admin UI cannot store
    # overrides, so these env vars are the only way to show the banner.
    banner_enabled: bool = False
    banner_text: str = ""
    banner_color: str = "warning"

    cors_allowed_origins: str = ""
    upload_max_size_mb: int = Field(default=500, gt=0)
    upload_staging_dir: str = "/app/staging"
    # NOTE: this is a PersistentConfig default — deployments where an admin
    # has stored an override keep their stored list and must add new
    # extensions (e.g. .parquet) themselves in Admin → Storage.
    upload_allowed_extensions: str = (
        ".zip,.gpkg,.geojson,.json,.csv,.tif,.tiff,.xlsx,.xls,.parquet,.fgb,.kml,.kmz"
    )
    # fix(#1236): capped at S3's single-PUT hard limit (5GiB). The invariant
    # that actually matters is enforced in code, not config -- see the clamp
    # in `recheck_transfer_margin_seconds()` (platform/jobs/router.py).
    presigned_multipart_threshold_mb: int = Field(default=100, gt=0, le=5120)
    # fix(#1234): a presigned job is abandoned after this long, and its part
    # URLs must not outlive it. Lives here (not platform/jobs) because
    # platform/storage must read it too and platform/jobs already imports
    # platform/storage, so the reverse import would cycle.
    #
    # fix(#1235): bounded at MAX_PRESIGNED_URL_LIFETIME_SECONDS (the SigV4
    # ceiling) and floored above MIN_SIGNABLE_JOB_LIFETIME_SECONDS (where
    # `require_signable_job_lifetime` always refuses to sign) -- either
    # extreme boots clean but makes every upload fail. The floor only
    # guarantees no value is self-defeating by construction; a slow request
    # can still eat the remaining lifetime at any setting.
    #
    # Lowering it mid-flight is not a leak: issued URLs keep their old
    # lifetime, and the sweep's re-check pass (fix #1236,
    # `_sweep_expired_presigned_staging` in platform/jobs/router.py)
    # revisits anything reaped once MAX_PRESIGNED_URL_LIFETIME_SECONDS has
    # passed since creation -- the latest any such URL can still be live.
    pending_job_timeout_seconds: int = Field(
        default=3600,
        gt=MIN_SIGNABLE_JOB_LIFETIME_SECONDS,
        le=MAX_PRESIGNED_URL_LIFETIME_SECONDS,
    )
    procrastinate_schema: str = "catalog"

    public_app_url: str | None = None
    public_api_url: str | None = None
    public_base_url: str | None = None
    # PRIV-1: privacy-policy link shown on the login/register pages. Unset by
    # default so a self-hosted instance never links to another operator's
    # privacy page; set this to the operator's own policy URL to show the link.
    privacy_url: str | None = None
    # Multi-tenant Host routing is accepted only below this explicit DNS
    # suffix (for example ``geolens.example``). Exact non-tenant service hosts
    # are separately allowlisted for health checks, Compose, and test clients.
    tenant_base_domain: str | None = None
    tenant_trusted_hosts: str = "localhost,127.0.0.1,::1,api,testserver"
    # Public, monitored organization mailbox used as the DCAT-US contactPoint
    # fallback when a published record has no usable record-level contact.
    dcat_contact_email: str | None = None

    log_json: bool = False
    log_level: str = "INFO"

    # SEC-005: explicit deployment environment, controlling API docs exposure
    # (/docs, /redoc), the Secure flag on the OAuth session cookie
    # (SessionMiddleware https_only), and, fix(#1485), plain traceback
    # rendering (rich's frame-locals tables made one exception a
    # multi-minute event-loop stall). Unset falls back to LOG_JSON. Set
    # ENVIRONMENT=production on any public, TLS-terminated deployment.
    environment: Literal["development", "production"] | None = None

    # Explicit edition request. None preserves extension auto-detection, while
    # invalid values fail during Settings construction instead of silently
    # falling back to community behavior.
    geolens_edition: Literal["community", "enterprise"] | None = None

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
    llm_model: str = "claude-sonnet-5"

    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o"
    # Light model for SQL generation / metadata. Unset defaults to openai_model
    # so it always points at a model the provider actually serves -- for Azure
    # OpenAI / gateways a hardcoded default 404s if it doesn't match a real
    # deployment name.
    openai_model_light: str | None = None
    openai_base_url: str | None = None

    embedding_model: str = "text-embedding-3-small"
    embedding_dims: int = Field(default=1536, ge=1, le=4096)
    embedding_base_url: str | None = None

    storage_provider: Literal["local", "s3", "azure"] = "local"
    s3_endpoint: str | None = None
    s3_bucket: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_region: str = "us-east-1"
    s3_allow_http: bool = False
    s3_addressing_style: Literal["auto", "path", "virtual"] = "auto"

    # Ambient AWS credential markers, injected by the runtime not an operator:
    # EKS IRSA/Pod Identity set AWS_ROLE_ARN + AWS_WEB_IDENTITY_TOKEN_FILE;
    # ECS/EKS container providers set one of the AWS_CONTAINER_CREDENTIALS_*
    # pair. Fields (not os.environ) per CONF-03/CONF-04; read only by
    # has_ambient_aws_credentials below -- boto3/GDAL resolve credentials themselves.
    aws_role_arn: str | None = None
    aws_web_identity_token_file: str | None = None
    aws_container_credentials_full_uri: str | None = None
    aws_container_credentials_relative_uri: str | None = None

    # Azure Blob Storage (STOR-01 / Phase 1210)
    azure_storage_container: str | None = None
    azure_storage_connection_string: SecretStr | None = (
        None  # for Azurite: "DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;..."
    )
    azure_storage_account_url: str | None = (
        None  # for live: "https://<account>.blob.core.windows.net"
    )
    # CR-04: when connection_string is absent and only account_url is given,
    # AzureBlobStorageProvider needs this key to authenticate --
    # BlobServiceClient(account_url=..., credential=None) otherwise falls
    # through to Entra ID, which silently fails for most deployments.
    # Revealed only at the SDK boundary in init_storage(); never logged.
    azure_storage_account_key: SecretStr | None = None

    # IN-01: env-overridable Titiler base URL, matching the Docker Compose
    # service name by default; override via TITILER_BASE_URL for bare-metal
    # or alternative service names.
    titiler_base_url: str = "http://titiler:8000"

    redis_url: str | None = None
    cdn_base_url: str | None = None
    tile_signing_secret: SecretStr | None = None
    tile_cache_ttl: int = Field(default=300, ge=0)

    database_url_override: str | None = None
    # Opt-in single-tenant runtime login. Empty preserves the legacy connection;
    # when set, bootstrap verifies this exact live session role is unprivileged.
    geolens_runtime_db_role: str | None = None
    # Object owner used by the ordered migrate service. The role reconciler
    # targets this identity's default privileges when it differs from the
    # provider/bundled reconciliation admin.
    geolens_migration_db_role: str | None = None
    # Dedicated, read-only tile login. In multi-tenant deployments this login
    # is a SET-only member of geolens_tile_gateway, never the API/worker role.
    tile_database_url_override: str | None = None
    database_ssl_mode: Literal["disable", "prefer", "require", "verify-full"] = "prefer"
    database_ssl_ca_cert: str | None = None
    database_pool_pre_ping: bool = True

    # CONF-03 (Phase 277 / M-38): replaces raw os.environ.get("WORKER_SHUTDOWN_TIMEOUT") in worker.py
    worker_shutdown_timeout: int = Field(default=30, gt=0)

    # fix(#448): Procrastinate parallel job slots per worker process. A
    # default of 1 head-of-line-blocks every queued upload behind a long COG
    # conversion; 2-3 suits multi-core hosts, keep 1 on 2-vCPU boxes.
    worker_concurrency: int = Field(default=1, ge=1)
    # fix(#448): queues this worker listens to, so a deployment can run a
    # second worker dedicated to e.g. WORKER_QUEUES=raster so long raster
    # jobs never stall vector ingests. fix(#1812): "ingest-auth-v2" is
    # consumer-only -- nothing enqueues there; drop the name once drained.
    worker_queues: str = "priority,ingest,raster,ingest-auth-v2"

    # CONF-04 (Phase 277 / M-39): replaces raw os.environ.get("ENV_ONLY_CONFIG") in core/public_urls.py
    # Security-relevant: when true, the PersistentConfig DB layer is bypassed for reads
    # and writes return 403. Keep in sync with .env.example.
    env_only_config: bool = False

    db_use_external_pooler: bool = False
    db_pool_size: int = Field(default=10, ge=1)
    # SQLAlchemy uses -1 for unlimited overflow / disabled recycling.
    db_max_overflow: int = Field(default=3, ge=-1)
    db_pool_timeout: int = Field(default=30, gt=0)
    db_pool_recycle: int = Field(default=1800, ge=-1)

    tile_pool_min_size: int = Field(default=2, ge=1)
    tile_pool_max_size: int = Field(default=10, ge=1)

    # SEED-02 (Phase 1054): GDAL_HTTP_TIMEOUT for ogr2ogr service ingest, raised
    # from the 120s hardcoded default that timed out 50% of AGO layers in M001-7n8vpc.
    # Set INGEST_HTTP_TIMEOUT_SECONDS in the api service env to override.
    ingest_http_timeout_seconds: int = Field(default=300, gt=0)

    # fix(#1013): the materialize CTAS budget, applied as SET LOCAL
    # statement_timeout before the CREATE TABLE AS. 300 seconds covers
    # roughly 150k-600k buffered polygon rows, so a one-million-parcel
    # buffer fails.
    #
    # gt=0 is load-bearing: PostgreSQL reads statement_timeout='0' as no
    # timeout, so 0 here would silently produce the unbounded statement the
    # budget exists to prevent -- rejected at boot instead.
    #
    # Without an admission gate a longer budget just holds the job slot
    # longer; the work still runs, it fails later. Pairs with #691's
    # heartbeat lease and #701's pre-flight gates. One scalar for all
    # operations (a centroid needs seconds, a dissolve far more) is a
    # deliberate compromise; per-operation budgets are the natural follow-up.
    analysis_materialize_timeout_seconds: int = Field(default=300, gt=0)

    # fix(#1013): promoted alongside the CTAS budget -- the commit that makes
    # the output durable ends the transaction (and its SET LOCAL) with it, so
    # registration needs its own budget (#692) for the full-scan metadata
    # extraction. Raising the CTAS ceiling for a large dataset needs this
    # raised too.
    analysis_registration_timeout_seconds: int = Field(default=600, gt=0)

    # fix(#1012): per-slot work_mem budget for the materialize CTAS, in MB.
    # Configurable because the safe value depends on two things this process
    # cannot see: DB_MEM_LIMIT (a compose `mem_limit`, never passed into the
    # api/worker env, and operator-tunable -- prod compose documents 1.5g, an
    # external PostgreSQL may be smaller) and how many worker replicas run
    # against the `ingest` queue, since each would claim the budget
    # independently.
    #
    # The default is conservative, not optimal: work_mem is per operation AND
    # per backend, so one materialize can allocate this value times the
    # memory-hungry plan nodes (at most 2 for these shapes) times the backends
    # running it (2, since max_parallel_workers_per_gather is 1). At 64MB
    # that's 256MB per replica, so two replicas stay inside the default 2GB
    # alongside shared_buffers (512MB) and maintenance_work_mem (128MB).
    # Raise it only with checked headroom (a larger DB_MEM_LIMIT or a single
    # worker service); lower it for a smaller DB container or more replicas.
    #
    # 0 disables the override (no SET LOCAL; pre-#1012 behaviour), since this
    # process cannot read the connected cluster's work_mem and so cannot know
    # whether a floor would preserve it or quietly raise it. Positive values
    # are applied as given.
    analysis_materialize_work_mem_mb: int = Field(default=64, ge=0)

    # fix(#434): terminal jobs (complete/failed/cancelled/fanned_out) older
    # than this many days are purged by the 5-minute lifespan sweeper, except
    # each dataset's most recent complete job (backs /jobs/by-dataset
    # warning metadata). 0 disables the purge (keep history forever).
    ingest_jobs_retention_days: int = Field(default=30, ge=0)

    # fix(#1778): statement deadline for the API, in seconds; 0 disables it.
    # Applied to every transaction the API process opens (handlers open
    # request-scoped sessions directly in 20+ modules, not just get_db), as
    # SET LOCAL never a startup parameter so DB_USE_EXTERNAL_POOLER=true
    # still connects. The worker is excluded; see app/core/statement_timeout.py.
    # 300 sits inside the edge proxy's 600s read timeout, so a query that
    # would trip it has already lost its client.
    db_statement_timeout_seconds: int = Field(default=300, ge=0)

    # fix(#1249): how old an object under the `staging/` prefix must be
    # before the reconciliation sweep deletes it for having no ingest_jobs
    # row. Not a guess at upload duration -- the row check decides
    # ownership, so this only needs to outlast a LISTING racing the row's
    # own write. Floored at an hour so misconfiguration can't turn the
    # sweep into a deleter of objects still landing. Consumer:
    # `reconcile_orphaned_staging_objects` in platform/jobs/staging_reconcile.py.
    staging_orphan_min_age_seconds: int = Field(default=86400, ge=3600)

    # Outbound Notification channels (NOTIF-02/03/05). All defaults are
    # OFF/None so existing deployments are byte-identical on upgrade
    # (NOTIF-04). Secrets are SecretStr so they never render in logs/repr().
    # These are real wired fields, not inert knobs.
    #
    # NOT registered in persistent_config.py: notification secrets must NOT live
    # in the app_settings DB table (persistent_config.py:80-83 prohibition).

    # Master toggle: when False (default), notify() is a fast no-op regardless
    # of whether SMTP / webhook env vars are set. Set NOTIFICATIONS_ENABLED=true
    # to activate channels.
    notifications_enabled: bool = False

    # SMTP channel (NOTIF-02): configure with SMTP_HOST + SMTP_USERNAME +
    # SMTP_PASSWORD + SMTP_FROM_ADDRESS to send email notifications.
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from_address: str | None = None
    smtp_use_tls: bool = True

    # Webhook channel (NOTIF-03): configure with NOTIFICATION_WEBHOOK_URL to POST
    # JSON notifications to a generic incoming-webhook endpoint (Slack, Teams,
    # custom). NOTIFICATION_WEBHOOK_SECRET is used for HMAC signing (optional).
    notification_webhook_url: str | None = None
    notification_webhook_secret: SecretStr | None = None

    # EVENT-05 per-event opt-in toggles (default OFF), still gated behind
    # notifications_enabled=True + at least one configured channel. Not
    # registered in persistent_config.py -- env knobs, not DB settings.
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
        "privacy_url",
        "tenant_base_domain",
        "dcat_contact_email",
        "database_url_override",
        "geolens_runtime_db_role",
        "geolens_migration_db_role",
        "tile_database_url_override",
        "s3_endpoint",
        "s3_bucket",
        "s3_access_key_id",
        "s3_secret_access_key",
        "s3_addressing_style",
        "database_ssl_ca_cert",
        "tile_signing_secret",
        # fix(#1871): an uncommented-but-empty .env line arrives as "", which
        # would otherwise reach validate_known_bad_credentials' Fernet check
        # and fail boot on a config shape that means "not set" (INST-01 class).
        "secret_encryption_key",
        "secret_encryption_key_previous",
        "azure_storage_container",
        "azure_storage_connection_string",
        "azure_storage_account_url",
        "azure_storage_account_key",
        # Phase 1229 notification str | None fields — blank env values normalize to None
        "smtp_host",
        "smtp_username",
        "smtp_password",
        "smtp_from_address",
        "notification_webhook_url",
        "notification_webhook_secret",
        # Phase 1230 EVENT-05 recipient field — blank env value normalizes to None
        "notification_admin_email",
        # fix(#441): compose passes ENVIRONMENT through as "${ENVIRONMENT:-}",
        # so an unset value arrives as "" — normalize to None (LOG_JSON fallback)
        # instead of failing the Literal validation at boot.
        "environment",
        mode="before",
    )
    @classmethod
    def empty_str_to_none(cls, v: str | None) -> str | None:
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

    @field_validator("tenant_base_domain", mode="after")
    @classmethod
    def validate_tenant_base_domain(cls, v: str | None) -> str | None:
        """Normalize a host-only base suffix; schemes, ports and wildcards fail."""
        if v is None:
            return None
        value = v.strip().lower().rstrip(".")
        labels = value.split(".")
        host_label = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
        if (
            not value
            or "://" in value
            or ":" in value
            or "/" in value
            or "*" in value
            or any(host_label.fullmatch(label) is None for label in labels)
        ):
            raise ValueError(
                "TENANT_BASE_DOMAIN must be a host-only DNS suffix such as "
                "geolens.example (no scheme, port, path, or wildcard)"
            )
        return value

    @field_validator("tenant_trusted_hosts", mode="after")
    @classmethod
    def validate_tenant_trusted_hosts(cls, v: str) -> str:
        """Validate the comma-separated exact-host allowlist."""
        import ipaddress

        normalized: list[str] = []
        host_label = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$")
        for raw_host in v.split(","):
            host = raw_host.strip().lower().rstrip(".")
            if not host:
                continue
            try:
                ipaddress.ip_address(host)
            except ValueError:
                if (
                    "://" in host
                    or ":" in host
                    or "/" in host
                    or "*" in host
                    or host_label.fullmatch(host) is None
                    or ".." in host
                ):
                    raise ValueError(
                        "TENANT_TRUSTED_HOSTS accepts exact hostnames/IPs only"
                    ) from None
            normalized.append(host)
        return ",".join(dict.fromkeys(normalized))

    @field_validator("embedding_dims", mode="before")
    @classmethod
    def empty_embedding_dims_to_default(cls, v: object) -> object:
        # fix(#512): the one-shot migrate service deliberately preserves an
        # unset host value as "" so migration 0012 can distinguish it from an
        # explicitly configured 1536. Settings is imported before the revision,
        # so normalize only the application-facing value to its existing default.
        if isinstance(v, str) and not v.strip():
            return 1536
        return v

    @field_validator("geolens_edition", mode="before")
    @classmethod
    def normalize_geolens_edition(cls, v: str | None) -> str | None:
        if not isinstance(v, str):
            return v
        value = v.strip().lower()
        return value or None

    @field_validator("database_url_override", mode="after")
    @classmethod
    def validate_database_url_override(cls, v: str | None) -> str | None:
        if v is None:
            return None

        from urllib.parse import parse_qs, urlsplit

        value = v.strip()
        try:
            parsed = urlsplit(value)
            # Accessing .port validates both syntax and the 1-65535 range.
            parsed.port
        except ValueError:
            raise ValueError("DATABASE_URL_OVERRIDE contains an invalid port") from None

        allowed_schemes = {
            "postgres",
            "postgresql",
            "postgresql+asyncpg",
            "postgresql+psycopg",
        }
        if parsed.scheme not in allowed_schemes:
            raise ValueError(
                "DATABASE_URL_OVERRIDE must use a supported PostgreSQL scheme"
            )
        if not parsed.path or parsed.path == "/":
            raise ValueError("DATABASE_URL_OVERRIDE must include a database name")

        # fix(#1770): DATABASE_URL_OVERRIDE is an operator-supplied BOOT-TIME
        # env var, never a runtime service-advertised value -- see
        # `bounded_parse_qsl`'s docstring (`platform/service_endpoints.py`)
        # for the sites that DO need the field-count bound.
        query_hosts = parse_qs(  # parse_qs: unbounded
            parsed.query, keep_blank_values=True
        ).get("host", [])
        if parsed.hostname and query_hosts:
            raise ValueError(
                "DATABASE_URL_OVERRIDE must not combine authority and query hosts"
            )
        hosts = [parsed.hostname] if parsed.hostname else query_hosts
        if len(hosts) != 1 or not hosts[0] or "," in hosts[0]:
            raise ValueError("DATABASE_URL_OVERRIDE must contain exactly one host")
        return value

    @field_validator("privacy_url", mode="after")
    @classmethod
    def validate_privacy_url_env(cls, v: str | None) -> str | None:
        """PRIV-1: fail boot on an unsafe PRIVACY_URL rather than silently
        rendering it as an <a href> on the login/register page. This is the
        ONLY validation an ENV_ONLY_CONFIG deployment ever runs for this
        value — the admin-write validator in modules/settings/schemas.py
        never sees it in that mode. See validate_privacy_url_shape above for
        what "unsafe" means.
        """
        if v is None:
            return None
        try:
            return validate_privacy_url_shape(v)
        except ValueError as exc:
            raise ValueError(f"PRIVACY_URL {exc}") from exc

    @field_validator("geolens_runtime_db_role", mode="after")
    @classmethod
    def validate_runtime_db_role_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", v):
            raise ValueError(
                "GEOLENS_RUNTIME_DB_ROLE must be a lowercase PostgreSQL identifier"
            )
        return v

    @field_validator("geolens_migration_db_role", mode="after")
    @classmethod
    def validate_migration_db_role_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", v):
            raise ValueError(
                "GEOLENS_MIGRATION_DB_ROLE must be a lowercase PostgreSQL identifier"
            )
        return v

    @field_validator("dcat_contact_email", mode="after")
    @classmethod
    def validate_dcat_contact_email(cls, v: str | None) -> str | None:
        if v is None:
            return None
        value = v.strip()
        if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value) is None:
            raise ValueError(
                "DCAT_CONTACT_EMAIL must be a monitored email address "
                "such as metadata@example.gov"
            )
        return value

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

    @field_validator("worker_queues", mode="after")
    @classmethod
    def validate_worker_queues(cls, v: str) -> str:
        queues = [queue.strip() for queue in v.split(",") if queue.strip()]
        if not queues:
            raise ValueError("WORKER_QUEUES must contain at least one queue name")
        if len(queues) != len(set(queues)):
            raise ValueError("WORKER_QUEUES must not contain duplicate queue names")
        return ",".join(queues)

    @model_validator(mode="after")
    def validate_materialize_work_mem_budget(self) -> "Settings":
        """fix(#1012): refuse a budget that cannot be divided into legal shares.

        The budget is split across WORKER_CONCURRENCY slots. If a share falls
        below PostgreSQL's 64kB minimum for work_mem there is no honest
        outcome at run time: issuing the minimum exceeds the budget, and
        skipping the override leaves the cluster's own work_mem — usually
        LARGER — in force for every slot, which overshoots by more still. A
        1MB budget across 32 slots wants 32kB each; falling back to a bundled
        8MB default would expose 256MB. Neither is what the operator asked
        for, so the configuration is rejected at boot instead.
        """
        budget_kb = self.analysis_materialize_work_mem_mb * 1024
        if budget_kb <= 0:
            return self
        per_slot_kb = budget_kb // max(1, self.worker_concurrency)
        # PostgreSQL's own ceiling for work_mem. A share above it fails at
        # SET LOCAL, so every materialize would be recorded as a failed job —
        # a boot failure names the cause once instead.
        if per_slot_kb > 2147483647:
            raise ValueError(
                f"ANALYSIS_MATERIALIZE_WORK_MEM_MB="
                f"{self.analysis_materialize_work_mem_mb} divided across "
                f"WORKER_CONCURRENCY={self.worker_concurrency} is "
                f"{per_slot_kb}kB per slot, above PostgreSQL's work_mem maximum "
                "of 2147483647kB."
            )
        if per_slot_kb < 64:
            raise ValueError(
                f"ANALYSIS_MATERIALIZE_WORK_MEM_MB="
                f"{self.analysis_materialize_work_mem_mb} divided across "
                f"WORKER_CONCURRENCY={self.worker_concurrency} is "
                f"{per_slot_kb}kB per slot, below PostgreSQL's 64kB minimum "
                "for work_mem. Raise the budget, lower WORKER_CONCURRENCY, or "
                "set ANALYSIS_MATERIALIZE_WORK_MEM_MB=0 to leave work_mem at "
                "the cluster's own value."
            )
        return self

    @model_validator(mode="after")
    def validate_single_tenant_runtime_db_role(self) -> "Settings":
        """Keep the opt-in role exact and separate from the migrator login."""
        if self.geolens_runtime_db_role is None:
            return self
        if self.geolens_tenancy_mode != "single_tenant":
            raise ValueError(
                "GEOLENS_RUNTIME_DB_ROLE is the single-tenant role path; "
                "multi-tenant deployments must use the tenant role topology"
            )
        if self.database_url_override is None:
            raise ValueError(
                "GEOLENS_RUNTIME_DB_ROLE requires DATABASE_URL_OVERRIDE for the "
                "dedicated runtime credential"
            )

        from urllib.parse import unquote, urlsplit

        parsed_runtime_url = urlsplit(self.database_url_override)
        configured_user = unquote(parsed_runtime_url.username or "")
        if configured_user != self.geolens_runtime_db_role:
            raise ValueError(
                "DATABASE_URL_OVERRIDE username must match GEOLENS_RUNTIME_DB_ROLE"
            )
        runtime_password = self.postgres_password.get_secret_value()
        if len(runtime_password) < 32:
            raise ValueError(
                "GEOLENS_RUNTIME_DB_ROLE requires a POSTGRES_PASSWORD of at least "
                "32 characters"
            )
        if unquote(parsed_runtime_url.password or "") != runtime_password:
            raise ValueError(
                "DATABASE_URL_OVERRIDE password must match the runtime "
                "POSTGRES_PASSWORD"
            )
        return self

    @model_validator(mode="after")
    def validate_migration_database_role(self) -> "Settings":
        """Tie default-privilege ownership to the migration connection login."""
        if self.geolens_migration_db_role is None:
            return self

        from urllib.parse import unquote, urlsplit

        configured_user = self.postgres_user
        if self.database_url_override is not None:
            parsed_migration_url = urlsplit(self.database_url_override)
            configured_user = unquote(parsed_migration_url.username or "")
        if configured_user != self.geolens_migration_db_role:
            raise ValueError(
                "GEOLENS_MIGRATION_DB_ROLE username must match the migration "
                "database connection username"
            )
        return self

    @property
    def has_ambient_aws_credentials(self) -> bool:
        """True when the runtime supplies AWS credentials the SDKs resolve alone.

        Covers EKS IRSA / Pod Identity (web-identity token) and the ECS/EKS
        container credential providers. EC2 instance profiles are deliberately
        NOT probed: detecting one needs an IMDS round trip during settings
        construction, and a node role broad enough to reach the bucket is not a
        posture to boot silently into — set the keys, or use IRSA.
        """
        return bool(
            (self.aws_role_arn and self.aws_web_identity_token_file)
            or self.aws_container_credentials_full_uri
            or self.aws_container_credentials_relative_uri
        )

    @model_validator(mode="after")
    def validate_provider_settings(self) -> "Settings":
        if self.storage_provider == "s3":
            missing: list[str] = []
            if not self.s3_bucket:
                missing.append("S3_BUCKET")
            # A static key pair is one of two supported credential sources; the
            # other is ambient (IRSA/Pod Identity/container credentials),
            # which S3StorageProvider and derive_gdal_s3_env already support
            # by omitting explicit key args and leaving boto3/GDAL to resolve
            # the role themselves. A HALF-configured pair stays an error under
            # either source -- it is always a mistake.
            if not self.s3_access_key_id and not self.s3_secret_access_key:
                if not self.has_ambient_aws_credentials:
                    missing.append("S3_ACCESS_KEY_ID")
                    missing.append("S3_SECRET_ACCESS_KEY")
            elif not self.s3_access_key_id:
                missing.append("S3_ACCESS_KEY_ID")
            elif not self.s3_secret_access_key:
                missing.append("S3_SECRET_ACCESS_KEY")
            if missing:
                raise ValueError(
                    "STORAGE_PROVIDER=s3 requires: "
                    + ", ".join(missing)
                    + " (or ambient AWS credentials: on EKS, annotate the "
                    "ServiceAccount with eks.amazonaws.com/role-arn and leave "
                    "both keys unset)"
                )
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

        if self.tile_pool_min_size > self.tile_pool_max_size:
            raise ValueError(
                "TILE_POOL_MIN_SIZE must be less than or equal to TILE_POOL_MAX_SIZE"
            )

        return self

    @model_validator(mode="after")
    def validate_admin_credentials_nonempty(self) -> "Settings":
        # fix(#668): .env.example ships these keys empty and compose passes
        # "" straight through, so without this guard a verbatim-template
        # install silently seeds the initial admin with empty credentials.
        if not self.geolens_admin_username.strip():
            raise ValueError(
                "GEOLENS_ADMIN_USERNAME must not be empty. The initial "
                "admin user is seeded from it on first startup; set a "
                "username (e.g. admin) in your .env."
            )
        if not self.geolens_admin_password.get_secret_value().strip():
            raise ValueError(
                "GEOLENS_ADMIN_PASSWORD must not be empty. Generate one "
                "with `openssl rand -base64 16` and set it in your .env."
            )
        # fix(#1778): bound it at boot, where the message can name the
        # variable. seed_initial_admin() hashes this with bcrypt, which
        # refuses input over 72 bytes, and nothing upstream validates it --
        # an unbounded value produced a bare bcrypt ValueError inside a
        # restart-looping container instead.
        admin_password_bytes = len(
            self.geolens_admin_password.get_secret_value().encode("utf-8")
        )
        if admin_password_bytes > BCRYPT_MAX_PASSWORD_BYTES:
            raise ValueError(
                f"GEOLENS_ADMIN_PASSWORD is {admin_password_bytes} bytes when "
                f"encoded as UTF-8; the password hash accepts at most "
                f"{BCRYPT_MAX_PASSWORD_BYTES}. Generate a shorter value with "
                "`openssl rand -base64 16` and set it in your .env."
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

        # fix(#1871): fail here, not at the first SSO login. A bad value in
        # either key is only noticed when someone tries to sign in, and by then
        # the failure looks like a broken identity provider.
        from cryptography.fernet import Fernet

        for name, configured in (
            ("SECRET_ENCRYPTION_KEY", self.secret_encryption_key),
            ("SECRET_ENCRYPTION_KEY_PREVIOUS", self.secret_encryption_key_previous),
        ):
            if configured is None:
                continue
            raw = configured.get_secret_value()
            if raw in KNOWN_PUBLIC_CREDENTIALS:
                raise ValueError(
                    f"{name} is set to a known-public literal from the "
                    "project's git history." + FERNET_KEY_HINT
                )
            if raw == jwt_value:
                raise ValueError(
                    f"{name} must not be the same value as JWT_SECRET_KEY. "
                    "Sharing it restores the coupling this setting exists to "
                    "remove: rotating the JWT secret would again make every "
                    "stored SSO secret undecryptable." + FERNET_KEY_HINT
                )
            try:
                Fernet(raw.encode())
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    f"{name} is not a valid Fernet key. It must be url-safe "
                    "base64 of 32 random bytes." + FERNET_KEY_HINT
                ) from exc

        if self.secret_encryption_key is None and (
            self.secret_encryption_key_previous is not None
        ):
            raise ValueError(
                "SECRET_ENCRYPTION_KEY_PREVIOUS is set without "
                "SECRET_ENCRYPTION_KEY. The previous key is only ever read "
                "from; leaving it alone as the newest key would encrypt every "
                "later write under the key you are retiring. Promote it to "
                "SECRET_ENCRYPTION_KEY, or unset it."
            )

        if (
            self.secret_encryption_key is not None
            and self.secret_encryption_key_previous is not None
            and self.secret_encryption_key.get_secret_value()
            == self.secret_encryption_key_previous.get_secret_value()
        ):
            raise ValueError(
                "SECRET_ENCRYPTION_KEY_PREVIOUS is the same value as "
                "SECRET_ENCRYPTION_KEY, so nothing is being rotated. The key "
                "chain would hold one key twice, and rotate_secrets.py would "
                "report every row rewritten under the key they already use "
                "and then tell you to retire that key. Set the previous key "
                "to the one you are actually retiring, or unset it."
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
    def tenant_trusted_hosts_list(self) -> list[str]:
        """Exact non-tenant hosts accepted by the tenant middleware."""
        return [host for host in self.tenant_trusted_hosts.split(",") if host]

    @property
    def is_production(self) -> bool:
        """Whether to enforce the production posture (API docs hidden, Secure
        session cookie, plain tracebacks).

        SEC-005: driven by the explicit ENVIRONMENT setting; when unset, falls
        back to LOG_JSON so no existing deployment silently loses its
        hardened posture. An explicit ENVIRONMENT decouples fully.
        """
        if self.environment is not None:
            return self.environment == "production"
        return self.log_json

    @staticmethod
    def _strip_ssl_from_url(url: str) -> str:
        from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

        parts = urlsplit(url)
        # fix(#1770): same reasoning as `database_url_override`'s validator
        # above -- operator-supplied boot-time config.
        params = parse_qs(parts.query, keep_blank_values=True)  # parse_qs: unbounded
        params.pop("sslmode", None)
        new_query = urlencode(params, doseq=True)
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, new_query, parts.fragment)
        )

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            url = self.database_url_override
            if url.startswith("postgresql+psycopg://"):
                url = url.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
            elif url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            elif url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+asyncpg://", 1)
            return self._strip_ssl_from_url(url)
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password.get_secret_value()}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def tile_database_url(self) -> str:
        """Async DSN for the isolated tile pool, falling back for compatibility."""
        if self.tile_database_url_override:
            url = self.tile_database_url_override
            if url.startswith("postgresql://"):
                url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
            elif url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql+asyncpg://", 1)
            return self._strip_ssl_from_url(url)
        return self.database_url

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
            from urllib.parse import parse_qs, unquote, urlparse

            raw = self.database_url_override
            for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://"):
                if raw.startswith(prefix):
                    raw = raw.replace(prefix, "postgresql://", 1)
                    break
            if raw.startswith("postgres://"):
                raw = raw.replace("postgres://", "postgresql://", 1)
            parsed = urlparse(raw)
            parts = []
            # fix(#1770): same reasoning as `database_url_override`'s
            # validator -- operator boot-time config.
            host = (
                parsed.hostname
                or parse_qs(parsed.query).get(  # parse_qs: unbounded
                    "host", [None]
                )[0]
            )
            if host:
                parts.append(f"host={libpq_value(host)}")
            if parsed.port:
                parts.append(f"port={parsed.port}")
            if parsed.path and parsed.path != "/":
                parts.append(f"dbname={libpq_value(parsed.path.lstrip('/'))}")
            # unquote on the credentials ONLY: SQLAlchemy decodes username and
            # password but leaves the database name percent-encoded, so decoding
            # dbname here would make these two clients target a DIFFERENT
            # database than the API (#1617).
            if parsed.username:
                parts.append(f"user={libpq_value(unquote(parsed.username))}")
            if parsed.password:
                parts.append(f"password={libpq_value(unquote(parsed.password))}")
            if self.database_ssl_mode != "disable":
                parts.append(f"sslmode={self.database_ssl_mode}")
            # verify-full ONLY: libpq treats sslmode=require as verify-ca once
            # a root CA file is present, so emitting this under `require`
            # would verify the server cert here while database_connect_args
            # disables that check for the API (#1617).
            if self.database_ssl_mode == "verify-full" and self.database_ssl_ca_cert:
                parts.append(f"sslrootcert={libpq_value(self.database_ssl_ca_cert)}")
            # BUG-002: the override branch had dropped this search_path
            # option, breaking the job queue on managed Postgres. Re-add it,
            # preserving any caller-supplied ?options= -- ours applied last
            # so it always wins.
            search_path_opt = f"-c search_path={self.procrastinate_schema},public"
            # fix(#1770): same reasoning -- operator boot-time config, not a
            # runtime service-advertised value.
            caller_options = parse_qs(parsed.query).get(  # parse_qs: unbounded
                "options", [""]
            )[0]
            combined_options = (
                f"{caller_options} {search_path_opt}".strip()
                if caller_options.strip()
                else search_path_opt
            )
            parts.append(f"options='{combined_options}'")
            return " ".join(parts)
        parts = [
            f"host={libpq_value(self.postgres_host)}",
            f"port={self.postgres_port}",
            f"dbname={libpq_value(self.postgres_db)}",
            f"user={libpq_value(self.postgres_user)}",
            f"password={libpq_value(self.postgres_password.get_secret_value())}",
        ]
        parts += libpq_ssl_parts(self.database_ssl_mode, self.database_ssl_ca_cert)
        parts.append(f"options='-c search_path={self.procrastinate_schema},public'")
        return " ".join(parts)

    @property
    def ogr_connection_string(self) -> str:
        if self.database_url_override:
            from urllib.parse import parse_qs, unquote, urlparse

            raw = self.database_url_override
            for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://"):
                if raw.startswith(prefix):
                    raw = raw.replace(prefix, "postgresql://", 1)
                    break
            if raw.startswith("postgres://"):
                raw = raw.replace("postgres://", "postgresql://", 1)
            parsed = urlparse(raw)
            parts = ["PG:"]
            # fix(#1770): same reasoning as `database_url_override`'s
            # validator -- operator boot-time config.
            host = (
                parsed.hostname
                or parse_qs(parsed.query).get(  # parse_qs: unbounded
                    "host", [None]
                )[0]
            )
            if host:
                parts.append(f"host={libpq_value(host)}")
            if parsed.port:
                parts.append(f"port={parsed.port}")
            if parsed.path and parsed.path != "/":
                parts.append(f"dbname={libpq_value(parsed.path.lstrip('/'))}")
            # unquote on the credentials ONLY: SQLAlchemy decodes username and
            # password but leaves the database name percent-encoded, so decoding
            # dbname here would make these two clients target a DIFFERENT
            # database than the API (#1617).
            if parsed.username:
                parts.append(f"user={libpq_value(unquote(parsed.username))}")
            if parsed.password:
                parts.append(f"password={libpq_value(unquote(parsed.password))}")
            if self.database_ssl_mode not in ("disable", "prefer"):
                parts.append(f"sslmode={self.database_ssl_mode}")
            # ogr2ogr reaches PostGIS through libpq, which resolves the CA
            # from the DSN or ~/.postgresql/root.crt -- it cannot see
            # DATABASE_SSL_CA_CERT, which only reaches asyncpg as an
            # SSLContext. Without this, verify-full sends libpq looking for
            # a root.crt not in the image, and every vector ingest fails
            # while other paths (which never shell out) stay healthy.
            # Emitted whenever a CA is configured; libpq ignores it under
            # the modes that don't verify.
            # verify-full ONLY: libpq treats sslmode=require as verify-ca once
            # a root CA file is present, so emitting this under `require`
            # would verify the server cert here while database_connect_args
            # disables that check for the API (#1617).
            if self.database_ssl_mode == "verify-full" and self.database_ssl_ca_cert:
                parts.append(f"sslrootcert={libpq_value(self.database_ssl_ca_cert)}")
            return " ".join(parts)
        parts = [
            "PG:",
            f"host={libpq_value(self.postgres_host)}",
            f"port={self.postgres_port}",
            f"dbname={libpq_value(self.postgres_db)}",
            f"user={libpq_value(self.postgres_user)}",
            f"password={libpq_value(self.postgres_password.get_secret_value())}",
        ]
        parts += libpq_ssl_parts(self.database_ssl_mode, self.database_ssl_ca_cert)
        return " ".join(parts)

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
            else:
                # Literal, URL, and numeric-bound failures use dedicated
                # Pydantic error types. Report only the field and safe message;
                # re-raising ValidationError would echo secret-bearing inputs
                # such as DATABASE_URL_OVERRIDE in the traceback.
                field_name = str(error["loc"][0]).upper()
                value_errors.append(f"{field_name}: {error['msg']}")
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

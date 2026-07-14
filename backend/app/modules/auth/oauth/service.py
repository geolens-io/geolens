"""CRUD service for OAuth provider configuration and user account linking."""

import ipaddress
import secrets
import uuid
from collections.abc import Mapping
from urllib.parse import urlparse

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer_group

from app.core.edition import is_enterprise
from app.core.persistent_config import ALLOWED_EMAIL_DOMAINS
from app.modules.auth.domain_validation import is_email_allowed
from app.modules.auth.models import Role, User, UserRole
from app.modules.auth.oauth.encryption import encrypt_secret
from app.modules.auth.oauth.models import OAuthAccount, OAuthProvider
from app.modules.auth.oauth.schemas import (
    SAML_PROVIDER_ERROR,
    SAML_PROVIDER_FIELDS,
    OAuthProviderCreate,
    OAuthProviderUpdate,
)

# ---------------------------------------------------------------------------
# GitHub OAuth2 fixed endpoints (SSO-05, Phase 1237)
# ---------------------------------------------------------------------------

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USERINFO_URL = "https://api.github.com/user"
# The emails endpoint is derived from the (possibly provider-configured)
# user endpoint at call time — see _resolve_github_identity (Codex P2).
# Default scope: read:user to access the /user endpoint; user:email to access
# /user/emails (needed to resolve the primary verified email when email is null
# on /user — which is the normal case for users who have set email to private).
GITHUB_DEFAULT_SCOPE = "read:user user:email"

_OAUTH_ENDPOINT_FIELDS = (
    "discovery_url",
    "authorize_url",
    "token_url",
    "userinfo_url",
)
_GITHUB_PUBLIC_HOSTS = frozenset({"github.com", "api.github.com"})


class OAuthProviderConfigurationError(ValueError):
    """An OAuth provider configuration violates a security invariant."""


class OAuthCredentialDestinationError(OAuthProviderConfigurationError):
    """A credential destination changed without an explicit secret rotation."""


def _url_origin(url: str | None) -> tuple[str, str, int] | None:
    """Return a normalized ``(scheme, host, port)`` tuple for an endpoint."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise OAuthProviderConfigurationError(
            "OAuth endpoint has an invalid port"
        ) from exc
    if not parsed.hostname:
        raise OAuthProviderConfigurationError("OAuth endpoint must include a host")
    if parsed.username is not None or parsed.password is not None:
        raise OAuthProviderConfigurationError(
            "OAuth endpoint URLs must not contain credentials"
        )
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise OAuthProviderConfigurationError(
            "OAuth endpoint URLs must use http or https"
        )
    return scheme, parsed.hostname.lower(), port or (443 if scheme == "https" else 80)


def _reject_obvious_internal_endpoint(url: str | None) -> None:
    """Reject literal/local endpoint targets without performing configuration-time DNS.

    Full DNS validation and IP pinning happen immediately before every server-side
    request. Keeping CRUD validation network-independent preserves offline config
    management while still refusing unambiguous loopback/private destinations at
    submission time.
    """
    origin = _url_origin(url)
    if origin is None:
        return
    host = origin[1]
    if host == "localhost" or host.endswith(".localhost"):
        raise OAuthProviderConfigurationError(
            "OAuth endpoints cannot target private/internal networks"
        )
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address in ipaddress.ip_network("100.64.0.0/10")
        or address in ipaddress.ip_network("fc00::/7")
        or address in ipaddress.ip_network("64:ff9b::/96")
    ):
        raise OAuthProviderConfigurationError(
            "OAuth endpoints cannot target private/internal networks"
        )


def _default_and_validate_github_endpoints(values: dict) -> None:
    """Apply GitHub.com defaults and pin any public-GitHub configuration.

    Custom endpoint triples remain supported for GitHub Enterprise. A provider
    that uses either public GitHub hostname, however, must use the exact canonical
    public endpoint triple; this prevents a partly overridden public configuration
    from becoming a credential redirect.
    """
    if values.get("provider_type") != "github":
        return
    if values.get("discovery_url"):
        raise OAuthProviderConfigurationError(
            "GitHub providers cannot use an OIDC discovery URL"
        )
    values["authorize_url"] = values.get("authorize_url") or GITHUB_AUTHORIZE_URL
    values["token_url"] = values.get("token_url") or GITHUB_TOKEN_URL
    values["userinfo_url"] = values.get("userinfo_url") or GITHUB_USERINFO_URL

    endpoints = (
        values["authorize_url"],
        values["token_url"],
        values["userinfo_url"],
    )
    hosts = {_url_origin(url)[1] for url in endpoints}
    if hosts & _GITHUB_PUBLIC_HOSTS and endpoints != (
        GITHUB_AUTHORIZE_URL,
        GITHUB_TOKEN_URL,
        GITHUB_USERINFO_URL,
    ):
        raise OAuthProviderConfigurationError(
            "Public GitHub providers must use the canonical GitHub endpoints"
        )


def _raw_provider_endpoint_values(
    provider: OAuthProvider | Mapping[str, object],
    updates: Mapping[str, object] | None = None,
) -> dict:
    """Project endpoint-bearing fields without rejecting a repairable legacy row."""
    if isinstance(provider, Mapping):
        values = {
            "provider_type": provider.get("provider_type"),
            **{field: provider.get(field) for field in _OAUTH_ENDPOINT_FIELDS},
        }
    else:
        values = {
            "provider_type": provider.provider_type,
            **{field: getattr(provider, field) for field in _OAUTH_ENDPOINT_FIELDS},
        }
    if updates:
        for field in ("provider_type", *_OAUTH_ENDPOINT_FIELDS):
            if field in updates:
                values[field] = updates[field]
    return values


def _provider_endpoint_values(
    provider: OAuthProvider | Mapping[str, object],
    updates: Mapping[str, object] | None = None,
) -> dict:
    """Project, normalize, and validate endpoint-bearing provider fields."""
    values = _raw_provider_endpoint_values(provider, updates)
    _default_and_validate_github_endpoints(values)
    if values.get("discovery_url") and any(
        values.get(field) for field in ("authorize_url", "token_url", "userinfo_url")
    ):
        raise OAuthProviderConfigurationError(
            "OAuth providers must use either discovery or explicit endpoints, not both"
        )
    for field in _OAUTH_ENDPOINT_FIELDS:
        _reject_obvious_internal_endpoint(values.get(field))
    return values


def _credential_destination_changed(
    current: Mapping[str, object], updated: Mapping[str, object]
) -> bool:
    """Return whether an update adds or retargets a credential destination."""
    if current.get("provider_type") != updated.get("provider_type"):
        return True

    def active_destinations(values: Mapping[str, object]) -> dict[str, tuple]:
        discovery_url = values.get("discovery_url")
        if isinstance(discovery_url, str) and discovery_url:
            active = {"discovery_url": _url_origin(discovery_url)}
            # Historical mixed GitHub rows used discovery for token exchange but
            # still sent the access token to their explicit identity endpoint.
            if values.get("provider_type") == "github":
                userinfo_url = values.get("userinfo_url")
                if isinstance(userinfo_url, str) and userinfo_url:
                    active["userinfo_url"] = _url_origin(userinfo_url)
            return active
        return {
            field: _url_origin(url)
            for field in ("token_url", "userinfo_url")
            if isinstance((url := values.get(field)), str) and url
        }

    current_active = active_destinations(current)
    updated_active = active_destinations(updated)
    for field, updated_origin in updated_active.items():
        if updated_origin != current_active.get(field):
            return True
    return False


def normalize_provider_create(data: OAuthProviderCreate) -> dict[str, object]:
    """Return the validated values that ``create_provider`` will persist.

    This is intentionally pure so config-import preflight can run the same
    endpoint and edition checks as apply without staging an ORM object.  The
    returned mapping contains write-only credentials when the caller supplied
    them; callers must never serialize it into a response or audit payload.
    """
    normalized: dict[str, object] = data.model_dump()
    is_saml = data.provider_type == "saml"
    if is_saml and not is_enterprise():
        raise OAuthProviderConfigurationError(SAML_PROVIDER_ERROR)

    endpoint_values = _provider_endpoint_values(normalized)
    for field in _OAUTH_ENDPOINT_FIELDS:
        normalized[field] = endpoint_values[field]

    if data.provider_type == "github" and data.scopes == "openid profile email":
        normalized["scopes"] = GITHUB_DEFAULT_SCOPE

    return normalized


def normalize_provider_update(
    provider: OAuthProvider,
    data: OAuthProviderUpdate,
) -> dict[str, object]:
    """Return the validated values that ``update_provider`` will persist.

    Validation depends on the current provider (not just the request schema):
    existing SAML rows remain edition-gated and an OAuth credential destination
    cannot move without an explicit secret rotation.  Keeping this logic pure
    lets config dry-run and apply consume the exact same normalization contract.
    """
    update_data: dict[str, object] = data.model_dump(exclude_unset=True)
    if not is_enterprise() and (
        provider.provider_type == "saml"
        or update_data.get("provider_type") == "saml"
        or any(field in update_data for field in SAML_PROVIDER_FIELDS)
    ):
        raise OAuthProviderConfigurationError(SAML_PROVIDER_ERROR)

    current_endpoints = _raw_provider_endpoint_values(provider)
    updated_endpoints = _provider_endpoint_values(provider, update_data)
    destination_changed = _credential_destination_changed(
        current_endpoints, updated_endpoints
    )
    replacement_secret = update_data.get("client_secret")
    if (
        updated_endpoints["provider_type"] != "saml"
        and destination_changed
        and not replacement_secret
    ):
        raise OAuthCredentialDestinationError(
            "client_secret must be provided when changing an OAuth credential destination origin"
        )

    # Persist the normalized/defaulted endpoint set used for the security
    # comparison, including canonical public-GitHub defaults.
    for field in _OAUTH_ENDPOINT_FIELDS:
        update_data[field] = updated_endpoints[field]
    return update_data


async def validate_provider_server_endpoints(provider: OAuthProvider) -> None:
    """Resolve and validate every configured URL before OAuth credentials are used."""
    from app.modules.catalog.sources.security import validate_url_for_ssrf

    values = _provider_endpoint_values(provider)
    for field in _OAUTH_ENDPOINT_FIELDS:
        url = values.get(field)
        if isinstance(url, str) and url:
            await validate_url_for_ssrf(url)


async def _is_manage_settings_admin(db: AsyncSession, user: User) -> bool:
    """Return True if *user* holds the manage_settings capability.

    Used for break-glass exemptions in the SSO domain-enforcement paths.
    Lazy-imports to avoid circular dependencies (mirrors the pattern used in
    auth/router.py DOMAIN-04 gate, per D-17).
    """
    from app.modules.auth.permissions import (  # LAZY — per D-17
        MANAGE_SETTINGS,
        user_has_capability,
    )

    return await user_has_capability(db, user, MANAGE_SETTINGS)


logger = structlog.stdlib.get_logger(__name__)


class OAuthEmailUnverifiedError(Exception):
    """Phase 268 H-30: raised when an OAuth login presents an unverified
    email that collides with an existing local user.

    The router translates this into a redirect with an
    ``error=email_not_verified`` correlation to surface the issue to the
    operator without exposing whether the colliding email exists (the
    error itself reveals the collision; surfacing username-enumeration
    detail is acceptable here because the attacker already supplied the
    email under attempt — no new info beyond their own input).
    """


class OAuthDomainNotAllowedError(Exception):
    """DOMAIN-03: raised when an OAuth identity's email domain is not in a
    non-empty ``allowed_email_domains`` allowlist.

    No user is provisioned when this is raised — the domain check fires
    BEFORE any OAuthAccount lookup or user find/create, so a disallowed
    domain never reaches the provisioning path (T-1236-01, TOCTOU-free).

    The router translates this into a redirect with an
    ``error=domain_not_allowed`` fragment.  The warning log records only
    the provider slug and a correlation_id; the attempted email is never
    logged (T-1236-04 — information-disclosure mitigation).
    """


async def create_provider(
    db: AsyncSession,
    data: OAuthProviderCreate,
    public_app_url: str = "http://localhost:8080",
) -> OAuthProvider:
    """Create a new OAuth or SAML provider, encrypting credentials.

    OAuth providers (oidc/google/microsoft) require client_id + client_secret;
    the secret is Fernet-encrypted via ``client_secret_encrypted``.

    SAML providers (provider_type='saml') require the 4 SAML fields:
    ``idp_entity_id``, ``idp_sso_url``, ``idp_certificate``, ``sp_entity_id``.
    The IdP signing cert is Fernet-encrypted (D-03 — Pattern D, mirrors the
    OAuth client_secret idiom). NOT-NULL columns ``client_id`` and
    ``client_secret_encrypted`` are populated with placeholder strings for
    SAML rows because the DB columns themselves are NOT-NULL (Plan 03 makes
    the Pydantic fields Optional but does not relax the DB constraint).

    The Pydantic per-type validator on ``OAuthProviderCreate`` rejects mixed/
    incomplete configs at the schema layer, so we can trust the data shape here.
    """
    normalized = normalize_provider_create(data)
    is_saml = normalized["provider_type"] == "saml"

    # NOT-NULL placeholder strings for SAML rows (DB columns require non-null).
    client_id_value = normalized["client_id"] if not is_saml else "saml-no-client-id"
    raw_client_secret = normalized.get("client_secret")
    client_secret_value = (
        encrypt_secret(str(raw_client_secret))
        if raw_client_secret
        else encrypt_secret("saml-no-client-secret")
    )

    # GitHub auto-populate: fill in GitHub's fixed endpoints when the admin did
    # not supply explicit values (SSO-05, Phase 1237).  GitHub is plain OAuth2
    # (no discovery URL, no id_token), so these three explicit endpoint fields
    # must be populated here rather than via a discovery_url fetch.
    #
    # Admin-supplied values always take precedence: we only set a field when it
    # is None (i.e. the admin left it blank).  The scope is auto-defaulted to
    # GITHUB_DEFAULT_SCOPE only when the admin sent the schema default
    # ("openid profile email"), which is not useful for GitHub.
    provider = OAuthProvider(
        slug=normalized["slug"],
        display_name=normalized["display_name"],
        provider_type=normalized["provider_type"],
        client_id=client_id_value,
        client_secret_encrypted=client_secret_value,
        discovery_url=normalized["discovery_url"],
        authorize_url=normalized["authorize_url"],
        token_url=normalized["token_url"],
        userinfo_url=normalized["userinfo_url"],
        # SAML fields: idp_certificate is Fernet-encrypted (D-03 / Pattern D);
        # the other 3 are plaintext (entity IDs and a public URL — not credentials).
        idp_entity_id=normalized["idp_entity_id"],
        idp_sso_url=normalized["idp_sso_url"],
        idp_certificate=(
            encrypt_secret(str(normalized["idp_certificate"]))
            if normalized["idp_certificate"]
            else None
        ),
        sp_entity_id=normalized["sp_entity_id"],
        scopes=normalized["scopes"],
        default_role=normalized["default_role"],
        group_claim=normalized["group_claim"],
        group_role_mapping=normalized["group_role_mapping"],
        enabled=normalized["enabled"],
    )
    db.add(provider)
    await db.flush()
    await db.refresh(provider)
    return provider


async def get_provider_by_slug(db: AsyncSession, slug: str) -> OAuthProvider | None:
    """Look up an OAuth provider by its URL slug."""
    result = await db.execute(select(OAuthProvider).where(OAuthProvider.slug == slug))
    return result.scalar_one_or_none()


async def get_provider_by_id(
    db: AsyncSession, provider_id: uuid.UUID
) -> OAuthProvider | None:
    """Look up an OAuth provider by its ID."""
    result = await db.execute(
        select(OAuthProvider).where(OAuthProvider.id == provider_id)
    )
    return result.scalar_one_or_none()


async def list_providers(
    db: AsyncSession,
    enabled_only: bool = False,
    *,
    include_saml_fields: bool = False,
) -> list[OAuthProvider]:
    """List OAuth providers, optionally loading the deferred SAML field group."""
    query = select(OAuthProvider).order_by(OAuthProvider.display_name)
    if include_saml_fields:
        query = query.options(undefer_group("saml"))
    if enabled_only:
        query = query.where(OAuthProvider.enabled.is_(True))
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_enabled_providers(db: AsyncSession) -> list[OAuthProvider]:
    """Shortcut: list only enabled OAuth providers."""
    return await list_providers(db, enabled_only=True)


async def lock_enabled_providers(db: AsyncSession) -> list[uuid.UUID]:
    """Row-lock every currently-enabled provider (``FOR UPDATE``) and return their ids.

    Serializes the three SSO lockout guards (password-disable, provider-disable,
    provider-delete) at the Postgres row-lock level. Two concurrent admin requests
    that could together leave the org with zero login methods both contend on these
    rows, so the second blocks until the first commits and then re-evaluates the
    (now-updated) state — closing the check-then-act race without a global advisory
    lock (whose constant key serialized unrelated settings writes; see git 898048b2).

    The caller MUST invoke this BEFORE reading ``password_login_enabled`` so a
    concurrent password-disable is serialized rather than read stale. ``ORDER BY id``
    gives a deterministic multi-row lock order, so two callers can never deadlock.
    The lock is transaction-scoped and releases on commit/rollback.
    """
    result = await db.execute(
        select(OAuthProvider.id)
        .where(OAuthProvider.enabled.is_(True))
        .order_by(OAuthProvider.id)
        .with_for_update()
    )
    return list(result.scalars().all())


async def update_provider(
    db: AsyncSession,
    provider: OAuthProvider,
    data: OAuthProviderUpdate,
) -> OAuthProvider:
    """Update an OAuth or SAML provider. Re-encrypts secrets if provided.

    Both ``client_secret`` (OAuth) and ``idp_certificate`` (SAML) are
    Fernet-encrypted before storage if present in the update body. Other
    fields flow through the standard ``setattr`` loop.
    """
    # Serialize updates to the same provider row. Besides preventing lost
    # updates, populate_existing refreshes the supplied ORM instance after the
    # lock wait so the credential-origin comparison always uses current state.
    locked_result = await db.execute(
        select(OAuthProvider)
        .where(OAuthProvider.id == provider.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    provider = locked_result.scalar_one()

    update_data = normalize_provider_update(provider, data)

    # Handle client_secret specially: encrypt before storing
    if "client_secret" in update_data:
        raw_secret = update_data.pop("client_secret")
        if raw_secret is not None:
            provider.client_secret_encrypted = encrypt_secret(raw_secret)

    # Handle idp_certificate the same way (D-03 / Pattern D — mirrors client_secret).
    if "idp_certificate" in update_data:
        raw_cert = update_data.pop("idp_certificate")
        if raw_cert is not None:
            provider.idp_certificate = encrypt_secret(raw_cert)

    for field, value in update_data.items():
        setattr(provider, field, value)

    await db.flush()
    await db.refresh(provider)
    return provider


async def delete_provider(db: AsyncSession, provider: OAuthProvider) -> None:
    """Delete an OAuth provider (cascades to oauth_accounts)."""
    await db.delete(provider)
    await db.flush()


# ---------------------------------------------------------------------------
# GitHub OAuth2 identity resolution (SSO-05, Phase 1237)
# ---------------------------------------------------------------------------


async def _resolve_github_identity(
    token: dict, userinfo_url: str | None = None
) -> dict:
    """Resolve a GitHub user's primary+verified email and return a normalized userinfo dict.

    GitHub's ``/user`` endpoint omits the email field when the user has set their
    email to private.  Even when it is present it may be an unverified address.
    This helper calls ``GET /user/emails`` to find the entry that is BOTH
    ``primary == true`` AND ``verified == true``, which is the only address that
    can reliably identify the account without enabling account-takeover via an
    attacker-added unverified email (T-1237-01).

    Security contract
    -----------------
    - Only the entry that is simultaneously ``primary`` AND ``verified`` is
      accepted.  An entry that is verified-but-not-primary, or primary-but-not-
      verified, is ignored.
    - If no such entry exists the function raises ``ValueError`` so the callback's
      broad ``except`` converts it to an ``oauth_failed`` redirect — the login
      cannot proceed without a trustworthy email address.
    - The GitHub token endpoint returns form-encoded unless ``Accept: application/json``
      is sent; the caller (router.py) ensures the token is already a dict by the
      time this helper is called.

    Parameters
    ----------
    token:
        The token dict returned by ``client.authorize_access_token(request)``.
        Must include ``"access_token"`` at the top level.

    Returns
    -------
    dict with keys ``sub`` (str), ``email`` (str), ``name`` (str), and
    ``email_verified`` (always ``True`` — enforced by the primary+verified guard).
    """
    access_token = token.get("access_token")
    if not access_token:
        raise ValueError("GitHub token response missing access_token")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # Codex P2: use the provider's configured user endpoint (GitHub Enterprise
    # providers set a custom userinfo_url) and derive the emails endpoint from it,
    # so an enterprise access token is never sent to the hard-coded public
    # api.github.com. Falls back to the public GitHub API when unset.
    user_url = userinfo_url or GITHUB_USERINFO_URL
    emails_url = user_url.rstrip("/") + "/emails"

    # The provider URL is admin-configured. Use the shared IP-pinning transport
    # and disable redirects for bearer-token requests so neither DNS rebinding
    # nor a redirect can retarget the token to another authority.
    from app.modules.catalog.sources.security import make_safe_client

    async with make_safe_client() as client:
        # Fetch basic user profile for id, login, name.
        user_resp = await client.get(user_url, headers=headers, follow_redirects=False)
        user_resp.raise_for_status()
        user_data = user_resp.json()

        # Fetch verified email list — required because /user returns email=null
        # when the user has set their email to private (the common case).
        emails_resp = await client.get(
            emails_url, headers=headers, follow_redirects=False
        )
        emails_resp.raise_for_status()
        emails_data = emails_resp.json()

    github_id = user_data.get("id")
    if not github_id:
        raise ValueError("GitHub /user response missing id")

    # T-1237-01: select ONLY the entry that is both primary AND verified.
    primary_verified = next(
        (
            entry
            for entry in emails_data
            if entry.get("primary") is True and entry.get("verified") is True
        ),
        None,
    )
    if primary_verified is None:
        raise ValueError(
            "GitHub account has no primary+verified email — cannot authenticate. "
            "Please verify your primary email address on GitHub and try again."
        )

    email = primary_verified["email"]
    name = user_data.get("name") or user_data.get("login", "")

    return {
        "sub": str(github_id),
        "email": email,
        "name": name,
        "email_verified": True,  # enforced by the primary+verified guard above
    }


# ---------------------------------------------------------------------------
# OAuth user find-or-create (OAUTH-05, OAUTH-06, OAUTH-07)
# ---------------------------------------------------------------------------


def _generate_username(display_name: str | None, email: str | None) -> str:
    """Generate a base username from email prefix or display name."""
    if email:
        return email.split("@")[0]
    if display_name:
        # Lowercase, replace spaces with underscores, keep alphanumeric + underscore
        cleaned = "".join(
            c if c.isalnum() or c == "_" else "_"
            for c in display_name.lower().replace(" ", "_")
        )
        return cleaned or "oauth_user"
    return "oauth_user"


def _resolve_role(
    groups: list[str] | None,
    mapping: dict | None,
    default: str,
) -> str:
    """Match first group from mapping, fallback to default role."""
    if groups and mapping:
        for group in groups:
            if group in mapping:
                return mapping[group]
    return default


_AZURE_MULTITENANT_AUTHORITIES = ("/common/", "/organizations/")


def is_azure_multitenant(provider_type: str, discovery_url: str | None) -> bool:
    """True for Azure multitenant Microsoft (``/common/``, ``/organizations/``).

    These authorities accept identities from many tenants and advertise a
    templated issuer, unlike a tenant-specific (or ``/consumers/``) authority
    whose issuer is fixed. Both the relaxed id_token ``iss`` check and the
    tenant-partitioned account subject are gated on this (geolens#303).
    """
    if provider_type != "microsoft":
        return False
    disco = (discovery_url or "").lower()
    return any(authority in disco for authority in _AZURE_MULTITENANT_AUTHORITIES)


def oauth_account_subject(
    provider_type: str, discovery_url: str | None, userinfo: dict
) -> str:
    """Stable per-provider key for ``OAuthAccount.subject``.

    For Azure *multitenant* Microsoft the bare ``sub`` is not globally unique
    across tenants (Microsoft's stable id is tenant-scoped — ``tid`` + ``oid``),
    so two users in different tenants sharing a ``sub`` would collide on
    ``(provider_id, subject)`` and the second would be linked to the first's
    local account — a cross-tenant account takeover. Prefix the subject with the
    tenant id for multitenant Microsoft; every other provider (including
    single-tenant Microsoft, whose issuer is fixed) keeps the bare ``sub``
    (geolens#303).
    """
    sub = str(userinfo.get("sub", ""))
    if is_azure_multitenant(provider_type, discovery_url):
        tid = str(userinfo.get("tid", "")).strip()
        if tid:
            return f"{tid}:{sub}"
    return sub


class OAuthIssuerError(ValueError):
    """Raised when an Azure multitenant id_token's resolved issuer is invalid."""


def verify_azure_multitenant_issuer(
    provider_type: str, discovery_url: str | None, claims: dict
) -> None:
    """Re-assert the resolved per-tenant issuer for Azure multitenant tokens.

    The id_token ``iss`` value-pin is relaxed at parse time because joserfc cannot
    substitute ``{tenantid}`` via a callable validator, so verify here that ``iss``
    exactly equals the tenant-substituted template using the token's own ``tid``.
    Rejects a Microsoft-signed token whose ``iss`` and ``tid`` disagree — the
    account key is derived from ``tid:sub``, so they must be consistent. No-op for
    non-multitenant providers (geolens#303).
    """
    if not is_azure_multitenant(provider_type, discovery_url):
        return
    tid = str(claims.get("tid", "")).strip()
    iss = str(claims.get("iss", "")).strip()
    if not tid or iss != f"https://login.microsoftonline.com/{tid}/v2.0":
        raise OAuthIssuerError("Azure multitenant issuer/tid mismatch")


async def find_or_create_oauth_user(
    db: AsyncSession,
    provider: OAuthProvider,
    userinfo: dict,
    token: dict,
) -> User:
    """Find or create a GeoLens user from OAuth userinfo.

    Three-step resolution:
    1. Existing OAuthAccount link (returning user) -> return linked user
    2. Email match (OAUTH-06) -> link to existing user, return user
    3. New user (OAUTH-05) -> create user with default_role, create OAuthAccount

    Group claims are mapped to roles per provider config (OAUTH-07).
    """
    subject = oauth_account_subject(
        provider.provider_type, provider.discovery_url, userinfo
    )
    email = userinfo.get("email")
    display_name = userinfo.get("name")

    # Extract groups using provider's group_claim
    groups: list[str] | None = None
    if provider.group_claim:
        groups = userinfo.get(provider.group_claim)
        if isinstance(groups, str):
            groups = [groups]

    # Step 1: Check existing OAuth link
    result = await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.provider_id == provider.id,
            OAuthAccount.subject == subject,
        )
    )
    existing_link = result.scalar_one_or_none()
    # No legacy bare-sub fallback for Microsoft multitenant (geolens#303 review):
    # those subjects are tenant-partitioned (tid:sub), and a bare-sub-only match
    # cannot prove the token is from the same Azure tenant — falling back would
    # reintroduce the cross-tenant collision the partitioning exists to prevent.
    # It is also unnecessary: multitenant Microsoft was un-loginable before this
    # change (authlib rejected the templated /common/ issuer), so no bare-sub
    # multitenant links exist. Any improbable legacy user with a verified email
    # still re-links via the email path below.
    if existing_link is not None:
        returning_user = existing_link.user

        # WR-02 (Phase 1236 Plan 03): domain check for RETURNING users.
        # The original DOMAIN-03 check ran before Step 1, so a returning user
        # whose email claim was OMITTED by the IdP would bypass it entirely.
        # For a returning user we have a stored User.email to fall back to;
        # use that when the IdP omits the claim.
        #
        # WR-01 (Phase 1236 Plan 03): break-glass for returning manage_settings
        # admins — consistent with the password-login break-glass (DOMAIN-04).
        # A NEW (JIT) identity still has no principal and must satisfy the
        # allowlist; only returning users with an established account get the
        # exemption.
        # WR-02 / Codex P1: prefer the IdP email claim ONLY when it is verified.
        # An unverified, caller-controlled claim must not be usable to satisfy the
        # allowlist for a returning user whose stored email is disallowed (mirrors
        # the JIT verified-email requirement). Fall back to the stored, already-
        # trusted email otherwise.
        claim_trusted = email is not None and userinfo.get("email_verified") is True
        check_email = email if claim_trusted else returning_user.email
        if check_email is None:
            # No claim and no stored email — cannot enforce; log a warning so
            # operators can investigate IdP misconfiguration.
            logger.warning(
                "OAuth login: domain enforcement skipped — no email claim and no stored email",
                provider=provider.slug,
                user_id=str(returning_user.id),
            )
        else:
            # Cache-bypass: enforcement reads committed state (see auth login gate).
            domains = await ALLOWED_EMAIL_DOMAINS.get_uncached(db)
            if not is_email_allowed(check_email, domains):
                # WR-01: break-glass for manage_settings admins.
                if not await _is_manage_settings_admin(db, returning_user):
                    raise OAuthDomainNotAllowedError(
                        "OAuth identity email domain is not in the allowed_email_domains allowlist."
                    )
                logger.info(
                    "OAuth login: returning manage_settings admin exempt from domain check",
                    provider=provider.slug,
                    user_id=str(returning_user.id),
                )

        logger.info(
            "OAuth login: existing link found",
            provider=provider.slug,
            user_id=str(returning_user.id),
        )
        return returning_user

    # DOMAIN-03 (T-1236-01): domain check for NEW (JIT) identities.
    # Fires BEFORE the email_verified collision guard and BEFORE provisioning —
    # so a disallowed domain never reaches the provisioning path (TOCTOU-free).
    # Empty allowlist ⇒ is_email_allowed returns True (no-op, zero behavior change).
    # No break-glass here: a NEW identity has no established principal, so there
    # is nothing to exempt.
    #
    # FIX-A (Codex P1): when the allowlist is NON-EMPTY and the IdP emits no
    # email claim, the new identity cannot be verified against the allowlist.
    # An unverifiable identity must be rejected (not silently provisioned with
    # email=None) — otherwise a no-email claim is an accidental allowlist bypass.
    # When the allowlist IS empty, a no-email new user still provisions as before
    # (zero behavior change when unconfigured).
    # Cache-bypass: enforcement reads committed state (see auth login gate).
    domains = await ALLOWED_EMAIL_DOMAINS.get_uncached(db)
    if domains:
        # Non-empty allowlist — email is required for verification.
        if not email:
            raise OAuthDomainNotAllowedError(
                "OAuth identity has no email claim; cannot verify against the "
                "allowed_email_domains allowlist."
            )
        # FIX (Codex P1): an allowed DOMAIN only satisfies the allowlist if the
        # email is VERIFIED. Without this, a provider where the caller controls
        # the claim could assert attacker@allowed.example with email_verified
        # false/absent; it would pass the domain check here, then the H-30 branch
        # below would drop the unverified email and still provision a new account
        # (email=None) — bypassing the allowlist entirely. Use the SAME
        # email_verified trust signal H-30 relies on for auto-linking, so a
        # trusted IdP that sets email_verified=True (incl. SAML JIT) is unaffected.
        if userinfo.get("email_verified") is not True:
            raise OAuthEmailUnverifiedError(
                "OAuth identity email is not verified; a verified email in an "
                "allowed domain is required when an allowlist is configured."
            )
        if not is_email_allowed(email, domains):
            raise OAuthDomainNotAllowedError(
                "OAuth identity email domain is not in the allowed_email_domains allowlist."
            )
    # Empty allowlist → is_email_allowed(email, []) returns True for any email,
    # so no additional check is needed; a no-email new user still provisions.

    # Step 2: Check email match (case-insensitive)
    # Phase 268 H-30: only honor the email-match auto-link when the IdP
    # explicitly marked the email as verified. Without this gate, an attacker
    # who registered their own IdP account at victim@example.com (with an
    # IdP that does not enforce verification, OR an admin-added permissive
    # provider) could sign in via OAuth and inherit the existing GeoLens
    # account that was previously registered locally with that email.
    # OIDC-compliant providers (Google, Microsoft, Okta, Auth0) always set
    # `email_verified` for verified addresses; if the claim is missing or
    # false, the login is refused entirely if a local user exists with that
    # email (preventing both account takeover AND new-user creation that
    # would otherwise hit a UNIQUE-constraint error). If no local collision,
    # fall through to step 3 with `email=None` so the new user is created
    # without claiming the unverified address.
    email_verified = userinfo.get("email_verified") is True
    if email and email_verified:
        result = await db.execute(
            select(User).where(func.lower(User.email) == func.lower(email))
        )
        existing_user = result.scalar_one_or_none()
        if existing_user is not None:
            # Link OAuth account to existing user
            link = OAuthAccount(
                provider_id=provider.id,
                user_id=existing_user.id,
                subject=subject,
            )
            db.add(link)
            await db.flush()
            logger.info(
                "OAuth login: linked to existing user by email",
                provider=provider.slug,
                email=email,
                user_id=str(existing_user.id),
            )
            return existing_user
    elif email and not email_verified:
        # Refuse the login entirely if the unverified email collides with an
        # existing local user (closes the account-takeover path). If no
        # collision, drop the email so new-user creation does not claim it.
        result = await db.execute(
            select(User.id).where(func.lower(User.email) == func.lower(email))
        )
        if result.scalar_one_or_none() is not None:
            logger.warning(
                "OAuth login refused: unverified email collides with local user",
                provider=provider.slug,
                email=email,
            )
            raise OAuthEmailUnverifiedError(
                "OAuth provider returned an unverified email that matches an "
                "existing account. Sign in with the local account first and "
                "link OAuth from your profile, or have your IdP verify the "
                "email."
            )
        logger.info(
            "OAuth login: email not verified by IdP, dropping email for new user",
            provider=provider.slug,
            email=email,
        )
        email = None

    # Step 3: Auto-create new user
    base_username = _generate_username(display_name, email)
    username = base_username

    # Handle username collision: check if username exists, append suffix
    for _ in range(5):
        result = await db.execute(
            select(User).where(func.lower(User.username) == func.lower(username))
        )
        if result.scalar_one_or_none() is None:
            break
        username = f"{base_username}_{secrets.token_hex(4)}"

    # Resolve role from group mapping (D-05).
    # Enterprise: apply IdP group→role mapping via _resolve_role().
    # Community: use default_role — defense-in-depth for legacy/direct-DB rows
    # that may have group_role_mapping populated before the schema gate shipped.
    if is_enterprise():
        role_name = _resolve_role(
            groups, provider.group_role_mapping, provider.default_role
        )
    else:
        role_name = provider.default_role

    new_user = User(
        username=username,
        email=email,
        password_hash=None,
        auth_provider="oauth",
        status="active",
        is_active=True,
    )
    db.add(new_user)
    await db.flush()

    # Assign role
    role_result = await db.execute(select(Role).where(Role.name == role_name))
    role = role_result.scalar_one_or_none()
    if role is None:
        # Fallback to viewer if configured role doesn't exist
        role_result = await db.execute(select(Role).where(Role.name == "viewer"))
        role = role_result.scalar_one()
    db.add(UserRole(user_id=new_user.id, role_id=role.id))

    # Create OAuth account link
    link = OAuthAccount(
        provider_id=provider.id,
        user_id=new_user.id,
        subject=subject,
    )
    db.add(link)
    await db.flush()

    # Refresh to load relationships
    await db.refresh(new_user)

    logger.info(
        "OAuth login: created new user",
        provider=provider.slug,
        username=username,
        role=role_name,
    )
    return new_user

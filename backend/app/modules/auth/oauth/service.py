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
from app.core.persistent_config import ALLOWED_EMAIL_DOMAINS, REGISTRATION_ENABLED
from app.modules.auth.domain_validation import is_email_allowed
from app.modules.auth.models import Role, User, UserRole
from app.modules.auth.oauth.encryption import encrypt_secret
from app.modules.auth.oauth.models import OAuthAccount, OAuthProvider
from app.modules.auth.oauth.schemas import (
    IDP_MAPPING_ERROR,
    SAML_PROVIDER_ERROR,
    SAML_PROVIDER_FIELDS,
    OAuthProviderCreate,
    OAuthProviderUpdate,
)

# GitHub OAuth2 fixed endpoints (SSO-05, Phase 1237).
GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USERINFO_URL = "https://api.github.com/user"
# Emails endpoint is derived from the (possibly provider-configured) user
# endpoint at call time; see _resolve_github_identity. Default scope:
# read:user for /user, user:email for /user/emails (needed when the primary
# email is private and email is null on /user).
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
    has_saml_fields = any(
        field in data.model_fields_set or getattr(data, field) is not None
        for field in SAML_PROVIDER_FIELDS
    )
    if not is_enterprise() and (is_saml or has_saml_fields):
        raise OAuthProviderConfigurationError(SAML_PROVIDER_ERROR)
    has_paid_idp_mapping = data.group_claim is not None or (
        data.group_role_mapping is not None and data.group_role_mapping != {}
    )
    if not is_enterprise() and has_paid_idp_mapping:
        raise OAuthProviderConfigurationError(IDP_MAPPING_ERROR)

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
    has_paid_idp_mapping = update_data.get("group_claim") is not None or (
        update_data.get("group_role_mapping") is not None
        and update_data.get("group_role_mapping") != {}
    )
    if not is_enterprise() and has_paid_idp_mapping:
        raise OAuthProviderConfigurationError(IDP_MAPPING_ERROR)

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
    from app.platform.security import validate_url_for_ssrf

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
    """Raised when an OAuth login presents an unverified email that collides
    with an existing local user.

    Router redirects with ``error=email_not_verified``. Revealing the
    collision is acceptable here since the attacker already supplied that
    email.
    """


class OAuthDomainNotAllowedError(Exception):
    """DOMAIN-03: raised when an OAuth identity's email domain is not in a
    non-empty ``allowed_email_domains`` allowlist.

    Fires BEFORE any OAuthAccount lookup or user find/create (TOCTOU-free) —
    no user is ever provisioned for a disallowed domain. Router redirects with
    ``error=domain_not_allowed``; the attempted email is never logged.
    """


class OAuthRegistrationDisabledError(Exception):
    """fix(#1778): raised when an unknown OAuth identity would be provisioned
    while self-serve registration is switched off.

    Only NEW identities are refused — a returning user with an existing
    OAuthAccount link, or an identity matching an existing account by verified
    email, still signs in. The gate is about creating accounts, not about
    locking out existing ones.

    Applies to the SAML overlay too, since it provisions through this same
    function: the switch answers whether a sign-in may create an account,
    independent of which protocol carried the assertion.

    Router redirects with ``error=registration_disabled`` and an audit row
    naming the reason; no email or subject is logged.
    """


async def create_provider(
    db: AsyncSession,
    data: OAuthProviderCreate,
    public_app_url: str = "http://localhost:8080",
) -> OAuthProvider:
    """Create a new OAuth or SAML provider, encrypting credentials.

    OAuth providers (oidc/google/microsoft) require client_id + client_secret,
    Fernet-encrypted via ``client_secret_encrypted``.

    SAML providers require the 4 SAML fields (``idp_entity_id``,
    ``idp_sso_url``, ``idp_certificate``, ``sp_entity_id``); the IdP cert is
    Fernet-encrypted (D-03). ``client_id``/``client_secret_encrypted`` get
    placeholder strings for SAML rows since those DB columns are NOT-NULL.

    The edition gate is repeated here (not just at the schema layer) because
    internal callers can invoke this service without schema validation.
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

    # GitHub auto-populate: fill in GitHub's fixed endpoints when the admin
    # left them blank (SSO-05, Phase 1237) — GitHub is plain OAuth2 (no
    # discovery), so these fields can't come from a discovery_url fetch.
    # Scope defaults to GITHUB_DEFAULT_SCOPE only when the admin sent the
    # schema default ("openid profile email"), which isn't useful for GitHub.
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
    result = await db.execute(select(OAuthProvider).where(OAuthProvider.slug == slug))
    return result.scalar_one_or_none()


async def get_provider_by_id(
    db: AsyncSession, provider_id: uuid.UUID
) -> OAuthProvider | None:
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
    return await list_providers(db, enabled_only=True)


async def lock_enabled_providers(db: AsyncSession) -> list[uuid.UUID]:
    """Row-lock every currently-enabled provider (``FOR UPDATE``) and return their ids.

    Serializes the three SSO lockout guards (password-disable, provider-disable,
    provider-delete) at the Postgres row-lock level, closing the check-then-act
    race without a global advisory lock (see git 898048b2).

    Caller MUST invoke this BEFORE reading ``password_login_enabled`` so a
    concurrent password-disable is serialized rather than read stale.
    ``ORDER BY id`` gives a deterministic lock order so two callers can't
    deadlock. Transaction-scoped; releases on commit/rollback.
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

    if "client_secret" in update_data:
        raw_secret = update_data.pop("client_secret")
        if raw_secret is not None:
            provider.client_secret_encrypted = encrypt_secret(raw_secret)

    # idp_certificate handled the same way (D-03 / Pattern D).
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


async def _resolve_github_identity(
    token: dict, userinfo_url: str | None = None
) -> dict:
    """Resolve a GitHub user's primary+verified email into a normalized userinfo dict.

    GitHub's /user endpoint omits email when private, and even when present it
    may be unverified. Fetches /user/emails and accepts ONLY the entry that is
    BOTH primary AND verified (T-1237-01) — the only address that can't be used
    for account-takeover via an attacker-added unverified email. Raises
    ValueError if none exists, which router.py's broad except turns into an
    oauth_failed redirect.

    token must include "access_token" (from client.authorize_access_token).
    Returns sub/email/name/email_verified (email_verified is always True,
    enforced by the primary+verified guard).
    """
    access_token = token.get("access_token")
    if not access_token:
        raise ValueError("GitHub token response missing access_token")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # Use the provider's configured user endpoint (GitHub Enterprise sets a
    # custom userinfo_url) so an enterprise access token is never sent to the
    # hard-coded public api.github.com. Falls back to the public API if unset.
    user_url = userinfo_url or GITHUB_USERINFO_URL
    emails_url = user_url.rstrip("/") + "/emails"

    # Admin-configured URL: use the SSRF-safe transport and disable redirects
    # so DNS rebinding or a redirect can't retarget the bearer token elsewhere.
    from app.platform.security import make_safe_client

    async with make_safe_client() as client:
        user_resp = await client.get(user_url, headers=headers, follow_redirects=False)
        user_resp.raise_for_status()
        user_data = user_resp.json()

        # /user returns email=null when set private (the common case), hence
        # the separate /user/emails fetch below.
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


# OAuth user find-or-create (OAUTH-05, OAUTH-06, OAUTH-07).
def _generate_username(display_name: str | None, email: str | None) -> str:
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


async def _reconcile_mapped_role(
    db: AsyncSession,
    provider: OAuthProvider,
    user: User,
    groups: list[str] | None,
) -> None:
    """fix(#1778): re-apply ``group_role_mapping`` on a returning user's login.

    Previously the mapping only ran at JIT creation, so removing someone from
    the IdP group never demoted them. Four preconditions, all load-bearing,
    must hold before a role is touched:

    * ``is_enterprise()`` — group mapping is an enterprise capability.
    * mapping is NON-EMPTY — with none configured, GeoLens is the system of
      record and a local promotion is never undone by a login.
    * groups claim is PRESENT — ``_resolve_role(None, ...)`` returns
      ``default_role``, so an IdP that omits the claim would otherwise demote
      everyone who signs in during the omission. An asserted EMPTY list
      resolves to the default; no claim means no evidence either way.
    * account is OAuth-provisioned — a local account merely linked by verified
      email keeps the roles a GeoLens admin gave it.

    fix(#1778): goes through
    ``AdminService.set_role_from_identity_provider`` rather than assigning
    ``user.roles`` directly, so it inherits the admin-lifecycle advisory lock,
    the last-admin rule, and the ``key_epoch`` bump (#821) — without which an
    API key minted as a viewer would silently gain admin on the next login.

    Every outcome is recorded: a structured log line, an
    ``oauth.role.changed`` audit row on a move, and
    ``oauth.role.change_refused`` when the last-admin rule holds the role.
    Neither carries a claim value.
    """
    if not is_enterprise():
        return
    mapping = provider.group_role_mapping
    if not mapping:
        return
    if groups is None:
        return
    if user.auth_provider != "oauth":
        return

    resolved = _resolve_role(groups, mapping, provider.default_role)

    current = list(user.roles)
    if len(current) == 1 and current[0].name == resolved:
        return

    known_role = await db.scalar(select(Role.id).where(Role.name == resolved))
    if known_role is None:
        # Mapping names a role this deployment lacks; refusing is the safe
        # answer (no silent demotion, no inventing roles). Checked here so
        # the operator's message names the mapping.
        logger.warning(
            "OAuth login: mapped role does not exist, leaving roles unchanged",
            provider=provider.slug,
            user_id=str(user.id),
            mapped_role=resolved,
        )
        return

    # LAZY, per D-17 and to keep the import graph acyclic: admin/service.py
    # already imports from auth/providers/local.py.
    from app.modules.admin.service import AdminService  # noqa: PLC0415
    from app.modules.audit.service import AuditEvent, audit_emit  # noqa: PLC0415

    outcome = await AdminService(db).set_role_from_identity_provider(user, resolved)
    await db.flush()
    await db.refresh(user, attribute_names=["roles"])

    # fix(#1778): roles as captured UNDER the lock, not before it —
    # two concurrent callbacks racing this must not both describe a
    # transition that already happened.
    previous = outcome.previous_roles

    if not outcome.applied:
        # Last active admin: an IdP assertion cannot remove the deployment's
        # only way back in. Role stands; this row is how an operator learns
        # the mapping and the account list disagree.
        logger.warning(
            "OAuth login: mapped demotion refused, account is the last admin",
            provider=provider.slug,
            user_id=str(user.id),
            previous_roles=previous,
            mapped_role=resolved,
        )
        await audit_emit(
            db,
            AuditEvent(
                user_id=user.id,
                action="oauth.role.change_refused",
                resource_type="user",
                resource_id=user.id,
                details={
                    "provider_slug": provider.slug,
                    "current_roles": previous,
                    "mapped_role": resolved,
                    "reason": "last_admin",
                },
            ),
        )
        return

    if not outcome.changed:
        # fix(#1778): already at the mapped role — the second of two
        # concurrent callbacks landing here after the first already applied it.
        return

    logger.info(
        "OAuth login: role re-evaluated from IdP group mapping",
        provider=provider.slug,
        user_id=str(user.id),
        previous_roles=previous,
        new_role=resolved,
    )

    await audit_emit(
        db,
        AuditEvent(
            user_id=user.id,
            action="oauth.role.changed",
            resource_type="user",
            resource_id=user.id,
            details={
                "provider_slug": provider.slug,
                "previous_roles": previous,
                "new_role": resolved,
                "reason": "group_role_mapping",
            },
        ),
    )


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

    For Azure multitenant Microsoft the bare ``sub`` is not globally unique
    across tenants, so two users in different tenants sharing a ``sub`` would
    collide on ``(provider_id, subject)`` — a cross-tenant account takeover.
    Prefixes with tenant id for multitenant Microsoft; every other provider
    keeps the bare ``sub`` (geolens#303).
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

    id_token ``iss`` pinning is relaxed at parse time (joserfc can't substitute
    ``{tenantid}`` via a validator), so this verifies ``iss`` matches the
    tenant-substituted template against the token's own ``tid``. Rejects a
    token whose ``iss``/``tid`` disagree, since the account key is derived
    from ``tid:sub``. No-op for non-multitenant providers (geolens#303).
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

    fix(#1778): steps 1 and 2 both yield an EXISTING account and both
    call ``_reconcile_mapped_role``; step 3 sets the role inline via
    ``_resolve_role``. Any new return path for an existing user must add the
    reconcile call too — reconciliation once lived on step 1 alone, which left
    a first-time cross-provider link carrying its old role for the session.
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
    # No legacy bare-sub fallback for Microsoft multitenant (geolens#303): a
    # bare-sub match can't prove same-tenant and would reintroduce the
    # cross-tenant collision the tid: prefix prevents.
    if existing_link is not None:
        returning_user = existing_link.user

        # WR-02: domain check also applies to RETURNING users (the original
        # DOMAIN-03 ran only before Step 1, letting a returning user with an
        # omitted email claim bypass it) — falls back to stored User.email.
        #
        # WR-01: break-glass exemption below is for RETURNING manage_settings
        # admins only; a NEW (JIT) identity has no principal yet and must
        # satisfy the allowlist.
        #
        # WR-02/Codex P1: prefer the IdP email claim ONLY when verified — an
        # unverified caller-controlled claim must not satisfy the allowlist
        # for a returning user whose stored email is disallowed.
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

        # fix(#623): converge pre-JIT accounts missing email_verified. Only
        # when the IdP asserts verification for the SAME stored address, and
        # only for OAuth-provisioned users — never flips a local account's
        # own verification state via a link.
        if (
            claim_trusted
            and not returning_user.email_verified
            and returning_user.auth_provider == "oauth"
            and returning_user.email is not None
            and email is not None
            and returning_user.email.lower() == email.lower()
        ):
            returning_user.email_verified = True
            await db.flush()

        await _reconcile_mapped_role(db, provider, returning_user, groups)

        logger.info(
            "OAuth login: existing link found",
            provider=provider.slug,
            user_id=str(returning_user.id),
        )
        return returning_user

    # DOMAIN-03 (T-1236-01): domain check for NEW (JIT) identities. Fires
    # BEFORE the email_verified collision guard and BEFORE provisioning
    # (TOCTOU-free). Empty allowlist -> always allowed. No break-glass: a
    # NEW identity has no established principal to exempt.
    #
    # FIX-A (Codex P1): a NON-EMPTY allowlist with no email claim must reject
    # (not silently provision email=None) — a no-email claim would otherwise
    # be an accidental allowlist bypass. Empty allowlist still provisions
    # as before.
    domains = await ALLOWED_EMAIL_DOMAINS.get_uncached(db)
    if domains:
        if not email:
            raise OAuthDomainNotAllowedError(
                "OAuth identity has no email claim; cannot verify against the "
                "allowed_email_domains allowlist."
            )
        # FIX (Codex P1): an allowed domain only satisfies the allowlist if
        # the email is VERIFIED — otherwise a caller-controlled claim could
        # assert an allowed address, pass here, then have H-30 below drop the
        # unverified email and provision anyway (bypassing the allowlist).
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
    # H-30: only honor email-match auto-link when the IdP marked email
    # verified — otherwise an attacker who registers victim@example.com at a
    # permissive IdP could inherit that local GeoLens account. Unverified +
    # colliding email refuses the login entirely; unverified + no collision
    # drops the email and falls through to step 3.
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
            # fix(#1778): the other return path yielding an EXISTING
            # account, so it needs the same reconciliation — otherwise a
            # first-time cross-provider link keeps the first provider's role
            # for the session. A LOCAL account linked here still keeps the
            # roles its GeoLens admin gave it (helper's own preconditions).
            await _reconcile_mapped_role(db, provider, existing_user, groups)
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

    # fix(#1778): self-serve-registration switch gates new-account creation
    # too, placed AFTER domain/email checks so a refusal here can't be used
    # to probe which gate an identity trips. Cache-bypass: reads committed
    # state so a just-disabled registration isn't overruled by a stale value.
    if not await REGISTRATION_ENABLED.get_uncached(db):
        raise OAuthRegistrationDisabledError(
            "Self-serve registration is disabled, so a new account cannot be "
            "created for this identity. An administrator must create the "
            "account first; signing in through this provider will then link to "
            "it."
        )

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

    # D-05: enterprise applies IdP group->role via _resolve_role(); community
    # uses default_role (defense-in-depth for legacy rows with
    # group_role_mapping populated before the schema gate shipped).
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
        # fix(#623): persists the IdP's assertion rather than the model
        # default (False), which left every SSO user unverified. Both halves
        # of the AND are load-bearing — no email means nothing verified.
        email_verified=email is not None and email_verified,
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

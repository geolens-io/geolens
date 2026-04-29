"""CRUD service for OAuth provider configuration and user account linking."""

import secrets
import uuid

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.edition import is_enterprise
from app.modules.auth.models import Role, User, UserRole
from app.modules.auth.oauth.encryption import encrypt_secret
from app.modules.auth.oauth.models import OAuthAccount, OAuthProvider
from app.modules.auth.oauth.schemas import OAuthProviderCreate, OAuthProviderUpdate

logger = structlog.stdlib.get_logger(__name__)


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
    is_saml = data.provider_type == "saml"

    # NOT-NULL placeholder strings for SAML rows (DB columns require non-null).
    client_id_value = data.client_id if not is_saml else "saml-no-client-id"
    client_secret_value = (
        encrypt_secret(data.client_secret)
        if data.client_secret
        else encrypt_secret("saml-no-client-secret")
    )

    provider = OAuthProvider(
        slug=data.slug,
        display_name=data.display_name,
        provider_type=data.provider_type,
        client_id=client_id_value,
        client_secret_encrypted=client_secret_value,
        discovery_url=data.discovery_url,
        authorize_url=data.authorize_url,
        token_url=data.token_url,
        userinfo_url=data.userinfo_url,
        # SAML fields: idp_certificate is Fernet-encrypted (D-03 / Pattern D);
        # the other 3 are plaintext (entity IDs and a public URL — not credentials).
        idp_entity_id=data.idp_entity_id,
        idp_sso_url=data.idp_sso_url,
        idp_certificate=(
            encrypt_secret(data.idp_certificate) if data.idp_certificate else None
        ),
        sp_entity_id=data.sp_entity_id,
        scopes=data.scopes,
        default_role=data.default_role,
        group_claim=data.group_claim,
        group_role_mapping=data.group_role_mapping,
        enabled=data.enabled,
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
    db: AsyncSession, enabled_only: bool = False
) -> list[OAuthProvider]:
    """List all OAuth providers, optionally filtering to enabled only."""
    query = select(OAuthProvider).order_by(OAuthProvider.display_name)
    if enabled_only:
        query = query.where(OAuthProvider.enabled.is_(True))
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_enabled_providers(db: AsyncSession) -> list[OAuthProvider]:
    """Shortcut: list only enabled OAuth providers."""
    return await list_providers(db, enabled_only=True)


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
    update_data = data.model_dump(exclude_unset=True)

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
    subject = str(userinfo.get("sub", ""))
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
    if existing_link is not None:
        logger.info(
            "OAuth login: existing link found",
            provider=provider.slug,
            user_id=str(existing_link.user_id),
        )
        return existing_link.user

    # Step 2: Check email match (case-insensitive)
    if email:
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

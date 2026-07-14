"""Verification-email sender for Phase 1231 self-serve signup (SIGNUP-03).

Builds a ``Notification`` with ``data["to"]`` set to the registrant's email
and calls ``send_email`` from the 1229 SMTP channel DIRECTLY — NOT via
``notify()`` (which fans out to admin sinks via EVENT-* dispatch and would
deliver the registrant's link to the admin address instead).

Security notes:
- smtplib/OSError exceptions propagate to the caller; the router maps them to
  a clear, non-leaky HTTP 502 (exception type name only, never the raw repr
  or password — mirrors env_sink secret-free aggregation, T-1231-07).
- The raw verification token is embedded in the URL only; it is never logged
  here (the router must not log it either).
"""

from __future__ import annotations

import structlog

logger = structlog.stdlib.get_logger(__name__)


async def send_verification_email(
    db: "AsyncSession",  # noqa: F821 — type-only import for callers
    *,
    to_email: str,
    raw_token: str,
    request: "Request | None" = None,  # noqa: F821 — type-only import
) -> None:
    """Send an email-verification link to *to_email*.

    Community/self-hosted mode builds the URL from ``PUBLIC_APP_URL.get(db)``
    and retains the historical relative-path fallback when unset. Hosted mode
    instead requires the tenant origin validated by ``TenantContextMiddleware``;
    one fleet-wide setting cannot represent tenant-specific verification links.

    Imports are deferred (Phase 214 deferred-import discipline).

    Args:
        db: Async DB session — used only for ``PUBLIC_APP_URL.get(db)``.
        to_email: The registrant's email address.
        raw_token: The raw opaque verification token (URL-safe base64, 32 bytes).
        request: Request carrying middleware-validated tenant origin in hosted mode.

    Raises:
        smtplib.SMTPException: on SMTP-level failures (auth, server error, …).
        OSError: on connection failures (host unreachable, timeout, …).
        (All exceptions propagate — the router decides the HTTP response.)
    """
    # Deferred imports — Phase 214 discipline.
    from app.core.persistent_config import PUBLIC_APP_URL
    from app.core.public_urls import get_public_app_url
    from app.core.tenancy import is_multi_tenant
    from app.platform.extensions.protocols import Notification
    from app.platform.notifications.smtp_channel import send_email

    if is_multi_tenant():
        base_url = await get_public_app_url(
            db,
            request=request,
            for_external_use=True,
        )
    else:
        # Preserve the historical Community/self-hosted configuration and
        # relative-link fallback byte-for-byte.
        base_url = await PUBLIC_APP_URL.get(db)
    if base_url:
        verify_url = f"{base_url.rstrip('/')}/verify-email?token={raw_token}"
    else:
        # Relative fallback for local/dev where PUBLIC_APP_URL is unset.
        # Operators should configure PUBLIC_APP_URL in production.
        verify_url = f"/verify-email?token={raw_token}"
        logger.warning(
            "verification_email.public_app_url_unset",
            message=(
                "PUBLIC_APP_URL is not configured; verification link is relative. "
                "Set PUBLIC_APP_URL for production deployments."
            ),
        )

    subject = "Verify your email address"
    body = (
        "Welcome to GeoLens!\n\n"
        "Click the link below to verify your email address and activate your account.\n"
        "This link expires in 24 hours.\n\n"
        f"{verify_url}\n\n"
        "If you did not create an account, you can ignore this email."
    )

    notification = Notification(
        event_type="email_verification",
        subject=subject,
        body=body,
        data={"to": to_email},
    )

    # DIRECTLY call send_email — NOT notify() (which routes to admin sinks).
    await send_email(notification)

"""Verification-email sender for self-serve signup (SIGNUP-03).

Calls ``send_email`` directly — NOT ``notify()``, which fans out to admin
sinks and would deliver the registrant's link to the admin address instead.

Security: SMTP/OSError exceptions propagate to the caller for a non-leaky
502 (exception type only, never the raw repr or password). The raw token is
embedded in the URL only and is never logged here (the router must not log
it either).
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

    Community mode builds the URL from ``PUBLIC_APP_URL``; hosted mode
    instead requires the tenant origin validated by ``TenantContextMiddleware``
    — one fleet-wide setting cannot represent tenant-specific links.

    Raises:
        smtplib.SMTPException, OSError: propagate to the caller, which maps
        them to the HTTP response.
    """
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
        base_url = await PUBLIC_APP_URL.get(db)
    if base_url:
        verify_url = f"{base_url.rstrip('/')}/verify-email?token={raw_token}"
    else:
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

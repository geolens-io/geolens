"""Generic outbound webhook channel for GeoLens notifications (NOTIF-03).

POSTs a JSON payload to the operator-configured ``NOTIFICATION_WEBHOOK_URL``
via the already-present ``httpx`` dependency.

Payload: ``{event_type, subject, body, data, text}`` — ``text`` is
"<subject>\\n<body>" so a Slack/Teams incoming-webhook URL (which renders
``{"text": "..."}``) works through this channel with no vendor SDK.

Security (T-1229-04/T-1229-06): ``NOTIFICATION_WEBHOOK_SECRET``, if set,
is sent only as the ``X-Webhook-Secret`` header, revealed via ``reveal()``
at construction — never appended to the URL/query string. The webhook URL
is operator-configured (admin trust boundary); no URL allow-list is
enforced — SSRF risk accepted per design (T-1229-SC).

Timeout: ``httpx.Timeout(10.0, connect=5.0)`` bounds the POST (T-1229-05).

Non-2xx raises ``httpx.HTTPStatusError`` via ``raise_for_status()``;
transport errors propagate. The caller (``EnvConfiguredNotificationSink``)
provides per-channel isolation.
"""

from __future__ import annotations


def _make_client(timeout: "httpx.Timeout") -> "httpx.AsyncClient":  # type: ignore[name-defined]  # noqa: F821
    """Return an ``httpx.AsyncClient`` with *timeout* applied.

    Module-level so tests can monkeypatch it without patching
    ``httpx.AsyncClient`` globally, which would recurse into this function.
    """
    import httpx

    return httpx.AsyncClient(timeout=timeout)


async def post_webhook(notification: "Notification") -> None:  # type: ignore[name-defined]  # noqa: F821
    """POST *notification* as JSON to the configured webhook URL.

    Imports are deferred (Phase 214) so this module pays no import cost
    for deployments that never call it.

    Raises:
        httpx.HTTPStatusError: on non-2xx HTTP response.
        httpx.TransportError: on network-level failures.
    """
    import httpx

    from app.core.config import reveal
    from app.core.config import settings as app_settings

    url = app_settings.notification_webhook_url
    secret = app_settings.notification_webhook_secret  # SecretStr | None — never log

    payload: dict[str, object] = {
        "event_type": notification.event_type,
        "subject": notification.subject,
        "body": notification.body,
        "data": notification.data or {},
        # Slack/Teams compatibility: both render {"text": "..."} (NOTIF-03).
        "text": f"{notification.subject}\n{notification.body}",
    }

    headers: dict[str, str] = {}
    if secret is not None:
        # Reveal only at header-construction; never in the URL/query (T-1229-04).
        headers["X-Webhook-Secret"] = reveal(secret) or ""

    timeout = httpx.Timeout(10.0, connect=5.0)
    async with _make_client(timeout) as client:
        response = await client.post(url, json=payload, headers=headers)
        # Raise on non-2xx so the sink can treat this channel as failed.
        response.raise_for_status()

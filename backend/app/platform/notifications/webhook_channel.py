"""Generic outbound webhook channel for GeoLens notifications (Phase 1229 NOTIF-03).

POSTs a JSON payload to the operator-configured ``NOTIFICATION_WEBHOOK_URL``
via the already-present ``httpx`` dependency (no new package added).

Payload shape:
    {
        "event_type": "<str>",
        "subject":    "<str>",
        "body":       "<str>",
        "data":       {<dict>},
        "text":       "<subject>\\n<body>"
    }

The ``text`` field makes a Slack or Teams incoming-webhook URL work
through this generic channel with no vendor SDK — Slack and Teams both
render ``{"text": "..."}`` as the message body (NOTIF-03).

Security notes (T-1229-04 / T-1229-06):
- If ``NOTIFICATION_WEBHOOK_SECRET`` is configured, it is sent as the
  ``X-Webhook-Secret`` request **header** only, revealed via ``reveal()``
  at the header-construction boundary. It is never appended to the URL
  or a query string.
- The webhook URL is operator-configured (admin trust boundary). No
  URL allow-list is enforced by this channel — that is out of scope
  (T-1229-SC: operator controls the URL; SSRF risk accepted per design).

Timeout (T-1229-05):
- ``httpx.Timeout(10.0, connect=5.0)`` bounds the POST so an
  unreachable URL cannot hang the caller indefinitely.

On non-2xx responses ``response.raise_for_status()`` raises
``httpx.HTTPStatusError``; transport errors propagate as-is. The caller
(``EnvConfiguredNotificationSink``) provides per-channel isolation.
"""

from __future__ import annotations


def _make_client(timeout: "httpx.Timeout") -> "httpx.AsyncClient":  # type: ignore[name-defined]  # noqa: F821
    """Return an ``httpx.AsyncClient`` with *timeout* applied.

    Extracted as a module-level function so tests can monkeypatch it
    without patching ``httpx.AsyncClient`` globally (which causes
    recursion when the patch lambda itself calls ``httpx.AsyncClient``).
    """
    import httpx

    return httpx.AsyncClient(timeout=timeout)


async def post_webhook(notification: "Notification") -> None:  # type: ignore[name-defined]  # noqa: F821
    """POST *notification* as JSON to the configured webhook URL.

    Imports are deferred (Phase 214 deferred-import discipline) so this
    module does not pay import cost for deployments that never call it.

    Raises:
        httpx.HTTPStatusError: on non-2xx HTTP response.
        httpx.TransportError: on network-level failures (unreachable host, …).
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
        # Slack/Teams incoming-webhook compatibility: both render {"text": "..."}
        # as the message body with no vendor SDK required (NOTIF-03).
        "text": f"{notification.subject}\n{notification.body}",
    }

    headers: dict[str, str] = {}
    if secret is not None:
        # Reveal the secret ONLY at the header-construction boundary.
        # Never append it to the URL or query string (T-1229-04).
        headers["X-Webhook-Secret"] = reveal(secret) or ""

    timeout = httpx.Timeout(10.0, connect=5.0)
    async with _make_client(timeout) as client:
        response = await client.post(url, json=payload, headers=headers)
        # Raise on non-2xx so the sink can treat this channel as failed.
        response.raise_for_status()

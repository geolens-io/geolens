"""Shared TNM Access API helpers for the ADK marketing-data scripts."""

from __future__ import annotations

import json
import sys
import asyncio

import httpx


class TnmAccessError(RuntimeError):
    """Raised when TNM cannot return a usable JSON response."""


async def fetch_tnm_json(
    client: httpx.AsyncClient,
    endpoint: str,
    params: dict[str, object],
    *,
    timeout: float = 60,
    max_attempts: int = 3,
) -> dict:
    """GET a TNM JSON endpoint with retry and useful invalid-JSON errors.

    TNM occasionally returns HTTP 200 with an `application/json` content type
    and a pseudo-JSON body such as `{errorMessage=[BadRequest] ...}`. Calling
    `Response.json()` directly turns that into an opaque traceback, so keep the
    retry/error handling in one place for the marketing-data scripts.
    """

    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = await client.get(endpoint, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except json.JSONDecodeError as exc:
            last_error = exc
            content_type = resp.headers.get("content-type", "")
            body = resp.text[:500].replace("\n", " ")
            message = (
                "TNM returned invalid JSON "
                f"(status={resp.status_code}, content-type={content_type!r}, "
                f"body_prefix={body!r})"
            )
        except httpx.HTTPStatusError as exc:
            last_error = exc
            status = exc.response.status_code
            body = exc.response.text[:500].replace("\n", " ")
            message = f"TNM returned HTTP {status} body_prefix={body!r}"
            if status < 500:
                raise TnmAccessError(message) from exc
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last_error = exc
            message = f"TNM request failed: {exc}"

        if attempt < max_attempts:
            delay = 2 ** attempt
            print(
                f"  RETRY TNM query {attempt}/{max_attempts} after {delay}s: {message}",
                file=sys.stderr,
            )
            await asyncio.sleep(delay)
            continue
        raise TnmAccessError(f"{message} after {max_attempts} attempts") from last_error

    raise TnmAccessError("TNM query failed for an unknown reason")

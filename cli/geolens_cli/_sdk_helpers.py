# SPDX-License-Identifier: Apache-2.0
"""SDK call helpers — Response → T translator + httpx-error → exit-code mapper.

Hand-maintained — NOT regenerated. Centralizes the SDK call boundary so each
command's body is free of error-mapping noise (CONTEXT.md D-32, D-33).

Note on httpx import: this module imports httpx ONLY for exception types
used in error mapping. The httpx instance comes from the SDK
(client.get_httpx_client()); the CLI never constructs an httpx.Client.
OCCLI-06 enforcement is on the dep list (cli/pyproject.toml has no httpx
direct dep — it's transitive via the geolens SDK). The `cli-lint` grep gate
in Plan 06 is scoped to `^(import|from) (httpx|requests)` lines that
construct clients; httpx exception imports here are explicitly allowed.
"""
from __future__ import annotations

from typing import Any, Callable, TypeVar

import typer

T = TypeVar("T")

# Exit codes per CONTEXT.md D-32
EXIT_OK = 0
EXIT_GENERIC = 1
EXIT_USAGE = 2
EXIT_AUTH = 3
EXIT_NETWORK = 4
EXIT_SERVER = 5

#: fix(#1778): the SDK builds its httpx client with timeout=None (no limit
#: at all, not httpx's 5s default — see main.py's AppState.sdk()), so
#: without a default here every command (login, whoami, status, publish,
#: apply, export stac, analysis preview, default refresh) hangs forever
#: against a host that black-holes packets, and this module's own
#: httpx.TimeoutException branch above can never fire. A plain float
#: (not httpx.Timeout) so callers stay clear of OCCLI-06's import
#: restriction; httpx accepts either. The long upload stage in publish.py
#: overrides this with a more generous bound for the file transfer itself.
DEFAULT_HTTP_TIMEOUT_SECONDS: float = 30.0


class DeadlineTimeout(Exception):
    """An SDK request consumed the caller's operation deadline."""


def unwrap(resp: Any, *, expected: int = 200) -> Any:
    """Translate an SDK Response into either parsed model or typer.Exit.

    Maps HTTP status to exit codes:
      expected (default 200) → return resp.parsed
      401, 403 → exit 3 (EXIT_AUTH)
      5xx      → exit 5 (EXIT_SERVER)
      other    → exit 1 (EXIT_GENERIC)
    """
    from geolens.models.problem_detail import ProblemDetail  # lazy

    sc = int(resp.status_code)
    if sc == expected:
        if isinstance(resp.parsed, ProblemDetail):
            typer.secho(f"Error: {resp.parsed.detail}", fg="red", err=True)
            raise typer.Exit(EXIT_SERVER if sc >= 500 else EXIT_GENERIC)
        return resp.parsed

    detail = ""
    if isinstance(resp.parsed, ProblemDetail):
        detail = f": {resp.parsed.detail}"

    if sc == 401:
        typer.secho(f"Authentication required{detail}. Run `geolens login` first.", fg="red", err=True)
        raise typer.Exit(EXIT_AUTH)
    if sc == 403:
        typer.secho(f"Permission denied{detail}", fg="red", err=True)
        raise typer.Exit(EXIT_AUTH)
    if 500 <= sc <= 599:
        typer.secho(f"Server error ({sc}){detail}", fg="red", err=True)
        raise typer.Exit(EXIT_SERVER)
    typer.secho(f"Request failed ({sc}){detail}", fg="red", err=True)
    raise typer.Exit(EXIT_GENERIC)


def call_sdk(
    fn: Callable[..., Any],
    *,
    deadline_expired: Callable[[], bool] | None = None,
    **kwargs: Any,
) -> Any:
    """Run a sync_detailed call, mapping httpx exceptions to exit codes."""
    import httpx  # lazy — only for exception types

    try:
        return fn(**kwargs)
    except httpx.TimeoutException:
        if deadline_expired is not None and deadline_expired():
            raise DeadlineTimeout from None
        typer.secho("Request timed out", fg="red", err=True)
        raise typer.Exit(EXIT_NETWORK)
    except httpx.NetworkError as exc:
        typer.secho(f"Network error: {exc}", fg="red", err=True)
        raise typer.Exit(EXIT_NETWORK)


def call_sdk_with_reauth(
    fn: Callable[..., Any],
    *,
    instance: str,
    rebuild_client: Callable[[], Any],
    client_kwarg: str = "client",
    deadline_expired: Callable[[], bool] | None = None,
    **kwargs: Any,
) -> Any:
    """Like ``call_sdk``, but refresh-retries once on 401/403 (D-13).

    fix(#1778): a stored refresh token was only ever spent by ``whoami`` —
    every other command hard-failed on an expired access token even though
    login stores a refresh token whenever the server returns one. This
    generalizes ``whoami``'s inline retry so other commands can opt in
    without duplicating it: on 401/403, attempt one
    ``auth.try_refresh(instance)``; if it yields a new access token,
    ``rebuild_client()`` is called to obtain a client carrying the rotated
    token and the request is retried once with it under ``client_kwarg``.
    """
    from . import auth as _auth  # lazy: avoid an import cycle with main.py

    resp = call_sdk(fn, deadline_expired=deadline_expired, **kwargs)
    if int(resp.status_code) in (401, 403):
        new_access = _auth.try_refresh(instance)
        if new_access:
            sdk = rebuild_client()
            kwargs[client_kwarg] = sdk.client
            resp = call_sdk(fn, deadline_expired=deadline_expired, **kwargs)
    return resp

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


def make_client(
    instance: str,
    *,
    bearer_token: str | None = None,
    api_key: str | None = None,
) -> Any:
    """Construct a GeolensClient bound to DEFAULT_HTTP_TIMEOUT_SECONDS.

    fix(#1778 review round 2): every construction of the SDK's generated
    client in this package must go through here — AppState.sdk(), the
    interactive login flow, auth.try_refresh(), and
    call_sdk_with_reauth's retry client had each been given the timeout
    bound (or missed it, in login's case) independently, so a new call
    site could ship unbounded with nothing to catch it.
    tests/test_client_construction.py greps the package for the
    construction call and asserts the only occurrence is inside this
    function's body.

    fix(#1778 review round 3): the returned object also carries
    ``.credential_kind`` — one of "bearer", "api_key", "anonymous" — so a
    caller that refresh-retries on 401 (call_sdk_with_reauth) can tell
    whether the request that got a 401 even HAS a refreshable bearer
    session, rather than assuming one. This is set on the hand-maintained
    GeolensClient wrapper (sdks/python/geolens/auth.py), not on the
    generated ``.client`` attrs object it wraps — the generated class is
    ``@define``-slotted and rejects new attributes. Returning a tuple or
    a separate dataclass instead was rejected: AppState.sdk() returns
    this object directly and roughly a dozen call sites across the CLI
    do ``state.sdk().client`` — changing the return shape here would
    ripple through all of them for a fix that only two call sites
    (whoami, status) need.
    """
    from geolens import GeolensClient  # lazy: keep `geolens --help` snappy

    client = GeolensClient(base_url=instance, bearer_token=bearer_token, api_key=api_key)
    client.client.get_httpx_client().timeout = DEFAULT_HTTP_TIMEOUT_SECONDS
    if bearer_token:
        client.credential_kind = "bearer"
    elif api_key:
        client.credential_kind = "api_key"
    else:
        client.credential_kind = "anonymous"
    return client


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
    credential_kind: str,
    client_kwarg: str = "client",
    deadline_expired: Callable[[], bool] | None = None,
    **kwargs: Any,
) -> Any:
    """Like ``call_sdk``, but refresh-retries once on 401 (D-13).

    fix(#1778): a stored refresh token was only ever spent by ``whoami`` —
    every other command hard-failed on an expired access token even though
    login stores a refresh token whenever the server returns one. This
    generalizes ``whoami``'s inline retry so other commands can opt in
    without duplicating it: on 401, attempt one
    ``auth.try_refresh(instance)``; if it yields a new access token, the
    request is retried once with a client built directly from that token.

    fix(#1778 review round 1):

    - 401 only, not 403. A 403 is a real permission denial, not an
      expired token — refreshing on it let a legacy profile holding both
      an API key and a stale refresh token silently retry as a different
      (renewed-bearer) identity instead of surfacing the denial.
    - The retry client is built from ``new_access`` directly via
      ``make_client(instance, bearer_token=new_access)`` rather than by
      re-resolving credentials (the previous ``rebuild_client()``
      parameter). Re-resolving picks GEOLENS_TOKEN over a stored
      credential (D-35), so with an expired env token and a valid stored
      refresh token, the retry kept resending the same expired env token
      and burned the rotated refresh token for nothing.

    fix(#1778 review round 2): the retry client above (and every other
    client construction in this package) now goes through
    ``make_client()`` so the timeout bound is structurally guaranteed
    rather than repeated at each call site.

    fix(#1778 review round 3): ``credential_kind`` — the value
    ``make_client()`` tagged the ORIGINAL request's client with — gates
    the refresh attempt to bearer clients only. An API-key client gets a
    401 (not 403 — ``_resolve_api_key()`` returns None for a revoked or
    mistyped key, so the backend reports it the same as no credential at
    all) for a reason that has nothing to do with a stored bearer
    session. A legacy profile can hold both an API key AND an old
    refresh token; refreshing that unrelated bearer session and retrying
    with it would silently switch the retry to a different identity
    instead of reporting the invalid key. Anonymous clients are skipped
    for the same reason — there is no session to refresh.
    """
    from . import auth as _auth  # lazy: avoid an import cycle with main.py

    resp = call_sdk(fn, deadline_expired=deadline_expired, **kwargs)
    if int(resp.status_code) == 401 and credential_kind == "bearer":
        new_access = _auth.try_refresh(instance)
        if new_access:
            retry_sdk = make_client(instance, bearer_token=new_access)
            kwargs[client_kwarg] = retry_sdk.client
            resp = call_sdk(fn, deadline_expired=deadline_expired, **kwargs)
    return resp

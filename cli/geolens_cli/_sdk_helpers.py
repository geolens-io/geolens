# SPDX-License-Identifier: Apache-2.0
"""SDK call helpers — Response → T translator + httpx-error → exit-code mapper.

Hand-maintained — NOT regenerated. Centralizes the SDK call boundary so each
command's body is free of error-mapping noise.

Note on httpx import: this module imports httpx ONLY for exception types
used in error mapping. The httpx instance comes from the SDK
(client.get_httpx_client()); the CLI never constructs an httpx.Client.
cli/pyproject.toml has no direct httpx dependency; it is transitive via the
geolens SDK.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Mapping, TypeVar

import typer

# Stdlib logging, not structlog: unconfigured structlog prints every call to
# stdout, which would corrupt --json output. A logger with no handler stays
# silent below WARNING.
log = logging.getLogger(__name__)

T = TypeVar("T")

# Exit codes
EXIT_OK = 0
EXIT_GENERIC = 1
EXIT_USAGE = 2
EXIT_AUTH = 3
EXIT_NETWORK = 4
EXIT_SERVER = 5
EXIT_BLOCKED = 6

#: The SDK builds its httpx client with timeout=None (no limit at all, not
#: httpx's 5s default; see main.py's AppState.sdk()), so without a default
#: every command would hang forever against a host that black-holes packets.
#: A plain float (not httpx.Timeout) keeps callers clear of the httpx import
#: restriction; httpx accepts either. long_request_timeout() overrides it for
#: requests that carry a file body or that the backend processes synchronously.
DEFAULT_HTTP_TIMEOUT_SECONDS: float = 30.0

#: The backend's largest synchronous deadline that CLI call sites hit is
#: OGRINFO_TIMEOUT_SECONDS = 300s (backend/app/processing/ingest/ogr.py, the
#: ingest/reupload preview probe). This is that with a 2x margin, as one shared
#: bound instead of a guess per call site.
EXTENDED_REQUEST_TIMEOUT_SECONDS: float = 600.0


class DeadlineTimeout(Exception):
    """An SDK request consumed the caller's operation deadline."""


class PollDeadlineExceeded(Exception):
    """A poll_until() deadline passed while a per-request timeout was being
    retried, so no response was read in the final stretch.

    Carries no message: the caller has its own deadline in scope and words the
    failure itself ("still running after 120s" vs a bare network error).
    """


def poll_until(
    fetch: Callable[[], Any],
    *,
    deadline: float,
    interval: float,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
) -> Any:
    """Call ``fetch()``, retrying on ``httpx.TimeoutException`` until it
    succeeds or ``deadline`` (a ``monotonic()`` timestamp) is reached.

    Every ``--wait`` poll loop (``publish.resolve_dataset_id``,
    ``refresh.wait_for_refresh``) retries a per-request timeout through this
    helper; a plain ``call_sdk()`` would exit ``EXIT_NETWORK`` on one slow
    status GET even with the operation's deadline far off. ``fetch`` is
    typically ``lambda: call_sdk(fn, reraise_timeout=True, ...)``.

    Timing invariants, pinned in
    ``tests/test_poll_retry_usage.py::TestPollUntilDeadlineDiscipline``:

    - No ``fetch()`` starts after ``deadline``: ``remaining`` is checked
      before every call, and a sleep is capped to ``min(interval, remaining)``
      so it cannot carry the loop past the deadline.
    - Total wall time is bounded by ``deadline`` plus one in-flight request's
      own timeout.
    - ``deadline = float("inf")`` (``analysis.POLL_FOREVER``, the default
      ``--wait``) never raises and always sleeps the full ``interval``.
    - A ``fetch()`` that succeeds returns immediately with no deadline check,
      even if it straddled the deadline.

    Raises ``PollDeadlineExceeded`` once ``deadline`` is reached without a
    successful call; the caller decides what that means.
    """
    import httpx  # lazy — only for exception types

    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise PollDeadlineExceeded
        try:
            return fetch()
        except httpx.TimeoutException:
            log.debug("poll_request_timed_out")
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise PollDeadlineExceeded from None
            sleep(min(interval, remaining))


@contextmanager
def long_request_timeout(
    client: Any, *, timeout: float | None = EXTENDED_REQUEST_TIMEOUT_SECONDS
) -> Iterator[Any]:
    """Temporarily raise ``client``'s httpx transport timeout to ``timeout``
    (default EXTENDED_REQUEST_TIMEOUT_SECONDS), restoring the original
    afterward, even on an exception.

    ``timeout`` overrides the fixed default for a caller with its own bound,
    such as manifest_apply.py's batch-aware budget for a many-entry manifest.

    ``timeout=None`` means no client-side read timeout: an explicit operator
    opt-out (manifest apply's ``--timeout 0``). It is built as an
    ``httpx.Timeout`` with ``read``/``write``/``pool`` None but ``connect``
    still bound to ``DEFAULT_HTTP_TIMEOUT_SECONDS``, because a hung TCP
    handshake is a network failure, not a slow server.

    Every request the backend documents as long-running before it responds
    goes through this, not just ones with a file body: the ingest/reupload
    preview requests wait on a synchronous ogrinfo probe of up to 300s.
    ``LONG_RUNNING_SDK_FUNCTIONS`` below names those SDK functions, and
    ``tests/test_long_request_timeout_usage.py`` asserts every call to one sits
    inside a ``with long_request_timeout(client):`` block and that each name
    still resolves against the generated SDK.
    """
    httpx_client = client.get_httpx_client()
    original_timeout = httpx_client.timeout
    if timeout is None:
        import httpx  # lazy -- only for this Timeout value construction

        httpx_client.timeout = httpx.Timeout(
            connect=DEFAULT_HTTP_TIMEOUT_SECONDS, read=None, write=None, pool=None
        )
    else:
        httpx_client.timeout = timeout
    try:
        yield httpx_client
    finally:
        httpx_client.timeout = original_timeout


#: Generated SDK functions the backend documents as long-running before they
#: respond. Each value is the (module, attribute) pair that
#: tests/test_long_request_timeout_usage.py resolves against the installed
#: ``geolens`` SDK.
#:
#: - ``ingest_preview`` / ``reupload_preview``: both run
#:   ``run_ogrinfo_preview()`` server-side, bounded by
#:   ``OGRINFO_TIMEOUT_SECONDS = 300`` (backend/app/processing/ingest/ogr.py).
#:   They carry no file body, so a ``files=``-keyed check would miss them.
#: - ``analysis_materialize``: expects a synchronous 200 (submit-time
#:   validation/setup work), not a fire-and-forget 202.
#: - ``analysis_preview``: ``run_analysis_preview`` can run up to three
#:   sequential sandbox queries (bbox source count, capped geometry query,
#:   match/total count) of up to ``DEFAULT_TIMEOUT_MS = 10_000`` each
#:   (backend/app/platform/sandbox/executor.py). The count queries degrade to
#:   ``None`` rather than failing, so a valid preview can take ~30s, right at
#:   ``DEFAULT_HTTP_TIMEOUT_SECONDS``.
#: - ``service_probe`` / ``service_preview`` (``arcgis migrate``): the ArcGIS
#:   probe reads the service document for up to 30 s and then enriches feature
#:   counts under its own 30 s deadline; the preview reads the layer's metadata
#:   and sample rows, or runs ogrinfo, before it responds.
#:
#: Not registered: commit and refresh trigger return 202 and queue; the CLI
#: calls no ``/services`` connector, file-download or backfill endpoint; VRT/COG
#: creation runs only in the background worker. The manifest apply POST
#: (manifest_apply.post_manifest_apply) is a raw ``httpx_client.post()``, so it
#: has no SDK function to register and has its own pin test
#: (test_manifest_apply.py::test_post_manifest_apply_raises_the_timeout_then_restores_it).
LONG_RUNNING_SDK_FUNCTIONS: dict[str, tuple[str, str]] = {
    "ingest_preview": (
        "geolens.api.datasets.preview_file_ingest_preview_job_id_post",
        "sync_detailed",
    ),
    "reupload_preview": (
        "geolens.api.datasets_reupload."
        "reupload_preview_datasets_dataset_id_reupload_job_id_preview_post",
        "sync_detailed",
    ),
    "analysis_materialize": (
        "geolens.api.datasets_analysis."
        "analysis_materialize_endpoint_datasets_dataset_id_analysis_materialize_post",
        "sync_detailed",
    ),
    "analysis_preview": (
        "geolens.api.datasets_analysis."
        "analysis_preview_endpoint_datasets_dataset_id_analysis_preview_post",
        "sync_detailed",
    ),
    "service_probe": (
        "geolens.api.datasets.probe_service_url_services_probe_post",
        "sync_detailed",
    ),
    "service_preview": (
        "geolens.api.datasets.preview_service_layer_services_preview_post",
        "sync_detailed",
    ),
}


def make_client(
    instance: str,
    *,
    bearer_token: str | None = None,
    api_key: str | None = None,
    provenance: str | None = None,
) -> Any:
    """Construct a GeolensClient bound to DEFAULT_HTTP_TIMEOUT_SECONDS.

    Every construction of the SDK's generated client in this package goes
    through here (AppState.sdk(), the interactive login flow,
    auth.try_refresh(), call_sdk_with_reauth's retry client) so none ships
    unbounded. tests/test_client_construction.py asserts the construction call
    appears only in this function.

    The returned object carries ``.credential_kind`` ("bearer", "api_key" or
    "anonymous") so a caller that refresh-retries on 401 can tell whether the
    request even had a refreshable bearer session. It is set on the
    hand-maintained GeolensClient wrapper (sdks/python/geolens/auth.py), since
    the generated ``.client`` class is ``@define``-slotted and rejects new
    attributes.

    ``credential_kind`` alone cannot tell a GEOLENS_TOKEN bearer from one
    loaded from a stored login, and call_sdk_with_reauth must not spend a
    stored refresh token to rescue an env-var override, which would silently
    continue the command as a different principal. ``provenance`` records where
    the credential came from ("env", "stored-bearer", "stored-api-key");
    AppState.sdk() is the only caller that sets it meaningfully. It defaults to
    ``credential_kind``, which never equals "env".
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
    client.credential_provenance = provenance or client.credential_kind
    return client


def detail_text(detail: Any) -> str:
    """A ProblemDetail.detail value as printable text.

    A coded refusal's detail is a {"code", "message", ...} object; this
    prints its message instead of the object's repr.
    """
    if isinstance(detail, str):
        return detail
    payload = detail if isinstance(detail, Mapping) else None
    if payload is None:
        to_dict = getattr(detail, "to_dict", None)
        payload = to_dict() if callable(to_dict) else None
    message = payload.get("message") if payload else None
    return message if isinstance(message, str) else str(detail)


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
            typer.secho(f"Error: {detail_text(resp.parsed.detail)}", fg="red", err=True)
            raise typer.Exit(EXIT_SERVER if sc >= 500 else EXIT_GENERIC)
        return resp.parsed

    detail = ""
    if isinstance(resp.parsed, ProblemDetail):
        detail = f": {detail_text(resp.parsed.detail)}"

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
    reraise_timeout: bool = False,
    on_timeout: Callable[[], BaseException] | None = None,
    **kwargs: Any,
) -> Any:
    """Run a sync_detailed call, mapping httpx exceptions to exit codes.

    ``reraise_timeout=True`` re-raises the plain ``httpx.TimeoutException``
    instead of mapping it to ``typer.Exit(EXIT_NETWORK)``, for a poll loop that
    treats one slow request as retryable (see ``publish.resolve_dataset_id``).
    ``deadline_expired`` is checked first regardless: when it returns True the
    timeout becomes ``DeadlineTimeout``.

    ``on_timeout``, when given, is called with no arguments to produce a custom
    exception raised instead of the raw one, for a caller (manifest_apply.py)
    that must not import ``httpx`` but needs to tell "this request timed out"
    apart from other failures, with its own data attached. It takes priority
    over ``reraise_timeout``.

    ``on_timeout`` fires only for ``httpx.ReadTimeout``: the request was fully
    sent, so the server may already have accepted the work (manifest apply's
    "re-running may duplicate an in-flight entry" guidance). Connect and pool
    timeouts fire before anything is sent, and a write timeout before the
    request finished sending, so they fall through to ``reraise_timeout`` or the
    ordinary network-failure path.
    """
    import httpx  # lazy — only for exception types

    try:
        return fn(**kwargs)
    except httpx.TimeoutException as exc:
        if deadline_expired is not None and deadline_expired():
            raise DeadlineTimeout from None
        if on_timeout is not None and isinstance(exc, httpx.ReadTimeout):
            raise on_timeout() from exc
        if reraise_timeout:
            raise
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
    credential_provenance: str | None = None,
    client_kwarg: str = "client",
    deadline_expired: Callable[[], bool] | None = None,
    on_reauthenticated: Callable[[Any], None] | None = None,
    **kwargs: Any,
) -> Any:
    """Retry one 401 with the paired refresh token for a stored bearer.

    API keys, anonymous clients, environment tokens, and 403 responses cannot
    switch identity through this helper. The retry uses the newly issued
    access token directly. ``on_reauthenticated`` exposes that replacement
    client to callers that make subsequent requests.
    """
    from . import auth as _auth  # lazy: avoid an import cycle with main.py

    resp = call_sdk(fn, deadline_expired=deadline_expired, **kwargs)
    if int(resp.status_code) == 401 and credential_kind == "bearer":
        if credential_provenance == "stored-bearer":
            new_access = _auth.try_refresh(instance)
            if new_access:
                retry_sdk = make_client(
                    instance, bearer_token=new_access, provenance="stored-bearer"
                )
                kwargs[client_kwarg] = retry_sdk.client
                if on_reauthenticated is not None:
                    on_reauthenticated(retry_sdk.client)
                resp = call_sdk(fn, deadline_expired=deadline_expired, **kwargs)
        elif credential_provenance == "env":
            typer.secho(
                "GEOLENS_TOKEN was rejected by the server (expired or "
                "invalid). A stored login's refresh token is never spent "
                "to rescue an env-var override -- that could silently "
                "continue the command as a different, stored identity. "
                "Update or unset GEOLENS_TOKEN to use a stored login "
                "instead.",
                fg="red",
                err=True,
            )
            raise typer.Exit(EXIT_AUTH)
    return resp

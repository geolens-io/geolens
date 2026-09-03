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

import logging
from contextlib import contextmanager
from typing import Any, Callable, Iterator, TypeVar

import typer

# fix(#1778 review round 8): stdlib logging, not structlog. structlog's
# unconfigured default is a PrintLogger that writes EVERY call straight to
# stdout regardless of level — this package configures no structlog
# handler anywhere, so a log.debug() here would corrupt any --json
# command's stdout the moment a poll retried. logging.getLogger() with no
# handler configured is silent for anything below WARNING by design
# (the "handler of last resort"), which is exactly what an internal
# debug breadcrumb should be until someone deliberately wires up logging.
log = logging.getLogger(__name__)

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
#: restriction; httpx accepts either. long_request_timeout() below overrides
#: this with a more generous bound for requests that carry a file body or
#: that the backend processes synchronously before responding.
DEFAULT_HTTP_TIMEOUT_SECONDS: float = 30.0

#: fix(#1778 review round 5, extended round 6): AppState.sdk()'s 30s
#: default is too short for a request the BACKEND documents as
#: long-running before it responds. The largest backend-declared
#: deadline this package's call sites hit is
#: OGRINFO_TIMEOUT_SECONDS = 300s (backend/app/processing/ingest/ogr.py)
#: for the ingest/reupload preview step's ogrinfo probe; this is that
#: plus a 2x margin, one shared bound so there is a single number to
#: tune, not one guess per call site.
EXTENDED_REQUEST_TIMEOUT_SECONDS: float = 600.0


class DeadlineTimeout(Exception):
    """An SDK request consumed the caller's operation deadline."""


class PollDeadlineExceeded(Exception):
    """A poll_until() loop's own deadline was reached WHILE a per-request
    timeout was being retried — i.e., no response was ever read during
    that final stretch. Distinct from a caller's own "the job is still
    pending after the deadline" case: that one happens after at least
    one SUCCESSFUL read, so it never reaches poll_until() at all — the
    caller's own loop just stops calling it.

    Carries no formatted message: the caller already has its own
    ``timeout``/deadline value in scope (this is raised back into the
    same call that supplied ``deadline`` to ``poll_until``) and knows
    its own wording — e.g. "still running after 120s" vs a bare network
    message — better than a generic one minted here from the bare
    monotonic() timestamp would.
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

    fix(#1778 review round 8): every ``--wait`` poll loop in this
    package (``publish.resolve_dataset_id``, ``refresh.wait_for_refresh``)
    now retries a per-request timeout through this ONE helper instead of
    each open-coding its own try/except — ``wait_for_refresh`` still
    called plain ``call_sdk()`` (no ``reraise_timeout``), so one slow
    status GET made ``geolens refresh --wait`` exit ``EXIT_NETWORK``
    immediately even with the operation's own deadline nowhere near
    reached. ``fetch`` is expected to be something like
    ``lambda: call_sdk(fn, reraise_timeout=True, ...)`` — ``poll_until``
    itself only handles the retry-vs-give-up decision, not the SDK call.

    A per-request timeout is logged at debug and slept past
    (``interval``) rather than treated as fatal. Raises
    ``PollDeadlineExceeded`` once ``deadline`` is reached without a
    successful call; the caller decides what that means (e.g.
    ``resolve_dataset_id`` exits ``EXIT_NETWORK`` naming the deadline,
    matching round 7's behavior). A SUCCESSFUL call's result is
    returned as-is on the first attempt that doesn't raise — the caller
    decides what's terminal about it; ``poll_until`` doesn't loop past a
    success.
    """
    import httpx  # lazy — only for exception types

    while True:
        try:
            return fetch()
        except httpx.TimeoutException:
            log.debug("poll_request_timed_out")
            if monotonic() >= deadline:
                raise PollDeadlineExceeded from None
            sleep(interval)


@contextmanager
def long_request_timeout(client: Any) -> Iterator[Any]:
    """Temporarily raise ``client``'s httpx transport timeout to
    EXTENDED_REQUEST_TIMEOUT_SECONDS, restoring the original afterward.

    fix(#1778 review round 5): every CLI request that carries a file
    body must go through this — previously each call site open-coded
    its own save/override/restore (or, in replace.py's and
    manifest_apply.py's case, never raised the bound at all and just
    ate whatever AppState.sdk()'s 30s default left it with).

    fix(#1778 review round 6): the class is bigger than "carries a
    file body" — round 5's structural gate keyed on ``files=`` and
    still missed the ingest/reupload preview requests (main.py), which
    have no multipart body but wait on the backend's synchronous
    ogrinfo probe (up to 300s, OGRINFO_TIMEOUT_SECONDS). The real
    classification is "every request the backend documents as
    long-running before it responds" — carrying a file is one way a
    request earns that, not the definition. This module now also keeps
    ``LONG_RUNNING_SDK_FUNCTIONS`` (below), naming every generated SDK
    function known to be long-running by that definition;
    ``tests/test_long_request_timeout_usage.py`` structurally asserts
    every call to one of those functions sits inside a
    ``with long_request_timeout(client):`` block, and separately
    asserts each name in the registry still resolves against the
    generated SDK (so a rename there fails the test loudly instead of
    silently dropping a call site out of coverage). Routing every one
    through a single helper closes the class: a new call site with the
    same shape has nowhere else to get its timeout from.

    Restored unconditionally (even on an exception) so a later request
    on this same client isn't left with the extended bound.
    """
    httpx_client = client.get_httpx_client()
    original_timeout = httpx_client.timeout
    httpx_client.timeout = EXTENDED_REQUEST_TIMEOUT_SECONDS
    try:
        yield httpx_client
    finally:
        httpx_client.timeout = original_timeout


#: fix(#1778 review round 6): every generated SDK function this package
#: calls that the BACKEND documents as long-running before it responds —
#: not just the ones with a multipart body. Keyed by a short display
#: name; each value is the (module, attribute) pair
#: tests/test_long_request_timeout_usage.py resolves against the
#: installed ``geolens`` SDK, so a rename on either side (this registry
#: or the generated module) fails that test instead of silently
#: dropping a call site out of coverage.
#:
#: - ``ingest_preview`` / ``reupload_preview``: both call
#:   ``run_ogrinfo_preview()`` server-side (backend/app/processing/
#:   ingest/router.py, backend/app/modules/catalog/datasets/api/
#:   router_reupload.py), bounded by
#:   ``OGRINFO_TIMEOUT_SECONDS = 300`` (backend/app/processing/ingest/
#:   ogr.py) — confirmed the source of the round-6 finding (main.py's
#:   publish/replace Stage 2 previews carry no file body, so round 5's
#:   ``files=``-keyed gate missed them).
#: - ``analysis_materialize``: expects a synchronous 200 back (submit-
#:   time validation/setup work), not a fire-and-forget 202 — already
#:   covered since round 5, kept here so the registry is the single
#:   list this test enumerates from.
#: - ``analysis_preview`` (fix(#1778 review round 11)): the backend's
#:   ``run_analysis_preview`` (backend/app/modules/catalog/datasets/
#:   domain/service_analysis.py) can run up to three SEQUENTIAL
#:   sandbox queries before responding — a bbox-scoped source count
#:   (``_resolve_bbox_source_count``), the capped geometry query
#:   (``execute_safe``), and an uncapped match/total count
#:   (``_resolve_match_count``) — each on its own connection through
#:   ``execute_safe``'s ``DEFAULT_TIMEOUT_MS = 10_000`` (backend/app/
#:   platform/sandbox/executor.py). The two count queries degrade to
#:   ``None`` on a ``SandboxError`` (including their own timeout) rather
#:   than failing the preview, so a slow-but-valid preview legitimately
#:   spends up to ~30s server-side (3 x 10s) before the geometry result
#:   comes back — right at, or past, ``DEFAULT_HTTP_TIMEOUT_SECONDS``.
#:
#: Every other backend route with its own timeout budget was checked
#: against the CLI's actual call sites and rejected, with the fact that
#: rules each out:
#:
#: - commit/finalize: publish and reupload commit both queue a
#:   background job and return 202/202 immediately — CommitRequest/
#:   ReuploadCommitRequest handlers do no synchronous ingest work.
#: - refresh trigger: ``refresh_dataset_...`` also returns 202 and
#:   queues (``REFRESH_ACCEPTED_STATUS``) — geolens_cli/refresh.py's
#:   ``start_refresh`` asserts exactly that status.
#: - service preview (``run_service_preview``, backend/app/modules/
#:   catalog/sources/preview.py) and every other ``/services`` connector
#:   op (bounded by ``_CONNECTOR_OPERATION_TIMEOUT_SECONDS = 30.0``,
#:   backend/app/modules/catalog/sources/router.py): IS long-running
#:   server-side, but no CLI command calls any
#:   ``.../services/...`` endpoint today — the CLI has no service-
#:   connector surface at all.
#: - dataset file export/download (backend/app/processing/export/
#:   router.py, backed by ogr2ogr subprocess export bounded by
#:   ``EDGE_PROXY_READ_TIMEOUT_SECONDS = 600``): the CLI's only
#:   ``export`` subcommand is ``export stac``
#:   (geolens_cli/export_stac.py), which calls the STAC item metadata
#:   endpoint, not the file-download endpoint — no CLI command streams
#:   a file response today.
#: - VRT / COG raster creation (backend/app/processing/raster/vrt.py,
#:   ``GDAL_SUBPROCESS_TIMEOUT_SECONDS = 3600``): only ever invoked from
#:   the Procrastinate background worker (backend/app/processing/
#:   ingest/tasks_vrt.py), never on a synchronous request path any CLI
#:   command reaches.
#: - backfills and bulk operations: the CLI has no backfill or bulk
#:   command of any kind (nothing calls a backend route by that name),
#:   so there is no call site to register regardless of the backend's
#:   own timeout shape.
#: - publish's keyword/collection-membership POSTs
#:   (``_apply_tags``/``_apply_collection`` in geolens_cli/publish.py):
#:   plain single-row ORM writes/lookups with no elevated backend
#:   timeout budget documented anywhere — ordinary request-scoped work,
#:   not "long-running" by this registry's definition.
#:
#: The manifest apply POST (manifest_apply.post_manifest_apply) is also
#: long-running but is a raw ``httpx_client.post()`` call, not a
#: generated SDK function — it has no name to register here and is
#: covered by its own dedicated pin test instead
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
}


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
    reraise_timeout: bool = False,
    **kwargs: Any,
) -> Any:
    """Run a sync_detailed call, mapping httpx exceptions to exit codes.

    fix(#1778 review round 7): ``reraise_timeout=True`` re-raises the
    plain ``httpx.TimeoutException`` to the caller instead of mapping it
    to ``typer.Exit(EXIT_NETWORK)``, for a poll loop that wants to treat
    one slow request as retryable rather than immediately fatal, as long
    as the operation's own deadline hasn't passed — see
    ``publish.resolve_dataset_id``. ``deadline_expired`` is unrelated
    and still checked first: a caller that wants call_sdk itself to
    distinguish "the deadline already passed" (``DeadlineTimeout``) from
    a plain hard-exit keeps that behavior regardless of
    ``reraise_timeout``.
    """
    import httpx  # lazy — only for exception types

    try:
        return fn(**kwargs)
    except httpx.TimeoutException:
        if deadline_expired is not None and deadline_expired():
            raise DeadlineTimeout from None
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

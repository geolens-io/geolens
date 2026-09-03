"""Raw read-only SQL endpoint over the sandbox (#565).

``POST /api/query/`` accepts a single SELECT statement and returns
``{columns, rows}`` through the same validation/execution rails AI chat uses
(``app.platform.sandbox``), with a tighter budget on every axis:

- auth required (``use_ai_chat``), never anonymous — anonymous would also
  collapse the sandbox's per-user single-flight lock onto one shared slot;
- ``restrict_tables`` is MANDATORY and non-empty, so one route can never
  enumerate-and-dump every visible dataset (S03 follow-through);
- a self-join repetition cap (``max_table_repeats``) closes the CROSS JOIN
  cost vector a raw endpoint makes cheap to reach;
- a 5 s statement timeout and a smaller default row limit than chat's;
- the single-tenant reader role binds fail-closed (``require_reader_role``),
  so a query can never silently run with superuser privileges;
- per-user AND per-IP slowapi rate limits;
- errors expose only ``SandboxError.user_message`` (status carries the mapped
  category), and every query the sandbox EVALUATES — success or rejection —
  emits a durable audit event.

Audit scope (fix(#565 codex P2)): the durable trail records queries the
sandbox actually evaluated. PRE-sandbox rejections — a request refused by
authentication, by body validation (a malformed/oversized payload), or by the
rate limiter — never became a query and are deliberately NOT written to the
durable trail; they are logged instead. This is a security decision, not an
oversight: body-validation rejections bypass the per-request limiter, and a
429 IS the limiter shedding load, so a durable DB write per such rejection
would let a stream of cheap, throttled requests amplify into unbounded audit
writes — the exact denial vector this endpoint is hardened against. Logs carry
the same signal without a per-request write.

This router lives in ``processing/`` (not ``platform/``) on purpose: it must
import ``modules.auth``/``modules.audit``, and ``platform/`` may not import
``modules`` (``backend/tests/test_layering.py``).

The primary consumer is the read-only MCP server's ``query`` tool
(``mcp/geolens_mcp/``). Decided in #875/#565: a ``read_only`` API key may call
this POST route — it is a read semantically — via the exact-route carve-out in
``app.modules.auth.dependencies``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field, field_validator
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.identity import Identity
from app.modules.audit.service import AuditEvent, audit_emit_durable
from app.modules.auth.dependencies import require_permission
from app.platform.ratelimit import limiter
from app.platform.sandbox import SandboxError, SandboxResult, validate_and_execute
from app.processing.ai.sandbox_bounds import (
    MAX_OUTPUT_COLUMNS,
    MAX_TABLE_REPEATS,
    MAX_VALUES_ROWS,
    capacity_bound,
    query_slots,
)
from app.standards.ogc.errors import ERROR_RESPONSES_AUTH, RATE_LIMIT_RESPONSE

logger = structlog.stdlib.get_logger(__name__)


class _LoggedRejectionRoute(APIRoute):
    """Log — never durably audit — authenticated PRE-sandbox rejections (#565).

    A body-validation failure (``RequestValidationError``, HTTP 422) or a
    rate-limit rejection (``RateLimitExceeded``, HTTP 429) is raised before the
    handler body runs, so neither ``query.reject`` audit in the handler fires.
    These are intentionally logged, not written to the durable audit trail: see
    the module docstring for why durably auditing them is a write-amplification
    vector. The durable trail is reserved for queries the sandbox evaluated.

    FastAPI solves dependencies (including auth) BEFORE body validation, and the
    rate limiter runs inside the wrapped endpoint AFTER dependencies, so in both
    cases ``_rate_limit_scoped_user`` has already stamped the resolved user id
    onto ``request.state``. Auth failures raise their own 401/403 during
    dependency solving and never reach here, so an unauthenticated request is
    not logged as a rejected query attempt.
    """

    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        original = super().get_route_handler()

        async def _handler(request: Request) -> Response:
            try:
                return await original(request)
            except (RequestValidationError, RateLimitExceeded) as exc:
                user_id = getattr(request.state, "sandbox_query_user_id", None)
                if user_id is not None:
                    category = (
                        "rate_limited"
                        if isinstance(exc, RateLimitExceeded)
                        else "invalid_request"
                    )
                    logger.info(
                        "sandbox_query.pre_sandbox_rejection",
                        user_id=user_id,
                        category=category,
                    )
                raise

        return _handler


router = APIRouter(
    prefix="/query",
    tags=["Query"],
    route_class=_LoggedRejectionRoute,
    responses={**ERROR_RESPONSES_AUTH, 429: RATE_LIMIT_RESPONSE},
)

# Statement budget: half chat's 10 s default. The sandbox's per-user advisory
# lock already serializes each caller to one in-flight query, so this bounds
# how long any single request can hold a main-pool connection.
_QUERY_TIMEOUT_MS = 5_000

# Smaller than chat's 1000-row default; callers may raise it back up to 1000.
_QUERY_DEFAULT_ROW_LIMIT = 100
_QUERY_MAX_ROW_LIMIT = 1000

# fix(#1778): the self-join fan-out cap moved to sandbox_bounds.py and now
# applies to AI chat's query_data tool as well. It bounds worst-case
# cardinality, which is a property of the shared planner and pool rather than
# of this endpoint, and both surfaces are gated by the same `use_ai_chat`
# permission — so "applied only on this endpoint" made it opt-out by asking
# the chatbot instead. Kept under the local name so the call site below and
# the #565 regression tests read unchanged.
_QUERY_MAX_TABLE_REPEATS = MAX_TABLE_REPEATS

# Output-amplifying functions dropped on this raw surface (#565 codex P1
# r17/r18). Each turns a small input into an arbitrarily large single cell via
# a width / count / replacement argument, which neither the SQL-length cap nor
# row_limit nor the statement timeout bounds. The allowlist currently admits
# only format / replace / regexp_replace of this set; the rest are listed
# defensively so a future allowlist addition cannot silently reopen the hole on
# this endpoint. AI chat keeps them all (it passes no extra-blocked set).
_QUERY_BLOCKED_FUNCTIONS: frozenset[str] = frozenset(
    {
        "format",
        "replace",
        "regexp_replace",
        "repeat",
        "lpad",
        "rpad",
        "space",
        "overlay",
        # concatenation doubles a value when both operands are the same — chained
        # through CTEs it amplifies without bound (#565 codex P1 r19). `concat`
        # is the trigger that also blocks the `||` operator in validate_sql.
        "concat",
        "concat_ws",
        # concatenating aggregates build one huge cell from many rows
        "string_agg",
        "group_concat",  # sqlglot's canonical name for STRING_AGG
        "array_agg",
        "json_agg",
        "jsonb_agg",
        "xmlagg",
        # JSON/array builders double a value the same way via repeated args —
        # jsonb_build_object('a', s, 'b', s) or array_to_string(ARRAY[s, s]).
        "json_build_object",
        "jsonb_build_object",
        "array_to_string",
    }
)

# fix(#1778): the VALUES-row, output-column and concurrency bounds moved to
# sandbox_bounds.py so AI chat's query_data applies the same objects. The
# response-byte cap stays here: it bounds THIS endpoint's serialized HTTP
# response, which the chat tool result does not produce.
_QUERY_MAX_VALUES_ROWS = MAX_VALUES_ROWS
_QUERY_MAX_OUTPUT_COLUMNS = MAX_OUTPUT_COLUMNS
_QUERY_MAX_RESPONSE_BYTES = 8 * 1024 * 1024

_capacity_bound = capacity_bound
_query_slots = query_slots

# Module-level so tests can lower them; slowapi evaluates callables per
# request (same pattern as auth.router's persistent-config-driven limits).
#
# These reuse the app-wide in-memory ``limiter`` (from modules/auth/router.py),
# so like EVERY slowapi limit in this codebase the per-user/per-IP counters are
# per-uvicorn-worker, not shared (#565 codex P2 r10). Cross-worker frequency
# enforcement (a Valkey-backed limiter) is an app-wide change tracked separately
# — deliberately not forked here for one endpoint. It is a secondary bound
# regardless: the sandbox's per-user advisory lock is a Postgres xact lock, so
# it is GLOBAL across workers and already serializes each user to ONE in-flight
# query, and every query is capped at a 5 s statement timeout. So the
# per-worker counter caps request FREQUENCY loosely; concurrency and per-query
# cost are bounded cross-worker no matter the worker count.
_QUERY_PER_USER_LIMIT = "30/minute"
_QUERY_PER_IP_LIMIT = "60/minute"


def _per_user_limit(_request: Request | None = None) -> str:
    return _QUERY_PER_USER_LIMIT


def _per_ip_limit(_request: Request | None = None) -> str:
    return _QUERY_PER_IP_LIMIT


# Mirrors router_analysis's category → status mapping, extended with the two
# validation-side categories this endpoint surfaces directly. Everything else
# (query_failed and any future category) stays a generic 500.
_SANDBOX_STATUS = {
    "invalid_query": status.HTTP_422_UNPROCESSABLE_CONTENT,
    # Denied and nonexistent tables share one category and one message, so the
    # 404 is oracle-free (repo convention: access denial reads as not-found).
    "table_not_accessible": status.HTTP_404_NOT_FOUND,
    "query_timeout": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "query_data_error": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "query_busy": status.HTTP_429_TOO_MANY_REQUESTS,
    "query_at_capacity": status.HTTP_429_TOO_MANY_REQUESTS,
}

_require_ai_chat = require_permission("use_ai_chat")


async def _rate_limit_scoped_user(
    request: Request,
    user: Identity = Depends(_require_ai_chat),
) -> Identity:
    """Resolve the caller and stash their id for the per-user rate-limit key.

    FastAPI resolves dependencies before invoking the (slowapi-wrapped)
    endpoint, so the key function below always sees the id for an
    authenticated request.
    """
    request.state.sandbox_query_user_id = str(user.id)
    return user


def _user_scope_key(request: Request) -> str:
    """Per-user rate-limit key; falls back to the remote address."""
    user_id = getattr(request.state, "sandbox_query_user_id", None)
    return f"user:{user_id}" if user_id else get_remote_address(request)


class SandboxQueryRequest(BaseModel):
    """One read-only SELECT plus its mandatory table scope."""

    sql: str = Field(
        ...,
        min_length=1,
        max_length=20_000,
        description="A single SELECT statement over `data.*` tables.",
    )
    restrict_tables: list[str] = Field(
        ...,
        min_length=1,
        max_length=25,
        description=(
            "Table names (without the `data.` prefix) the query may touch. "
            "Required and non-empty; intersected with your access — it can "
            "only narrow what you already see, never widen it."
        ),
    )
    row_limit: int = Field(
        default=_QUERY_DEFAULT_ROW_LIMIT,
        ge=1,
        le=_QUERY_MAX_ROW_LIMIT,
        description="Maximum rows to return.",
    )

    @field_validator("restrict_tables")
    @classmethod
    def _sane_table_names(cls, value: list[str]) -> list[str]:
        cleaned = [name.strip() for name in value]
        if any(not name for name in cleaned):
            raise ValueError("restrict_tables entries must be non-empty")
        # PostgreSQL identifiers cap at 63 bytes; these names are echoed into
        # the audit trail, so junk-sized entries are refused, not stored.
        if any(len(name) > 63 for name in cleaned):
            raise ValueError("restrict_tables entries must be valid table names")
        return cleaned


async def _audit_query(
    request: Request,
    user: Identity,
    body: SandboxQueryRequest,
    *,
    category: str | None = None,
    row_count: int | None = None,
    truncated: bool | None = None,
) -> None:
    """Durably record one sandbox-EVALUATED query — success or rejection.

    Called only from inside the handler, after body validation and the rate
    limiter have passed, so every row here corresponds to a query the sandbox
    actually parsed and ran or refused. Pre-sandbox rejections are logged by
    the route class instead (see the module docstring).

    Uses ``audit_emit_durable`` (own session, own commit) because this
    endpoint's request session never writes; the audit row must not depend on
    a handler commit that doesn't otherwise exist.
    """
    details: dict = {
        # Bounded copy of the statement: the audit trail is the governance
        # record of SQL data access, and 2000 chars covers real queries
        # without letting a 20 KB statement bloat every row.
        "sql": body.sql[:2000],
        "restrict_tables": sorted(set(body.restrict_tables)),
        "row_limit": body.row_limit,
        "timeout_ms": _QUERY_TIMEOUT_MS,
    }
    if category is not None:
        details["category"] = category
    if row_count is not None:
        details["row_count"] = row_count
        details["truncated"] = truncated
    # Two literal-action call sites on purpose: test_audit_action_registry
    # statically verifies every AuditEvent action string, so the action must
    # be a literal here, not an expression.
    common = dict(
        user_id=user.id,
        resource_type="query",
        resource_id=None,
        details=details,
        ip_address=request.client.host if request.client else None,
    )
    if category is None:
        await audit_emit_durable(AuditEvent(action="query.execute", **common))
    else:
        await audit_emit_durable(AuditEvent(action="query.reject", **common))


# ROUTE-01 dual-shape: the trailing-slash form is canonical and OpenAPI-visible;
# the no-slash form is a hidden alias. fix(#565 codex P2 r3): both are registered
# on THIS router so both carry `_LoggedRejectionRoute` — the app-level
# trailing-slash alias builder re-registers missing no-slash routes as PLAIN
# APIRoutes, which would drop pre-sandbox-rejection logging on `/query`. It skips
# `/query` because this hidden route already claims the (method, path) pair, and
# `include_in_schema=False` keeps it out of the OpenAPI surface (and the #875
# read_only carve-out already exempts both `/query/` and `/query`).
@router.post("", include_in_schema=False)
@router.post(
    "/",
    response_model=SandboxResult,
    summary="Run a read-only SQL query",
)
@limiter.limit(_per_ip_limit)
@limiter.limit(_per_user_limit, key_func=_user_scope_key)
async def sandbox_query_endpoint(
    request: Request,
    body: SandboxQueryRequest,
    user: Identity = Depends(_rate_limit_scoped_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Execute one SELECT through the read-only SQL sandbox.

    The statement must be a single SELECT over `data.*` tables you can
    access, name every table in `restrict_tables`, and fit the sandbox's
    function allowlist and cost bounds. Rows are capped by `row_limit` and
    execution by a server-side statement timeout.
    """
    restrict = frozenset(body.restrict_tables)
    try:
        result = await validate_and_execute(
            body.sql,
            db,
            user,
            row_limit=body.row_limit,
            timeout_ms=_QUERY_TIMEOUT_MS,
            restrict_tables=restrict,
            max_table_repeats=_QUERY_MAX_TABLE_REPEATS,
            require_reader_role=True,
            # Return the request connection before the sandbox opens its own,
            # and cap total concurrent executions (#565 codex P1 r11). Nothing
            # below reads `db`; the audit trail uses its own session.
            release_session=True,
            capacity_semaphore=_query_slots,
            # Raw-surface guards against output/cardinality amplification
            # (#565 codex P1 r17/r20).
            extra_blocked_functions=_QUERY_BLOCKED_FUNCTIONS,
            max_values_rows=_QUERY_MAX_VALUES_ROWS,
            max_output_columns=_QUERY_MAX_OUTPUT_COLUMNS,
        )
    except SandboxError as exc:
        # Only the sanitized message and the category-mapped status leave the
        # API. The category itself and full server-side detail are logged by
        # the sandbox; __cause__ never crosses this boundary.
        await _audit_query(request, user, body, category=exc.category)
        raise HTTPException(
            status_code=_SANDBOX_STATUS.get(
                exc.category, status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=exc.user_message,
        ) from exc
    await _audit_query(
        request, user, body, row_count=result.row_count, truncated=result.truncated
    )
    # fix(#565 codex P2 r15/r20): driver types Pydantic cannot serialize turn a
    # successful, already-audited query into a 500. Normalize each cell — bytea
    # to \x-hex (matching to_jsonb), asyncpg ranges to text — recursively.
    result.rows = [[_json_safe(cell) for cell in row] for row in result.rows]
    # fix(#565 codex P1 r20 / P2 r23): a wide DATA cell (or a projection the
    # column cap let through) can still make one row gigabytes. Bound the
    # response by its ACTUAL serialized size, not a `str(cell)` character count:
    # that undercounts multi-byte UTF-8 (an 8M-emoji cell is ~32 MiB encoded)
    # and JSON escaping. Serialize once with the model's own JSON encoder,
    # measure the encoded bytes, and return exactly those bytes so the limit is
    # enforced on what crosses the wire (and nothing is serialized twice).
    payload = result.model_dump_json().encode("utf-8")
    if len(payload) > _QUERY_MAX_RESPONSE_BYTES:
        await _audit_query(request, user, body, category="response_too_large")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Query result is too large to return",
        )
    return Response(content=payload, media_type="application/json")


def _json_safe(value: object) -> object:
    """Make one result cell JSON-serializable, recursive.

    Mirrors ``service_analysis._json_safe`` — duplicated because ``processing/``
    may not import ``modules.catalog``. Encodes bytea as ``\\x``-hex (matching
    to_jsonb) and asyncpg ranges (``int4range``, ``tsrange``, …) as their text
    form, which Pydantic cannot serialize natively (fix(#565 codex P2 r20)).
    Recurses into containers; scalar driver types Pydantic handles (datetime,
    Decimal, UUID) pass through.
    """
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "\\x" + bytes(value).hex()
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if _is_pg_range(value):
        return _range_to_text(value)
    return value


def _is_pg_range(value: object) -> bool:
    """Whether ``value`` is an asyncpg range (duck-typed to avoid the import)."""
    return (
        hasattr(value, "lower")
        and hasattr(value, "upper")
        and hasattr(value, "lower_inc")
        and hasattr(value, "upper_inc")
        and hasattr(value, "isempty")
    )


def _range_to_text(value) -> str:
    """PostgreSQL text form of an asyncpg range, e.g. ``[1,3)`` or ``empty``."""
    if value.isempty:
        return "empty"
    lower = "" if value.lower is None else value.lower
    upper = "" if value.upper is None else value.upper
    left = "[" if value.lower_inc else "("
    right = "]" if value.upper_inc else ")"
    return f"{left}{lower},{upper}{right}"

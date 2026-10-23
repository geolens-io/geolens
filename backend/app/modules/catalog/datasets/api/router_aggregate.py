"""Dataset aggregate endpoint for dashboard and story widgets."""

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from slowapi.util import get_remote_address
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.identity import Identity
from app.core.record_types import capabilities
from app.modules.auth.dependencies import (
    get_optional_user_fail_open,
    reject_unresolvable_credentials,
)
from app.modules.catalog.authorization import check_dataset_access_or_anonymous
from app.modules.catalog.datasets.api.router_analysis import SANDBOX_STATUS
from app.modules.catalog.datasets.domain.aggregate import (
    AggregateError,
    AggregateRequest,
    AggregateResponse,
    TableUnavailable,
    run_aggregate,
)
from app.modules.catalog.datasets.domain.service import get_dataset
from app.modules.embed_tokens.service import validate_embed_token_access
from app.platform.ratelimit import limiter
from app.platform.sandbox.schemas import SandboxError
from app.standards.ogc.errors import ERROR_RESPONSES_AUTH, RATE_LIMIT_RESPONSE

router = APIRouter(prefix="/datasets", tags=["Datasets - Analysis"])

# Each widget on a dashboard asks once per refresh, and a pan refreshes them
# all; the filtered OGC items route takes the same per-address rate.
_AGGREGATE_RATE_LIMIT = "10/second"


@router.post(
    "/{dataset_id}/aggregate/",
    response_model=AggregateResponse,
    responses={**ERROR_RESPONSES_AUTH, 429: RATE_LIMIT_RESPONSE},
)
@limiter.limit(_AGGREGATE_RATE_LIMIT, override_defaults=False)
async def aggregate_endpoint(
    dataset_id: uuid.UUID,
    body: AggregateRequest,
    request: Request,
    user: Identity | None = Depends(get_optional_user_fail_open),
    embed_token: str | None = Header(
        default=None,
        alias="X-Embed-Token",
        description=(
            "Optional embed token. Datasets in the token's scope are "
            "authorized even without user credentials (embed viewers)."
        ),
    ),
    db: AsyncSession = Depends(get_db),
) -> AggregateResponse:
    """Compute one exact aggregate over a dataset's rows, for a widget.

    Anonymous callers can read public, published datasets; ``X-Embed-Token``
    authorizes datasets in the token's scope. Other datasets return 404.

    With ``bbox``, a view the planner expects to hold more than 500,000 rows
    is refused with 422 and the code ``too_wide`` rather than approximated. A
    ``bbox`` that contains the whole dataset is answered as the whole layer.
    Refusals carry a ``code`` in ``detail``: ``too_wide``, ``invalid_column``,
    ``invalid_filter``, ``no_geometry``, ``query_timeout``,
    ``query_data_error``, ``result_too_large``, and with 429 ``query_busy``
    (this caller already has two aggregates running) or ``query_at_capacity``.

    Clients should keep at most two requests in flight per caller and retry a
    429 after 200-400 ms with jitter.
    """
    # The embed capability is checked first; a supplied credential that does
    # not resolve gets 401 only when the capability did not authorize.
    embed_ok = bool(
        embed_token
        and await validate_embed_token_access(embed_token, dataset_id, db, request)
    )
    if not embed_ok:
        reject_unresolvable_credentials(request, user)

    dataset = await get_dataset(db, dataset_id)
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found"
        )
    if not embed_ok:
        await check_dataset_access_or_anonymous(db, dataset, dataset_id, user)

    if not capabilities(dataset.record.record_type).feature_table:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset '{dataset_id}' has no feature table to aggregate",
        )

    caller_key = str(user.id) if user is not None else get_remote_address(request)
    try:
        return await run_aggregate(db, dataset, body, caller_key=caller_key)
    except AggregateError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": exc.code, "message": exc.message},
        ) from exc
    except SandboxError as exc:
        raise HTTPException(
            status_code=SANDBOX_STATUS.get(
                exc.category, status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail={"code": exc.category, "message": exc.user_message},
        ) from exc
    except (ProgrammingError, OperationalError, TableUnavailable) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dataset table is temporarily unavailable",
        ) from exc

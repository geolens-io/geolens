"""The API's readiness probe.

`/health` also fails when the optional cache or the shared object store is
down, and pulling every replica out of service for either turns a partial
outage into a full one. This route answers only whether the process can reach
the database. It stays out of the published contract like `/health/live`, and
under the default per-client rate limit, which a probe interval never nears.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.observability.health.service import check_readiness

router = APIRouter(tags=["Health"])


@router.get("/health/ready", include_in_schema=False)
async def health_ready() -> JSONResponse:
    """Readiness probe: the database answers a query."""
    result = await check_readiness()
    return JSONResponse(result, status_code=200 if result["status"] == "ready" else 503)

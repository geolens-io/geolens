"""STAC asset size lookup for the import review step."""

import asyncio
import time

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from app.core.identity import Identity
from app.core.service_tokens import STAC_SERVICE_FORMAT
from app.modules.auth.dependencies import require_permission
from app.modules.catalog.sources.adapters.stac_asset_size import (
    BATCH_DEADLINE,
    probe_asset_sizes,
)
from app.modules.catalog.sources.schemas import ServiceAuthRequest
from app.modules.catalog.sources.stac_router import _validate_stac_http_url
from app.platform.security import SSRFError, validate_url_for_ssrf
from app.platform.service_auth import credential_or_422, service_credential_from_request
from app.standards.ogc.errors import ERROR_RESPONSES_WRITE

router = APIRouter(
    prefix="/services/stac",
    tags=["STAC Import"],
    responses=ERROR_RESPONSES_WRITE,
)


class StacAssetSizeTarget(BaseModel):
    id: str = Field(max_length=2048, description="STAC item ID the asset belongs to.")
    href: str = Field(max_length=4096, description="URL of the item's data asset.")
    _validate_href = field_validator("href")(_validate_stac_http_url)


class StacAssetSizesRequest(BaseModel):
    url: str = Field(
        min_length=1,
        max_length=2048,
        description="STAC API root URL the assets were found in.",
    )
    _validate_url = field_validator("url")(_validate_stac_http_url)
    assets: list[StacAssetSizeTarget] = Field(
        min_length=1,
        max_length=50,
        description="Assets to measure (max 50 per request).",
    )
    auth: ServiceAuthRequest | None = Field(
        default=None,
        description=(
            "Credential for a protected catalog. It is sent only to assets "
            "on the catalog's own origin."
        ),
    )


class StacAssetSize(BaseModel):
    id: str = Field(description="STAC item ID.")
    size_bytes: int | None = Field(
        default=None,
        description="Asset size in bytes, or null when the server did not report one.",
    )


class StacAssetSizesResponse(BaseModel):
    sizes: list[StacAssetSize] = Field(description="One entry per requested asset.")


@router.post("/asset-sizes", response_model=StacAssetSizesResponse)
async def stac_asset_sizes(
    request: StacAssetSizesRequest,
    user: Identity = Depends(require_permission("create_layers")),
) -> StacAssetSizesResponse:
    """Look up the size of data assets whose item publishes no ``file:size``.

    Asks each asset's server for its length (HEAD, then a one-byte range
    request). A size the server does not report comes back as null.
    """
    credential = credential_or_422(
        service_credential_from_request(request.auth, None),
        service_format=STAC_SERVICE_FORMAT,
    )
    started = time.monotonic()
    try:
        async with asyncio.timeout(BATCH_DEADLINE):
            await validate_url_for_ssrf(request.url)
    except SSRFError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="The catalog address could not be checked in time.",
        )

    sizes = await probe_asset_sizes(
        request.url,
        [a.href for a in request.assets],
        credential,
        deadline=max(0.0, BATCH_DEADLINE - (time.monotonic() - started)),
    )
    return StacAssetSizesResponse(
        sizes=[
            StacAssetSize(id=a.id, size_bytes=size)
            for a, size in zip(request.assets, sizes)
        ]
    )

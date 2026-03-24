"""FastAPI router for layer creation.

Column management (add/drop) is handled by the datasets router at
/datasets/{id}/columns/ — those endpoints were removed from here
to avoid duplication.
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_permission
from app.auth.models import User
from app.dependencies import get_db
from app.layers.schemas import (
    CreateLayerRequest,
    CreateLayerResponse,
)
from app.layers.service import create_layer

logger = structlog.stdlib.get_logger(__name__)

layers_router = APIRouter(prefix="/layers", tags=["Maps"])


@layers_router.post(
    "/",
    response_model=CreateLayerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_layer_endpoint(
    body: CreateLayerRequest,
    user: User = Depends(require_permission("create_layers")),
    db: AsyncSession = Depends(get_db),
):
    """Create a new empty spatial layer.

    Creates a PostGIS table with a typed geometry column, runs the full
    post-processing pipeline (geom_4326, spatial index, reader grants),
    and registers the layer as a catalog dataset.

    Requires editor or admin role.
    """
    try:
        dataset = await create_layer(
            db,
            body.title,
            body.geometry_type,
            user.id,
            columns=body.columns,
            description=body.summary,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    logger.info(
        "layer.create",
        table_name=dataset.table_name,
        user_id=str(user.id),
        geometry_type=body.geometry_type,
    )

    await db.commit()
    await db.refresh(dataset)

    return CreateLayerResponse(
        id=dataset.id,
        title=dataset.record.title,
        table_name=dataset.table_name,
        geometry_type=dataset.geometry_type,
        feature_count=dataset.feature_count or 0,
        visibility=dataset.record.visibility,
        created_at=dataset.record.created_at,
    )



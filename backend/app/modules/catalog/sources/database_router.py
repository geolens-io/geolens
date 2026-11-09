"""Spatial tables of an operator-configured database connection."""

import uuid
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.geo import unknown_srid_refusal
from app.core.identity import Identity
from app.modules.auth.dependencies import require_permission
from app.modules.catalog.authorization import check_public_visibility_allowed
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.catalog.datasets.domain.schemas import Visibility
from app.modules.quota.service import check_upload_quota
from app.platform.database_sources import (
    LISTING_LIMIT,
    DatabaseSourceError,
    UnknownDatabaseConnectionError,
    get_database_connection,
    importable_identifier,
    list_spatial_tables,
)
from app.platform.extensions import get_catalog_port
from app.platform.jobs import ledger
from app.platform.jobs.models import DATABASE_SOURCE_METADATA_KEY
from app.standards.ogc.errors import (
    BAD_GATEWAY_RESPONSE,
    CONFLICT_RESPONSE,
    ERROR_RESPONSES_WRITE,
    NOT_FOUND_RESPONSE,
)

logger = structlog.stdlib.get_logger(__name__)

router = APIRouter(
    prefix="/services/databases", tags=["Datasets"], responses=ERROR_RESPONSES_WRITE
)


class DatabaseTable(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    schema_name: str = Field(description="Schema that holds the table or view.")
    table_name: str = Field(description="Table or view name.")
    object_type: Literal["table", "view"] = Field(description="Table or view.")
    geometry_column: str = Field(description="Spatial column.")
    column_type: Literal["geometry", "geography"] = Field(
        description="SQL Server spatial type of the column."
    )
    srid: int | None = Field(
        description=(
            "SRID of the column's first non-null value, or null when it is 0, "
            "the table has no rows, or it couldn't be read."
        )
    )


class DatabaseTableListResponse(BaseModel):
    connection: str = Field(description="Connection name from the deployment.")
    database: str = Field(description="Database the connection reads.")
    tables: list[DatabaseTable] = Field(
        description="One entry per spatial column, ordered by schema, table and column."
    )
    limit: int = Field(description="Most entries one listing returns.")
    truncated: bool = Field(
        description="True when the connection has more spatial columns than `limit`."
    )


@router.get(
    "/{connection}/tables",
    response_model=DatabaseTableListResponse,
    include_in_schema=False,
    summary="List a database connection's spatial tables",
)
@router.get(
    "/{connection}/tables/",
    response_model=DatabaseTableListResponse,
    responses={404: NOT_FOUND_RESPONSE, 502: BAD_GATEWAY_RESPONSE},
    summary="List a database connection's spatial tables",
)
async def list_database_tables(
    connection: str = Path(max_length=64, description="Connection name."),
    user: Identity = Depends(require_permission("create_layers")),
    db: AsyncSession = Depends(get_db),
) -> DatabaseTableListResponse:
    """List the tables and views with a geometry or geography column that the
    connection's login can read.

    Connections come from the deployment's `DATABASE_SOURCES`. A 502 means the
    server could not be reached or signed in to, or a table could not be read;
    the detail names only the connection.
    """
    # Read off `user` before the release expires it. Released before the
    # subprocess, which can wait 30 s on an unreachable server.
    user_id = user.id
    await db.rollback()
    try:
        database = get_database_connection(connection).database
        listing = await list_spatial_tables(connection)
    except UnknownDatabaseConnectionError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    except DatabaseSourceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from None
    logger.info(
        "database tables listed",
        connection=connection,
        user_id=str(user_id),
        count=len(listing.tables),
        truncated=listing.truncated,
    )
    return DatabaseTableListResponse(
        connection=connection,
        database=database,
        tables=[DatabaseTable.model_validate(t) for t in listing.tables],
        limit=LISTING_LIMIT,
        truncated=listing.truncated,
    )


class DatabaseImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_name: str = Field(
        min_length=1, max_length=128, description="Schema of the table, as listed."
    )
    table_name: str = Field(
        min_length=1, max_length=128, description="Table or view name, as listed."
    )
    title: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        description="Dataset title. Defaults to the table name.",
    )
    summary: str | None = Field(
        default=None,
        max_length=5000,
        description="Optional dataset description shown in the catalog.",
    )
    visibility: Visibility = Field(
        default="private",
        description="Dataset visibility: private, restricted, internal or public.",
    )
    srid_override: int | None = Field(
        default=None,
        ge=1,
        le=998999,
        description=(
            "EPSG code the table's coordinates are read under. Needed when the "
            "listing shows no SRID: the geometries have SRID 0 or the table "
            "has no rows. Otherwise it replaces the table's own SRID."
        ),
    )


class DatabaseImportResponse(BaseModel):
    job_id: uuid.UUID = Field(description="Ingest job that copies the table.")
    status: Literal["pending"] = Field(description="Status of the new job.")
    message: str = Field(description="What happened.")


async def _existing_copy(
    db: AsyncSession, user_id: uuid.UUID, connection: str, body: DatabaseImportRequest
):
    return (
        await db.execute(
            select(Dataset.id, Record.title)
            .join(Record, Dataset.record_id == Record.id)
            .where(
                Dataset.source_format == "database",
                Dataset.origin_ref["connection"].astext == connection,
                Dataset.origin_ref["schema"].astext == body.schema_name,
                Dataset.origin_ref["table"].astext == body.table_name,
                Record.created_by == user_id,
            )
            .limit(1)
        )
    ).first()


def _table_not_listed(connection: str) -> HTTPException:
    return HTTPException(
        status.HTTP_404_NOT_FOUND,
        detail={
            "code": "database_table_not_listed",
            "message": (
                f"The database connection {connection!r} doesn't list that "
                "table, or the table can't be imported."
            ),
        },
    )


@router.post(
    "/{connection}/imports",
    response_model=DatabaseImportResponse,
    status_code=status.HTTP_202_ACCEPTED,
    include_in_schema=False,
    summary="Import a table from a database connection",
)
@router.post(
    "/{connection}/imports/",
    response_model=DatabaseImportResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        404: NOT_FOUND_RESPONSE,
        409: CONFLICT_RESPONSE,
        502: BAD_GATEWAY_RESPONSE,
    },
    summary="Import a table from a database connection",
)
async def import_database_table(
    body: DatabaseImportRequest,
    request: Request,
    connection: str = Path(max_length=64, description="Connection name."),
    user: Identity = Depends(require_permission("create_layers")),
    db: AsyncSession = Depends(get_db),
) -> DatabaseImportResponse:
    """Copy one listed table or view into a new dataset, as an ingest job.

    The table must be one the connection's listing returns for this request.
    A second import of the same table by the same user answers 409
    `duplicate_source` naming the existing dataset; refresh that one instead.
    """
    user_id = user.id
    try:
        get_database_connection(connection)
    except UnknownDatabaseConnectionError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    await check_public_visibility_allowed(db, user, body.visibility)
    srid_refusal = await unknown_srid_refusal(db, body.srid_override)
    if srid_refusal:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=srid_refusal)
    await check_upload_quota(db, user_id, 0, request)
    existing = await _existing_copy(db, user_id, connection, body)
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "duplicate_source",
                "message": (
                    f"This table is already imported (existing: "
                    f"'{existing.title}'). To pull the latest data into it, "
                    "refresh that dataset instead of importing it again."
                ),
                "existing_dataset_id": str(existing.id),
                "existing_title": existing.title,
            },
        )
    # Released before the listing, which can wait 30 s on an unreachable server.
    await db.rollback()
    if not (
        importable_identifier(body.schema_name)
        and importable_identifier(body.table_name)
    ):
        raise _table_not_listed(connection)
    try:
        listing = await list_spatial_tables(connection)
    except DatabaseSourceError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from None
    if not any(
        table.schema_name == body.schema_name and table.table_name == body.table_name
        for table in listing.tables
    ):
        raise _table_not_listed(connection)

    metadata = {
        DATABASE_SOURCE_METADATA_KEY: {
            "connection": connection,
            "schema": body.schema_name,
            "table": body.table_name,
        },
        "title": body.title or body.table_name,
        "visibility": body.visibility,
        **({"summary": body.summary} if body.summary else {}),
        **(
            {"srid_override": body.srid_override}
            if body.srid_override is not None
            else {}
        ),
    }
    job = ledger.create(
        db,
        created_by=user_id,
        source_filename=f"{body.schema_name}.{body.table_name}",
        user_metadata=metadata,
    )
    await db.commit()
    await get_catalog_port().queue_ingest_job(job, str(user_id), db=db)
    logger.info(
        "database import queued",
        connection=connection,
        user_id=str(user_id),
        job_id=str(job.id),
    )
    return DatabaseImportResponse(
        job_id=job.id, status="pending", message="Import queued"
    )

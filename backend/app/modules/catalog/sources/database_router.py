"""Spatial tables of an operator-configured database connection."""

from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.identity import Identity
from app.modules.auth.dependencies import require_permission
from app.platform.database_sources import (
    LISTING_LIMIT,
    DatabaseSourceError,
    UnknownDatabaseConnectionError,
    get_database_connection,
    list_spatial_tables,
)
from app.standards.ogc.errors import (
    BAD_GATEWAY_RESPONSE,
    ERROR_RESPONSES_WRITE,
    NOT_FOUND_RESPONSE,
)

logger = structlog.stdlib.get_logger(__name__)

router = APIRouter(
    prefix="/services/databases", tags=["Datasets"], responses=ERROR_RESPONSES_WRITE
)


class DatabaseTable(BaseModel):
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
        tables=[
            DatabaseTable(
                schema_name=table.schema_name,
                table_name=table.table_name,
                object_type=table.object_type,
                geometry_column=table.geometry_column,
                column_type=table.column_type,
                srid=table.srid,
            )
            for table in listing.tables
        ],
        limit=LISTING_LIMIT,
        truncated=listing.truncated,
    )

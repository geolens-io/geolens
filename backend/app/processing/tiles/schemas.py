import uuid
from typing import Literal

from pydantic import BaseModel, Field


class VectorTileToken(BaseModel):
    kind: Literal["vector"]
    sig: str
    exp: int
    scope: str
    expires_in: int


class RasterTileToken(BaseModel):
    """A raster tile template, signed like its vector sibling.

    fix(#688): the raster shape used to carry no signature at all, so a client
    following the API contract literally received an *unauthenticated* template
    for a private raster. MapLibre issues the tile image requests itself and
    attaches no `X-Api-Key`, so an API-key-only client could not render one —
    the workarounds were `setTransformRequest` (not available to every consumer)
    or `?api_key=` in the tile URL, which puts a non-expiring unscoped
    credential into tile URLs, server logs, and saved client project files.

    `tile_url` now arrives with `sig`/`exp`/`scope` already in its query string,
    so the template is self-sufficient and expires. The three are also returned
    as fields, mirroring `VectorTileToken`, for clients that rebuild the URL.
    """

    kind: Literal["raster"]
    tile_url: str
    sig: str
    exp: int
    scope: str
    expires_in: int
    bounds: list[float] | None
    minzoom: int
    maxzoom: int
    tile_size: int
    format: str


class TileTokenBatchRequest(BaseModel):
    """Batch request for tile tokens — accepts up to 50 dataset IDs."""

    dataset_ids: list[uuid.UUID] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Dataset IDs to generate tokens for. Must be unique; duplicates deduplicated server-side.",
    )


class TileTokenBatchResponse(BaseModel):
    """Batch response mapping dataset_id (string) to token or error.

    Each entry is either a VectorTileToken, a RasterTileToken, or a
    ``{"error": "..."}`` object describing why the token could not be
    generated (404 dataset, 403 forbidden, etc.). The batch call itself
    succeeds even if individual datasets fail — clients should check each
    entry for the ``error`` key.
    """

    tokens: dict[str, VectorTileToken | RasterTileToken | dict]

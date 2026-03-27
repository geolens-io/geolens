from typing import Literal

from pydantic import BaseModel


class VectorTileToken(BaseModel):
    kind: Literal["vector"]
    sig: str
    exp: int
    scope: str
    expires_in: int


class RasterTileToken(BaseModel):
    kind: Literal["raster"]
    tile_url: str
    bounds: list[float] | None
    minzoom: int
    maxzoom: int
    tile_size: int
    format: str

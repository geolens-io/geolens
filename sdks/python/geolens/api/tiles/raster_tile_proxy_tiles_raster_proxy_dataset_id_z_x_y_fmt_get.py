from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...models.raster_tile_proxy_tiles_raster_proxy_dataset_id_zxy_fmt_get_colormap_name_type_0 import (
    RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetColormapNameType0,
)
from ...models.raster_tile_proxy_tiles_raster_proxy_dataset_id_zxy_fmt_get_stretch_type_0 import (
    RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetStretchType0,
)
from ...types import Unset
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    z: int,
    x: int,
    y: int,
    fmt: str,
    *,
    colormap_name: None
    | RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetColormapNameType0
    | Unset = UNSET,
    stretch: None
    | RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetStretchType0
    | Unset = UNSET,
    pmin: float | None | Unset = UNSET,
    pmax: float | None | Unset = UNSET,
    sigma: float | None | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_colormap_name: None | str | Unset
    if isinstance(colormap_name, Unset):
        json_colormap_name = UNSET
    elif isinstance(colormap_name, str):
        json_colormap_name = colormap_name
    else:
        json_colormap_name = colormap_name
    params["colormap_name"] = json_colormap_name

    json_stretch: None | str | Unset
    if isinstance(stretch, Unset):
        json_stretch = UNSET
    elif isinstance(stretch, str):
        json_stretch = stretch
    else:
        json_stretch = stretch
    params["stretch"] = json_stretch

    json_pmin: float | None | Unset
    if isinstance(pmin, Unset):
        json_pmin = UNSET
    else:
        json_pmin = pmin
    params["pmin"] = json_pmin

    json_pmax: float | None | Unset
    if isinstance(pmax, Unset):
        json_pmax = UNSET
    else:
        json_pmax = pmax
    params["pmax"] = json_pmax

    json_sigma: float | None | Unset
    if isinstance(sigma, Unset):
        json_sigma = UNSET
    else:
        json_sigma = sigma
    params["sigma"] = json_sigma

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/tiles/raster-proxy/{dataset_id}/{z}/{x}/{y}.{fmt}".format(
            dataset_id=quote(str(dataset_id), safe=""),
            z=quote(str(z), safe=""),
            x=quote(str(x), safe=""),
            y=quote(str(y), safe=""),
            fmt=quote(str(fmt), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = cast(Any, None)
        return response_200

    if response.status_code == 400:
        response_400 = ProblemDetail.from_dict(response.json())

        return response_400

    if response.status_code == 404:
        response_404 = ProblemDetail.from_dict(response.json())

        return response_404

    if response.status_code == 422:
        response_422 = ProblemDetail.from_dict(response.json())

        return response_422

    if response.status_code == 500:
        response_500 = ProblemDetail.from_dict(response.json())

        return response_500

    if response.status_code == 503:
        response_503 = ProblemDetail.from_dict(response.json())

        return response_503

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[Any | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    dataset_id: UUID,
    z: int,
    x: int,
    y: int,
    fmt: str,
    *,
    client: AuthenticatedClient,
    colormap_name: None
    | RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetColormapNameType0
    | Unset = UNSET,
    stretch: None
    | RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetStretchType0
    | Unset = UNSET,
    pmin: float | None | Unset = UNSET,
    pmax: float | None | Unset = UNSET,
    sigma: float | None | Unset = UNSET,
) -> Response[Any | ProblemDetail]:
    """Raster Tile Proxy

     API-side raster tile proxy: auth check + fetch from Titiler.

    Used by Vite dev proxy and as a fallback for deployments without nginx.
    Production deployments with nginx should use the nginx raster-tiles path
    for better caching and performance.

    colormap_name: Optional Titiler colormap for single-band display. Validated
    against _ALLOWED_COLORMAPS (T-1140-01). Gray is the Titiler default for
    single-band — passing gray is a no-op (not forwarded). colormap_name is not
    forwarded for DEM layers (render_params starts with 'algorithm=').

    stretch: Optional stretch strategy. percentile/stddev compute a stats-based
    rescale from Titiler band statistics. Multi-band rasters produce one rescale=
    fragment per band (up to 3, RASTER-STRETCH-03).

    pmin/pmax: Configurable percentile clip bounds (default 2/98). Must satisfy
    0 <= pmin < pmax <= 100. Forwarded as repeated p= params to /cog/statistics.
    The _band_stats_cache key includes pmin/pmax so different bounds never serve
    stale cached stats (RASTER-STRETCH-UI-01 / Phase 1153 cache-key isolation).

    sigma: Standard-deviation multiplier for stretch=stddev (default 2.0).
    Must be > 0.

    Args:
        dataset_id (UUID):
        z (int):
        x (int):
        y (int):
        fmt (str):
        colormap_name (None | RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetColormapNameType0 |
            Unset): Titiler colormap for single-band display
        stretch (None | RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetStretchType0 | Unset):
            Stretch strategy: minmax (default), percentile, stddev
        pmin (float | None | Unset): Lower percentile clip for stretch=percentile (0–100, default
            2). Absent = current p2 behavior. Must be less than pmax.
        pmax (float | None | Unset): Upper percentile clip for stretch=percentile (0–100, default
            98). Absent = current p98 behavior. Must be greater than pmin.
        sigma (float | None | Unset): Standard-deviation multiplier for stretch=stddev (default
            2.0). Absent = current 2.0σ behavior. Must be > 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        z=z,
        x=x,
        y=y,
        fmt=fmt,
        colormap_name=colormap_name,
        stretch=stretch,
        pmin=pmin,
        pmax=pmax,
        sigma=sigma,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    z: int,
    x: int,
    y: int,
    fmt: str,
    *,
    client: AuthenticatedClient,
    colormap_name: None
    | RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetColormapNameType0
    | Unset = UNSET,
    stretch: None
    | RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetStretchType0
    | Unset = UNSET,
    pmin: float | None | Unset = UNSET,
    pmax: float | None | Unset = UNSET,
    sigma: float | None | Unset = UNSET,
) -> Any | ProblemDetail | None:
    """Raster Tile Proxy

     API-side raster tile proxy: auth check + fetch from Titiler.

    Used by Vite dev proxy and as a fallback for deployments without nginx.
    Production deployments with nginx should use the nginx raster-tiles path
    for better caching and performance.

    colormap_name: Optional Titiler colormap for single-band display. Validated
    against _ALLOWED_COLORMAPS (T-1140-01). Gray is the Titiler default for
    single-band — passing gray is a no-op (not forwarded). colormap_name is not
    forwarded for DEM layers (render_params starts with 'algorithm=').

    stretch: Optional stretch strategy. percentile/stddev compute a stats-based
    rescale from Titiler band statistics. Multi-band rasters produce one rescale=
    fragment per band (up to 3, RASTER-STRETCH-03).

    pmin/pmax: Configurable percentile clip bounds (default 2/98). Must satisfy
    0 <= pmin < pmax <= 100. Forwarded as repeated p= params to /cog/statistics.
    The _band_stats_cache key includes pmin/pmax so different bounds never serve
    stale cached stats (RASTER-STRETCH-UI-01 / Phase 1153 cache-key isolation).

    sigma: Standard-deviation multiplier for stretch=stddev (default 2.0).
    Must be > 0.

    Args:
        dataset_id (UUID):
        z (int):
        x (int):
        y (int):
        fmt (str):
        colormap_name (None | RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetColormapNameType0 |
            Unset): Titiler colormap for single-band display
        stretch (None | RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetStretchType0 | Unset):
            Stretch strategy: minmax (default), percentile, stddev
        pmin (float | None | Unset): Lower percentile clip for stretch=percentile (0–100, default
            2). Absent = current p2 behavior. Must be less than pmax.
        pmax (float | None | Unset): Upper percentile clip for stretch=percentile (0–100, default
            98). Absent = current p98 behavior. Must be greater than pmin.
        sigma (float | None | Unset): Standard-deviation multiplier for stretch=stddev (default
            2.0). Absent = current 2.0σ behavior. Must be > 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        z=z,
        x=x,
        y=y,
        fmt=fmt,
        client=client,
        colormap_name=colormap_name,
        stretch=stretch,
        pmin=pmin,
        pmax=pmax,
        sigma=sigma,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    z: int,
    x: int,
    y: int,
    fmt: str,
    *,
    client: AuthenticatedClient,
    colormap_name: None
    | RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetColormapNameType0
    | Unset = UNSET,
    stretch: None
    | RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetStretchType0
    | Unset = UNSET,
    pmin: float | None | Unset = UNSET,
    pmax: float | None | Unset = UNSET,
    sigma: float | None | Unset = UNSET,
) -> Response[Any | ProblemDetail]:
    """Raster Tile Proxy

     API-side raster tile proxy: auth check + fetch from Titiler.

    Used by Vite dev proxy and as a fallback for deployments without nginx.
    Production deployments with nginx should use the nginx raster-tiles path
    for better caching and performance.

    colormap_name: Optional Titiler colormap for single-band display. Validated
    against _ALLOWED_COLORMAPS (T-1140-01). Gray is the Titiler default for
    single-band — passing gray is a no-op (not forwarded). colormap_name is not
    forwarded for DEM layers (render_params starts with 'algorithm=').

    stretch: Optional stretch strategy. percentile/stddev compute a stats-based
    rescale from Titiler band statistics. Multi-band rasters produce one rescale=
    fragment per band (up to 3, RASTER-STRETCH-03).

    pmin/pmax: Configurable percentile clip bounds (default 2/98). Must satisfy
    0 <= pmin < pmax <= 100. Forwarded as repeated p= params to /cog/statistics.
    The _band_stats_cache key includes pmin/pmax so different bounds never serve
    stale cached stats (RASTER-STRETCH-UI-01 / Phase 1153 cache-key isolation).

    sigma: Standard-deviation multiplier for stretch=stddev (default 2.0).
    Must be > 0.

    Args:
        dataset_id (UUID):
        z (int):
        x (int):
        y (int):
        fmt (str):
        colormap_name (None | RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetColormapNameType0 |
            Unset): Titiler colormap for single-band display
        stretch (None | RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetStretchType0 | Unset):
            Stretch strategy: minmax (default), percentile, stddev
        pmin (float | None | Unset): Lower percentile clip for stretch=percentile (0–100, default
            2). Absent = current p2 behavior. Must be less than pmax.
        pmax (float | None | Unset): Upper percentile clip for stretch=percentile (0–100, default
            98). Absent = current p98 behavior. Must be greater than pmin.
        sigma (float | None | Unset): Standard-deviation multiplier for stretch=stddev (default
            2.0). Absent = current 2.0σ behavior. Must be > 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        z=z,
        x=x,
        y=y,
        fmt=fmt,
        colormap_name=colormap_name,
        stretch=stretch,
        pmin=pmin,
        pmax=pmax,
        sigma=sigma,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    z: int,
    x: int,
    y: int,
    fmt: str,
    *,
    client: AuthenticatedClient,
    colormap_name: None
    | RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetColormapNameType0
    | Unset = UNSET,
    stretch: None
    | RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetStretchType0
    | Unset = UNSET,
    pmin: float | None | Unset = UNSET,
    pmax: float | None | Unset = UNSET,
    sigma: float | None | Unset = UNSET,
) -> Any | ProblemDetail | None:
    """Raster Tile Proxy

     API-side raster tile proxy: auth check + fetch from Titiler.

    Used by Vite dev proxy and as a fallback for deployments without nginx.
    Production deployments with nginx should use the nginx raster-tiles path
    for better caching and performance.

    colormap_name: Optional Titiler colormap for single-band display. Validated
    against _ALLOWED_COLORMAPS (T-1140-01). Gray is the Titiler default for
    single-band — passing gray is a no-op (not forwarded). colormap_name is not
    forwarded for DEM layers (render_params starts with 'algorithm=').

    stretch: Optional stretch strategy. percentile/stddev compute a stats-based
    rescale from Titiler band statistics. Multi-band rasters produce one rescale=
    fragment per band (up to 3, RASTER-STRETCH-03).

    pmin/pmax: Configurable percentile clip bounds (default 2/98). Must satisfy
    0 <= pmin < pmax <= 100. Forwarded as repeated p= params to /cog/statistics.
    The _band_stats_cache key includes pmin/pmax so different bounds never serve
    stale cached stats (RASTER-STRETCH-UI-01 / Phase 1153 cache-key isolation).

    sigma: Standard-deviation multiplier for stretch=stddev (default 2.0).
    Must be > 0.

    Args:
        dataset_id (UUID):
        z (int):
        x (int):
        y (int):
        fmt (str):
        colormap_name (None | RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetColormapNameType0 |
            Unset): Titiler colormap for single-band display
        stretch (None | RasterTileProxyTilesRasterProxyDatasetIdZXYFmtGetStretchType0 | Unset):
            Stretch strategy: minmax (default), percentile, stddev
        pmin (float | None | Unset): Lower percentile clip for stretch=percentile (0–100, default
            2). Absent = current p2 behavior. Must be less than pmax.
        pmax (float | None | Unset): Upper percentile clip for stretch=percentile (0–100, default
            98). Absent = current p98 behavior. Must be greater than pmin.
        sigma (float | None | Unset): Standard-deviation multiplier for stretch=stddev (default
            2.0). Absent = current 2.0σ behavior. Must be > 0.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            z=z,
            x=x,
            y=y,
            fmt=fmt,
            client=client,
            colormap_name=colormap_name,
            stretch=stretch,
            pmin=pmin,
            pmax=pmax,
            sigma=sigma,
        )
    ).parsed

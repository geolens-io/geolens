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

    if response.status_code == 401:
        response_401 = ProblemDetail.from_dict(response.json())

        return response_401

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

     Render one raster tile and return the image.

    Returns the image itself rather than a redirect: the dataset is
    authorized, then the rendered tile comes back in the response body. Used by
    the development proxy and by deployments that run without nginx in front.

    ``colormap_name`` applies a colormap to a single-band raster. Passing
    ``gray`` leaves the rendering unchanged, and a digital elevation model
    ignores the parameter, because its terrain encoding cannot be recoloured.

    ``stretch`` chooses how pixel values map to the output range. ``minmax``
    keeps the range the dataset already implies: the recorded per-band minimum
    and maximum for a raster imported from a remote source that published
    statistics, a range derived from the data type for most others, and no
    rescale parameter for 8-bit data, which needs none. ``percentile`` and
    ``stddev`` instead derive a range from band statistics read at request
    time, for up to three bands. A digital elevation model ignores the
    parameter, and so does a request whose band statistics cannot be read,
    which falls back to ``minmax`` rather than failing.

    ``pmin`` and ``pmax`` (2 and 98 by default) are read when ``stretch`` is
    ``percentile``, and ``sigma`` (2.0 by default) when it is ``stddev``. A
    parameter that does not apply to the selected stretch is ignored, and its
    default is used in place of the value sent.

    Responds 204 when the tile falls outside the raster, 400 for an
    unsupported format, 401 when authentication is required, or when a request
    that no capability authorized carried a credential which did not resolve,
    403 when the embed token is invalid or expired
    or a multi-tenant request arrives with no tenant context, 422 for an
    out-of-range stretch parameter, and 503 when the renderer cannot be
    reached. A different failure from the renderer is passed through with its
    own status.

    404 covers more than a missing dataset. A dataset that is unknown, is not a
    raster or has no image answers 404. Where no capability authorized the
    request, so does a dataset the caller may not read: an authorization denial
    on a non-public raster, and an unpublished raster asked for by a caller who
    is neither its owner nor an admin. That is deliberate, so a refusal keeps a
    dataset's existence undisclosed.

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
            2). Absent = current p2 behavior. Must be less than pmax. Ignored, and not validated, when
            stretch is not percentile.
        pmax (float | None | Unset): Upper percentile clip for stretch=percentile (0–100, default
            98). Absent = current p98 behavior. Must be greater than pmin. Ignored, and not validated,
            when stretch is not percentile.
        sigma (float | None | Unset): Standard-deviation multiplier for stretch=stddev (default
            2.0). Absent = current 2.0σ behavior. Must be > 0. Ignored, and not validated, when
            stretch is not stddev.

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

     Render one raster tile and return the image.

    Returns the image itself rather than a redirect: the dataset is
    authorized, then the rendered tile comes back in the response body. Used by
    the development proxy and by deployments that run without nginx in front.

    ``colormap_name`` applies a colormap to a single-band raster. Passing
    ``gray`` leaves the rendering unchanged, and a digital elevation model
    ignores the parameter, because its terrain encoding cannot be recoloured.

    ``stretch`` chooses how pixel values map to the output range. ``minmax``
    keeps the range the dataset already implies: the recorded per-band minimum
    and maximum for a raster imported from a remote source that published
    statistics, a range derived from the data type for most others, and no
    rescale parameter for 8-bit data, which needs none. ``percentile`` and
    ``stddev`` instead derive a range from band statistics read at request
    time, for up to three bands. A digital elevation model ignores the
    parameter, and so does a request whose band statistics cannot be read,
    which falls back to ``minmax`` rather than failing.

    ``pmin`` and ``pmax`` (2 and 98 by default) are read when ``stretch`` is
    ``percentile``, and ``sigma`` (2.0 by default) when it is ``stddev``. A
    parameter that does not apply to the selected stretch is ignored, and its
    default is used in place of the value sent.

    Responds 204 when the tile falls outside the raster, 400 for an
    unsupported format, 401 when authentication is required, or when a request
    that no capability authorized carried a credential which did not resolve,
    403 when the embed token is invalid or expired
    or a multi-tenant request arrives with no tenant context, 422 for an
    out-of-range stretch parameter, and 503 when the renderer cannot be
    reached. A different failure from the renderer is passed through with its
    own status.

    404 covers more than a missing dataset. A dataset that is unknown, is not a
    raster or has no image answers 404. Where no capability authorized the
    request, so does a dataset the caller may not read: an authorization denial
    on a non-public raster, and an unpublished raster asked for by a caller who
    is neither its owner nor an admin. That is deliberate, so a refusal keeps a
    dataset's existence undisclosed.

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
            2). Absent = current p2 behavior. Must be less than pmax. Ignored, and not validated, when
            stretch is not percentile.
        pmax (float | None | Unset): Upper percentile clip for stretch=percentile (0–100, default
            98). Absent = current p98 behavior. Must be greater than pmin. Ignored, and not validated,
            when stretch is not percentile.
        sigma (float | None | Unset): Standard-deviation multiplier for stretch=stddev (default
            2.0). Absent = current 2.0σ behavior. Must be > 0. Ignored, and not validated, when
            stretch is not stddev.

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

     Render one raster tile and return the image.

    Returns the image itself rather than a redirect: the dataset is
    authorized, then the rendered tile comes back in the response body. Used by
    the development proxy and by deployments that run without nginx in front.

    ``colormap_name`` applies a colormap to a single-band raster. Passing
    ``gray`` leaves the rendering unchanged, and a digital elevation model
    ignores the parameter, because its terrain encoding cannot be recoloured.

    ``stretch`` chooses how pixel values map to the output range. ``minmax``
    keeps the range the dataset already implies: the recorded per-band minimum
    and maximum for a raster imported from a remote source that published
    statistics, a range derived from the data type for most others, and no
    rescale parameter for 8-bit data, which needs none. ``percentile`` and
    ``stddev`` instead derive a range from band statistics read at request
    time, for up to three bands. A digital elevation model ignores the
    parameter, and so does a request whose band statistics cannot be read,
    which falls back to ``minmax`` rather than failing.

    ``pmin`` and ``pmax`` (2 and 98 by default) are read when ``stretch`` is
    ``percentile``, and ``sigma`` (2.0 by default) when it is ``stddev``. A
    parameter that does not apply to the selected stretch is ignored, and its
    default is used in place of the value sent.

    Responds 204 when the tile falls outside the raster, 400 for an
    unsupported format, 401 when authentication is required, or when a request
    that no capability authorized carried a credential which did not resolve,
    403 when the embed token is invalid or expired
    or a multi-tenant request arrives with no tenant context, 422 for an
    out-of-range stretch parameter, and 503 when the renderer cannot be
    reached. A different failure from the renderer is passed through with its
    own status.

    404 covers more than a missing dataset. A dataset that is unknown, is not a
    raster or has no image answers 404. Where no capability authorized the
    request, so does a dataset the caller may not read: an authorization denial
    on a non-public raster, and an unpublished raster asked for by a caller who
    is neither its owner nor an admin. That is deliberate, so a refusal keeps a
    dataset's existence undisclosed.

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
            2). Absent = current p2 behavior. Must be less than pmax. Ignored, and not validated, when
            stretch is not percentile.
        pmax (float | None | Unset): Upper percentile clip for stretch=percentile (0–100, default
            98). Absent = current p98 behavior. Must be greater than pmin. Ignored, and not validated,
            when stretch is not percentile.
        sigma (float | None | Unset): Standard-deviation multiplier for stretch=stddev (default
            2.0). Absent = current 2.0σ behavior. Must be > 0. Ignored, and not validated, when
            stretch is not stddev.

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

     Render one raster tile and return the image.

    Returns the image itself rather than a redirect: the dataset is
    authorized, then the rendered tile comes back in the response body. Used by
    the development proxy and by deployments that run without nginx in front.

    ``colormap_name`` applies a colormap to a single-band raster. Passing
    ``gray`` leaves the rendering unchanged, and a digital elevation model
    ignores the parameter, because its terrain encoding cannot be recoloured.

    ``stretch`` chooses how pixel values map to the output range. ``minmax``
    keeps the range the dataset already implies: the recorded per-band minimum
    and maximum for a raster imported from a remote source that published
    statistics, a range derived from the data type for most others, and no
    rescale parameter for 8-bit data, which needs none. ``percentile`` and
    ``stddev`` instead derive a range from band statistics read at request
    time, for up to three bands. A digital elevation model ignores the
    parameter, and so does a request whose band statistics cannot be read,
    which falls back to ``minmax`` rather than failing.

    ``pmin`` and ``pmax`` (2 and 98 by default) are read when ``stretch`` is
    ``percentile``, and ``sigma`` (2.0 by default) when it is ``stddev``. A
    parameter that does not apply to the selected stretch is ignored, and its
    default is used in place of the value sent.

    Responds 204 when the tile falls outside the raster, 400 for an
    unsupported format, 401 when authentication is required, or when a request
    that no capability authorized carried a credential which did not resolve,
    403 when the embed token is invalid or expired
    or a multi-tenant request arrives with no tenant context, 422 for an
    out-of-range stretch parameter, and 503 when the renderer cannot be
    reached. A different failure from the renderer is passed through with its
    own status.

    404 covers more than a missing dataset. A dataset that is unknown, is not a
    raster or has no image answers 404. Where no capability authorized the
    request, so does a dataset the caller may not read: an authorization denial
    on a non-public raster, and an unpublished raster asked for by a caller who
    is neither its owner nor an admin. That is deliberate, so a refusal keeps a
    dataset's existence undisclosed.

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
            2). Absent = current p2 behavior. Must be less than pmax. Ignored, and not validated, when
            stretch is not percentile.
        pmax (float | None | Unset): Upper percentile clip for stretch=percentile (0–100, default
            98). Absent = current p98 behavior. Must be greater than pmin. Ignored, and not validated,
            when stretch is not percentile.
        sigma (float | None | Unset): Standard-deviation multiplier for stretch=stddev (default
            2.0). Absent = current 2.0σ behavior. Must be > 0. Ignored, and not validated, when
            stretch is not stddev.

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

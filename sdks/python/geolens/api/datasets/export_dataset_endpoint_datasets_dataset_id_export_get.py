from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.export_format import ExportFormat
from ...models.http_validation_error import HTTPValidationError
from ...models.problem_detail import ProblemDetail
from ...types import Unset
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    *,
    format_: ExportFormat | Unset = UNSET,
    target_crs: None | str | Unset = UNSET,
    bbox: None | str | Unset = UNSET,
    where: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_format_: str | Unset = UNSET
    if not isinstance(format_, Unset):
        json_format_ = format_

    params["format"] = json_format_

    json_target_crs: None | str | Unset
    if isinstance(target_crs, Unset):
        json_target_crs = UNSET
    else:
        json_target_crs = target_crs
    params["target_crs"] = json_target_crs

    json_bbox: None | str | Unset
    if isinstance(bbox, Unset):
        json_bbox = UNSET
    else:
        json_bbox = bbox
    params["bbox"] = json_bbox

    json_where: None | str | Unset
    if isinstance(where, Unset):
        json_where = UNSET
    else:
        json_where = where
    params["where"] = json_where

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/datasets/{dataset_id}/export".format(
            dataset_id=quote(str(dataset_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | HTTPValidationError | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = cast(Any, None)
        return response_200

    if response.status_code == 400:
        response_400 = ProblemDetail.from_dict(response.json())

        return response_400

    if response.status_code == 403:
        response_403 = ProblemDetail.from_dict(response.json())

        return response_403

    if response.status_code == 404:
        response_404 = ProblemDetail.from_dict(response.json())

        return response_404

    if response.status_code == 413:
        response_413 = ProblemDetail.from_dict(response.json())

        return response_413

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())

        return response_422

    if response.status_code == 429:
        response_429 = ProblemDetail.from_dict(response.json())

        return response_429

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
) -> Response[Any | HTTPValidationError | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    format_: ExportFormat | Unset = UNSET,
    target_crs: None | str | Unset = UNSET,
    bbox: None | str | Unset = UNSET,
    where: None | str | Unset = UNSET,
) -> Response[Any | HTTPValidationError | ProblemDetail]:
    """Export Dataset Endpoint

     Export a dataset as a downloadable file.

    Supports GeoPackage, GeoJSON, Shapefile (zipped), CSV, and GeoParquet
    formats. Optional CRS reprojection, spatial filtering, and attribute
    filtering. GeoParquet is always emitted in EPSG:4326 (OGC:CRS84).

    Args:
        dataset_id (UUID):
        format_ (ExportFormat | Unset):
        target_crs (None | str | Unset): Target CRS, e.g. EPSG:3857
        bbox (None | str | Unset): Bounding box: minx,miny,maxx,maxy (WGS84)
        where (None | str | Unset): Attribute filter expression, e.g. pop > 1000

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        format_=format_,
        target_crs=target_crs,
        bbox=bbox,
        where=where,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    format_: ExportFormat | Unset = UNSET,
    target_crs: None | str | Unset = UNSET,
    bbox: None | str | Unset = UNSET,
    where: None | str | Unset = UNSET,
) -> Any | HTTPValidationError | ProblemDetail | None:
    """Export Dataset Endpoint

     Export a dataset as a downloadable file.

    Supports GeoPackage, GeoJSON, Shapefile (zipped), CSV, and GeoParquet
    formats. Optional CRS reprojection, spatial filtering, and attribute
    filtering. GeoParquet is always emitted in EPSG:4326 (OGC:CRS84).

    Args:
        dataset_id (UUID):
        format_ (ExportFormat | Unset):
        target_crs (None | str | Unset): Target CRS, e.g. EPSG:3857
        bbox (None | str | Unset): Bounding box: minx,miny,maxx,maxy (WGS84)
        where (None | str | Unset): Attribute filter expression, e.g. pop > 1000

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        client=client,
        format_=format_,
        target_crs=target_crs,
        bbox=bbox,
        where=where,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    format_: ExportFormat | Unset = UNSET,
    target_crs: None | str | Unset = UNSET,
    bbox: None | str | Unset = UNSET,
    where: None | str | Unset = UNSET,
) -> Response[Any | HTTPValidationError | ProblemDetail]:
    """Export Dataset Endpoint

     Export a dataset as a downloadable file.

    Supports GeoPackage, GeoJSON, Shapefile (zipped), CSV, and GeoParquet
    formats. Optional CRS reprojection, spatial filtering, and attribute
    filtering. GeoParquet is always emitted in EPSG:4326 (OGC:CRS84).

    Args:
        dataset_id (UUID):
        format_ (ExportFormat | Unset):
        target_crs (None | str | Unset): Target CRS, e.g. EPSG:3857
        bbox (None | str | Unset): Bounding box: minx,miny,maxx,maxy (WGS84)
        where (None | str | Unset): Attribute filter expression, e.g. pop > 1000

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        format_=format_,
        target_crs=target_crs,
        bbox=bbox,
        where=where,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    format_: ExportFormat | Unset = UNSET,
    target_crs: None | str | Unset = UNSET,
    bbox: None | str | Unset = UNSET,
    where: None | str | Unset = UNSET,
) -> Any | HTTPValidationError | ProblemDetail | None:
    """Export Dataset Endpoint

     Export a dataset as a downloadable file.

    Supports GeoPackage, GeoJSON, Shapefile (zipped), CSV, and GeoParquet
    formats. Optional CRS reprojection, spatial filtering, and attribute
    filtering. GeoParquet is always emitted in EPSG:4326 (OGC:CRS84).

    Args:
        dataset_id (UUID):
        format_ (ExportFormat | Unset):
        target_crs (None | str | Unset): Target CRS, e.g. EPSG:3857
        bbox (None | str | Unset): Bounding box: minx,miny,maxx,maxy (WGS84)
        where (None | str | Unset): Attribute filter expression, e.g. pop > 1000

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            client=client,
            format_=format_,
            target_crs=target_crs,
            bbox=bbox,
            where=where,
        )
    ).parsed

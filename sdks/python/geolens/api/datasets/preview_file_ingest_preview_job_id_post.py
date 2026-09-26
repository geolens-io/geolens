from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.point_cloud_preview_response import PointCloudPreviewResponse
from ...models.preview_response import PreviewResponse
from ...models.problem_detail import ProblemDetail
from ...models.raster_preview_response import RasterPreviewResponse
from ...models.tileset_preview_response import TilesetPreviewResponse
from ...types import Unset
from uuid import UUID


def _get_kwargs(
    job_id: UUID,
    *,
    layer_name: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    json_layer_name: None | str | Unset
    if isinstance(layer_name, Unset):
        json_layer_name = UNSET
    else:
        json_layer_name = layer_name
    params["layer_name"] = json_layer_name

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/ingest/preview/{job_id}".format(
            job_id=quote(str(job_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    PointCloudPreviewResponse
    | PreviewResponse
    | RasterPreviewResponse
    | TilesetPreviewResponse
    | ProblemDetail
    | None
):
    if response.status_code == 200:

        def _parse_response_200(
            data: object,
        ) -> (
            PointCloudPreviewResponse
            | PreviewResponse
            | RasterPreviewResponse
            | TilesetPreviewResponse
        ):
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                response_200_type_0 = PreviewResponse.from_dict(data)

                return response_200_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                response_200_type_1 = RasterPreviewResponse.from_dict(data)

                return response_200_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                response_200_type_2 = TilesetPreviewResponse.from_dict(data)

                return response_200_type_2
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            if not isinstance(data, dict):
                raise TypeError()
            response_200_type_3 = PointCloudPreviewResponse.from_dict(data)

            return response_200_type_3

        response_200 = _parse_response_200(response.json())

        return response_200

    if response.status_code == 400:
        response_400 = ProblemDetail.from_dict(response.json())

        return response_400

    if response.status_code == 401:
        response_401 = ProblemDetail.from_dict(response.json())

        return response_401

    if response.status_code == 403:
        response_403 = ProblemDetail.from_dict(response.json())

        return response_403

    if response.status_code == 404:
        response_404 = ProblemDetail.from_dict(response.json())

        return response_404

    if response.status_code == 409:
        response_409 = ProblemDetail.from_dict(response.json())

        return response_409

    if response.status_code == 422:
        response_422 = ProblemDetail.from_dict(response.json())

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
) -> Response[
    PointCloudPreviewResponse
    | PreviewResponse
    | RasterPreviewResponse
    | TilesetPreviewResponse
    | ProblemDetail
]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    job_id: UUID,
    *,
    client: AuthenticatedClient,
    layer_name: None | str | Unset = UNSET,
) -> Response[
    PointCloudPreviewResponse
    | PreviewResponse
    | RasterPreviewResponse
    | TilesetPreviewResponse
    | ProblemDetail
]:
    """Preview File

     Run preview on a staged file and return preview data.

    For vector files: returns columns, CRS, geometry type, feature count, sample rows.
    For raster files: returns band count, CRS, resolution, compliance status.
    For a 3D Tiles tileset: returns its version, root geometric error, bounding
    volume kind, extent and unpacked size, read from the archive's directory
    and tileset.json without unpacking it.
    For a COPC point cloud: returns its point count and format, CRS, extent,
    elevation range and size, read from its header and hierarchy.
    Only callable on jobs with status 'pending'.

    Args:
        job_id (UUID):
        layer_name (None | str | Unset): Sheet/layer name for multi-layer files

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PointCloudPreviewResponse | PreviewResponse | RasterPreviewResponse | TilesetPreviewResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        job_id=job_id,
        layer_name=layer_name,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    job_id: UUID,
    *,
    client: AuthenticatedClient,
    layer_name: None | str | Unset = UNSET,
) -> (
    PointCloudPreviewResponse
    | PreviewResponse
    | RasterPreviewResponse
    | TilesetPreviewResponse
    | ProblemDetail
    | None
):
    """Preview File

     Run preview on a staged file and return preview data.

    For vector files: returns columns, CRS, geometry type, feature count, sample rows.
    For raster files: returns band count, CRS, resolution, compliance status.
    For a 3D Tiles tileset: returns its version, root geometric error, bounding
    volume kind, extent and unpacked size, read from the archive's directory
    and tileset.json without unpacking it.
    For a COPC point cloud: returns its point count and format, CRS, extent,
    elevation range and size, read from its header and hierarchy.
    Only callable on jobs with status 'pending'.

    Args:
        job_id (UUID):
        layer_name (None | str | Unset): Sheet/layer name for multi-layer files

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PointCloudPreviewResponse | PreviewResponse | RasterPreviewResponse | TilesetPreviewResponse | ProblemDetail
    """

    return sync_detailed(
        job_id=job_id,
        client=client,
        layer_name=layer_name,
    ).parsed


async def asyncio_detailed(
    job_id: UUID,
    *,
    client: AuthenticatedClient,
    layer_name: None | str | Unset = UNSET,
) -> Response[
    PointCloudPreviewResponse
    | PreviewResponse
    | RasterPreviewResponse
    | TilesetPreviewResponse
    | ProblemDetail
]:
    """Preview File

     Run preview on a staged file and return preview data.

    For vector files: returns columns, CRS, geometry type, feature count, sample rows.
    For raster files: returns band count, CRS, resolution, compliance status.
    For a 3D Tiles tileset: returns its version, root geometric error, bounding
    volume kind, extent and unpacked size, read from the archive's directory
    and tileset.json without unpacking it.
    For a COPC point cloud: returns its point count and format, CRS, extent,
    elevation range and size, read from its header and hierarchy.
    Only callable on jobs with status 'pending'.

    Args:
        job_id (UUID):
        layer_name (None | str | Unset): Sheet/layer name for multi-layer files

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[PointCloudPreviewResponse | PreviewResponse | RasterPreviewResponse | TilesetPreviewResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        job_id=job_id,
        layer_name=layer_name,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    job_id: UUID,
    *,
    client: AuthenticatedClient,
    layer_name: None | str | Unset = UNSET,
) -> (
    PointCloudPreviewResponse
    | PreviewResponse
    | RasterPreviewResponse
    | TilesetPreviewResponse
    | ProblemDetail
    | None
):
    """Preview File

     Run preview on a staged file and return preview data.

    For vector files: returns columns, CRS, geometry type, feature count, sample rows.
    For raster files: returns band count, CRS, resolution, compliance status.
    For a 3D Tiles tileset: returns its version, root geometric error, bounding
    volume kind, extent and unpacked size, read from the archive's directory
    and tileset.json without unpacking it.
    For a COPC point cloud: returns its point count and format, CRS, extent,
    elevation range and size, read from its header and hierarchy.
    Only callable on jobs with status 'pending'.

    Args:
        job_id (UUID):
        layer_name (None | str | Unset): Sheet/layer name for multi-layer files

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        PointCloudPreviewResponse | PreviewResponse | RasterPreviewResponse | TilesetPreviewResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            job_id=job_id,
            client=client,
            layer_name=layer_name,
        )
    ).parsed

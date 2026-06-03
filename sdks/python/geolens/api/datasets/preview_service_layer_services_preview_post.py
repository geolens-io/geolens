from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...models.service_preview_request import ServicePreviewRequest
from ...models.service_preview_response import ServicePreviewResponse


def _get_kwargs(
    *,
    body: ServicePreviewRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/services/preview/",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ProblemDetail | ServicePreviewResponse | None:
    if response.status_code == 200:
        response_200 = ServicePreviewResponse.from_dict(response.json())

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

    if response.status_code == 500:
        response_500 = ProblemDetail.from_dict(response.json())

        return response_500

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[ProblemDetail | ServicePreviewResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: ServicePreviewRequest,
) -> Response[ProblemDetail | ServicePreviewResponse]:
    """Preview Service Layer

     Preview a selected remote layer via ogrinfo and create a pending IngestJob.

    Validates the URL against SSRF, builds the GDAL driver source string,
    runs ogrinfo to extract metadata and sample rows, then creates an IngestJob
    ready for the existing commit flow.

    Args:
        body (ServicePreviewRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | ServicePreviewResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: ServicePreviewRequest,
) -> ProblemDetail | ServicePreviewResponse | None:
    """Preview Service Layer

     Preview a selected remote layer via ogrinfo and create a pending IngestJob.

    Validates the URL against SSRF, builds the GDAL driver source string,
    runs ogrinfo to extract metadata and sample rows, then creates an IngestJob
    ready for the existing commit flow.

    Args:
        body (ServicePreviewRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | ServicePreviewResponse
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: ServicePreviewRequest,
) -> Response[ProblemDetail | ServicePreviewResponse]:
    """Preview Service Layer

     Preview a selected remote layer via ogrinfo and create a pending IngestJob.

    Validates the URL against SSRF, builds the GDAL driver source string,
    runs ogrinfo to extract metadata and sample rows, then creates an IngestJob
    ready for the existing commit flow.

    Args:
        body (ServicePreviewRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | ServicePreviewResponse]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: ServicePreviewRequest,
) -> ProblemDetail | ServicePreviewResponse | None:
    """Preview Service Layer

     Preview a selected remote layer via ogrinfo and create a pending IngestJob.

    Validates the URL against SSRF, builds the GDAL driver source string,
    runs ogrinfo to extract metadata and sample rows, then creates an IngestJob
    ready for the existing commit flow.

    Args:
        body (ServicePreviewRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | ServicePreviewResponse
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed

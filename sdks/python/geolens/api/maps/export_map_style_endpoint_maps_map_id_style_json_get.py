from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.export_map_style_endpoint_maps_map_id_style_json_get_response_200 import (
    ExportMapStyleEndpointMapsMapIdStyleJsonGetResponse200,
)
from ...models.problem_detail import ProblemDetail
from uuid import UUID


def _get_kwargs(
    map_id: UUID,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/maps/{map_id}/style.json".format(
            map_id=quote(str(map_id), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ExportMapStyleEndpointMapsMapIdStyleJsonGetResponse200 | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = ExportMapStyleEndpointMapsMapIdStyleJsonGetResponse200.from_dict(
            response.json()
        )

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
) -> Response[ExportMapStyleEndpointMapsMapIdStyleJsonGetResponse200 | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    map_id: UUID,
    *,
    client: AuthenticatedClient,
) -> Response[ExportMapStyleEndpointMapsMapIdStyleJsonGetResponse200 | ProblemDetail]:
    """Export Map Style Endpoint

     Export a saved map as a complete MapLibre style JSON document.

    Args:
        map_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ExportMapStyleEndpointMapsMapIdStyleJsonGetResponse200 | ProblemDetail]
    """

    kwargs = _get_kwargs(
        map_id=map_id,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    map_id: UUID,
    *,
    client: AuthenticatedClient,
) -> ExportMapStyleEndpointMapsMapIdStyleJsonGetResponse200 | ProblemDetail | None:
    """Export Map Style Endpoint

     Export a saved map as a complete MapLibre style JSON document.

    Args:
        map_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ExportMapStyleEndpointMapsMapIdStyleJsonGetResponse200 | ProblemDetail
    """

    return sync_detailed(
        map_id=map_id,
        client=client,
    ).parsed


async def asyncio_detailed(
    map_id: UUID,
    *,
    client: AuthenticatedClient,
) -> Response[ExportMapStyleEndpointMapsMapIdStyleJsonGetResponse200 | ProblemDetail]:
    """Export Map Style Endpoint

     Export a saved map as a complete MapLibre style JSON document.

    Args:
        map_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ExportMapStyleEndpointMapsMapIdStyleJsonGetResponse200 | ProblemDetail]
    """

    kwargs = _get_kwargs(
        map_id=map_id,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    map_id: UUID,
    *,
    client: AuthenticatedClient,
) -> ExportMapStyleEndpointMapsMapIdStyleJsonGetResponse200 | ProblemDetail | None:
    """Export Map Style Endpoint

     Export a saved map as a complete MapLibre style JSON document.

    Args:
        map_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ExportMapStyleEndpointMapsMapIdStyleJsonGetResponse200 | ProblemDetail
    """

    return (
        await asyncio_detailed(
            map_id=map_id,
            client=client,
        )
    ).parsed

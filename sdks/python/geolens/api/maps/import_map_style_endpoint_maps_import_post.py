from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.map_style_import_request import MapStyleImportRequest
from ...models.map_style_import_response import MapStyleImportResponse
from ...models.problem_detail import ProblemDetail


def _get_kwargs(
    *,
    body: MapStyleImportRequest,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/maps/import",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> MapStyleImportResponse | ProblemDetail | None:
    if response.status_code == 201:
        response_201 = MapStyleImportResponse.from_dict(response.json())

        return response_201

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
) -> Response[MapStyleImportResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: MapStyleImportRequest,
) -> Response[MapStyleImportResponse | ProblemDetail]:
    r"""Import Map Style Endpoint

     Import a MapLibre style JSON document into a new GeoLens map.

    API-01 (M-05): the request body is now a typed Pydantic model instead of
    a bare ``dict``. ``MapStyleImportRequest`` mirrors the MapLibre style
    spec top-level keys with ``extra=\"allow\"``, so existing payloads keep
    working byte-identically while the OpenAPI schema gains a named class
    and the auto-generated SDKs stop emitting an opaque ``Mapping[str, Any]``
    request type.

    Args:
        body (MapStyleImportRequest): Typed request body for POST /maps/import — API-01 / M-05.

            Mirrors the top-level keys of the MapLibre Style Specification that
            ``parse_maplibre_style_import`` actually reads. ``extra="allow"`` keeps
            forward-compatibility with future MapLibre fields (e.g. ``projection``,
            ``light``, ``transition``) so adding a new key on the client side
            doesn't require a server release.

            Replacing the previous bare-``dict`` body parameter removes
            ``additionalProperties: true`` from the OpenAPI schema and lets
            openapi-python-client generate a navigable named model class.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[MapStyleImportResponse | ProblemDetail]
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
    body: MapStyleImportRequest,
) -> MapStyleImportResponse | ProblemDetail | None:
    r"""Import Map Style Endpoint

     Import a MapLibre style JSON document into a new GeoLens map.

    API-01 (M-05): the request body is now a typed Pydantic model instead of
    a bare ``dict``. ``MapStyleImportRequest`` mirrors the MapLibre style
    spec top-level keys with ``extra=\"allow\"``, so existing payloads keep
    working byte-identically while the OpenAPI schema gains a named class
    and the auto-generated SDKs stop emitting an opaque ``Mapping[str, Any]``
    request type.

    Args:
        body (MapStyleImportRequest): Typed request body for POST /maps/import — API-01 / M-05.

            Mirrors the top-level keys of the MapLibre Style Specification that
            ``parse_maplibre_style_import`` actually reads. ``extra="allow"`` keeps
            forward-compatibility with future MapLibre fields (e.g. ``projection``,
            ``light``, ``transition``) so adding a new key on the client side
            doesn't require a server release.

            Replacing the previous bare-``dict`` body parameter removes
            ``additionalProperties: true`` from the OpenAPI schema and lets
            openapi-python-client generate a navigable named model class.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        MapStyleImportResponse | ProblemDetail
    """

    return sync_detailed(
        client=client,
        body=body,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: MapStyleImportRequest,
) -> Response[MapStyleImportResponse | ProblemDetail]:
    r"""Import Map Style Endpoint

     Import a MapLibre style JSON document into a new GeoLens map.

    API-01 (M-05): the request body is now a typed Pydantic model instead of
    a bare ``dict``. ``MapStyleImportRequest`` mirrors the MapLibre style
    spec top-level keys with ``extra=\"allow\"``, so existing payloads keep
    working byte-identically while the OpenAPI schema gains a named class
    and the auto-generated SDKs stop emitting an opaque ``Mapping[str, Any]``
    request type.

    Args:
        body (MapStyleImportRequest): Typed request body for POST /maps/import — API-01 / M-05.

            Mirrors the top-level keys of the MapLibre Style Specification that
            ``parse_maplibre_style_import`` actually reads. ``extra="allow"`` keeps
            forward-compatibility with future MapLibre fields (e.g. ``projection``,
            ``light``, ``transition``) so adding a new key on the client side
            doesn't require a server release.

            Replacing the previous bare-``dict`` body parameter removes
            ``additionalProperties: true`` from the OpenAPI schema and lets
            openapi-python-client generate a navigable named model class.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[MapStyleImportResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        body=body,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: MapStyleImportRequest,
) -> MapStyleImportResponse | ProblemDetail | None:
    r"""Import Map Style Endpoint

     Import a MapLibre style JSON document into a new GeoLens map.

    API-01 (M-05): the request body is now a typed Pydantic model instead of
    a bare ``dict``. ``MapStyleImportRequest`` mirrors the MapLibre style
    spec top-level keys with ``extra=\"allow\"``, so existing payloads keep
    working byte-identically while the OpenAPI schema gains a named class
    and the auto-generated SDKs stop emitting an opaque ``Mapping[str, Any]``
    request type.

    Args:
        body (MapStyleImportRequest): Typed request body for POST /maps/import — API-01 / M-05.

            Mirrors the top-level keys of the MapLibre Style Specification that
            ``parse_maplibre_style_import`` actually reads. ``extra="allow"`` keeps
            forward-compatibility with future MapLibre fields (e.g. ``projection``,
            ``light``, ``transition``) so adding a new key on the client side
            doesn't require a server release.

            Replacing the previous bare-``dict`` body parameter removes
            ``additionalProperties: true`` from the OpenAPI schema and lets
            openapi-python-client generate a navigable named model class.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        MapStyleImportResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
        )
    ).parsed

from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response
from ... import errors

from ...models.problem_detail import ProblemDetail
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    path: str,
) -> dict[str, Any]:

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/datasets/{dataset_id}/tiles3d/{path}".format(
            dataset_id=quote(str(dataset_id), safe=""),
            path=quote(str(path), safe=""),
        ),
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = cast(Any, None)
        return response_200

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

    if response.status_code == 502:
        response_502 = ProblemDetail.from_dict(response.json())

        return response_502

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
    path: str,
    *,
    client: AuthenticatedClient,
) -> Response[Any | ProblemDetail]:
    """Get Tileset File

     Serve one file of a published 3D Tiles tileset.

    Point a client at ``/datasets/{dataset_id}/tiles3d/tileset.json``, the
    dataset's ``tileset.url``; the relative URIs inside the tileset resolve to
    this same route. Send credentials in the ``X-Api-Key`` or
    ``Authorization`` header. A browser client on another origin also needs
    that origin on the deployment's CORS allowlist (``CORS_ALLOWED_ORIGINS``).
    A private or missing tileset and a missing file all answer 404, and a
    storage failure answers 502.

    Args:
        dataset_id (UUID):
        path (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        path=path,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    path: str,
    *,
    client: AuthenticatedClient,
) -> Any | ProblemDetail | None:
    """Get Tileset File

     Serve one file of a published 3D Tiles tileset.

    Point a client at ``/datasets/{dataset_id}/tiles3d/tileset.json``, the
    dataset's ``tileset.url``; the relative URIs inside the tileset resolve to
    this same route. Send credentials in the ``X-Api-Key`` or
    ``Authorization`` header. A browser client on another origin also needs
    that origin on the deployment's CORS allowlist (``CORS_ALLOWED_ORIGINS``).
    A private or missing tileset and a missing file all answer 404, and a
    storage failure answers 502.

    Args:
        dataset_id (UUID):
        path (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        path=path,
        client=client,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    path: str,
    *,
    client: AuthenticatedClient,
) -> Response[Any | ProblemDetail]:
    """Get Tileset File

     Serve one file of a published 3D Tiles tileset.

    Point a client at ``/datasets/{dataset_id}/tiles3d/tileset.json``, the
    dataset's ``tileset.url``; the relative URIs inside the tileset resolve to
    this same route. Send credentials in the ``X-Api-Key`` or
    ``Authorization`` header. A browser client on another origin also needs
    that origin on the deployment's CORS allowlist (``CORS_ALLOWED_ORIGINS``).
    A private or missing tileset and a missing file all answer 404, and a
    storage failure answers 502.

    Args:
        dataset_id (UUID):
        path (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        path=path,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    path: str,
    *,
    client: AuthenticatedClient,
) -> Any | ProblemDetail | None:
    """Get Tileset File

     Serve one file of a published 3D Tiles tileset.

    Point a client at ``/datasets/{dataset_id}/tiles3d/tileset.json``, the
    dataset's ``tileset.url``; the relative URIs inside the tileset resolve to
    this same route. Send credentials in the ``X-Api-Key`` or
    ``Authorization`` header. A browser client on another origin also needs
    that origin on the deployment's CORS allowlist (``CORS_ALLOWED_ORIGINS``).
    A private or missing tileset and a missing file all answer 404, and a
    storage failure answers 502.

    Args:
        dataset_id (UUID):
        path (str):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            path=path,
            client=client,
        )
    ).parsed

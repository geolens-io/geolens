from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.backfill_response import BackfillResponse
from ...models.problem_detail import ProblemDetail
from ...types import Unset


def _get_kwargs(
    *,
    force: bool | Unset = False,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["force"] = force

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/admin/backfill-embeddings/",
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> BackfillResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = BackfillResponse.from_dict(response.json())

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
) -> Response[BackfillResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    force: bool | Unset = False,
) -> Response[BackfillResponse | ProblemDetail]:
    """Trigger Backfill

     Trigger semantic-search embedding generation for records (admin only).

    Pass ?force=true to delete all existing embeddings and regenerate from
    scratch (required after changing the embedding model or dimensions).

    Args:
        force (bool | Unset):  Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[BackfillResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        force=force,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    force: bool | Unset = False,
) -> BackfillResponse | ProblemDetail | None:
    """Trigger Backfill

     Trigger semantic-search embedding generation for records (admin only).

    Pass ?force=true to delete all existing embeddings and regenerate from
    scratch (required after changing the embedding model or dimensions).

    Args:
        force (bool | Unset):  Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        BackfillResponse | ProblemDetail
    """

    return sync_detailed(
        client=client,
        force=force,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    force: bool | Unset = False,
) -> Response[BackfillResponse | ProblemDetail]:
    """Trigger Backfill

     Trigger semantic-search embedding generation for records (admin only).

    Pass ?force=true to delete all existing embeddings and regenerate from
    scratch (required after changing the embedding model or dimensions).

    Args:
        force (bool | Unset):  Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[BackfillResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        force=force,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    force: bool | Unset = False,
) -> BackfillResponse | ProblemDetail | None:
    """Trigger Backfill

     Trigger semantic-search embedding generation for records (admin only).

    Pass ?force=true to delete all existing embeddings and regenerate from
    scratch (required after changing the embedding model or dimensions).

    Args:
        force (bool | Unset):  Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        BackfillResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            client=client,
            force=force,
        )
    ).parsed

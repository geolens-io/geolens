from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem_detail import ProblemDetail
from ...models.tile_token_batch_request import TileTokenBatchRequest
from ...models.tile_token_batch_response import TileTokenBatchResponse
from ...types import Unset


def _get_kwargs(
    *,
    body: TileTokenBatchRequest,
    x_embed_token: None | str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(x_embed_token, Unset):
        headers["X-Embed-Token"] = x_embed_token

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/tiles/tokens/",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> ProblemDetail | TileTokenBatchResponse | None:
    if response.status_code == 200:
        response_200 = TileTokenBatchResponse.from_dict(response.json())

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

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Response[ProblemDetail | TileTokenBatchResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: TileTokenBatchRequest,
    x_embed_token: None | str | Unset = UNSET,
) -> Response[ProblemDetail | TileTokenBatchResponse]:
    r"""Get Tile Tokens Batch

     Batch-generate tile tokens for up to 50 datasets in one request.

    Optimization for multi-layer maps: a 20-layer builder map previously
    fired 20 parallel GET /token/{id}/ requests (20 HTTP + 20 RBAC + 20 HMAC
    signatures). This endpoint does the same work in a single round trip
    with one DB query for dataset metadata (PERF-N5).

    Per-dataset errors (404, 403) do not fail the batch — instead the
    response maps the offending dataset_id to ``{\"error\": \"...\"}``. Clients
    should check each entry for the ``error`` key.

    fix(#394) SH-04: ``X-Embed-Token`` is accepted as per-dataset fallback
    authorization (same capability check as tile serving), so embed terrain
    builds its raster-dem source from the real bounds/maxzoom descriptor.

    Args:
        x_embed_token (None | str | Unset):
        body (TileTokenBatchRequest): Batch request for tile tokens — accepts up to 50 dataset
            IDs.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | TileTokenBatchResponse]
    """

    kwargs = _get_kwargs(
        body=body,
        x_embed_token=x_embed_token,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: TileTokenBatchRequest,
    x_embed_token: None | str | Unset = UNSET,
) -> ProblemDetail | TileTokenBatchResponse | None:
    r"""Get Tile Tokens Batch

     Batch-generate tile tokens for up to 50 datasets in one request.

    Optimization for multi-layer maps: a 20-layer builder map previously
    fired 20 parallel GET /token/{id}/ requests (20 HTTP + 20 RBAC + 20 HMAC
    signatures). This endpoint does the same work in a single round trip
    with one DB query for dataset metadata (PERF-N5).

    Per-dataset errors (404, 403) do not fail the batch — instead the
    response maps the offending dataset_id to ``{\"error\": \"...\"}``. Clients
    should check each entry for the ``error`` key.

    fix(#394) SH-04: ``X-Embed-Token`` is accepted as per-dataset fallback
    authorization (same capability check as tile serving), so embed terrain
    builds its raster-dem source from the real bounds/maxzoom descriptor.

    Args:
        x_embed_token (None | str | Unset):
        body (TileTokenBatchRequest): Batch request for tile tokens — accepts up to 50 dataset
            IDs.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | TileTokenBatchResponse
    """

    return sync_detailed(
        client=client,
        body=body,
        x_embed_token=x_embed_token,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: TileTokenBatchRequest,
    x_embed_token: None | str | Unset = UNSET,
) -> Response[ProblemDetail | TileTokenBatchResponse]:
    r"""Get Tile Tokens Batch

     Batch-generate tile tokens for up to 50 datasets in one request.

    Optimization for multi-layer maps: a 20-layer builder map previously
    fired 20 parallel GET /token/{id}/ requests (20 HTTP + 20 RBAC + 20 HMAC
    signatures). This endpoint does the same work in a single round trip
    with one DB query for dataset metadata (PERF-N5).

    Per-dataset errors (404, 403) do not fail the batch — instead the
    response maps the offending dataset_id to ``{\"error\": \"...\"}``. Clients
    should check each entry for the ``error`` key.

    fix(#394) SH-04: ``X-Embed-Token`` is accepted as per-dataset fallback
    authorization (same capability check as tile serving), so embed terrain
    builds its raster-dem source from the real bounds/maxzoom descriptor.

    Args:
        x_embed_token (None | str | Unset):
        body (TileTokenBatchRequest): Batch request for tile tokens — accepts up to 50 dataset
            IDs.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ProblemDetail | TileTokenBatchResponse]
    """

    kwargs = _get_kwargs(
        body=body,
        x_embed_token=x_embed_token,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: TileTokenBatchRequest,
    x_embed_token: None | str | Unset = UNSET,
) -> ProblemDetail | TileTokenBatchResponse | None:
    r"""Get Tile Tokens Batch

     Batch-generate tile tokens for up to 50 datasets in one request.

    Optimization for multi-layer maps: a 20-layer builder map previously
    fired 20 parallel GET /token/{id}/ requests (20 HTTP + 20 RBAC + 20 HMAC
    signatures). This endpoint does the same work in a single round trip
    with one DB query for dataset metadata (PERF-N5).

    Per-dataset errors (404, 403) do not fail the batch — instead the
    response maps the offending dataset_id to ``{\"error\": \"...\"}``. Clients
    should check each entry for the ``error`` key.

    fix(#394) SH-04: ``X-Embed-Token`` is accepted as per-dataset fallback
    authorization (same capability check as tile serving), so embed terrain
    builds its raster-dem source from the real bounds/maxzoom descriptor.

    Args:
        x_embed_token (None | str | Unset):
        body (TileTokenBatchRequest): Batch request for tile tokens — accepts up to 50 dataset
            IDs.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ProblemDetail | TileTokenBatchResponse
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
            x_embed_token=x_embed_token,
        )
    ).parsed

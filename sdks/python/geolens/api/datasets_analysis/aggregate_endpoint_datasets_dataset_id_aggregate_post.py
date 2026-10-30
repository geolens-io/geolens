from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.count_request import CountRequest
from ...models.count_response import CountResponse
from ...models.group_by_request import GroupByRequest
from ...models.group_by_response import GroupByResponse
from ...models.histogram_request import HistogramRequest
from ...models.histogram_response import HistogramResponse
from ...models.problem_detail import ProblemDetail
from ...models.stats_request import StatsRequest
from ...models.stats_response import StatsResponse
from ...models.value_counts_request import ValueCountsRequest
from ...models.value_counts_response import ValueCountsResponse
from ...types import Unset
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    *,
    body: CountRequest
    | GroupByRequest
    | HistogramRequest
    | StatsRequest
    | ValueCountsRequest,
    x_embed_token: None | str | Unset = UNSET,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}
    if not isinstance(x_embed_token, Unset):
        headers["X-Embed-Token"] = x_embed_token

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/datasets/{dataset_id}/aggregate/".format(
            dataset_id=quote(str(dataset_id), safe=""),
        ),
    }

    if isinstance(body, CountRequest):
        _kwargs["json"] = body.to_dict()
    elif isinstance(body, StatsRequest):
        _kwargs["json"] = body.to_dict()
    elif isinstance(body, ValueCountsRequest):
        _kwargs["json"] = body.to_dict()
    elif isinstance(body, HistogramRequest):
        _kwargs["json"] = body.to_dict()
    else:
        _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> (
    CountResponse
    | GroupByResponse
    | HistogramResponse
    | StatsResponse
    | ValueCountsResponse
    | ProblemDetail
    | None
):
    if response.status_code == 200:

        def _parse_response_200(
            data: object,
        ) -> (
            CountResponse
            | GroupByResponse
            | HistogramResponse
            | StatsResponse
            | ValueCountsResponse
        ):
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                response_200_type_0 = CountResponse.from_dict(data)

                return response_200_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                response_200_type_1 = StatsResponse.from_dict(data)

                return response_200_type_1
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                response_200_type_2 = ValueCountsResponse.from_dict(data)

                return response_200_type_2
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            try:
                if not isinstance(data, dict):
                    raise TypeError()
                response_200_type_3 = HistogramResponse.from_dict(data)

                return response_200_type_3
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            if not isinstance(data, dict):
                raise TypeError()
            response_200_type_4 = GroupByResponse.from_dict(data)

            return response_200_type_4

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
    CountResponse
    | GroupByResponse
    | HistogramResponse
    | StatsResponse
    | ValueCountsResponse
    | ProblemDetail
]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: CountRequest
    | GroupByRequest
    | HistogramRequest
    | StatsRequest
    | ValueCountsRequest,
    x_embed_token: None | str | Unset = UNSET,
) -> Response[
    CountResponse
    | GroupByResponse
    | HistogramResponse
    | StatsResponse
    | ValueCountsResponse
    | ProblemDetail
]:
    """Aggregate Endpoint

     Compute one exact aggregate over a dataset's rows, for a widget.

    Anonymous callers can read public, published datasets; ``X-Embed-Token``
    authorizes datasets in the token's scope. Other datasets return 404. A
    request only the embed token authorizes may read only the columns in the
    dataset's tile column allowlist, when it has one; any other column is
    refused as an unknown one.

    With ``bbox``, a view the planner expects to hold more than 500,000 rows
    is refused with 422 and the code ``too_wide`` rather than approximated. A
    ``bbox`` that contains the whole dataset is answered as the whole layer.
    Refusals carry a ``code`` in ``detail``: ``too_wide``, ``invalid_column``,
    ``invalid_filter``, ``no_geometry``, ``query_timeout``,
    ``query_data_error``, ``result_too_large``, and with 429 ``query_busy``
    (this caller already has two aggregates running) or ``query_at_capacity``.

    Clients should keep at most two requests in flight per caller and retry a
    429 after 200-400 ms with jitter.

    Args:
        dataset_id (UUID):
        x_embed_token (None | str | Unset): Optional embed token. Datasets in the token's scope
            are authorized even without user credentials (embed viewers).
        body (CountRequest | GroupByRequest | HistogramRequest | StatsRequest |
            ValueCountsRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CountResponse | GroupByResponse | HistogramResponse | StatsResponse | ValueCountsResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        body=body,
        x_embed_token=x_embed_token,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: CountRequest
    | GroupByRequest
    | HistogramRequest
    | StatsRequest
    | ValueCountsRequest,
    x_embed_token: None | str | Unset = UNSET,
) -> (
    CountResponse
    | GroupByResponse
    | HistogramResponse
    | StatsResponse
    | ValueCountsResponse
    | ProblemDetail
    | None
):
    """Aggregate Endpoint

     Compute one exact aggregate over a dataset's rows, for a widget.

    Anonymous callers can read public, published datasets; ``X-Embed-Token``
    authorizes datasets in the token's scope. Other datasets return 404. A
    request only the embed token authorizes may read only the columns in the
    dataset's tile column allowlist, when it has one; any other column is
    refused as an unknown one.

    With ``bbox``, a view the planner expects to hold more than 500,000 rows
    is refused with 422 and the code ``too_wide`` rather than approximated. A
    ``bbox`` that contains the whole dataset is answered as the whole layer.
    Refusals carry a ``code`` in ``detail``: ``too_wide``, ``invalid_column``,
    ``invalid_filter``, ``no_geometry``, ``query_timeout``,
    ``query_data_error``, ``result_too_large``, and with 429 ``query_busy``
    (this caller already has two aggregates running) or ``query_at_capacity``.

    Clients should keep at most two requests in flight per caller and retry a
    429 after 200-400 ms with jitter.

    Args:
        dataset_id (UUID):
        x_embed_token (None | str | Unset): Optional embed token. Datasets in the token's scope
            are authorized even without user credentials (embed viewers).
        body (CountRequest | GroupByRequest | HistogramRequest | StatsRequest |
            ValueCountsRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CountResponse | GroupByResponse | HistogramResponse | StatsResponse | ValueCountsResponse | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        client=client,
        body=body,
        x_embed_token=x_embed_token,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: CountRequest
    | GroupByRequest
    | HistogramRequest
    | StatsRequest
    | ValueCountsRequest,
    x_embed_token: None | str | Unset = UNSET,
) -> Response[
    CountResponse
    | GroupByResponse
    | HistogramResponse
    | StatsResponse
    | ValueCountsResponse
    | ProblemDetail
]:
    """Aggregate Endpoint

     Compute one exact aggregate over a dataset's rows, for a widget.

    Anonymous callers can read public, published datasets; ``X-Embed-Token``
    authorizes datasets in the token's scope. Other datasets return 404. A
    request only the embed token authorizes may read only the columns in the
    dataset's tile column allowlist, when it has one; any other column is
    refused as an unknown one.

    With ``bbox``, a view the planner expects to hold more than 500,000 rows
    is refused with 422 and the code ``too_wide`` rather than approximated. A
    ``bbox`` that contains the whole dataset is answered as the whole layer.
    Refusals carry a ``code`` in ``detail``: ``too_wide``, ``invalid_column``,
    ``invalid_filter``, ``no_geometry``, ``query_timeout``,
    ``query_data_error``, ``result_too_large``, and with 429 ``query_busy``
    (this caller already has two aggregates running) or ``query_at_capacity``.

    Clients should keep at most two requests in flight per caller and retry a
    429 after 200-400 ms with jitter.

    Args:
        dataset_id (UUID):
        x_embed_token (None | str | Unset): Optional embed token. Datasets in the token's scope
            are authorized even without user credentials (embed viewers).
        body (CountRequest | GroupByRequest | HistogramRequest | StatsRequest |
            ValueCountsRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[CountResponse | GroupByResponse | HistogramResponse | StatsResponse | ValueCountsResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        body=body,
        x_embed_token=x_embed_token,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: CountRequest
    | GroupByRequest
    | HistogramRequest
    | StatsRequest
    | ValueCountsRequest,
    x_embed_token: None | str | Unset = UNSET,
) -> (
    CountResponse
    | GroupByResponse
    | HistogramResponse
    | StatsResponse
    | ValueCountsResponse
    | ProblemDetail
    | None
):
    """Aggregate Endpoint

     Compute one exact aggregate over a dataset's rows, for a widget.

    Anonymous callers can read public, published datasets; ``X-Embed-Token``
    authorizes datasets in the token's scope. Other datasets return 404. A
    request only the embed token authorizes may read only the columns in the
    dataset's tile column allowlist, when it has one; any other column is
    refused as an unknown one.

    With ``bbox``, a view the planner expects to hold more than 500,000 rows
    is refused with 422 and the code ``too_wide`` rather than approximated. A
    ``bbox`` that contains the whole dataset is answered as the whole layer.
    Refusals carry a ``code`` in ``detail``: ``too_wide``, ``invalid_column``,
    ``invalid_filter``, ``no_geometry``, ``query_timeout``,
    ``query_data_error``, ``result_too_large``, and with 429 ``query_busy``
    (this caller already has two aggregates running) or ``query_at_capacity``.

    Clients should keep at most two requests in flight per caller and retry a
    429 after 200-400 ms with jitter.

    Args:
        dataset_id (UUID):
        x_embed_token (None | str | Unset): Optional embed token. Datasets in the token's scope
            are authorized even without user credentials (embed viewers).
        body (CountRequest | GroupByRequest | HistogramRequest | StatsRequest |
            ValueCountsRequest):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        CountResponse | GroupByResponse | HistogramResponse | StatsResponse | ValueCountsResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            client=client,
            body=body,
            x_embed_token=x_embed_token,
        )
    ).parsed

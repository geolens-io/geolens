from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.keyword_list_response import KeywordListResponse
from ...models.problem_detail import ProblemDetail
from ...types import Unset
from uuid import UUID


def _get_kwargs(
    record_id: UUID,
    *,
    skip: int | Unset = 0,
    limit: int | Unset = 100,
    audience_visibility: None | str | Unset = UNSET,
    audience_record_status: None | str | Unset = UNSET,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["skip"] = skip

    params["limit"] = limit

    json_audience_visibility: None | str | Unset
    if isinstance(audience_visibility, Unset):
        json_audience_visibility = UNSET
    else:
        json_audience_visibility = audience_visibility
    params["audience_visibility"] = json_audience_visibility

    json_audience_record_status: None | str | Unset
    if isinstance(audience_record_status, Unset):
        json_audience_record_status = UNSET
    else:
        json_audience_record_status = audience_record_status
    params["audience_record_status"] = json_audience_record_status

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/records/{record_id}/keywords/".format(
            record_id=quote(str(record_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> KeywordListResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = KeywordListResponse.from_dict(response.json())

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
) -> Response[KeywordListResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    record_id: UUID,
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 100,
    audience_visibility: None | str | Unset = UNSET,
    audience_record_status: None | str | Unset = UNSET,
) -> Response[KeywordListResponse | ProblemDetail]:
    """List Keywords Endpoint

     List all keywords for a record, marking analysis-inherited ones.

    Args:
        record_id (UUID):
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 100.
        audience_visibility (None | str | Unset): Compute inherited_audience_gap as if the record
            had this visibility — the counterfactual an owner asks before widening access (feat
            #1070). Keywords themselves are unaffected.
        audience_record_status (None | str | Unset): Compute inherited_audience_gap as if the
            record had this status — the counterfactual an owner asks before publishing (feat #1070).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[KeywordListResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        record_id=record_id,
        skip=skip,
        limit=limit,
        audience_visibility=audience_visibility,
        audience_record_status=audience_record_status,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    record_id: UUID,
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 100,
    audience_visibility: None | str | Unset = UNSET,
    audience_record_status: None | str | Unset = UNSET,
) -> KeywordListResponse | ProblemDetail | None:
    """List Keywords Endpoint

     List all keywords for a record, marking analysis-inherited ones.

    Args:
        record_id (UUID):
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 100.
        audience_visibility (None | str | Unset): Compute inherited_audience_gap as if the record
            had this visibility — the counterfactual an owner asks before widening access (feat
            #1070). Keywords themselves are unaffected.
        audience_record_status (None | str | Unset): Compute inherited_audience_gap as if the
            record had this status — the counterfactual an owner asks before publishing (feat #1070).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        KeywordListResponse | ProblemDetail
    """

    return sync_detailed(
        record_id=record_id,
        client=client,
        skip=skip,
        limit=limit,
        audience_visibility=audience_visibility,
        audience_record_status=audience_record_status,
    ).parsed


async def asyncio_detailed(
    record_id: UUID,
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 100,
    audience_visibility: None | str | Unset = UNSET,
    audience_record_status: None | str | Unset = UNSET,
) -> Response[KeywordListResponse | ProblemDetail]:
    """List Keywords Endpoint

     List all keywords for a record, marking analysis-inherited ones.

    Args:
        record_id (UUID):
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 100.
        audience_visibility (None | str | Unset): Compute inherited_audience_gap as if the record
            had this visibility — the counterfactual an owner asks before widening access (feat
            #1070). Keywords themselves are unaffected.
        audience_record_status (None | str | Unset): Compute inherited_audience_gap as if the
            record had this status — the counterfactual an owner asks before publishing (feat #1070).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[KeywordListResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        record_id=record_id,
        skip=skip,
        limit=limit,
        audience_visibility=audience_visibility,
        audience_record_status=audience_record_status,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    record_id: UUID,
    *,
    client: AuthenticatedClient,
    skip: int | Unset = 0,
    limit: int | Unset = 100,
    audience_visibility: None | str | Unset = UNSET,
    audience_record_status: None | str | Unset = UNSET,
) -> KeywordListResponse | ProblemDetail | None:
    """List Keywords Endpoint

     List all keywords for a record, marking analysis-inherited ones.

    Args:
        record_id (UUID):
        skip (int | Unset):  Default: 0.
        limit (int | Unset):  Default: 100.
        audience_visibility (None | str | Unset): Compute inherited_audience_gap as if the record
            had this visibility — the counterfactual an owner asks before widening access (feat
            #1070). Keywords themselves are unaffected.
        audience_record_status (None | str | Unset): Compute inherited_audience_gap as if the
            record had this status — the counterfactual an owner asks before publishing (feat #1070).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        KeywordListResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            record_id=record_id,
            client=client,
            skip=skip,
            limit=limit,
            audience_visibility=audience_visibility,
            audience_record_status=audience_record_status,
        )
    ).parsed

from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.problem_detail import ProblemDetail
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    *,
    expected_version_number: int,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["expected_version_number"] = expected_version_number

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "delete",
        "url": "/datasets/{dataset_id}/previous-version".format(
            dataset_id=quote(str(dataset_id), safe=""),
        ),
        "params": params,
    }

    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> Any | ProblemDetail | None:
    if response.status_code == 204:
        response_204 = cast(Any, None)
        return response_204

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
) -> Response[Any | ProblemDetail]:
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
    expected_version_number: int,
) -> Response[Any | ProblemDetail]:
    """Delete Previous Version

     Delete the dataset's previous version, so it can no longer be restored.

    Refuses with 404 ``no_previous_version`` when there is none, 409
    ``previous_version_changed`` when it is not ``expected_version_number``,
    and 409 ``dataset_busy`` while a refresh, replacement or restore is
    active.

    Args:
        dataset_id (UUID):
        expected_version_number (int): The previous version the caller confirmed deleting

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        expected_version_number=expected_version_number,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    expected_version_number: int,
) -> Any | ProblemDetail | None:
    """Delete Previous Version

     Delete the dataset's previous version, so it can no longer be restored.

    Refuses with 404 ``no_previous_version`` when there is none, 409
    ``previous_version_changed`` when it is not ``expected_version_number``,
    and 409 ``dataset_busy`` while a refresh, replacement or restore is
    active.

    Args:
        dataset_id (UUID):
        expected_version_number (int): The previous version the caller confirmed deleting

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        client=client,
        expected_version_number=expected_version_number,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    expected_version_number: int,
) -> Response[Any | ProblemDetail]:
    """Delete Previous Version

     Delete the dataset's previous version, so it can no longer be restored.

    Refuses with 404 ``no_previous_version`` when there is none, 409
    ``previous_version_changed`` when it is not ``expected_version_number``,
    and 409 ``dataset_busy`` while a refresh, replacement or restore is
    active.

    Args:
        dataset_id (UUID):
        expected_version_number (int): The previous version the caller confirmed deleting

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        expected_version_number=expected_version_number,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    expected_version_number: int,
) -> Any | ProblemDetail | None:
    """Delete Previous Version

     Delete the dataset's previous version, so it can no longer be restored.

    Refuses with 404 ``no_previous_version`` when there is none, 409
    ``previous_version_changed`` when it is not ``expected_version_number``,
    and 409 ``dataset_busy`` while a refresh, replacement or restore is
    active.

    Args:
        dataset_id (UUID):
        expected_version_number (int): The previous version the caller confirmed deleting

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            client=client,
            expected_version_number=expected_version_number,
        )
    ).parsed

from http import HTTPStatus
from typing import Any
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.dataset_retention_response import DatasetRetentionResponse
from ...models.dataset_retention_update import DatasetRetentionUpdate
from ...models.problem_detail import ProblemDetail
from ...types import Unset
from uuid import UUID


def _get_kwargs(
    dataset_id: UUID,
    *,
    body: DatasetRetentionUpdate,
    dry_run: bool | Unset = False,
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    params: dict[str, Any] = {}

    params["dry_run"] = dry_run

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/datasets/{dataset_id}/retention/".format(
            dataset_id=quote(str(dataset_id), safe=""),
        ),
        "params": params,
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> DatasetRetentionResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = DatasetRetentionResponse.from_dict(response.json())

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
) -> Response[DatasetRetentionResponse | ProblemDetail]:
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
    body: DatasetRetentionUpdate,
    dry_run: bool | Unset = False,
) -> Response[DatasetRetentionResponse | ProblemDetail]:
    """Set Dataset Retention

     Set or clear how many days of rows a feature dataset keeps.

    Hourly worker runs delete rows whose retention column is older than the
    cutoff, in batches, so a large backlog can take several runs; rows where
    it is null are kept. `rows_past_cutoff` counts the rows past the cutoff
    now. The instance's dataset editing switch does not apply: this is the
    owner's setting, not an edit.

    Args:
        dataset_id (UUID):
        dry_run (bool | Unset): Check the setting and count its rows without saving it. Default:
            False.
        body (DatasetRetentionUpdate): The retention setting to store; null turns retention off.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DatasetRetentionResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        body=body,
        dry_run=dry_run,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    body: DatasetRetentionUpdate,
    dry_run: bool | Unset = False,
) -> DatasetRetentionResponse | ProblemDetail | None:
    """Set Dataset Retention

     Set or clear how many days of rows a feature dataset keeps.

    Hourly worker runs delete rows whose retention column is older than the
    cutoff, in batches, so a large backlog can take several runs; rows where
    it is null are kept. `rows_past_cutoff` counts the rows past the cutoff
    now. The instance's dataset editing switch does not apply: this is the
    owner's setting, not an edit.

    Args:
        dataset_id (UUID):
        dry_run (bool | Unset): Check the setting and count its rows without saving it. Default:
            False.
        body (DatasetRetentionUpdate): The retention setting to store; null turns retention off.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DatasetRetentionResponse | ProblemDetail
    """

    return sync_detailed(
        dataset_id=dataset_id,
        client=client,
        body=body,
        dry_run=dry_run,
    ).parsed


async def asyncio_detailed(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    body: DatasetRetentionUpdate,
    dry_run: bool | Unset = False,
) -> Response[DatasetRetentionResponse | ProblemDetail]:
    """Set Dataset Retention

     Set or clear how many days of rows a feature dataset keeps.

    Hourly worker runs delete rows whose retention column is older than the
    cutoff, in batches, so a large backlog can take several runs; rows where
    it is null are kept. `rows_past_cutoff` counts the rows past the cutoff
    now. The instance's dataset editing switch does not apply: this is the
    owner's setting, not an edit.

    Args:
        dataset_id (UUID):
        dry_run (bool | Unset): Check the setting and count its rows without saving it. Default:
            False.
        body (DatasetRetentionUpdate): The retention setting to store; null turns retention off.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DatasetRetentionResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        dataset_id=dataset_id,
        body=body,
        dry_run=dry_run,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    dataset_id: UUID,
    *,
    client: AuthenticatedClient,
    body: DatasetRetentionUpdate,
    dry_run: bool | Unset = False,
) -> DatasetRetentionResponse | ProblemDetail | None:
    """Set Dataset Retention

     Set or clear how many days of rows a feature dataset keeps.

    Hourly worker runs delete rows whose retention column is older than the
    cutoff, in batches, so a large backlog can take several runs; rows where
    it is null are kept. `rows_past_cutoff` counts the rows past the cutoff
    now. The instance's dataset editing switch does not apply: this is the
    owner's setting, not an edit.

    Args:
        dataset_id (UUID):
        dry_run (bool | Unset): Check the setting and count its rows without saving it. Default:
            False.
        body (DatasetRetentionUpdate): The retention setting to store; null turns retention off.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DatasetRetentionResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            dataset_id=dataset_id,
            client=client,
            body=body,
            dry_run=dry_run,
        )
    ).parsed

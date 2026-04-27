from http import HTTPStatus
from typing import Any

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.config_import_request import ConfigImportRequest
from ...models.dry_run_configuration_config_ops_dry_run_post_mode import (
    DryRunConfigurationConfigOpsDryRunPostMode,
)
from ...models.dry_run_response import DryRunResponse
from ...models.problem_detail import ProblemDetail
from ...types import Unset


def _get_kwargs(
    *,
    body: ConfigImportRequest,
    mode: DryRunConfigurationConfigOpsDryRunPostMode | Unset = "merge",
) -> dict[str, Any]:
    headers: dict[str, Any] = {}

    params: dict[str, Any] = {}

    json_mode: str | Unset = UNSET
    if not isinstance(mode, Unset):
        json_mode = mode

    params["mode"] = json_mode

    params = {k: v for k, v in params.items() if v is not UNSET and v is not None}

    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/config-ops/dry-run/",
        "params": params,
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs


def _parse_response(
    *, client: AuthenticatedClient | Client, response: httpx.Response
) -> DryRunResponse | ProblemDetail | None:
    if response.status_code == 200:
        response_200 = DryRunResponse.from_dict(response.json())

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
) -> Response[DryRunResponse | ProblemDetail]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,
    body: ConfigImportRequest,
    mode: DryRunConfigurationConfigOpsDryRunPostMode | Unset = "merge",
) -> Response[DryRunResponse | ProblemDetail]:
    """Dry Run Configuration

     Preview what an import would change without applying any modifications.

    Args:
        mode (DryRunConfigurationConfigOpsDryRunPostMode | Unset):  Default: 'merge'.
        body (ConfigImportRequest): Payload for importing configuration.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DryRunResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        body=body,
        mode=mode,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    body: ConfigImportRequest,
    mode: DryRunConfigurationConfigOpsDryRunPostMode | Unset = "merge",
) -> DryRunResponse | ProblemDetail | None:
    """Dry Run Configuration

     Preview what an import would change without applying any modifications.

    Args:
        mode (DryRunConfigurationConfigOpsDryRunPostMode | Unset):  Default: 'merge'.
        body (ConfigImportRequest): Payload for importing configuration.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DryRunResponse | ProblemDetail
    """

    return sync_detailed(
        client=client,
        body=body,
        mode=mode,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    body: ConfigImportRequest,
    mode: DryRunConfigurationConfigOpsDryRunPostMode | Unset = "merge",
) -> Response[DryRunResponse | ProblemDetail]:
    """Dry Run Configuration

     Preview what an import would change without applying any modifications.

    Args:
        mode (DryRunConfigurationConfigOpsDryRunPostMode | Unset):  Default: 'merge'.
        body (ConfigImportRequest): Payload for importing configuration.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DryRunResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        body=body,
        mode=mode,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    body: ConfigImportRequest,
    mode: DryRunConfigurationConfigOpsDryRunPostMode | Unset = "merge",
) -> DryRunResponse | ProblemDetail | None:
    """Dry Run Configuration

     Preview what an import would change without applying any modifications.

    Args:
        mode (DryRunConfigurationConfigOpsDryRunPostMode | Unset):  Default: 'merge'.
        body (ConfigImportRequest): Payload for importing configuration.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DryRunResponse | ProblemDetail
    """

    return (
        await asyncio_detailed(
            client=client,
            body=body,
            mode=mode,
        )
    ).parsed

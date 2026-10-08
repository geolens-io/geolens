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
    all_tenants: bool | Unset = False,
) -> dict[str, Any]:

    params: dict[str, Any] = {}

    params["force"] = force

    params["all_tenants"] = all_tenants

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
    all_tenants: bool | Unset = False,
) -> Response[BackfillResponse | ProblemDetail]:
    """Trigger Backfill

     Queue semantic-search embedding generation for records (admin only).

    Pass ?force=true to regenerate every record and replace its stored vectors.
    Without it, the run embeds only records that lack a current-model embedding.

    The run covers the calling tenant's records. In a multi-tenant deployment
    the embedding model and width are shared by every tenant, so a change
    leaves each tenant to regenerate. Pass ?all_tenants=true, which needs the
    manage_tenants permission there, to also queue a run for every other
    tenant that has records; ``other_tenants`` reports each one. When the
    calling tenant's own run is refused, no other tenant is queued. A
    single-tenant deployment ignores the flag.

    The run happens on the job queue because a full regeneration can exceed
    request timeouts. This endpoint returns the job id; poll
    ``GET /jobs/{job_id}`` for the outcome.

    Args:
        force (bool | Unset):  Default: False.
        all_tenants (bool | Unset):  Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[BackfillResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        force=force,
        all_tenants=all_tenants,
    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)


def sync(
    *,
    client: AuthenticatedClient,
    force: bool | Unset = False,
    all_tenants: bool | Unset = False,
) -> BackfillResponse | ProblemDetail | None:
    """Trigger Backfill

     Queue semantic-search embedding generation for records (admin only).

    Pass ?force=true to regenerate every record and replace its stored vectors.
    Without it, the run embeds only records that lack a current-model embedding.

    The run covers the calling tenant's records. In a multi-tenant deployment
    the embedding model and width are shared by every tenant, so a change
    leaves each tenant to regenerate. Pass ?all_tenants=true, which needs the
    manage_tenants permission there, to also queue a run for every other
    tenant that has records; ``other_tenants`` reports each one. When the
    calling tenant's own run is refused, no other tenant is queued. A
    single-tenant deployment ignores the flag.

    The run happens on the job queue because a full regeneration can exceed
    request timeouts. This endpoint returns the job id; poll
    ``GET /jobs/{job_id}`` for the outcome.

    Args:
        force (bool | Unset):  Default: False.
        all_tenants (bool | Unset):  Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        BackfillResponse | ProblemDetail
    """

    return sync_detailed(
        client=client,
        force=force,
        all_tenants=all_tenants,
    ).parsed


async def asyncio_detailed(
    *,
    client: AuthenticatedClient,
    force: bool | Unset = False,
    all_tenants: bool | Unset = False,
) -> Response[BackfillResponse | ProblemDetail]:
    """Trigger Backfill

     Queue semantic-search embedding generation for records (admin only).

    Pass ?force=true to regenerate every record and replace its stored vectors.
    Without it, the run embeds only records that lack a current-model embedding.

    The run covers the calling tenant's records. In a multi-tenant deployment
    the embedding model and width are shared by every tenant, so a change
    leaves each tenant to regenerate. Pass ?all_tenants=true, which needs the
    manage_tenants permission there, to also queue a run for every other
    tenant that has records; ``other_tenants`` reports each one. When the
    calling tenant's own run is refused, no other tenant is queued. A
    single-tenant deployment ignores the flag.

    The run happens on the job queue because a full regeneration can exceed
    request timeouts. This endpoint returns the job id; poll
    ``GET /jobs/{job_id}`` for the outcome.

    Args:
        force (bool | Unset):  Default: False.
        all_tenants (bool | Unset):  Default: False.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[BackfillResponse | ProblemDetail]
    """

    kwargs = _get_kwargs(
        force=force,
        all_tenants=all_tenants,
    )

    response = await client.get_async_httpx_client().request(**kwargs)

    return _build_response(client=client, response=response)


async def asyncio(
    *,
    client: AuthenticatedClient,
    force: bool | Unset = False,
    all_tenants: bool | Unset = False,
) -> BackfillResponse | ProblemDetail | None:
    """Trigger Backfill

     Queue semantic-search embedding generation for records (admin only).

    Pass ?force=true to regenerate every record and replace its stored vectors.
    Without it, the run embeds only records that lack a current-model embedding.

    The run covers the calling tenant's records. In a multi-tenant deployment
    the embedding model and width are shared by every tenant, so a change
    leaves each tenant to regenerate. Pass ?all_tenants=true, which needs the
    manage_tenants permission there, to also queue a run for every other
    tenant that has records; ``other_tenants`` reports each one. When the
    calling tenant's own run is refused, no other tenant is queued. A
    single-tenant deployment ignores the flag.

    The run happens on the job queue because a full regeneration can exceed
    request timeouts. This endpoint returns the job id; poll
    ``GET /jobs/{job_id}`` for the outcome.

    Args:
        force (bool | Unset):  Default: False.
        all_tenants (bool | Unset):  Default: False.

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
            all_tenants=all_tenants,
        )
    ).parsed

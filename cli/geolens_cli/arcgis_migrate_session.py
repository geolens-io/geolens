# SPDX-License-Identifier: Apache-2.0
"""What `geolens arcgis migrate` hands to each action handler.

Hand-maintained. The GeoLens session, the run's ArcGIS token, the inventory
rows and the errors a handler raises. Handlers live in their own modules and
import this one, so the orchestration in ``arcgis_migrate`` can import them.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._sdk_helpers import call_sdk_with_reauth, detail_text
from .arcgis_migrate_state import DONE
from .arcgis_portal import (
    PortalClient,
    Redactor,
    _retry_after,
    holds_secret,
)

RATE_LIMIT_ATTEMPTS = 3
RATE_LIMIT_WAIT = 5.0
# A renewable token is replaced this long before it expires, so a preview
# never starts with a token about to lapse.
TOKEN_RENEW_MARGIN = 120.0


class GeoLensError(Exception):
    """A GeoLens request answered with an error status.

    ``detail`` is the problem body's ``detail``: text, or the object a coded
    refusal carries.
    """

    def __init__(self, message: str, status: int, detail: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.detail = detail


class ItemFailed(Exception):
    """An item could not be migrated; the message goes to the state file."""


class CredentialRefused(ItemFailed):
    """A GeoLens request would have carried a token or password the run was
    given; it wasn't sent. Fails the item in scope, or stops the run."""


class WriteRaced(ItemFailed):
    """GeoLens refused a write because its object changed after it was read."""


class StopRun(Exception):
    """The run can't continue (for example, the ArcGIS token can no longer be
    renewed); the item fails with this message and later items wait for a
    rerun."""


@dataclass
class ItemResult:
    """How an item ended, and notes for the report.

    A handler records the ids it creates on the item's ``ItemState`` as it
    goes, so a failure part way keeps them.
    """

    status: str = DONE
    notes: list[str] = field(default_factory=list)


class GeoLens:
    """The operator's SDK session.

    A 401 spends a stored refresh token once, and a 429 is retried after the
    server's ``Retry-After``. Every access token the session holds, the first
    and each refreshed one, is given to *redact*.
    """

    def __init__(
        self,
        sdk: Any,
        instance: str,
        redact: Redactor,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._sdk = sdk
        self._instance = instance
        self._redact = redact
        self._sleep = sleep
        self.client = sdk.client
        redact.add(getattr(sdk.client, "token", None))

    def write(self, fn: Callable[..., Any], *, during: str, **kwargs: Any) -> Any:
        """``call`` for a write whose body names the ``expected_updated_at`` it
        read; GeoLens refusing it as stale raises ``WriteRaced``, which says
        the object changed *during* the write."""
        try:
            return self.call(fn, **kwargs)
        except GeoLensError as exc:
            detail = exc.detail
            if (
                exc.status == 409
                and isinstance(detail, Mapping)
                and detail.get("code") == "stale_write"
            ):
                raise WriteRaced(
                    f"changed in GeoLens while {during}; it was left as it is"
                ) from None
            raise

    def call(
        self,
        fn: Callable[..., Any],
        *,
        expected: int = 200,
        sends: tuple[str, ...] = (),
        **kwargs: Any,
    ) -> Any:
        """Send one request. ``CredentialRefused`` before sending when a
        parameter or body field holds a secret the redactor knows, except the
        fields *sends* names, which carry one by design (a new user's
        password); see ``outgoing_secret`` for what else is exempt."""
        from geolens.models.problem_detail import ProblemDetail  # lazy

        refused = outgoing_secret(fn, kwargs, self._redact, sends)
        if refused is not None:
            raise CredentialRefused(
                f"the request to {refused[0]} holds this run's ArcGIS credential "
                f"in {refused[1]}, so it wasn't sent"
            )
        restore: list[tuple[Any, Any]] = []

        def replace_client(replacement: Any) -> None:
            # The retry keeps the timeout the caller set for this call (for
            # example long_request_timeout's), then goes back to its own.
            self._redact.add(getattr(replacement, "token", None))
            http = replacement.get_httpx_client()
            restore.append((http, http.timeout))
            http.timeout = self.client.get_httpx_client().timeout
            self.client = replacement

        try:
            for attempt in range(1, RATE_LIMIT_ATTEMPTS + 1):
                resp = call_sdk_with_reauth(
                    fn,
                    instance=self._instance,
                    credential_kind=self._sdk.credential_kind,
                    credential_provenance=self._sdk.credential_provenance,
                    on_reauthenticated=replace_client,
                    client=self.client,
                    **kwargs,
                )
                status = int(resp.status_code)
                if status != 429 or attempt == RATE_LIMIT_ATTEMPTS:
                    break
                wait = _retry_after(resp.headers)
                self._sleep(RATE_LIMIT_WAIT if wait is None else wait)
        finally:
            for http, timeout in restore:
                http.timeout = timeout
        if status == expected and not isinstance(resp.parsed, ProblemDetail):
            return resp.parsed
        detail: Any = None
        text = "no detail"
        if isinstance(resp.parsed, ProblemDetail):
            raw = resp.parsed.detail
            detail = raw.to_dict() if hasattr(raw, "to_dict") else raw
            text = detail_text(raw)
        raise GeoLensError(f"HTTP {status}: {text}", status, detail)


class PortalAuth:
    """The run's ArcGIS token, presented to GeoLens as a bearer credential.

    A token minted from a password or an OAuth sign-in is renewed shortly
    before it expires, and once after GeoLens reports it rejected; a pasted
    token can't be renewed. The portal client keeps the password or refresh
    token in memory and stops renewing after one failed sign-in, since ArcGIS
    locks an account after five.
    """

    def __init__(
        self,
        client: PortalClient,
        *,
        renewable: bool,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._clock = clock
        self._minted_at = clock() if renewable else None

    @property
    def client(self) -> PortalClient:
        return self._client

    def service_auth(self) -> Any:
        from geolens.models.service_auth_request import ServiceAuthRequest

        if self._minted_at is not None:
            age = self._clock() - self._minted_at
            lifetime = self._client.token_lifetime
            # A lifetime under twice the margin would renew on every call.
            if age > lifetime - min(TOKEN_RENEW_MARGIN, lifetime / 2):
                self.renew()
        return ServiceAuthRequest(method="bearer", token=self._client.token)

    def renew(self) -> bool:
        """Mint a replacement token; False when that isn't possible."""
        if self._minted_at is None or not self._client.renew_token():
            return False
        self._minted_at = self._clock()
        return True


@dataclass
class MigrationContext:
    geolens: GeoLens
    inventory: Mapping[str, Mapping[str, Any]]
    portal: PortalAuth | None
    save: Callable[[], None]
    # The inventory's portal record (url, kind, org_id), which decides which
    # service hosts are the organization's own.
    portal_info: Mapping[str, Any] | None = None
    trusted_hosts: frozenset[str] = frozenset()
    # The plan's defaults.collection_from, and the state's collection ids,
    # which the collections step fills in place.
    collection_from: str = "folder"
    collections: dict[str, str] = field(default_factory=dict)
    collections_denied: bool = False
    # The export bundle: its folder, byte cap per item, and the web origins
    # story links point at.
    export_dir: Path | None = None
    # Every item's state, for the map a story's web map became.
    items: dict[str, Any] = field(default_factory=dict)
    export_cap: int = 0
    # The instance URL without /api, and the web app's own URL when the
    # instance configures one, read once the first time a story needs it.
    web_origin: str = ""
    web_app: str | None = None
    # Esri basemap URL -> GeoLens basemap id, from the plan.
    basemap_map: dict[str, str] = field(default_factory=dict)
    # A skipped hosted view's item id -> the parent item whose datasets stand
    # in for it, from the plan's alias_of.
    aliases: dict[str, str] = field(default_factory=dict)
    portal_root: str = ""
    redact: Callable[[str], str] = str
    # The GeoLens operator's user id, whose writes a rerun recognises as its own.
    operator_id: str | None = None
    # An editor migrating their own content: items stay with the operator.
    own_content: bool = False
    # The plan's items that import layers or a file, also those a partial
    # inventory leaves unlisted, which a web map's layer waits on until the
    # run has finished them.
    importable: frozenset[str] = frozenset()
    # The instance's upload_max_size_mb in bytes, read once from its settings.
    upload_limit: int | None = None
    # How the plan's sharing becomes GeoLens sharing (arcgis_migrate_groups.Sharing).
    sharing: Any = None
    # The GeoLens version, read once when a style default is recorded.
    server_version: str | None = None
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic


def outgoing_secret(
    fn: Callable[..., Any],
    kwargs: Mapping[str, Any],
    redact: Any,
    sends: tuple[str, ...] = (),
) -> tuple[str, str] | None:
    """(request path, parameter or body key) of the first value in an SDK
    call's arguments that holds a registered secret; None when none does.

    Every argument but the client is read: path and query parameters, body
    fields at any depth (keys included), and an upload's file name, never its
    bytes. Exempt are the client's own authentication, which travels in a
    header, and a body's ``auth`` member when it is the service credential
    an import, preview, commit or refresh of a non-public service carries.
    """
    for name, value in kwargs.items():
        if name == "client":
            continue
        for key, text in _texts(name, value):
            if key not in sends and holds_secret(text, redact):
                return _request_path(fn, kwargs), key
    return None


def _texts(name: str, value: Any) -> Iterator[tuple[str, str]]:
    if isinstance(value, Path):
        yield name, value.name
        return
    if hasattr(value, "to_dict"):
        from geolens.models.service_auth_request import ServiceAuthRequest

        data = value.to_dict()
        if isinstance(getattr(value, "auth", None), ServiceAuthRequest):
            data.pop("auth", None)
        value = data
    stack: list[tuple[str, Any]] = [(name, value)]
    while stack:
        key, node = stack.pop()
        if isinstance(node, str):
            yield key, node
        elif isinstance(node, Mapping):
            for k, v in node.items():
                yield key, str(k)
                stack.append((f"{key}.{k}", v))
        elif isinstance(node, list | tuple):
            stack.extend((f"{key}[{i}]", v) for i, v in enumerate(node))


def _request_path(fn: Callable[..., Any], kwargs: Mapping[str, Any]) -> str:
    """The request's path as the SDK builds it, or the function's name."""
    build = getattr(sys.modules.get(fn.__module__), "_get_kwargs", None)
    try:
        args = {k: v for k, v in kwargs.items() if k != "client"}
        return str(build(**args)["url"])  # type: ignore[misc]
    except Exception:  # broad: only names the refused request, never sends it
        return f"{fn.__module__.rsplit('.', 1)[-1]}.{fn.__name__}"


def refuse_credentials(ctx: MigrationContext, fields: Mapping[str, Any]) -> None:
    """``ItemFailed`` naming each field, never its value, whose value (text, a
    list or a JSON document) contains a token or password the run was given.
    Callers pass each value as the portal holds it and as it is sent."""
    held = [name for name, value in fields.items() if holds_secret(value, ctx.redact)]
    if held:
        shown = ", ".join(dict.fromkeys(name.replace("_", " ") for name in held))
        raise ItemFailed(
            f"the item's {shown} holds this run's ArcGIS credential, so it isn't "
            "written"
        )


def operator_or_nobody_wrote_last(ctx: MigrationContext, dataset: Any) -> bool:
    """Whether *dataset*'s last writer is this run's operator or nobody.
    GeoLens stamps the writer of every feature, column and metadata write, and
    a fresh vector import leaves no writer."""
    from .refresh import _value

    by = _value(getattr(dataset, "updated_by", None))
    return by is None or str(by) == ctx.operator_id


def changed_before_handover(dataset_id: str) -> ItemFailed:
    return ItemFailed(
        f"dataset {dataset_id} changed in GeoLens before its owner was handed "
        "over; it was left as it is"
    )

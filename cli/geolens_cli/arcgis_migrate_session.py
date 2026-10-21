# SPDX-License-Identifier: Apache-2.0
"""What `geolens arcgis migrate` hands to each action handler.

Hand-maintained. The GeoLens session, the run's ArcGIS token, the inventory
rows and the errors a handler raises. Handlers live in their own modules and
import this one, so the orchestration in ``arcgis_migrate`` can import them.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ._sdk_helpers import call_sdk_with_reauth, detail_text
from .arcgis_migrate_state import DONE
from .arcgis_portal import (
    TOKEN_EXPIRATION_MINUTES,
    PortalClient,
    Redactor,
    _retry_after,
)

RATE_LIMIT_ATTEMPTS = 3
RATE_LIMIT_WAIT = 5.0
# A token minted from a password is replaced this long before it expires, so
# a preview never starts with a token about to lapse.
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

    def call(
        self, fn: Callable[..., Any], *, expected: int = 200, **kwargs: Any
    ) -> Any:
        from geolens.models.problem_detail import ProblemDetail  # lazy

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

    A token minted from a password is renewed shortly before it expires, and
    once after GeoLens reports it rejected; a pasted token can't be renewed.
    The portal client keeps the password in memory and stops renewing after
    one failed sign-in, since ArcGIS locks an account after five.
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

    def service_auth(self) -> Any:
        from geolens.models.service_auth_request import ServiceAuthRequest

        if self._minted_at is not None:
            age = self._clock() - self._minted_at
            if age > TOKEN_EXPIRATION_MINUTES * 60 - TOKEN_RENEW_MARGIN:
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
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic

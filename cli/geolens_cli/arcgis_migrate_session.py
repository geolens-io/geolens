# SPDX-License-Identifier: Apache-2.0
"""What `geolens arcgis migrate` hands to each action handler.

Hand-maintained. The GeoLens session, the run context and the errors a
handler raises. Handlers live in their own modules and import this one, so
the orchestration in ``arcgis_migrate`` can import them.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ._sdk_helpers import call_sdk_with_reauth, detail_text
from .arcgis_migrate_state import DONE
from .arcgis_portal import Redactor


class GeoLensError(Exception):
    """A GeoLens request answered with an error status."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


class ItemFailed(Exception):
    """An item could not be migrated; the message goes to the state file."""


@dataclass
class ItemResult:
    """How an item ended.

    A handler records the ids it creates on the item's ``ItemState`` as it
    goes, and calls ``MigrationContext.save`` after each one, so a failure or
    a crash part way keeps them and a rerun doesn't create them again.
    """

    status: str = DONE


class GeoLens:
    """The operator's SDK session; a 401 spends a stored refresh token once.

    Every access token the session holds, the first and each refreshed one,
    is given to *redact*.
    """

    def __init__(self, sdk: Any, instance: str, redact: Redactor) -> None:
        self._sdk = sdk
        self._instance = instance
        self._redact = redact
        self.client = sdk.client
        redact.add(getattr(sdk.client, "token", None))

    def call(
        self, fn: Callable[..., Any], *, expected: int = 200, **kwargs: Any
    ) -> Any:
        from geolens.models.problem_detail import ProblemDetail  # lazy

        def replace_client(replacement: Any) -> None:
            self._redact.add(getattr(replacement, "token", None))
            self.client = replacement

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
        if status != expected or isinstance(resp.parsed, ProblemDetail):
            detail = (
                detail_text(resp.parsed.detail)
                if isinstance(resp.parsed, ProblemDetail)
                else "no detail"
            )
            raise GeoLensError(f"HTTP {status}: {detail}", status)
        return resp.parsed


@dataclass
class MigrationContext:
    geolens: GeoLens
    save: Callable[[], None]

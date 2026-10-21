"""The API key a request authenticated with, recorded on its database session.

A request's dependencies and handler share one session, so the record made
while resolving the caller is visible to the guards and audit events of the
same request, and to nothing else. Also the routes each dataset-bound key
scope may call, and whether a request's header key was looked up, which the
CORS layer reads.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

_SESSION_KEY = "geolens.api_key_credential"
_HEADER_KEY_EVALUATED = "geolens.header_api_key_evaluated"


def mark_header_api_key_evaluated(scope: MutableMapping[str, Any]) -> None:
    """Record that the auth layer looked up this request's X-Api-Key header."""
    scope.setdefault("state", {})[_HEADER_KEY_EVALUATED] = True


def header_api_key_evaluated(scope: Mapping[str, Any]) -> bool:
    """Whether the auth layer looked up this request's X-Api-Key, valid or not."""
    return bool(scope.get("state", {}).get(_HEADER_KEY_EVALUATED))


# The only routes a dataset_write key authenticates, as exact (METHOD, route
# template) pairs: reading and writing features of the dataset each template
# names in its ``dataset_id`` path parameter. Templates are FastAPI route
# templates, including the generated no-slash aliases.
DATASET_WRITE_KEY_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/datasets/{dataset_id}/features/"),
        ("GET", "/datasets/{dataset_id}/features"),
        ("POST", "/datasets/{dataset_id}/features/"),
        ("POST", "/datasets/{dataset_id}/features"),
        ("POST", "/datasets/{dataset_id}/features/dry-run/"),
        ("POST", "/datasets/{dataset_id}/features/dry-run"),
        ("GET", "/datasets/{dataset_id}/features/{gid}"),
        ("PUT", "/datasets/{dataset_id}/features/{gid}"),
        ("PATCH", "/datasets/{dataset_id}/features/{gid}"),
        ("DELETE", "/datasets/{dataset_id}/features/{gid}"),
        ("POST", "/datasets/{dataset_id}/features/delete/"),
        ("POST", "/datasets/{dataset_id}/features/delete"),
        ("GET", "/datasets/{dataset_id}/features.geojson"),
        ("GET", "/collections/{dataset_id}/items"),
        ("GET", "/collections/{dataset_id}/items/"),
        ("GET", "/collections/{dataset_id}/items/{feature_id}"),
    }
)

# A dataset_append key only creates features, one or a FeatureCollection at a
# time, so a leaked one can neither read the dataset back nor change it.
DATASET_APPEND_KEY_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/datasets/{dataset_id}/features/"),
        ("POST", "/datasets/{dataset_id}/features"),
    }
)

# The routes each dataset key scope authenticates; any other request treats
# the key as invalid.
DATASET_KEY_SCOPE_ROUTES: dict[str, frozenset[tuple[str, str]]] = {
    "dataset_write": DATASET_WRITE_KEY_ROUTES,
    "dataset_append": DATASET_APPEND_KEY_ROUTES,
}

# Scopes whose keys are bound to the one dataset in ``api_keys.dataset_id``.
DATASET_KEY_SCOPES: frozenset[str] = frozenset(DATASET_KEY_SCOPE_ROUTES)


@dataclass(frozen=True, slots=True)
class ApiKeyCredential:
    id: uuid.UUID
    scope: str
    dataset_id: uuid.UUID | None
    expires_at: datetime | None = None


def record_api_key(session: AsyncSession, credential: ApiKeyCredential) -> None:
    session.info[_SESSION_KEY] = credential


def api_key_credential(session: AsyncSession) -> ApiKeyCredential | None:
    """The key that authenticated this session's request, or None."""
    credential = session.info.get(_SESSION_KEY)
    return credential if isinstance(credential, ApiKeyCredential) else None


def api_key_audit_details(session: AsyncSession) -> dict[str, str]:
    """Audit details naming the key that authenticated the request, if any."""
    credential = api_key_credential(session)
    return {"api_key_id": str(credential.id)} if credential is not None else {}

"""The API key a request authenticated with, recorded on its database session.

A request's dependencies and handler share one session, so the record made
while resolving the caller is visible to the guards and audit events of the
same request, and to nothing else.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

_SESSION_KEY = "geolens.api_key_credential"

# Scopes whose keys are bound to the one dataset in ``api_keys.dataset_id``.
DATASET_KEY_SCOPES: frozenset[str] = frozenset({"dataset_write", "dataset_append"})


@dataclass(frozen=True, slots=True)
class ApiKeyCredential:
    id: uuid.UUID
    scope: str
    dataset_id: uuid.UUID | None


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

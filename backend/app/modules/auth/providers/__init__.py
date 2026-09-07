"""Auth provider abstraction layer.

All auth providers (local, OIDC) implement the AuthProvider protocol.
Downstream code only sees AuthenticatedIdentity -- it never knows
how the user was verified.
"""

import uuid
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class AuthenticatedIdentity:
    """Universal output of any auth provider, replacing provider-specific data."""

    user_id: uuid.UUID
    username: str
    email: str | None = None


class AuthenticationError(Exception):
    def __init__(self, detail: str = "Authentication failed") -> None:
        self.detail = detail
        super().__init__(detail)


@runtime_checkable
class AuthProvider(Protocol):
    """Protocol all auth providers implement.

    Local uses username/password, OIDC uses token exchange; ``**kwargs``
    lets each accept its own parameters through one interface.
    """

    async def authenticate(self, **kwargs: object) -> AuthenticatedIdentity: ...

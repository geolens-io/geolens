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
    """Represents a successfully authenticated user.

    This is the universal output of any auth provider. The rest of the
    system uses this instead of provider-specific data structures.
    """

    user_id: uuid.UUID
    username: str
    email: str | None = None


class AuthenticationError(Exception):
    """Raised when authentication fails for any reason."""

    def __init__(self, detail: str = "Authentication failed") -> None:
        self.detail = detail
        super().__init__(detail)


@runtime_checkable
class AuthProvider(Protocol):
    """Protocol that all auth providers must implement.

    Local auth uses username/password; OIDC will use token exchange.
    The **kwargs signature allows each provider to accept its own
    parameters while conforming to a single interface.
    """

    async def authenticate(self, **kwargs: object) -> AuthenticatedIdentity: ...

"""Local (username + password) authentication provider."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pwdlib.hashers.bcrypt import BcryptHasher

from app.modules.auth.models import User
from app.modules.auth.providers import AuthenticatedIdentity, AuthenticationError

# ---------------------------------------------------------------------------
# Password hashing setup
# ---------------------------------------------------------------------------

password_hash = PasswordHash((BcryptHasher(),))

# Pre-computed dummy hash used in timing-attack prevention: when a username
# is not found we still run the bcrypt verify so that the response time is
# indistinguishable from a real password check.
DUMMY_HASH = password_hash.hash("timing-attack-prevention-dummy")


def hash_password(password: str) -> str:
    """Hash a plaintext password for storage."""
    return password_hash.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a stored hash."""
    return password_hash.verify(plain, hashed)


# ---------------------------------------------------------------------------
# Local auth provider
# ---------------------------------------------------------------------------


class LocalAuthProvider:
    """Authenticates users via username and bcrypt-hashed password.

    Implements the AuthProvider protocol.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def authenticate(
        self, *, username: str, password: str
    ) -> AuthenticatedIdentity:
        """Validate credentials and return an AuthenticatedIdentity.

        Raises AuthenticationError on any failure (wrong user, wrong password,
        or deactivated account).
        """
        result = await self.db.execute(
            select(User).where(func.lower(User.username) == func.lower(username))
        )
        user = result.scalar_one_or_none()

        if user is None:
            # Timing-attack prevention: still verify against a dummy hash
            password_hash.verify(password, DUMMY_HASH)
            raise AuthenticationError("Invalid credentials")

        if user.password_hash is None:
            # fix(#1230 codex r10): OAuth-only users have no local password
            # hash (oauth/service.py never sets one) -- `user.password_hash
            # or ""` used to hand pwdlib an empty string, which it cannot
            # parse as any known hash format. That raised UnknownHashError
            # uncaught here, 500ing the login request and skipping the
            # user.login.failure audit emit entirely (the except clause in
            # the router only catches AuthenticationError). Still run a
            # real verify against the dummy hash for timing-attack parity
            # with the "user not found" branch above, then always fail --
            # there is no real password for this account to match.
            password_hash.verify(password, DUMMY_HASH)
            raise AuthenticationError("Invalid credentials")

        try:
            valid = verify_password(password, user.password_hash)
        except UnknownHashError:
            # Defense in depth: any other unparseable/corrupted stored hash
            # is a login failure, not a 500.
            valid = False
        if not valid:
            raise AuthenticationError("Invalid credentials")

        return AuthenticatedIdentity(
            user_id=user.id,
            username=user.username,
            email=user.email,
        )

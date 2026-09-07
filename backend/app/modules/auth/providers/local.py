"""Local (username + password) authentication provider."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pwdlib.hashers.bcrypt import BcryptHasher

from app.modules.auth.models import User
from app.modules.auth.password_policy import BCRYPT_MAX_PASSWORD_BYTES
from app.modules.auth.providers import AuthenticatedIdentity, AuthenticationError

password_hash = PasswordHash((BcryptHasher(),))

# Pre-computed dummy hash used in timing-attack prevention: when a username
# is not found we still run the bcrypt verify so that the response time is
# indistinguishable from a real password check.
DUMMY_HASH = password_hash.hash("timing-attack-prevention-dummy")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a stored hash.

    fix(#1778): an input longer than bcrypt's 72-byte limit is a NON-MATCH,
    not an exception — pwdlib's BcryptHasher raises ValueError rather than
    truncating, and unvalidated callers (POST /auth/login, whose form schema
    has no length cap) turned that into an uncaught 500 that also skipped
    the user.login.failure audit row.

    Refusing rather than truncating is correct: signup, password reset and
    change-password all run validate_password_complexity, capping the stored
    credential at
    BCRYPT_MAX_PASSWORD_BYTES, so no correct password can be rejected here,
    and truncating would instead accept the first 72 bytes of a longer
    string as the whole password.
    """
    if len(plain.encode("utf-8")) > BCRYPT_MAX_PASSWORD_BYTES:
        return False
    return password_hash.verify(plain, hashed)


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
        # fix(#1715): a locking read, not a bare SELECT. An admin
        # reset holds FOR UPDATE on this row while writing the new hash and
        # revoking credentials; without a lock here, a login reading the row
        # before that commit could verify the STALE hash and then mint
        # tokens carrying the POST-reset token_version and revocation
        # horizon, surviving
        # the revocation. Blocking here means the verify runs against
        # whatever the reset committed, so the old password fails.
        #
        # FOR NO KEY UPDATE, not FOR SHARE: the login handler's
        # last_login_at UPDATE needs it — under FOR SHARE, two concurrent
        # logins would each try to upgrade and deadlock (Postgres aborts
        # one, fix(#1715)). Taking the write-compatible mode up
        # front serializes them instead, without blocking FOR KEY SHARE
        # (this request's own refresh_tokens insert), and still conflicts
        # with the reset's FOR UPDATE, which is what it must serialize
        # against.
        #
        # Lock is held to the end of the request transaction (the router
        # commits after minting tokens). Lock ordering is unchanged and
        # acyclic: the reset takes the admin-lifecycle advisory lock then
        # this row; login and change_password take only this row.
        result = await self.db.execute(
            select(User)
            .where(func.lower(User.username) == func.lower(username))
            .with_for_update(key_share=True)
        )
        user = result.scalar_one_or_none()

        if user is None:
            # Timing-attack prevention: still verify against a dummy hash
            verify_password(password, DUMMY_HASH)
            raise AuthenticationError("Invalid credentials")

        if user.password_hash is None:
            # fix(#1230): OAuth-only users have no local password
            # hash; `user.password_hash or ""` used to hand pwdlib an empty
            # string, raising uncaught UnknownHashError (500, and skipping
            # the login.failure audit). Still verify against the dummy hash
            # for timing-attack parity, then always fail.
            verify_password(password, DUMMY_HASH)
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

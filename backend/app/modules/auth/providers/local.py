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
        # fix(#1715 codex r4 P1): a locking read, not a bare SELECT. An admin reset
        # (POST /admin/users/{id}/reset-password/) holds FOR UPDATE on this row
        # while it writes the new hash and revokes the account's credentials.
        # Without a lock here, a login that read the row before that commit
        # would verify the STALE hash and then mint tokens from the post-reset
        # row: an access JWT carrying the new token_version, and a refresh row
        # created after sessions_revoked_at, so both survive the revocation.
        # The old-password holder would come out of the recovery with a live
        # session. Blocking here means the verify below runs against whatever
        # the reset committed, so the old password fails and nothing is minted.
        #
        # FOR NO KEY UPDATE, not FOR SHARE. The login handler assigns
        # user.last_login_at, and that UPDATE needs FOR NO KEY UPDATE: under a
        # shared lock two concurrent logins to one account would each hold FOR
        # SHARE and then each try to upgrade, which is a deadlock Postgres
        # resolves by aborting one otherwise-valid login (fix(#1715 codex r5)).
        # Taking the write-compatible mode up front makes those two serialize
        # for the few milliseconds of verify-plus-mint instead. It still does
        # not conflict with FOR KEY SHARE, so foreign-key checks from other
        # tables -- including this request's own refresh_tokens insert -- are
        # not blocked, and it still conflicts with the reset's FOR UPDATE,
        # which is the writer this has to serialize against.
        #
        # The lock is held to the end of the request transaction, which is what
        # keeps it covering the mint: the router commits after create_access_
        # token and create_refresh_token, and nothing between here and there
        # leaves the database. Lock ordering is unchanged and acyclic -- the
        # reset takes the admin-lifecycle advisory lock and then this row, the
        # login and change_password take only this row.
        result = await self.db.execute(
            select(User)
            .where(func.lower(User.username) == func.lower(username))
            .with_for_update(key_share=True)
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

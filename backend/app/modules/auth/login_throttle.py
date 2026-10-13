"""Per-account throttle for password sign-in, with remembered browsers.

Each account accepts at most ``LOGIN_FAILURE_LIMIT`` failed sign-ins per
``LOGIN_FAILURE_WINDOW`` from clients it does not know. A browser that signed
in to the account before carries a device cookie and spends a budget of its
own, so guessing from elsewhere cannot lock the owner out of that browser. A
remembered browser that spends its own budget is treated as unknown.

An attempt is reserved before the password check, in one short transaction
under an advisory lock on its budget, so parallel requests cannot all read
the count before any of them is recorded. A wrong password marks its
reservation failed, in the transaction that commits before the 401 is sent,
and a correct one removes it. A reservation never settled, because the
request failed or was cancelled first, counts for ``_UNSETTLED_GRACE``: its
caller never saw an outcome. A refused attempt never reaches the password
check or writes a row, whether or not the account exists.

Every key is a keyed digest over the tenant and the lowercased username, so
nothing here stores a username, and the device cookie is an HMAC token, never
a JWT, so it cannot pass as a bearer credential.
"""

import hashlib
import hmac
import math
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import HTTPException, Request, Response, status
from sqlalchemy import (
    ColumnElement,
    and_,
    delete,
    exists,
    func,
    not_,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db.tenant_session import current_tenant_var
from app.core.dependencies import get_client_ip
from app.modules.auth.cookies import (
    wants_cookie_auth,
    clear_login_device_cookie,
    cookie_values,
    cookies_with_prefix,
    set_login_device_cookie,
)
from app.modules.auth.models import LoginAttempt, LoginTrustToken, User
from app.platform.audit import AuditEvent, audit_emit

LOGIN_FAILURE_LIMIT = 10
LOGIN_FAILURE_WINDOW = timedelta(hours=1)
DEVICE_COOKIE_MAX_AGE = timedelta(days=180)
TRUST_TOKEN_TTL = timedelta(minutes=10)
# Far longer than a password check takes, so in-flight attempts still count.
_UNSETTLED_GRACE = timedelta(minutes=5)

LOGIN_THROTTLED_CODE = "login_throttled"
LOGIN_THROTTLED_MESSAGE = (
    "Too many failed sign-ins for this account. Use a browser you've signed "
    "in with before, or sign in with SSO."
)

_DEVICE_COOKIE_PREFIX = "geolens_device_"
_DEVICE_COOKIE_VERSION = "v1"
_MAX_REMEMBERED_ACCOUNTS = 5
_SWEEP_BATCH = 100
_NONCE_BYTES = 32
# Tolerates a clock step between workers; a cookie dated further ahead is forged.
_ISSUED_AT_SKEW_SECONDS = 300
_TRUST_TOKEN_MAX_LENGTH = 128
# The audit row stores the username as the failure row does, at the column width.
_AUDIT_USERNAME_MAX = 150
_KDF_SALT = b"geolens-login-throttle"


def _derived_key(info: bytes) -> bytes:
    """A purpose-bound key from the JWT secret, sharing nothing with its other uses."""
    kdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=_KDF_SALT, info=info)
    return kdf.derive(settings.jwt_secret_key.get_secret_value().encode())


def _keyed_digest(info: bytes, message: str) -> str:
    return hmac.new(_derived_key(info), message.encode(), hashlib.sha256).hexdigest()


def login_account_key(normalized: str) -> str:
    """The throttle's handle for an already-lowercased username in the active tenant."""
    tenant = current_tenant_var.get() or ""
    return _keyed_digest(
        b"account-key", f"{len(tenant)}:{tenant}:{len(normalized)}:{normalized}"
    )


async def _db_lower(db: AsyncSession, username: str) -> str:
    """*username* lowercased by the database, as sign-in matches it.

    Python's ``str.lower`` disagrees with PostgreSQL's ``lower`` on some
    characters, which would split one account across several budgets.
    """
    return await db.scalar(select(func.lower(username)))


def account_binding(user_id: uuid.UUID, key_epoch: int) -> str:
    """What a device cookie is bound to beyond the username.

    The user id makes a username deleted and created again a new account,
    and ``key_epoch``, which password changes and resets advance, makes a
    credential reset forget every remembered browser.
    """
    return f"{user_id}:{key_epoch}"


async def _account(db: AsyncSession, normalized: str) -> tuple[uuid.UUID, str] | None:
    row = (
        await db.execute(
            select(User.id, User.key_epoch).where(
                func.lower(User.username) == normalized
            )
        )
    ).one_or_none()
    return None if row is None else (row.id, account_binding(row.id, row.key_epoch))


def _current_cookie_prefix() -> str:
    """The name prefix of cookies minted under the current secret.

    A rotated secret changes it, so cookies the rotation voided are told
    apart by name and cleared instead of filling the per-browser cap.
    """
    return _DEVICE_COOKIE_PREFIX + _keyed_digest(b"device-generation", "")[:4] + "_"


def device_cookie_name(account_key: str) -> str:
    """One cookie per account, so a browser remembered for two keeps both."""
    return _current_cookie_prefix() + account_key[:16]


def _device_mac(account_key: str, binding: str, nonce: str, issued_at: int) -> str:
    # The account key binds the tenant and the lowercased username.
    message = f"{_DEVICE_COOKIE_VERSION}|{account_key}|{binding}|{nonce}|{issued_at}"
    return _keyed_digest(b"device-cookie", message)


def mint_device_cookie(account_key: str, binding: str) -> str:
    nonce = secrets.token_urlsafe(_NONCE_BYTES)
    issued_at = int(time.time())
    mac = _device_mac(account_key, binding, nonce, issued_at)
    return f"{_DEVICE_COOKIE_VERSION}.{nonce}.{issued_at}.{mac}"


def _device_nonce(value: str, account_key: str, binding: str, now: int) -> str | None:
    """The nonce of a device cookie minted for this account, or None."""
    parts = value.split(".")
    if len(parts) != 4 or parts[0] != _DEVICE_COOKIE_VERSION:
        return None
    _, nonce, issued_raw, mac = parts
    if not (issued_raw.isascii() and issued_raw.isdigit()) or len(issued_raw) > 12:
        return None
    issued_at = int(issued_raw)
    max_age = int(DEVICE_COOKIE_MAX_AGE.total_seconds())
    if not now - max_age <= issued_at <= now + _ISSUED_AT_SKEW_SECONDS:
        return None
    expected = _device_mac(account_key, binding, nonce, issued_at)
    if not hmac.compare_digest(mac.encode(), expected.encode()):
        return None
    return nonce


def _presented_device_key(
    request: Request, account_key: str, binding: str | None
) -> str | None:
    """The ledger key of a valid device cookie for this account, if any.

    Every occurrence is tried: a cookie planted from a sibling domain cannot
    carry a valid MAC, and refusing on a duplicate would let one plant cost
    the owner their remembered browser.
    """
    if binding is None:
        return None
    now = int(time.time())
    for value in cookie_values(request, device_cookie_name(account_key)):
        nonce = _device_nonce(value, account_key, binding, now)
        if nonce is not None:
            return _keyed_digest(b"device-key", nonce)
    return None


def device_cookie_fits(request: Request, account_key: str) -> bool:
    """Whether this browser may hold a device cookie for the account.

    Every device cookie rides every sign-in request, so a browser holds at
    most ``_MAX_REMEMBERED_ACCOUNTS`` of the current generation. At the cap a
    new account goes unremembered rather than displacing one: other
    accounts' cookies can't be verified here, and one planted from a sibling
    domain must not be able to push out a real one.
    """
    name = device_cookie_name(account_key)
    current = _current_cookie_prefix()
    others = {
        other for other, _ in cookies_with_prefix(request, current) if other != name
    }
    return bool(cookie_values(request, name)) or len(others) < _MAX_REMEMBERED_ACCOUNTS


def issue_device_cookie(
    response: Response, request: Request, account_key: str, binding: str
) -> None:
    """Remember this browser for the account, if it fits under the cap.

    Also clears a bounded number of cookies a secret rotation voided, so they
    neither fill the cap nor swell the response when a sibling floods names.
    """
    stale = sorted(
        {
            other
            for other, _ in cookies_with_prefix(request, _DEVICE_COOKIE_PREFIX)
            if not other.startswith(_current_cookie_prefix())
        }
    )
    for other in stale[:_MAX_REMEMBERED_ACCOUNTS]:
        clear_login_device_cookie(response, request, other)
    if not device_cookie_fits(request, account_key):
        return
    set_login_device_cookie(
        response,
        request,
        device_cookie_name(account_key),
        mint_device_cookie(account_key, binding),
        int(DEVICE_COOKIE_MAX_AGE.total_seconds()),
    )


@dataclass(frozen=True)
class LoginReservation:
    """One counted attempt, and the budget it was charged to."""

    attempt_id: uuid.UUID
    account_key: str
    device_key: str | None
    username: str


class _BudgetSpent(Exception):
    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after


def _bucket(account_key: str, device_key: str | None) -> ColumnElement[bool]:
    device = (
        LoginAttempt.device_key.is_(None)
        if device_key is None
        else LoginAttempt.device_key == device_key
    )
    return and_(LoginAttempt.account_key == account_key, device)


def _counted(
    account_key: str, device_key: str | None, now: datetime
) -> ColumnElement[bool]:
    """The rows that spend this budget now: failures, and attempts still in flight."""
    return and_(
        _bucket(account_key, device_key),
        LoginAttempt.attempted_at >= now - LOGIN_FAILURE_WINDOW,
        or_(LoginAttempt.failed, LoginAttempt.attempted_at >= now - _UNSETTLED_GRACE),
    )


async def _lock_bucket(
    db: AsyncSession, account_key: str, device_key: str | None
) -> None:
    # Transaction-scoped, so the commit that records the attempt releases it.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": f"login-throttle:{account_key}:{device_key or ''}"},
    )


async def _check_budget(
    db: AsyncSession, account_key: str, device_key: str | None, now: datetime
) -> None:
    """Raise ``_BudgetSpent`` when the window already holds the limit."""
    count, oldest_failed, oldest_unsettled = (
        await db.execute(
            select(
                func.count(),
                func.min(LoginAttempt.attempted_at).filter(LoginAttempt.failed),
                func.min(LoginAttempt.attempted_at).filter(not_(LoginAttempt.failed)),
            ).where(_counted(account_key, device_key, now))
        )
    ).one()
    if count >= LOGIN_FAILURE_LIMIT:
        frees = []
        if oldest_failed is not None:
            frees.append(oldest_failed + LOGIN_FAILURE_WINDOW)
        if oldest_unsettled is not None:
            frees.append(oldest_unsettled + _UNSETTLED_GRACE)
        frees_at = min(frees)
        raise _BudgetSpent(max(1, math.ceil((frees_at - now).total_seconds())))


async def _reserve_in(
    db: AsyncSession, account_key: str, device_key: str | None
) -> uuid.UUID:
    now = datetime.now(tz=UTC)
    # A spent budget refuses without queueing on the lock; refusing on a
    # stale read only errs toward refusal.
    await _check_budget(db, account_key, device_key, now)
    await _lock_bucket(db, account_key, device_key)
    await _check_budget(db, account_key, device_key, now)
    attempt_id = uuid.uuid4()
    db.add(LoginAttempt(id=attempt_id, account_key=account_key, device_key=device_key))
    await _sweep_expired(db, now)
    await db.commit()
    return attempt_id


async def _sweep_expired(db: AsyncSession, now: datetime) -> None:
    """Drop up to ``_SWEEP_BATCH`` rows that left the window.

    Fixed order with locked rows skipped, so two sweeps for different
    accounts never deadlock over the same expired rows. Each reservation
    adds one row and removes up to a batch, so a backlog drains without
    one sign-in paying for all of it. The batch is a materialized CTE: as a
    plain ``IN`` subquery the planner may rescan it, and each rescan of a
    ``LIMIT ... SKIP LOCKED`` select can hand back a fresh batch.
    """
    batch = (
        select(LoginAttempt.id)
        .where(LoginAttempt.attempted_at < now - LOGIN_FAILURE_WINDOW)
        .order_by(LoginAttempt.id)
        .limit(_SWEEP_BATCH)
        .with_for_update(skip_locked=True)
        .cte("expired_login_attempts")
        .prefix_with("MATERIALIZED")
    )
    await db.execute(
        delete(LoginAttempt).where(LoginAttempt.id.in_(select(batch.c.id)))
    )


async def reserve_login_attempt(
    db: AsyncSession, request: Request, username: str
) -> LoginReservation:
    """Count one attempt before its password is checked, or refuse it with 429.

    Commits the request session's transaction. *username* is the whole
    submitted value, as the password check matches it.
    """
    normalized = await _db_lower(db, username)
    account_key = login_account_key(normalized)
    device_key = None
    # The cookie-mode header proves the request came from this app's own
    # script: a cross-origin form, which a same-site sibling can submit with
    # the cookie attached, cannot set it without a CORS preflight.
    if wants_cookie_auth(request) and cookie_values(
        request, device_cookie_name(account_key)
    ):
        account = await _account(db, normalized)
        binding = None if account is None else account[1]
        device_key = _presented_device_key(request, account_key, binding)
    try:
        if device_key is not None:
            try:
                attempt_id = await _reserve_in(db, account_key, device_key)
                return LoginReservation(
                    attempt_id, account_key, device_key, username[:_AUDIT_USERNAME_MAX]
                )
            except _BudgetSpent:
                device_key = None
        attempt_id = await _reserve_in(db, account_key, None)
    except _BudgetSpent as spent:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": LOGIN_THROTTLED_CODE, "message": LOGIN_THROTTLED_MESSAGE},
            headers={"Retry-After": str(spent.retry_after)},
        ) from None
    return LoginReservation(
        attempt_id, account_key, None, username[:_AUDIT_USERNAME_MAX]
    )


async def settle_login_failure(
    db: AsyncSession, request: Request, reservation: LoginReservation
) -> None:
    """Count a wrong password for the window; audit the attempt that fills its budget.

    One audit row per window: a later failure in the same window finds the
    tripped row and stays quiet. Runs in the caller's transaction, which the
    caller commits before answering.
    """
    await _lock_bucket(db, reservation.account_key, reservation.device_key)
    await db.execute(
        update(LoginAttempt)
        .where(LoginAttempt.id == reservation.attempt_id)
        .values(failed=True)
    )
    in_window = and_(
        _bucket(reservation.account_key, reservation.device_key),
        LoginAttempt.attempted_at >= datetime.now(tz=UTC) - LOGIN_FAILURE_WINDOW,
    )
    # Recorded failures only: an attempt still in flight may yet succeed.
    failures = await db.scalar(
        select(func.count()).where(in_window, LoginAttempt.failed)
    )
    if int(failures or 0) < LOGIN_FAILURE_LIMIT:
        return
    if await db.scalar(select(exists().where(in_window, LoginAttempt.tripped))):
        return
    await db.execute(
        update(LoginAttempt)
        .where(LoginAttempt.id == reservation.attempt_id)
        .values(tripped=True)
    )
    await audit_emit(
        db,
        AuditEvent(
            user_id=None,
            action="user.login.throttled",
            resource_type="user",
            details={
                "username": reservation.username,
                "scope": "untrusted" if reservation.device_key is None else "device",
                "failures": int(failures),
                "window_seconds": int(LOGIN_FAILURE_WINDOW.total_seconds()),
            },
            ip_address=get_client_ip(request),
        ),
    )


async def settle_login_success(db: AsyncSession, reservation: LoginReservation) -> None:
    """Uncount an attempt whose password was right, in the caller's transaction."""
    await db.execute(
        delete(LoginAttempt).where(LoginAttempt.id == reservation.attempt_id)
    )


def _trust_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_trust_token(db: AsyncSession, username: str) -> str | None:
    """Mint a single-use link token that remembers a browser for *username*.

    Returns None when no account has that username. Only the token's digest
    is stored, and deleting the account deletes its tokens. The caller commits.
    """
    normalized = await _db_lower(db, username)
    account = await _account(db, normalized)
    if account is None:
        return None
    now = datetime.now(tz=UTC)
    await db.execute(delete(LoginTrustToken).where(LoginTrustToken.expires_at <= now))
    token = secrets.token_urlsafe(32)
    db.add(
        LoginTrustToken(
            id=uuid.uuid4(),
            token_hash=_trust_token_hash(token),
            account_key=login_account_key(normalized),
            user_id=account[0],
            binding=account[1],
            expires_at=now + TRUST_TOKEN_TTL,
        )
    )
    return token


async def redeem_trust_token(db: AsyncSession, token: str) -> tuple[str, str] | None:
    """Consume *token* and return its account key and binding, or None if unusable.

    One ``DELETE ... RETURNING``, so two requests racing on one link cannot
    both succeed. The caller commits.
    """
    if not token or len(token) > _TRUST_TOKEN_MAX_LENGTH:
        return None
    row = (
        await db.execute(
            delete(LoginTrustToken)
            .where(
                LoginTrustToken.token_hash == _trust_token_hash(token),
                LoginTrustToken.expires_at > func.now(),
            )
            .returning(
                LoginTrustToken.account_key,
                LoginTrustToken.user_id,
                LoginTrustToken.binding,
            )
        )
    ).one_or_none()
    if row is None:
        return None
    # A credential reset, rename or secret rotation since the link was minted
    # voids it, as each does every remembered browser.
    current = (
        await db.execute(
            select(func.lower(User.username), User.key_epoch).where(
                User.id == row.user_id
            )
        )
    ).one_or_none()
    if current is None:
        return None
    normalized, key_epoch = current
    if (
        login_account_key(normalized) != row.account_key
        or account_binding(row.user_id, key_epoch) != row.binding
    ):
        return None
    return row.account_key, row.binding

"""Per-account throttle for password sign-in, with remembered browsers.

Each account accepts at most ``LOGIN_FAILURE_LIMIT`` failed sign-ins per
``LOGIN_FAILURE_WINDOW`` from clients it does not know. A browser that signed
in to the account before carries a device cookie and spends a budget of its
own, so guessing from elsewhere cannot lock the owner out of that browser. A
remembered browser that spends its own budget is treated as unknown.

An attempt is reserved before the password check, in one short transaction
under an advisory lock on its budget, so parallel requests cannot all read
the count before any of them is recorded. A failure keeps its reservation,
and so does a request cancelled mid-check; anything past the password check
removes it. A refused attempt never reaches the password check or writes a
row, whether or not the account exists.

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
from sqlalchemy import ColumnElement, and_, delete, exists, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db.tenant_session import current_tenant_var
from app.core.dependencies import get_client_ip
from app.modules.auth.cookies import cookie_values, set_login_device_cookie
from app.modules.auth.models import LoginAttempt, LoginTrustToken
from app.platform.audit import AuditEvent, audit_emit

LOGIN_FAILURE_LIMIT = 10
LOGIN_FAILURE_WINDOW = timedelta(hours=1)
DEVICE_COOKIE_MAX_AGE = timedelta(days=180)
TRUST_TOKEN_TTL = timedelta(minutes=10)

LOGIN_THROTTLED_CODE = "login_throttled"
LOGIN_THROTTLED_MESSAGE = (
    "Too many failed sign-ins for this account. Use a browser you've signed "
    "in with before, or sign in with SSO."
)

_DEVICE_COOKIE_PREFIX = "geolens_device_"
_DEVICE_COOKIE_VERSION = "v1"
_NONCE_BYTES = 32
# Tolerates a clock step between workers; a cookie dated further ahead is forged.
_ISSUED_AT_SKEW_SECONDS = 300
_TRUST_TOKEN_MAX_LENGTH = 128
_KDF_SALT = b"geolens-login-throttle"


def _derived_key(info: bytes) -> bytes:
    """A purpose-bound key from the JWT secret, sharing nothing with its other uses."""
    kdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=_KDF_SALT, info=info)
    return kdf.derive(settings.jwt_secret_key.get_secret_value().encode())


def _keyed_digest(info: bytes, message: str) -> str:
    return hmac.new(_derived_key(info), message.encode(), hashlib.sha256).hexdigest()


def login_account_key(username: str) -> str:
    """The throttle's handle for *username* in the active tenant."""
    tenant = current_tenant_var.get() or ""
    normalized = username.lower()
    return _keyed_digest(
        b"account-key", f"{len(tenant)}:{tenant}:{len(normalized)}:{normalized}"
    )


def device_cookie_name(account_key: str) -> str:
    """One cookie per account, so a browser remembered for two keeps both."""
    return _DEVICE_COOKIE_PREFIX + account_key[:16]


def _device_mac(account_key: str, nonce: str, issued_at: int) -> str:
    # The account key binds the tenant and the lowercased username.
    message = f"{_DEVICE_COOKIE_VERSION}|{account_key}|{nonce}|{issued_at}"
    return _keyed_digest(b"device-cookie", message)


def mint_device_cookie(account_key: str) -> str:
    nonce = secrets.token_urlsafe(_NONCE_BYTES)
    issued_at = int(time.time())
    mac = _device_mac(account_key, nonce, issued_at)
    return f"{_DEVICE_COOKIE_VERSION}.{nonce}.{issued_at}.{mac}"


def _device_nonce(value: str, account_key: str, now: int) -> str | None:
    """The nonce of a device cookie minted for *account_key*, or None."""
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
    expected = _device_mac(account_key, nonce, issued_at)
    if not hmac.compare_digest(mac.encode(), expected.encode()):
        return None
    return nonce


def _presented_device_key(request: Request, account_key: str) -> str | None:
    """The ledger key of a valid device cookie for this account, if any.

    Every occurrence is tried: a cookie planted from a sibling domain cannot
    carry a valid MAC, and refusing on a duplicate would let one plant cost
    the owner their remembered browser.
    """
    now = int(time.time())
    for value in cookie_values(request, device_cookie_name(account_key)):
        nonce = _device_nonce(value, account_key, now)
        if nonce is not None:
            return _keyed_digest(b"device-key", nonce)
    return None


def issue_device_cookie(response: Response, request: Request, account_key: str) -> None:
    set_login_device_cookie(
        response,
        request,
        device_cookie_name(account_key),
        mint_device_cookie(account_key),
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
    count, oldest = (
        await db.execute(
            select(func.count(), func.min(LoginAttempt.attempted_at)).where(
                _bucket(account_key, device_key),
                LoginAttempt.attempted_at >= now - LOGIN_FAILURE_WINDOW,
            )
        )
    ).one()
    if count >= LOGIN_FAILURE_LIMIT:
        frees_at = oldest + LOGIN_FAILURE_WINDOW
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
    """Drop rows that left the window.

    Fixed order with locked rows skipped, so two sweeps for different
    accounts never deadlock over the same expired rows.
    """
    expired = (
        select(LoginAttempt.id)
        .where(LoginAttempt.attempted_at < now - LOGIN_FAILURE_WINDOW)
        .order_by(LoginAttempt.id)
        .with_for_update(skip_locked=True)
    )
    await db.execute(
        delete(LoginAttempt).where(LoginAttempt.id.in_(expired.scalar_subquery()))
    )


async def reserve_login_attempt(
    db: AsyncSession, request: Request, username: str
) -> LoginReservation:
    """Count one attempt before its password is checked, or refuse it with 429.

    Commits the request session's transaction.
    """
    account_key = login_account_key(username)
    device_key = _presented_device_key(request, account_key)
    try:
        if device_key is not None:
            try:
                attempt_id = await _reserve_in(db, account_key, device_key)
                return LoginReservation(attempt_id, account_key, device_key, username)
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
    return LoginReservation(attempt_id, account_key, None, username)


async def settle_login_failure(
    db: AsyncSession, request: Request, reservation: LoginReservation
) -> None:
    """Keep a wrong password counted; audit the attempt that fills its budget.

    One audit row per window: a later failure in the same window finds the
    tripped row and stays quiet. Runs in the caller's transaction, which the
    caller commits.
    """
    await _lock_bucket(db, reservation.account_key, reservation.device_key)
    now = datetime.now(tz=UTC)
    in_window = and_(
        _bucket(reservation.account_key, reservation.device_key),
        LoginAttempt.attempted_at >= now - LOGIN_FAILURE_WINDOW,
    )
    failures = await db.scalar(select(func.count()).where(in_window))
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


async def create_trust_token(db: AsyncSession, username: str) -> str:
    """Mint a single-use link token that remembers a browser for *username*.

    Only the token's digest is stored. The caller commits.
    """
    now = datetime.now(tz=UTC)
    await db.execute(delete(LoginTrustToken).where(LoginTrustToken.expires_at <= now))
    token = secrets.token_urlsafe(32)
    db.add(
        LoginTrustToken(
            id=uuid.uuid4(),
            token_hash=_trust_token_hash(token),
            account_key=login_account_key(username),
            expires_at=now + TRUST_TOKEN_TTL,
        )
    )
    return token


async def redeem_trust_token(db: AsyncSession, token: str) -> str | None:
    """Consume *token* and return its account key, or None if unusable.

    One ``DELETE ... RETURNING``, so two requests racing on one link cannot
    both succeed. The caller commits.
    """
    if not token or len(token) > _TRUST_TOKEN_MAX_LENGTH:
        return None
    return await db.scalar(
        delete(LoginTrustToken)
        .where(
            LoginTrustToken.token_hash == _trust_token_hash(token),
            LoginTrustToken.expires_at > func.now(),
        )
        .returning(LoginTrustToken.account_key)
    )

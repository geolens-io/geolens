# SPDX-License-Identifier: Apache-2.0
"""Credential storage — OS keyring with credentials.toml fallback.

Hand-maintained — NOT regenerated. Mirrors sdks/python/geolens/auth.py's
"configure exactly one" discipline for BearerToken vs ApiKey.

Backend storage precedence (matches CONTEXT.md D-35):
    CLI flag (handled in main.py)
    > GEOLENS_TOKEN env var
    > credentials.toml
    > OS keyring

Storage backends:
    Default: OS keyring via `keyring` (service="geolens", account=<instance_url>)
    Fallback: ~/.config/geolens/credentials.toml (mode 0600)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

import keyring
import structlog
import tomli_w
import tomllib
from keyring.errors import KeyringError

from . import config as _config

log = structlog.get_logger()
SERVICE = "geolens"


@dataclass(frozen=True)
class BearerToken:
    value: str


@dataclass(frozen=True)
class ApiKey:
    value: str


# ---------- Internal helpers ----------

def _keyring_account_token(instance: str) -> str:
    return instance


def _keyring_account_refresh(instance: str) -> str:
    return f"{instance}:refresh"


def _keyring_account_api_key(instance: str) -> str:
    return f"{instance}:api_key"


def _read_credentials_file() -> dict:
    path = _config.credentials_path()
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError:
        return {}


def _write_credentials_file(data: dict) -> None:
    _config.atomic_write_text(
        _config.credentials_path(),
        tomli_w.dumps(data),
        mode=0o600,
        tighten_parent=True,
    )


def _set_credential_field(instance: str, field: str, value: str) -> None:
    data = _read_credentials_file()
    data.setdefault(instance, {})[field] = value
    _write_credentials_file(data)


def _clear_credential_section(instance: str) -> None:
    data = _read_credentials_file()
    data.pop(instance, None)
    if data:
        _write_credentials_file(data)
    else:
        # Empty -> remove the file entirely so `geolens logout` leaves no trace.
        path = _config.credentials_path()
        if path.exists():
            path.unlink()


# ---------- Store ----------

def store_bearer_token(instance: str, token: str, *, no_keyring: bool = False) -> str:
    """Store the access token. Returns 'keyring' or 'file'."""
    if not no_keyring:
        try:
            keyring.set_password(SERVICE, _keyring_account_token(instance), token)
            return "keyring"
        except KeyringError as exc:
            log.warning("keyring_unavailable_falling_back_to_file", error=str(exc))
    _set_credential_field(instance, "bearer_token", token)
    return "file"


def store_api_key(instance: str, api_key: str, *, no_keyring: bool = False) -> str:
    """Store an API key. Returns 'keyring' or 'file'."""
    if not no_keyring:
        try:
            keyring.set_password(SERVICE, _keyring_account_api_key(instance), api_key)
            return "keyring"
        except KeyringError as exc:
            log.warning("keyring_unavailable_falling_back_to_file", error=str(exc))
    _set_credential_field(instance, "api_key", api_key)
    return "file"


def store_refresh_token(instance: str, refresh: str, *, no_keyring: bool = False) -> str:
    if not no_keyring:
        try:
            keyring.set_password(SERVICE, _keyring_account_refresh(instance), refresh)
            return "keyring"
        except KeyringError as exc:
            log.warning("keyring_unavailable_falling_back_to_file", error=str(exc))
    _set_credential_field(instance, "refresh_token", refresh)
    return "file"


# ---------- Load ----------

def load_bearer_token(instance: str) -> Optional[BearerToken]:
    """Return the active bearer token per the D-35 precedence."""
    env_token = _config.get_token_from_env()
    if env_token:
        return BearerToken(env_token)
    # credentials.toml > keyring (file is explicit; keyring is fallback)
    data = _read_credentials_file().get(instance, {})
    token = data.get("bearer_token")
    if token:
        return BearerToken(token)
    try:
        kr_token = keyring.get_password(SERVICE, _keyring_account_token(instance))
    except KeyringError:
        return None
    return BearerToken(kr_token) if kr_token else None


def load_api_key(instance: str) -> Optional[ApiKey]:
    data = _read_credentials_file().get(instance, {})
    key = data.get("api_key")
    if key:
        return ApiKey(key)
    try:
        kr_key = keyring.get_password(SERVICE, _keyring_account_api_key(instance))
    except KeyringError:
        return None
    return ApiKey(kr_key) if kr_key else None


def load_refresh_token(instance: str) -> Optional[str]:
    data = _read_credentials_file().get(instance, {})
    refresh = data.get("refresh_token")
    if refresh:
        return refresh
    try:
        return keyring.get_password(SERVICE, _keyring_account_refresh(instance))
    except KeyringError:
        return None


#: fix(#1778 review round 10): the field name for the "active credential
#: kind" marker in credentials.toml — see load_active_credential_kind().
_ACTIVE_KIND_FIELD = "active_kind"


def load_active_credential_kind(instance: str) -> Optional[str]:
    """Return ``"bearer"`` or ``"api_key"`` — whichever kind ``login``
    most recently stored for ``instance`` — or ``None`` if never set.

    fix(#1778 review round 10): a stale competing credential surviving
    in EITHER backend (keyring or credentials.toml) after a swap could
    always outrank the one that was actually just stored, because
    ``load_bearer_token``/``load_api_key`` are independent reads and
    ``AppState.sdk()``'s precedence unconditionally preferred bearer —
    rounds 5 through 9 chased that by making cleanup of the OTHER
    backend more and more careful, but cleanup can only ever be
    best-effort (keyring and credentials.toml are separate backends
    with no shared transaction). This marker is written unconditionally
    by ``replace_credentials()`` in the SAME file section regardless of
    which backend the secret itself landed in, so it survives even a
    ``--no-keyring`` login or a keyring that was unavailable at store
    time. Readers (``AppState.sdk()``) consult it FIRST: cleanup
    failing to evict a competing entry no longer matters for
    correctness, only for tidiness.
    """
    data = _read_credentials_file().get(instance, {})
    kind = data.get(_ACTIVE_KIND_FIELD)
    return kind if kind in ("bearer", "api_key") else None


# ---------- Delete ----------

def delete_credentials(instance: str) -> None:
    """Remove all three keyring entries AND the credentials.toml section.

    Missing entries are silently ignored — logout is idempotent.
    """
    for account in (
        _keyring_account_token(instance),
        _keyring_account_refresh(instance),
        _keyring_account_api_key(instance),
    ):
        try:
            keyring.delete_password(SERVICE, account)
        except Exception:
            # PasswordDeleteError + KeyringError + missing entries all swallowed.
            pass
    _clear_credential_section(instance)


# ---------- Atomic credential swap (login) ----------

_FIELD_BY_KIND = {"bearer": "bearer_token", "api_key": "api_key"}
_ACCOUNT_FN_BY_KIND = {
    "bearer": _keyring_account_token,
    "api_key": _keyring_account_api_key,
    "refresh": _keyring_account_refresh,
}


class _Unknown:
    """Sentinel: the snapshot could not read this keyring account at all
    (fix(#1778 review round 9)) — distinct from ``None`` ("confirmed
    absent"). Swallowing a read failure to ``None`` recorded an EXISTING
    credential as absent; if cleanup later failed and the keyring
    happened to be readable again by the time ``_restore_credentials``
    ran, that ``None`` made it call ``delete_password()`` on an account
    that actually held a real, pre-existing credential the whole time —
    the snapshot just couldn't see it for a moment. Restore must never
    delete on this sentinel, only on a confirmed absence.
    """

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "<unknown>"


_UNKNOWN = _Unknown()

_KeyringValue = Union[str, None, _Unknown]


@dataclass(frozen=True)
class _CredentialSnapshot:
    """Raw values read directly from each backend — deliberately NOT
    ``load_bearer_token()`` et al., which resolve GEOLENS_TOKEN env
    precedence; a restore must reproduce exactly what storage held, not
    what precedence would currently resolve to.

    Each keyring field is a string (the stored value), ``None``
    (confirmed absent), or ``_UNKNOWN`` (the read itself failed — see
    ``_Unknown``)."""

    keyring_bearer: _KeyringValue
    keyring_api_key: _KeyringValue
    keyring_refresh: _KeyringValue
    file_section: dict


def _snapshot_credentials(instance: str) -> _CredentialSnapshot:
    def _kr(account: str) -> _KeyringValue:
        try:
            return keyring.get_password(SERVICE, account)
        except KeyringError:
            return _UNKNOWN

    return _CredentialSnapshot(
        keyring_bearer=_kr(_keyring_account_token(instance)),
        keyring_api_key=_kr(_keyring_account_api_key(instance)),
        keyring_refresh=_kr(_keyring_account_refresh(instance)),
        file_section=dict(_read_credentials_file().get(instance, {})),
    )


def _restore_credentials(instance: str, snapshot: _CredentialSnapshot) -> None:
    """Best-effort restore to exactly the pre-swap state.

    Only called when the delete-competing-kinds step of
    ``replace_credentials`` fails partway through — there is nothing
    further to fall back to here, so each write is independently
    swallowed-and-logged rather than raised.
    """
    for account, value in (
        (_keyring_account_token(instance), snapshot.keyring_bearer),
        (_keyring_account_api_key(instance), snapshot.keyring_api_key),
        (_keyring_account_refresh(instance), snapshot.keyring_refresh),
    ):
        if value is _UNKNOWN:
            # fix(#1778 review round 9): never learned whether this
            # account held a credential — see _Unknown. Neither
            # deleting nor overwriting it is safe; leave it alone.
            continue
        try:
            if value is None:
                keyring.delete_password(SERVICE, account)
            else:
                keyring.set_password(SERVICE, account, value)
        except Exception as exc:
            log.warning("credential_restore_failed", account=account, error=str(exc))

    try:
        data = _read_credentials_file()
        if snapshot.file_section:
            data[instance] = dict(snapshot.file_section)
        else:
            data.pop(instance, None)
        if data:
            _write_credentials_file(data)
        else:
            path = _config.credentials_path()
            if path.exists():
                path.unlink()
    except Exception as exc:
        log.warning("credential_restore_failed", account="file", error=str(exc))


def _delete_stale_credentials(instance: str, *, keep: str, keep_backend: str) -> None:
    """Delete every stored credential for ``instance`` except ``keep``'s
    value in the backend it was just stored to (``keep_backend``).

    Two related cleanups happen in one pass:

    - every OTHER credential kind (the competing types) is deleted from
      BOTH backends, same as before;
    - ``keep`` itself is ALSO deleted from whichever backend it was NOT
      just stored to (fix(#1778 review round 5)). ``store_bearer_token``/
      ``store_api_key`` only ever write ONE backend per call (keyring, or
      the file on fallback/``no_keyring``); a stale same-kind value left
      in the OTHER backend from an earlier login was never cleaned up,
      and ``load_bearer_token``/``load_api_key`` prefer the file over
      keyring — so a stale file value kept winning over a freshly-stored
      keyring value even though login reported the new one stored.

    fix(#1778 review round 7): the keyring half used to swallow EVERY
    delete failure with a blanket ``except Exception: pass``, matching
    ``delete_credentials()``'s best-effort semantics. But
    ``keyring.errors.PasswordDeleteError`` is raised for BOTH "no such
    entry" (expected and fine — this cleanup is idempotent by design)
    AND a genuine backend refusal (a locked keychain, permission
    denied, ...), with no reliable way to tell the two apart from the
    exception alone. Swallowing both meant a real refusal was silently
    ignored: ``replace_credentials()`` reported success while the old
    credential stayed live in the OTHER backend, and
    ``load_bearer_token``/``load_api_key`` kept resolving it — a stale
    BEARER token in particular keeps outranking a freshly-stored API
    key under the stored-credential precedence.

    Checking existence FIRST (rather than pattern-matching the
    exception) resolves the ambiguity: an already-absent entry is
    skipped without ever calling delete (nothing to fail), so a delete
    that IS attempted was for an entry that existed, and its failure is
    real — it propagates. The credentials.toml write below is allowed
    to raise for the same reason: ``replace_credentials`` is the one
    that needs to know, so it can restore the pre-swap snapshot instead
    of leaving either backend in a half-cleaned state.

    fix(#1778 review round 8): an UNREADABLE keyring (locked, backend
    down, ...) during the existence check is NOT "no such entry" —
    round 7's fix skipped it as if it were, but that meant a stale
    credential we genuinely could not see was left untouched. That
    matters specifically because ``store_bearer_token``/
    ``store_api_key`` themselves fall back to the credentials.toml file
    on a ``KeyringError`` — so a keyring that is locked at STORE time
    (the new credential lands in the file) can still hold an untouched
    OLD credential from an earlier, working login. Once the keyring
    becomes readable again, ``load_bearer_token``'s keyring-as-last-
    resort lookup returns that stale value, and it outranks the
    freshly-stored (file-backed) one under ``AppState.sdk()``'s
    bearer-first precedence. An unreadable backend during cleanup is
    therefore treated as a failed swap: it propagates, so
    ``replace_credentials`` restores its snapshot and ``login`` reports
    the failure instead of the false success.

    fix(#1778 review round 9): round 8's propagation was UNCONDITIONAL,
    which broke ``login --no-keyring`` and any headless install with no
    working keyring at all — ``keep_backend`` is ``"file"`` in both
    cases (``store_bearer_token``/``store_api_key`` never touch keyring
    when ``no_keyring=True``, or fall back to the file the moment
    keyring raises), and the cleanup loop below still tried to read
    keyring for every account regardless, so it hit the exact same
    unavailable backend and failed the whole login — defeating the
    automatic file fallback the store side already has. The keyring
    read failure is now fatal ONLY when ``keep_backend == "keyring"``:
    that is the one case where the keyring is DEMONSTRABLY reachable
    right now (the new credential just landed there), so a read
    failure for a different account is a real, worth-surfacing
    problem, not an unavailable backend. When ``keep_backend`` is
    ``"file"`` — by explicit ``--no-keyring`` or because the store
    already fell back — an unreadable keyring is tolerated the same as
    "no such entry": there is nothing here that can safely be told
    apart from a keyring that simply doesn't exist on this box.
    """
    for name, account_fn in _ACCOUNT_FN_BY_KIND.items():
        if name == keep and keep_backend == "keyring":
            continue
        account = account_fn(instance)
        try:
            exists = keyring.get_password(SERVICE, account) is not None
        except KeyringError as exc:
            if keep_backend == "keyring":
                raise KeyringError(
                    f"could not read the keyring while cleaning up stored "
                    f"credentials for {instance}: {exc}"
                ) from exc
            # keep_backend == "file": --no-keyring, or store_* already
            # hit this identical failure and fell back moments ago.
            # Either way the keyring is not part of this operation by
            # the caller's own choice or by its own current state, and
            # failing the whole login over it would make a headless box
            # with no keyring unable to log in at all.
            continue
        if exists:
            keyring.delete_password(SERVICE, account)

    data = _read_credentials_file()
    section = data.get(instance)
    if not section:
        return
    keep_field = _FIELD_BY_KIND.get(keep)
    for field in ("bearer_token", "api_key", "refresh_token"):
        if field == keep_field and keep_backend == "file":
            continue
        section.pop(field, None)
    if section:
        data[instance] = section
    else:
        data.pop(instance, None)
    if data:
        _write_credentials_file(data)
    else:
        path = _config.credentials_path()
        if path.exists():
            path.unlink()


def replace_credentials(
    instance: str, kind: str, value: str, *, no_keyring: bool = False
) -> str:
    """Atomically swap the active credential for ``instance`` to ``kind``.

    fix(#1778 review round 4): ``login`` used to call ``delete_credentials()``
    BEFORE storing the replacement, so a storage failure (keyring falling
    back to a read-only or full XDG path, a permissions error, ...) left
    the user logged out — the working credential was already gone — with
    login reporting failure too. This stores the new credential FIRST;
    only once that succeeds is anything else touched.

    If the store itself raises, nothing here has touched storage yet
    (the snapshot read is read-only) — the exception propagates and the
    prior credentials are untouched. If the cleanup afterward fails
    partway — keyring and credentials.toml are separate backends with no
    shared transaction, so that step is the one place this can't be
    fully atomic — the pre-swap snapshot is restored before re-raising,
    so the net effect is still "nothing changed" rather than a mix of
    old and new credentials.

    fix(#1778 review round 5): the cleanup step deletes both the
    competing credential kinds AND ``kind``'s own value from whichever
    backend it did NOT just land in — see ``_delete_stale_credentials``.
    Without that second part, a bearer token stored in credentials.toml
    by an earlier ``--no-keyring`` login survived a later plain
    ``login`` that stored the replacement in the keyring, and
    ``load_bearer_token``'s file-over-keyring precedence kept resolving
    the stale one.

    fix(#1778 review round 10): rounds 5-9 tried to make that cleanup
    step correctness-bearing (deleting the stale competing entry
    reliably enough that it could never be read back), but cleanup can
    only ever be best-effort — keyring and credentials.toml are
    separate backends with no shared transaction, and an API-key login
    that fell back to the file while the keyring was temporarily
    unavailable had NOTHING it could safely do about a stale bearer
    token sitting in that unreachable keyring. This now also writes an
    explicit "active credential kind" marker (see
    ``load_active_credential_kind``) into the SAME file section the
    snapshot/restore machinery already covers, unconditionally —
    regardless of which backend ``value`` itself landed in. Readers
    consult that marker first, so a stale competing entry surviving in
    the other backend can no longer outrank the credential that was
    just stored; ``_delete_stale_credentials`` below is now tidiness,
    not the thing correctness depends on.

    ``kind`` is ``"bearer"`` or ``"api_key"``. Returns ``'keyring'`` or
    ``'file'`` (where the new credential landed).
    """
    if kind not in ("bearer", "api_key"):
        raise ValueError(f"unknown credential kind: {kind!r}")

    snapshot = _snapshot_credentials(instance)

    if kind == "bearer":
        backend = store_bearer_token(instance, value, no_keyring=no_keyring)
    else:
        backend = store_api_key(instance, value, no_keyring=no_keyring)

    # The marker lives in the file section the snapshot above already
    # captured, so a subsequent restore (on a cleanup failure) correctly
    # reverts it too, along with everything else — no separate rollback
    # path is needed for it.
    _set_credential_field(instance, _ACTIVE_KIND_FIELD, kind)

    try:
        _delete_stale_credentials(instance, keep=kind, keep_backend=backend)
    except Exception:
        _restore_credentials(instance, snapshot)
        raise

    return backend


# ---------- Refresh ----------

def _detect_credential_backend(instance: str) -> bool:
    """Return True (no_keyring=True / file backend) if the refresh token was
    read from credentials.toml, False (keyring backend) otherwise.

    We check the credentials file first because load_refresh_token uses the
    same file-before-keyring precedence — if the file has a refresh token,
    the credential lives in the file backend.
    """
    file_data = _read_credentials_file().get(instance, {})
    return "refresh_token" in file_data


def try_refresh(instance: str) -> Optional[str]:
    """Attempt a single refresh; return new access token or None on failure.

    Per CONTEXT D-13, this is called once on a 401. If it fails, the caller
    prints "Session expired" and exits with EXIT_AUTH (3).

    BUG-013 fix: rotated tokens are written back to the SAME backend that
    held the original credential (file vs keyring) so that a file-backed
    credential is not shadowed by a newly keyring-written token.
    """
    refresh = load_refresh_token(instance)
    if not refresh:
        return None

    # Detect the backend BEFORE the HTTP call so we know where to write back.
    no_keyring = _detect_credential_backend(instance)

    from geolens.api.auth import refresh_auth_refresh_post
    from geolens.models.refresh_request import RefreshRequest

    from ._sdk_helpers import make_client

    try:
        # fix(#1778 review round 1): this used to build its own client
        # with the SDK's default timeout=None (unbounded), so a stalled
        # refresh endpoint hung the calling command forever instead of
        # falling back to "refresh failed" within a bounded time.
        # fix(#1778 review round 2): routed through make_client() (the
        # single construction point for every GeolensClient in this
        # package) rather than setting the bound here directly.
        sdk = make_client(instance)
        body = RefreshRequest(refresh_token=refresh)
        resp = refresh_auth_refresh_post.sync_detailed(client=sdk.client, body=body)
    except Exception as exc:  # network or unexpected SDK error (incl. timeout)
        log.warning("refresh_failed", error=str(exc))
        return None
    if int(resp.status_code) != 200:
        return None
    parsed = resp.parsed
    if parsed is None or not getattr(parsed, "access_token", None):
        return None
    new_access = parsed.access_token
    store_bearer_token(instance, new_access, no_keyring=no_keyring)
    new_refresh = getattr(parsed, "refresh_token", None)
    if new_refresh:
        store_refresh_token(instance, new_refresh, no_keyring=no_keyring)
    return new_access

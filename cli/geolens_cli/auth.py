# SPDX-License-Identifier: Apache-2.0
"""Credential storage — OS keyring with credentials.toml fallback.

Hand-maintained — NOT regenerated. Mirrors sdks/python/geolens/auth.py's
"configure exactly one" discipline for BearerToken vs ApiKey.

Backend storage precedence:
    CLI flag (handled in main.py)
    > GEOLENS_TOKEN env var
    > credentials.toml
    > OS keyring

Storage backends:
    Default: OS keyring via `keyring` (service="geolens", account=<instance_url>)
    Fallback: ~/.config/geolens/credentials.toml (mode 0600)
"""
from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import keyring
import structlog
import tomli_w
import tomllib
from keyring.errors import KeyringError

from . import config as _config

# Unconfigured structlog prints every log call to stdout, which would corrupt
# the one JSON document a --json command promises there. Send this module's
# logger to stderr instead, once, at import time. (_sdk_helpers.py uses stdlib
# logging for the same reason.)
structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))
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


def _keyring_account_refresh_fingerprint(instance: str) -> str:
    return f"{instance}:refresh_fp"


def _fingerprint_bearer(bearer_token: str) -> str:
    """A short, non-reversible pairing tag for a bearer token, never the token
    itself and never logged. It proves a stored refresh token belongs to the
    bearer it would rotate, not just that both are present. sha256 truncated
    to 16 hex chars is enough: it is only compared against itself."""
    # codeql[py/weak-sensitive-data-hashing] comparison tag over a high-entropy bearer, not password storage; the digest is truncated, never reversible to the token, and never used to authenticate
    return hashlib.sha256(bearer_token.encode()).hexdigest()[:16]


# The credential set for an instance, defined once as (name,
# keyring-account-fn, file-field-name) triples. Every operation that treats the
# whole set uniformly (snapshot, restore, logout, stale-credential cleanup)
# iterates this tuple, so a member added later cannot be forgotten in one of
# them (test_credential_set_structural.py). The refresh_fingerprint is the
# fourth member: a login rollback that dropped it would restore a bearer+refresh
# pair without the fingerprint proving they belong together.
_CREDENTIAL_SET = (
    ("bearer", _keyring_account_token, "bearer_token"),
    ("api_key", _keyring_account_api_key, "api_key"),
    ("refresh", _keyring_account_refresh, "refresh_token"),
    ("refresh_fingerprint", _keyring_account_refresh_fingerprint, "refresh_fingerprint"),
)


class CredentialsFileCorrupt(Exception):
    """Raised by ``_read_credentials_file()`` when credentials.toml exists but
    cannot be read or parsed.

    Degrading this to ``{}`` would be indistinguishable from "no file", and a
    writer building on that dict would overwrite the corrupt file with only the
    current instance's data, destroying every other instance's file-backed
    credentials. Every write path therefore refuses to touch the file, while
    read-with-fallback paths (load_bearer_token and friends, snapshot/restore,
    try_refresh's backend detection) degrade it to "nothing usable here, try the
    other backend" so an unrelated broken file cannot break flows that never
    write it.
    """

    def __init__(self, path: Path, detail: str) -> None:
        super().__init__(f"credentials file at {path} is corrupt: {detail}")
        self.path = path
        self.detail = detail


def _read_credentials_file() -> dict:
    path = _config.credentials_path()
    if not path.is_file():
        return {}
    # An unreadable file (PermissionError or any OSError) is reported the same
    # way as an unparseable one: neither can be trusted.
    try:
        text = path.read_text()
    except OSError as exc:
        raise CredentialsFileCorrupt(path, str(exc)) from exc
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CredentialsFileCorrupt(path, str(exc)) from exc


def _write_credentials_file(data: dict) -> None:
    _config.atomic_write_text(
        _config.credentials_path(),
        tomli_w.dumps(data),
        mode=0o600,
        tighten_parent=True,
    )


def _set_credential_field(instance: str, field: str, value: str) -> None:
    # CredentialsFileCorrupt propagates: merging new data into an unparseable
    # file would silently discard what was in it. Callers for whom this write
    # is non-fatal (replace_credentials' marker write, try_refresh's) catch it
    # at their own call site, since only they know whether the primary
    # credential already landed elsewhere.
    data = _read_credentials_file()
    data.setdefault(instance, {})[field] = value
    _write_credentials_file(data)


def _clear_credential_section(instance: str) -> None:
    # CredentialsFileCorrupt propagates deliberately: logout is a
    # read-modify-write, and treating an unreadable file as empty would rewrite
    # it with nothing in it, destroying every other instance's credentials. The
    # keyring-side cleanup in delete_credentials() runs first and is unaffected.
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


def store_refresh_token(
    instance: str,
    refresh: str,
    *,
    bearer_token: Optional[str] = None,
    no_keyring: bool = False,
) -> str:
    """Store the refresh token. Returns 'keyring' or 'file'.

    ``bearer_token``, when given, pairs this refresh token with the bearer it
    can rotate: a fingerprint (never the bearer itself) is written alongside it
    in the same backend, so try_refresh() can prove the refresh token belongs to
    the currently stored bearer before spending it. Without that, a refresh
    token left behind by an old interactive session (a later ``login
    --token``/``--api-key`` never clears it) would rotate the wrong principal.
    Every production call site must supply it
    (tests/test_refresh_token_backend_derivation.py); only tests building a
    legacy unpaired token omit it.
    """
    if not no_keyring:
        try:
            keyring.set_password(SERVICE, _keyring_account_refresh(instance), refresh)
            if bearer_token is not None:
                keyring.set_password(
                    SERVICE,
                    _keyring_account_refresh_fingerprint(instance),
                    _fingerprint_bearer(bearer_token),
                )
            return "keyring"
        except KeyringError as exc:
            log.warning("keyring_unavailable_falling_back_to_file", error=str(exc))
    _set_credential_field(instance, "refresh_token", refresh)
    if bearer_token is not None:
        _set_credential_field(
            instance, "refresh_fingerprint", _fingerprint_bearer(bearer_token)
        )
    return "file"


# ---------- Load ----------

def _read_credentials_section_tolerant(instance: str) -> dict:
    """``_read_credentials_file()``'s section for ``instance``, or ``{}`` if
    the file is missing, has no section for this instance, or is corrupt.

    Read-with-fallback callers (the ``load_*`` functions,
    ``_detect_credential_backend``) treat a corrupt file as "nothing usable
    here" because a degraded read destroys nothing, and several sit on hot
    paths (``try_refresh()``, ``AppState.sdk()``) that must keep working via
    keyring when the file is broken. Write paths still propagate
    ``CredentialsFileCorrupt``, and ``ensure_credentials_file_readable()`` lets
    whoami/status surface it instead of reporting "not logged in."
    """
    try:
        return _read_credentials_file().get(instance, {})
    except CredentialsFileCorrupt:
        return {}


class KeyringCredentialUnreadable(Exception):
    """Raised by the strict credential readers (``load_bearer_token_strict``,
    ``load_api_key_strict``) when the OS keyring refuses a read for an account
    (locked, backend down, permission denied), as opposed to a clean read that
    found nothing (``None``).

    ``load_bearer_token()``/``load_api_key()`` swallow it for callers that do
    not need to tell the two apart.
    """

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind} credential unreadable: {detail}")
        self.kind = kind
        self.detail = detail


def load_bearer_token_strict(instance: str) -> Optional[BearerToken]:
    """Like ``load_bearer_token()``, but raises ``KeyringCredentialUnreadable``
    instead of swallowing a keyring read failure to ``None``.

    AppState.sdk() must tell "the marked-active bearer account is unreadable"
    apart from "there is no bearer credential"; conflating them would let it
    fall through to a competing, possibly stale api_key credential. The env
    token and a file-backed value short-circuit before the keyring, so only the
    keyring leg can raise.
    """
    env_token = _config.get_token_from_env()
    if env_token:
        return BearerToken(env_token)
    data = _read_credentials_section_tolerant(instance)
    token = data.get("bearer_token")
    if token:
        return BearerToken(token)
    try:
        kr_token = keyring.get_password(SERVICE, _keyring_account_token(instance))
    except KeyringError as exc:
        raise KeyringCredentialUnreadable("bearer", str(exc)) from exc
    return BearerToken(kr_token) if kr_token else None


def load_api_key_strict(instance: str) -> Optional[ApiKey]:
    """Like ``load_api_key()``, but raises ``KeyringCredentialUnreadable``
    instead of swallowing a keyring read failure to ``None`` -- see
    ``load_bearer_token_strict()``'s docstring."""
    data = _read_credentials_section_tolerant(instance)
    key = data.get("api_key")
    if key:
        return ApiKey(key)
    try:
        kr_key = keyring.get_password(SERVICE, _keyring_account_api_key(instance))
    except KeyringError as exc:
        raise KeyringCredentialUnreadable("api_key", str(exc)) from exc
    return ApiKey(kr_key) if kr_key else None


def load_bearer_token(instance: str) -> Optional[BearerToken]:
    """Return the active bearer token per the storage precedence.

    Tolerant: a keyring read failure degrades to "not found" for callers that
    do not need to tell the two apart. AppState.sdk()'s marker-authoritative
    branch uses ``load_bearer_token_strict()`` to avoid that.
    """
    try:
        return load_bearer_token_strict(instance)
    except KeyringCredentialUnreadable:
        return None


def load_api_key(instance: str) -> Optional[ApiKey]:
    """Return the active API key per the storage precedence. Tolerant --
    see ``load_bearer_token()``'s docstring."""
    try:
        return load_api_key_strict(instance)
    except KeyringCredentialUnreadable:
        return None


def load_refresh_token_strict(instance: str) -> Optional[str]:
    """Three-state strict refresh-token read: the stored value, ``None`` if
    genuinely absent, or ``KeyringCredentialUnreadable("refresh", ...)`` if the
    keyring account could not be read. The pairing check in try_refresh() must
    tell "no refresh token" apart from "can't tell right now".
    """
    data = _read_credentials_section_tolerant(instance)
    refresh = data.get("refresh_token")
    if refresh:
        return refresh
    try:
        return keyring.get_password(SERVICE, _keyring_account_refresh(instance))
    except KeyringError as exc:
        raise KeyringCredentialUnreadable("refresh", str(exc)) from exc


def _load_stored_bearer_value(instance: str) -> Optional[str]:
    """Like ``load_bearer_token_strict()``, but never consults GEOLENS_TOKEN.

    try_refresh() compares a refresh token's pairing fingerprint against the
    stored bearer, the one it can rotate, not an env override.
    ``call_sdk_with_reauth`` already gates try_refresh() on
    ``credential_provenance == "stored-bearer"``, so this should not diverge
    from ``load_bearer_token()`` in practice.

    Strict: a keyring read failure raises ``KeyringCredentialUnreadable``
    instead of looking like "no bearer stored", which would make a possibly
    valid pairing look stale and trigger try_refresh()'s destructive
    discard-and-warn path.
    """
    data = _read_credentials_section_tolerant(instance)
    token = data.get("bearer_token")
    if token:
        return token
    try:
        return keyring.get_password(SERVICE, _keyring_account_token(instance))
    except KeyringError as exc:
        raise KeyringCredentialUnreadable("bearer", str(exc)) from exc


def _load_refresh_fingerprint(instance: str) -> Optional[str]:
    """The pairing fingerprint stored alongside the refresh token, or ``None``
    if there isn't one (a legacy profile with no pairing).

    Strict, for the same reason as ``_load_stored_bearer_value()``: a keyring
    read failure raises ``KeyringCredentialUnreadable("refresh_fingerprint",
    ...)`` rather than meaning "no fingerprint".
    """
    data = _read_credentials_section_tolerant(instance)
    fp = data.get("refresh_fingerprint")
    if fp:
        return fp
    try:
        return keyring.get_password(
            SERVICE, _keyring_account_refresh_fingerprint(instance)
        )
    except KeyringError as exc:
        raise KeyringCredentialUnreadable("refresh_fingerprint", str(exc)) from exc


def _rewrite_refresh_fingerprint(
    instance: str, bearer_token: str, *, no_keyring: bool
) -> None:
    """Rewrite only the pairing fingerprint to match ``bearer_token``, leaving
    the refresh token value alone.

    Used by try_refresh() when a rotation renews the access token but the
    server issues no new refresh token: the retained refresh token's
    fingerprint must follow the new bearer, or the next attempt would find it
    mismatched and discard a valid refresh token. Used whenever the bearer
    stayed in the backend it was in; rewriting the unchanged refresh secret
    there would ask a second account for a needless write, and a keyring that
    refused it (with no usable file fallback) would lose a rotation that
    otherwise completes. Only a backend-moved rotation rewrites the whole pair;
    see try_refresh().
    """
    fingerprint = _fingerprint_bearer(bearer_token)
    if not no_keyring:
        try:
            keyring.set_password(
                SERVICE, _keyring_account_refresh_fingerprint(instance), fingerprint
            )
            return
        except KeyringError as exc:
            log.warning("keyring_unavailable_falling_back_to_file", error=str(exc))
    _set_credential_field(instance, "refresh_fingerprint", fingerprint)


def _delete_keyring_refresh_entries(instance: str) -> None:
    """Best-effort delete of the refresh token and its pairing fingerprint from
    the keyring only, leaving the file side alone. Never raises (see
    ``_discard_unpaired_refresh_token()`` and
    tests/test_best_effort_helpers_never_raise.py).

    try_refresh() uses it on its own when a rotation falls back from the
    keyring to credentials.toml: the pair is rewritten to the file and only the
    superseded keyring copy has to go.
    """
    for account_fn in (_keyring_account_refresh, _keyring_account_refresh_fingerprint):
        try:
            keyring.delete_password(SERVICE, account_fn(instance))
        except (KeyringError, OSError):
            pass


def _discard_unpaired_refresh_token(instance: str) -> None:
    """Best-effort delete of the refresh token and its fingerprint from both
    backends.

    Called from try_refresh() when a stored refresh token cannot be proven to
    belong to the stored bearer (no fingerprint, a mismatch, or no bearer).
    Never raises: it runs on a path already reporting "no refresh available",
    and try_refresh() has no rollback net, so even an unwritable
    credentials.toml must not turn whoami/status into a storage traceback
    instead of the normal auth error. Every step catches KeyringError and
    OSError, logs once and continues
    (tests/test_best_effort_helpers_never_raise.py).
    """
    _delete_keyring_refresh_entries(instance)
    try:
        data = _read_credentials_file()
        section = data.get(instance)
        if not section:
            return
        changed = False
        for field in ("refresh_token", "refresh_fingerprint"):
            if section.pop(field, None) is not None:
                changed = True
        if not changed:
            return
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
    except CredentialsFileCorrupt:
        return
    except OSError as exc:
        log.warning("stale_refresh_token_file_cleanup_failed", error=str(exc))


#: Field name for the "active credential kind" marker in credentials.toml; see
#: load_active_credential_kind().
_ACTIVE_KIND_FIELD = "active_kind"


def _read_active_kind_marker(instance: str) -> Optional[str]:
    """Strict marker reader: ``"bearer"``/``"api_key"`` for a valid marker,
    ``None`` when the field is absent from a readable file, and
    ``KeyringCredentialUnreadable("marker", ...)`` when the file cannot be
    read or parsed or the field holds any other value.

    ``load_active_credential_kind()`` collapses all three failures to the
    ``None`` of a never-set marker. AppState.sdk() treats a present marker as
    authoritative, so an unreadable file must not look like "no marker", or
    resolution would fall back to bearer-first precedence and pick exactly the
    stale credential the marker exists to shadow.
    ``resolve_active_credential()`` is the one caller that needs the
    distinction.
    """
    try:
        data = _read_credentials_file().get(instance, {})
    except CredentialsFileCorrupt as exc:
        # Name the path: a corrupt-file failure is more actionable that way,
        # matching the whoami/status message.
        raise KeyringCredentialUnreadable(
            "marker", f"{exc.path} is corrupt: {exc.detail}"
        ) from exc
    if _ACTIVE_KIND_FIELD not in data:
        return None
    kind = data[_ACTIVE_KIND_FIELD]
    if kind not in ("bearer", "api_key"):
        raise KeyringCredentialUnreadable(
            "marker", f"unrecognized active_kind value: {kind!r}"
        )
    return kind


def load_active_credential_kind(instance: str) -> Optional[str]:
    """Return ``"bearer"`` or ``"api_key"``, whichever kind ``login`` most
    recently stored for ``instance``, or ``None`` if never set or unreadable.

    A stale competing credential left in either backend after a swap could
    outrank the one just stored, since ``load_bearer_token``/``load_api_key``
    are independent reads and bearer wins, and cleanup of the other backend can
    only be best-effort (no shared transaction). ``replace_credentials()``
    therefore writes this marker unconditionally in the same file section
    regardless of where the secret landed, so it survives a ``--no-keyring``
    login or an unavailable keyring. ``AppState.sdk()`` consults it first, which
    makes failed cleanup a matter of tidiness, not correctness.

    Tolerant wrapper around ``_read_active_kind_marker()``, for callers that do
    not need the strict distinction (try_refresh()'s "does the marker already
    say bearer" write-skip check is narrower than credential selection).
    """
    try:
        return _read_active_kind_marker(instance)
    except KeyringCredentialUnreadable:
        return None


class ActiveCredentialMissing(Exception):
    """Raised by ``resolve_active_credential()`` when the active_kind marker
    names a kind but a clean read confirms nothing is stored for it: "not
    logged in", not anonymous, and not a fallback to whatever else exists."""

    def __init__(self, instance: str, kind: str) -> None:
        super().__init__(f"no {kind} credential found for {instance}")
        self.instance = instance
        self.kind = kind


class CredentialAmbiguous(Exception):
    """Raised by ``resolve_active_credential()`` when there is no active_kind
    marker and more than one credential kind is genuinely present. Guessing
    (bearer-first) could authenticate as the wrong principal, since an API-key
    login can leave a stale bearer in the keyring (cleanup is best-effort), and
    nothing records which is current."""

    def __init__(self, instance: str) -> None:
        super().__init__(
            f"multiple credentials found for {instance} with no active_kind "
            "marker to disambiguate"
        )
        self.instance = instance


@dataclass(frozen=True)
class ResolvedCredential:
    """The output of ``resolve_active_credential()``: which credential
    (if any) is active for an instance, and where it came from."""

    kind: str  # "bearer" | "api_key" | "anonymous"
    value: Optional[str]
    provenance: str  # "env" | "stored-bearer" | "stored-api-key" | "anonymous"


def resolve_active_credential(instance: str) -> ResolvedCredential:
    """The single precedence implementation for "which credential is active
    for ``instance``", covering marker precedence, marker-authoritative rules
    and ambiguity/unreadable handling.

    ``AppState.sdk()`` (main.py) is the only caller; every other command
    reaches it through ``state.sdk()``. ``call_sdk_with_reauth`` and
    ``make_client`` consume its output, and ``try_refresh()`` asks the narrower
    tolerant ``load_active_credential_kind()`` question, so a corrupt file there
    cannot block a rotation that already succeeded. ``login`` writes a
    credential and ``logout`` deletes all of them without resolving one.

    Raises:
        KeyringCredentialUnreadable: the marker, or the kind it names, could
            not be read (corrupt credentials.toml, keyring read failure, or an
            unrecognized marker value). Never treated as absent.
        ActiveCredentialMissing: the marker names a kind but a clean read
            confirms nothing is stored for it.
        CredentialAmbiguous: no marker, and more than one kind is present.
    """
    env_token = _config.get_token_from_env()
    if env_token:
        return ResolvedCredential("bearer", env_token, "env")

    marker = _read_active_kind_marker(instance)  # may raise KeyringCredentialUnreadable

    if marker == "api_key":
        api_key = load_api_key_strict(instance)
        if api_key:
            return ResolvedCredential("api_key", api_key.value, "stored-api-key")
        raise ActiveCredentialMissing(instance, "api_key")
    if marker == "bearer":
        bearer = load_bearer_token_strict(instance)
        if bearer:
            return ResolvedCredential("bearer", bearer.value, "stored-bearer")
        raise ActiveCredentialMissing(instance, "bearer")

    # No marker: legacy bearer-over-api_key precedence, but only when at most
    # one kind is present. The tolerant readers are used because there is no
    # authoritative signal to be strict about, so a transiently unreadable
    # keyring account degrades to the readable kind.
    bearer = load_bearer_token(instance)
    api_key = load_api_key(instance)
    if bearer and api_key:
        raise CredentialAmbiguous(instance)
    if bearer:
        return ResolvedCredential("bearer", bearer.value, "stored-bearer")
    if api_key:
        return ResolvedCredential("api_key", api_key.value, "stored-api-key")
    return ResolvedCredential("anonymous", None, "anonymous")


def ensure_credentials_file_readable() -> None:
    """Raise ``CredentialsFileCorrupt`` if credentials.toml exists but cannot be
    read or parsed; a no-op otherwise.

    Credential lookups tolerate a corrupt file and fall back to the keyring, but
    a read-only command whose job is to report on the stored credential
    (``whoami``, ``status``) must not launder a corrupt file into a misleading
    "not logged in". Call this first, before resolving any credential.
    """
    _read_credentials_file()


# ---------- Delete ----------

def delete_credentials(instance: str) -> None:
    """Remove every member of the credential set (_CREDENTIAL_SET:
    bearer, refresh, api_key, and the refresh token's pairing
    fingerprint) from the keyring, AND the credentials.toml section.

    Missing entries are silently ignored — logout is idempotent.
    """
    for _name, account_fn, _field in _CREDENTIAL_SET:
        try:
            keyring.delete_password(SERVICE, account_fn(instance))
        except (KeyringError, OSError):
            # PasswordDeleteError and missing entries are ignored: logout is
            # idempotent.
            pass
    _clear_credential_section(instance)


# ---------- Atomic credential swap (login) ----------

_FIELD_BY_KIND = {"bearer": "bearer_token", "api_key": "api_key"}


class _Unknown:
    """Sentinel: the snapshot could not read this keyring account at all, as
    distinct from ``None`` ("confirmed absent").

    Recording a read failure as ``None`` would make ``_restore_credentials``
    call ``delete_password()`` on an account that held a real credential the
    snapshot merely failed to see. Restore never deletes on this sentinel, only
    on a confirmed absence.
    """

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "<unknown>"


_UNKNOWN = _Unknown()

_KeyringValue = Union[str, None, _Unknown]


@dataclass(frozen=True)
class _CredentialSnapshot:
    """Raw values read directly from each backend, deliberately not
    ``load_bearer_token()`` et al., which apply GEOLENS_TOKEN precedence; a
    restore must reproduce what storage held.

    Each keyring field is the stored string, ``None`` (confirmed absent), or
    ``_UNKNOWN`` (the read failed). ``keyring_refresh_fingerprint`` is
    snapshotted too: restoring the old bearer+refresh pair without it would make
    the next 401 discard the valid refresh token as unpaired.
    """

    keyring_bearer: _KeyringValue
    keyring_api_key: _KeyringValue
    keyring_refresh: _KeyringValue
    keyring_refresh_fingerprint: _KeyringValue
    file_section: dict


def _snapshot_credentials(instance: str) -> _CredentialSnapshot:
    def _kr(account: str) -> _KeyringValue:
        try:
            return keyring.get_password(SERVICE, account)
        except KeyringError:
            return _UNKNOWN

    # Iterates _CREDENTIAL_SET rather than hand-listing accounts.
    bearer, api_key, refresh, fingerprint = (
        _kr(account_fn(instance)) for _name, account_fn, _field in _CREDENTIAL_SET
    )
    return _CredentialSnapshot(
        keyring_bearer=bearer,
        keyring_api_key=api_key,
        keyring_refresh=refresh,
        keyring_refresh_fingerprint=fingerprint,
        # Tolerant of a corrupt file: _restore_credentials re-reads the file and
        # hits the same CredentialsFileCorrupt, which it logs and skips, so
        # nothing treats this snapshot value as grounds for an overwrite.
        file_section=dict(_read_credentials_section_tolerant(instance)),
    )


def _restore_credentials(instance: str, snapshot: _CredentialSnapshot) -> None:
    """Best-effort restore to exactly the pre-swap state.

    Only called when the delete-competing-kinds step of
    ``replace_credentials`` fails partway through — there is nothing
    further to fall back to here, so each write is independently
    swallowed-and-logged rather than raised.
    """
    # Iterates _CREDENTIAL_SET, including the fingerprint.
    values_by_name = {
        "bearer": snapshot.keyring_bearer,
        "api_key": snapshot.keyring_api_key,
        "refresh": snapshot.keyring_refresh,
        "refresh_fingerprint": snapshot.keyring_refresh_fingerprint,
    }
    for name, account_fn, _field in _CREDENTIAL_SET:
        value = values_by_name[name]
        if value is _UNKNOWN:
            # Never learned whether this account held a credential (see
            # _Unknown); neither deleting nor overwriting is safe.
            continue
        account = account_fn(instance)
        try:
            if value is None:
                keyring.delete_password(SERVICE, account)
            else:
                keyring.set_password(SERVICE, account, value)
        except (KeyringError, OSError) as exc:
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
    except (CredentialsFileCorrupt, OSError) as exc:
        log.warning("credential_restore_failed", account="file", error=str(exc))


def _delete_stale_credentials(
    instance: str, *, keep: str, keep_backend: str, snapshot: _CredentialSnapshot
) -> None:
    """Delete every stored credential for ``instance`` except ``keep``'s value
    in the backend it was just stored to (``keep_backend``).

    Two cleanups happen in one pass: every other credential kind is deleted from
    both backends, and ``keep`` itself is deleted from the backend it was not
    stored to. ``store_bearer_token``/``store_api_key`` write one backend per
    call, and a stale same-kind value in the other would win because
    ``load_bearer_token``/``load_api_key`` prefer the file over keyring.

    Keyring deletes are not blanket-swallowed: ``PasswordDeleteError`` covers
    both "no such entry" (fine, the cleanup is idempotent) and a real backend
    refusal (locked keychain, permission denied), and the two cannot be told
    apart from the exception. Existence is checked first, so a delete that is
    attempted was for an entry that existed and its failure is real and
    propagates. The credentials.toml write below may raise for the same reason:
    ``replace_credentials`` restores its snapshot rather than leave either
    backend half-cleaned.

    An unreadable keyring during the existence check is not "no such entry":
    skipping it would leave a stale credential unseen. Because the store falls
    back to the file on a ``KeyringError``, a keyring locked at store time can
    still hold an old credential that later outranks the file-backed new one.
    So an unreadable backend is a failed swap, and ``login`` reports it.

    That is fatal only when ``keep_backend == "keyring"``, the one case where
    the keyring is demonstrably reachable. With ``login --no-keyring`` or a
    headless box (``keep_backend == "file"``) an unreadable keyring is tolerated
    like a missing entry, or the automatic file fallback would be defeated.

    ``snapshot`` (the pre-swap read of this same ``replace_credentials()`` call)
    gates every keyring delete: an account whose snapshot is ``_UNKNOWN`` is
    never deleted, even if the keyring became readable since. If a later step
    failed, ``_restore_credentials`` skips that account for the same reason and
    could not put it back, so the failed login would irreversibly remove a
    credential nothing ever read. Skipping costs nothing, since the active_kind
    marker already makes a stale entry harmless and this cleanup is only
    tidiness.
    """
    # Iterates _CREDENTIAL_SET rather than special-casing members
    # (test_credential_set_structural.py). The fingerprint is treated like
    # "refresh", which it travels with.
    snapshot_by_name = {
        "bearer": snapshot.keyring_bearer,
        "api_key": snapshot.keyring_api_key,
        "refresh": snapshot.keyring_refresh,
        "refresh_fingerprint": snapshot.keyring_refresh_fingerprint,
    }
    for name, account_fn, _field in _CREDENTIAL_SET:
        if name == keep and keep_backend == "keyring":
            continue
        if snapshot_by_name[name] is _UNKNOWN:
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
            # keep_backend == "file": --no-keyring, or store_* already fell
            # back moments ago. The keyring is not part of this operation, and
            # failing would make a headless box with no keyring unable to log in.
            continue
        if exists:
            keyring.delete_password(SERVICE, account)

    # Only the READ is best-effort: a pre-existing corrupt file is not
    # something this login broke, so it is logged and skipped. The WRITE below
    # is deliberately not swallowed: it runs inside replace_credentials()'s
    # rollback-protected block, so a real write failure propagates and triggers
    # _restore_credentials(). _discard_unpaired_refresh_token() differs because
    # try_refresh() has no rollback net and must never let a write failure
    # escape.
    try:
        data = _read_credentials_file()
    except CredentialsFileCorrupt as exc:
        log.warning(
            "stale_credential_file_cleanup_skipped_corrupt_file",
            path=str(exc.path),
            error=exc.detail,
        )
        return
    section = data.get(instance)
    if not section:
        return
    keep_field = _FIELD_BY_KIND.get(keep)
    for _name, _account_fn, field in _CREDENTIAL_SET:
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
    instance: str,
    kind: str,
    value: str,
    *,
    no_keyring: bool = False,
    refresh_token: Optional[str] = None,
) -> str:
    """Atomically swap the active credential for ``instance`` to ``kind``
    (``"bearer"`` or ``"api_key"``). Returns ``'keyring'`` or ``'file'``, where
    the new credential landed.

    The new credential is stored first: deleting the old one first would log
    the user out if the storage write then failed. If the store raises, nothing
    has been touched and the exception propagates. If the cleanup afterward
    fails partway (keyring and credentials.toml share no transaction, so this is
    the one non-atomic step), the pre-swap snapshot is restored before
    re-raising, so the net effect is "nothing changed".

    ``refresh_token``, when given, is persisted inside this same
    rollback-protected transaction. A separate ``store_refresh_token()`` call
    afterward could fail after the new access token was committed and the prior
    refresh credential deleted, leaving a half-replaced session with nothing to
    roll back to. It is written after ``_delete_stale_credentials``, which
    deletes any existing refresh entry.

    Cleanup deletes the competing kinds and ``kind``'s own value from the
    backend it did not land in (see ``_delete_stale_credentials``), so a bearer
    left in credentials.toml by an earlier ``--no-keyring`` login does not
    outrank a replacement stored in the keyring. Cleanup can only be
    best-effort, so this also writes the "active credential kind" marker (see
    ``load_active_credential_kind``) unconditionally into the same file section
    the snapshot covers. Readers consult it first, which makes cleanup tidiness,
    not correctness.

    A corrupt credentials.toml refuses every login up front, before any secret
    is stored. The file holds both credentials and the marker, so while it
    cannot be parsed neither the competing credential's state nor the marker can
    be established, and any carve-out would rest on unknowable information.
    Read-only commands resolve through ``resolve_active_credential()``, so a
    corrupt file stops them too unless ``GEOLENS_TOKEN`` is set; ``logout`` also
    refuses. ``try_refresh()``'s marker write stays non-fatal, since it
    refreshes an already-trusted session.
    """
    if kind not in ("bearer", "api_key"):
        raise ValueError(f"unknown credential kind: {kind!r}")

    # Refuse before anything else runs; see the docstring.
    ensure_credentials_file_readable()

    snapshot = _snapshot_credentials(instance)

    # An _UNKNOWN snapshot for the account about to be overwritten cannot be
    # left to rollback alone: get_password raising does not guarantee
    # set_password will, so the write could succeed and destroy the one value
    # _restore_credentials would need.
    #
    # Aborting would break the documented credentials.toml fallback (a plain
    # ``login --token`` on a headless box would need --no-keyring). Instead
    # the one store call takes the --no-keyring path and writes straight to the
    # file, so a write never lands in an account whose read just failed. The
    # active_kind marker still records the new kind, so the file credential
    # outranks any stale keyring entry that becomes readable later, and cleanup
    # of the other kinds stays best-effort (keep_backend == "file" here). The
    # call fails only if the file backend is itself unwritable, before anything
    # has been mutated.
    target_is_unknown = False
    if not no_keyring:
        target = snapshot.keyring_bearer if kind == "bearer" else snapshot.keyring_api_key
        target_is_unknown = target is _UNKNOWN

    store_no_keyring = no_keyring or target_is_unknown

    try:
        if kind == "bearer":
            backend = store_bearer_token(instance, value, no_keyring=store_no_keyring)
        else:
            backend = store_api_key(instance, value, no_keyring=store_no_keyring)
    except Exception as exc:
        if target_is_unknown:
            # The keyring was unreadable and the forced file write also failed
            # (e.g. a read-only or full config dir), so no backend can take the
            # credential. Re-raised as KeyringError so it reaches EXIT_NETWORK
            # through the handler for every other "credential store backend
            # unavailable" case.
            raise KeyringError(
                f"keyring unreadable for {instance}, and the fallback "
                f"credentials.toml write also failed: {exc}"
            ) from exc
        raise

    # The marker write must be inside the rollback-protected block. It lives in
    # the file section the snapshot captured, so a restore reverts it, but only
    # if a failure writing it triggers that restore. Outside the try, a failure
    # would skip _restore_credentials: a same-kind login would have already
    # overwritten the old keyring secret, and a kind switch would leave the old
    # marker pointing at a value that had changed backends. A corrupt
    # credentials.toml is refused up front, so a failure here is an ordinary
    # write failure that rolls back the whole swap.
    try:
        _set_credential_field(instance, _ACTIVE_KIND_FIELD, kind)
        _delete_stale_credentials(
            instance, keep=kind, keep_backend=backend, snapshot=snapshot
        )
        if refresh_token:
            # Must match the backend the access token actually landed in, not
            # the caller's no_keyring. If the tokens split across backends,
            # try_refresh() detects the backend from the refresh token's
            # location and rewrites both there, while load_bearer_token()
            # keeps preferring the stale file-backed bearer, so every 401
            # refreshes again and never converges.
            #
            # Key this off `backend` (the store call's actual outcome), not
            # store_no_keyring (the intent from snapshot readability): they
            # diverge when get_password succeeded at snapshot time but
            # set_password then fails and store_* falls back to the file.
            store_refresh_token(
                instance,
                refresh_token,
                bearer_token=value,
                no_keyring=(backend != "keyring"),
            )
    except Exception:
        _restore_credentials(instance, snapshot)
        raise

    return backend


# ---------- Refresh ----------

def _detect_credential_backend(instance: str) -> bool:
    """Return True (no_keyring=True / file backend) if the refresh token was
    read from credentials.toml, False (keyring backend) otherwise.

    The file is checked first because load_refresh_token_strict uses the same
    file-before-keyring precedence.

    Tolerant of a corrupt file, like load_refresh_token_strict(): this is
    try_refresh()'s first step, and assuming "not file-backed" is right when the
    refresh token lives in the keyring and the file is merely broken.
    """
    file_data = _read_credentials_section_tolerant(instance)
    return "refresh_token" in file_data


def try_refresh(instance: str) -> Optional[str]:
    """Attempt a single refresh; return new access token or None on failure.

    This is called once on a 401. If it fails, the caller prints "Session
    expired" and exits with EXIT_AUTH (3).

    Rotated tokens are written back to the same backend that held the original
    credential (file vs keyring) so a file-backed credential is not shadowed by
    a newly keyring-written token.

    "None on failure, never raise" covers the HTTP call, response parsing and
    persisting a successful rotation. store_bearer_token()/store_refresh_token()
    propagate when both the keyring and the credentials.toml fallback fail, and
    the only caller (call_sdk_with_reauth) does not catch storage exceptions, so
    the command would die with an unrelated traceback after the server had
    already rotated the refresh token, leaving the old one invalid and the new
    one unrecorded. The bearer and refresh-token writes are therefore wrapped in
    one block that warns once and returns None on any failure. The active_kind
    marker write is handled separately and non-fatally: a marker-only failure
    must not discard a rotation whose credentials landed.

    A stored refresh token is not proof it belongs to the stored bearer:
    ``credential_provenance == "stored-bearer"`` (the gate
    ``call_sdk_with_reauth`` applies) only proves both are stored. A refresh
    token surviving a later ``login --token``/``--api-key`` would rotate the old
    session and retry as a different principal. The refresh token is therefore
    spent only when its pairing fingerprint (``_fingerprint_bearer()``) matches
    the stored bearer; on a mismatch, or a legacy profile with no fingerprint,
    it is treated as absent, discarded (``_discard_unpaired_refresh_token()``)
    and this returns ``None``.

    The pairing check reads the refresh token, bearer and fingerprint strictly
    (present / confirmed absent / unreadable). A tolerant read would turn a
    transient KeyringError into an apparent absence and run the destructive
    discard on a possibly valid pairing. Unreadable on any of them aborts with
    one warning and ``None``, deleting nothing; only a confirmed absence or
    mismatch reaches the discard path.

    When the server issues no new refresh token and the bearer moved backends
    (a keyring write that fell back to the file), the refresh token and its
    fingerprint are written together through ``store_refresh_token()`` into the
    bearer's backend, and the superseded keyring copy is dropped after that
    write commits. A fingerprint-only rewrite would split the pair:
    ``_detect_credential_backend()`` looks for a refresh_token in the file, would
    answer "keyring", and the rotated bearer written there would be shadowed by
    the stale file bearer, so commands would refresh on every call. If the
    backend did not move, ``_rewrite_refresh_fingerprint()`` updates only the
    stale member, since rewriting the unchanged refresh secret could fail on a
    keyring that refuses that one account and lose an otherwise complete
    rotation.
    """
    try:
        refresh = load_refresh_token_strict(instance)
        if not refresh:
            return None
        stored_bearer = _load_stored_bearer_value(instance)
        fingerprint = _load_refresh_fingerprint(instance)
    except KeyringCredentialUnreadable as exc:
        # A read failure proves nothing; the pairing may be valid. Never
        # delete on an unknown, just decline to refresh this time.
        log.warning(
            "refresh_pairing_check_skipped_unreadable",
            member=exc.kind,
            error=exc.detail,
        )
        return None

    if (
        stored_bearer is None
        or fingerprint is None
        or fingerprint != _fingerprint_bearer(stored_bearer)
    ):
        _discard_unpaired_refresh_token(instance)
        log.warning("stale_refresh_token_discarded_unpaired_with_stored_bearer")
        return None

    # Detect the backend BEFORE the HTTP call so we know where to write back.
    no_keyring = _detect_credential_backend(instance)

    from geolens.api.auth import refresh_auth_refresh_post
    from geolens.models.refresh_request import RefreshRequest

    from ._sdk_helpers import make_client

    try:
        # make_client() bounds the request timeout so a stalled refresh
        # endpoint cannot hang the command instead of failing the refresh.
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
    # store_bearer_token() can fall back to credentials.toml on its own even
    # when `no_keyring` (from where the old refresh token lived) said keyring.
    # The refresh write below keys off `backend`, the actual outcome, as
    # replace_credentials() does; using `no_keyring` would split the rotated
    # tokens across backends, and the expired file bearer would then shadow later
    # keyring bearer writes so commands loop on refresh.
    # Both writes can propagate (see the docstring), so they share one try:
    # they are one logical step, "persist the rotation". Never logs a token.
    try:
        backend = store_bearer_token(instance, new_access, no_keyring=no_keyring)
        # Only the keyring -> file fallback is a move; `no_keyring` already
        # means "the file, deliberately".
        backend_moved = not no_keyring and backend != "keyring"
        new_refresh = getattr(parsed, "refresh_token", None)
        if new_refresh:
            store_refresh_token(
                instance,
                new_refresh,
                bearer_token=new_access,
                no_keyring=(backend != "keyring"),
            )
        else:
            # The server renewed the access token without a new refresh token.
            # The existing one stays valid, but its fingerprint was computed
            # against the old bearer and must follow the new one, or the next
            # refresh would find a mismatch and discard it.
            #
            # A fingerprint-only rewrite is wrong once the bearer moved
            # backends: the pair would split across backends and the stale file
            # bearer would shadow the rotated one (see the docstring), so a
            # moved bearer takes the whole pair through store_refresh_token().
            # When it did not move, update only the fingerprint: rewriting an
            # unchanged secret could fail on a keyring that refuses that
            # account and turn a completable rotation into a failure.
            if backend_moved:
                store_refresh_token(
                    instance,
                    refresh,
                    bearer_token=new_access,
                    no_keyring=(backend != "keyring"),
                )
            else:
                _rewrite_refresh_fingerprint(
                    instance, new_access, no_keyring=(backend != "keyring")
                )
    except Exception as exc:
        log.warning(
            "refresh_rotated_but_not_stored",
            error=str(exc),
            hint=(
                "the server rotated this session but the new credentials "
                "could not be saved locally -- run `geolens login` again"
            ),
        )
        return None
    # The rotation asked for the keyring and landed in the file, so the refresh
    # token now also lives in the superseded keyring copy. The file copy wins
    # every read, but the leftover is a spendable credential for a session this
    # profile no longer tracks there. Dropped best-effort, after the file write
    # committed, and only on the keyring side.
    if backend_moved:
        _delete_keyring_refresh_entries(instance)
    # The marker write must be non-fatal: an unwritable credentials.toml must
    # not turn a rotation whose tokens already landed into a reported refresh
    # failure (EXIT_AUTH), since the marker only tie-breaks stale competing
    # credentials. It is skipped when it already reads "bearer" (try_refresh
    # only rotates a bearer session), and a failed write is logged, not raised.
    if load_active_credential_kind(instance) != "bearer":
        try:
            _set_credential_field(instance, _ACTIVE_KIND_FIELD, "bearer")
        except Exception as exc:
            log.warning(
                "active_kind_marker_write_failed_after_refresh", error=str(exc)
            )
    return new_access

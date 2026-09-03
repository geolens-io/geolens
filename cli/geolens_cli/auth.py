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

# fix(#1778 review round 24): structlog's UNCONFIGURED default is a
# PrintLogger that writes every log.*() call straight to stdout,
# regardless of level -- every log.warning() below used to land there,
# silently corrupting the one JSON document a --json command promises
# on stdout the moment one fired on a path that still ends in success
# (e.g. a keyring fallback during `login`, or the best-effort cleanup
# skip in _delete_stale_credentials below). Configuring the factory
# once, here, at import time, sends every call this module's logger
# ever makes to stderr instead -- closing the class for every current
# call site AND any future one, rather than requiring each new
# log.warning() to remember to route around the default. This mirrors
# _sdk_helpers.py's own stdlib `logging` choice (its lastResort handler
# is stderr-only by default) without having to rewrite every structured
# key=value call site here into stdlib logging's positional-args shape.
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
    """A short, non-reversible pairing tag for a bearer token -- fix
    (#1778 round 31). Never the token itself, never logged: proves a
    stored refresh token actually belongs to the bearer it would
    rotate, not just that both happen to be present in storage. sha256
    truncated to 16 hex chars is plenty for this -- it only ever needs
    to be compared against itself, never guessed."""
    # codeql[py/weak-sensitive-data-hashing] fix(#1778 round 32): comparison tag over a high-entropy bearer, not password storage; the digest is truncated, never reversible to the token, and never used to authenticate
    return hashlib.sha256(bearer_token.encode()).hexdigest()[:16]


# fix(#1778 round 32): the credential SET for an instance, defined
# ONCE as a tuple of (name, keyring-account-fn, file-field-name)
# triples. Round 31 added the refresh_fingerprint as a fourth member
# of this set, but delete_credentials()/_delete_stale_credentials()
# were updated by hand while _CredentialSnapshot/_restore_credentials
# were not -- a login rollback silently dropped it, leaving a restored
# bearer+refresh pair without the fingerprint that proves they belong
# together. Every operation that must treat the whole set uniformly
# (snapshot, restore, logout, stale-credential cleanup) now iterates
# THIS tuple instead of hand-listing its own subset, so a fifth member
# added here later cannot be forgotten in one of them the same way --
# enforced by test_credential_set_structural.py.
_CREDENTIAL_SET = (
    ("bearer", _keyring_account_token, "bearer_token"),
    ("api_key", _keyring_account_api_key, "api_key"),
    ("refresh", _keyring_account_refresh, "refresh_token"),
    ("refresh_fingerprint", _keyring_account_refresh_fingerprint, "refresh_fingerprint"),
)


class CredentialsFileCorrupt(Exception):
    """Raised by ``_read_credentials_file()`` when credentials.toml
    exists but is not valid TOML.

    fix(#1778 review round 22): the file previously degraded a parse
    failure straight to ``{}`` -- indistinguishable from "no file at
    all." A writer building on that empty dict (e.g. the active_kind
    marker write after a keyring-backed login) would then overwrite
    the ACTUAL corrupt file with a fresh one holding only the CURRENT
    instance's data, silently destroying every OTHER instance's
    file-backed credentials that happened to be sitting in the
    unparseable file. Every write path must now be able to tell "empty"
    apart from "corrupt" and refuse to touch the file in the latter
    case; every read-with-fallback path (load_bearer_token and
    friends, the snapshot/restore machinery, try_refresh's backend
    detection) still degrades this to "nothing usable here, try the
    other backend" internally, so an unrelated corrupt file cannot
    break flows that do not actually need to write it. See each
    catch site's own comment for which behavior applies where.
    """

    def __init__(self, path: Path, detail: str) -> None:
        super().__init__(f"credentials file at {path} is corrupt: {detail}")
        self.path = path
        self.detail = detail


def _read_credentials_file() -> dict:
    path = _config.credentials_path()
    if not path.is_file():
        return {}
    # fix(#1778 round 30): a PermissionError (or any other OSError) on
    # the read() itself used to propagate straight past every caller
    # here uncaught -- unlike a TOMLDecodeError, which every caller
    # already handles via CredentialsFileCorrupt. There is no
    # meaningful difference between "can't parse this file" and "can't
    # even read this file" from any caller's point of view: both mean
    # the file cannot be trusted, and both must be reported the same
    # way rather than one of them crashing.
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
    # fix(#1778 review round 22): _read_credentials_file() propagates
    # CredentialsFileCorrupt uncaught here too -- this is the SAME
    # read-modify-write shape as _clear_credential_section, used both
    # for the primary credential's file FALLBACK (store_bearer_token/
    # store_api_key/store_refresh_token when the keyring is unusable or
    # --no-keyring) and for the active_kind marker write. Refusing to
    # merge new data into an unparseable file (rather than starting
    # from an empty dict and silently discarding whatever was actually
    # in there) is the same correctness requirement either way. Callers
    # for whom this write is genuinely non-fatal -- replace_credentials
    # ()'s marker write, try_refresh()'s -- catch CredentialsFileCorrupt
    # at THEIR call site instead of here, since only they know whether
    # the primary credential already landed safely elsewhere.
    data = _read_credentials_file()
    data.setdefault(instance, {})[field] = value
    _write_credentials_file(data)


def _clear_credential_section(instance: str) -> None:
    # fix(#1778 review round 22): _read_credentials_file() propagates
    # CredentialsFileCorrupt uncaught here, deliberately -- logout's
    # whole job is a read-modify-write of this file (drop this
    # instance's section, rewrite the rest), and there is no safe
    # interpretation of "modify" when the read itself failed. Refusing
    # (the exception reaches delete_credentials()'s caller, main.py's
    # logout command) is correct: the alternative, treating unreadable
    # as empty, would rewrite the file with NOTHING in it, destroying
    # every other instance's stored credentials the same way an
    # unconditional marker write would have. The keyring-side cleanup
    # in delete_credentials() runs BEFORE this and is unaffected.
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

    fix(#1778 round 31): ``bearer_token``, when given, pairs this
    refresh token with the bearer it can rotate -- a fingerprint
    (never the bearer itself) is written alongside it, in the SAME
    backend, so try_refresh() can later prove the refresh token it is
    about to spend actually belongs to the CURRENTLY stored bearer
    before using it (see try_refresh()'s own docstring for the finding
    this closes: an old interactive session's refresh token, left
    behind by a later ``login --token``/``--api-key`` that never
    cleared it, otherwise proves nothing about which principal it
    would rotate). Every PRODUCTION call site in this package must
    supply it -- enforced structurally by
    tests/test_refresh_token_backend_derivation.py. Omitted only by
    tests deliberately constructing a legacy/unpaired refresh token.
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
    """``_read_credentials_file()``'s section for ``instance``, or
    ``{}`` if the file is missing, has no section for this instance,
    OR is corrupt.

    fix(#1778 review round 22): every READ-with-fallback caller below
    (the ``load_*`` functions, ``_detect_credential_backend``) needs to
    treat a corrupt file as "nothing usable here, fall back to the
    other backend" rather than raise -- unlike a WRITE path, a read
    that degrades gracefully cannot destroy anything, and several of
    these are on hot paths (``try_refresh()``'s very first call,
    ``AppState.sdk()`` for every authenticated command) that must keep
    working via keyring even when the file is unrelated-and-broken.
    Corruption is NOT silently invisible system-wide, though: write
    paths (``_set_credential_field``, ``_clear_credential_section``)
    still propagate ``CredentialsFileCorrupt`` and refuse to touch the
    file, and ``ensure_credentials_file_readable()`` lets a read-only
    command (whoami/status) surface the error explicitly instead of
    silently reporting "not logged in."
    """
    try:
        return _read_credentials_file().get(instance, {})
    except CredentialsFileCorrupt:
        return {}


class KeyringCredentialUnreadable(Exception):
    """Raised by the STRICT credential readers (``load_bearer_token_strict``
    /``load_api_key_strict``) when the OS keyring itself
    refuses a read for a specific account (locked, backend down,
    permission denied, ...) -- distinct from a clean read that simply
    found nothing (a confirmed-absent credential, returned as
    ``None``, same as always).

    fix(#1778 review round 27): ``load_bearer_token()``/``load_api_key()``
    (below) swallow exactly this exception to preserve their existing
    tolerant contract for every caller that does not need to tell the
    two apart -- see their own docstrings.
    """

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind} credential unreadable: {detail}")
        self.kind = kind
        self.detail = detail


def load_bearer_token_strict(instance: str) -> Optional[BearerToken]:
    """Like ``load_bearer_token()``, but raises ``KeyringCredentialUnreadable``
    instead of swallowing a keyring read failure to ``None``.

    fix(#1778 review round 27): AppState.sdk() needs to tell "the
    marked-active bearer account is unreadable right now" apart from
    "there is genuinely no bearer credential" -- conflating the two
    (the OLD, and still current, behavior of load_bearer_token() itself)
    let it silently fall through to a competing, possibly-stale api_key
    credential the round-14/23/25 _UNKNOWN cleanup gate deliberately
    left in place. GEOLENS_TOKEN and a file-backed value both
    short-circuit before ever touching the keyring here, exactly as
    load_bearer_token() does -- only the keyring leg can raise.
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
    """Return the active bearer token per the D-35 precedence.

    Tolerant: a keyring read failure degrades to "not found," same as
    every call site here relied on before round 27. AppState.sdk()'s
    marker-authoritative branch uses ``load_bearer_token_strict()``
    instead, specifically to NOT tolerate this.
    """
    try:
        return load_bearer_token_strict(instance)
    except KeyringCredentialUnreadable:
        return None


def load_api_key(instance: str) -> Optional[ApiKey]:
    """Return the active API key per the D-35 precedence. Tolerant --
    see ``load_bearer_token()``'s docstring."""
    try:
        return load_api_key_strict(instance)
    except KeyringCredentialUnreadable:
        return None


def load_refresh_token(instance: str) -> Optional[str]:
    """Tolerant: a keyring read failure degrades to "not found." See
    ``load_refresh_token_strict()`` for the pairing check's own
    three-state read, which must NOT make this mistake."""
    try:
        return load_refresh_token_strict(instance)
    except KeyringCredentialUnreadable:
        return None


def load_refresh_token_strict(instance: str) -> Optional[str]:
    """Three-state STRICT refresh-token read (fix(#1778 round 32)):
    returns the stored value, ``None`` if genuinely absent, or raises
    ``KeyringCredentialUnreadable("refresh", ...)`` if the keyring
    account itself could not be read. The pairing check in
    try_refresh() must be able to tell "no refresh token here" apart
    from "can't tell right now" -- a transient/account-specific
    KeyringError collapsing to ``None`` looked identical to a
    confirmed absence, and there was nothing to discard or warn about
    either way.
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
    """Like ``load_bearer_token_strict()``, but NEVER consults
    GEOLENS_TOKEN.

    fix(#1778 round 31): try_refresh() must compare a refresh token's
    pairing fingerprint against the STORED bearer specifically -- the
    one it can actually rotate -- not whatever env override might
    (even transiently) be set. ``call_sdk_with_reauth`` already gates
    try_refresh() on ``credential_provenance == "stored-bearer"``
    (round 26), so this should never actually diverge from
    ``load_bearer_token()`` in practice; kept separate anyway so the
    pairing check can never be fooled by that precedence rule even in
    principle.

    fix(#1778 round 32): now STRICT -- raises
    ``KeyringCredentialUnreadable("bearer", ...)`` on a keyring read
    failure instead of collapsing it to ``None``. A transient or
    account-specific KeyringError here used to look identical to "no
    bearer stored," which made a POSSIBLY VALID pairing look stale and
    triggered the destructive discard-and-warn path in try_refresh()
    for a refresh token that may have been perfectly fine.
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
    """The pairing fingerprint stored alongside the refresh token, or
    ``None`` if there isn't one (a legacy profile predating round 31).

    fix(#1778 round 32): now STRICT -- raises
    ``KeyringCredentialUnreadable("refresh_fingerprint", ...)`` on a
    keyring read failure rather than treating it as "no fingerprint,"
    for the same reason as ``_load_stored_bearer_value()`` above.
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
    """Rewrite ONLY the pairing fingerprint to match ``bearer_token``,
    without touching the refresh token value itself.

    fix(#1778 round 31): used by try_refresh() when a rotation renews
    the access token but the server does NOT issue a new refresh
    token -- the existing (unrotated) refresh token still needs its
    fingerprint updated to the NEW bearer, or the next refresh attempt
    would find it "mismatched" against the very rotation this call
    just performed and discard a perfectly good, still-valid refresh
    token as if it were stale.
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


def _discard_unpaired_refresh_token(instance: str) -> None:
    """Best-effort delete of the refresh token AND its fingerprint from
    BOTH backends -- fix(#1778 round 31, fixed round 32).

    Called from try_refresh() when a stored refresh token cannot be
    PROVEN to belong to the currently stored bearer (no fingerprint at
    all -- a legacy profile; a fingerprint that doesn't match; or no
    bearer to compare against). Never raises: this runs on a path that
    is already reporting "no refresh available," and a delete failure
    here must not turn that into a crash (mirrors ``delete_credentials()``'s
    own best-effort, idempotent design).

    fix(#1778 round 32): the docstring already claimed "never raises,"
    but the file WRITE at the end was unguarded -- an unwritable
    credentials.toml (read-only, full) raised straight out of this
    function and past try_refresh(), which has no rollback net the way
    replace_credentials() does. whoami/status died with a storage
    traceback instead of the normal auth error this function exists to
    produce cleanly. Every step now explicitly catches KeyringError
    (covers PasswordDeleteError and the rest of that family) and
    OSError, logs once, and continues -- see
    tests/test_best_effort_helpers_never_raise.py.
    """
    for account_fn in (_keyring_account_refresh, _keyring_account_refresh_fingerprint):
        try:
            keyring.delete_password(SERVICE, account_fn(instance))
        except (KeyringError, OSError):
            pass
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


#: fix(#1778 review round 10): the field name for the "active credential
#: kind" marker in credentials.toml — see load_active_credential_kind().
_ACTIVE_KIND_FIELD = "active_kind"


def _read_active_kind_marker(instance: str) -> Optional[str]:
    """STRICT marker reader (fix(#1778 round 30)): returns
    ``"bearer"``/``"api_key"`` for a present, valid marker; ``None``
    when the field is genuinely absent (no file, or the field itself
    is missing) on an otherwise-readable file; raises
    ``KeyringCredentialUnreadable("marker", ...)`` when the file
    cannot be read/parsed OR the field holds a value that is neither
    ``"bearer"`` nor ``"api_key"``.

    Round 22-27's ``load_active_credential_kind()`` (below) collapsed
    ALL three of those failure shapes -- a corrupt file, a permission
    error, and a garbage value -- to the exact same ``None`` a
    genuinely-never-set marker returns. Round 27 fixed AppState.sdk()
    to treat a PRESENT marker as authoritative, but that fix only ever
    fires when the marker can be READ; if the file becomes unreadable
    after a kind switch, this function's old two-state contract made
    that failure indistinguishable from "no marker was ever written,"
    and resolution silently fell back to legacy bearer-first
    precedence -- exactly the stale credential a kind switch's marker
    exists to shadow. ``resolve_active_credential()`` below is the one
    caller that needs this distinction; every OTHER existing caller
    keeps using the tolerant ``load_active_credential_kind()`` and is
    unaffected.
    """
    try:
        data = _read_credentials_file().get(instance, {})
    except CredentialsFileCorrupt as exc:
        # fix(#1778 round 30): fold the path into the detail string --
        # KeyringCredentialUnreadable has no path attribute of its own
        # (a keyring account read failure has no meaningful path), but
        # a corrupt-FILE failure specifically is much more actionable
        # named, matching round 23's whoami/status message.
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
    """Return ``"bearer"`` or ``"api_key"`` — whichever kind ``login``
    most recently stored for ``instance`` — or ``None`` if never set OR
    unreadable right now.

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

    fix(#1778 round 30): TOLERANT wrapper around the strict
    ``_read_active_kind_marker()`` above -- unchanged in name and
    contract for every EXISTING caller (``try_refresh()``'s own
    "does the marker already say bearer" write-skip check is a
    narrower question than credential SELECTION and deliberately
    keeps this tolerant behavior). ``resolve_active_credential()``
    below is the one place that needs to tell "never set" apart from
    "can't tell right now."
    """
    try:
        return _read_active_kind_marker(instance)
    except KeyringCredentialUnreadable:
        return None


class ActiveCredentialMissing(Exception):
    """Raised by ``resolve_active_credential()`` when the active_kind
    marker names a kind but a clean, successful read confirms nothing
    is stored for it -- "not logged in," not anonymous, and NOT a
    fallback to whatever else might exist: the marker says a
    credential of exactly this kind should be there."""

    def __init__(self, instance: str, kind: str) -> None:
        super().__init__(f"no {kind} credential found for {instance}")
        self.instance = instance
        self.kind = kind


class CredentialAmbiguous(Exception):
    """Raised by ``resolve_active_credential()`` when there is no
    active_kind marker to consult AND more than one credential kind is
    genuinely present (both reads succeeded and both found a real
    value) -- round 30. Guessing here (the old bearer-first legacy
    precedence, unconditional) risks silently authenticating as the
    WRONG principal: an API-key login can leave a stale bearer behind
    in the keyring (round 14's best-effort, not correctness-bearing,
    cleanup), and there is no safe default once more than one real
    credential exists with nothing recording which is current."""

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
    """THE single precedence implementation for "which credential is
    active for ``instance``" (D-35). Consolidates round 10's marker
    precedence, round 23/25/27's marker-authoritative fixes, and round
    30's ambiguity/unreadable handling into one place, closing the
    state matrix rather than patching another individual cell.

    Enumerated call sites (fix(#1778 round 30) -- every consumer of a
    credential-selection decision routes through THIS function; call
    sites that consume its OUTPUT, or that ask a narrower question
    than "which credential is active," are listed for completeness
    but do not call it):

    - ``AppState.sdk()`` (main.py) -- the ONLY caller. Every other
      credential-consuming command (whoami, status, refresh, publish,
      analysis, export, manifest apply, ...) reaches this exclusively
      through ``state.sdk()``, so they inherit this resolver without
      calling it directly.
    - ``_sdk_helpers.call_sdk_with_reauth`` (the reauth helper) and
      ``_sdk_helpers.make_client`` (the SDK-client factory) consume
      this function's OUTPUT (``credential_kind``/``credential_
      provenance``, set by ``AppState.sdk()`` when it calls
      ``make_client()``) -- they do not re-implement precedence.
    - ``try_refresh()`` (auth.py) calls the TOLERANT ``load_active_
      credential_kind()`` for a narrower, different question --
      "does the marker already say bearer" (a write-skip
      optimization) -- not "which credential should this request use."
      It is not a precedence implementation and deliberately keeps
      the old graceful-degradation behavior: a corrupt file there
      must not block a token rotation that already succeeded.
    - ``login``/``logout`` (auth.py) do not resolve an active
      credential at all -- ``login`` WRITES one (``replace_
      credentials()``, whose own corrupt-file handling is round 28's
      separate, already-closed matter), ``logout`` DELETES all three
      backends unconditionally regardless of which is active.

    Raises:
        KeyringCredentialUnreadable: the marker, or the specific kind
            it names, could not be read (a corrupt/unreadable
            credentials.toml, a keyring read failure, or an
            unrecognized marker value). Never silently treated as
            absent.
        ActiveCredentialMissing: the marker names a kind but a clean
            read confirms nothing is stored for it.
        CredentialAmbiguous: no marker, and more than one kind is
            genuinely present with nothing to disambiguate them.
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

    # fix(#1778 round 30): no marker at all -- the legacy bearer-over-
    # api_key precedence (pre-round-10) applies, but ONLY when at most
    # one kind is genuinely present. Uses the TOLERANT readers, not
    # the strict ones: with no marker, there is no authoritative
    # signal to be strict ABOUT, so a transiently-unreadable keyring
    # account here degrades exactly as round 27 already established
    # and pinned (no marker + one kind unreadable + the other kind
    # readable -> fall back to the readable one, unchanged).
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
    """Raise ``CredentialsFileCorrupt`` if credentials.toml exists but
    is not valid TOML; a no-op otherwise (missing file, or valid TOML).

    fix(#1778 review round 22): every credential LOOKUP in this module
    (``load_bearer_token`` and friends, ``load_active_credential_kind``)
    deliberately tolerates a corrupt file by treating it as "nothing
    usable here" and falling back to keyring, so most commands never
    notice the file is broken at all -- correct for them, since they
    just want a working credential from wherever one is available. But
    a read-ONLY command whose whole job IS to report on the stored
    credential (``whoami``, ``status``) must not silently launder a
    corrupt file into a misleading "not logged in" / EXIT_AUTH when the
    real problem is a local file needing repair. Call this FIRST, before
    resolving any credential, so that case is reported for what it is.
    """
    _read_credentials_file()


# ---------- Delete ----------

def delete_credentials(instance: str) -> None:
    """Remove every member of the credential set (fix(#1778 round 32):
    _CREDENTIAL_SET -- bearer, refresh, api_key, and the refresh
    token's pairing fingerprint) from the keyring, AND the
    credentials.toml section.

    Missing entries are silently ignored — logout is idempotent.
    """
    for _name, account_fn, _field in _CREDENTIAL_SET:
        try:
            keyring.delete_password(SERVICE, account_fn(instance))
        except (KeyringError, OSError):
            # PasswordDeleteError (a KeyringError subclass) + missing
            # entries all swallowed -- logout is idempotent.
            pass
    _clear_credential_section(instance)


# ---------- Atomic credential swap (login) ----------

_FIELD_BY_KIND = {"bearer": "bearer_token", "api_key": "api_key"}


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
    ``_Unknown``).

    fix(#1778 round 32): ``keyring_refresh_fingerprint`` closes the gap
    that let round 31's rollback silently drop the pairing fingerprint
    -- ``bearer``/``api_key``/``refresh`` were already covered, but
    nothing snapshotted or restored the fourth member of
    ``_CREDENTIAL_SET``, so a login that failed after storing a new
    refresh token restored the OLD bearer+refresh pair without their
    matching fingerprint, and the next 401 discarded the restored
    (perfectly valid) refresh token as unpaired.
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

    # fix(#1778 round 32): iterates _CREDENTIAL_SET (the single
    # definition of the four-member set) rather than hand-listing each
    # account -- see test_credential_set_structural.py.
    bearer, api_key, refresh, fingerprint = (
        _kr(account_fn(instance)) for _name, account_fn, _field in _CREDENTIAL_SET
    )
    return _CredentialSnapshot(
        keyring_bearer=bearer,
        keyring_api_key=api_key,
        keyring_refresh=refresh,
        keyring_refresh_fingerprint=fingerprint,
        # fix(#1778 review round 22): tolerant on a corrupt file --
        # snapshotting "nothing" is safe even though it is not
        # literally accurate, because every WRITE path that could act
        # on this snapshot (_restore_credentials' own file section
        # write) independently re-reads the file and hits the SAME
        # CredentialsFileCorrupt itself, which it already treats as
        # "log and skip" (best-effort restore). Nothing here ever
        # blindly trusts this snapshot value to justify an overwrite.
        file_section=dict(_read_credentials_section_tolerant(instance)),
    )


def _restore_credentials(instance: str, snapshot: _CredentialSnapshot) -> None:
    """Best-effort restore to exactly the pre-swap state.

    Only called when the delete-competing-kinds step of
    ``replace_credentials`` fails partway through — there is nothing
    further to fall back to here, so each write is independently
    swallowed-and-logged rather than raised.
    """
    # fix(#1778 round 32): iterates _CREDENTIAL_SET, including the
    # fingerprint (round 31 left it out of both the snapshot dataclass
    # and this restore loop -- see _CredentialSnapshot's own docstring).
    values_by_name = {
        "bearer": snapshot.keyring_bearer,
        "api_key": snapshot.keyring_api_key,
        "refresh": snapshot.keyring_refresh,
        "refresh_fingerprint": snapshot.keyring_refresh_fingerprint,
    }
    for name, account_fn, _field in _CREDENTIAL_SET:
        value = values_by_name[name]
        if value is _UNKNOWN:
            # fix(#1778 review round 9): never learned whether this
            # account held a credential — see _Unknown. Neither
            # deleting nor overwriting it is safe; leave it alone.
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

    fix(#1778 review round 14): ``snapshot`` (the pre-swap read this
    same ``replace_credentials()`` call already took) gates every
    keyring delete below — an account whose snapshot came back
    ``_UNKNOWN`` is skipped entirely, never handed to
    ``keyring.delete_password``, even if the keyring has since become
    readable again. Without that gate: the snapshot recorded
    ``_UNKNOWN`` for an account precisely because it could not be read
    at snapshot time; if the keyring becomes readable again later in
    THIS SAME call (a transient hiccup) and this cleanup then deletes
    that account, and a LATER step in the transaction (another
    account's cleanup, the refresh-token write) then fails,
    ``_restore_credentials`` cannot put it back either — it applies the
    identical ``_UNKNOWN`` skip, for the identical reason (see its own
    docstring). The failed login would then irreversibly remove a
    credential nothing in this call ever actually read. Skipping the
    delete costs nothing: the round-10 marker already makes a stale
    entry in another backend harmless (readers consult the marker
    before any bearer-first/file-first precedence), so this cleanup
    was only ever tidiness, never correctness-bearing.
    """
    # fix(#1778 round 32): iterates _CREDENTIAL_SET (the single
    # definition of the four-member set: bearer, api_key, refresh,
    # refresh_fingerprint) instead of the round-31 approach of a
    # snapshot-gated loop over three members PLUS a separate,
    # differently-behaved best-effort block bolted on for the fourth --
    # see test_credential_set_structural.py. The fingerprint now gets
    # the SAME treatment as "refresh" (skipped on _UNKNOWN, propagated
    # when keep_backend == "keyring"), which is correct: an orphaned
    # fingerprint is inert on its own, but treating its cleanup
    # DIFFERENTLY from the refresh token it travels with is exactly
    # the kind of per-member special-casing this round closes.
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
            # keep_backend == "file": --no-keyring, or store_* already
            # hit this identical failure and fell back moments ago.
            # Either way the keyring is not part of this operation by
            # the caller's own choice or by its own current state, and
            # failing the whole login over it would make a headless box
            # with no keyring unable to log in at all.
            continue
        if exists:
            keyring.delete_password(SERVICE, account)

    # fix(#1778 review round 22): unlike _set_credential_field's and
    # _clear_credential_section's writes, only the READ here is
    # best-effort tidiness -- a PRE-EXISTING corrupt file is not
    # something THIS login broke, so that alone must not fail it (log
    # and skip). The WRITE below is deliberately NOT swallowed: it
    # runs inside replace_credentials()'s rollback-protected try block
    # specifically so a genuine write failure DURING this call (a
    # filesystem that just went read-only, say) propagates and
    # triggers _restore_credentials() -- see
    # TestCleanupFileRewriteFailureIsRollbackProtected. This is
    # DIFFERENT from _discard_unpaired_refresh_token() (fix(#1778
    # round 32)), which runs from try_refresh() with no such rollback
    # net and must never let a write failure escape at all -- the same
    # exception type means something different depending on which
    # transaction (if any) is listening for it.
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
    """Atomically swap the active credential for ``instance`` to ``kind``.

    fix(#1778 review round 13): ``refresh_token``, when given, is
    persisted inside this SAME rollback-protected transaction rather
    than by a separate ``store_refresh_token()`` call after this
    function returns. The interactive login flow used to do the
    latter -- by the time it ran, ``replace_credentials`` had already
    committed the new access token AND deleted the prior refresh
    credential as part of its own cleanup. If that separate call then
    failed (keyring rejects, file fallback read-only), login reported
    failure with a half-replaced session: a new access token with no
    refresh token at all, and nothing left to roll back to. Folding it
    in here means a refresh-token write failure rolls back the ENTIRE
    swap through the existing snapshot/restore machinery -- the access
    token, the refresh token, and the marker are all restored to their
    pre-login values together, exactly like any other failure inside
    this transaction. Stored AFTER ``_delete_stale_credentials`` below
    (not before): that cleanup unconditionally deletes any existing
    refresh entry as part of clearing stale state, so writing the new
    one first would just have cleanup delete it again.

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

    fix(#1778 review round 28): rounds 22-25 each tried to characterize
    exactly when a corrupt credentials.toml was "safe" to tolerate
    during login -- same kind unchanged (round 22), or the competing
    kind's OWN state confirmed absent (round 25's
    ``competing_confirmed_absent``, computed from the keyring alone).
    Round 27 found the second characterization already wrong: a
    corrupt FILE can itself be the thing holding a competing bearer
    value, invisible to a keyring-only check, so "confirmed absent"
    was sometimes lying. The file is BOTH the credential store and the
    marker store; while it cannot be parsed, neither the competing
    credential's state nor the marker itself can be established, which
    is exactly the information every one of those carve-outs needed to
    reason about. Closing the class instead of adding a third
    exception: a corrupt file now refuses EVERY login up front, before
    any secret is stored, unconditionally -- regardless of ``kind``,
    keyring state, or what was active before. ``whoami``/``status``/
    every other read-only command stay tolerant exactly as round 23
    left them (a corrupt file only surfaces there when the file was
    genuinely the last thing to try -- see ``AppState.sdk()``);
    ``logout`` still refuses (round 22, unrelated to this function);
    ``try_refresh()``'s own marker write stays non-fatal (round 19,
    also unrelated -- a different function, refreshing an ALREADY
    -trusted session rather than deciding what to trust next).

    ``kind`` is ``"bearer"`` or ``"api_key"``. Returns ``'keyring'`` or
    ``'file'`` (where the new credential landed).
    """
    if kind not in ("bearer", "api_key"):
        raise ValueError(f"unknown credential kind: {kind!r}")

    # fix(#1778 review round 28): see the docstring above -- refuse
    # before anything else runs, read-only or not. The snapshot below
    # is itself read-only and harmless against a corrupt file, but
    # there is no longer any reason to take it, or read the active
    # kind, or store anything, when the file cannot be trusted.
    ensure_credentials_file_readable()

    snapshot = _snapshot_credentials(instance)

    # fix(#1778 review round 12): _UNKNOWN used to be checked ONLY on the
    # rollback path, after the mutating store_bearer_token/store_api_key
    # call below had already run. That call is unconditionally attempted
    # against the SAME keyring account the snapshot just tried (and
    # failed) to read — get_password raising is no guarantee set_password
    # will too, so a snapshot read failure for the account about to be
    # overwritten does not mean the write will safely fall back to the
    # file; it can just as well succeed, silently destroying the one
    # value _restore_credentials would have needed to recover it.
    #
    # fix(#1778 review round 13): round 12 closed that window by ABORTING
    # outright, which broke the documented automatic credentials.toml
    # fallback (round 8/9) — an ordinary ``login --token``/``--api-key``
    # on a headless box with no usable keyring now refused unless the
    # caller already knew to pass --no-keyring, even when the file
    # backend was perfectly writable. Reconciling rounds 9-12: an
    # unreadable snapshot for the account about to be overwritten no
    # longer aborts the login. It instead forces the SAME keyring-free
    # path --no-keyring already takes for this one store call —
    # store_bearer_token/store_api_key skip keyring.set_password
    # entirely and write straight to the file — so there is no
    # unpredictable set_password outcome left to protect against; round
    # 12's actual danger (a write landing in an account whose read had
    # just failed) cannot happen when the write never touches that
    # account. The round-10 marker below still records the new kind
    # unconditionally, so the file credential outranks any stale keyring
    # entry that later becomes readable again. Keyring cleanup for the
    # OTHER account kinds stays best-effort exactly as round 9 already
    # made it (an unreadable keyring is tolerated whenever
    # keep_backend == "file", which this forces here). The only way this
    # call still fails is the file backend itself being unwritable —
    # store_bearer_token/store_api_key then raise directly, before
    # anything has been mutated (see this function's own top-level
    # docstring), propagating exactly like any other store failure.
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
            # fix(#1778 review round 13): the keyring was unreadable AND
            # the forced file write above also failed (e.g. a read-only
            # or full XDG config dir) -- there is genuinely no backend
            # this credential could land in. Re-raised as KeyringError
            # (not the raw OSError/etc.) so it reaches EXIT_NETWORK
            # through the same handler every other "credential store
            # backend unavailable" case in this package already uses;
            # login reports it as one class of failure, not two.
            raise KeyringError(
                f"keyring unreadable for {instance}, and the fallback "
                f"credentials.toml write also failed: {exc}"
            ) from exc
        raise

    # fix(#1778 review round 11): the marker write must be INSIDE the
    # rollback-protected block, not before it. It lives in the file
    # section the snapshot above already captured, so a restore
    # correctly reverts it too, along with everything else — but only
    # if a failure writing it (a read-only or full filesystem, same as
    # any other credentials.toml write) actually triggers that restore.
    # Written outside the try, a failure here propagated straight past
    # _restore_credentials: for a same-kind login the OLD keyring
    # secret was already overwritten by store_bearer_token/
    # store_api_key above, so there was nothing left to fall back to;
    # for a kind switch, the marker write failing left the OLD kind's
    # marker in place pointing at a value that had also already
    # changed backends. Either way login reported failure with the
    # credential store left in a state nothing had rolled back.
    #
    # fix(#1778 review round 28): rounds 22-25 special-cased a
    # ``CredentialsFileCorrupt`` failure HERE as tolerable (sometimes
    # non-fatal, sometimes conditionally fatal via ``mandatory_marker``)
    # -- moot now that the file is refused unconditionally, up front,
    # before this point is ever reached (see this function's own
    # docstring). Any failure writing the marker -- corrupt file or
    # otherwise -- is now an ORDINARY marker-write failure: it rolls
    # back the whole swap and fails the login, exactly like any other
    # write in this transaction.
    try:
        _set_credential_field(instance, _ACTIVE_KIND_FIELD, kind)
        _delete_stale_credentials(
            instance, keep=kind, keep_backend=backend, snapshot=snapshot
        )
        if refresh_token:
            # fix(#1778 review round 14): must match the backend the
            # access token actually landed in, not the caller's
            # original no_keyring. When the target keyring read was
            # unknown, round 13 forces the access token into
            # credentials.toml but the keyring itself may still be
            # perfectly willing to accept the refresh token -- if it
            # were stored there with the original no_keyring=False, the
            # two tokens would land in DIFFERENT backends. try_refresh()
            # detects the backend from the refresh token's own location
            # (_detect_credential_backend) and rewrites BOTH tokens back
            # to whatever it finds, so a rotation would move the refresh
            # token into the keyring while load_bearer_token() keeps
            # preferring the (now stale, unrotated) file-backed bearer
            # under its file-over-keyring precedence -- every subsequent
            # 401 refreshes again, never converging.
            #
            # fix(#1778 review round 15): round 14 keyed this off
            # store_no_keyring -- the PRE-store INTENT computed from
            # snapshot readability alone -- not off `backend`, the
            # store call's ACTUAL outcome. The two diverge whenever
            # keyring.get_password succeeded at snapshot time (so
            # store_no_keyring is False) but keyring.set_password then
            # fails at store time (a locked keychain needing a write
            # unlock, contention, a quota) -- store_bearer_token/
            # store_api_key already catch that KeyringError and fall
            # back to the file, returning backend == "file", while
            # store_no_keyring stays False. With store_no_keyring the
            # refresh write would still try the keyring first; if THAT
            # account's set_password happens to succeed, the two
            # tokens split again -- the exact bug this round closes,
            # reopened through a store-time failure instead of a
            # snapshot-read failure. `backend != "keyring"` reflects
            # what actually happened, not what was intended going in;
            # --no-keyring and an unknown target snapshot still force
            # backend == "file" either way, so those cases are
            # unchanged.
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

    We check the credentials file first because load_refresh_token uses the
    same file-before-keyring precedence — if the file has a refresh token,
    the credential lives in the file backend.

    fix(#1778 review round 22): tolerant on a corrupt file, same as
    load_refresh_token() itself -- this runs as try_refresh()'s very
    first step, before the refresh HTTP call. Assuming "not file-backed"
    (False) is the safe default: it means try_refresh() proceeds
    assuming keyring, which is exactly right when the refresh token
    actually lives there and the file is merely unrelated-and-broken.
    """
    file_data = _read_credentials_section_tolerant(instance)
    return "refresh_token" in file_data


def try_refresh(instance: str) -> Optional[str]:
    """Attempt a single refresh; return new access token or None on failure.

    Per CONTEXT D-13, this is called once on a 401. If it fails, the caller
    prints "Session expired" and exits with EXIT_AUTH (3).

    BUG-013 fix: rotated tokens are written back to the SAME backend that
    held the original credential (file vs keyring) so that a file-backed
    credential is not shadowed by a newly keyring-written token.

    fix(#1778 round 29): the optional-return contract ("None on failure,
    never raise") covers the HTTP call and response parsing above, but
    round 17-19 left the actual PERSISTENCE of a successful rotation
    unguarded for two of its three sinks -- store_bearer_token()/
    store_refresh_token() propagate uncaught when both the keyring
    write AND the credentials.toml fallback fail (a locked keychain
    plus a read-only XDG config dir, say). The only caller
    (_sdk_helpers.call_sdk_with_reauth) does not catch storage
    exceptions, so a command already deep in its own request handling
    died with an unrelated traceback -- after the server had ALREADY
    rotated the refresh token server-side, which is the specific thing
    that makes this worse than an ordinary failed refresh: the OLD
    refresh token is now invalid too, and nothing local recorded the
    new one. Every sink is now covered: bearer + refresh-token writes
    below are wrapped in ONE block, emitting exactly one warning and
    returning None on ANY failure there (never raising); the
    active_kind marker write keeps round 19's own separate, already-
    non-fatal handling unchanged -- a marker-only failure must NOT
    discard a rotation whose actual credentials already landed safely.

    fix(#1778 round 31): a stored refresh token existing at all used to
    be treated as proof it belongs to the currently stored bearer --
    but ``credential_provenance == "stored-bearer"`` (the gate
    ``call_sdk_with_reauth`` already applies before ever calling this)
    only proves BOTH values are stored, not that they are paired. An
    upgraded profile where an earlier interactive login's refresh
    token survived a LATER ``login --token``/``--api-key`` (which
    never clears it -- see the write-path enumeration in this round's
    PR section) let this function rotate the OLD session and retry as
    a DIFFERENT principal instead of reporting the rejected token. The
    refresh token is now spent ONLY when its stored pairing
    fingerprint (see ``_fingerprint_bearer()``) matches the CURRENTLY
    stored bearer; on any mismatch -- or a legacy profile with no
    fingerprint at all -- it is treated as absent, discarded from
    storage (``_discard_unpaired_refresh_token()``), and this returns
    ``None`` exactly as if there had never been a refresh token here.

    fix(#1778 round 32): round 31's pairing check read the refresh
    token, the bearer, and the fingerprint TOLERANTLY -- a transient
    or account-specific KeyringError on any one of them collapsed to
    ``None``, indistinguishable from a confirmed absence, and the
    pairing check then judged a POSSIBLY VALID pairing "stale" and ran
    the destructive discard on a refresh token that may have been
    perfectly fine. All three reads are now STRICT (three-state:
    present / confirmed absent / unreadable). Unreadable on ANY of
    them aborts the whole pairing decision immediately -- no cleanup,
    no refresh attempt, exactly one warning, ``None`` -- never
    deleting on an unknown. Only a CONFIRMED absence or a CONFIRMED
    mismatch reaches the destructive discard-and-warn path below.
    """
    try:
        refresh = load_refresh_token_strict(instance)
        if not refresh:
            return None
        stored_bearer = _load_stored_bearer_value(instance)
        fingerprint = _load_refresh_fingerprint(instance)
    except KeyringCredentialUnreadable as exc:
        # fix(#1778 round 32): a read failure proves nothing -- the
        # pairing might still be perfectly valid. Never delete on an
        # unknown; just decline to refresh this time.
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
    # fix(#1778 review round 17): the sibling of round 15's
    # replace_credentials() fix, in this function's own rotation path.
    # store_bearer_token() can fall back to credentials.toml on its OWN
    # (a transient or account-specific keyring failure -- see its
    # `except KeyringError` -- even though `no_keyring` (detected from
    # where the OLD refresh token lived) said "keyring"). Using the
    # requested `no_keyring` instead of `backend` (the store call's
    # ACTUAL outcome) for the refresh-token write below split the two
    # rotated tokens across backends: the new access token in the file,
    # the new refresh token in the keyring. After that access token
    # expires, a LATER successful keyring bearer write is shadowed by
    # the still-there, now-expired file bearer under
    # load_bearer_token()'s file-over-keyring precedence, and commands
    # loop on refresh forever. `backend != "keyring"` reflects what
    # actually happened, exactly as replace_credentials() now does.
    # fix(#1778 round 29): both writes below can propagate -- see this
    # function's own docstring. Wrapped together (not each in its own
    # try/except) because they are one logical step from the caller's
    # point of view: "persist the rotation," which either succeeds as
    # a whole or is reported as a whole. Never logs a token value.
    try:
        backend = store_bearer_token(instance, new_access, no_keyring=no_keyring)
        new_refresh = getattr(parsed, "refresh_token", None)
        if new_refresh:
            store_refresh_token(
                instance,
                new_refresh,
                bearer_token=new_access,
                no_keyring=(backend != "keyring"),
            )
        else:
            # fix(#1778 round 31): the server renewed the access token
            # but did not issue a new refresh token -- the EXISTING
            # one is still valid and still gets used again, but its
            # pairing fingerprint was computed against the OLD bearer
            # a moment ago. Without rewriting it here, the very next
            # refresh attempt would find this pairing "mismatched"
            # against the rotation this call just performed, and
            # wrongly discard a perfectly good refresh token as stale.
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
    # fix(#1778 review round 19): the round-17 marker write below used
    # to be unconditional AND fatal -- an unwritable credentials.toml
    # (read-only or full XDG config dir) raised straight out of
    # try_refresh() even though BOTH rotated tokens had already landed
    # safely in the keyring a few lines up. That turned a successful
    # rotation into a reported refresh FAILURE, which the caller (D-13)
    # treats as "session expired" and exits EXIT_AUTH -- discarding a
    # perfectly good new access token over a marker write that was
    # only ever a tie-breaker for STALE competing credentials (round
    # 10), not a requirement for using the one just rotated.
    #
    # Two changes, without reordering the rotation above:
    # - skip the write entirely when the marker already reads "bearer"
    #   (try_refresh only ever rotates a bearer session, so the common
    #   case -- an ordinary refresh, not a kind switch -- has nothing
    #   to update);
    # - when a write IS needed, treat a failure as non-fatal: log and
    #   keep going, rather than raising. A rotation that already
    #   committed real tokens must not be undone by a best-effort
    #   bookkeeping write failing after the fact.
    if load_active_credential_kind(instance) != "bearer":
        try:
            _set_credential_field(instance, _ACTIVE_KIND_FIELD, "bearer")
        except Exception as exc:
            log.warning(
                "active_kind_marker_write_failed_after_refresh", error=str(exc)
            )
    return new_access

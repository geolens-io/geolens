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

# structlog's UNCONFIGURED default is a
# PrintLogger that writes every log.*() call straight to stdout,
# regardless of level -- every log.warning() below would land there,
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
    """A short, non-reversible pairing tag for a bearer token. Never the
    token itself, never logged: proves a
    stored refresh token actually belongs to the bearer it would
    rotate, not just that both happen to be present in storage. sha256
    truncated to 16 hex chars is plenty for this -- it only ever needs
    to be compared against itself, never guessed."""
    # codeql[py/weak-sensitive-data-hashing] comparison tag over a high-entropy bearer, not password storage; the digest is truncated, never reversible to the token, and never used to authenticate
    return hashlib.sha256(bearer_token.encode()).hexdigest()[:16]


# The credential SET for an instance, defined
# ONCE as a tuple of (name, keyring-account-fn, file-field-name)
# triples. The refresh_fingerprint is the fourth member of this set;
# hand-listing members per operation risks a login rollback silently
# dropping one, leaving a restored bearer+refresh pair without the
# fingerprint that proves they belong together. Every operation that must
# treat the whole set uniformly (snapshot, restore, logout, stale-credential
# cleanup) iterates THIS tuple instead of hand-listing its own subset, so a
# fifth member added here later cannot be forgotten in one of them --
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

    Degrading a parse failure straight to ``{}`` would be indistinguishable
    from "no file at all." A writer building on that empty dict (e.g. the active_kind
    marker write after a keyring-backed login) would then overwrite
    the ACTUAL corrupt file with a fresh one holding only the CURRENT
    instance's data, silently destroying every OTHER instance's
    file-backed credentials that happened to be sitting in the
    unparseable file. Every write path must be able to tell "empty"
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
    # A PermissionError (or any other OSError) on
    # the read() itself would propagate straight past every caller
    # here uncaught -- unlike a TOMLDecodeError, which every caller
    # handles via CredentialsFileCorrupt. There is no
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
    # _read_credentials_file() propagates
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
    # _read_credentials_file() propagates
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

    ``bearer_token``, when given, pairs this
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

    Every READ-with-fallback caller below
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

    ``load_bearer_token()``/``load_api_key()``
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

    AppState.sdk() needs to tell "the
    marked-active bearer account is unreadable right now" apart from
    "there is genuinely no bearer credential" -- conflating the two
    (what load_bearer_token() itself does) would let it silently fall
    through to a competing, possibly-stale api_key credential the
    _UNKNOWN cleanup gate deliberately left in place. GEOLENS_TOKEN and a file-backed value both
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

    Tolerant: a keyring read failure degrades to "not found," for callers that
    do not need to tell the two apart. AppState.sdk()'s
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


def load_refresh_token_strict(instance: str) -> Optional[str]:
    """Three-state STRICT refresh-token read:
    returns the stored value, ``None`` if genuinely absent, or raises
    ``KeyringCredentialUnreadable("refresh", ...)`` if the keyring
    account itself could not be read. The pairing check in
    try_refresh() must be able to tell "no refresh token here" apart
    from "can't tell right now" -- a transient/account-specific
    KeyringError collapsing to ``None`` would look identical to a
    confirmed absence.
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

    try_refresh() must compare a refresh token's
    pairing fingerprint against the STORED bearer specifically -- the
    one it can actually rotate -- not whatever env override might
    (even transiently) be set. ``call_sdk_with_reauth`` already gates
    try_refresh() on ``credential_provenance == "stored-bearer"``,
    so this should never actually diverge from
    ``load_bearer_token()`` in practice; kept separate anyway so the
    pairing check can never be fooled by that precedence rule even in
    principle.

    STRICT -- raises
    ``KeyringCredentialUnreadable("bearer", ...)`` on a keyring read
    failure instead of collapsing it to ``None``. A transient or
    account-specific KeyringError here would otherwise look identical to "no
    bearer stored," which would make a POSSIBLY VALID pairing look stale and
    trigger the destructive discard-and-warn path in try_refresh()
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
    ``None`` if there isn't one (a legacy profile with no pairing).

    STRICT -- raises
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

    Used by try_refresh() when a rotation renews
    the access token but the server does NOT issue a new refresh
    token -- the existing (unrotated) refresh token still needs its
    fingerprint updated to the NEW bearer, or the next refresh attempt
    would find it "mismatched" against the very rotation this call
    just performed and discard a perfectly good, still-valid refresh
    token as if it were stale.

    The right call whenever the bearer stayed
    in the backend it was already in, which is every rotation but the
    fallback one. Rewriting the unchanged refresh SECRET there would ask
    a second account for a write nothing needs, and a keyring that
    accepts the bearer and fingerprint accounts while refusing the
    refresh one -- with no usable file fallback behind it -- would then
    lose a rotation this helper completes: try_refresh() would report
    failure with the new bearer already stored against the OLD
    fingerprint, and the next attempt would discard a still-valid
    refresh token as unpaired. Only the
    backend-MOVED case needs the whole pair rewritten; see
    try_refresh().
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
    """Best-effort delete of the refresh token AND its pairing
    fingerprint from the KEYRING only, leaving the file side alone.
    Never raises -- see ``_discard_unpaired_refresh_token()`` (which
    calls this for its own keyring half) for why every step here
    swallows KeyringError/OSError, and
    tests/test_best_effort_helpers_never_raise.py for the gate.

    try_refresh() also needs exactly this half on its own,
    with the file side deliberately untouched -- when a rotation falls
    back from the keyring to credentials.toml, the pair is REWRITTEN to
    the file and only the superseded keyring copy has to go. Deleting
    both sides there would throw away the copy just written.
    """
    for account_fn in (_keyring_account_refresh, _keyring_account_refresh_fingerprint):
        try:
            keyring.delete_password(SERVICE, account_fn(instance))
        except (KeyringError, OSError):
            pass


def _discard_unpaired_refresh_token(instance: str) -> None:
    """Best-effort delete of the refresh token AND its fingerprint from
    BOTH backends.

    Called from try_refresh() when a stored refresh token cannot be
    PROVEN to belong to the currently stored bearer (no fingerprint at
    all -- a legacy profile; a fingerprint that doesn't match; or no
    bearer to compare against). Never raises: this runs on a path that
    is already reporting "no refresh available," and a delete failure
    here must not turn that into a crash (mirrors ``delete_credentials()``'s
    own best-effort, idempotent design).

    The file WRITE at the end must be guarded too -- an unwritable
    credentials.toml (read-only, full) would otherwise raise straight out
    of this function and past try_refresh(), which has no rollback net the
    way replace_credentials() does, and whoami/status would die with a
    storage traceback instead of the normal auth error this function
    exists to produce cleanly. Every step explicitly catches KeyringError
    (covers PasswordDeleteError and the rest of that family) and
    OSError, logs once, and continues -- see
    tests/test_best_effort_helpers_never_raise.py.
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


#: The field name for the "active credential
#: kind" marker in credentials.toml — see load_active_credential_kind().
_ACTIVE_KIND_FIELD = "active_kind"


def _read_active_kind_marker(instance: str) -> Optional[str]:
    """STRICT marker reader: returns
    ``"bearer"``/``"api_key"`` for a present, valid marker; ``None``
    when the field is genuinely absent (no file, or the field itself
    is missing) on an otherwise-readable file; raises
    ``KeyringCredentialUnreadable("marker", ...)`` when the file
    cannot be read/parsed OR the field holds a value that is neither
    ``"bearer"`` nor ``"api_key"``.

    ``load_active_credential_kind()`` (below) collapses
    ALL three of those failure shapes -- a corrupt file, a permission
    error, and a garbage value -- to the exact same ``None`` a
    genuinely-never-set marker returns. AppState.sdk() treats a PRESENT
    marker as authoritative, but that only works when the marker can be
    READ; if the file becomes unreadable after a kind switch, a two-state
    contract would make that failure indistinguishable from "no marker
    was ever written," and resolution would silently fall back to legacy
    bearer-first precedence -- exactly the stale credential a kind switch's marker
    exists to shadow. ``resolve_active_credential()`` below is the one
    caller that needs this distinction; every OTHER existing caller
    keeps using the tolerant ``load_active_credential_kind()`` and is
    unaffected.
    """
    try:
        data = _read_credentials_file().get(instance, {})
    except CredentialsFileCorrupt as exc:
        # Fold the path into the detail string --
        # KeyringCredentialUnreadable has no path attribute of its own
        # (a keyring account read failure has no meaningful path), but
        # a corrupt-FILE failure specifically is much more actionable
        # named, matching the whoami/status message.
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

    A stale competing credential surviving
    in EITHER backend (keyring or credentials.toml) after a swap could
    outrank the one that was actually just stored, because
    ``load_bearer_token``/``load_api_key`` are independent reads and
    bearer wins by default — and cleanup of the OTHER backend can only
    ever be best-effort (keyring and credentials.toml are separate backends
    with no shared transaction). This marker is written unconditionally
    by ``replace_credentials()`` in the SAME file section regardless of
    which backend the secret itself landed in, so it survives even a
    ``--no-keyring`` login or a keyring that was unavailable at store
    time. Readers (``AppState.sdk()``) consult it FIRST: cleanup
    failing to evict a competing entry no longer matters for
    correctness, only for tidiness.

    TOLERANT wrapper around the strict
    ``_read_active_kind_marker()`` above, for every caller that
    does not need the strict distinction (``try_refresh()``'s own
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
    value). Guessing here (an unconditional bearer-first legacy
    precedence) risks silently authenticating as the
    WRONG principal: an API-key login can leave a stale bearer behind
    in the keyring (the cleanup is best-effort, not
    correctness-bearing), and there is no safe default once more than
    one real
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
    active for ``instance``". Marker precedence, the
    marker-authoritative rules, and the ambiguity/unreadable handling
    live in one place, covering the whole state matrix.

    Enumerated call sites (every consumer of a
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
      credentials()``, which handles a corrupt file itself), ``logout`` DELETES all three
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

    # No marker at all -- the legacy bearer-over-
    # api_key precedence applies, but ONLY when at most
    # one kind is genuinely present. Uses the TOLERANT readers, not
    # the strict ones: with no marker, there is no authoritative
    # signal to be strict ABOUT, so a transiently-unreadable keyring
    # account here degrades gracefully (no marker + one kind
    # unreadable + the other kind readable -> fall back to the
    # readable one).
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

    Every credential LOOKUP in this module
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
    """Remove every member of the credential set (_CREDENTIAL_SET:
    bearer, refresh, api_key, and the refresh token's pairing
    fingerprint) from the keyring, AND the credentials.toml section.

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
    — distinct from ``None`` ("confirmed
    absent"). Swallowing a read failure to ``None`` would record an EXISTING
    credential as absent; if cleanup later failed and the keyring
    happened to be readable again by the time ``_restore_credentials``
    ran, that ``None`` would make it call ``delete_password()`` on an account
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

    ``keyring_refresh_fingerprint`` is the fourth member of
    ``_CREDENTIAL_SET``; without snapshotting and restoring it, a login
    that failed after storing a new refresh token would restore the OLD
    bearer+refresh pair without their matching fingerprint, and the next
    401 would discard the restored (perfectly valid) refresh token as
    unpaired.
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

    # Iterates _CREDENTIAL_SET (the single
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
        # Tolerant on a corrupt file --
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
    # Iterates _CREDENTIAL_SET, including the
    # fingerprint (see _CredentialSnapshot's own docstring).
    values_by_name = {
        "bearer": snapshot.keyring_bearer,
        "api_key": snapshot.keyring_api_key,
        "refresh": snapshot.keyring_refresh,
        "refresh_fingerprint": snapshot.keyring_refresh_fingerprint,
    }
    for name, account_fn, _field in _CREDENTIAL_SET:
        value = values_by_name[name]
        if value is _UNKNOWN:
            # Never learned whether this
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
      BOTH backends;
    - ``keep`` itself is ALSO deleted from whichever backend it was NOT
      just stored to. ``store_bearer_token``/``store_api_key`` only ever
      write ONE backend per call (keyring, or the file on
      fallback/``no_keyring``); a stale same-kind value left in the OTHER
      backend from an earlier login would otherwise win, because
      ``load_bearer_token``/``load_api_key`` prefer the file over keyring.

    The keyring half must not swallow every delete failure with a blanket
    ``except Exception: pass``. ``keyring.errors.PasswordDeleteError`` is
    raised for BOTH "no such entry" (expected and fine — this cleanup is
    idempotent by design) AND a genuine backend refusal (a locked
    keychain, permission denied, ...), with no reliable way to tell the
    two apart from the exception alone. Swallowing both would let
    ``replace_credentials()`` report success while the old credential
    stayed live in the OTHER backend, where a stale BEARER token in
    particular keeps outranking a freshly-stored API key.

    Checking existence FIRST (rather than pattern-matching the
    exception) resolves the ambiguity: an already-absent entry is
    skipped without ever calling delete (nothing to fail), so a delete
    that IS attempted was for an entry that existed, and its failure is
    real — it propagates. The credentials.toml write below is allowed
    to raise for the same reason: ``replace_credentials`` is the one
    that needs to know, so it can restore the pre-swap snapshot instead
    of leaving either backend in a half-cleaned state.

    An UNREADABLE keyring (locked, backend down, ...) during the
    existence check is NOT "no such entry": skipping it would leave a
    stale credential we genuinely could not see untouched. That matters
    specifically because ``store_bearer_token``/``store_api_key``
    themselves fall back to the credentials.toml file on a
    ``KeyringError`` — so a keyring that is locked at STORE time (the new
    credential lands in the file) can still hold an untouched OLD
    credential from an earlier, working login. Once the keyring becomes
    readable again, ``load_bearer_token``'s keyring-as-last-resort lookup
    returns that stale value, and it outranks the freshly-stored
    (file-backed) one under ``AppState.sdk()``'s bearer-first precedence.
    An unreadable backend during cleanup is therefore treated as a failed
    swap: it propagates, so ``replace_credentials`` restores its snapshot
    and ``login`` reports the failure instead of a false success.

    That propagation is fatal ONLY when ``keep_backend == "keyring"``:
    ``login --no-keyring`` and a headless install with no working keyring
    have ``keep_backend == "file"`` (``store_bearer_token``/
    ``store_api_key`` never touch keyring when ``no_keyring=True``, or
    fall back to the file the moment keyring raises), and failing there
    would defeat the automatic file fallback the store side already has.
    ``"keyring"`` is the one case where the keyring is DEMONSTRABLY
    reachable right now (the new credential just landed there), so a read
    failure for a different account is a real, worth-surfacing problem,
    not an unavailable backend. When ``keep_backend`` is ``"file"`` an
    unreadable keyring is tolerated the same as "no such entry": there is
    nothing here that can safely be told apart from a keyring that simply
    doesn't exist on this box.

    ``snapshot`` (the pre-swap read this same ``replace_credentials()``
    call already took) gates every keyring delete below — an account
    whose snapshot came back ``_UNKNOWN`` is skipped entirely, never
    handed to ``keyring.delete_password``, even if the keyring has since
    become readable again. Without that gate: the snapshot recorded
    ``_UNKNOWN`` for an account precisely because it could not be read at
    snapshot time; if the keyring becomes readable again later in THIS
    SAME call (a transient hiccup) and this cleanup then deleted that
    account, and a LATER step in the transaction (another account's
    cleanup, the refresh-token write) then failed, ``_restore_credentials``
    could not put it back either — it applies the identical ``_UNKNOWN``
    skip, for the identical reason (see its own docstring). The failed
    login would then irreversibly remove a credential nothing in this call
    ever actually read. Skipping the delete costs nothing: the active_kind
    marker already makes a stale entry in another backend harmless
    (readers consult the marker before any bearer-first/file-first
    precedence), so this cleanup is only tidiness, never
    correctness-bearing.
    """
    # Iterates _CREDENTIAL_SET (the single
    # definition of the four-member set: bearer, api_key, refresh,
    # refresh_fingerprint) rather than special-casing any member -- see
    # test_credential_set_structural.py. The fingerprint gets the SAME
    # treatment as "refresh" (skipped on _UNKNOWN, propagated when
    # keep_backend == "keyring"): an orphaned fingerprint is inert on its
    # own, but treating its cleanup DIFFERENTLY from the refresh token it
    # travels with is exactly the per-member special-casing to avoid.
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

    # Unlike _set_credential_field's and
    # _clear_credential_section's writes, only the READ here is
    # best-effort tidiness -- a PRE-EXISTING corrupt file is not
    # something THIS login broke, so that alone must not fail it (log
    # and skip). The WRITE below is deliberately NOT swallowed: it
    # runs inside replace_credentials()'s rollback-protected try block
    # specifically so a genuine write failure DURING this call (a
    # filesystem that just went read-only, say) propagates and
    # triggers _restore_credentials() -- see
    # TestCleanupFileRewriteFailureIsRollbackProtected. This is
    # DIFFERENT from _discard_unpaired_refresh_token(), which runs
    # from try_refresh() with no such rollback
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

    ``refresh_token``, when given, is
    persisted inside this SAME rollback-protected transaction rather
    than by a separate ``store_refresh_token()`` call after this
    function returns. By the time a separate call ran, ``replace_credentials``
    would already have committed the new access token AND deleted the
    prior refresh credential as part of its own cleanup; if that call then
    failed (keyring rejects, file fallback read-only), login would report
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

    The new credential is stored FIRST, before anything else is touched
    (deleting the old one first would leave the user logged out, with the
    working credential already gone, if the storage write then failed --
    a keyring falling back to a read-only or full XDG path, a permissions
    error, ...).

    If the store itself raises, nothing here has touched storage yet
    (the snapshot read is read-only) — the exception propagates and the
    prior credentials are untouched. If the cleanup afterward fails
    partway — keyring and credentials.toml are separate backends with no
    shared transaction, so that step is the one place this can't be
    fully atomic — the pre-swap snapshot is restored before re-raising,
    so the net effect is still "nothing changed" rather than a mix of
    old and new credentials.

    The cleanup step deletes both the
    competing credential kinds AND ``kind``'s own value from whichever
    backend it did NOT just land in — see ``_delete_stale_credentials``.
    Without that second part, a bearer token stored in credentials.toml
    by an earlier ``--no-keyring`` login would survive a later plain
    ``login`` that stored the replacement in the keyring, and
    ``load_bearer_token``'s file-over-keyring precedence would keep
    resolving the stale one.

    That cleanup cannot be correctness-bearing: it can only ever be
    best-effort — keyring and credentials.toml are
    separate backends with no shared transaction, and an API-key login
    that fell back to the file while the keyring was temporarily
    unavailable has NOTHING it can safely do about a stale bearer
    token sitting in that unreachable keyring. So this also writes an
    explicit "active credential kind" marker (see
    ``load_active_credential_kind``) into the SAME file section the
    snapshot/restore machinery already covers, unconditionally —
    regardless of which backend ``value`` itself landed in. Readers
    consult that marker first, so a stale competing entry surviving in
    the other backend cannot outrank the credential that was
    just stored; ``_delete_stale_credentials`` below is tidiness,
    not the thing correctness depends on.

    A corrupt credentials.toml refuses EVERY login up front, before any
    secret is stored, unconditionally -- regardless of ``kind``, keyring
    state, or what was active before. The file is BOTH the credential
    store and the marker store; while it cannot be parsed, neither the
    competing credential's state nor the marker itself can be
    established (a corrupt FILE can itself be holding a competing bearer
    value, invisible to a keyring-only check), so any carve-out that
    tolerated it would rest on information that cannot be known.
    Read-only commands resolve through ``resolve_active_credential()``,
    which reads the marker first, so a corrupt file stops them too unless
    ``GEOLENS_TOKEN`` is set; ``logout`` also refuses;
    ``try_refresh()``'s own marker write stays non-fatal -- a different
    function, refreshing an ALREADY-trusted session rather than deciding
    what to trust next.

    ``kind`` is ``"bearer"`` or ``"api_key"``. Returns ``'keyring'`` or
    ``'file'`` (where the new credential landed).
    """
    if kind not in ("bearer", "api_key"):
        raise ValueError(f"unknown credential kind: {kind!r}")

    # See the docstring above -- refuse
    # before anything else runs, read-only or not. The snapshot below
    # is itself read-only and harmless against a corrupt file, but
    # there is no reason to take it, or read the active
    # kind, or store anything, when the file cannot be trusted.
    ensure_credentials_file_readable()

    snapshot = _snapshot_credentials(instance)

    # An _UNKNOWN snapshot read for the account about to be overwritten
    # cannot be left to the rollback path alone. The mutating
    # store_bearer_token/store_api_key call below is unconditionally
    # attempted against the SAME keyring account the snapshot just tried
    # (and failed) to read — get_password raising is no guarantee
    # set_password will too, so the write may just as well succeed,
    # silently destroying the one value _restore_credentials would have
    # needed to recover it.
    #
    # Aborting outright would break the documented automatic
    # credentials.toml fallback: an ordinary ``login --token``/``--api-key``
    # on a headless box with no usable keyring would refuse unless the
    # caller already knew to pass --no-keyring, even when the file
    # backend is perfectly writable. So an unreadable snapshot for the
    # account about to be overwritten instead forces the SAME keyring-free
    # path --no-keyring already takes for this one store call —
    # store_bearer_token/store_api_key skip keyring.set_password
    # entirely and write straight to the file — so a write can never land
    # in an account whose read just failed. The active_kind marker below
    # still records the new kind unconditionally, so the file credential
    # outranks any stale keyring entry that later becomes readable again.
    # Keyring cleanup for the OTHER account kinds stays best-effort (an
    # unreadable keyring is tolerated whenever keep_backend == "file",
    # which this forces here). The only way this call still fails is the
    # file backend itself being unwritable — store_bearer_token/
    # store_api_key then raise directly, before anything has been mutated
    # (see this function's own top-level docstring), propagating exactly
    # like any other store failure.
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
            # The keyring was unreadable AND
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

    # The marker write must be INSIDE the
    # rollback-protected block, not before it. It lives in the file
    # section the snapshot above already captured, so a restore
    # correctly reverts it too, along with everything else — but only
    # if a failure writing it (a read-only or full filesystem, same as
    # any other credentials.toml write) actually triggers that restore.
    # Written outside the try, a failure here would propagate straight past
    # _restore_credentials: for a same-kind login the OLD keyring
    # secret was already overwritten by store_bearer_token/
    # store_api_key above, so there would be nothing left to fall back to;
    # for a kind switch, the marker write failing would leave the OLD kind's
    # marker in place pointing at a value that had also already
    # changed backends. Either way login would report failure with the
    # credential store left in a state nothing had rolled back.
    #
    # A corrupt credentials.toml never reaches this point (it is refused
    # unconditionally, up front -- see this function's own docstring), so
    # any failure writing the marker is an ORDINARY marker-write failure: it
    # rolls back the whole swap and fails the login, exactly like any other
    # write in this transaction.
    try:
        _set_credential_field(instance, _ACTIVE_KIND_FIELD, kind)
        _delete_stale_credentials(
            instance, keep=kind, keep_backend=backend, snapshot=snapshot
        )
        if refresh_token:
            # Must match the backend the
            # access token actually landed in, not the caller's
            # original no_keyring. When the target keyring read was
            # unknown, the access token is forced into
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
            # Key this off `backend`, the store call's ACTUAL outcome, not
            # store_no_keyring, the PRE-store INTENT computed from
            # snapshot readability alone. The two diverge whenever
            # keyring.get_password succeeded at snapshot time (so
            # store_no_keyring is False) but keyring.set_password then
            # fails at store time (a locked keychain needing a write
            # unlock, contention, a quota) -- store_bearer_token/
            # store_api_key already catch that KeyringError and fall
            # back to the file, returning backend == "file", while
            # store_no_keyring stays False. With store_no_keyring the
            # refresh write would still try the keyring first; if THAT
            # account's set_password happens to succeed, the two
            # tokens split again. `backend != "keyring"` reflects
            # what actually happened, not what was intended going in;
            # --no-keyring and an unknown target snapshot still force
            # backend == "file" either way.
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

    We check the credentials file first because load_refresh_token_strict uses the
    same file-before-keyring precedence — if the file has a refresh token,
    the credential lives in the file backend.

    Tolerant on a corrupt file, same as
    load_refresh_token_strict() itself -- this runs as try_refresh()'s very
    first step, before the refresh HTTP call. Assuming "not file-backed"
    (False) is the safe default: it means try_refresh() proceeds
    assuming keyring, which is exactly right when the refresh token
    actually lives there and the file is merely unrelated-and-broken.
    """
    file_data = _read_credentials_section_tolerant(instance)
    return "refresh_token" in file_data


def try_refresh(instance: str) -> Optional[str]:
    """Attempt a single refresh; return new access token or None on failure.

    This is called once on a 401. If it fails, the caller
    prints "Session expired" and exits with EXIT_AUTH (3).

    BUG-013 fix: rotated tokens are written back to the SAME backend that
    held the original credential (file vs keyring) so that a file-backed
    credential is not shadowed by a newly keyring-written token.

    The optional-return contract ("None on failure,
    never raise") covers the HTTP call, response parsing, and the
    PERSISTENCE of a successful rotation. store_bearer_token()/
    store_refresh_token() propagate uncaught when both the keyring
    write AND the credentials.toml fallback fail (a locked keychain
    plus a read-only XDG config dir, say), and the only caller
    (_sdk_helpers.call_sdk_with_reauth) does not catch storage
    exceptions, so a command already deep in its own request handling
    would die with an unrelated traceback -- after the server had ALREADY
    rotated the refresh token server-side, which is the specific thing
    that makes this worse than an ordinary failed refresh: the OLD
    refresh token is now invalid too, and nothing local recorded the
    new one. Bearer + refresh-token writes below are therefore wrapped
    in ONE block, emitting exactly one warning and returning None on ANY
    failure there (never raising); the active_kind marker write has its
    own separate, non-fatal handling -- a marker-only failure must NOT
    discard a rotation whose actual credentials already landed safely.

    A stored refresh token existing at all is not proof it belongs to the
    currently stored bearer:
    ``credential_provenance == "stored-bearer"`` (the gate
    ``call_sdk_with_reauth`` applies before ever calling this)
    only proves BOTH values are stored, not that they are paired. A
    profile where an earlier interactive login's refresh
    token survived a LATER ``login --token``/``--api-key`` (which
    never clears it) would let this function rotate the OLD session and
    retry as a DIFFERENT principal instead of reporting the rejected
    token. The refresh token is therefore spent ONLY when its stored
    pairing fingerprint (see ``_fingerprint_bearer()``) matches the
    CURRENTLY stored bearer; on any mismatch -- or a legacy profile with
    no fingerprint at all -- it is treated as absent, discarded from
    storage (``_discard_unpaired_refresh_token()``), and this returns
    ``None`` exactly as if there had never been a refresh token here.

    The pairing check reads the refresh token, the bearer, and the
    fingerprint STRICTLY (three-state: present / confirmed absent /
    unreadable). A tolerant read would collapse a transient or
    account-specific KeyringError to ``None``, indistinguishable from a
    confirmed absence, and judge a POSSIBLY VALID pairing "stale" and run
    the destructive discard on a refresh token that may be perfectly
    fine. Unreadable on ANY of them aborts the whole pairing decision
    immediately -- no cleanup, no refresh attempt, exactly one warning,
    ``None`` -- never deleting on an unknown. Only a CONFIRMED absence or
    a CONFIRMED mismatch reaches the destructive discard-and-warn path
    below.

    When the server issues no new refresh token, a rotation whose bearer
    MOVED backends (a keyring bearer write that fell back to the file)
    writes the refresh token and its fingerprint together through
    ``store_refresh_token()`` into the backend the bearer actually
    landed in, and drops the superseded keyring copy once that write
    has committed. Rewriting only the fingerprint would split the
    retained pair across backends: the next refresh's
    ``_detect_credential_backend()`` -- which decides by looking for a
    refresh_token in the FILE -- would answer "keyring," write the newly
    rotated bearer there, and have it shadowed by the stale file bearer
    that outranks it, so commands would refresh on every call instead of
    converging.

    Only when it moved: rewriting the unchanged refresh SECRET on every
    retained-token rotation needs a write to an account that had nothing
    to say, and a keyring that accepts the bearer and fingerprint
    accounts while refusing the refresh one -- with an unusable
    credentials.toml behind it -- would lose a rotation the
    fingerprint-only path completes: this would return ``None`` with the
    new bearer already stored against the OLD fingerprint, so the next
    attempt would discard a still-valid refresh token as unpaired. An
    unchanged backend takes ``_rewrite_refresh_fingerprint()``, which
    touches exactly the one member that is actually stale.
    """
    try:
        refresh = load_refresh_token_strict(instance)
        if not refresh:
            return None
        stored_bearer = _load_stored_bearer_value(instance)
        fingerprint = _load_refresh_fingerprint(instance)
    except KeyringCredentialUnreadable as exc:
        # A read failure proves nothing -- the
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
        # Routed through make_client() (the single construction point for
        # every GeolensClient in this package), which bounds the request
        # timeout so a stalled refresh endpoint cannot hang the calling
        # command forever instead of falling back to "refresh failed".
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
    # store_bearer_token() can fall back to credentials.toml on its OWN
    # (a transient or account-specific keyring failure -- see its
    # `except KeyringError` -- even though `no_keyring` (detected from
    # where the OLD refresh token lived) said "keyring"). Using the
    # requested `no_keyring` instead of `backend` (the store call's
    # ACTUAL outcome) for the refresh-token write below would split the two
    # rotated tokens across backends: the new access token in the file,
    # the new refresh token in the keyring. After that access token
    # expires, a LATER successful keyring bearer write is shadowed by
    # the still-there, now-expired file bearer under
    # load_bearer_token()'s file-over-keyring precedence, and commands
    # loop on refresh forever. `backend != "keyring"` reflects what
    # actually happened, exactly as replace_credentials() does.
    # Both writes below can propagate -- see this
    # function's own docstring. Wrapped together (not each in its own
    # try/except) because they are one logical step from the caller's
    # point of view: "persist the rotation," which either succeeds as
    # a whole or is reported as a whole. Never logs a token value.
    try:
        backend = store_bearer_token(instance, new_access, no_keyring=no_keyring)
        # Did the bearer actually land in the backend
        # this rotation asked for? Only the keyring -> file fallback is a
        # MOVE; `no_keyring` already means "the file, deliberately."
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
            # The server renewed the access token
            # but did not issue a new refresh token -- the EXISTING
            # one is still valid and still gets used again, but its
            # pairing fingerprint was computed against the OLD bearer
            # a moment ago. Without rewriting it here, the very next
            # refresh attempt would find this pairing "mismatched"
            # against the rotation this call just performed, and
            # wrongly discard a perfectly good refresh token as stale.
            #
            # Rewriting only the FINGERPRINT is enough while the bearer lands
            # where `no_keyring` said it would, and wrong the moment
            # store_bearer_token() falls back to the file on its own. That
            # would split the retained pair across backends -- fingerprint in
            # the file, refresh token still in the keyring -- and the next
            # refresh's _detect_credential_backend() (which looks for a
            # refresh_token in the FILE) would answer "keyring" and write the
            # new bearer there, where the stale file-backed bearer shadows it
            # under load_bearer_token()'s file-over-keyring precedence: every
            # subsequent command would 401, refresh, and 401 again instead of
            # converging. A MOVED bearer therefore takes the whole retained
            # pair with it, through store_refresh_token(), exactly as the
            # new-refresh-token branch above does.
            #
            # Only when it moved: rewriting the pair unconditionally asks a
            # second keyring account for a write of a secret that did not
            # change, and a keyring accepting the bearer and fingerprint
            # accounts while refusing the refresh one, with no usable file
            # fallback behind it, would turn a rotation that can complete into
            # a reported failure, with the new bearer already stored against
            # the OLD fingerprint for the next attempt to discard as unpaired.
            # Unchanged backend -> update the fingerprint member alone, in
            # place.
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
    # The rotation above asked for the keyring and landed in
    # the file, so the refresh token now lives in BOTH backends -- the
    # copy just written, and the superseded keyring one it was moved
    # from. The file copy wins every read, so the leftover is not
    # actively wrong, but it is a spendable credential for a session
    # this profile no longer tracks there. Dropped best-effort (it
    # never raises), only after the file write above has already
    # committed, and only on the keyring side: the file holds the copy
    # that must survive.
    if backend_moved:
        _delete_keyring_refresh_entries(instance)
    # The marker write below must be non-fatal: an unwritable
    # credentials.toml (read-only or full XDG config dir) must not raise out
    # of try_refresh() when BOTH rotated tokens already landed safely, since
    # that would turn a successful rotation into a reported refresh FAILURE,
    # which the caller treats as "session expired" and exits EXIT_AUTH
    # -- discarding a perfectly good new access token over a marker write
    # that is only a tie-breaker for STALE competing credentials, not a
    # requirement for using the one just rotated.
    #
    # Two measures, without reordering the rotation above:
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

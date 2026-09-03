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
# _warn_credentials_file_corrupt() below still prints directly rather
# than using log.warning() -- not for stdout-safety anymore, but
# because it wants an unconditional, human-readable sentence instead of
# structlog's key=value dump for the one warning a user must actually
# read and act on.
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
    try:
        return tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise CredentialsFileCorrupt(path, str(exc)) from exc


def _write_credentials_file(data: dict) -> None:
    _config.atomic_write_text(
        _config.credentials_path(),
        tomli_w.dumps(data),
        mode=0o600,
        tighten_parent=True,
    )


def _warn_credentials_file_corrupt(exc: CredentialsFileCorrupt) -> None:
    """Print a corrupt-credentials.toml warning directly to stderr.

    fix(#1778 review round 22): this module has no access to the CLI's
    Output formatter (data layer, not command layer -- see every other
    function here, none of which print). Printed unconditionally
    (independent of ``--json``) for the one case a login genuinely
    needs a human to notice: the marker was NOT updated, and the file
    needs fixing or moving before it can be trusted again.

    fix(#1778 review round 24): kept as a direct print rather than
    switched to ``log.warning()`` now that the module's structlog
    logger is configured to stderr too (see the module-level comment
    above) -- this one warning still wants an unconditional,
    human-readable sentence ("Fix or move the file") rather than
    structlog's key=value dump, since it is the one diagnostic in this
    file a user is actually expected to read and act on, not just a
    routine breadcrumb.
    """
    print(
        f"Warning: {exc.path} is corrupt ({exc.detail}) -- the active "
        "credential marker was not updated there. Fix or move the file.",
        file=sys.stderr,
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


def load_bearer_token(instance: str) -> Optional[BearerToken]:
    """Return the active bearer token per the D-35 precedence."""
    env_token = _config.get_token_from_env()
    if env_token:
        return BearerToken(env_token)
    # credentials.toml > keyring (file is explicit; keyring is fallback)
    data = _read_credentials_section_tolerant(instance)
    token = data.get("bearer_token")
    if token:
        return BearerToken(token)
    try:
        kr_token = keyring.get_password(SERVICE, _keyring_account_token(instance))
    except KeyringError:
        return None
    return BearerToken(kr_token) if kr_token else None


def load_api_key(instance: str) -> Optional[ApiKey]:
    data = _read_credentials_section_tolerant(instance)
    key = data.get("api_key")
    if key:
        return ApiKey(key)
    try:
        kr_key = keyring.get_password(SERVICE, _keyring_account_api_key(instance))
    except KeyringError:
        return None
    return ApiKey(kr_key) if kr_key else None


def load_refresh_token(instance: str) -> Optional[str]:
    data = _read_credentials_section_tolerant(instance)
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
    data = _read_credentials_section_tolerant(instance)
    kind = data.get(_ACTIVE_KIND_FIELD)
    return kind if kind in ("bearer", "api_key") else None


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
    snapshot_by_name = {
        "bearer": snapshot.keyring_bearer,
        "api_key": snapshot.keyring_api_key,
        "refresh": snapshot.keyring_refresh,
    }
    for name, account_fn in _ACCOUNT_FN_BY_KIND.items():
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
    # _clear_credential_section's writes, this cleanup is best-effort
    # tidiness (round 10's docstring above: "now tidiness, not the
    # thing correctness depends on"), not something a failure here
    # should turn into the whole login failing. Called from inside
    # replace_credentials()'s rollback-protected try block -- letting
    # CredentialsFileCorrupt propagate would trigger a snapshot
    # rollback and re-raise, reporting a hard login failure over a step
    # that was only ever cleaning up STALE data, for a file that was
    # already broken before this login ever started. Log and skip the
    # file-side cleanup instead; the keyring-side cleanup above already
    # ran regardless.
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


def _resolve_current_active_kind(instance: str) -> Optional[str]:
    """Best-effort resolution of the credential kind currently in effect
    for ``instance``, mirroring ``AppState.sdk()``'s own precedence (the
    active_kind marker first, then bearer-over-api_key) via the
    TOLERANT reads -- ``load_active_credential_kind``/``load_bearer_token``/
    ``load_api_key`` already degrade a corrupt credentials.toml to
    "nothing here, check the other backend" -- so this can run safely
    before ``replace_credentials`` knows whether the file is healthy.

    fix(#1778 review round 23): ``replace_credentials`` needs to know,
    BEFORE storing anything, whether this login is about to CHANGE the
    active kind (bearer -> api_key or back) so it can decide how
    strictly to treat the marker write below.
    """
    marker = load_active_credential_kind(instance)
    if marker is not None:
        return marker
    if load_bearer_token(instance) is not None:
        return "bearer"
    if load_api_key(instance) is not None:
        return "api_key"
    return None


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

    ``kind`` is ``"bearer"`` or ``"api_key"``. Returns ``'keyring'`` or
    ``'file'`` (where the new credential landed).
    """
    if kind not in ("bearer", "api_key"):
        raise ValueError(f"unknown credential kind: {kind!r}")

    snapshot = _snapshot_credentials(instance)

    previous_kind = _resolve_current_active_kind(instance)
    kind_changed = previous_kind is not None and previous_kind != kind

    # fix(#1778 review round 23): a kind swap (bearer -> api_key or back)
    # makes the active_kind marker written below load-bearing, not mere
    # tidiness -- it is the ONLY thing that keeps a still-lingering OLD
    # credential in the other backend from outranking the one this login
    # is about to store (AppState.sdk() falls back to bearer-first
    # precedence whenever the marker is missing or stale). Round 22 let
    # a corrupt file swallow that write to a warning and carry on
    # regardless of kind -- fine for a same-kind re-login (nothing about
    # precedence changes), wrong for a swap: login would report success
    # while quietly leaving the OLD kind in charge. Refuse UP FRONT here,
    # before the new secret is stored anywhere, so a refusal leaves both
    # backends exactly as they were -- unlike the marker-write failure
    # handled below, which can only roll back what THIS call already
    # stored.
    if kind_changed:
        ensure_credentials_file_readable()

    # fix(#1778 review round 23): mirrors _delete_stale_credentials's own
    # round-14 _UNKNOWN gate for the SAME (old-kind) keyring account --
    # when the pre-swap snapshot could not read it, that cleanup skips
    # it below rather than risk deleting something it never actually
    # saw. The marker is what makes a skipped, still-lingering old
    # credential harmless; if the marker write ITSELF then also fails,
    # nothing stops that old credential from resurfacing under
    # AppState.sdk()'s bearer-first fallback. Detected here (rather than
    # inside _delete_stale_credentials, which runs after the marker
    # write) so the marker's own except block below can decide whether
    # to treat a failure there as fatal.
    old_kind = "api_key" if kind == "bearer" else "bearer"
    old_kind_snapshot = (
        snapshot.keyring_api_key if old_kind == "api_key" else snapshot.keyring_bearer
    )
    mandatory_marker = kind_changed and old_kind_snapshot is _UNKNOWN

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
    try:
        try:
            _set_credential_field(instance, _ACTIVE_KIND_FIELD, kind)
        except CredentialsFileCorrupt as exc:
            if mandatory_marker:
                # fix(#1778 review round 23): unlike the ordinary case
                # below, there is no stale-entry safety net here -- the
                # old kind's keyring entry could not be verified or
                # deleted (round 14's _UNKNOWN gate on
                # _delete_stale_credentials, computed above as
                # old_kind_snapshot), so the marker is the ONLY thing
                # standing between this login and a silent fallback to
                # the OLD credential. Propagate so the outer except
                # rolls the whole swap back -- the secret just stored a
                # few lines up is removed, and the untouched old
                # credential is left exactly where it was.
                raise
            # fix(#1778 review round 22): a PRE-EXISTING corrupt
            # credentials.toml is not something THIS login broke, and
            # the primary credential already landed safely in
            # `backend` a few lines up -- refusing to touch the file
            # (not overwriting it with a marker-only "fresh" version
            # that would destroy every OTHER instance's file-backed
            # credentials sitting in that same unparseable file) is
            # strictly safer than either silently overwriting it or
            # failing the whole login over a marker round 10 already
            # documented as tidiness, not correctness-bearing. Unlike
            # an ORDINARY marker-write failure (round 11, which DOES
            # roll back and fail the login -- the file was healthy a
            # moment ago there and something just broke a write we
            # could have trusted), this file was never trustworthy to
            # begin with. Printed via _warn_credentials_file_corrupt()
            # (a human-readable sentence, not log.warning()'s key=value
            # dump -- see that function's own docstring, round 24) so
            # the operator actually notices it.
            _warn_credentials_file_corrupt(exc)
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
                instance, refresh_token, no_keyring=(backend != "keyring")
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
    backend = store_bearer_token(instance, new_access, no_keyring=no_keyring)
    new_refresh = getattr(parsed, "refresh_token", None)
    if new_refresh:
        store_refresh_token(instance, new_refresh, no_keyring=(backend != "keyring"))
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

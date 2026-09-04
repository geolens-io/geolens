# SPDX-License-Identifier: Apache-2.0
"""fix(#1778 round 30): the class-closing test for the credential-
resolution state matrix.

Round 30's finding: if credentials.toml becomes malformed after a
successful kind switch, load_active_credential_kind() used to treat
the marker as absent and resolution fell back to legacy bearer-first
precedence. In the supported case where an API-key login left an old
bearer in the keyring (round 14's best-effort cleanup gate skips an
unverifiable delete), repairing the keyring while the file stayed
corrupt made later commands silently authenticate with the stale
bearer instead of the active API key.

Every round since 22 patched one CELL of the same underlying decision
("given the marker and the keyring, which credential is active?").
This file pins the WHOLE table instead, against
auth.resolve_active_credential() (the one precedence implementation
round 30 introduced -- see its own docstring in auth.py) exercised
through AppState.sdk(), so it also proves main.py's exception-to-exit-
code translation is right.

Axes:
    marker  in {absent, bearer, api_key, corrupt, unreadable, unknown_value}
    keyring in {none, bearer_only, api_key_only, both}
    env     in {unset, set}

marker=corrupt/unreadable/unknown_value are the three concrete shapes
of "unreadable" named in the round-30 brief (a TOML parse error, an
OS-level permission error, and a value that is neither "bearer" nor
"api_key") -- each must produce the identical KeyringCredentialUnreadable
failure, never silently collapse to "absent".

24 (marker, keyring) combinations x 2 env states = 48 matrix rows.

fix(#1807): plus one row the table's axes cannot express, at the
bottom of this file -- the BACKEND itself moving mid-rotation, when
store_bearer_token() falls back from the keyring to credentials.toml
and the retained refresh token has to follow it. See that section's
own comment for the finding.
"""
from __future__ import annotations

import pathlib as _pathlib
from http import HTTPStatus
from types import SimpleNamespace

import pytest
import typer
from keyring.errors import KeyringError

from geolens_cli import auth as _auth
from geolens_cli import config as _config
from geolens_cli import output as _output
from geolens_cli._sdk_helpers import EXIT_AUTH, EXIT_NETWORK
from geolens_cli.main import AppState

INSTANCE = "https://x.example.com/api"
ENV_TOKEN = "env-token-value"


def _make_state() -> AppState:
    return AppState(
        output=_output.Formatter(json_mode=False, quiet=True, verbose=False),
        config=_config.AppConfig(instance=INSTANCE),
    )


# ---------------------------------------------------------------------------
# Row setup: marker and keyring are independent axes. "marker" describes
# ONLY the credentials.toml active_kind field (or its unreadability);
# "keyring" describes ONLY what is physically present in the keyring.
# Neither setup implies anything about the other -- e.g. marker="bearer"
# with keyring="none" is a real, reachable state (the marker survived a
# login whose keyring entry has since been removed out of band).
# ---------------------------------------------------------------------------

MARKER_STATES = ("absent", "bearer", "api_key", "corrupt", "unreadable", "unknown_value")
KEYRING_STATES = ("none", "bearer_only", "api_key_only", "both")


def _setup_marker(marker: str, monkeypatch) -> None:
    if marker == "absent":
        return  # No file at all.
    if marker in ("bearer", "api_key"):
        _auth._set_credential_field(INSTANCE, _auth._ACTIVE_KIND_FIELD, marker)
        return
    if marker == "unknown_value":
        _auth._set_credential_field(
            INSTANCE, _auth._ACTIVE_KIND_FIELD, "totally-bogus-kind"
        )
        return
    if marker == "corrupt":
        path = _config.credentials_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"this is not valid TOML [[[ = = =\n")
        return
    if marker == "unreadable":
        # A syntactically fine file -- write it FIRST, then block the
        # read itself (a permission error), simulating a file that
        # parses fine but the process can no longer read.
        _auth._set_credential_field(INSTANCE, _auth._ACTIVE_KIND_FIELD, "bearer")
        target = _config.credentials_path()
        real_read_text = _pathlib.Path.read_text

        def flaky_read_text(self, *a, **k):
            if self == target:
                raise PermissionError("permission denied")
            return real_read_text(self, *a, **k)

        monkeypatch.setattr(_pathlib.Path, "read_text", flaky_read_text)
        return
    raise AssertionError(f"unhandled marker state: {marker!r}")


def _setup_keyring(mock_keyring: dict, keyring_state: str) -> None:
    if keyring_state in ("bearer_only", "both"):
        mock_keyring[("geolens", INSTANCE)] = "kr-bearer-token"
    if keyring_state in ("api_key_only", "both"):
        mock_keyring[("geolens", f"{INSTANCE}:api_key")] = "kr-api-key"


# ---------------------------------------------------------------------------
# The table itself (env UNSET). Each value is the expected outcome:
# ("ok", credential_kind, token_value) for a successful resolution, or
# ("error", exception_class, exit_code) for a refusal.
# ---------------------------------------------------------------------------

MATRIX_ENV_UNSET = {
    # marker=absent: legacy bearer-over-api_key precedence applies
    # ONLY when at most one kind is genuinely present (round 30) --
    # both present with nothing to disambiguate is now an error, not
    # a silent bearer-first guess.
    ("absent", "none"): ("ok", "anonymous", None),
    ("absent", "bearer_only"): ("ok", "bearer", "kr-bearer-token"),
    ("absent", "api_key_only"): ("ok", "api_key", "kr-api-key"),
    ("absent", "both"): ("error", _auth.CredentialAmbiguous, EXIT_AUTH),
    # marker=bearer: authoritative (round 27) -- api_key in the
    # keyring is NEVER consulted, present or not.
    ("bearer", "none"): ("error", _auth.ActiveCredentialMissing, EXIT_AUTH),
    ("bearer", "bearer_only"): ("ok", "bearer", "kr-bearer-token"),
    ("bearer", "api_key_only"): ("error", _auth.ActiveCredentialMissing, EXIT_AUTH),
    ("bearer", "both"): ("ok", "bearer", "kr-bearer-token"),
    # marker=api_key: mirror of bearer.
    ("api_key", "none"): ("error", _auth.ActiveCredentialMissing, EXIT_AUTH),
    ("api_key", "bearer_only"): ("error", _auth.ActiveCredentialMissing, EXIT_AUTH),
    ("api_key", "api_key_only"): ("ok", "api_key", "kr-api-key"),
    ("api_key", "both"): ("ok", "api_key", "kr-api-key"),
    # marker=corrupt / unreadable / unknown_value: round 30's own
    # finding -- NEVER collapses to "absent", regardless of what the
    # keyring holds. All three unreadable shapes behave identically.
    ("corrupt", "none"): ("error", _auth.KeyringCredentialUnreadable, EXIT_NETWORK),
    ("corrupt", "bearer_only"): ("error", _auth.KeyringCredentialUnreadable, EXIT_NETWORK),
    ("corrupt", "api_key_only"): ("error", _auth.KeyringCredentialUnreadable, EXIT_NETWORK),
    ("corrupt", "both"): ("error", _auth.KeyringCredentialUnreadable, EXIT_NETWORK),
    ("unreadable", "none"): ("error", _auth.KeyringCredentialUnreadable, EXIT_NETWORK),
    ("unreadable", "bearer_only"): ("error", _auth.KeyringCredentialUnreadable, EXIT_NETWORK),
    ("unreadable", "api_key_only"): ("error", _auth.KeyringCredentialUnreadable, EXIT_NETWORK),
    ("unreadable", "both"): ("error", _auth.KeyringCredentialUnreadable, EXIT_NETWORK),
    ("unknown_value", "none"): ("error", _auth.KeyringCredentialUnreadable, EXIT_NETWORK),
    ("unknown_value", "bearer_only"): ("error", _auth.KeyringCredentialUnreadable, EXIT_NETWORK),
    ("unknown_value", "api_key_only"): ("error", _auth.KeyringCredentialUnreadable, EXIT_NETWORK),
    ("unknown_value", "both"): ("error", _auth.KeyringCredentialUnreadable, EXIT_NETWORK),
}

assert set(MATRIX_ENV_UNSET) == {(m, k) for m in MARKER_STATES for k in KEYRING_STATES}, (
    "the table above must cover every (marker, keyring) cell exactly once"
)


class TestCredentialResolutionMatrixEnvUnset:
    """24 rows: every (marker, keyring) cell with GEOLENS_TOKEN unset."""

    @pytest.mark.parametrize(
        "marker,keyring_state", sorted(MATRIX_ENV_UNSET), ids=lambda v: str(v)
    )
    def test_matrix_row(
        self, tmp_xdg_home, mock_keyring, monkeypatch, marker: str, keyring_state: str
    ) -> None:
        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        _setup_marker(marker, monkeypatch)
        _setup_keyring(mock_keyring, keyring_state)

        expected = MATRIX_ENV_UNSET[(marker, keyring_state)]
        state = _make_state()

        if expected[0] == "ok":
            _, kind, token_value = expected
            sdk = state.sdk()
            assert sdk.credential_kind == kind, (marker, keyring_state)
            if kind != "anonymous":
                assert sdk.client.token == token_value, (marker, keyring_state)
        else:
            _, exc_cls, exit_code = expected
            with pytest.raises(typer.Exit) as exc_info:
                state.sdk()
            assert exc_info.value.exit_code == exit_code, (marker, keyring_state)
            # The exception typer.Exit was raised `from` is the one the
            # table names -- confirms the RIGHT failure mode fired, not
            # just that something raised.
            assert isinstance(exc_info.value.__cause__, exc_cls), (
                marker,
                keyring_state,
                exc_info.value.__cause__,
            )


class TestCredentialResolutionMatrixEnvSet:
    """The other 24 rows: GEOLENS_TOKEN always wins outright, regardless
    of marker or keyring state -- D-35's top precedence, already
    ratified, pinned here across the SAME 24 (marker, keyring) cells so
    the env axis is proven independent of the rest of the matrix."""

    @pytest.mark.parametrize(
        "marker,keyring_state", sorted(MATRIX_ENV_UNSET), ids=lambda v: str(v)
    )
    def test_matrix_row_env_always_wins(
        self, tmp_xdg_home, mock_keyring, monkeypatch, marker: str, keyring_state: str
    ) -> None:
        monkeypatch.setenv("GEOLENS_TOKEN", ENV_TOKEN)
        _setup_marker(marker, monkeypatch)
        _setup_keyring(mock_keyring, keyring_state)

        state = _make_state()
        sdk = state.sdk()

        assert sdk.credential_kind == "bearer"
        assert sdk.credential_provenance == "env"
        assert sdk.client.token == ENV_TOKEN


# ---------------------------------------------------------------------------
# fix(#1807): the backend-fallback row of the refresh pairing matrix.
#
# Every row above holds the BACKEND fixed: a credential written to the
# keyring stays in the keyring. store_bearer_token() can break that on
# its own, though -- a transient or account-specific KeyringError makes
# it fall back to credentials.toml even when the caller asked for the
# keyring -- and try_refresh()'s "the server issued no new refresh
# token" branch used to move only the pairing fingerprint with it,
# leaving the retained refresh token behind in the keyring.
#
# The next refresh then read the two halves from different backends:
# _detect_credential_backend() looks for a refresh_token in the FILE,
# found none, answered "keyring," and wrote the newly rotated bearer
# there -- where the stale file-backed bearer written by the fallback
# outranks it under load_bearer_token()'s file-over-keyring precedence.
# Every later command 401s, refreshes, 401s again, and never converges.
#
# This row drives the whole sequence through the real CLI: a bearer
# whose keyring write fails once, a refresh response with no
# replacement refresh token, then a second expiry with the keyring
# healthy again.
# ---------------------------------------------------------------------------

OLD_BEARER = "kr-bearer-token-expired"
RETAINED_REFRESH = "kr-refresh-token-retained"


class _FakeAuthServer:
    """A /auth/me + /auth/refresh pair where only the most recently
    issued access token is accepted, and a refresh never issues a
    replacement refresh token (the exact response shape this row is
    about)."""

    def __init__(self) -> None:
        self.issued: list[str] = []
        self.refresh_calls = 0
        self.accepted: set[str] = set()

    def issue(self, token: str) -> str:
        self.issued.append(token)
        self.accepted = {token}
        return token

    def expire_all(self) -> None:
        self.accepted = set()

    def refresh_endpoint(self, **kwargs):
        self.refresh_calls += 1
        rotated = self.issue(f"rotated-access-token-{self.refresh_calls}")
        return SimpleNamespace(
            status_code=HTTPStatus.OK,
            # No replacement refresh token -- the retained one stays valid.
            parsed=SimpleNamespace(access_token=rotated, refresh_token=None),
        )

    def me_endpoint(self, **kwargs):
        presented = getattr(kwargs.get("client"), "token", None)
        if presented not in self.accepted:
            return SimpleNamespace(status_code=HTTPStatus.UNAUTHORIZED, parsed=None)
        return SimpleNamespace(
            status_code=HTTPStatus.OK,
            parsed=SimpleNamespace(email="alice@example.com", id="u-1", role="admin"),
        )


class TestRefreshPairingBackendFallbackRow:
    """fix(#1807): a keyring bearer write that falls back to the file
    must take the RETAINED refresh token and its fingerprint with it,
    and the profile must then converge on the file backend instead of
    refreshing on every command."""

    def _setup(self, mock_keyring, monkeypatch) -> tuple[_FakeAuthServer, dict]:
        # A keyring-backed interactive session: bearer + refresh token
        # + the fingerprint pairing them (round 31).
        mock_keyring[("geolens", INSTANCE)] = OLD_BEARER
        mock_keyring[("geolens", f"{INSTANCE}:refresh")] = RETAINED_REFRESH
        mock_keyring[("geolens", f"{INSTANCE}:refresh_fp")] = _auth._fingerprint_bearer(
            OLD_BEARER
        )
        _config.write_default_instance(INSTANCE, username="alice")

        # The bearer ACCOUNT specifically refuses writes while this flag
        # is on -- store_bearer_token()'s documented fallback trigger.
        # Every other account (and this one, once the flag clears)
        # writes normally.
        fail_bearer_write = {"on": True}

        def flaky_set_password(svc: str, user: str, pwd: str) -> None:
            if fail_bearer_write["on"] and user == INSTANCE:
                raise KeyringError("this account is temporarily locked")
            mock_keyring[(svc, user)] = pwd

        monkeypatch.setattr("keyring.set_password", flaky_set_password)

        server = _FakeAuthServer()
        server.issue(OLD_BEARER)
        server.expire_all()  # the stored bearer is already expired
        monkeypatch.setattr(
            "geolens.api.auth.refresh_auth_refresh_post.sync_detailed",
            server.refresh_endpoint,
        )
        monkeypatch.setattr(
            "geolens.api.auth.me_auth_me_get.sync_detailed", server.me_endpoint
        )
        return server, fail_bearer_write

    def test_retained_refresh_token_follows_the_bearer_into_the_file(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        server, _ = self._setup(mock_keyring, monkeypatch)

        result = runner.invoke(app, ["whoami"])

        assert result.exit_code == 0, result.output
        assert server.refresh_calls == 1
        rotated = server.issued[-1]

        section = _auth._read_credentials_file()[INSTANCE]
        assert section["bearer_token"] == rotated, (
            "the keyring write failed, so the rotated bearer must be in the file"
        )
        assert section["refresh_token"] == RETAINED_REFRESH, (
            "the retained refresh token must move to the bearer's ACTUAL "
            "backend, not stay behind in the keyring"
        )
        assert section["refresh_fingerprint"] == _auth._fingerprint_bearer(rotated), (
            "the fingerprint must pair the retained token with the NEW bearer"
        )
        assert ("geolens", f"{INSTANCE}:refresh") not in mock_keyring, (
            "the superseded keyring copy of the refresh token must be dropped"
        )
        assert ("geolens", f"{INSTANCE}:refresh_fp") not in mock_keyring, (
            "the superseded keyring copy of the fingerprint must be dropped"
        )

    def test_the_next_refresh_converges_instead_of_looping(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        server, fail_bearer_write = self._setup(mock_keyring, monkeypatch)

        # 1. The expired stored bearer 401s, the fallback rotation runs.
        assert runner.invoke(app, ["whoami"]).exit_code == 0
        assert server.refresh_calls == 1

        # 2. That rotated token expires too, with the keyring healthy
        #    again -- the state the loop used to start from.
        fail_bearer_write["on"] = False
        server.expire_all()
        assert runner.invoke(app, ["whoami"]).exit_code == 0
        assert server.refresh_calls == 2

        # 3. Nothing has expired since, so this command must simply use
        #    the credential step 2 stored. Before the fix it read the
        #    stale file bearer (step 2 wrote its rotation to the
        #    keyring, where the file shadows it) and refreshed again.
        result = runner.invoke(app, ["whoami"])
        assert result.exit_code == 0, result.output
        assert server.refresh_calls == 2, (
            "a converged profile must not refresh again -- the bearer "
            "resolved here is shadowed by a stale copy in the other backend"
        )
        resolved = _auth.load_bearer_token(INSTANCE)
        assert resolved is not None and resolved.value == server.issued[-1]


# ---------------------------------------------------------------------------
# fix(#1807 round 2): the row above's mirror -- the backend does NOT move,
# and the retained refresh token's own keyring account is the one refusing
# writes (readable, and paired to a bearer that just rotated; the bearer and
# fingerprint accounts still accept writes) with no usable credentials.toml
# behind it.
#
# Rewriting the whole retained pair here, as the first cut of #1807 did,
# asks that account for a write of a secret that did not change -- the
# write fails, the file fallback fails, and try_refresh() reports a
# rotation the server already performed as a failure, with the new bearer
# stored against the OLD fingerprint. The next attempt then reads that
# mismatch and discards a still-valid refresh token as unpaired. Updating
# only the fingerprint member, in place, completes the rotation.
# ---------------------------------------------------------------------------


class TestRefreshPairingRefreshAccountWriteRejectedRow:
    """fix(#1807 round 2): a retained refresh token whose backend did not
    move must not be rewritten -- only the fingerprint pairing it to the
    new bearer is stale, and the account holding the token may well
    refuse the write."""

    def _setup(self, mock_keyring, monkeypatch) -> _FakeAuthServer:
        mock_keyring[("geolens", INSTANCE)] = OLD_BEARER
        mock_keyring[("geolens", f"{INSTANCE}:refresh")] = RETAINED_REFRESH
        mock_keyring[("geolens", f"{INSTANCE}:refresh_fp")] = _auth._fingerprint_bearer(
            OLD_BEARER
        )
        _config.write_default_instance(INSTANCE, username="alice")

        # The refresh ACCOUNT alone rejects writes; it stays readable,
        # and the bearer + fingerprint accounts write normally.
        def picky_set_password(svc: str, user: str, pwd: str) -> None:
            if user == f"{INSTANCE}:refresh":
                raise KeyringError("this account is not writable")
            mock_keyring[(svc, user)] = pwd

        monkeypatch.setattr("keyring.set_password", picky_set_password)

        # ...and there is no credentials.toml fallback behind it, so a
        # write that reaches the file fails outright rather than quietly
        # succeeding in the other backend.
        def unwritable(*_a, **_k):
            raise OSError("read-only file system")

        monkeypatch.setattr(_auth, "_write_credentials_file", unwritable)

        server = _FakeAuthServer()
        server.issue(OLD_BEARER)
        server.expire_all()
        monkeypatch.setattr(
            "geolens.api.auth.refresh_auth_refresh_post.sync_detailed",
            server.refresh_endpoint,
        )
        monkeypatch.setattr(
            "geolens.api.auth.me_auth_me_get.sync_detailed", server.me_endpoint
        )
        return server

    def test_only_the_fingerprint_is_rewritten_when_the_backend_did_not_move(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli.main import app

        server = self._setup(mock_keyring, monkeypatch)

        result = runner.invoke(app, ["whoami"])

        assert result.exit_code == 0, result.output
        assert server.refresh_calls == 1
        rotated = server.issued[-1]

        assert mock_keyring[("geolens", INSTANCE)] == rotated
        assert mock_keyring[
            ("geolens", f"{INSTANCE}:refresh_fp")
        ] == _auth._fingerprint_bearer(rotated), (
            "the fingerprint is the only member that went stale -- it must "
            "be updated in place, in the backend the pair already lives in"
        )
        assert mock_keyring[("geolens", f"{INSTANCE}:refresh")] == RETAINED_REFRESH, (
            "the retained token itself did not change; rewriting it needs a "
            "write this account refuses"
        )
        assert not _config.credentials_path().exists(), (
            "nothing should have been pushed to the file backend here"
        )

        # Still paired on the next resolve: the rotated bearer expires,
        # and the retained token is spent again rather than discarded as
        # unpaired.
        server.expire_all()
        result = runner.invoke(app, ["whoami"])
        assert result.exit_code == 0, result.output
        assert server.refresh_calls == 2
        assert mock_keyring[("geolens", f"{INSTANCE}:refresh")] == RETAINED_REFRESH

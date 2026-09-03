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
"""
from __future__ import annotations

import pathlib as _pathlib

import pytest
import typer

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

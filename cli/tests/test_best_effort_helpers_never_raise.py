# SPDX-License-Identifier: Apache-2.0
"""fix(#1778 round 32): every cleanup helper documented as "best-effort"
must actually be non-raising. _discard_unpaired_refresh_token() claimed
this in its own docstring, but its file WRITE was unguarded -- an
unwritable credentials.toml raised straight out of it, past
try_refresh() (which has no rollback net the way replace_credentials()
does), so whoami/status died with a storage traceback instead of the
normal auth error this whole call chain exists to produce cleanly.

Enumerated here, each pinned with a raising-sink test that simulates
every failure point the helper's own docstring claims to tolerate:

- _discard_unpaired_refresh_token() -- keyring deletes AND the file
  read/write, all raising.
- _delete_keyring_refresh_entries() -- its keyring half, which
  fix(#1807) factored out for try_refresh()'s backend-fallback path
  and which carries the same contract.
- _restore_credentials() -- keyring deletes/sets AND the file
  read/write, all raising.
- delete_credentials()'s own keyring loop -- all four accounts raising
  (the file clear at the end is INTENTIONALLY NOT best-effort, per
  round 22: logout must refuse on a corrupt file, so that part is not
  pinned here).
"""
from __future__ import annotations

from keyring.errors import KeyringError

from geolens_cli import auth as _auth
from geolens_cli import config as _config

INSTANCE = "https://x.example.com/api"


def _raise_keyring_error(*_a, **_k):
    raise KeyringError("keyring locked")


def _raise_os_error(*_a, **_k):
    raise OSError("read-only file system")


class TestDiscardUnpairedRefreshTokenNeverRaises:
    def test_both_keyring_deletes_raise(self, tmp_xdg_home, mock_keyring, monkeypatch) -> None:
        monkeypatch.setattr("keyring.delete_password", _raise_keyring_error)
        # Must not raise.
        _auth._discard_unpaired_refresh_token(INSTANCE)

    def test_file_read_raises_corrupt(self, tmp_xdg_home, mock_keyring, monkeypatch) -> None:
        path = _config.credentials_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not valid toml [[[ = = =\n")
        # Must not raise -- CredentialsFileCorrupt is caught inside.
        _auth._discard_unpaired_refresh_token(INSTANCE)

    def test_file_write_raises_os_error(self, tmp_xdg_home, mock_keyring, monkeypatch) -> None:
        # A real refresh_token field so the write path is actually
        # reached (an empty section returns early with nothing to do).
        # A SECOND, unrelated instance keeps the file non-empty after
        # this instance's section is cleared, so the code takes the
        # _write_credentials_file() branch rather than the "delete the
        # whole file" branch -- otherwise this test would never
        # exercise the write failure it exists to pin.
        _auth._set_credential_field(INSTANCE, "refresh_token", "some-refresh-token")
        _auth._set_credential_field("https://other.example.com/api", "bearer_token", "x")
        monkeypatch.setattr(_auth, "_write_credentials_file", _raise_os_error)
        # Must not raise -- this is the exact finding round 32 fixes.
        _auth._discard_unpaired_refresh_token(INSTANCE)


class TestRestoreCredentialsNeverRaises:
    def _snapshot_with_real_values(self) -> "_auth._CredentialSnapshot":
        return _auth._CredentialSnapshot(
            keyring_bearer="old-bearer",
            keyring_api_key="old-api-key",
            keyring_refresh="old-refresh",
            keyring_refresh_fingerprint="old-fingerprint",
            file_section={"bearer_token": "old-bearer"},
        )

    def test_keyring_set_and_delete_raise(self, tmp_xdg_home, mock_keyring, monkeypatch) -> None:
        monkeypatch.setattr("keyring.set_password", _raise_keyring_error)
        monkeypatch.setattr("keyring.delete_password", _raise_keyring_error)
        # Must not raise.
        _auth._restore_credentials(INSTANCE, self._snapshot_with_real_values())

    def test_file_write_raises_os_error(self, tmp_xdg_home, mock_keyring, monkeypatch) -> None:
        monkeypatch.setattr(_auth, "_write_credentials_file", _raise_os_error)
        # Must not raise.
        _auth._restore_credentials(INSTANCE, self._snapshot_with_real_values())

    def test_file_read_raises_corrupt(self, tmp_xdg_home, mock_keyring, monkeypatch) -> None:
        path = _config.credentials_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not valid toml [[[ = = =\n")
        # Must not raise -- CredentialsFileCorrupt is caught inside.
        _auth._restore_credentials(INSTANCE, self._snapshot_with_real_values())


class TestDeleteCredentialsKeyringLoopNeverRaises:
    """logout's file-side _clear_credential_section() is deliberately
    NOT best-effort (round 22: a corrupt file must make logout refuse,
    not silently rewrite it empty) -- only the keyring loop's own
    documented "missing entries are silently ignored" contract is
    pinned here."""

    def test_all_four_keyring_deletes_raise(
        self, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        monkeypatch.setattr("keyring.delete_password", _raise_keyring_error)
        # Must not raise -- the file is healthy, so _clear_credential_
        # section() at the end completes normally too.
        _auth.delete_credentials(INSTANCE)


class TestDeleteKeyringRefreshEntriesNeverRaises:
    """fix(#1807): the keyring half of _discard_unpaired_refresh_token(),
    factored out because try_refresh() needs exactly that half on its
    own when a rotation falls back to the file (the file side there
    holds the copy that must survive). It inherits the same
    never-raises contract, so it is enumerated here too."""

    def test_both_keyring_deletes_raise(
        self, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        monkeypatch.setattr("keyring.delete_password", _raise_keyring_error)
        # Must not raise.
        _auth._delete_keyring_refresh_entries(INSTANCE)

    def test_keyring_deletes_raise_os_error(
        self, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        monkeypatch.setattr("keyring.delete_password", _raise_os_error)
        # Must not raise -- some keyring backends surface an OSError
        # rather than a KeyringError.
        _auth._delete_keyring_refresh_entries(INSTANCE)

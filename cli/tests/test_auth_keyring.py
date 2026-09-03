"""Auth module — keyring + file fallback + refresh-retry."""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from geolens_cli import auth as _auth
from geolens_cli import config as _config


INSTANCE = "https://test.example.com"


class TestKeyringStore:
    def test_store_bearer_uses_keyring(self, tmp_xdg_home, mock_keyring) -> None:
        backend = _auth.store_bearer_token(INSTANCE, "tok-1")
        assert backend == "keyring"
        assert mock_keyring[("geolens", INSTANCE)] == "tok-1"

    def test_store_api_key_uses_keyring(self, tmp_xdg_home, mock_keyring) -> None:
        backend = _auth.store_api_key(INSTANCE, "key-1")
        assert backend == "keyring"
        assert mock_keyring[("geolens", f"{INSTANCE}:api_key")] == "key-1"

    def test_store_refresh_uses_keyring(self, tmp_xdg_home, mock_keyring) -> None:
        backend = _auth.store_refresh_token(INSTANCE, "ref-1")
        assert backend == "keyring"
        assert mock_keyring[("geolens", f"{INSTANCE}:refresh")] == "ref-1"

    def test_load_bearer_from_keyring(self, tmp_xdg_home, mock_keyring) -> None:
        mock_keyring[("geolens", INSTANCE)] = "tok-2"
        tok = _auth.load_bearer_token(INSTANCE)
        assert tok is not None
        assert tok.value == "tok-2"

    def test_load_returns_none_when_missing(self, tmp_xdg_home, mock_keyring) -> None:
        assert _auth.load_bearer_token(INSTANCE) is None
        assert _auth.load_api_key(INSTANCE) is None
        assert _auth.load_refresh_token(INSTANCE) is None


class TestNoKeyringFallback:
    def test_store_bearer_no_keyring_writes_file(self, tmp_xdg_home, mock_keyring) -> None:
        backend = _auth.store_bearer_token(INSTANCE, "tok-3", no_keyring=True)
        assert backend == "file"
        # Token should NOT be in keyring
        assert ("geolens", INSTANCE) not in mock_keyring
        # File should contain the token
        text = _config.credentials_path().read_text()
        assert "tok-3" in text

    @pytest.mark.skipif(os.name == "nt", reason="POSIX file modes only")
    def test_credentials_file_mode_0600(self, tmp_xdg_home, mock_keyring) -> None:
        _auth.store_bearer_token(INSTANCE, "tok-4", no_keyring=True)
        actual_mode = stat.S_IMODE(_config.credentials_path().stat().st_mode)
        assert actual_mode == 0o600

    def test_load_bearer_from_file(self, tmp_xdg_home, mock_keyring) -> None:
        _auth.store_bearer_token(INSTANCE, "tok-5", no_keyring=True)
        tok = _auth.load_bearer_token(INSTANCE)
        assert tok is not None
        assert tok.value == "tok-5"


class TestKeyringErrorAutoFallback:
    def test_keyring_error_falls_back_to_file(self, tmp_xdg_home, monkeypatch) -> None:
        from keyring.errors import NoKeyringError

        def explode(*args, **kwargs):
            raise NoKeyringError("no backend")

        monkeypatch.setattr("keyring.set_password", explode)
        backend = _auth.store_bearer_token(INSTANCE, "tok-6")
        assert backend == "file"
        text = _config.credentials_path().read_text()
        assert "tok-6" in text


class TestEnvOverride:
    def test_env_token_takes_precedence(self, tmp_xdg_home, mock_keyring, monkeypatch) -> None:
        mock_keyring[("geolens", INSTANCE)] = "tok-from-keyring"
        monkeypatch.setenv("GEOLENS_TOKEN", "tok-from-env")
        tok = _auth.load_bearer_token(INSTANCE)
        assert tok is not None
        assert tok.value == "tok-from-env"


class TestDeleteCredentials:
    def test_delete_clears_keyring_and_file(self, tmp_xdg_home, mock_keyring) -> None:
        _auth.store_bearer_token(INSTANCE, "tok", no_keyring=False)
        _auth.store_refresh_token(INSTANCE, "ref", no_keyring=False)
        _auth.store_api_key(INSTANCE, "key", no_keyring=True)  # this one in file
        _auth.delete_credentials(INSTANCE)
        # Keyring entries gone
        assert ("geolens", INSTANCE) not in mock_keyring
        assert ("geolens", f"{INSTANCE}:refresh") not in mock_keyring
        # File entry gone
        assert _auth.load_api_key(INSTANCE) is None

    def test_delete_idempotent_when_nothing_stored(self, tmp_xdg_home, mock_keyring) -> None:
        _auth.delete_credentials(INSTANCE)  # should not raise


class TestTryRefreshBackendRouting:
    """BUG-013: try_refresh must write rotated tokens back to the SAME backend."""

    def _patch_sdk_refresh(self, monkeypatch, new_access: str, new_refresh: str) -> None:
        """Patch the GeolensClient + SDK refresh call so no real HTTP occurs.

        try_refresh uses lazy 'from X import Y' inside the function body.
        We pre-import those modules and patch their attributes so the
        already-cached sys.modules entries are used at call time.
        """
        from unittest.mock import MagicMock
        import geolens
        import geolens.api.auth.refresh_auth_refresh_post as _refresh_mod
        import geolens.models.refresh_request as _refresh_req_mod

        class FakeParsed:
            pass

        parsed = FakeParsed()
        parsed.access_token = new_access
        parsed.refresh_token = new_refresh

        class FakeResp:
            status_code = 200

        FakeResp.parsed = parsed

        monkeypatch.setattr(geolens, "GeolensClient", MagicMock())
        monkeypatch.setattr(_refresh_mod, "sync_detailed", MagicMock(return_value=FakeResp()))
        monkeypatch.setattr(_refresh_req_mod, "RefreshRequest", MagicMock())

    def test_file_backend_refresh_writes_to_file_not_keyring(
        self, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """Credential stored in FILE backend — refresh must stay in file."""
        # Store the initial credential in the FILE backend.
        _auth.store_bearer_token(INSTANCE, "old-access", no_keyring=True)
        _auth.store_refresh_token(INSTANCE, "old-refresh", no_keyring=True)

        self._patch_sdk_refresh(monkeypatch, "new-access", "new-refresh")

        new_tok = _auth.try_refresh(INSTANCE)
        assert new_tok == "new-access"

        # New access token must be in the FILE — not in keyring.
        file_data = _config.credentials_path().read_text()
        assert "new-access" in file_data
        assert ("geolens", INSTANCE) not in mock_keyring, (
            "BUG-013: refresh wrote to keyring even though original credential was in file"
        )

        # New refresh token must be in the FILE — not in keyring.
        assert "new-refresh" in file_data
        assert ("geolens", f"{INSTANCE}:refresh") not in mock_keyring, (
            "BUG-013: refresh_token written to keyring; should stay in file"
        )

    def test_keyring_backend_refresh_writes_to_keyring(
        self, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """Credential stored in KEYRING backend — refresh must stay in keyring."""
        _auth.store_bearer_token(INSTANCE, "old-access", no_keyring=False)
        _auth.store_refresh_token(INSTANCE, "old-refresh", no_keyring=False)

        self._patch_sdk_refresh(monkeypatch, "new-access-kr", "new-refresh-kr")

        new_tok = _auth.try_refresh(INSTANCE)
        assert new_tok == "new-access-kr"

        # Access token must be in keyring.
        assert mock_keyring.get(("geolens", INSTANCE)) == "new-access-kr", (
            "BUG-013: refresh did not write new access token to keyring"
        )
        # Refresh token must be in keyring.
        assert mock_keyring.get(("geolens", f"{INSTANCE}:refresh")) == "new-refresh-kr", (
            "BUG-013: refresh did not write new refresh token to keyring"
        )

    def test_a_bearer_write_failure_during_rotation_keeps_both_tokens_together(
        self, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """fix(#1778 review round 17): the sibling of round 15's
        replace_credentials() bug, in try_refresh()'s own rotation
        path. The original credential lives in the keyring (so
        _detect_credential_backend says no_keyring=False going in),
        but the ROTATED access token's keyring write fails for the
        bearer account specifically -- store_bearer_token() catches
        that and falls back to the file, returning backend == "file".
        The refresh account's OWN set_password is left free to
        succeed. Before this fix, the refresh write still used the
        original no_keyring=False and would have landed in the
        keyring, splitting the two rotated tokens across backends."""
        import keyring
        from keyring.errors import KeyringError

        # Original session lives in the keyring.
        _auth.store_bearer_token(INSTANCE, "old-access", no_keyring=False)
        _auth.store_refresh_token(INSTANCE, "old-refresh", no_keyring=False)
        # A prior login already set the marker, as replace_credentials()
        # always does -- try_refresh must keep it consistent, not leave
        # it untouched by accident.
        _auth._set_credential_field(INSTANCE, _auth._ACTIVE_KIND_FIELD, "bearer")

        self._patch_sdk_refresh(monkeypatch, "new-access", "new-refresh")

        original_set = keyring.set_password  # mock_keyring's dict-backed one
        bearer_account = INSTANCE

        def failing_set(service, username, password):
            if username == bearer_account:
                raise KeyringError("locked keychain needs a write unlock")
            return original_set(service, username, password)

        monkeypatch.setattr("keyring.set_password", failing_set)

        new_tok = _auth.try_refresh(INSTANCE)
        assert new_tok == "new-access"

        # Both rotated tokens land in the FILE together -- not split
        # across backends.
        file_section = _auth._read_credentials_file().get(INSTANCE, {})
        assert file_section.get("bearer_token") == "new-access"
        assert file_section.get("refresh_token") == "new-refresh"
        # The refresh account's keyring entry was never even asked --
        # it would have accepted the write if it had been.
        assert ("geolens", f"{INSTANCE}:refresh") not in mock_keyring or (
            mock_keyring.get(("geolens", f"{INSTANCE}:refresh")) == "old-refresh"
        )
        # The marker stays consistent with the rotation.
        assert _auth.load_active_credential_kind(INSTANCE) == "bearer"

    def test_an_unwritable_config_file_does_not_fail_a_keyring_backed_refresh(
        self, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """fix(#1778 review round 19) P2 pin (a): the active_kind marker
        write used to be unconditional AND fatal. When both rotated
        tokens land safely in the keyring but credentials.toml itself
        is unwritable (the marker's only home), the OLD code raised
        straight out of try_refresh() -- reporting a refresh FAILURE
        (D-13: caller prints "Session expired", exits EXIT_AUTH) even
        though the rotation itself fully succeeded. The marker write
        must be non-fatal: try_refresh() still returns the new access
        token, and a subsequent load (what `whoami` uses) resolves it."""
        # Marker starts as something other than "bearer" (here: unset)
        # so the marker write is actually ATTEMPTED, not skipped by
        # pin (b)'s short-circuit below.
        _auth.store_bearer_token(INSTANCE, "old-access", no_keyring=False)
        _auth.store_refresh_token(INSTANCE, "old-refresh", no_keyring=False)
        assert _auth.load_active_credential_kind(INSTANCE) is None

        self._patch_sdk_refresh(monkeypatch, "new-access", "new-refresh")

        def raising_write(*args, **kwargs):
            raise OSError("read-only filesystem")

        monkeypatch.setattr(_auth, "_write_credentials_file", raising_write)

        new_tok = _auth.try_refresh(INSTANCE)

        assert new_tok == "new-access"
        # Both rotated tokens landed in the keyring -- unaffected by
        # the marker write's failure.
        assert mock_keyring.get(("geolens", INSTANCE)) == "new-access"
        assert mock_keyring.get(("geolens", f"{INSTANCE}:refresh")) == "new-refresh"
        # "whoami works": load_bearer_token (what AppState.sdk() uses)
        # resolves the freshly rotated token regardless of the marker.
        loaded = _auth.load_bearer_token(INSTANCE)
        assert loaded is not None
        assert loaded.value == "new-access"

    def test_marker_already_bearer_skips_the_write_entirely(
        self, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """fix(#1778 review round 19) P2 pin (b): try_refresh() only
        ever rotates a bearer session, so if the marker already reads
        "bearer" there is nothing to update -- the write must be
        skipped, not merely tolerated-on-failure. Proven by mocking
        _write_credentials_file to raise unconditionally: if the
        marker write were still attempted, try_refresh() would see
        that raise (even though it's now non-fatal per pin (a)); this
        asserts the writer is never even CALLED."""
        _auth.store_bearer_token(INSTANCE, "old-access", no_keyring=False)
        _auth.store_refresh_token(INSTANCE, "old-refresh", no_keyring=False)
        _auth._set_credential_field(INSTANCE, _auth._ACTIVE_KIND_FIELD, "bearer")
        assert _auth.load_active_credential_kind(INSTANCE) == "bearer"

        self._patch_sdk_refresh(monkeypatch, "new-access", "new-refresh")

        write_calls: list[dict] = []
        original_write = _auth._write_credentials_file

        def tracking_write(data):
            write_calls.append(dict(data))
            return original_write(data)

        monkeypatch.setattr(_auth, "_write_credentials_file", tracking_write)

        new_tok = _auth.try_refresh(INSTANCE)

        assert new_tok == "new-access"
        assert write_calls == [], (
            "the marker write must be skipped entirely when the stored "
            "active_kind is already \"bearer\", not merely attempted "
            "and tolerated"
        )
        assert _auth.load_active_credential_kind(INSTANCE) == "bearer"


def _write_corrupt_credentials_file(instance: str = INSTANCE) -> Path:
    """Write unparseable bytes to credentials.toml directly (bypassing
    every write helper in auth.py, which would refuse) so tests can
    exercise the round-22 corrupt-file handling. Returns the path."""
    path = _config.credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"this is not valid TOML [[[ = = =\n")
    return path


class TestCredentialsFileCorruption:
    """fix(#1778 review round 22): _read_credentials_file() used to
    degrade a TOML parse failure straight to `{}` -- indistinguishable
    from "no file at all." A writer building on that empty dict (the
    active_kind marker write after a keyring-backed login, chief among
    them) would then overwrite the ACTUAL corrupt file with a fresh one
    holding only the current instance's data, silently destroying
    every OTHER instance's file-backed credentials sitting in the
    unparseable file. _read_credentials_file() now raises
    CredentialsFileCorrupt (naming the path and the parser's own
    message); every WRITE path refuses to touch the file on it, while
    READ-with-fallback paths (load_bearer_token and friends,
    try_refresh's own backend detection) still degrade tolerantly so
    an unrelated corrupt file cannot break a flow that does not
    actually need to write it.

    fix(#1778 review round 28): rounds 22-25 each tried to carve out a
    case where a corrupt file was "safe" to tolerate during login
    (same kind unchanged, or the competing kind confirmed absent) --
    round 27 found the second carve-out already wrong (a corrupt FILE
    can itself be holding the competing credential, invisible to a
    keyring-only check). replace_credentials() now refuses EVERY login
    up front on a corrupt file, unconditionally, before anything is
    stored -- see its own docstring. See
    TestLoginRefusesUnconditionallyOnACorruptFile below for the
    consolidated pins; logout (below) and refresh (below) are
    unaffected -- neither goes through replace_credentials()."""

    def test_logout_refuses_with_a_corrupt_file_and_leaves_it_untouched(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """Pin: corrupt file + logout -> refuses, file unchanged."""
        from geolens_cli.main import app
        from geolens_cli import config as _cfg

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        instance = "https://x.example.com"
        canonical = _cfg.normalize_instance_url(instance)
        _auth.store_bearer_token(canonical, "old-bearer-token", no_keyring=False)

        path = _write_corrupt_credentials_file(canonical)
        original_bytes = path.read_bytes()

        result = runner.invoke(app, ["--instance", instance, "logout"])

        assert result.exit_code != 0, result.output
        assert path.read_bytes() == original_bytes, "a refusal must not rewrite the file"
        assert str(path) in result.output

    def test_refresh_rotates_tokens_with_a_corrupt_file_and_logs_a_warning(
        self, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """Pin: corrupt file + refresh -> tokens rotated, file
        unchanged, warning logged."""
        _auth.store_bearer_token(INSTANCE, "old-access", no_keyring=False)
        _auth.store_refresh_token(INSTANCE, "old-refresh", no_keyring=False)

        path = _write_corrupt_credentials_file(INSTANCE)
        original_bytes = path.read_bytes()

        warnings: list[tuple[str, dict]] = []
        original_warning = _auth.log.warning

        def spying_warning(event, **kwargs):
            warnings.append((event, kwargs))
            return original_warning(event, **kwargs)

        monkeypatch.setattr(_auth.log, "warning", spying_warning)

        # _patch_sdk_refresh lives on TestTryRefreshBackendRouting; reuse
        # its exact patching shape inline since this is a different class.
        from unittest.mock import MagicMock
        import geolens
        import geolens.api.auth.refresh_auth_refresh_post as _refresh_mod
        import geolens.models.refresh_request as _refresh_req_mod

        class FakeParsed:
            pass

        parsed = FakeParsed()
        parsed.access_token = "new-access"
        parsed.refresh_token = "new-refresh"

        class FakeResp:
            status_code = 200

        FakeResp.parsed = parsed

        monkeypatch.setattr(geolens, "GeolensClient", MagicMock())
        monkeypatch.setattr(_refresh_mod, "sync_detailed", MagicMock(return_value=FakeResp()))
        monkeypatch.setattr(_refresh_req_mod, "RefreshRequest", MagicMock())

        new_tok = _auth.try_refresh(INSTANCE)

        assert new_tok == "new-access"
        assert path.read_bytes() == original_bytes, "a corrupt file must not be rewritten"
        assert mock_keyring.get(("geolens", INSTANCE)) == "new-access"
        assert mock_keyring.get(("geolens", f"{INSTANCE}:refresh")) == "new-refresh"
        assert warnings, "a warning must be logged for the skipped marker write"


class TestLoginRefusesUnconditionallyOnACorruptFile:
    """fix(#1778 review round 28): the file is BOTH a credential store
    and the marker store, so while it cannot be parsed, neither the
    competing credential's state nor the marker itself can be
    established -- exactly the information every one of rounds 22-25's
    "safe to tolerate" carve-outs needed. Round 27's own finding (round
    25's competing_confirmed_absent looked only at the keyring, so a
    corrupt file that itself held a competing bearer looked identical
    to nothing to worry about) was the second time that
    characterization turned out wrong. Closing the class instead of
    adding a third term: replace_credentials() now refuses EVERY login
    on a corrupt file, unconditionally, before any secret is stored --
    regardless of kind, keyring state, or what was previously active.
    whoami/status/logout/refresh keep their own independent, unchanged
    behavior -- see the sibling test classes in this file."""

    def test_login_with_an_api_key_refuses_on_a_corrupt_file(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """Pin: corrupt file + login api-key -> refused, keyring
        untouched, file untouched, message names the path and says to
        fix or move it."""
        from geolens_cli.main import app

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        instance = "https://x.example.com"
        path = _write_corrupt_credentials_file(instance)
        original_bytes = path.read_bytes()

        result = runner.invoke(app, ["login", instance, "--api-key", "new-api-key"])

        assert result.exit_code != 0, result.output
        assert path.read_bytes() == original_bytes, "a refusal must not rewrite the file"
        assert str(path) in result.output
        assert "corrupt" in result.output.lower()
        assert "fix" in result.output.lower() or "move" in result.output.lower()
        assert not mock_keyring, "nothing must ever be stored"

    def test_login_with_a_bearer_token_refuses_on_a_corrupt_file(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """Pin: corrupt file + login bearer -> same as the api-key
        case above."""
        from geolens_cli.main import app

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        instance = "https://x.example.com"
        path = _write_corrupt_credentials_file(instance)
        original_bytes = path.read_bytes()

        result = runner.invoke(app, ["login", instance, "--token", "new-bearer-token"])

        assert result.exit_code != 0, result.output
        assert path.read_bytes() == original_bytes, "a refusal must not rewrite the file"
        assert str(path) in result.output
        assert "corrupt" in result.output.lower()
        assert "fix" in result.output.lower() or "move" in result.output.lower()
        assert not mock_keyring, "nothing must ever be stored"


class TestWhoamiStatusToleratesCorruptFileWhenSomethingElseResolves:
    """fix(#1778 review round 23): round 22 added an UNCONDITIONAL
    corrupt-file preflight at the top of whoami/status, so a corrupt
    credentials.toml made both commands fail even when GEOLENS_TOKEN was
    set or a perfectly good keyring credential existed -- both of which
    the pre-round-22 resolver would have happily used. The check now
    lives inside AppState.sdk()'s own final fallback branch (the one
    that's about to give up and return an anonymous client), so it only
    ever fires when the file was genuinely the last option."""

    def test_whoami_succeeds_with_env_token_despite_a_corrupt_file(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """Pin: corrupt file + GEOLENS_TOKEN -> whoami succeeds."""
        from unittest.mock import MagicMock

        import geolens
        import geolens.api.auth.me_auth_me_get as _me_mod

        from geolens_cli.main import app

        instance = "https://x.example.com/api"
        _write_corrupt_credentials_file(instance)
        monkeypatch.setenv("GEOLENS_TOKEN", "env-token")

        class FakeUser:
            email = "env-user@example.com"

        class FakeResp:
            status_code = 200
            parsed = FakeUser()

        monkeypatch.setattr(geolens, "GeolensClient", MagicMock())
        monkeypatch.setattr(_me_mod, "sync_detailed", MagicMock(return_value=FakeResp()))

        result = runner.invoke(app, ["--instance", instance, "whoami"])

        assert result.exit_code == 0, result.output
        assert "corrupt" not in result.output.lower()
        assert "env-user@example.com" in result.output

    def test_whoami_succeeds_with_a_keyring_credential_despite_a_corrupt_file(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """Pin: corrupt file + keyring credential -> whoami succeeds."""
        from unittest.mock import MagicMock

        import geolens
        import geolens.api.auth.me_auth_me_get as _me_mod

        from geolens_cli import config as _cfg
        from geolens_cli.main import app

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        instance = "https://x.example.com/api"
        canonical = _cfg.normalize_instance_url(instance)
        _auth.store_bearer_token(canonical, "keyring-token", no_keyring=False)
        _write_corrupt_credentials_file(canonical)

        class FakeUser:
            email = "keyring-user@example.com"

        class FakeResp:
            status_code = 200
            parsed = FakeUser()

        monkeypatch.setattr(geolens, "GeolensClient", MagicMock())
        monkeypatch.setattr(_me_mod, "sync_detailed", MagicMock(return_value=FakeResp()))

        result = runner.invoke(app, ["--instance", instance, "whoami"])

        assert result.exit_code == 0, result.output
        assert "corrupt" not in result.output.lower()
        assert "keyring-user@example.com" in result.output

    def test_whoami_names_the_corrupt_path_when_nothing_else_resolves(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """Pin: corrupt file + nothing else -> error names the path,
        not the generic "not logged in" message."""
        from geolens_cli.main import app

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        instance = "https://x.example.com/api"
        path = _write_corrupt_credentials_file(instance)

        result = runner.invoke(app, ["--instance", instance, "whoami"])

        assert result.exit_code != 0, result.output
        assert str(path) in result.output
        assert "corrupt" in result.output.lower()
        assert "not logged in" not in result.output.lower()
        assert "no active instance" not in result.output.lower()


class TestLoginKindSwapMakesTheMarkerMandatory:
    """fix(#1778 review round 23): a KIND SWAP (bearer -> api_key or
    back) makes the active_kind marker the only thing keeping a still-
    lingering old credential in the other backend from outranking the
    one just stored -- a marker-write failure must roll the whole swap
    back, not be swallowed to a warning.

    fix(#1778 review round 28): this class used to also pin the
    CORRUPT-FILE side of that rule (a kind swap against a corrupt file
    refuses; a same-kind login tolerates one). Both are superseded now
    that replace_credentials() refuses on a corrupt file
    unconditionally, before anything is stored, regardless of kind --
    see TestLoginRefusesUnconditionallyOnACorruptFile. What is left
    here is the one HEALTHY-file scenario rounds 23-27 leave unchanged:
    a marker-write failure (whatever its cause) is now unconditionally
    fatal, which already covers the narrower "mandatory when the old
    kind is unverifiable" case this test originally isolated."""

    def test_login_kind_swap_with_unknown_old_kind_and_marker_failure_rolls_back(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """Pin: kind swap + cleanup _UNKNOWN on the old kind + marker
        write failure -> the just-stored secret is removed, login
        fails, and the old credential is untouched.

        No corrupt file is involved in the setup here -- the file is
        healthy (so the round-28 preflight passes) but two things are
        engineered directly: the pre-swap snapshot cannot read the OLD
        kind's keyring account (-> _UNKNOWN, same as a transient keyring
        hiccup), and the marker write itself is made to fail (any
        failure there is unconditionally fatal now, round 28).
        """
        from geolens_cli import config as _cfg
        from geolens_cli.main import app

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        instance = "https://x.example.com"
        canonical = _cfg.normalize_instance_url(instance)

        # Establish an existing BEARER login via the keyring -- this is
        # the "old kind" credential that must survive untouched.
        _auth.replace_credentials(canonical, "bearer", "old-bearer-token")
        bearer_account = ("geolens", canonical)
        assert mock_keyring.get(bearer_account) == "old-bearer-token"

        import keyring as _keyring_mod
        from keyring.errors import KeyringError

        real_get_password = _keyring_mod.get_password

        def flaky_get_password(svc: str, user: str):
            if user == canonical:
                # The bearer (old-kind) account is unreadable during
                # THIS login's pre-swap snapshot -> recorded as _UNKNOWN.
                raise KeyringError("keyring temporarily unavailable")
            return real_get_password(svc, user)

        monkeypatch.setattr(_keyring_mod, "get_password", flaky_get_password)

        def failing_set_credential_field(instance_arg, field, value):
            raise _auth.CredentialsFileCorrupt(
                _cfg.credentials_path(), "simulated marker write failure"
            )

        monkeypatch.setattr(_auth, "_set_credential_field", failing_set_credential_field)
        # The round-23 preflight only checks readability, which the
        # (currently absent) credentials.toml passes -- so the swap
        # proceeds to the store call, and fails at the marker write.

        result = runner.invoke(app, ["login", instance, "--api-key", "new-api-key"])

        assert result.exit_code != 0, result.output
        api_key_account = ("geolens", f"{canonical}:api_key")
        assert api_key_account not in mock_keyring, (
            "the just-stored API key must be removed on rollback"
        )
        assert mock_keyring.get(bearer_account) == "old-bearer-token", (
            "the old bearer credential must be untouched"
        )


class TestCorruptFileDiagnosticsStayOffStdout:
    """fix(#1778 review round 24): structlog's UNCONFIGURED default
    PrintLogger writes every log.warning() call straight to stdout --
    the CLI configures no structlog handler anywhere, so a warning
    fired mid-login could land directly in a --json login's promised
    single JSON document on stdout. auth.py now configures structlog's
    logger_factory to stderr at import time (module-level, see auth.py's
    own comment), so every log.warning() in this module -- current and
    future -- is stderr-safe without having to remember to route around
    the default at each call site.

    fix(#1778 review round 28): the original pin here used a corrupt
    credentials.toml to trigger _delete_stale_credentials()'s cleanup-
    skip warning during an otherwise-successful login -- unreachable
    now that a corrupt file refuses login outright before that point is
    ever reached (see TestLoginRefusesUnconditionallyOnACorruptFile).
    Repinned against a still-live success-path warning instead: a
    keyring that rejects the WRITE (unrelated to file health) still
    succeeds via the documented credentials.toml fallback, logging
    "keyring_unavailable_falling_back_to_file" -- the exact class of
    warning this round's structlog fix protects, on a path that still
    exists."""

    def test_json_login_emits_exactly_one_json_document_on_stdout_despite_a_keyring_fallback_warning(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """Pin: healthy file + a keyring write failure that falls back
        to the file, with --json -> stdout is exactly one JSON
        document, and the fallback warning still fired (spied
        directly on the logger -- CliRunner's stderr capture cannot
        observe structlog's own PrintLogger here, because its
        logger_factory captured a reference to the REAL sys.stderr at
        module-IMPORT time, before CliRunner ever reassigns sys.stderr
        for the duration of one invoke() call; a plain print(file=
        sys.stderr) done AT CALL TIME, like _warn_credentials_file_
        corrupt()'s, looks up sys.stderr fresh and IS visible to
        CliRunner, which is a real difference between the two but not
        one that matters outside tests -- a real process's sys.stderr
        is never reassigned mid-run either way)."""
        import json

        import keyring as _keyring_mod
        from keyring.errors import KeyringError

        from geolens_cli.main import app

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        instance = "https://x.example.com"

        def failing_set_password(svc, user, pwd):
            raise KeyringError("keyring locked")

        monkeypatch.setattr(_keyring_mod, "set_password", failing_set_password)

        warnings: list[str] = []
        original_warning = _auth.log.warning

        def spying_warning(event, **kwargs):
            warnings.append(event)
            return original_warning(event, **kwargs)

        monkeypatch.setattr(_auth.log, "warning", spying_warning)

        result = runner.invoke(
            app, ["--json", "login", instance, "--token", "new-bearer-token"]
        )

        assert result.exit_code == 0, result.output
        # Exactly one JSON document on stdout -- a bare json.loads (not
        # a line-by-line scan) fails outright if any stray diagnostic
        # text shares the stream.
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        # The warning genuinely fired (this isn't a vacuous pass) --
        # and, per the docstring above, still landed on stdout NOT AT
        # ALL, which is the property that actually matters.
        assert "keyring_unavailable_falling_back_to_file" in warnings


class TestUnreadableCompetingCredentialDoesNotBlockANormalLogin:
    """fix(#1778 review round 25): the active_kind marker must still
    get written correctly even when the COMPETING kind's own keyring
    account happens to be unreadable (a transient hiccup, unrelated to
    this login) -- an unrelated read failure elsewhere must not block
    an otherwise-ordinary login against a perfectly healthy file.

    fix(#1778 review round 28): this class originally also pinned two
    CORRUPT-FILE rows of a previous_kind x competing-state x file
    truth table (round 25's `competing_confirmed_absent`/
    `marker_required`, since removed). Both are superseded now that
    replace_credentials() refuses on a corrupt file unconditionally,
    before anything is stored, regardless of competing-credential
    state -- see TestLoginRefusesUnconditionallyOnACorruptFile. What
    remains is the one HEALTHY-file scenario rounds 23-27 leave
    unchanged."""

    def test_marker_is_written_when_the_competing_kind_is_unreadable_but_the_file_is_healthy(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """Pin: competing kind unreadable + file healthy -> marker
        written, login succeeds."""
        import keyring as _keyring_mod
        from keyring.errors import KeyringError

        from geolens_cli import auth as _auth
        from geolens_cli import config as _cfg
        from geolens_cli.main import app

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        instance = "https://x.example.com"
        canonical = _cfg.normalize_instance_url(instance)

        real_get_password = _keyring_mod.get_password

        def flaky_get_password(svc: str, user: str):
            if user == canonical:
                # The bearer account (competing kind for this api_key
                # login) is unreadable -- unrelated to this login.
                raise KeyringError("keyring temporarily unavailable")
            return real_get_password(svc, user)

        monkeypatch.setattr(_keyring_mod, "get_password", flaky_get_password)

        result = runner.invoke(app, ["login", instance, "--api-key", "new-api-key"])

        assert result.exit_code == 0, result.output
        api_key_account = ("geolens", f"{canonical}:api_key")
        assert mock_keyring.get(api_key_account) == "new-api-key"
        assert _auth.load_active_credential_kind(canonical) == "api_key"

"""Exit-code matrix (CONTEXT.md D-32).

Plan 01 stubbed login/logout/whoami exits at 2; Plan 02 replaced those stubs
with real implementations whose exit codes depend on state:
- whoami with no instance configured → EXIT_AUTH (3)
- login --token + --api-key together → EXIT_USAGE (2)
Plan 03 wires scan to walk + classify (exits 0 even on all-ingest:no per
D-17). Plan 04 wires publish to the 3-step ingest flow (per-command
behavior in test_publish_unit.py::TestPublishCli). The remaining stub
command (export stac) still exits 2 until Plan 05 lands.

Phase 242 adds offline manifest commands:
- init creates geolens.yaml locally and refuses overwrite with EXIT_USAGE (2)
- validate exits 0 for valid manifests and EXIT_USAGE (2) for invalid input
"""

from __future__ import annotations

from geolens_cli._sdk_helpers import (
    EXIT_AUTH,
    EXIT_GENERIC,
    EXIT_NETWORK,
    EXIT_OK,
    EXIT_SERVER,
    EXIT_USAGE,
)
from geolens_cli.main import app
from geolens_cli.manifest.template import minimal_manifest_text


class TestExitCodeConstants:
    def test_constants_match_d32(self) -> None:
        assert EXIT_OK == 0
        assert EXIT_GENERIC == 1
        assert EXIT_USAGE == 2
        assert EXIT_AUTH == 3
        assert EXIT_NETWORK == 4
        assert EXIT_SERVER == 5


class TestRemainingStubsExitWithUsage:
    """Plan 05 still ships an export stac stub that exits 2 until it lands.

    Plan 03 replaced the scan stub with a real walker (exits 0 on dry-run
    per D-17); per-command exit-code behavior for scan is asserted in
    test_scan.py::TestCliInvocation. Plan 04 replaced the publish stub
    with the 3-step ingest flow; per-command exit-code behavior for
    publish is asserted in test_publish_unit.py::TestPublishCli.
    """

    def test_export_stac_stub_exits_2(self, runner, tmp_xdg_home) -> None:
        # fix(#1105): tmp_xdg_home, because without it this reads the
        # developer's real config. It passes in CI, where there is none, and on
        # a machine with a logged-in instance it reaches the host keychain and
        # blocks on the OS access prompt — hanging the whole `make cli-test`
        # run, not just this test.
        result = runner.invoke(app, ["export", "stac", "abc"])
        assert result.exit_code == 2


class TestAuthCommandExitCodes:
    """Real per-command behavior (Plan 02 replaces the Plan 01 stubs)."""

    def test_login_mutually_exclusive_token_and_api_key(
        self, runner, tmp_xdg_home
    ) -> None:
        result = runner.invoke(
            app,
            [
                "login",
                "https://x.example.com",
                "--token",
                "abc",
                "--api-key",
                "xyz",
                "--no-keyring",
            ],
        )
        assert result.exit_code == 2

    def test_login_rejects_non_http_url(self, runner, tmp_xdg_home) -> None:
        result = runner.invoke(
            app, ["login", "ftp://x.example.com", "--token", "abc", "--no-keyring"]
        )
        assert result.exit_code == 2

    def test_login_with_token_succeeds(
        self, runner, tmp_xdg_home, mock_keyring
    ) -> None:
        result = runner.invoke(
            app, ["login", "https://x.example.com", "--token", "abc.def.ghi"]
        )
        assert result.exit_code == 0, result.output

    def test_logout_with_no_instance_exits_2(
        self, runner, tmp_xdg_home, mock_keyring
    ) -> None:
        result = runner.invoke(app, ["logout"])
        assert result.exit_code == 2

    def test_logout_after_login_succeeds(
        self, runner, tmp_xdg_home, mock_keyring
    ) -> None:
        runner.invoke(app, ["login", "https://x.example.com", "--token", "abc.def.ghi"])
        result = runner.invoke(app, ["logout"])
        assert result.exit_code == 0, result.output

    def test_whoami_with_no_instance_exits_3(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        monkeypatch.delenv("GEOLENS_INSTANCE", raising=False)
        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        result = runner.invoke(app, ["whoami"])
        assert result.exit_code == EXIT_AUTH, result.output


class TestLoginStdinSecret:
    """SEC-016: login accepts the secret via stdin (--token -)."""

    def test_login_token_dash_reads_from_stdin(
        self, runner, tmp_xdg_home, mock_keyring
    ) -> None:
        """--token - reads the bearer token from stdin, not argv."""
        result = runner.invoke(
            app,
            ["login", "https://x.example.com", "--token", "-", "--no-keyring"],
            input="stdin-token-value\n",
        )
        assert result.exit_code == 0, result.output
        # Token stored from stdin must be the stdin value, NOT the literal "-"
        creds_text = (tmp_xdg_home / "geolens" / "credentials.toml").read_text()
        assert "stdin-token-value" in creds_text
        assert '"-"' not in creds_text

    def test_login_api_key_dash_reads_from_stdin(
        self, runner, tmp_xdg_home, mock_keyring
    ) -> None:
        """--api-key - reads the API key from stdin."""
        result = runner.invoke(
            app,
            ["login", "https://x.example.com", "--api-key", "-", "--no-keyring"],
            input="stdin-api-key-value\n",
        )
        assert result.exit_code == 0, result.output
        creds_text = (tmp_xdg_home / "geolens" / "credentials.toml").read_text()
        assert "stdin-api-key-value" in creds_text

    def test_login_token_argv_still_works(
        self, runner, tmp_xdg_home, mock_keyring
    ) -> None:
        """Backward compat: --token <value> on argv continues to work."""
        result = runner.invoke(
            app,
            ["login", "https://x.example.com", "--token", "argv-token", "--no-keyring"],
        )
        assert result.exit_code == 0, result.output


class TestInteractiveLoginIsBounded:
    """fix(#1778 review round 2): the interactive login flow built its own
    GeolensClient directly with the SDK's default timeout=None
    (unbounded), so `geolens login <url>` (no --token/--api-key) could
    hang forever on a host that accepts a connection and then stalls,
    despite AppState.sdk()'s bound added earlier in this PR. It now goes
    through the same _sdk_helpers.make_client() every other client
    construction in this package uses."""

    def test_a_stalled_login_endpoint_exits_network_within_the_bound(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        import httpx

        from geolens_cli._sdk_helpers import DEFAULT_HTTP_TIMEOUT_SECONDS

        seen_timeout = None

        def stalled_login(**kwargs):
            nonlocal seen_timeout
            seen_timeout = kwargs["client"].get_httpx_client().timeout
            raise httpx.TimeoutException("login endpoint never responded")

        monkeypatch.setattr(
            "geolens.api.auth.login_auth_login_post.sync_detailed",
            stalled_login,
        )

        result = runner.invoke(
            app,
            ["login", "https://x.example.com"],
            input="alice\nsecret\n",
        )

        assert result.exit_code == EXIT_NETWORK, result.output
        assert seen_timeout is not None
        assert seen_timeout == httpx.Timeout(DEFAULT_HTTP_TIMEOUT_SECONDS)


class TestLoginEvictsOtherCredentialType:
    """fix(#1778): AppState.sdk() prefers a stored bearer token over an API
    key. `login --api-key` used to store the key WITHOUT clearing a stale
    bearer/refresh token left over from an earlier interactive login, so
    every command kept using the stale JWT (and failed once it expired)
    with no indication the fresh API key was ever ignored. `logout` was
    the only way to clear the loser. login must evict the other stored
    credential type before storing the new one."""

    def test_api_key_login_evicts_a_stale_bearer_token(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli import auth as _auth
        from geolens_cli import config as _config

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        instance = "https://x.example.com"
        canonical = _config.normalize_instance_url(instance)

        login_result = runner.invoke(
            app, ["login", instance, "--token", "stale.bearer.jwt"]
        )
        assert login_result.exit_code == 0, login_result.output
        assert _auth.load_bearer_token(canonical) is not None

        api_key_result = runner.invoke(
            app, ["login", instance, "--api-key", "fresh-api-key"]
        )
        assert api_key_result.exit_code == 0, api_key_result.output

        # The stale bearer token must no longer be resolvable — otherwise
        # AppState.sdk()'s bearer-before-api-key precedence keeps using it.
        assert _auth.load_bearer_token(canonical) is None
        loaded_key = _auth.load_api_key(canonical)
        assert loaded_key is not None
        assert loaded_key.value == "fresh-api-key"

    def test_token_login_evicts_a_stale_api_key(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli import auth as _auth
        from geolens_cli import config as _config

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        instance = "https://x.example.com"
        canonical = _config.normalize_instance_url(instance)

        runner.invoke(app, ["login", instance, "--api-key", "stale-api-key"])
        assert _auth.load_api_key(canonical) is not None

        runner.invoke(app, ["login", instance, "--token", "fresh.bearer.jwt"])

        assert _auth.load_api_key(canonical) is None
        loaded = _auth.load_bearer_token(canonical)
        assert loaded is not None
        assert loaded.value == "fresh.bearer.jwt"


class TestLoginAtomicCredentialSwap:
    """fix(#1778 review round 4): login used to call delete_credentials()
    BEFORE storing the replacement, so a storage failure (keyring falling
    back to a read-only or full XDG path, a permissions error, ...) left
    the user logged out AND login reporting failure — the working
    credential was already gone. login now stores the new credential
    first via auth.replace_credentials() and only evicts the competing
    kinds once that succeeds."""

    def test_a_storage_failure_leaves_prior_credentials_intact_and_exits_nonzero(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli import auth as _auth
        from geolens_cli import config as _config

        instance = "https://x.example.com"
        canonical = _config.normalize_instance_url(instance)

        # Seed a working bearer + refresh token, as an earlier successful
        # login would have left behind.
        _auth.store_bearer_token(canonical, "old-bearer-token")
        _auth.store_refresh_token(canonical, "old-refresh-token")

        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(_auth, "store_api_key", boom)

        result = runner.invoke(app, ["login", instance, "--api-key", "new-key"])

        assert result.exit_code != 0, result.output
        loaded_bearer = _auth.load_bearer_token(canonical)
        assert loaded_bearer is not None
        assert loaded_bearer.value == "old-bearer-token"
        assert _auth.load_refresh_token(canonical) == "old-refresh-token"
        assert _auth.load_api_key(canonical) is None

    def test_a_successful_swap_leaves_exactly_the_new_kind(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli import auth as _auth
        from geolens_cli import config as _config

        instance = "https://x.example.com"
        canonical = _config.normalize_instance_url(instance)

        _auth.store_bearer_token(canonical, "old-bearer-token")
        _auth.store_refresh_token(canonical, "old-refresh-token")

        result = runner.invoke(app, ["login", instance, "--api-key", "new-key"])

        assert result.exit_code == 0, result.output
        assert _auth.load_bearer_token(canonical) is None
        assert _auth.load_refresh_token(canonical) is None
        loaded_key = _auth.load_api_key(canonical)
        assert loaded_key is not None
        assert loaded_key.value == "new-key"

    def test_replace_credentials_raising_touches_nothing(
        self, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """Unit-level: the store call itself raising must not have deleted
        anything — the snapshot read is read-only, and the delete step
        never runs until after the store succeeds."""
        import pytest

        from geolens_cli import auth as _auth

        instance = "https://x.example.com/api"
        _auth.store_bearer_token(instance, "old-bearer-token")
        _auth.store_refresh_token(instance, "old-refresh-token")

        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(_auth, "store_api_key", boom)

        with pytest.raises(OSError):
            _auth.replace_credentials(instance, "api_key", "new-key")

        loaded_bearer = _auth.load_bearer_token(instance)
        assert loaded_bearer is not None
        assert loaded_bearer.value == "old-bearer-token"
        assert _auth.load_refresh_token(instance) == "old-refresh-token"
        assert _auth.load_api_key(instance) is None

    def test_delete_step_failure_restores_the_snapshot(
        self, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """If the store succeeds but evicting the competing kinds then
        fails partway (the credentials.toml write, specifically — the
        keyring half already swallows its own errors), the pre-swap
        snapshot must be restored rather than left in a mixed state."""
        import pytest

        from geolens_cli import auth as _auth

        instance = "https://x.example.com/api"
        _auth.store_bearer_token(instance, "old-bearer-token", no_keyring=True)
        _auth.store_refresh_token(instance, "old-refresh-token", no_keyring=True)

        def boom(*args, **kwargs):
            raise OSError("disk full")

        # Only the delete-competing-kinds step must fail — the initial
        # store of the new api_key (also a credentials.toml write) needs
        # to succeed so this actually exercises the restore path, not
        # the already-covered "store itself raised" path above.
        monkeypatch.setattr(_auth, "_delete_stale_credentials", boom)

        with pytest.raises(OSError):
            _auth.replace_credentials(instance, "api_key", "new-key", no_keyring=True)

        # The failed delete-competing-kinds step must not have left the
        # new api_key live without evicting the old bearer/refresh — the
        # restore puts the file back to its pre-swap content, so the
        # ORIGINAL bearer/refresh are exactly as they were, and the new
        # api_key is gone again.
        loaded_bearer = _auth.load_bearer_token(instance)
        assert loaded_bearer is not None
        assert loaded_bearer.value == "old-bearer-token"
        assert _auth.load_refresh_token(instance) == "old-refresh-token"
        assert _auth.load_api_key(instance) is None


class TestLoginCrossBackendStaleCredential:
    """fix(#1778 review round 5): when the old bearer/API key lives in
    credentials.toml and the replacement of the SAME kind lands in the
    keyring, the old delete-competing-kinds step never touched it (it
    only ever deleted the OTHER kinds) — it kept skipping "bearer"
    entirely because that was the kind being kept. load_bearer_token()
    prefers the file over the keyring, so the stale file value kept
    winning over the freshly-stored keyring one, even though login
    reported success."""

    def test_a_bearer_login_evicts_the_same_kind_from_the_file_too(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli import auth as _auth
        from geolens_cli import config as _config

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        instance = "https://x.example.com"
        canonical = _config.normalize_instance_url(instance)

        # Old bearer token lives in the FILE backend (an earlier
        # --no-keyring login, say).
        _auth.store_bearer_token(canonical, "old-file-bearer", no_keyring=True)
        assert "bearer_token" in _auth._read_credentials_file()[canonical]

        # Keyring is available for this login (mock_keyring never
        # raises), so the new token lands there instead.
        result = runner.invoke(app, ["login", instance, "--token", "new-keyring-bearer"])

        assert result.exit_code == 0, result.output
        loaded = _auth.load_bearer_token(canonical)
        assert loaded is not None
        assert loaded.value == "new-keyring-bearer"
        file_section = _auth._read_credentials_file().get(canonical, {})
        assert "bearer_token" not in file_section, (
            "the old file-backed bearer token must be evicted once the "
            "new one is confirmed stored in the keyring"
        )


class TestDeleteStaleCredentialsSurfacesGenuineFailures:
    """fix(#1778 review round 7): _delete_stale_credentials() used to
    swallow EVERY keyring delete failure with a blanket
    `except Exception: pass`, matching keyring.errors.PasswordDeleteError
    raised for both "no such entry" (expected) and a genuine backend
    refusal (locked keychain, permission denied, ...) — with no way to
    tell them apart from the exception alone. It now checks existence
    first, so a refusal on an entry that DID exist propagates and
    replace_credentials() restores the pre-swap snapshot instead of
    reporting success."""

    def test_a_delete_refusal_restores_the_snapshot_and_exits_nonzero(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        import keyring

        from geolens_cli import auth as _auth
        from geolens_cli import config as _config

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        instance = "https://x.example.com"
        canonical = _config.normalize_instance_url(instance)

        # Old bearer token lives in the keyring (an earlier plain login).
        _auth.store_bearer_token(canonical, "old-bearer-token")
        bearer_account = canonical  # _keyring_account_token(instance)

        original_delete = keyring.delete_password  # mock_keyring's dict-backed one

        def refusing_delete(service, username):
            if username == bearer_account:
                raise RuntimeError("keychain is locked")
            return original_delete(service, username)

        monkeypatch.setattr("keyring.delete_password", refusing_delete)

        # A --api-key login must evict the competing bearer kind, which
        # is exactly the delete this test makes fail.
        result = runner.invoke(app, ["login", instance, "--api-key", "new-key"])

        assert result.exit_code != 0, result.output
        # Snapshot restored: the old bearer survives, and the api_key
        # that had briefly been stored is rolled back too.
        loaded_bearer = _auth.load_bearer_token(canonical)
        assert loaded_bearer is not None
        assert loaded_bearer.value == "old-bearer-token"
        assert _auth.load_api_key(canonical) is None

    def test_a_missing_entry_is_still_tolerated(
        self, tmp_xdg_home, mock_keyring
    ) -> None:
        from geolens_cli import auth as _auth

        instance = "https://x.example.com/api"
        # Nothing stored for this instance in either backend — every
        # account in _delete_stale_credentials' loop is absent.
        _auth._delete_stale_credentials(instance, keep="bearer", keep_backend="keyring")


class TestManifestCommandExitCodes:
    """Offline manifest commands use usage errors for local input problems."""

    def test_init_existing_manifest_exits_2(
        self,
        runner,
        tmp_path,
        tmp_xdg_home,
        monkeypatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "geolens.yaml").write_text("existing: true\n", encoding="utf-8")

        result = runner.invoke(app, ["init"])

        assert result.exit_code == EXIT_USAGE, result.output

    def test_validate_valid_manifest_exits_0(
        self,
        runner,
        tmp_path,
        tmp_xdg_home,
        monkeypatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "geolens.yaml").write_text(
            minimal_manifest_text(),
            encoding="utf-8",
        )

        result = runner.invoke(app, ["validate"])

        assert result.exit_code == EXIT_OK, result.output

    def test_validate_invalid_manifest_exits_2(
        self,
        runner,
        tmp_path,
        tmp_xdg_home,
        monkeypatch,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "geolens.yaml").write_text(
            'manifest_version: "1"\ncatalog: {}\ndatasets: []\n',
            encoding="utf-8",
        )

        result = runner.invoke(app, ["validate"])

        assert result.exit_code == EXIT_USAGE, result.output

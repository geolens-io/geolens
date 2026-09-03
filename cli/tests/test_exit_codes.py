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

--------------------------------------------------------------------------
Credential-swap state table (fix(#1778 review round 14): built as a
coverage audit, not narrative — every cell below is either pinned by a
named test or proven unreachable with the structural reason why).

Axes: STORE BACKEND the credential ends up in (keyring | file) x SNAPSHOT
STATE for an account at replace_credentials()'s pre-store read (present:
a real prior value | absent: confirmed None | unknown: the read itself
raised, recorded as auth._UNKNOWN) x LOGIN KIND (bearer via --token |
api_key via --api-key | interactive: bearer + refresh_token together,
only reachable via the interactive prompt flow or a direct
replace_credentials(refresh_token=...) call — --token/--api-key never
pass one) x FAILURE POINT (none | pre-store snapshot read | store call |
marker write | cleanup | refresh-token write | rollback/restore itself).

Organized by failure point, since that is what each round's fix actually
gates on; store backend, snapshot state, and login kind are enumerated
within each.

1. PRE-STORE SNAPSHOT READ (a keyring.get_password raises while building
   the pre-swap snapshot). This never itself raises out of
   _snapshot_credentials() — every read is individually try/excepted to
   _UNKNOWN — so "failure" here always degrades into a snapshot STATE,
   not a crash. That state then interacts with every later step:
   - snapshot unknown for the TARGET account (the one about to be
     overwritten): store is forced to the file backend regardless of the
     caller's no_keyring (round 13). bearer/api_key:
     TestSnapshotUnknownForcesFileBackend::
     test_a_snapshot_read_failure_forces_the_file_backend_with_the_marker_set.
     interactive+refresh: TestRefreshTokenSharesAccessTokenBackend::
     test_a_forced_file_login_puts_both_tokens_in_the_file, and the
     try_refresh() composition proof in the same class's
     test_try_refresh_detects_the_file_backend_from_where_the_tokens_landed.
   - snapshot unknown for a NON-target account (the competing kind, or
     refresh): cleanup must never delete it (round 14) —
     TestSnapshotUnknownIsNeverDeletedByCleanup (both the direct
     _delete_stale_credentials() unit test and the end-to-end rollback
     test); restore must never touch it either (round 9) —
     TestSnapshotUnknownStateNeverDeleted.
   - snapshot present or absent, any login kind: the ordinary path,
     implicitly covered by every happy-path test in
     TestLoginAtomicCredentialSwap, TestLoginEvictsOtherCredentialType,
     and TestLoginCrossBackendStaleCredential.

2. STORE CALL (store_bearer_token/store_api_key itself raises or falls
   back).
   - keyring set_password raises alone: caught INSIDE store_* itself,
     which falls back to the file — not a replace_credentials()-level
     failure at all. Implicit in every "keyring unavailable" test below.
   - target snapshot unknown AND the forced file write also raises (no
     backend left to land in): re-raised as KeyringError -> EXIT_NETWORK,
     nothing mutated — TestSnapshotUnknownForcesFileBackend::
     test_keyring_unreadable_and_file_read_only_exits_network_with_no_mutation.
   - target snapshot present/absent (not forced) and the store call
     raises outright (e.g. explicit --no-keyring with an unwritable
     file): nothing has been mutated yet, propagates untouched (round 4)
     — TestLoginAtomicCredentialSwap::
     test_a_storage_failure_leaves_prior_credentials_intact_and_exits_nonzero,
     test_replace_credentials_raising_touches_nothing.

3. MARKER WRITE (_set_credential_field(active_kind) raises).
   - Covered for bearer via CLI --token: TestActiveKindMarkerWriteIsRollback
     Protected::test_a_marker_write_failure_restores_the_previous_credential
     (round 11). Not separately pinned per login kind: the marker write
     has no kind-conditional branch (it writes the same field the same
     way regardless of "bearer" vs "api_key"), so this is proven by
     symmetry rather than duplicated per kind.

4. CLEANUP (_delete_stale_credentials — deleting competing-kind and
   stale same-kind entries).
   - keep_backend == "keyring", a DIFFERENT account's cleanup read fails
     after having been READABLE at snapshot time (a transient
     mid-transaction failure, not an _UNKNOWN snapshot): surfaced as a
     hard failure, rollback (round 8) — TestUnreadableKeyringDuringCleanup::
     test_a_keyring_that_cannot_be_read_at_cleanup_restores_the_snapshot_and_exits_nonzero.
   - keep_backend == "file" (explicit --no-keyring, or forced by round
     13), an account's cleanup read fails: tolerated the same as "no such
     entry" (round 9) — TestUnreadableKeyringDuringCleanup::
     test_no_keyring_login_succeeds_even_if_the_keyring_raises,
     test_plain_login_falls_back_to_file_when_the_keyring_is_entirely_unavailable.
   - an account's SNAPSHOT was unknown (regardless of keep_backend):
     skipped unconditionally, never handed to delete_password (round
     14) — TestSnapshotUnknownIsNeverDeletedByCleanup.
   - a genuine delete refusal on a KNOWN-present entry: surfaced,
     rollback (round 7) — TestDeleteStaleCredentialsSurfacesGenuineFailures::
     test_a_delete_refusal_restores_the_snapshot_and_exits_nonzero.
   - a missing/absent entry: trivially tolerated (round 7 baseline) —
     TestDeleteStaleCredentialsSurfacesGenuineFailures::
     test_a_missing_entry_is_still_tolerated.
   - cleanup's OWN file-section rewrite raises (distinct from the marker
     write above — the second credentials.toml write in the transaction,
     not the first): rollback —
     TestCleanupFileRewriteFailureIsRollbackProtected::
     test_cleanups_own_file_rewrite_failure_restores_the_snapshot.

5. REFRESH-TOKEN WRITE (store_refresh_token(), only reachable when
   replace_credentials() is called with refresh_token= — the interactive
   flow's own shape; --token/--api-key never reach this step at all,
   making "bearer/api_key + refresh-token-write failure" structurally
   UNREACHABLE via those two CLI flags, not merely untested).
   - failure restores the WHOLE prior session (access token, refresh
     token, marker together), not just the refresh token (round 13) —
     TestInteractiveLoginRefreshTokenIsTransactional::
     test_a_refresh_token_write_failure_restores_the_whole_prior_session.
   - backend co-location with the access token, both forced-file and
     keyring, plus the try_refresh() rotation composing correctly with
     it (round 14) — TestRefreshTokenSharesAccessTokenBackend.
   - backend co-location when the DIVERGENCE is at STORE time, not
     snapshot time: snapshot reads succeed for the target account (so
     store_no_keyring/target_is_unknown stay False — distinct from the
     round-14 forced-file cell above), but keyring.set_password then
     fails for the access account only, so store_bearer_token/
     store_api_key fall back to backend == "file" while the refresh
     account's OWN set_password would have succeeded if asked (round
     15 — this is what `backend != "keyring"` fixes, replacing the
     round-14 store_no_keyring check) — TestRefreshTokenSharesAccess
     TokenBackend::
     test_a_store_time_keyring_failure_also_keeps_both_tokens_together.

6. ROLLBACK / RESTORE ITSELF (_restore_credentials()'s own writes fail).
   Proven UNREACHABLE as a distinct login-visible failure mode:
   _restore_credentials() wraps every keyring write and the file write
   each in their own try/except Exception that only logs
   ("credential_restore_failed") and continues — see its docstring
   ("each write is independently swallowed-and-logged rather than
   raised"). It cannot itself raise, so there is no rollback-of-rollback
   case to pin; the ORIGINAL triggering exception (from whichever step
   above called it) is what propagates and is what every rollback test
   listed under points 2-5 already asserts the exit code and restored
   state against.
--------------------------------------------------------------------------
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
        # account in _delete_stale_credentials' loop is absent. The
        # snapshot (fix(#1778 review round 14): now a required arg) is
        # taken fresh here too, so every field is a confirmed None, not
        # _UNKNOWN — this test is specifically about tolerating a
        # confirmed-absent entry, distinct from the _UNKNOWN case
        # TestSnapshotUnknownIsNeverDeletedByCleanup covers.
        snapshot = _auth._snapshot_credentials(instance)
        _auth._delete_stale_credentials(
            instance, keep="bearer", keep_backend="keyring", snapshot=snapshot
        )


class TestSnapshotUnknownStateNeverDeleted:
    """fix(#1778 review round 9): a transient keyring read failure while
    taking the rollback snapshot used to be swallowed to None, which
    recorded an EXISTING credential as absent. If cleanup then failed
    and the keyring was readable again by the time _restore_credentials
    ran, that None made it call delete_password() on an account that
    held a real, pre-existing credential the whole time -- the snapshot
    just couldn't see it for a moment. The snapshot now records an
    explicit "unknown" sentinel instead, which restore never deletes."""

    def test_a_snapshot_read_failure_is_never_deleted_on_restore(
        self, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        import keyring
        from keyring.errors import KeyringError

        from geolens_cli import auth as _auth

        instance = "https://x.example.com/api"
        _auth.store_bearer_token(instance, "old-bearer-token")
        bearer_account = instance  # _keyring_account_token(instance)

        original_get = keyring.get_password  # mock_keyring's dict-backed one

        def failing_get(service, username):
            if username == bearer_account:
                raise KeyringError("transient read failure")
            return original_get(service, username)

        monkeypatch.setattr("keyring.get_password", failing_get)

        snapshot = _auth._snapshot_credentials(instance)
        assert snapshot.keyring_bearer is _auth._UNKNOWN

        # The keyring is readable again by the time restore runs -- the
        # failure above was transient.
        monkeypatch.setattr("keyring.get_password", original_get)

        _auth._restore_credentials(instance, snapshot)

        # The pre-existing bearer token must be untouched: restore must
        # not delete it just because the snapshot couldn't read it.
        loaded = _auth.load_bearer_token(instance)
        assert loaded is not None
        assert loaded.value == "old-bearer-token"


class TestSnapshotUnknownIsNeverDeletedByCleanup:
    """fix(#1778 review round 14): TestSnapshotUnknownStateNeverDeleted
    (above) covers the RESTORE side of the _UNKNOWN sentinel -- a
    transient read failure at snapshot time must never be deleted when
    _restore_credentials() runs. This covers the other half:
    _delete_stale_credentials() itself must not delete an account whose
    snapshot came back _UNKNOWN either, even if the keyring has become
    readable again by the time CLEANUP runs (not restore). Without this,
    a genuinely unrecoverable delete could happen during a login that
    otherwise succeeds outright (no rollback needed at all) -- there is
    no window to catch it after the fact. It matters because a LATER
    step in the SAME transaction (another account's cleanup, the
    refresh-token write) can still fail after this cleanup step already
    ran, and _restore_credentials() would have no recorded value to put
    the deleted account back to."""

    def test_a_snapshot_unknown_refresh_account_is_never_deleted_by_cleanup(
        self, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """Unit-level, directly on _delete_stale_credentials(): the
        refresh account's snapshot is _UNKNOWN, but by the time cleanup
        runs the keyring is readable again and the account genuinely
        exists -- delete_password must still never be called for it."""
        import keyring
        from keyring.errors import KeyringError

        from geolens_cli import auth as _auth

        instance = "https://x.example.com/api"
        refresh_account = f"{instance}:refresh"
        _auth.store_refresh_token(instance, "old-refresh-token")

        original_get = keyring.get_password  # mock_keyring's dict-backed one

        def failing_get(service, username):
            if username == refresh_account:
                raise KeyringError("transient read failure")
            return original_get(service, username)

        monkeypatch.setattr("keyring.get_password", failing_get)
        snapshot = _auth._snapshot_credentials(instance)
        assert snapshot.keyring_refresh is _auth._UNKNOWN

        # The keyring becomes readable again before cleanup runs.
        monkeypatch.setattr("keyring.get_password", original_get)

        delete_calls: list[str] = []
        original_delete = keyring.delete_password

        def tracking_delete(service, username):
            delete_calls.append(username)
            return original_delete(service, username)

        monkeypatch.setattr("keyring.delete_password", tracking_delete)

        _auth._delete_stale_credentials(
            instance, keep="bearer", keep_backend="keyring", snapshot=snapshot
        )

        assert refresh_account not in delete_calls, (
            "cleanup must never delete an account its own snapshot "
            "recorded as _UNKNOWN, regardless of whether the keyring "
            "has since become readable"
        )
        assert keyring.get_password("geolens", refresh_account) == "old-refresh-token"

    def test_an_unknown_account_survives_a_later_failure_in_the_same_login(
        self, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """Exercises replace_credentials() directly (the interactive
        login flow's own call shape, refresh_token included) rather
        than through the CLI, so the api_key account's snapshot state
        is easy to control: a bearer login where the competing api_key
        account's snapshot is _UNKNOWN (transient), the keyring becomes
        readable again before cleanup, and the refresh-token write
        (which runs AFTER cleanup -- see
        TestInteractiveLoginRefreshTokenIsTransactional) then fails,
        forcing a rollback. The api_key account must never have been
        touched at all -- not deleted by cleanup, and therefore nothing
        for restore to (fail to) put back."""
        import keyring
        from keyring.errors import KeyringError

        from geolens_cli import auth as _auth
        from geolens_cli import config as _config

        instance = "https://x.example.com"
        canonical = _config.normalize_instance_url(instance)
        api_key_account = f"{canonical}:api_key"

        _auth.store_api_key(canonical, "old-api-key")

        original_get = keyring.get_password  # mock_keyring's dict-backed one
        calls_for_api_key = 0

        def flaky_get(service, username):
            nonlocal calls_for_api_key
            if username == api_key_account:
                calls_for_api_key += 1
                if calls_for_api_key == 1:
                    # The pre-store snapshot read: fails once, so the
                    # snapshot records _UNKNOWN for this account.
                    raise KeyringError("transient read failure")
            return original_get(service, username)

        monkeypatch.setattr("keyring.get_password", flaky_get)

        def raising_store_refresh_token(*args, **kwargs):
            raise OSError("refresh write rejected")

        monkeypatch.setattr(_auth, "store_refresh_token", raising_store_refresh_token)

        try:
            _auth.replace_credentials(
                canonical, "bearer", "new-bearer", refresh_token="new-refresh"
            )
            raised = False
        except Exception:
            raised = True
        assert raised, "the refresh-token write failure must propagate"

        # The competing api_key account (readable again after its one
        # transient failure) must still hold its ORIGINAL value --
        # cleanup skipped it because the snapshot never confirmed a
        # safe-to-delete state.
        loaded_api_key = _auth.load_api_key(canonical)
        assert loaded_api_key is not None
        assert loaded_api_key.value == "old-api-key"


class TestActiveKindMarkerWriteIsRollbackProtected:
    """fix(#1778 review round 11): the active_kind marker write sat
    OUTSIDE replace_credentials()'s rollback-protected block. If the
    keyring store succeeded but the marker write to credentials.toml
    then failed (read-only or full filesystem), the exception
    propagated straight past _restore_credentials -- for a same-kind
    login, the OLD keyring secret had ALREADY been overwritten by the
    new store call, so there was nothing left to fall back to; login
    reported failure with no working credential at all."""

    def test_a_marker_write_failure_restores_the_previous_credential(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli import auth as _auth
        from geolens_cli import config as _config
        from geolens_cli.main import app

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        instance = "https://x.example.com"
        canonical = _config.normalize_instance_url(instance)

        _auth.store_bearer_token(canonical, "old-bearer-token")

        def raising_write(*args, **kwargs):
            raise OSError("read-only filesystem")

        monkeypatch.setattr(_auth, "_write_credentials_file", raising_write)

        # Same-kind login: the keyring store below succeeds and
        # overwrites the old bearer with the new one BEFORE the marker
        # write (also to the now-broken filesystem) fails.
        result = runner.invoke(app, ["login", instance, "--token", "new-bearer-token"])

        assert result.exit_code != 0, result.output
        loaded = _auth.load_bearer_token(canonical)
        assert loaded is not None
        assert loaded.value == "old-bearer-token"


class TestInteractiveLoginRollbackRestoresTheWholeCredentialSet:
    """fix(#1778 round 32): _CredentialSnapshot/_restore_credentials
    covered bearer/api_key/refresh but not the refresh token's pairing
    fingerprint -- round 31 added the fingerprint to delete_
    credentials()/_delete_stale_credentials() by hand, but not to this
    pair, so a login that failed AFTER the fingerprint had already
    been swept by cleanup restored the OLD bearer+refresh pair WITHOUT
    their matching fingerprint. The next 401 then discarded the
    restored (perfectly valid) refresh token as unpaired instead of
    spending it."""

    def test_a_final_write_failure_restores_all_four_members_and_a_later_refresh_still_works(
        self, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        import pytest

        from geolens_cli import auth as _auth

        instance = "https://x.example.com/api"

        # An existing, fully paired interactive session.
        _auth.replace_credentials(
            instance, "bearer", "old-bearer-token", refresh_token="old-refresh-token"
        )
        old_bearer = mock_keyring[("geolens", instance)]
        old_refresh = mock_keyring[("geolens", f"{instance}:refresh")]
        old_fingerprint = mock_keyring[("geolens", f"{instance}:refresh_fp")]
        assert old_bearer == "old-bearer-token"
        assert old_refresh == "old-refresh-token"
        assert old_fingerprint == _auth._fingerprint_bearer("old-bearer-token")

        # A new interactive-style login (same kind: "bearer") that
        # fails on the FINAL write -- the new refresh token's own
        # store call, after the marker write and cleanup (which sweeps
        # the OLD refresh token + fingerprint, since "refresh" is
        # never `keep`) have already run.
        original_store_refresh_token = _auth.store_refresh_token

        def raising_store_refresh_token(*args, **kwargs):
            raise OSError("read-only filesystem")

        monkeypatch.setattr(_auth, "store_refresh_token", raising_store_refresh_token)

        with pytest.raises(OSError):
            _auth.replace_credentials(
                instance,
                "bearer",
                "new-bearer-token",
                refresh_token="new-refresh-token",
            )

        # All four members restored BYTE-FOR-BYTE.
        assert mock_keyring[("geolens", instance)] == old_bearer
        assert mock_keyring[("geolens", f"{instance}:refresh")] == old_refresh
        assert mock_keyring[("geolens", f"{instance}:refresh_fp")] == old_fingerprint

        # A subsequent 401 refreshes successfully using the RESTORED
        # pair -- this is the property round 31's gap broke: with the
        # fingerprint missing after a restore, try_refresh() would
        # have judged the restored (perfectly valid) refresh token
        # "unpaired" and discarded it instead of spending it.
        # Restore JUST store_refresh_token -- monkeypatch.undo() would
        # also un-patch keyring itself (mock_keyring uses the SAME
        # monkeypatch fixture), which is not what this step is about.
        monkeypatch.setattr(_auth, "store_refresh_token", original_store_refresh_token)
        import geolens
        import geolens.api.auth.refresh_auth_refresh_post as _refresh_mod
        import geolens.models.refresh_request as _refresh_req_mod
        from unittest.mock import MagicMock

        class FakeParsed:
            pass

        parsed = FakeParsed()
        parsed.access_token = "rotated-access-token"
        parsed.refresh_token = None

        class FakeResp:
            status_code = 200

        FakeResp.parsed = parsed

        monkeypatch.setattr(geolens, "GeolensClient", MagicMock())
        monkeypatch.setattr(_refresh_mod, "sync_detailed", MagicMock(return_value=FakeResp()))
        monkeypatch.setattr(_refresh_req_mod, "RefreshRequest", MagicMock())

        new_access = _auth.try_refresh(instance)

        assert new_access == "rotated-access-token"


class TestCleanupFileRewriteFailureIsRollbackProtected:
    """Distinct from TestActiveKindMarkerWriteIsRollbackProtected above:
    that test's marker-write failure is the FIRST credentials.toml
    write in the try block, so cleanup's own file-section rewrite (the
    second write, removing stale bearer_token/api_key/refresh_token
    fields — see _delete_stale_credentials) never runs at all. This
    covers cleanup's file write failing on its OWN, after the marker
    write already succeeded -- the same try/except still must restore
    the pre-swap snapshot."""

    def test_cleanups_own_file_rewrite_failure_restores_the_snapshot(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from geolens_cli import auth as _auth
        from geolens_cli import config as _config
        from geolens_cli.main import app

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        instance = "https://x.example.com"
        canonical = _config.normalize_instance_url(instance)

        # A stale api_key in the file gives _delete_stale_credentials'
        # file-section rewrite something to actually do (pop a field),
        # not just a no-op early return on an empty section.
        _auth.store_bearer_token(canonical, "old-bearer-token")
        _auth.store_api_key(canonical, "stale-api-key", no_keyring=True)

        original_write = _auth._write_credentials_file
        write_calls = 0

        def failing_on_second_write(*args, **kwargs):
            nonlocal write_calls
            write_calls += 1
            if write_calls == 1:
                # The marker write: let it succeed.
                return original_write(*args, **kwargs)
            # Cleanup's own file-section rewrite: fail it.
            raise OSError("read-only filesystem")

        monkeypatch.setattr(_auth, "_write_credentials_file", failing_on_second_write)

        result = runner.invoke(app, ["login", instance, "--token", "new-bearer-token"])

        assert result.exit_code != 0, result.output
        assert write_calls >= 2, "test did not reach cleanup's own file write"

        loaded_bearer = _auth.load_bearer_token(canonical)
        assert loaded_bearer is not None
        assert loaded_bearer.value == "old-bearer-token"
        loaded_api_key = _auth.load_api_key(canonical)
        assert loaded_api_key is not None
        assert loaded_api_key.value == "stale-api-key"


class TestSnapshotUnknownForcesFileBackend:
    """fix(#1778 review round 12): the _UNKNOWN sentinel used to be
    checked ONLY on the rollback path, after replace_credentials() had
    already called store_bearer_token/store_api_key -- the mutating
    keyring.set_password for the SAME account the snapshot just failed
    to read. A get_password failure is no guarantee the matching
    set_password would also fail (an entry that cannot be decoded can
    still be overwritten), so if the snapshot for the credential being
    replaced was unknown and a LATER step (the marker write, cleanup)
    then failed, rollback skipped restoring it -- login reported
    failure with the prior credential irreversibly gone, not restored.

    Round 12 closed that window by ABORTING outright before any store
    call. fix(#1778 review round 13): that broke the documented
    automatic credentials.toml fallback (round 8/9) for a headless box
    with no usable keyring -- an ordinary login now refused unless the
    caller already knew to pass --no-keyring, even when the file
    backend was perfectly writable. replace_credentials() now forces
    the keyring-free file path instead of aborting: set_password is
    still never attempted against an account whose read just failed
    (closing round 12's actual danger), but the login itself succeeds
    via the file when the file is writable, with the round-10 marker
    recorded so the file credential outranks any stale keyring entry
    that later becomes readable again. The rollback-side _UNKNOWN check
    (TestSnapshotUnknownStateNeverDeleted, above) stays as defense in
    depth for the OTHER accounts _delete_stale_credentials can still
    touch after a successful store."""

    def test_a_snapshot_read_failure_forces_the_file_backend_with_the_marker_set(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """Read fails; write is NOT mocked to fail (it would otherwise
        succeed) -- the asymmetric case the round-12 finding names.
        Asserts set_password is never even attempted, login still
        succeeds via the file, and the marker records the new kind."""
        import keyring
        from keyring.errors import KeyringError

        from geolens_cli import auth as _auth
        from geolens_cli import config as _config
        from geolens_cli.main import app

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        instance = "https://x.example.com"
        canonical = _config.normalize_instance_url(instance)
        bearer_account = canonical  # _keyring_account_token(instance)

        _auth.store_bearer_token(canonical, "old-bearer-token")

        original_get = keyring.get_password  # mock_keyring's dict-backed one
        set_calls: list[tuple[str, str]] = []
        original_set = keyring.set_password

        def failing_get(service, username):
            if username == bearer_account:
                raise KeyringError("entry cannot be decoded")
            return original_get(service, username)

        def tracking_set(service, username, password):
            set_calls.append((service, username))
            return original_set(service, username, password)

        monkeypatch.setattr("keyring.get_password", failing_get)
        monkeypatch.setattr("keyring.set_password", tracking_set)

        # Same-kind login: pre-round-13, this would either abort
        # outright (round 12) or call set_password on the bearer
        # account despite the read above having just failed for it
        # (pre-round-12) -- and set_password is NOT mocked to fail
        # here, so a call to it would have succeeded, destroying the
        # only copy of "old-bearer-token" before any later step could
        # roll back.
        result = runner.invoke(app, ["login", instance, "--token", "new-bearer-token"])

        assert result.exit_code == 0, result.output
        assert set_calls == [], (
            "replace_credentials must never call set_password against "
            "an account it just failed to read"
        )

        # The new token landed in the file (keyring was never touched
        # for this account), and the marker records "bearer" so it
        # outranks whatever the keyring account turns out to hold once
        # it becomes readable again.
        loaded_file = _auth._read_credentials_file().get(canonical, {})
        assert loaded_file.get("bearer_token") == "new-bearer-token"
        assert _auth.load_active_credential_kind(canonical) == "bearer"

        # The keyring becomes readable again -- the old bearer token
        # must still be exactly what it was: untouched, since
        # set_password was never called against it.
        monkeypatch.setattr("keyring.get_password", original_get)
        assert (
            keyring.get_password("geolens", bearer_account) == "old-bearer-token"
        )

    def test_keyring_unreadable_and_file_read_only_exits_network_with_no_mutation(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """Both backends fail: the keyring read for the target account
        raises, and the forced file write also raises. There is
        genuinely nowhere for the credential to land -- login must
        refuse (EXIT_NETWORK) and leave the prior state untouched."""
        import keyring
        from keyring.errors import KeyringError

        from geolens_cli import auth as _auth
        from geolens_cli import config as _config
        from geolens_cli._sdk_helpers import EXIT_NETWORK
        from geolens_cli.main import app

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        instance = "https://x.example.com"
        canonical = _config.normalize_instance_url(instance)
        bearer_account = canonical  # _keyring_account_token(instance)

        _auth.store_bearer_token(canonical, "old-bearer-token")

        original_get = keyring.get_password  # mock_keyring's dict-backed one

        def failing_get(service, username):
            if username == bearer_account:
                raise KeyringError("entry cannot be decoded")
            return original_get(service, username)

        def raising_write(*args, **kwargs):
            raise OSError("read-only filesystem")

        monkeypatch.setattr("keyring.get_password", failing_get)
        monkeypatch.setattr(_auth, "_write_credentials_file", raising_write)

        result = runner.invoke(app, ["login", instance, "--token", "new-bearer-token"])

        assert result.exit_code == EXIT_NETWORK, result.output

        monkeypatch.setattr("keyring.get_password", original_get)
        loaded = _auth.load_bearer_token(canonical)
        assert loaded is not None
        assert loaded.value == "old-bearer-token"
        assert _auth.load_active_credential_kind(canonical) is None


class TestInteractiveLoginRefreshTokenIsTransactional:
    """fix(#1778 review round 13): the interactive login flow used to
    persist the refresh token with a SEPARATE store_refresh_token() call
    AFTER replace_credentials() had already returned -- by then the new
    access token was committed and the prior refresh credential already
    deleted by replace_credentials()'s own cleanup. If that separate
    call then failed (keyring rejects, file fallback read-only), login
    reported failure with a half-replaced session: a valid new access
    token, no refresh token at all, and nothing left to roll back to.
    replace_credentials() now takes ``refresh_token`` itself and
    persists it inside its own snapshot/rollback transaction, so a
    failure there rolls back the access token, the refresh token, and
    the marker together."""

    def test_a_refresh_token_write_failure_restores_the_whole_prior_session(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        from unittest.mock import MagicMock

        from geolens_cli import auth as _auth
        from geolens_cli import config as _config

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        instance = "https://x.example.com"
        canonical = _config.normalize_instance_url(instance)

        # Realistic pre-existing session: an earlier login already set
        # the round-10 marker via replace_credentials(), not a bare
        # store_bearer_token() call.
        _auth.replace_credentials(canonical, "bearer", "old-access-token")
        _auth.store_refresh_token(canonical, "old-refresh-token")

        fake_response = MagicMock(
            status_code=200,
            parsed=MagicMock(
                access_token="new-access-token",
                refresh_token="new-refresh-token",
            ),
        )
        monkeypatch.setattr(
            "geolens.api.auth.login_auth_login_post.sync_detailed",
            lambda **kwargs: fake_response,
        )

        # Patched at the store_refresh_token() call site itself, not at
        # keyring.set_password -- the latter is also what
        # _restore_credentials() uses to put "old-refresh-token" back,
        # so blocking it unconditionally would block the restore this
        # test is trying to verify, not just the original write.
        def raising_store_refresh_token(*args, **kwargs):
            raise OSError("refresh keyring entry rejected")

        monkeypatch.setattr(_auth, "store_refresh_token", raising_store_refresh_token)

        result = runner.invoke(
            app,
            ["login", instance],
            input="alice\nsecret\n",
        )

        assert result.exit_code != 0, result.output

        # Counterfactual proof this is a FULL rollback, not a partial
        # one: the NEW access token must not have been left in place
        # either, even though replace_credentials() committed it before
        # the refresh-token write that failed.
        loaded_bearer = _auth.load_bearer_token(canonical)
        assert loaded_bearer is not None
        assert loaded_bearer.value == "old-access-token"

        loaded_refresh = _auth.load_refresh_token(canonical)
        assert loaded_refresh == "old-refresh-token"

        # The marker must also be back to whatever it was before this
        # login attempt (round 10) -- restore_credentials reverts the
        # whole file section, marker included.
        assert _auth.load_active_credential_kind(canonical) == "bearer"


class TestRefreshTokenSharesAccessTokenBackend:
    """fix(#1778 review round 14): replace_credentials() persisted the
    refresh token with the CALLER's original no_keyring, not
    store_no_keyring (the backend actually chosen for the access token
    a few lines above it). When the target keyring read was unknown,
    round 13 forces the access token into credentials.toml -- but the
    keyring itself may still be perfectly willing to accept the refresh
    token on its own account, so with the original no_keyring=False the
    two tokens landed in DIFFERENT backends. try_refresh() detects the
    backend from the refresh token's own location
    (_detect_credential_backend) and rewrites BOTH rotated tokens back
    to whatever it finds there -- so a rotation would move the refresh
    token into the keyring while load_bearer_token() kept preferring
    the (now stale, unrotated) file-backed bearer under its
    file-over-keyring precedence: every subsequent 401 tries to refresh
    again and never converges. Both tokens must always land in the SAME
    backend.

    fix(#1778 review round 15): round 14's fix keyed the refresh
    token's backend off ``store_no_keyring`` — the PRE-store intent
    computed from snapshot readability alone. That diverges from
    ``backend``, the store call's ACTUAL outcome, whenever
    ``keyring.get_password`` succeeds at snapshot time (so
    ``store_no_keyring`` stays False) but ``keyring.set_password`` then
    fails at STORE time — a locked keychain needing a write unlock,
    contention, a quota. ``store_bearer_token``/``store_api_key``
    already catch that and fall back to the file, returning
    ``backend == "file"``, while ``store_no_keyring`` stays False; the
    refresh write then tried the keyring first, and if THAT account's
    ``set_password`` happened to succeed, the two tokens split again —
    the exact bug this round exists to close, reopened through a
    store-time failure this class's original tests never exercised
    (they only fail ``get_password``). The refresh write now keys off
    ``backend != "keyring"`` — the real outcome, not the pre-store
    intent."""

    def test_a_forced_file_login_puts_both_tokens_in_the_file(
        self, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """The target account's snapshot is _UNKNOWN (forcing the file
        backend, round 13), but the keyring itself is NOT globally
        broken -- set_password would happily accept the refresh token
        if asked. It must not be asked: both tokens belong in the file
        together."""
        import keyring
        from keyring.errors import KeyringError

        from geolens_cli import auth as _auth
        from geolens_cli import config as _config

        instance = "https://x.example.com"
        canonical = _config.normalize_instance_url(instance)
        bearer_account = canonical

        original_get = keyring.get_password  # mock_keyring's dict-backed one

        def failing_get(service, username):
            if username == bearer_account:
                raise KeyringError("entry cannot be decoded")
            return original_get(service, username)

        monkeypatch.setattr("keyring.get_password", failing_get)

        backend = _auth.replace_credentials(
            canonical, "bearer", "new-access", refresh_token="new-refresh"
        )

        assert backend == "file"
        file_section = _auth._read_credentials_file().get(canonical, {})
        assert file_section.get("bearer_token") == "new-access"
        assert file_section.get("refresh_token") == "new-refresh"
        # Neither token was ever asked of the keyring for this account.
        monkeypatch.setattr("keyring.get_password", original_get)
        assert keyring.get_password("geolens", bearer_account) is None
        assert keyring.get_password("geolens", f"{canonical}:refresh") is None

    def test_a_keyring_login_puts_both_tokens_in_the_keyring(
        self, tmp_xdg_home, mock_keyring
    ) -> None:
        """The ordinary happy path, as a negative control: nothing
        forces the file, so both tokens land in the keyring together,
        same as before this fix."""
        from geolens_cli import auth as _auth
        from geolens_cli import config as _config

        instance = "https://x.example.com"
        canonical = _config.normalize_instance_url(instance)

        backend = _auth.replace_credentials(
            canonical, "bearer", "new-access", refresh_token="new-refresh"
        )

        assert backend == "keyring"
        assert _auth.load_bearer_token(canonical).value == "new-access"
        assert _auth.load_refresh_token(canonical) == "new-refresh"
        # Confirms via the file, not just load_*() (which would also
        # resolve a keyring value) -- the file section must be empty.
        file_section = _auth._read_credentials_file().get(canonical, {})
        assert "bearer_token" not in file_section
        assert "refresh_token" not in file_section

    def test_try_refresh_detects_the_file_backend_from_where_the_tokens_landed(
        self, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """End-to-end proof the two fixes compose: a forced-file login
        (this round) followed by try_refresh() (BUG-013, pre-existing)
        rotates both tokens back into the SAME backend it found them
        in -- the file -- rather than leaking the rotated refresh token
        into the keyring."""
        import keyring
        from keyring.errors import KeyringError
        from unittest.mock import MagicMock

        from geolens_cli import auth as _auth
        from geolens_cli import config as _config

        instance = "https://x.example.com"
        canonical = _config.normalize_instance_url(instance)
        bearer_account = canonical

        original_get = keyring.get_password  # mock_keyring's dict-backed one

        def failing_get(service, username):
            if username == bearer_account:
                raise KeyringError("entry cannot be decoded")
            return original_get(service, username)

        monkeypatch.setattr("keyring.get_password", failing_get)
        _auth.replace_credentials(
            canonical, "bearer", "old-access", refresh_token="old-refresh"
        )
        monkeypatch.setattr("keyring.get_password", original_get)

        import geolens
        import geolens.api.auth.refresh_auth_refresh_post as _refresh_mod
        import geolens.models.refresh_request as _refresh_req_mod

        parsed = MagicMock(access_token="rotated-access", refresh_token="rotated-refresh")
        fake_resp = MagicMock(status_code=200, parsed=parsed)
        monkeypatch.setattr(geolens, "GeolensClient", MagicMock())
        monkeypatch.setattr(_refresh_mod, "sync_detailed", MagicMock(return_value=fake_resp))
        monkeypatch.setattr(_refresh_req_mod, "RefreshRequest", MagicMock())

        new_access = _auth.try_refresh(canonical)

        assert new_access == "rotated-access"
        file_section = _auth._read_credentials_file().get(canonical, {})
        assert file_section.get("bearer_token") == "rotated-access"
        assert file_section.get("refresh_token") == "rotated-refresh"
        assert keyring.get_password("geolens", bearer_account) is None
        assert keyring.get_password("geolens", f"{canonical}:refresh") is None

    def test_a_store_time_keyring_failure_also_keeps_both_tokens_together(
        self, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """fix(#1778 review round 15): the round-14 fix keyed the
        refresh-token backend off store_no_keyring -- the PRE-store
        INTENT computed from snapshot readability alone -- not off
        `backend`, the store call's ACTUAL outcome. Reproduces the
        divergence the round-15 audit found: keyring.get_password
        SUCCEEDS at snapshot time (so store_no_keyring stays False --
        this is NOT the target_is_unknown/forced-file case above), but
        keyring.set_password then fails for the bearer account only at
        STORE time (a locked keychain needing a write unlock,
        contention, a quota) -- store_bearer_token already catches
        that and falls back to the file, returning backend == "file".
        The refresh account's OWN set_password is left free to
        succeed, so with the pre-round-15 code the refresh token would
        land in the keyring while the access token sat in the file."""
        import keyring
        from keyring.errors import KeyringError

        from geolens_cli import auth as _auth
        from geolens_cli import config as _config

        instance = "https://x.example.com"
        canonical = _config.normalize_instance_url(instance)
        bearer_account = canonical
        refresh_account = f"{canonical}:refresh"

        original_set = keyring.set_password  # mock_keyring's dict-backed one

        def failing_set(service, username, password):
            if username == bearer_account:
                raise KeyringError("locked keychain needs a write unlock")
            return original_set(service, username, password)

        monkeypatch.setattr("keyring.set_password", failing_set)

        # Snapshot reads are NOT mocked to fail -- both accounts are
        # confirmed-absent (None), not _UNKNOWN, so target_is_unknown
        # stays False and store_no_keyring stays False too. This is
        # what distinguishes the round-15 cell from round 14's
        # forced-file test above.
        backend = _auth.replace_credentials(
            canonical, "bearer", "new-access", refresh_token="new-refresh"
        )

        assert backend == "file"
        file_section = _auth._read_credentials_file().get(canonical, {})
        assert file_section.get("bearer_token") == "new-access"
        assert file_section.get("refresh_token") == "new-refresh"
        # The refresh account's set_password was never even asked --
        # it would have succeeded if it had been.
        assert keyring.get_password("geolens", refresh_account) is None
        assert keyring.get_password("geolens", bearer_account) is None


class TestUnreadableKeyringDuringCleanup:
    """fix(#1778 review round 8): an unreadable keyring during the
    existence check (locked, backend down, ...) is not "no such
    entry". Round 7 treated it as such, which left a stale credential
    untouched in a keyring that store_bearer_token/store_api_key had
    themselves just fallen back away from (they also catch
    KeyringError and write to credentials.toml instead) — once the
    keyring became readable again, the untouched stale value won under
    AppState.sdk()'s bearer-first precedence.

    fix(#1778 review round 9): round 8's propagation was
    unconditional, which broke `login --no-keyring` and any headless
    install with no working keyring at all -- keep_backend is "file"
    in both cases, and the cleanup loop still tried (and failed) to
    read the keyring regardless, defeating the automatic file
    fallback. An unreadable keyring during cleanup is now fatal ONLY
    when keep_backend == "keyring" (the keyring is demonstrably
    reachable right now -- the new credential just landed there, so a
    read failure for a DIFFERENT account is a real problem); when the
    new credential went to the file instead (--no-keyring, or the
    store itself already fell back), an unreadable keyring is
    tolerated the same as "no such entry".

    fix(#1778 review round 14): round 8's "real problem" framing only
    holds when the account was READABLE at snapshot time and then
    became unreadable mid-transaction -- a genuine, worth-surfacing
    hiccup. _delete_stale_credentials now also skips an account whose
    SNAPSHOT (taken before any mutation) already came back _UNKNOWN,
    regardless of keep_backend: an account we never had visibility
    into cannot safely be deleted (see
    TestSnapshotUnknownIsNeverDeletedByCleanup), and the round-10
    marker already makes a stale entry in another backend harmless
    either way. test_a_keyring_that_cannot_be_read_at_cleanup below now
    lets the snapshot read succeed and only breaks the LATER cleanup
    read, so it keeps exercising round 8's actual case instead of the
    now-tolerated one."""

    def test_a_keyring_that_cannot_be_read_at_cleanup_restores_the_snapshot_and_exits_nonzero(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """The new credential DOES land in the keyring (keep_backend ==
        "keyring", so the keyring is confirmed reachable right now),
        and the account was READABLE at snapshot time (this is not the
        round-14 "never had visibility" case) -- but the cleanup step's
        LATER read of that same competing account fails. That is a
        real, worth-surfacing problem, not an unavailable backend, and
        round 8's behavior for it stands."""
        import keyring
        from keyring.errors import KeyringError

        from geolens_cli import auth as _auth
        from geolens_cli import config as _config

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        instance = "https://x.example.com"
        canonical = _config.normalize_instance_url(instance)
        bearer_account = canonical  # _keyring_account_token(instance)

        # Old bearer token lives in a currently-working keyring.
        _auth.store_bearer_token(canonical, "old-bearer-token")

        original_get = keyring.get_password  # mock_keyring's dict-backed one
        calls_for_bearer = 0

        def flaky_get(service, username):
            nonlocal calls_for_bearer
            if username == bearer_account:
                calls_for_bearer += 1
                if calls_for_bearer > 1:
                    # The FIRST read is replace_credentials()'s own
                    # pre-store snapshot -- it must succeed, so the
                    # snapshot is NOT _UNKNOWN and round 14's skip does
                    # not apply. Only the cleanup step's read (the
                    # second call onward) fails.
                    raise KeyringError("keychain hiccup")
            return original_get(service, username)

        monkeypatch.setattr("keyring.get_password", flaky_get)

        # The new api_key store to keyring itself succeeds -- only the
        # competing bearer account's cleanup read is broken.
        result = runner.invoke(app, ["login", instance, "--api-key", "new-key"])

        assert result.exit_code != 0, result.output
        assert "keyring" in result.output.lower()

    def test_no_keyring_login_succeeds_even_if_the_keyring_raises(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """The regression this round fixes: --no-keyring must work on a
        box with no functioning keyring backend at all."""
        from keyring.errors import KeyringError

        from geolens_cli import auth as _auth
        from geolens_cli import config as _config

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        instance = "https://x.example.com"
        canonical = _config.normalize_instance_url(instance)

        def broken(*args, **kwargs):
            raise KeyringError("no keyring backend available")

        monkeypatch.setattr("keyring.get_password", broken)
        monkeypatch.setattr("keyring.set_password", broken)
        monkeypatch.setattr("keyring.delete_password", broken)

        result = runner.invoke(
            app, ["login", instance, "--api-key", "new-key", "--no-keyring"]
        )

        assert result.exit_code == 0, result.output
        loaded = _auth.load_api_key(canonical)
        assert loaded is not None
        assert loaded.value == "new-key"

    def test_plain_login_falls_back_to_file_when_the_keyring_is_entirely_unavailable(
        self, runner, tmp_xdg_home, mock_keyring, monkeypatch
    ) -> None:
        """The other half of the regression round 8/9 fixed: a PLAIN
        login (no --no-keyring flag) on a box where the keyring simply
        doesn't work must also succeed via the automatic file fallback,
        not just an explicit --no-keyring invocation.

        fix(#1778 review round 12): this test briefly asserted the
        OPPOSITE -- that a plain login should refuse outright when the
        keyring is unreadable -- because replace_credentials() aborted
        before any store call whenever the snapshot for the target
        account was unknown. fix(#1778 review round 13): that broke
        this documented fallback for real headless installs, so
        round 13 restores it: an unreadable snapshot now forces the
        keyring-free file path (see TestSnapshotUnknownForcesFileBackend)
        rather than aborting. The marker assertion below is new --
        round 10's active_kind marker must be set to "api_key" so a
        stale keyring entry that becomes readable later cannot outrank
        the credential this login actually stored."""
        from keyring.errors import KeyringError

        from geolens_cli import auth as _auth
        from geolens_cli import config as _config

        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        instance = "https://x.example.com"
        canonical = _config.normalize_instance_url(instance)

        def locked(*args, **kwargs):
            raise KeyringError("keychain is locked")

        monkeypatch.setattr("keyring.set_password", locked)
        monkeypatch.setattr("keyring.get_password", locked)

        result = runner.invoke(app, ["login", instance, "--api-key", "new-key"])

        assert result.exit_code == 0, result.output
        loaded = _auth.load_api_key(canonical)
        assert loaded is not None
        assert loaded.value == "new-key"
        assert _auth.load_active_credential_kind(canonical) == "api_key"


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

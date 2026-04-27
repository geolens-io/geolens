"""Exit-code matrix (CONTEXT.md D-32).

Plan 01 stubbed login/logout/whoami exits at 2; Plan 02 replaced those stubs
with real implementations whose exit codes depend on state:
- whoami with no instance configured → EXIT_AUTH (3)
- login --token + --api-key together → EXIT_USAGE (2)
Plan 03 wires scan to walk + classify (exits 0 even on all-ingest:no per
D-17); the remaining stub commands (publish, export stac) still exit 2
until Plans 04-05 land.
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


class TestExitCodeConstants:
    def test_constants_match_d32(self) -> None:
        assert EXIT_OK == 0
        assert EXIT_GENERIC == 1
        assert EXIT_USAGE == 2
        assert EXIT_AUTH == 3
        assert EXIT_NETWORK == 4
        assert EXIT_SERVER == 5


class TestRemainingStubsExitWithUsage:
    """Plans 04-05 still ship stubs that exit 2 until they land.

    Plan 03 replaced the scan stub with a real walker (exits 0 on dry-run
    per D-17); the per-command exit-code behavior for scan is asserted in
    test_scan.py::TestCliInvocation.
    """

    def test_publish_stub_exits_2(self, runner, tmp_path) -> None:
        f = tmp_path / "x.geojson"
        f.write_text("{}")
        result = runner.invoke(app, ["publish", str(f)])
        assert result.exit_code == 2

    def test_export_stac_stub_exits_2(self, runner) -> None:
        result = runner.invoke(app, ["export", "stac", "abc"])
        assert result.exit_code == 2


class TestAuthCommandExitCodes:
    """Real per-command behavior (Plan 02 replaces the Plan 01 stubs)."""

    def test_login_mutually_exclusive_token_and_api_key(self, runner, tmp_xdg_home) -> None:
        result = runner.invoke(
            app,
            ["login", "https://x.example.com", "--token", "abc", "--api-key", "xyz", "--no-keyring"],
        )
        assert result.exit_code == 2

    def test_login_rejects_non_http_url(self, runner, tmp_xdg_home) -> None:
        result = runner.invoke(app, ["login", "ftp://x.example.com", "--token", "abc", "--no-keyring"])
        assert result.exit_code == 2

    def test_login_with_token_succeeds(self, runner, tmp_xdg_home, mock_keyring) -> None:
        result = runner.invoke(app, ["login", "https://x.example.com", "--token", "abc.def.ghi"])
        assert result.exit_code == 0, result.output

    def test_logout_with_no_instance_exits_2(self, runner, tmp_xdg_home, mock_keyring) -> None:
        result = runner.invoke(app, ["logout"])
        assert result.exit_code == 2

    def test_logout_after_login_succeeds(self, runner, tmp_xdg_home, mock_keyring) -> None:
        runner.invoke(app, ["login", "https://x.example.com", "--token", "abc.def.ghi"])
        result = runner.invoke(app, ["logout"])
        assert result.exit_code == 0, result.output

    def test_whoami_with_no_instance_exits_3(self, runner, tmp_xdg_home, mock_keyring, monkeypatch) -> None:
        monkeypatch.delenv("GEOLENS_INSTANCE", raising=False)
        monkeypatch.delenv("GEOLENS_TOKEN", raising=False)
        result = runner.invoke(app, ["whoami"])
        assert result.exit_code == EXIT_AUTH, result.output

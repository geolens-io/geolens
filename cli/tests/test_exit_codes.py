"""Exit-code matrix (CONTEXT.md D-32)."""
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


class TestStubCommandsExitWithUsage:
    """Stub bodies in main.py exit with EXIT_USAGE (2) until plans 02-05 land.

    These tests guard the matrix shape; they will be replaced by real
    per-command behavior tests in plans 02-05.
    """

    def test_login_stub_exits_2(self, runner) -> None:
        result = runner.invoke(app, ["login", "https://example.com"])
        assert result.exit_code == 2

    def test_logout_stub_exits_2(self, runner) -> None:
        result = runner.invoke(app, ["logout"])
        assert result.exit_code == 2

    def test_whoami_stub_exits_2(self, runner) -> None:
        result = runner.invoke(app, ["whoami"])
        assert result.exit_code == 2

    def test_scan_stub_exits_2(self, runner, tmp_path) -> None:
        result = runner.invoke(app, ["scan", str(tmp_path)])
        assert result.exit_code == 2

    def test_publish_stub_exits_2(self, runner, tmp_path) -> None:
        f = tmp_path / "x.geojson"
        f.write_text("{}")
        result = runner.invoke(app, ["publish", str(f)])
        assert result.exit_code == 2

    def test_export_stac_stub_exits_2(self, runner) -> None:
        result = runner.invoke(app, ["export", "stac", "abc"])
        assert result.exit_code == 2

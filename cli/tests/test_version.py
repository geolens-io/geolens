"""OCCLI-01: `geolens --version` prints version and exits 0 (no config, no SDK)."""

from __future__ import annotations

from geolens_cli import __version__
from geolens_cli.main import app


class TestVersion:
    def test_module_version_is_string(self) -> None:
        assert isinstance(__version__, str)
        assert __version__  # non-empty

    def test_version_flag_prints_and_exits(self, runner) -> None:
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0, result.output
        assert result.output.startswith("geolens "), result.output

    def test_help_lists_subcommands(self, runner) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0, result.output
        for cmd in (
            "init",
            "validate",
            "login",
            "logout",
            "whoami",
            "scan",
            "publish",
            "export",
        ):
            assert cmd in result.output, f"missing {cmd} in --help"

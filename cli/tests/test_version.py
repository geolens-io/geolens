"""OCCLI-01: `geolens --version` prints version and exits 0 (no config, no SDK)."""

from __future__ import annotations

from importlib import metadata

from geolens_cli import __version__
from geolens_cli.main import app


class TestVersion:
    def test_module_version_is_string(self) -> None:
        assert isinstance(__version__, str)
        assert __version__  # non-empty

    def test_module_version_sourced_from_cli_distribution(self) -> None:
        """BUG-031: the version must come from `geolens-cli`, not the SDK."""
        assert __version__ == metadata.version("geolens-cli")

    def test_version_flag_reports_cli_distribution(self, runner, monkeypatch) -> None:
        """BUG-031: `--version` must look up `geolens-cli`, not `geolens`.

        Map the SDK distribution to a sentinel that must NOT appear, and the
        CLI distribution to a recognizable value that MUST appear.
        """
        real_version = metadata.version

        def fake_version(name: str) -> str:
            if name == "geolens":
                return "9.9.9-sdk-should-not-be-reported"
            if name == "geolens-cli":
                return "1.2.3-cli"
            return real_version(name)

        monkeypatch.setattr("importlib.metadata.version", fake_version)
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0, result.output
        assert "1.2.3-cli" in result.output, result.output
        assert "9.9.9-sdk-should-not-be-reported" not in result.output, result.output

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

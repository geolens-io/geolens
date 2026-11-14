"""Output formatter — JSON vs human; NO_COLOR honored; quiet/verbose toggles."""

from __future__ import annotations

import json
from pathlib import Path

from geolens_cli.output import Formatter


class TestFormatter:
    def test_json_success_emits_json(self, capsys) -> None:
        fmt = Formatter(json_mode=True)
        fmt.success("done")
        out = capsys.readouterr().out.strip()
        payload = json.loads(out)
        assert payload == {"ok": True, "message": "done"}

    def test_json_error_emits_json_to_stderr(self, capsys) -> None:
        fmt = Formatter(json_mode=True)
        fmt.error("boom")
        err = capsys.readouterr().err.strip()
        payload = json.loads(err)
        assert payload == {"ok": False, "error": "boom"}

    def test_quiet_suppresses_success(self, capsys) -> None:
        fmt = Formatter(json_mode=False, quiet=True)
        fmt.success("done")
        assert capsys.readouterr().out == ""

    def test_quiet_does_not_suppress_error(self, capsys) -> None:
        fmt = Formatter(json_mode=False, quiet=True)
        fmt.error("boom")
        assert "boom" in capsys.readouterr().err

    def test_verbose_emits_debug(self, capsys) -> None:
        fmt = Formatter(json_mode=False, verbose=True)
        fmt.debug("hint")
        assert "hint" in capsys.readouterr().err

    def test_no_verbose_silences_debug(self, capsys) -> None:
        fmt = Formatter(json_mode=False, verbose=False)
        fmt.debug("hint")
        assert "hint" not in capsys.readouterr().err

    def test_no_color_env_var_disables_ansi(self, monkeypatch, capsys) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        fmt = Formatter(json_mode=False)
        fmt.error("boom")
        err = capsys.readouterr().err
        assert "\x1b[" not in err  # no ANSI escape sequences

    def test_mask_applies_to_every_string_of_a_json_payload(self, capsys) -> None:
        fmt = Formatter(json_mode=True, mask=lambda text: text.replace("s3cr3t", "*"))
        fmt.json(
            {"a s3cr3t": ["x s3cr3t"], "a *": 1, "path": Path("/tmp/s3cr3t"), "n": 2}
        )
        assert json.loads(capsys.readouterr().out) == {
            "a *": ["x *"],
            "a *#": 1,
            "path": "/tmp/*",
            "n": 2,
        }

# SPDX-License-Identifier: Apache-2.0
"""Output formatter — rich Console + JSON mode + exit-code constants.

Hand-maintained — NOT regenerated. Centralizes stdout/stderr formatting so
every command respects --json / --quiet / --verbose / NO_COLOR.
"""
from __future__ import annotations

import json as _json
import os
import sys
from dataclasses import dataclass
from typing import Any

import typer
from rich.console import Console


@dataclass
class Formatter:
    json_mode: bool = False
    quiet: bool = False
    verbose: bool = False

    def __post_init__(self) -> None:
        no_color = bool(os.environ.get("NO_COLOR"))
        self._stdout = Console(no_color=no_color, file=sys.stdout, force_terminal=False if self.json_mode else None)
        self._stderr = Console(no_color=no_color, file=sys.stderr, stderr=True, force_terminal=False if self.json_mode else None)

    @property
    def is_tty(self) -> bool:
        return sys.stdout.isatty() and not self.json_mode

    @property
    def console_stdout(self) -> Console:
        """Public accessor for the underlying stdout Console.

        Used by commands that need to render rich primitives (tables, trees)
        beyond the success/error/info/json/debug message helpers — e.g.,
        Plan 03 (scan) renders a rich.Table for human output.
        """
        return self._stdout

    def success(self, message: str) -> None:
        if self.json_mode:
            typer.echo(_json.dumps({"ok": True, "message": message}))
            return
        if not self.quiet:
            self._stdout.print(message)

    def error(self, message: str) -> None:
        if self.json_mode:
            typer.echo(_json.dumps({"ok": False, "error": message}), err=True)
            return
        self._stderr.print(f"[red]Error:[/red] {message}")

    def json(self, payload: Any) -> None:
        typer.echo(_json.dumps(payload, indent=2 if self.is_tty else None, sort_keys=True, default=str))

    def info(self, message: str) -> None:
        if self.json_mode or self.quiet:
            return
        self._stdout.print(message)

    def debug(self, message: str) -> None:
        if self.verbose and not self.json_mode:
            self._stderr.print(f"[dim]debug:[/dim] {message}")

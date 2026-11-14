# SPDX-License-Identifier: Apache-2.0
"""Output formatter — rich Console + JSON mode + exit-code constants.

Hand-maintained — NOT regenerated. Centralizes stdout/stderr formatting so
every command respects --json / --quiet / --verbose / NO_COLOR.
"""

from __future__ import annotations

import json as _json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import typer
from rich.console import Console
from rich.markup import escape


@dataclass
class Formatter:
    json_mode: bool = False
    quiet: bool = False
    verbose: bool = False
    # Applied to every message and every string in a JSON payload, keys
    # included, just before it is written.
    mask: Callable[[str], str] | None = None

    def __post_init__(self) -> None:
        no_color = bool(os.environ.get("NO_COLOR"))
        self._stdout = Console(
            no_color=no_color,
            file=sys.stdout,
            force_terminal=False if self.json_mode else None,
        )
        self._stderr = Console(
            no_color=no_color,
            file=sys.stderr,
            stderr=True,
            force_terminal=False if self.json_mode else None,
        )

    @property
    def is_tty(self) -> bool:
        return sys.stdout.isatty() and not self.json_mode

    @property
    def console_stdout(self) -> Console:
        """Public accessor for the underlying stdout Console.

        Used by commands that need to render rich primitives (tables, trees)
        beyond the success/error/info/json/debug message helpers — e.g.,
        the scan command renders a rich.Table for human output.
        """
        return self._stdout

    def _masked(self, message: str) -> str:
        return message if self.mask is None else self.mask(message)

    def _masked_json(self, value: Any) -> Any:
        mask = self.mask
        if mask is None:
            return value
        if isinstance(value, str):
            return mask(value)
        if isinstance(value, list | tuple):
            return [self._masked_json(v) for v in value]
        if not isinstance(value, dict):
            return value
        out: dict[Any, Any] = {}
        for key, item in value.items():
            name = mask(key) if isinstance(key, str) else key
            # Two keys can mask to the same text; keep both values.
            while name in out:
                name = f"{name}#"
            out[name] = self._masked_json(item)
        return out

    def success(self, message: str) -> None:
        message = self._masked(message)
        if self.json_mode:
            typer.echo(_json.dumps({"ok": True, "message": message}))
            return
        if not self.quiet:
            self._stdout.print(message, soft_wrap=True, markup=False)

    def error(self, message: str) -> None:
        message = self._masked(message)
        if self.json_mode:
            typer.echo(_json.dumps({"ok": False, "error": message}), err=True)
            return
        self._stderr.print(
            f"Error: {message}", style="red", soft_wrap=True, markup=False
        )

    def warn(self, message: str) -> None:
        # Non-fatal advisory. Silent in --json/--quiet so machine-readable stdout
        # stays clean (CliRunner mixes stderr into captured output); humans get it
        # on stderr.
        if self.json_mode or self.quiet:
            return
        message = self._masked(message)
        self._stderr.print(
            f"Warning: {message}", style="yellow", soft_wrap=True, markup=False
        )

    def json(self, payload: Any) -> None:
        typer.echo(
            _json.dumps(
                self._masked_json(payload),
                indent=2 if self.is_tty else None,
                sort_keys=True,
                default=lambda value: self._masked(str(value)),
            )
        )

    def info(self, message: str) -> None:
        if self.json_mode or self.quiet:
            return
        self._stdout.print(self._masked(message), soft_wrap=True, markup=False)

    def debug(self, message: str) -> None:
        if self.verbose and not self.json_mode:
            self._stderr.print(f"[dim]debug:[/dim] {escape(self._masked(message))}")

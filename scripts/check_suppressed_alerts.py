#!/usr/bin/env python3
"""Fail when a CodeQL result suppressed in source still has an open alert.

advanced-security/dismiss-alerts indexes alerts by rule, path and start
position. When a dismissed alert and an open one share that key, the dismissed
one wins the index and the open alert is never touched, yet the step still
exits 0. This check matches every suppressed SARIF result against the open
alerts itself and reports any that remain.

Usage: check_suppressed_alerts.py <sarif file or directory> <owner/repo>
Needs the GitHub CLI authenticated with a token that can read code scanning
alerts.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _key(rule: str, path: str, line: int, column: int) -> tuple[str, str, int, int]:
    return (rule, path, line or 0, column or 1)


def suppressed_keys(sarif: dict) -> set[tuple[str, str, int, int]]:
    keys = set()
    for run in sarif.get("runs", []):
        for result in run.get("results", []):
            if not result.get("suppressions"):
                continue
            physical = result["locations"][0]["physicalLocation"]
            region = physical.get("region", {})
            keys.add(
                _key(
                    result.get("ruleId") or result["rule"]["id"],
                    physical["artifactLocation"]["uri"],
                    region.get("startLine", 0),
                    region.get("startColumn", 1),
                )
            )
    return keys


def stuck_alerts(sarif: dict, open_alerts: list[dict]) -> list[dict]:
    wanted = suppressed_keys(sarif)
    stuck = []
    for alert in open_alerts:
        loc = (alert.get("most_recent_instance") or {}).get("location") or {}
        key = _key(
            (alert.get("rule") or {}).get("id") or "",
            loc.get("path") or "",
            loc.get("start_line") or 0,
            loc.get("start_column") or 1,
        )
        if key in wanted:
            stuck.append(alert)
    return stuck


def _load_sarif(path: Path) -> dict:
    files = sorted(path.rglob("*.sarif")) if path.is_dir() else [path]
    if not files:
        raise SystemExit(f"no SARIF files under {path}")
    runs: list[dict] = []
    for file in files:
        runs.extend(json.loads(file.read_text(encoding="utf-8")).get("runs", []))
    return {"runs": runs}


def _open_alerts(repo: str) -> list[dict]:
    out = subprocess.run(
        [
            "gh", "api", "--paginate", "--slurp",
            f"repos/{repo}/code-scanning/alerts?state=open&tool_name=CodeQL&per_page=100",
        ],
        check=True, capture_output=True, text=True,
    ).stdout
    return [alert for page in json.loads(out) for alert in page]


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    stuck = stuck_alerts(_load_sarif(Path(argv[1])), _open_alerts(argv[2]))
    for alert in stuck:
        loc = alert["most_recent_instance"]["location"]
        print(
            f"::error::alert {alert['number']} ({alert['rule']['id']} at "
            f"{loc['path']}:{loc['start_line']}) is suppressed in source but still open"
        )
    return 1 if stuck else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""The post-dismissal check must flag a suppressed result whose alert is open."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_suppressed_alerts.py"
_spec = importlib.util.spec_from_file_location("check_suppressed_alerts", _SCRIPT)
assert _spec and _spec.loader
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)

PATH = "backend/app/processing/ingest/metadata_extent.py"


def _result(line: int, *, suppressed: bool) -> dict:
    result = {
        "ruleId": "py/sql-injection",
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": PATH},
                    "region": {"startLine": line, "startColumn": 13},
                }
            }
        ],
    }
    if suppressed:
        result["suppressions"] = [{"kind": "inSource"}]
    return result


def _alert(number: int, line: int) -> dict:
    return {
        "number": number,
        "rule": {"id": "py/sql-injection"},
        "most_recent_instance": {
            "location": {"path": PATH, "start_line": line, "start_column": 13}
        },
    }


def test_open_alert_at_a_suppressed_location_is_reported() -> None:
    sarif = {"runs": [{"results": [_result(148, suppressed=True)]}]}
    assert [a["number"] for a in checker.stuck_alerts(sarif, [_alert(136, 148)])] == [
        136
    ]


def test_open_alert_without_a_suppression_is_left_alone() -> None:
    sarif = {
        "runs": [
            {"results": [_result(148, suppressed=True), _result(200, suppressed=False)]}
        ]
    }
    assert checker.stuck_alerts(sarif, [_alert(7, 200), _alert(8, 300)]) == []

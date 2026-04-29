#!/usr/bin/env python3
"""Phase 218 verification gate. Six checks; exits 0 on PASS, 1 on FAIL.

Run from repo root:
    python3 .planning/phases/218-oc-audit-close-v13-1/verify_close_audit.py

Asserts (D-10):
  1. docs-internal/audits/oc-separation-audit-v13.1-close.md exists.
  2. File contains a parseable `## Scorecard` table.
  3. Boundary Integrity >= A-, Seam Quality >= B, OSS Surface >= C.
  4. File contains `## 8. Comparison to Prior Audit` section.
  5. File contains `## P1 Residual Triage` section with at least one table row.
  6. docs-internal/audits/oc-separation-deferred-items-20260426.md has >= 6
     `Closed by Phase NNN (YYYY-MM-DD)` markers (D-08).

Exits 1 on any failure (D-06: STOP on grade shortfall, no auto-advance).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

CLOSE = Path("docs-internal/audits/oc-separation-audit-v13.1-close.md")
DEFERRED = Path("docs-internal/audits/oc-separation-deferred-items-20260426.md")

GRADE_VALUES = {
    "A+": 4.33, "A": 4.0, "A-": 3.67,
    "B+": 3.33, "B": 3.0, "B-": 2.67,
    "C+": 2.33, "C": 2.0, "C-": 1.67,
    "D+": 1.33, "D": 1.0, "D-": 0.67, "F": 0.0,
}
THRESHOLDS = {  # substring -> minimum grade (skill emits "OSS Surface Readiness")
    "Boundary Integrity": "A-",
    "Seam Quality": "B",
    "OSS Surface": "C",
}


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def normalize(s: str) -> str:
    """Strip markdown bold/whitespace and replace U+2212 with U+002D."""
    return s.strip().strip("*").replace("−", "-")


def main() -> int:
    # Check 1: file exists
    if not CLOSE.is_file():
        fail(f"closing audit not found at {CLOSE}")
    text = CLOSE.read_text(encoding="utf-8")

    # Check 2: Scorecard table parses
    m = re.search(r"^##\s+Scorecard\s*$(.*?)^##\s+", text, re.MULTILINE | re.DOTALL)
    if not m:
        fail("'## Scorecard' section not found")
    section = m.group(1)
    rows = re.findall(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|", section, re.MULTILINE)
    grades: dict[str, str] = {}
    for name, grade in rows:
        n = normalize(name)
        g = normalize(grade)
        if n.lower() in ("dimension", "---", ""):
            continue
        if g not in GRADE_VALUES:
            continue  # skip rationale-only or separator rows
        grades[n] = g
    if not grades:
        fail("Scorecard table has no parseable grade rows")

    # Check 3: thresholds met (substring match for dimension name)
    for needle, threshold in THRESHOLDS.items():
        matched = [(n, g) for n, g in grades.items() if needle.lower() in n.lower()]
        if not matched:
            fail(f"dimension matching '{needle}' not found in Scorecard")
        name, actual = matched[0]
        if GRADE_VALUES[actual] < GRADE_VALUES[threshold]:
            fail(f"{name}: {actual} < threshold {threshold}")
        print(f"OK: {name} = {actual} (>= {threshold})")

    # Check 4: §8 present
    if not re.search(r"^##\s+8\.\s+Comparison to Prior Audit", text, re.MULTILINE):
        fail("'## 8. Comparison to Prior Audit' section not found")
    print("OK: §8 Comparison to Prior Audit present")

    # Check 5: P1 Residual Triage section present and non-empty
    m = re.search(r"^##\s+P1 Residual Triage\s*$(.*?)(^##\s+|\Z)", text, re.MULTILINE | re.DOTALL)
    if not m:
        fail("'## P1 Residual Triage' section not found")
    if not re.search(r"^\|", m.group(1), re.MULTILINE):
        fail("P1 Residual Triage section has no table rows")
    print("OK: P1 Residual Triage section present with table rows")

    # Check 6: deferred-items has six closure markers
    if not DEFERRED.is_file():
        fail(f"deferred-items not found at {DEFERRED}")
    deferred_text = DEFERRED.read_text(encoding="utf-8")
    closure_count = len(re.findall(r"Closed by Phase \d{3} \(\d{4}-\d{2}-\d{2}\)", deferred_text))
    if closure_count < 6:
        fail(f"deferred-items has {closure_count} closure markers; expected 6")
    print(f"OK: deferred-items has {closure_count} closure markers")

    print(f"\nPASS: closing audit complete; thresholds met; {closure_count} closure markers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

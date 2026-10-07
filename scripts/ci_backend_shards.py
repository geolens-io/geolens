#!/usr/bin/env python3
"""Print the backend test files that belong to one CI shard.

Usage: ci_backend_shards.py <shard-count> <shard-index>   (index is 1-based)
       ci_backend_shards.py --timings <junit.xml>...      (refresh timings)
       ci_backend_shards.py --selftest

Files are discovered the way pytest does (test_*.py and *_test.py under
backend/tests) and dealt out longest-first, so the split is deterministic and
needs no imports. A file's weight is its recorded duration in
ci_backend_timings.json; a file with no record (new since the last refresh)
weighs its test-function count times the recorded seconds per test. Paths are
printed relative to backend/, one per line.

``--timings`` rewrites ci_backend_timings.json from the JUnit reports the
Backend Tests shards upload as ``backend-junit-shard-*``. Refresh it when the
shards' run times drift apart; a stale file still splits correctly, only less
evenly.
"""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
TIMINGS = Path(__file__).resolve().parent / "ci_backend_timings.json"
_TEST_DEF = re.compile(r"^\s*(?:async\s+)?def\s+test_", re.MULTILINE)


def discover() -> list[Path]:
    tests = BACKEND / "tests"
    found = {*tests.rglob("test_*.py"), *tests.rglob("*_test.py")}
    return sorted(p.relative_to(BACKEND) for p in found)


def test_count(path: Path) -> int:
    text = (BACKEND / path).read_text(encoding="utf-8", errors="replace")
    return max(1, len(_TEST_DEF.findall(text)))


def load_timings() -> dict[str, float]:
    try:
        return json.loads(TIMINGS.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def weights(files: list[Path], timings: dict[str, float]) -> dict[Path, float]:
    counts = {p: test_count(p) for p in files}
    timed = [p for p in files if p.as_posix() in timings]
    timed_tests = sum(counts[p] for p in timed)
    per_test = (
        sum(timings[p.as_posix()] for p in timed) / timed_tests if timed_tests else 1.0
    )
    return {p: timings.get(p.as_posix(), counts[p] * per_test) for p in files}


def split(
    files: list[Path], count: int, timings: dict[str, float] | None = None
) -> list[list[Path]]:
    weight = weights(files, load_timings() if timings is None else timings)
    shards: list[list[Path]] = [[] for _ in range(count)]
    loads = [0.0] * count
    for path in sorted(files, key=lambda p: (-weight[p], p.as_posix())):
        lightest = loads.index(min(loads))
        shards[lightest].append(path)
        loads[lightest] += weight[path]
    return [sorted(shard) for shard in shards]


def _file_of(classname: str) -> str | None:
    """Map a JUnit classname (``tests.pkg.test_mod.TestCls``) to its file."""
    # A module-level skip or collection error has no classname.
    parts = classname.split(".") if classname else []
    for end in range(len(parts), 0, -1):
        candidate = Path(*parts[:end]).with_suffix(".py")
        if (BACKEND / candidate).is_file():
            return candidate.as_posix()
    return None


def collect_timings(reports: list[str]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for report in reports:
        # Our own CI's pytest output, read by a maintainer; expat resolves no
        # external entities and caps entity expansion.
        # nosemgrep: python.lang.security.use-defused-xml-parse.use-defused-xml-parse
        for case in ET.parse(report).iter("testcase"):
            path = _file_of(case.get("classname", ""))
            if path:
                totals[path] = totals.get(path, 0.0) + float(case.get("time") or 0)
    return {path: round(seconds, 1) for path, seconds in sorted(totals.items())}


def main(argv: list[str]) -> int:
    if argv[1:] == ["--selftest"]:
        _selftest()
        return 0
    if len(argv) >= 3 and argv[1] == "--timings":
        TIMINGS.write_text(
            json.dumps(collect_timings(argv[2:]), indent=0) + "\n", encoding="utf-8"
        )
        return 0
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    count, index = int(argv[1]), int(argv[2])
    if not 1 <= index <= count:
        print(f"shard index {index} is outside 1..{count}", file=sys.stderr)
        return 2
    for path in split(discover(), count)[index - 1]:
        print(path.as_posix())
    return 0


def _selftest() -> None:
    a, b, c = discover()[:3]
    timings = {a.as_posix(): 10.0, b.as_posix(): 6.0, c.as_posix(): 5.0}
    assert split([a, b, c], 2, timings) == [[a], sorted([b, c])]
    # An untimed file weighs its test count at the timed files' rate.
    rate = 21.0 / sum(test_count(p) for p in (a, b, c))
    assert weights([a, b, c, d := discover()[3]], timings)[d] == test_count(d) * rate


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

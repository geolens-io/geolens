#!/usr/bin/env python3
"""Print the backend test files that belong to one CI shard.

Usage: ci_backend_shards.py <shard-count> <shard-index>   (index is 1-based)

Files are discovered the way pytest does (test_*.py and *_test.py under
backend/tests) and dealt out longest-first by test-function count, so the split
is deterministic and roughly balanced without importing anything. Paths are
printed relative to backend/, one per line.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
_TEST_DEF = re.compile(r"^\s*(?:async\s+)?def\s+test_", re.MULTILINE)


def discover() -> list[Path]:
    tests = BACKEND / "tests"
    found = {*tests.rglob("test_*.py"), *tests.rglob("*_test.py")}
    return sorted(p.relative_to(BACKEND) for p in found)


def weight(path: Path) -> int:
    text = (BACKEND / path).read_text(encoding="utf-8", errors="replace")
    return max(1, len(_TEST_DEF.findall(text)))


def split(files: list[Path], count: int) -> list[list[Path]]:
    shards: list[list[Path]] = [[] for _ in range(count)]
    loads = [0] * count
    for path in sorted(files, key=lambda p: (-weight(p), p.as_posix())):
        lightest = loads.index(min(loads))
        shards[lightest].append(path)
        loads[lightest] += weight(path)
    return [sorted(shard) for shard in shards]


def main(argv: list[str]) -> int:
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


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

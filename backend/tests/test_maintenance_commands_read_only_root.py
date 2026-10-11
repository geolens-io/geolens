"""Operator commands that exec into the read-only api container must not use uv.

`uv run` creates a cache under the exec user's home, which is on the read-only
root filesystem, so the command dies before the script starts.
"""

from __future__ import annotations

import re

from tests.repo_paths import repo_root

REPO_ROOT = repo_root(__file__)

_DOCS = [
    "RUNBOOK.md",
    *(
        str(p.relative_to(REPO_ROOT))
        for p in (REPO_ROOT / "backend" / "scripts").glob("*")
        if p.suffix in {".py", ".md", ".sh"}
    ),
]
_BROKEN = re.compile(r"exec\s+(-\S+\s+)*api\s+uv\s+run\b")


def test_exec_api_commands_do_not_use_uv_run() -> None:
    offenders = [
        f"{rel}:{n}"
        for rel in _DOCS
        for n, line in enumerate(
            (REPO_ROOT / rel).read_text(encoding="utf-8").splitlines(), 1
        )
        if _BROKEN.search(line)
    ]
    assert not offenders, offenders

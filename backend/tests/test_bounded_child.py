"""A child's reply, however malformed, comes back as a failure category."""

from __future__ import annotations

import os
import sys

import pytest

from app.platform.bounded_child import ChildFailure, run_child


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param("json.dumps({'error': ['open']})", id="error-not-a-name"),
        pytest.param("'[' * 1_000_000 + ']' * 1_000_000", id="nested-past-the-stack"),
    ],
)
def test_a_malformed_reply_is_no_reply(reply) -> None:
    script = f"import json, sys\nprint({reply})\nsys.exit(1)\n"

    with pytest.raises(ChildFailure) as failure:
        run_child(
            [sys.executable, "-c", script],
            env={"PATH": os.environ["PATH"]},
            timeout=30,
            reported={"open": "open"},
        )

    assert failure.value.category == "no_reply"

"""unwrap() prints a coded refusal's message, not the detail object's repr."""

from __future__ import annotations

from http import HTTPStatus
from types import SimpleNamespace

import pytest
import typer


def _coded_response(status: int, code: str, message: str, **values):
    from geolens.models.problem_detail import ProblemDetail
    from geolens.models.problem_detail_detail_type_1 import ProblemDetailDetailType1

    detail = ProblemDetailDetailType1.from_dict(
        {"code": code, "message": message, **values}
    )
    return SimpleNamespace(
        status_code=HTTPStatus(status),
        parsed=ProblemDetail(title="Refused", status=status, detail=detail),
    )


def test_unwrap_prints_the_message_for_an_unexpected_status(capsys) -> None:
    from geolens_cli._sdk_helpers import unwrap

    resp = _coded_response(
        400, "disallowed_extension", "File extension '.exe' not allowed.", extension=".exe"
    )
    with pytest.raises(typer.Exit):
        unwrap(resp)
    err = capsys.readouterr().err
    assert "File extension '.exe' not allowed." in err
    assert "ProblemDetailDetailType1" not in err
    assert "additional_properties" not in err


def test_unwrap_prints_the_message_when_status_matches_expected(capsys) -> None:
    from geolens_cli._sdk_helpers import unwrap

    resp = _coded_response(422, "file_size_exceeded", "File size (2.0 MB) exceeds the maximum allowed (1 MB).")
    with pytest.raises(typer.Exit):
        unwrap(resp, expected=422)
    err = capsys.readouterr().err
    assert "File size (2.0 MB) exceeds the maximum allowed (1 MB)." in err
    assert "ProblemDetailDetailType1" not in err

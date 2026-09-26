"""A matched If-None-Match answers 304 to GET and HEAD and 412 to any other method."""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.platform.http.stored_bytes import evaluate_preconditions

_ETAG = '"v1"'


def _request(method: str, **headers: str) -> Request:
    raw = [
        (name.replace("_", "-").encode(), value.encode())
        for name, value in headers.items()
    ]
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/o",
            "headers": raw,
            "query_string": b"",
        }
    )


@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize("tag", [_ETAG, "*"])
def test_a_safe_method_holding_the_current_version_gets_304(
    method: str, tag: str
) -> None:
    """GET and HEAD whose If-None-Match holds the current version get a 304."""
    answer = evaluate_preconditions(
        _request(method, if_none_match=tag), _ETAG, changed_detail="changed"
    )

    assert answer is not None
    assert answer.status_code == 304
    assert answer.headers["etag"] == _ETAG


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE"])
@pytest.mark.parametrize("tag", [_ETAG, "*"])
def test_any_other_method_holding_the_current_version_gets_412(
    method: str, tag: str
) -> None:
    """RFC 9110 section 13.1.2 answers other methods with 412, never 304."""
    with pytest.raises(HTTPException) as refused:
        evaluate_preconditions(
            _request(method, if_none_match=tag), _ETAG, changed_detail="changed"
        )

    assert refused.value.status_code == 412
    assert refused.value.headers == {"ETag": _ETAG}


def test_no_precondition_lets_the_request_through() -> None:
    """Without either header the caller serves the request."""
    assert evaluate_preconditions(_request("GET"), _ETAG, changed_detail="x") is None

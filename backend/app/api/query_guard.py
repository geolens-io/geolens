"""Refuses query-string text PostgreSQL cannot store."""

from fastapi import Request
from fastapi.exceptions import RequestValidationError


async def refuse_nul_in_query(request: Request) -> None:
    """Refuse a NUL byte in any query parameter name or value.

    PostgreSQL rejects NUL in text, and the driver's error surfaces as a 500
    once a search term or row filter reaches a statement. Running as a
    dependency of the API routes, it answers through the validation handler,
    so the status and body match every other bad query value (400 on
    standards paths, else 422).
    """
    for name, value in request.query_params.multi_items():
        if "\x00" in name or "\x00" in value:
            raise RequestValidationError(
                errors=[
                    {
                        "type": "value_error",
                        "loc": ("query", name.replace("\x00", "")),
                        "msg": "must not contain a NUL byte",
                        "input": "",
                    }
                ]
            )

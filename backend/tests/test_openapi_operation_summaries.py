"""Every published operation carries a written summary.

Without an explicit ``summary=``, FastAPI titles an operation from its
function name ("Me", "Add Datasets Endpoint"). Those titles become the page
titles of the API reference and the docstrings of the generated SDKs.
"""

from __future__ import annotations

from app.api.main import _iter_api_routes, app


def test_no_operation_uses_the_function_name_as_its_summary():
    paths = app.openapi()["paths"]
    offenders = []
    for ctx in _iter_api_routes(app):
        derived = ctx.route.name.replace("_", " ").title()
        for method in sorted(ctx.route.methods):
            operation = paths.get(ctx.path_format, {}).get(method.lower())
            if operation and operation.get("summary") == derived:
                offenders.append(f"{method} {ctx.path_format}")

    assert not offenders, (
        "Operations whose summary is derived from the function name; "
        "add an explicit summary= action phrase:\n" + "\n".join(sorted(offenders))
    )

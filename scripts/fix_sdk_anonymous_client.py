#!/usr/bin/env python3
"""Widen the generated Python SDK's client type for anonymous-capable operations.

openapi-python-client types ``client`` from ``bool(security)`` alone, so a
security list containing ``{}`` (anonymous access allowed) still narrows to
``AuthenticatedClient`` only; this widens it to ``AuthenticatedClient | Client``
for exactly the operations backend/openapi.json marks anonymous-capable.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_OPENAPI_PATH = _REPO_ROOT / "backend/openapi.json"
_API_ROOT = _REPO_ROOT / "sdks/python/geolens/api"

_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}

_URL_RE = re.compile(r'"url":\s*"([^"]*)"')
_METHOD_RE = re.compile(r'"method":\s*"([a-z]+)"')

_NARROW_CLIENT = "    client: AuthenticatedClient,\n"
_WIDE_CLIENT = "    client: AuthenticatedClient | Client,\n"


def _anonymous_capable_operations() -> set[tuple[str, str]]:
    """Return the (path, method) pairs whose security allows anonymous access."""
    spec = json.loads(_OPENAPI_PATH.read_text(encoding="utf-8"))
    operations: set[tuple[str, str]] = set()
    for path, methods in spec.get("paths", {}).items():
        for method, operation in methods.items():
            if method not in _HTTP_METHODS:
                continue
            security = operation.get("security")
            if security and any(alternative == {} for alternative in security):
                operations.add((path, method))
    return operations


def _endpoint_key(source: str) -> tuple[str, str] | None:
    """Recover the (path, method) an endpoint module was generated for."""
    method_match = _METHOD_RE.search(source)
    url_match = _URL_RE.search(source)
    if not method_match or not url_match:
        return None
    return url_match.group(1), method_match.group(1)


def main() -> int:
    if not _OPENAPI_PATH.is_file():
        print(f"ERROR: {_OPENAPI_PATH} not found", file=sys.stderr)
        return 1
    if not _API_ROOT.is_dir():
        print(f"ERROR: generated SDK not found at {_API_ROOT}", file=sys.stderr)
        return 1

    anonymous = _anonymous_capable_operations()
    if not anonymous:
        print(
            "ERROR: no anonymous-capable operations found in backend/openapi.json; "
            "expected at least the dataset search and OGC/catalog collection routes.",
            file=sys.stderr,
        )
        return 1

    matched: set[tuple[str, str]] = set()
    patched: list[str] = []

    for path in sorted(_API_ROOT.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        key = _endpoint_key(source)
        if key is None or key not in anonymous:
            continue
        matched.add(key)
        count = source.count(_NARROW_CLIENT)
        if not count:
            continue
        path.write_text(source.replace(_NARROW_CLIENT, _WIDE_CLIENT), encoding="utf-8")
        patched.append(f"{path.relative_to(_REPO_ROOT)} ({count})")

    missing = anonymous - matched
    if missing:
        print(
            "ERROR: no generated endpoint module found for anonymous-capable "
            "operation(s); the generator may have dropped or renamed them:\n  "
            + "\n  ".join(
                f"{method.upper()} {path}" for path, method in sorted(missing)
            ),
            file=sys.stderr,
        )
        return 1

    if patched:
        print(f"Widened client typing for {len(patched)} anonymous-capable module(s):")
        for entry in patched:
            print(f"  {entry}")
    else:
        print("No anonymous-capable endpoints needed widening.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

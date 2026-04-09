#!/usr/bin/env python3
"""Auth + API-key lifecycle helper used by scripts/demo/run-seeder.sh.

Previously this logic lived inline in the shell wrapper as two ~40-line Python
heredocs. Extracting to a standalone module makes it lintable/testable and
eliminates the shell-escaping-collides-with-Python-literals hazard.

Subcommands:
  login            - POST /api/auth/login/ with form body; prints access_token
  rotate-key       - delete any existing ``demo-seed`` key and create a fresh
                     one; prints the plaintext key to stdout
  delete-key NAME  - delete the API key with the given name if it exists
                     (used by the SIGTERM/EXIT trap in run-seeder.sh)

All subcommands take ``--base-url`` (defaults to ``$GEOLENS_BASE_URL`` or
``http://api:8000``) and read credentials from environment variables so they
never appear in the process list.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, NoReturn

DEFAULT_BASE_URL = "http://api:8000"
DEMO_KEY_NAME = "demo-seed"


def _die(msg: str, code: int = 1) -> NoReturn:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def _request(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"{method} {url} returned {exc.code}: {exc.read()[:300].decode(errors='replace')}"
        ) from None


def cmd_login(base_url: str) -> int:
    username = os.environ.get("GEOLENS_ADMIN_USERNAME", "admin")
    password = os.environ.get("GEOLENS_ADMIN_PASSWORD", "admin")
    data = urllib.parse.urlencode(
        {"username": username, "password": password}
    ).encode()
    try:
        body = _request(
            f"{base_url}/api/auth/login/",
            method="POST",
            data=data,
        )
    except RuntimeError as exc:
        _die(str(exc))
    token = body.get("access_token") if isinstance(body, dict) else None
    if not token:
        _die("login succeeded but response had no access_token")
    print(token)
    return 0


def _list_keys(base_url: str, token: str) -> list[dict[str, Any]]:
    body = _request(
        f"{base_url}/api/auth/api-keys/",
        headers={"Authorization": f"Bearer {token}"},
    )
    # Endpoint has historically returned either {"items": [...]} or a bare list
    if isinstance(body, dict):
        return list(body.get("items") or [])
    if isinstance(body, list):
        return body
    return []


def _delete_key_id(base_url: str, token: str, key_id: str) -> None:
    try:
        _request(
            f"{base_url}/api/auth/api-keys/{key_id}",
            method="DELETE",
            headers={"Authorization": f"Bearer {token}"},
        )
    except RuntimeError as exc:
        # 404 is fine — already gone. Anything else should surface.
        if "404" not in str(exc):
            raise


def cmd_rotate_key(base_url: str) -> int:
    token = os.environ.get("SEED_TOKEN")
    if not token:
        _die("SEED_TOKEN env var is required for rotate-key")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Delete any existing ACTIVE demo-seed key so we start fresh. Plaintext
    # keys are only returned on create, so we always rotate rather than
    # trying to reuse. The `is_active` filter matters on DBs where prior
    # runs left soft-deleted rows behind (the API's DELETE endpoint sets
    # is_active=False rather than hard-deleting) — without it, find-first
    # could hit an already-inactive row and no-op, leaving a real active
    # key in place.
    for key in _list_keys(base_url, token):
        if key.get("name") == DEMO_KEY_NAME and key.get("is_active"):
            _delete_key_id(base_url, token, str(key["id"]))
            break

    data = json.dumps({"name": DEMO_KEY_NAME}).encode()
    try:
        body = _request(
            f"{base_url}/api/auth/api-keys/",
            method="POST",
            data=data,
            headers=headers,
        )
    except RuntimeError as exc:
        _die(str(exc))

    plaintext = body.get("key") if isinstance(body, dict) else None
    if not plaintext:
        _die("create-key succeeded but response had no plaintext key field")
    print(plaintext)
    return 0


def cmd_delete_key(base_url: str, name: str) -> int:
    """Best-effort cleanup used by run-seeder.sh SIGTERM/EXIT trap.

    Filters by ``is_active`` so the trap targets the row the current run
    created (and is actively using), not a stale soft-deleted row from
    an earlier run. Without the filter, the find-first loop would hit an
    inactive row on DBs with historical leakage and no-op, leaving the
    current run's key active on disk.
    """
    token = os.environ.get("SEED_TOKEN")
    if not token:
        # No token → nothing to clean up. Exit silently.
        return 0
    try:
        for key in _list_keys(base_url, token):
            if key.get("name") == name and key.get("is_active"):
                _delete_key_id(base_url, token, str(key["id"]))
                break
    except Exception as exc:
        print(f"WARN: delete-key cleanup failed: {exc}", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("GEOLENS_BASE_URL", DEFAULT_BASE_URL),
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login", help="Login and print access_token")
    sub.add_parser("rotate-key", help="Rotate demo-seed API key and print plaintext")
    sub_del = sub.add_parser("delete-key", help="Best-effort delete API key by name")
    sub_del.add_argument("name", nargs="?", default=DEMO_KEY_NAME)

    args = parser.parse_args()
    if args.cmd == "login":
        return cmd_login(args.base_url)
    if args.cmd == "rotate-key":
        return cmd_rotate_key(args.base_url)
    if args.cmd == "delete-key":
        return cmd_delete_key(args.base_url, args.name)
    return 1


if __name__ == "__main__":
    sys.exit(main())

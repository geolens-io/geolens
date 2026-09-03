# SPDX-License-Identifier: Apache-2.0
"""fix(#1778 review round 17): structural gate -- a store_refresh_token()
call that shares a function with a store_bearer_token()/store_api_key()
call must derive its `no_keyring=` from THAT call's actual return value
(the backend the credential really landed in), not from the pre-store
`no_keyring` intent the function started with.

store_bearer_token()/store_api_key() can silently fall back from the
keyring to credentials.toml on a KeyringError (a transient or
account-specific failure) even when the caller asked for the keyring.
Using the original intent instead of the real outcome for the sibling
refresh-token write splits the two tokens across backends -- review
round 15 found this in replace_credentials(), and round 17 found the
IDENTICAL bug in try_refresh()'s own rotation path, because nothing
enforced the pattern structurally between them. This walks every
function in cli/geolens_cli and fails if a third copy could land
unnoticed.

Uses ``ast`` rather than a text grep so the check is exact: a
`no_keyring=backend != "keyring"`-shaped comparison referencing the
backend-store call's own assigned variable passes; a bare name
(whatever it's called) does not.

fix(#1778 round 31): a second, independent structural gate below --
every PRODUCTION store_refresh_token() call must also pass
`bearer_token=`, pairing the refresh token to the bearer it can
rotate (see auth.py's own docstrings on store_refresh_token()/
try_refresh() for the finding this closes: an unpaired refresh token
proves nothing about which principal it would rotate). `bearer_token`
is optional on the function itself specifically so TESTS can keep
constructing legacy/unpaired refresh tokens without this gate firing
on them -- it only walks geolens_cli/, never tests/.
"""
from __future__ import annotations

import ast
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent.parent / "geolens_cli"

_BACKEND_STORE_FUNCS = {"store_bearer_token", "store_api_key"}


def _call_name(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id
    return None


def _backend_var_names(fn: ast.AST) -> set[str]:
    """Every name a store_bearer_token()/store_api_key() call's return
    value is assigned to, anywhere in `fn`."""
    names: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and _call_name(node.value) in _BACKEND_STORE_FUNCS:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
    return names


def _is_backend_derived(value: ast.expr, backend_vars: set[str]) -> bool:
    """True if `value` is a comparison referencing one of `backend_vars`
    -- e.g. `backend != "keyring"`. A bare name (even the right-sounding
    one) is NOT derived: it carries the pre-store intent, not the
    store's actual outcome."""
    if not isinstance(value, ast.Compare):
        return False
    operands = [value.left, *value.comparators]
    return any(isinstance(o, ast.Name) and o.id in backend_vars for o in operands)


def test_refresh_token_write_derives_backend_from_the_actual_store_outcome() -> None:
    offenders: list[str] = []
    functions_with_backend_var = 0
    refresh_calls_checked = 0

    for path in sorted(_PACKAGE_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            backend_vars = _backend_var_names(fn)
            if not backend_vars:
                continue  # this function never stores a bearer/api_key credential
            functions_with_backend_var += 1
            for node in ast.walk(fn):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "store_refresh_token"
                ):
                    refresh_calls_checked += 1
                    no_keyring_kw = next(
                        (kw for kw in node.keywords if kw.arg == "no_keyring"), None
                    )
                    if no_keyring_kw is None or not _is_backend_derived(
                        no_keyring_kw.value, backend_vars
                    ):
                        offenders.append(f"{path.name}:{node.lineno}")

    assert offenders == [], (
        "A store_refresh_token() call shares a function with a "
        "store_bearer_token()/store_api_key() call, but its no_keyring= "
        "does not derive from that store call's actual return value "
        f"at: {offenders}. store_bearer_token/store_api_key can "
        "silently fall back from keyring to the file on a "
        "KeyringError -- using the pre-store no_keyring intent instead "
        "of the real outcome splits the access and refresh tokens "
        "across backends (round 15, round 17). Use "
        "`no_keyring=(<backend var> != \"keyring\")`."
    )
    # Positive controls: if either drops to 0, the AST walk (or every
    # known call site) broke silently and the assertion above would
    # pass vacuously.
    assert functions_with_backend_var >= 2
    assert refresh_calls_checked >= 2


def test_store_refresh_token_calls_pass_bearer_token_for_pairing() -> None:
    offenders: list[str] = []
    calls_checked = 0

    for path in sorted(_PACKAGE_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "store_refresh_token"
            ):
                continue
            # The definition itself (in auth.py) is a FunctionDef, not
            # a Call to itself -- nothing to skip here, ast.walk only
            # ever finds real call sites.
            calls_checked += 1
            bearer_kw = next(
                (kw for kw in node.keywords if kw.arg == "bearer_token"), None
            )
            if bearer_kw is None:
                offenders.append(f"{path.name}:{node.lineno}")

    assert offenders == [], (
        "A store_refresh_token() call in production code (cli/geolens_cli/) "
        f"does not pass bearer_token= at: {offenders}. Every refresh token "
        "this package stores must be paired with the bearer it can rotate "
        "(round 31) -- an unpaired refresh token left the door open for "
        "try_refresh() to rotate a DIFFERENT stored session than the one "
        "that just got a 401. Pass bearer_token=<the bearer this refresh "
        "token belongs to>."
    )
    # Positive control: if this drops to 0, the AST walk broke silently
    # and the assertion above would pass vacuously.
    assert calls_checked >= 2

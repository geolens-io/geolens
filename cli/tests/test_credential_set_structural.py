# SPDX-License-Identifier: Apache-2.0
"""fix(#1778 round 32): structural gate -- delete_credentials()
(logout), _snapshot_credentials(), _restore_credentials(), and
_delete_stale_credentials() must each iterate _CREDENTIAL_SET (the
single definition of the four-member credential set: bearer, api_key,
refresh, refresh_fingerprint) rather than hand-rolling their own list
of accounts.

Before round 32, _CredentialSnapshot/_restore_credentials/
delete_credentials() each independently listed the accounts by hand.
Round 31 added the refresh_fingerprint to delete_credentials() and
_delete_stale_credentials() but NOT to the snapshot/restore pair, so a
login rollback silently dropped it -- a restored bearer+refresh pair
came back without the fingerprint that proves they belong together,
and the next 401 discarded the restored (perfectly valid) refresh
token as unpaired.

A fifth member added to _CREDENTIAL_SET only propagates automatically
to every one of these functions if each of them actually reads from
it, rather than naming its own (necessarily driftable) subset -- same
shape as tests/test_refresh_token_backend_derivation.py's producer
gate.
"""
from __future__ import annotations

import ast
from pathlib import Path

_AUTH_PATH = Path(__file__).resolve().parent.parent / "geolens_cli" / "auth.py"

_REQUIRED_FUNCTIONS = {
    "delete_credentials",
    "_snapshot_credentials",
    "_restore_credentials",
    "_delete_stale_credentials",
}


def test_full_sweep_functions_iterate_the_shared_credential_set() -> None:
    tree = ast.parse(_AUTH_PATH.read_text(), filename=str(_AUTH_PATH))

    references_by_name: dict[str, bool] = {}
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if fn.name not in _REQUIRED_FUNCTIONS:
            continue
        references_by_name[fn.name] = any(
            isinstance(node, ast.Name) and node.id == "_CREDENTIAL_SET"
            for node in ast.walk(fn)
        )

    missing = _REQUIRED_FUNCTIONS - set(references_by_name)
    assert not missing, (
        f"expected function(s) not found in auth.py: {missing} -- the AST "
        "walk (or the function names themselves) changed; update this "
        "gate's _REQUIRED_FUNCTIONS."
    )

    offenders = sorted(name for name, ok in references_by_name.items() if not ok)
    assert offenders == [], (
        f"{offenders} must iterate _CREDENTIAL_SET (auth.py's single "
        "definition of the four-member credential set: bearer, api_key, "
        "refresh, refresh_fingerprint) rather than hand-rolling its own "
        "list of accounts -- otherwise a future fifth member can be added "
        "to the set and silently forgotten in one of these functions, "
        "exactly as the round-31 fingerprint was forgotten in the "
        "snapshot/restore pair (round 32)."
    )


def test_credential_set_has_exactly_four_members_with_the_expected_shape() -> None:
    """Positive control: if _CREDENTIAL_SET itself is ever collapsed to
    fewer entries (or its per-entry shape changes), the gate above
    would pass vacuously -- this pins the tuple's own shape directly."""
    from geolens_cli import auth as _auth

    assert len(_auth._CREDENTIAL_SET) == 4
    names = [entry[0] for entry in _auth._CREDENTIAL_SET]
    assert names == ["bearer", "api_key", "refresh", "refresh_fingerprint"]
    for name, account_fn, field in _auth._CREDENTIAL_SET:
        assert callable(account_fn), name
        assert isinstance(field, str) and field, name

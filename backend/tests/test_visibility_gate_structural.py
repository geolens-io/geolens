"""Structural guard for the admins-only-public gate (feat #1691).

The `restrict_public_visibility` instance setting caps non-admin content at
non-public visibility. Its enforcement contract is: EVERY mutation route whose
request body accepts a `visibility` value routes through the ONE shared gate,
`check_public_visibility_allowed` in `app/modules/catalog/authorization.py` —
never a per-handler copy of the check.

Same spirit as test_rule1_structural.py, deliberately smaller machinery:

- Walk the real (flattened) FastAPI route table.
- For each POST/PUT/PATCH route, recurse through the request-body model tree
  (nested models, lists, unions) looking for a field literally named
  ``visibility``. Response models never enter ``dependant.body_params``, so
  read-side ``visibility`` fields (DatasetResponse, MapResponse, tile meta)
  cannot false-positive here, and query params (the records router's
  ``audience_visibility`` counterfactual, the maps list filter) are reads by
  construction and also invisible to this walk.
- Assert the handler's own source CALLS the gate, or the handler appears in
  ``_DELEGATED_GATES`` naming the exact helper that carries the call for it
  (integrity-checked below, so delegation cannot go stale).

Known limits (accepted):

- Source-level detection: a call site inside dead code would still credit the
  handler. The behavioral 403 is covered by test_public_visibility_gate.py.
- The manifest-apply body carries no ``visibility`` field — its publication
  *intent* maps to one in ``publication_to_catalog_fields``. The walk cannot
  see that by field name, so the route is pinned explicitly
  (test_manifest_apply_routes_through_the_gate) rather than discovered.
- The ingest fan-out body also carries no ``visibility`` field; the cloned
  jobs inherit the parent job's user_metadata, so the handler gates that
  inherited value as defense-in-depth. Pinned explicitly for the same reason
  (test_fan_out_gates_inherited_visibility).
"""

from __future__ import annotations

import inspect
import re
import textwrap
import typing
from functools import lru_cache
from typing import Any

import pytest

_GATE_NAME = "check_public_visibility_allowed"
_MUTATION_METHODS = {"POST", "PUT", "PATCH"}

# Handlers whose gate call lives in a helper instead of the handler body.
# Value: (module path, function name) whose source must contain the call.
_DELEGATED_GATES: dict[str, tuple[str, str]] = {}

# Mutation routes whose body accepts `visibility` but which are deliberately
# NOT gated, each with a written justification. Kept empty on purpose: every
# discovered surface is currently gated. Asserted exact in both directions.
_ALLOWLIST: dict[str, str] = {}


def _unwrap(fn: Any) -> Any:
    seen: set[int] = set()
    while hasattr(fn, "__wrapped__") and id(fn) not in seen:
        seen.add(id(fn))
        fn = fn.__wrapped__
    return fn


def _source_of(fn: Any) -> str:
    try:
        return textwrap.dedent(inspect.getsource(fn))
    except (OSError, TypeError):
        return ""


def _calls_gate(source: str) -> bool:
    """True when the source contains a CALL of the gate (not a bare mention)."""
    return re.search(rf"\b{_GATE_NAME}\s*\(", source) is not None


def _model_tree_has_visibility(annotation: Any, seen: set[int]) -> bool:
    """Recurse an annotation's model tree for a field named ``visibility``."""
    if annotation is None or id(annotation) in seen:
        return False
    seen.add(id(annotation))

    from pydantic import BaseModel

    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        for name, field in annotation.model_fields.items():
            if name == "visibility":
                return True
            if _model_tree_has_visibility(field.annotation, seen):
                return True
        return False

    for arg in typing.get_args(annotation):
        if _model_tree_has_visibility(arg, seen):
            return True
    return False


class _FlaggedRoute(typing.NamedTuple):
    key: str
    path: str
    methods: tuple[str, ...]
    gated: bool


@lru_cache(maxsize=1)
def _flagged_routes() -> tuple[_FlaggedRoute, ...]:
    """Every unique mutation handler whose body tree carries `visibility`."""
    from fastapi.routing import APIRoute, iter_route_contexts

    from app.api.main import app

    flagged: dict[str, _FlaggedRoute] = {}
    for ctx in iter_route_contexts(app.routes):
        route = ctx.route
        if not isinstance(route, APIRoute):
            continue
        if not (_MUTATION_METHODS & set(route.methods or ())):
            continue
        has_visibility = any(
            _model_tree_has_visibility(param.field_info.annotation, set())
            for param in route.dependant.body_params
        )
        if not has_visibility:
            continue
        fn = _unwrap(route.endpoint)
        key = f"{fn.__module__}.{fn.__qualname__}"
        if key in flagged:
            continue  # dual-shape slash aliases register the endpoint twice
        gated = _calls_gate(_source_of(fn))
        if not gated and key in _DELEGATED_GATES:
            mod_path, helper_name = _DELEGATED_GATES[key]
            module = __import__(mod_path, fromlist=[helper_name])
            gated = _calls_gate(_source_of(getattr(module, helper_name)))
        flagged[key] = _FlaggedRoute(
            key=key,
            path=ctx.path or route.path,
            methods=tuple(sorted(route.methods or ())),
            gated=gated,
        )
    return tuple(flagged.values())


@pytest.mark.architecture
def test_detection_is_alive() -> None:
    """The body-tree walk must still find the known visibility surfaces.

    If pydantic renames ``model_fields`` or the schemas move, every assertion
    below could pass vacuously (nothing flagged, nothing required). Pin a
    floor and two anchors that AGENTS.md-level refactors are least likely to
    touch silently.
    """
    flagged = _flagged_routes()
    assert len(flagged) >= 6, (
        f"only {len(flagged)} mutation routes with a body-level `visibility` "
        "field were discovered (expected >= 6: dataset PATCH, map PUT, ingest "
        "commit/register/bulk-register/VRT-create, STAC import). The "
        "detection walk is broken — fix it before trusting this module."
    )
    keys = {r.key for r in flagged}
    for anchor_suffix in ("update_dataset_metadata", "commit_import"):
        assert any(k.endswith(anchor_suffix) for k in keys), (
            f"anchor handler *.{anchor_suffix} no longer flagged — either its "
            "schema lost the visibility field or detection broke."
        )


@pytest.mark.architecture
def test_every_visibility_mutation_routes_through_the_gate() -> None:
    """feat(#1691): each discovered surface calls the ONE shared gate."""
    offenders = [
        f"  {r.key} [{','.join(r.methods)} {r.path}]"
        for r in _flagged_routes()
        if not r.gated and r.key not in _ALLOWLIST
    ]
    if offenders:
        pytest.fail(
            "Mutation route(s) accept a `visibility` value without calling "
            f"{_GATE_NAME} (app/modules/catalog/authorization.py). Gate them "
            "through that ONE shared check — do not hand-roll an admin "
            "check — or add a justified _ALLOWLIST entry:\n" + "\n".join(offenders)
        )


@pytest.mark.architecture
def test_allowlist_and_delegations_are_current() -> None:
    """Stale exemption entries are silent licences to regress — both lists
    must reference handlers that still exist and still need the entry."""
    flagged = {r.key: r for r in _flagged_routes()}
    stale = [key for key in _ALLOWLIST if key not in flagged]
    stale += [
        key
        for key in _DELEGATED_GATES
        if key not in flagged or _calls_gate(_source_of_key(key))
    ]
    assert not stale, (
        "_ALLOWLIST/_DELEGATED_GATES entries no longer match a flagged "
        f"handler (or the handler now gates directly): {stale}. Delete them."
    )


def _source_of_key(key: str) -> str:
    mod_path, _, qualname = key.rpartition(".")
    module = __import__(mod_path, fromlist=[qualname])
    return _source_of(getattr(module, qualname, None))


@pytest.mark.architecture
def test_manifest_apply_routes_through_the_gate() -> None:
    """The manifest body has no `visibility` field — its publication intent
    maps to one. Pin that the apply path's classification step calls the
    gate, and that the route itself still exists (so this pin cannot outlive
    the surface it covers)."""
    from fastapi.routing import APIRoute, iter_route_contexts

    from app.api.main import app
    from app.processing.ingest import manifest_service

    manifest_routes = [
        ctx.path
        for ctx in iter_route_contexts(app.routes)
        if isinstance(ctx.route, APIRoute)
        and "POST" in (ctx.route.methods or ())
        and (ctx.path or ctx.route.path).endswith("/ingest/manifest/apply")
    ]
    assert manifest_routes, "manifest apply route disappeared — update this pin"
    assert _calls_gate(_source_of(manifest_service._classify_dataset)), (
        "manifest_service._classify_dataset no longer calls "
        f"{_GATE_NAME}; a manifest with intent 'published' would create "
        "public datasets past the restrict_public_visibility setting."
    )


@pytest.mark.architecture
def test_fan_out_gates_inherited_visibility() -> None:
    """FanOutCommitRequest has no visibility field, but the cloned jobs
    inherit the parent job's user_metadata — the handler must gate that
    inherited value (defense-in-depth, feat #1691)."""
    from app.processing.ingest import router as ingest_router

    assert _calls_gate(_source_of(ingest_router.commit_fan_out)), (
        f"commit_fan_out no longer calls {_GATE_NAME} on the parent job's "
        "inherited user_metadata visibility."
    )


@pytest.mark.architecture
def test_gate_integrity() -> None:
    """The shared gate must still read the setting, resolve roles, and fail
    closed with a 403 — a hollowed-out gate satisfies every check above."""
    from app.modules.catalog import authorization

    source = _source_of(authorization.check_public_visibility_allowed)
    for needle, why in (
        ("RESTRICT_PUBLIC_VISIBILITY", "reads the instance setting"),
        ("get_user_roles", "resolves the caller's roles"),
        ('"admin"', "checks admin membership"),
        ("HTTP_403_FORBIDDEN", "fails closed with a 403"),
    ):
        assert needle in source, (
            f"{_GATE_NAME} no longer {why} ({needle!r} missing) — the "
            "structural credit every handler gets from calling it is void."
        )

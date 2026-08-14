"""Audit ``details`` payloads must be JSON-safe before they reach JSONB (#1484).

``audit_logs.details`` is a JSONB column and the engine configures no
``json_serializer``, so SQLAlchemy serializes it with stdlib ``json.dumps``.
A python-mode ``model_dump()`` leaves ``date``/``datetime``/``UUID``/``Decimal``
objects intact, and stdlib json cannot encode any of them.

Why that is worse than a broken audit row: the ``TypeError`` surfaces at FLUSH
time, not at ``audit_emit()`` time. ``audit_emit`` isolates sink failures
(AUDIT-03), but the sink only calls ``session.add()`` — the INSERT is emitted
later, inside the caller's commit, outside that try/except. So the failure
rolls back the whole request transaction and takes the user's already-staged
mutation with it. On the live demo a
``PATCH /datasets/{id} {"data_vintage_start": "1950-01-01"}`` 500'd and silently
discarded the license/keyword edits sent in the same body.

Two regression tests pin the observable behaviour, and one structural test
pins the class so a new call site cannot reintroduce it.
"""

import ast
import pathlib
import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.audit.models import AuditLog
from tests.factories import create_collection_via_api, create_dataset, get_user_id

pytestmark = pytest.mark.anyio


async def _latest_details(session, action: str, resource_id: uuid.UUID) -> dict:
    """Return the newest audit row's details for one action/resource."""
    # The handler committed on its own connection; drop any snapshot this
    # session is holding so the SELECT below sees that commit.
    await session.rollback()
    row = (
        await session.execute(
            select(AuditLog.details)
            .where(AuditLog.action == action, AuditLog.resource_id == resource_id)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(1)
        )
    ).scalar_one()
    return row


async def test_patch_dataset_vintage_dates_succeed_and_audit_iso_strings(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """The live 500 from #1484, end to end.

    Sends the vintage dates together with a plain-string field so the test also
    proves the co-staged record UPDATE survives: before the fix the audit INSERT
    rolled back the whole transaction, and ``license`` was lost with it.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await create_dataset(
        session, created_by=admin_id, name=f"Vintage {uuid.uuid4().hex[:6]}"
    )

    resp = await client.patch(
        f"/datasets/{ds.id}",
        json={
            "data_vintage_start": "1950-01-01",
            "data_vintage_end": "1999-12-31",
            "license": "https://creativecommons.org/licenses/by/4.0/",
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text

    # The mutation itself is durable, including the field that used to be
    # collateral damage.
    got = (await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)).json()
    assert got["data_vintage_start"] == "1950-01-01"
    assert got["data_vintage_end"] == "1999-12-31"
    assert got["license"] == "https://creativecommons.org/licenses/by/4.0/"

    # And the audit row records the edit as ISO strings rather than failing to
    # serialize. Asserting the stored value (not just a 200) is the point: an
    # engine-level ``default=str`` would also return 200 here while silently
    # stringifying every other type.
    details = await _latest_details(session, "metadata.edit", ds.id)
    assert details["data_vintage_start"] == "1950-01-01"
    assert details["data_vintage_end"] == "1999-12-31"
    assert details["license"] == "https://creativecommons.org/licenses/by/4.0/"


async def test_patch_dataset_vintage_null_clear_still_audits(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """``exclude_unset`` semantics survive the mode switch.

    ``mode="json"`` must not turn an explicit null-clear into an absent key —
    that distinction is load-bearing for the history feed (#458 E-04).
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await create_dataset(
        session,
        created_by=admin_id,
        name=f"VintageClear {uuid.uuid4().hex[:6]}",
        temporal_start=date(1950, 1, 1),
        temporal_end=date(1999, 12, 31),
    )

    resp = await client.patch(
        f"/datasets/{ds.id}",
        json={"data_vintage_start": None},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text

    details = await _latest_details(session, "metadata.edit", ds.id)
    assert "data_vintage_start" in details
    assert details["data_vintage_start"] is None
    # Unset fields stay out of the payload.
    assert "data_vintage_end" not in details


async def test_collection_update_audit_details_round_trip(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """The sibling ``model_dump`` site keeps recording what changed.

    ``CollectionUpdate`` carries only ``str | None`` fields today, so this site
    could not 500 — the ``mode="json"`` there is preventive. What this test pins
    is that making it preventive did not change the payload it records.
    """
    session = test_db_session
    coll = await create_collection_via_api(client, admin_auth_header)
    coll_id = uuid.UUID(coll["id"])

    resp = await client.patch(
        f"/catalog/collections/{coll_id}",
        json={"name": "Renamed collection", "description": "Edited description"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text

    details = await _latest_details(session, "collection.update", coll_id)
    assert details == {
        "name": "Renamed collection",
        "description": "Edited description",
    }


# ---------------------------------------------------------------------------
# Structural guard
# ---------------------------------------------------------------------------

_APP_ROOT = pathlib.Path(__file__).resolve().parents[1] / "app"


def _is_model_dump(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "model_dump"
    )


def _dumps_json(call: ast.Call) -> bool:
    """True only when ``mode`` is provably the literal ``"json"``.

    ``mode`` is ``model_dump``'s first positional parameter, so both spellings
    count. A non-literal (``mode=some_var``) is NOT provable and is reported —
    this guard fails loudly rather than assuming.
    """
    if call.args and isinstance(call.args[0], ast.Constant):
        return call.args[0].value == "json"
    for kw in call.keywords:
        if kw.arg == "mode":
            return isinstance(kw.value, ast.Constant) and kw.value.value == "json"
    return False


def _model_dumps_in(node: ast.AST) -> list[ast.Call]:
    return [child for child in ast.walk(node) if _is_model_dump(child)]


def _python_mode_details_dumps(tree: ast.AST) -> list[int]:
    """Return the line of every ``details=`` payload built by a python-mode dump.

    Scope is every ``details=`` keyword argument, not just the ones passed
    straight to ``AuditEvent``/``log_action``: forwarding helpers
    (``_propagate_record_write``, ``record_map_history_event``) take the same
    kwarg and hand it to the same columns, and a rule that only matched the
    direct calls would miss them.

    Resolution is lexical, within one enclosing function: a dump written inline
    (``details=body.model_dump(...)``), spread into a literal
    (``details={**body.model_dump(...), "x": 1}``), or assigned to the name that
    is then passed (``payload = body.model_dump(...)`` ... ``details=payload``).
    """
    # A function plus the module body: enough to resolve `x = ...dump()`
    # followed by `details=x`. Nested functions get walked by their parent too,
    # which only ever widens what this sees.
    scopes: list[ast.AST] = [tree] + [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    lines: set[int] = set()
    for scope in scopes:
        assigned: dict[str, list[ast.Call]] = {}
        for node in ast.walk(scope):
            if not isinstance(node, ast.Assign):
                continue
            dumps = _model_dumps_in(node.value)
            if not dumps:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned.setdefault(target.id, []).extend(dumps)

        for node in ast.walk(scope):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg != "details":
                    continue
                dumps = list(_model_dumps_in(kw.value))
                if isinstance(kw.value, ast.Name):
                    dumps.extend(assigned.get(kw.value.id, []))
                lines.update(d.lineno for d in dumps if not _dumps_json(d))
    return sorted(lines)


def test_audit_details_payloads_never_use_a_python_mode_model_dump():
    """No ``details=`` payload under app/ is built by a python-mode model dump.

    Known limit, stated rather than implied: a dump that reaches a ``details=``
    site with no lexical trace in the same function — built in another module,
    pulled from a container, arriving as a parameter — is not recognizable to
    any AST rule and this guard does not claim it. Every payload that reaches
    audit today is either one of the shapes above or a hand-built literal of
    strings, ints, and bools.
    """
    violations = [
        f"{path.relative_to(_APP_ROOT.parent)}:{line}"
        for path in sorted(_APP_ROOT.rglob("*.py"))
        for line in _python_mode_details_dumps(ast.parse(path.read_text()))
    ]

    assert not violations, (
        'audit `details=` payloads must be built with model_dump(mode="json") '
        "— a python-mode dump puts date/datetime/UUID/Decimal objects into a "
        "JSONB column that serializes with stdlib json.dumps, which raises at "
        "flush time and rolls back the caller's mutation (#1484). "
        f"Offending sites: {violations}"
    )


def test_structural_guard_detects_a_python_mode_dump():
    """The guard above asserts an absence; this proves it can still see one.

    Without this, gutting ``_python_mode_details_dumps`` would leave a
    permanently green test. Exercises the real resolver, not a copy of it.
    """
    sample = ast.parse(
        "def handler(body, other, chosen):\n"
        "    payload = body.model_dump(exclude_unset=True)\n"
        "    emit(details=payload)\n"  # line 3: via variable
        "    emit(details=other.model_dump())\n"  # line 4: inline
        "    emit(details={**other.model_dump(), 'k': 1})\n"  # line 5: spread
        "    emit(details=other.model_dump(mode=chosen))\n"  # line 6: unprovable
        "    emit(details=other.model_dump(mode='json'))\n"  # clean
        "    emit(details=other.model_dump('json'))\n"  # clean (positional)
        "    emit(details={'k': 1})\n"  # clean (no dump)
    )
    # Line 2 is where the via-variable dump is written, so that is the line
    # reported for the line-3 call site.
    assert _python_mode_details_dumps(sample) == [2, 4, 5, 6]

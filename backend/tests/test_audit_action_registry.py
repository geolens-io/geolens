"""#1230: the backend half of "one source of truth for action names".

Walks the AST of every file under ``backend/app`` and collects the literal
``action=`` value passed to every ``AuditEvent(...)`` call site. Any literal
that is not a member of ``app.modules.audit.actions.AUDIT_ACTIONS`` fails the
test — so an emit site introduced with a typo'd or unregistered action string
fails CI immediately instead of silently drifting from the frontend's display
registry (``frontend/src/components/admin/AuditLogViewer.tsx``), which is
exactly the gap #1230's 2026-08-05 audit sweep found.

Does not require a database: pure source-tree static analysis, same style as
test_layering.py's other AST-walking guards.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.modules.audit.actions import AUDIT_ACTIONS

_BACKEND_APP = Path(__file__).resolve().parents[1] / "app"

# backend/tests/.. -> backend/, backend/.. -> repo root.
_FRONTEND_AUDIT_LOG_VIEWER = (
    Path(__file__).resolve().parents[2]
    / "frontend/src/components/admin/AuditLogViewer.tsx"
)


def _find_audit_event_actions() -> dict[str, list[str]]:
    """Return {action_literal: [file paths that emit it]} across backend/app.

    Only literal string ``action=`` keywords on a call named ``AuditEvent``
    are collected (matching either ``AuditEvent(...)`` or ``foo.AuditEvent(...)``
    call shapes). A non-literal (e.g. a variable) is reported separately so a
    future dynamic action string does not silently pass unchecked — today
    there are none (verified below).

    ``AuditEvent`` is a dataclass, so ``AuditEvent(user_id, "x", "dataset")``
    (positional) is valid Python and would otherwise find no ``action=``
    keyword and silently vanish from this scan — the registry/frontend-parity
    checks would then pass while production emitted an action neither test
    ever saw. Every real call site in the codebase already uses the keyword
    form (this scan is itself the proof — see test_every_emitted_action_is_
    registered's zero false negatives against grep), so a call with no
    ``action=`` keyword is flagged the same way as a non-literal one rather
    than silently skipped.
    """
    sites: dict[str, list[str]] = {}
    dynamic: list[str] = []
    for path in sorted(_BACKEND_APP.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        rel = f"backend/app/{path.relative_to(_BACKEND_APP).as_posix()}"
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            fname = (
                func.id
                if isinstance(func, ast.Name)
                else (func.attr if isinstance(func, ast.Attribute) else None)
            )
            if fname != "AuditEvent":
                continue
            action_kw = next((kw for kw in node.keywords if kw.arg == "action"), None)
            if action_kw is None:
                dynamic.append(
                    f"{rel}:{node.lineno} (no action= keyword — positional or "
                    "missing; use the keyword form)"
                )
            elif isinstance(action_kw.value, ast.Constant) and isinstance(
                action_kw.value.value, str
            ):
                sites.setdefault(action_kw.value.value, []).append(rel)
            else:
                dynamic.append(f"{rel}:{node.lineno}")
    if dynamic:
        pytest.fail(
            "AuditEvent(action=...) called with a non-literal value — the "
            "static registry check cannot verify it. Use a literal string "
            "(add it to AUDIT_ACTIONS) or update this test to handle the "
            "dynamic case explicitly:\n" + "\n".join(dynamic)
        )
    return sites


@pytest.mark.architecture
def test_every_emitted_action_is_registered() -> None:
    """Every action= literal passed to AuditEvent(...) is in AUDIT_ACTIONS."""
    emitted = _find_audit_event_actions()
    unregistered = {
        action: files
        for action, files in emitted.items()
        if action not in AUDIT_ACTIONS
    }
    if unregistered:
        lines = [
            f"  {action!r} (emitted from {', '.join(files)})"
            for action, files in sorted(unregistered.items())
        ]
        pytest.fail(
            "These AuditEvent action strings are not in "
            "app.modules.audit.actions.AUDIT_ACTIONS. Add each one there in "
            "the same commit that starts emitting it:\n" + "\n".join(lines)
        )


@pytest.mark.architecture
def test_registry_has_no_stale_actions() -> None:
    """Every entry in AUDIT_ACTIONS is actually emitted somewhere.

    Counterpart to test_every_emitted_action_is_registered: keeps the
    registry from accumulating names nothing writes any more (the same kind
    of drift #1230 found on the frontend side, just in the other direction).
    """
    emitted = set(_find_audit_event_actions())
    stale = AUDIT_ACTIONS - emitted
    if stale:
        pytest.fail(
            "These AUDIT_ACTIONS entries are not emitted by any "
            "AuditEvent(action=...) call site in backend/app — remove them "
            "or fix the emit site:\n" + "\n".join(sorted(stale))
        )


def _parse_frontend_audit_actions() -> set[str]:
    """Extract the string literals inside AuditLogViewer.tsx's
    ``CURRENT_AUDIT_ACTIONS`` array.

    Regex, not a TS parser: the array is a flat list of single-quoted string
    literals (`'action.name',`), and that shape is enforced by this same
    test failing loudly the moment it stops holding.
    """
    text = _FRONTEND_AUDIT_LOG_VIEWER.read_text(encoding="utf-8")
    match = re.search(
        r"const CURRENT_AUDIT_ACTIONS = \[(.*?)\]\s*as const;", text, re.DOTALL
    )
    if match is None:
        pytest.fail(
            "Could not locate `const CURRENT_AUDIT_ACTIONS = [...] as const;` "
            f"in {_FRONTEND_AUDIT_LOG_VIEWER} — the array shape changed and "
            "this test's regex needs updating alongside it."
        )
    body = match.group(1)
    literals = re.findall(r"'([^']+)'", body)
    if not literals:
        pytest.fail(
            f"Parsed zero action strings out of CURRENT_AUDIT_ACTIONS in "
            f"{_FRONTEND_AUDIT_LOG_VIEWER} — the extraction regex is broken."
        )
    return set(literals)


@pytest.mark.architecture
def test_frontend_action_list_matches_backend_registry() -> None:
    """fix(#1230 codex r2 P2): a matching AUDIT_ACTIONS + emit-site pair added
    together passes the two tests above without ever looking at
    AuditLogViewer.tsx's CURRENT_AUDIT_ACTIONS — exactly the drift this
    whole change exists to close. Parse the frontend array directly and
    assert set equality against the backend registry, in both directions.
    """
    frontend_actions = _parse_frontend_audit_actions()
    missing_from_frontend = AUDIT_ACTIONS - frontend_actions
    extra_in_frontend = frontend_actions - AUDIT_ACTIONS
    if missing_from_frontend or extra_in_frontend:
        lines = []
        if missing_from_frontend:
            lines.append(
                "  Backend emits these but CURRENT_AUDIT_ACTIONS is missing "
                f"them: {sorted(missing_from_frontend)}"
            )
        if extra_in_frontend:
            lines.append(
                "  CURRENT_AUDIT_ACTIONS lists these but nothing in "
                f"backend/app emits them: {sorted(extra_in_frontend)}"
            )
        pytest.fail(
            "frontend/src/components/admin/AuditLogViewer.tsx's "
            "CURRENT_AUDIT_ACTIONS has drifted from "
            "app.modules.audit.actions.AUDIT_ACTIONS:\n" + "\n".join(lines)
        )

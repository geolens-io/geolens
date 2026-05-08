"""Static-analysis test: frontend Capability literal union must mirror
backend ALL_CAPABILITIES list byte-for-byte.

v13.14 post-impl P2: closes the bug class that allowed Phase 281's
`view_audit` typo (an unregistered capability key) to silently return
false from `usePermissions().can(...)`.

Frontend now declares `Capability` as a literal union from a single source
(`frontend/src/lib/capabilities.ts`). This test guards the contract: if a
capability is added, removed, or renamed in either place, this test fails
and the offending change must update both sides in lockstep.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.permissions import ALL_CAPABILITIES

REPO_ROOT = Path(__file__).resolve().parents[2]
CAPABILITIES_TS = REPO_ROOT / "frontend" / "src" / "lib" / "capabilities.ts"


def _parse_frontend_capabilities() -> list[str]:
    """Parse the `ALL_CAPABILITIES` `as const` array from the TypeScript
    source. Reads the literal strings between `[` and `]` after the
    `export const ALL_CAPABILITIES = [` declaration.

    Static analysis only — does not import or execute TypeScript.
    """
    source = CAPABILITIES_TS.read_text(encoding="utf-8")
    match = re.search(
        r"export\s+const\s+ALL_CAPABILITIES\s*=\s*\[(.*?)\]\s*as\s+const",
        source,
        re.DOTALL,
    )
    assert match, (
        f"Could not find `export const ALL_CAPABILITIES = [...] as const` in "
        f"{CAPABILITIES_TS}. The drift test cannot run without it."
    )
    body = match.group(1)
    return re.findall(r"'([a-z_]+)'", body)


def test_frontend_capabilities_mirror_backend_registry():
    """The frontend Capability literal union must list the same capabilities
    in the same order as the backend ALL_CAPABILITIES list.

    Order alignment is enforced because TypeScript's literal-union type is
    derived positionally — reordering still type-checks but causes silent
    semantic drift in any consumer that depends on iteration order.
    """
    frontend = _parse_frontend_capabilities()
    backend = list(ALL_CAPABILITIES)

    assert frontend == backend, (
        f"Capability registry drift between frontend and backend.\n"
        f"  Backend (app/core/permissions.py:ALL_CAPABILITIES): {backend}\n"
        f"  Frontend (lib/capabilities.ts:ALL_CAPABILITIES):    {frontend}\n"
        f"\n"
        f"Both lists must contain the same items in the same order. If you "
        f"added/removed/renamed a capability, update both sides in lockstep."
    )

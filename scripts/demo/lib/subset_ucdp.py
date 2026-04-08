#!/usr/bin/env python3
"""Subset UCDP GED CSV by year range. Used by Plan 04 (local stage) and Plan 05 (Dockerfile build)."""

import csv
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 5:
        print(
            "Usage: subset_ucdp.py <input_csv> <output_csv> <year_min> <year_max>",
            file=sys.stderr,
        )
        sys.exit(1)

    inp, out, ymin, ymax = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    kept = 0

    with open(inp, newline="") as inf, open(out, "w", newline="") as outf:
        reader = csv.DictReader(inf)
        writer = csv.DictWriter(outf, fieldnames=reader.fieldnames)
        writer.writeheader()
        for row in reader:
            try:
                y = int(row.get("year", 0))
                if ymin <= y <= ymax:
                    writer.writerow(row)
                    kept += 1
            except (ValueError, TypeError):
                continue

    print(f"Subset complete: {kept} rows in [{ymin}, {ymax}]")


if __name__ == "__main__":
    main()

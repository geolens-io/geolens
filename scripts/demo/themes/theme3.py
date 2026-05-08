"""Theme 3 — empty stub.

This module exists ONLY because scripts/demo/seed-thematic-demo.py line 67
imports it: `from themes import ThemeDataset, theme1, theme2, theme3`.
That orchestrator is FROZEN per CONTEXT.md, so the import target must
continue to resolve.

The orchestrator handles empty themes gracefully at line 422-424
("(no datasets registered for {THEME_NAME} yet)") so an empty DATASETS
list is harmless.

Do NOT delete this file. Do NOT add datasets here — the new demo design
ships only Theme 1 + Theme 2 (see theme1.py, theme2.py). If a third theme
is wanted later, populate DATASETS here and add a corresponding fixture
set under scripts/demo/fixtures/maps/.
"""
from __future__ import annotations
from themes import ThemeDataset

THEME_NAME = ""
THEME_DESCRIPTION = ""
THEME_IDX = 2

DATASETS: list[ThemeDataset] = []

---
resolved: 2026-05-21
resolved_in_phase: 1071
resolved_by_plan: 1071-03
resolution: "Added test_table_qualified_reference_rejected pinning exp.Dot rejection; runtime discovery (Rule 1+2) showed sqlglot collapses qualified refs into exp.Column with .table set rather than exp.Dot — fixed validate_where_ast to inspect Column.table/.db/.catalog at AST gate to honor documented contract."
commit: 3302769d07d3826f0baa3aefff7cf9594d63b8b2
---

---
created: 2026-05-20T00:00:00Z
title: "v1062 IN-03: where_validator.py has no test for exp.Dot AST bypass"
area: testing
phase: 1062
severity: info
source: 1062-REVIEW.md
resolves_phase: 1071
files:
  - backend/app/processing/export/where_validator.py
  - backend/tests/test_where_validator.py
---

## Finding

`validate_where_ast` (Phase 1062 SEC-S09) explicitly EXCLUDES `exp.Dot` from
its allowlist — meaning `table.column` references are rejected at the AST
level. There is no test that pins this rejection. If a future refactor adds
`exp.Dot` to `ALLOWED_EXPRESSIONS` by analogy (without updating the
downstream identifier regex), table-qualified injection could pass.

## Solution

Add a unit test:

```python
def test_table_qualified_reference_rejected():
    with pytest.raises(ValueError):
        validate_where_ast("catalog.records.title = 'x'")
```

## Deferred rationale

The behavior is correct today; the test is a regression pin for a hypothetical
future change. Not a real bug.

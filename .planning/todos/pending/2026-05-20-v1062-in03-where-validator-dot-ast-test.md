---
created: 2026-05-20T00:00:00Z
title: "v1062 IN-03: where_validator.py has no test for exp.Dot AST bypass"
area: testing
phase: 1062
severity: info
source: 1062-REVIEW.md
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

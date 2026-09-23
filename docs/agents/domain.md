# Domain Docs

GeoLens uses a single-context domain-documentation layout.

## Before exploring, read these

- `CONTEXT.md` at the repository root
- Relevant ADRs under `docs/adr/`
- Relevant ADRs under `docs-internal/decisions/`. The directory is gitignored, so only maintainer checkouts have it; it holds the refresh and record-model decisions that `docs/adr/` does not.

If these files do not exist, proceed silently. Do not suggest creating them upfront. The domain-modeling workflow creates them lazily when terminology or decisions are resolved.

## Layout

```text
/
├── CONTEXT.md
├── docs/
│   └── adr/
├── backend/
├── frontend/
├── cli/
└── mcp/
```

`CONTEXT.md` defines the shared domain vocabulary. `docs/adr/` contains system-wide architectural decisions.

## Use the glossary’s vocabulary

When output names a domain concept—in an issue title, refactoring proposal, hypothesis, or test name—use the term defined in `CONTEXT.md`. Do not drift to synonyms that the glossary explicitly avoids.

If a required concept is missing, reconsider whether the term reflects the project’s language or note the gap for the domain-modeling workflow.

## Flag ADR conflicts

If proposed work contradicts an existing ADR, surface the conflict explicitly instead of silently overriding the decision.

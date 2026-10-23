## Summary

<!-- What this PR changes and why. -->

## Related issue

<!-- Closes #1234. Write "None" if there isn't one. -->

Closes #

## Area

- [ ] Backend (API, services, models)
- [ ] Frontend (UI, components, hooks)
- [ ] Infrastructure (Docker, nginx)
- [ ] Tiles / Rendering
- [ ] Auth / Permissions
- [ ] Import / Ingestion
- [ ] OGC / Standards
- [ ] Docs / Config

## Schema, API and config impact

<!-- Migrations, API or OpenAPI changes (run `make sdks`), new or changed env vars or settings. Write "None" if there are none. -->

## Testing

<!-- What you ran and what you checked by hand. -->

- [ ] Backend: `cd backend && uv run ruff check . && uv run ruff format --check .`, plus the affected tests
- [ ] Frontend: `npm run lint`, `npm run typecheck` and `npm run test:coverage` from `frontend/`
- [ ] Playwright e2e for user-flow changes
- [ ] No tests needed (docs, config)

## Screenshots

<!-- Before and after for UI changes. Delete this section otherwise. -->

## Checklist

- [ ] New user-facing strings are in all five locales (en, es, fr, de, zh)
- [ ] No secrets or credentials in the diff
- [ ] Release/docs deploys: ran `make deployed-surface-check` after the marketing/docs deploy and recorded the result in Testing

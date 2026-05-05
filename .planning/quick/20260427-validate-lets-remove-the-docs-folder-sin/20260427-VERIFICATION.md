---
status: passed
date: 2026-05-05
task: "--validate lets remove the @docs folder since docs live in the getgeolens.com repo and we already have a docs-internal folder"
---

# Quick Task 20260427 Verification

## Must-Haves

- Root `docs/` directory removed: passed.
- Public docs links retargeted to docs.getgeolens.com or package registries: passed.
- README assets preserved outside `docs/`: passed, now in `.github/assets/`.
- Internal `docs-internal/` material preserved: passed.
- Unrelated dirty worktree changes preserved for separate work: passed, pending final commit staging review.

## Commands

- `test ! -d docs`: exit 0.
- `find .github/assets -maxdepth 1 -type f | sort`: listed the moved catalog, dataset, demo tour, avatar, map builder, and social preview assets.
- `rg -n "\\]\\(docs/|src=\\"docs/|github.com/geolens-io/geolens/blob/main/docs|docs/cli\\.md|docs/sdks\\.md|docs/widget-development\\.md|docs/testing-and-ci\\.md|docs/images|!docs/images" README*.md AGENTS.md CHANGELOG.md .github cli sdks .gitignore`: exit 1, no stale live root-docs links.
- `rg -n "docs/" --glob '!docs-internal/**' --glob '!backend/docs-internal/**' --glob '!frontend/docs/**' --glob '!node_modules/**' --glob '!.git/**' .`: reviewed accepted residual matches only.
- `git diff --check`: exit 0.
- `git diff --cached --check`: exit 0.
- `make cli-test`: initial run failed after CLI unit tests because the default local Postgres target did not have `geolens_test`.
- `docker compose up -d --wait db`: exit 0.
- `POSTGRES_HOST=localhost POSTGRES_PORT=5434 POSTGRES_DB=geolens POSTGRES_USER=geolens POSTGRES_PASSWORD=geolens JWT_SECRET_KEY=test-secret-key-for-ci-padding-32chars GEOLENS_ADMIN_USERNAME=admin GEOLENS_ADMIN_PASSWORD=admin make cli-test`: exit 0; CLI unit tests `170 passed`; backend CLI round trip `8 passed, 2 skipped`.

## Implementation Commit

- `42ed0461` — `docs(quick-20260427): remove root docs folder`

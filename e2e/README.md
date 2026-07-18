# End-to-End Tests

Playwright browser tests that exercise full-stack user flows against a running
GeoLens stack (the dockerized dev stack at `http://localhost:8080`). These are
the only browser/UI-flow tests in the repo; backend unit/integration tests live
in `backend/tests/` (pytest) and frontend component tests live alongside the
React source (`frontend/src/**/__tests__/`, Vitest).

## Running

```bash
npm ci                   # install Playwright (from the repo root)
npx playwright install   # one-time browser download
make dev                 # bring up the stack the specs run against

npm run e2e              # all specs
npm run e2e:smoke        # the smoke subset (core + builder + fixtures)
```

## Configs

- `playwright.config.ts`: the default config (Chromium), used by every
  `e2e:smoke:*` script except builder-hardening.
- `playwright.builder-hardening.config.ts`: a separate config that runs only
  `builder-hardening.spec.ts` across Chromium, Firefox, and WebKit.

The browser projects in both configs create one temporary vector dataset for
catalog-dependent flows. The cleanup project removes it after the browser tests
finish, including failed runs. The API-only export suite manages its own fixture
and does not require a browser install.

Against a host-run backend (uvicorn on the host + docker Postgres), the seeding
ingest cannot work — set `E2E_SKIP_SEED=1` to make setup authenticate and save
storage state without creating the shared fixture:

```bash
E2E_SKIP_SEED=1 E2E_BASE_URL=http://localhost:5173 npx playwright test e2e/foo.spec.ts --project=chromium
```

## Smoke groups

The `e2e:smoke:*` scripts in the root `package.json` group specs by area
(`core`, `builder`, `builder-hardening`, `fixtures`, `reupload`, `audit`,
`perf`). Specs not listed in a smoke group (e.g. `download-cog-token`,
`sec-audit`, `plugin-lifecycle`, `builder-unified-stack`) run only via the
catch-all `npm run e2e`.

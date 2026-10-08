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
  `e2e:smoke:*` script except builder-hardening and demo.
- `playwright.builder-hardening.config.ts`: a separate config that runs only
  `builder-hardening.spec.ts` across Chromium, Firefox, and WebKit.
- `playwright.demo.config.ts`: an opt-in, anonymous, read-only smoke against a
  named demo origin. It has no setup or cleanup project and is excluded from
  the default config.

The browser projects in the default and builder-hardening configs create one
temporary vector dataset for catalog-dependent flows. Their cleanup project
removes it after the browser tests finish, including failed runs. The demo
config performs no setup, cleanup, authentication, or writes. The API-only
export suite manages its own fixture and does not require a browser install.

Against a host-run backend (uvicorn on the host + docker Postgres), the seeding
ingest cannot work — set `E2E_SKIP_SEED=1` to make setup authenticate and save
storage state without creating the shared fixture:

```bash
E2E_SKIP_SEED=1 E2E_BASE_URL=http://localhost:5173 npx playwright test e2e/foo.spec.ts --project=chromium
```

## Signed-in session

Setup signs the admin in through the login form and saves the refresh cookie
and a token-free session marker to `playwright/.auth/user.json`. The app keeps
its access token in memory and recovers it from that cookie on every page
load, which rotates the cookie. The server revokes the whole session when a
rotated cookie is presented again after a short grace window, so specs import
`test` from `e2e/helpers/session.ts`, whose context writes the current cookie
back to the file when each test ends. A spec that signs in as another user or
signs out uses its own context, as `auth.spec.ts` does, or the next test inherits
that session. API calls made from Node use `getAuthToken()`, which reads the access
token kept beside the session file: setup saves the one from sign-in, and each
refresh in a test that uses the saved session replaces it.

## Smoke groups

The `e2e:smoke:*` scripts in the root `package.json` group specs by area
(`core`, `builder`, `builder-hardening`, `fixtures`, `reupload`, `audit`,
`perf`). Specs not listed in a smoke group (e.g. `download-cog-token`,
`sec-audit`, `plugin-lifecycle`, `builder-unified-stack`) run only via the
catch-all `npm run e2e`.

Run the deployed-demo smoke only against an explicitly named origin:

```bash
E2E_DEMO_BASE_URL=https://demo.getgeolens.com \
E2E_EXPECT_VERSION=1.19.1 \
npm run e2e:smoke:demo
```

The suite requires the ViewerMap composite `data-map-ready` contract. For an
older release that predates it, explicitly set `E2E_DEMO_LEGACY_READINESS=1`;
the report annotates the weaker fallback and still requires both
`data-tiles-loaded` and a completed dataset feature or tile response.

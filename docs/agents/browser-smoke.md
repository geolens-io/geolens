# Browser smoke checks with the Playwright MCP

Use this when you check the running app in a browser by hand, through the Playwright MCP server, rather than through `npm run e2e`.

## Signing in

`make smoke-auth` signs the admin in through the real login form and writes the session to `playwright/.auth/smoke.json`. It reads `GEOLENS_ADMIN_USERNAME` and `GEOLENS_ADMIN_PASSWORD` from `.env`, so the password never passes through your context. The file holds a live session token, so never print it.

Start the Playwright MCP server with `--isolated --storage-state playwright/.auth/smoke.json` (an absolute path), and every page opens signed in. The browser starts on the first browser tool call, so run `make smoke-auth` before that call. A page that lands on `/login`, or has no `geolens-auth` in `localStorage`, means the session expired or the browser restarted: run `make smoke-auth`, then `browser_close`, and the next browser call opens a browser with the new session.

The session belongs to the origin it was created on, `E2E_BASE_URL` (default `http://localhost:8080`). For a Vite server on another port, run `E2E_BASE_URL=http://localhost:5174 make smoke-auth`.

The e2e suite keeps its own session in `playwright/.auth/user.json`, so the two don't collide. Signing out still revokes the smoke session. To test sign-out or roles, create a throwaway user through the admin API. Give each parallel browser agent its own user.

## Locators

Copy locators from the spec for the area you're checking (`e2e/<area>.spec.ts`), since those already match the UI's accessible names. Start each `browser_run_code_unsafe` script with `page.setDefaultTimeout(5000)` so a wrong locator fails fast. Several labels repeat on one page (`Create`, `Data`, `Save`), so pass `exact: true` or scope the locator to a region.

`browser_run_code_unsafe` has no `require` and no dynamic `import`, so it cannot read local files.

## Fixtures

- Read rows with `docker compose exec -T db psql -U <POSTGRES_USER from .env> -d geolens`. Catalog tables live in the `catalog` schema and imported data in `data`. Run `\d catalog.<table>` before writing a query: a dataset's title and creation time are on `catalog.records`, not `catalog.datasets`.
- Feature editing is off by default. A check that edits features turns on **Admin → Settings → General → dataset editing**, and turns it off again when done.

## Screenshots

Take viewport screenshots. Full-page captures of long pages exceed the image size limit. The server writes only under the working directory and its `--output-dir`, so save screenshots there and not to a temp path.

Map tiles paint only in a visible browser. A blank map in a hidden Chrome tab proves nothing, so verify map rendering in Playwright.

## Cleaning up

Delete what the smoke check created through the API:

- `DELETE /api/datasets/{id}` requires a JSON body `{"confirm_title": "<the dataset's title>"}`.
- `GET /api/admin/users/` returns `{"users": [...]}`; delete each user with `DELETE /api/admin/users/{id}`.
- `DELETE /api/maps/{id}` removes a map.

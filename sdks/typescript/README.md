# @geolens/sdk (TypeScript)

Auto-generated TypeScript SDK for the [GeoLens](https://github.com/geolens-io/geolens) API.

Apache-2.0 licensed. Native `fetch` client + typed request/response interfaces + Bearer-token + API-key auth helpers. Requires Node 18+ (or any runtime with native `fetch`).

See [docs.getgeolens.com](https://docs.getgeolens.com/) for installation, regeneration, and version-pin policy.

## Install

```bash
npm install @geolens/sdk
```

The package is ESM only (`import`, not `require`).

## Quickstart

```typescript
import { createGeolensClient } from '@geolens/sdk';

const sdk = createGeolensClient({
  // The deployed API is served under /api, so include that suffix in baseUrl.
  baseUrl: 'https://geolens.example.com/api',
  bearerToken: '...',
});
// See docs.getgeolens.com for endpoint usage examples.
```

## Errors

Generated calls return `{ data, error, response }` and don't throw on an HTTP
error status. `error` is the parsed `application/problem+json` body
(`type`, `title`, `status`, `detail`):

```typescript
import { createGeolensClient, getSingleDatasetDatasetsDatasetIdGet } from '@geolens/sdk';

const sdk = createGeolensClient({ baseUrl: 'https://geolens.example.com/api', apiKey: '...' });
const { data, error, response } = await getSingleDatasetDatasetsDatasetIdGet({
  client: sdk.client,
  path: { dataset_id: '00000000-0000-0000-0000-000000000000' },
});
if (error) {
  console.error(response.status, error.detail);
}
```

With `throwOnError: true` the call throws the parsed error body, a plain object
rather than an `Error` instance.

`createGeolensClient()` returns a client scoped to that call (`sdk.client`).
Pass it explicitly to every generated endpoint call — `{ client: sdk.client }`
— when you build more than one client in the same process (for example, one
per request in a server), so concurrent callers cannot interfere with each
other. Omitting `client` from a generated call falls back to a shared
process-wide default that the most recent `createGeolensClient()` call
configures; that default is fine for a single-client script but is
last-caller-wins across concurrent clients.

## Redirects

When a redirect leaves the GeoLens origin, which happens when a COG download is
served from object storage, the SDK doesn't send credentials or client headers
there. Only `Range` and the `If-*` precondition headers go along.

In Node the SDK follows GET and HEAD redirects itself. A hop that leaves the
GeoLens origin goes through the global `fetch`, not the client's `fetch` option
(a proxy set with undici's `setGlobalDispatcher` still applies).

In a browser, where a redirect's target can't be read, a request carrying
`Authorization` or `X-API-Key` fails with `RedirectError`, and any other
request is sent again, without cookies, for the browser to follow. To download
a COG there, mint a download token (`POST /auth/download-token/{dataset_id}`)
and fetch `/datasets/{dataset_id}/download/cog?token=...` without credentials.

This applies to the default `redirect: 'follow'`. Set `redirect: 'manual'` or
`'error'`, per call or on the client, and you get what `fetch` gives: the
redirect returned unfollowed, or a `TypeError`.

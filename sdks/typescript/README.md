# @geolens/sdk (TypeScript)

Auto-generated TypeScript SDK for the [GeoLens](https://github.com/geolens-io/geolens) API.

Apache-2.0 licensed. Native `fetch` client + typed request/response interfaces + Bearer-token + API-key auth helpers. Requires Node 18+ (or any runtime with native `fetch`).

See [docs.getgeolens.com](https://docs.getgeolens.com/) for installation, regeneration, and version-pin policy.

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

`createGeolensClient()` returns a client scoped to that call (`sdk.client`).
Pass it explicitly to every generated endpoint call — `{ client: sdk.client }`
— when you build more than one client in the same process (for example, one
per request in a server), so concurrent callers cannot interfere with each
other. Omitting `client` from a generated call falls back to a shared
process-wide default that the most recent `createGeolensClient()` call
configures; that default is fine for a single-client script but is
last-caller-wins across concurrent clients.

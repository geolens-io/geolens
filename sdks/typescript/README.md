# @geolens/sdk (TypeScript)

Auto-generated TypeScript SDK for the [GeoLens](https://github.com/geolens-io/geolens) API.

Apache-2.0 licensed. Native `fetch` client + typed request/response interfaces + Bearer-token + API-key auth helpers. Requires Node 18+ (or any runtime with native `fetch`).

See [docs.getgeolens.com](https://docs.getgeolens.com/) for installation, regeneration, and version-pin policy.

## Quickstart

```typescript
import { createGeolensClient } from '@geolens/sdk';

const client = createGeolensClient({
  // The deployed API is served under /api, so include that suffix in baseUrl.
  baseUrl: 'https://geolens.example.com/api',
  bearerToken: '...',
});
// See docs.getgeolens.com for endpoint usage examples.
```

# @geolens/sdk (TypeScript)

Auto-generated TypeScript SDK for the [GeoLens](https://github.com/geolens-io/geolens) API.

Apache-2.0 licensed. Native `fetch` client + typed request/response interfaces + Bearer-token + API-key auth helpers. Requires Node 18+ (or any runtime with native `fetch`).

See `docs/sdks.md` in the GeoLens repo for installation, regeneration, and version-pin policy.

## Quickstart

```typescript
import { createGeolensClient } from '@geolens/sdk';

const client = createGeolensClient({
  baseUrl: 'https://geolens.example.com',
  bearerToken: '...',
});
// See ../../docs/sdks.md for endpoint usage examples.
```

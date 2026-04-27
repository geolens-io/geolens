// Hand-maintained — read by `npx @hey-api/openapi-ts@0.96.1`.
// Generator emits to src/client/. Plan 03 adds src/auth.ts + src/index.ts.
// Source: heyapi.dev/openapi-ts/configuration
//
// Note: the Makefile `sdks` target overrides `input` on the CLI with
// `-i /tmp/openapi-flat.json` (the flatten_openapi_defs.py output). The
// `input` value here is a fallback for direct `npx @hey-api/openapi-ts`
// invocations during local exploration — it points at the raw snapshot
// which the generator will choke on (Pitfall 1/2 territory). Always
// drive regeneration through `make sdks`.
//
// `format`/`postProcess` intentionally omitted — running prettier as a
// post-step would require adding it to devDeps, and the generator emits
// readable code without it. Drift gate (`make sdks-check`) only checks
// equality of consecutive runs, not formatting policy.
import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
  input: '../../backend/openapi.json',
  output: {
    path: 'src/client',
  },
  plugins: [
    '@hey-api/typescript',
    '@hey-api/sdk',
    '@hey-api/client-fetch',
  ],
});

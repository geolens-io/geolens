// Hand-maintained — read by `npx @hey-api/openapi-ts@0.96.1`.
// Generator emits to src/client/. Plan 03 adds src/auth.ts + src/index.ts.
// Source: heyapi.dev/openapi-ts/configuration
import { defineConfig } from '@hey-api/openapi-ts';

export default defineConfig({
  input: '../../backend/openapi.json',
  output: {
    path: 'src/client',
    format: 'prettier',
  },
  plugins: [
    '@hey-api/typescript',
    '@hey-api/sdk',
    '@hey-api/client-fetch',
  ],
});

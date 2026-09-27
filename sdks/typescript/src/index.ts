// SPDX-License-Identifier: Apache-2.0
/**
 * Public entry point for @geolens/sdk.
 *
 * Hand-maintained — re-exports the auth wrapper alongside the generated
 * client + types. Drift gate excludes this file.
 */
import { client } from './client/client.gen.js';
import { installFileReadHandling } from './fileReads.js';

// Hand-written auth surface
export { createGeolensClient } from './auth.js';
export type { GeolensClientOptions, GeolensClient } from './auth.js';

// Hand-written file-read result adapter
export { notModified } from './fileReads.js';

// Generated surface — re-export everything users need to make API calls.
// (The generated index.ts in src/client/ already re-exports types + sdk
// functions + the singleton client; one-line re-export keeps the public
// API stable across regenerations.)
export * from './client/index.js';

// Generated functions called without createGeolensClient() use this singleton.
installFileReadHandling(client);

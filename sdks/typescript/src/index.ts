// SPDX-License-Identifier: Apache-2.0
/**
 * Public entry point for @geolens/sdk.
 *
 * Hand-maintained — re-exports the auth wrapper alongside the generated
 * client + types. Drift gate excludes this file.
 */

// Hand-written auth surface
export { createGeolensClient } from './auth.js';
export type { GeolensClientOptions, GeolensClient } from './auth.js';

// Generated surface — re-export everything users need to make API calls.
// (The generated index.ts in src/client/ already re-exports types + sdk
// functions + the singleton client; one-line re-export keeps the public
// API stable across regenerations.)
export * from './client/index.js';

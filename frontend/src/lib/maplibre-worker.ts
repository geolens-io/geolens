import { addProtocol, setWorkerUrl } from 'maplibre-gl';
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { Protocol as PmtilesProtocol } from 'pmtiles';
import { tileRetryProtocol } from './tile-retry-protocol';

/**
 * Point maplibre-gl v6 at its worker file.
 *
 * v6 ships the worker as a separate ESM file resolved relative to
 * `import.meta.url`. `vite.config.ts` folds maplibre into the `map-vendor` chunk,
 * which moves `import.meta.url` away from the package directory, so the URL has
 * to be handed over explicitly.
 *
 * The `?worker&url` query is load-bearing: a plain `?url` emits the worker
 * without its `maplibre-gl-shared.mjs` sibling and fails silently in production
 * builds (vector tiles never request; upstream maplibre-gl-js#8186).
 *
 * This deliberately does not live in `main.tsx`: importing maplibre from the app
 * entry puts `map-vendor` (~295 kB gzip) in the eager entry graph, so every
 * login, admin and search page would download the mapping bundle, defeating the
 * lazy-route split in `App.tsx`. Import this module for its side effect from
 * each surface that constructs a map.
 *
 * It runs at module scope and the worker pool is created lazily on the first
 * `Map` construction, so this is early enough. Surfaces that only render inside
 * an existing map (e.g. FeaturePopup, which imports just `Popup`) don't need it.
 */
setWorkerUrl(maplibreWorkerUrl);

/**
 * Register the `pmtiles://` protocol so basemaps and style layers can point at a
 * single static PMTiles archive with no tile server.
 *
 * Registered here, not in `main.tsx`, for the same reason as `setWorkerUrl`. As
 * an ES module its top-level code runs once however many surfaces import it, so
 * registration is idempotent.
 */
addProtocol('pmtiles', new PmtilesProtocol().tile);

addProtocol('geolens-tile', tileRetryProtocol);

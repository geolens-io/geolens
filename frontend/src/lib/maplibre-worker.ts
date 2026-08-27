import { addProtocol, setWorkerUrl } from 'maplibre-gl';
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { Protocol as PmtilesProtocol } from 'pmtiles';

/**
 * feat(#846): point maplibre-gl v6 at its worker file.
 *
 * v6 ships the worker as a separate ESM file resolved relative to
 * `import.meta.url`. v5 was a UMD bundle that inlined the worker source and
 * self-registered it, so no consumer wiring existed. `vite.config.ts` folds
 * maplibre into the `map-vendor` chunk, which moves `import.meta.url` away from
 * the package directory and leaves the sibling worker unresolvable, so the URL
 * has to be handed over explicitly.
 *
 * The `?worker&url` query is load-bearing: a plain `?url` emits the worker
 * without its `maplibre-gl-shared.mjs` sibling and fails SILENTLY in production
 * builds. No error, no console message, vector tiles simply never request
 * (upstream maplibre-gl-js#8186).
 *
 * fix(#1624): this deliberately does NOT live in `main.tsx`. Importing
 * maplibre from the app entry puts `map-vendor` (~295 kB gzip) in the eager
 * entry graph and its modulepreload list, so every login, admin, and search
 * page would download the whole mapping bundle before rendering, defeating the
 * lazy-route split in `App.tsx`. Import this module for its side effect from
 * each surface that CONSTRUCTS a map instead, so it rides along in the lazy
 * chunk that already pulls maplibre.
 *
 * Runs at module scope, which is before any component renders, and the worker
 * pool is created lazily on the first `Map` construction, so this is early
 * enough. Surfaces that only render INSIDE an existing map (e.g. FeaturePopup,
 * which imports just `Popup`) do not need it.
 */
setWorkerUrl(maplibreWorkerUrl);

/**
 * feat(pmtiles): register the `pmtiles://` protocol so basemaps and style
 * layers can point at a single static PMTiles archive with no tile server.
 *
 * Registered here (not `main.tsx`) for the same reason as `setWorkerUrl`
 * above: this module only loads as a side effect of the lazy map-vendor
 * chunk, and an eager import from the app entry would pull that ~295 kB
 * chunk into every route. `addProtocol` is safe to call more than once (it
 * just replaces the handler for the scheme), and because this is an ES
 * module its top-level code runs once regardless of how many surfaces
 * import it, so registration is naturally idempotent.
 */
addProtocol('pmtiles', new PmtilesProtocol().tile);

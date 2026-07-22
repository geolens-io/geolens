import fs from 'fs'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// API_PROXY_TARGET is consumed only by the dev-server proxy below (Node side).
// It is *not* exposed to the browser bundle, so the `VITE_` prefix that Vite
// requires for browser-side env vars is intentionally absent. The deprecation
// window for the legacy `VITE_API_PROXY_TARGET` alias has closed (CONF-14,
// Phase 277 — see CHANGELOG.md for the original rename announcement).
const apiProxyTarget =
  process.env.API_PROXY_TARGET ||
  'http://localhost:8000'

// FRONTEND_ALLOWED_HOSTS: comma-separated Host header values the dev server
// accepts in addition to localhost/LAN, for serving the dev app behind a tunnel
// or reverse proxy that presents a public hostname (e.g. a Cloudflare tunnel).
// Vite blocks unknown Host headers as DNS-rebinding protection, so a tunnelled
// host must be listed here. Consumed Node-side only (no VITE_ prefix — this is
// dev-server config, not a browser var). Unset → Vite's default allowlist.
const allowedHosts = (process.env.FRONTEND_ALLOWED_HOSTS ?? '')
  .split(',')
  .map((h) => h.trim())
  .filter(Boolean)

// Stamp the frontend package version into the bundle at build time so the
// in-app "Report a problem" flow can auto-fill the GitHub issue version field
// without a runtime fetch. Exposed as the `__APP_VERSION__` global (see
// src/@types/build-globals.d.ts).
const appVersion = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, 'package.json'), 'utf-8'),
).version as string

function resolveExistingPath(target: string): string[] {
  if (!fs.existsSync(target)) return []

  const resolved = fs.realpathSync.native(target)
  return resolved === target ? [target] : [target, resolved]
}

const fsAllow = Array.from(new Set([
  path.resolve(__dirname),
  ...resolveExistingPath(path.resolve(__dirname, 'node_modules')),
  ...resolveExistingPath(path.resolve(__dirname, '../node_modules')),
]))

function manualChunks(id: string) {
  if (id.includes('/src/i18n/locales/')) {
    if (id.includes('/locales/de/')) return 'i18n-de'
    if (id.includes('/locales/es/')) return 'i18n-es'
    if (id.includes('/locales/fr/')) return 'i18n-fr'
    return 'i18n-en'
  }

  if (!id.includes('node_modules')) {
    return undefined
  }

  if (
    id.includes('react-dom') ||
    id.includes('/react/') ||
    id.includes('react-router') ||
    id.includes('@tanstack/react-query') ||
    id.includes('zustand') ||
    id.includes('sonner') ||
    id.includes('i18next') ||
    id.includes('react-i18next')
  ) {
    return 'app-vendor'
  }
  if (id.includes('@radix-ui') || id.includes('radix-ui')) return 'ui-vendor'
  if (id.includes('lucide-react')) return 'icon-vendor'
  if (id.includes('maplibre-gl') || id.includes('@vis.gl/react-maplibre')) return 'map-vendor'
  if (id.includes('terra-draw')) return 'draw-vendor'
  if (id.includes('@dnd-kit')) return 'dnd-vendor'
  if (id.includes('chroma-js') || id.includes('react-colorful')) return 'color-vendor'

  return undefined
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    __APP_VERSION__: JSON.stringify(appVersion),
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      // maplibre-contour uses non-standard export conditions (module/browser,
      // not import). Vitest's node environment cannot resolve `module` or
      // `browser` conditions, so we alias to the CJS build explicitly.
      'maplibre-contour': path.resolve(
        __dirname,
        'node_modules/maplibre-contour/dist/index.cjs',
      ),
    },
  },
  server: {
    port: 5173,
    host: true,
    // Only narrow the host allowlist when values are provided (tunnel/proxy
    // deployments); otherwise leave Vite's default behavior intact.
    ...(allowedHosts.length > 0 ? { allowedHosts } : {}),
    fs: {
      allow: fsAllow,
    },
    proxy: {
      '/health': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq, req) => {
            if (req.headers.host) proxyReq.setHeader('X-Forwarded-Host', req.headers.host);
          });
          // ROUTE-01 defense-in-depth (Phase 1092): rewrite any upstream
          // Location: http://api:8000/... to the external origin. Once
          // redirect_slashes=False lands in FastAPI, no 307 should reach
          // this hook, but the rewrite catches future code paths that
          // re-introduce one (e.g. an explicit 307 from a route handler).
          //
          // WR-05 (Phase 1092 review): scheme preservation. If the Vite
          // dev server is fronted by an HTTPS terminator (uncommon for
          // bundled dev but possible in mirror setups, behind tunnels
          // like ngrok, or in CI environments wrapping localhost), an
          // ``x-forwarded-proto: https`` header arrives on the request.
          // Hard-coding ``http://`` in the rewrite would emit a downgraded
          // Location to an HTTPS client, triggering mixed-content
          // warnings or downgrade redirects. Detect the inbound scheme
          // and preserve it on the rewrite.
          // WR-06 (Phase 1092 review): the detection regex must match the
          // SAME shape as the replacement regex. Previously the detection
          // required ``\/`` after the optional port (matching
          // ``http://api:8000/path``) while the replacement matched both
          // with-path and pathless forms — meaning a pathless
          // ``Location: http://api:8000`` would skip detection and pass
          // through unrewritten. FastAPI redirects always carry a path
          // in practice, but the inconsistency was sloppy and brittle.
          // Use ``(\/|$)`` to accept both shapes.
          proxy.on('proxyRes', (proxyRes, req) => {
            const location = proxyRes.headers.location
            if (typeof location === 'string' && /^https?:\/\/api(:\d+)?(\/|$)/.test(location)) {
              const externalHost = req.headers.host || 'localhost:8080'
              const forwardedProto = req.headers['x-forwarded-proto']
              const protoCandidate = Array.isArray(forwardedProto)
                ? forwardedProto[0]
                : forwardedProto
              const scheme = protoCandidate === 'https' ? 'https' : 'http'
              proxyRes.headers.location = location.replace(
                /^https?:\/\/api(:\d+)?/,
                `${scheme}://${externalHost}`,
              )
            }
          });
          // Dev-proxy resilience for large request bodies. In production nginx
          // buffers the full request body (`proxy_request_buffering on`) before
          // forwarding, so when the API rejects a large upload early — 413 (body
          // too large) or 401 (auth) — the browser still receives that real
          // status. Vite's dev proxy STREAMS the body instead, so an early
          // upstream response + socket close races the still-uploading body and
          // http-proxy raises ECONNRESET. With no 'error' listener that surfaces
          // as an opaque 502 (and an unhandled error in the dev console). Convert
          // it into a clean, explained response. The true upstream status is not
          // recoverable once the socket resets mid-upload — this only affects
          // requests the API was already going to reject, and only in dev.
          proxy.on('error', (err, _req, res) => {
            const code = (err as NodeJS.ErrnoException)?.code
            // For proxied WebSocket upgrades `res` is a raw Socket (no writeHead).
            if (res && 'writeHead' in res) {
              if (!res.headersSent) {
                res.writeHead(502, { 'Content-Type': 'application/json' })
                res.end(
                  JSON.stringify({
                    error: 'dev_proxy_upstream_reset',
                    detail:
                      'The API closed the connection before the request body ' +
                      'finished uploading (usually an early rejection of a large ' +
                      'body: size limit or auth). This streaming dev proxy cannot ' +
                      'recover the real status code; production buffers the body ' +
                      'and returns it directly.',
                  }),
                )
              }
            } else if (res && typeof res.destroy === 'function') {
              res.destroy()
            }
            console.warn(
              `[vite] /api proxy upstream error${code ? ` (${code})` : ''}: ${
                err?.message ?? String(err)
              }`,
            )
          });
        },
      },
      '/raster-tiles': {
        target: apiProxyTarget,
        changeOrigin: true,
        rewrite: (p) => {
          // /raster-tiles/{id}/tiles/{z}/{x}/{y}.png → /tiles/raster-proxy/{id}/{z}/{x}/{y}.png
          const m = p.match(/^\/raster-tiles\/([^/]+)\/tiles\/(.+)$/);
          return m ? `/tiles/raster-proxy/${m[1]}/${m[2]}` : p;
        },
      },
    },
  },
  build: {
    // MapLibre is isolated in map-vendor by manualChunks. Keep Vite's generic
    // warning above the current GIS engine chunk so build output only warns when
    // that explicit budget grows materially.
    chunkSizeWarningLimit: 1300,
    rollupOptions: {
      output: {
        manualChunks,
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    // Most component tests can skip stylesheet processing. The map-palette
    // contract test imports index.css as source so it can verify OKLCH/WebGL
    // parity without Node-only fs globals in the frontend TypeScript project.
    css: { include: [/index\.css/] },
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    setupFiles: ['./src/test/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov', 'html'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/test/**',
        'src/**/*.d.ts',
        'src/main.tsx',
        'src/vite-env.d.ts',
        'src/components/ui/**',
      ],
      // Coverage thresholds ratchet upward as the suite grows (TEST-02, Phase 278).
      // Each dimension is set to floor(actual_pct) from the most recent local
      // `npm test -- --run --coverage` run. To ratchet further: re-run coverage,
      // recompute floor(actual) and bump these (add a +1 / +2 buffer when actual
      // sits comfortably above the floor). Never lower without a documented
      // rationale in CHANGELOG.
      // 2026-05-07 actuals: statements 41.51 / branches 39.42 / functions 37.99 / lines 42.69
      // Note: plan-prescribed +2 buffer (43/41/39/44) failed all four dimensions because
      // actuals sit < 1pt above their integer floors. +1 buffer would also fail for the
      // same reason. Set to floor(actual) (= +0 buffer) — values still ratchet meaningfully
      // above the prior 32/27/27/32 baseline (statements +9, branches +12, functions +10,
      // lines +10) so the gate catches any non-trivial coverage regression.
      thresholds: {
        statements: 41,
        branches: 39,
        functions: 37,
        lines: 42,
      },
    },
  },
})

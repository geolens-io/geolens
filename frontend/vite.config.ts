import fs from 'fs'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// Dev proxy settings stay server-side; no VITE_ prefix.
const apiProxyTarget =
  process.env.API_PROXY_TARGET ||
  'http://localhost:8000'

// Explicit tunnel/proxy hosts extend Vite's DNS-rebinding allowlist.
const allowedHosts = (process.env.FRONTEND_ALLOWED_HOSTS ?? '')
  .split(',')
  .map((h) => h.trim())
  .filter(Boolean)

// The issue-report flow uses the build-time version without a runtime fetch.
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
    if (id.includes('/locales/zh/')) return 'i18n-zh'
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
  if (id.includes('react-colorful')) return 'color-vendor'

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
    },
  },
  server: {
    port: 5173,
    host: true,
    // Only narrow the host allowlist when values are provided (tunnel/proxy
    // deployments); otherwise leave Vite's default behavior intact.
    ...(allowedHosts.length > 0 ? { allowedHosts } : {}),
    // Let the API handle CORS preflights; Vite would otherwise answer before
    // the proxy and prevent the API's allowed-origin policy from taking effect.
    cors: false,
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
          // Rewrite internal API redirects to the external host and preserve HTTPS.
          // Match both pathless and path-bearing URLs to avoid leaking api:8000.
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
          // An early API rejection can reset a streamed upload. The original status
          // is then unavailable; return an explained 502 instead of losing the
          // response. Production nginx buffers uploads and preserves that status.
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
      // Coverage thresholds ratchet upward as the suite grows.
      // Never lower one without a documented rationale in CHANGELOG.
      //
      // These are floor(actual) as measured on 2026-05-07, and the suite has
      // since grown well past them. Measured 2026-07-31: statements 72.05 /
      // branches 67.31 / functions 66.29 / lines 74.16 — roughly 30 points of
      // headroom on every dimension, so an uncovered line does not trip a
      // threshold today.
      //
      // Thresholds are a floor from a recorded measurement rather than the
      // floor of the latest run. To ratchet: re-run `npm run
      // test:coverage`, set each to floor(actual), and update the measurement
      // above in the same commit.
      thresholds: {
        statements: 41,
        branches: 39,
        functions: 37,
        lines: 42,
      },
    },
  },
})

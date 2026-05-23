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
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    host: true,
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
          proxy.on('proxyRes', (proxyRes, req) => {
            const location = proxyRes.headers.location
            if (typeof location === 'string' && /^https?:\/\/api(:\d+)?\//.test(location)) {
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
    rollupOptions: {
      output: {
        manualChunks,
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
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

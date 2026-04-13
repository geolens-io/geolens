import fs from 'fs'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// API_PROXY_TARGET is consumed only by the dev-server proxy below (Node side).
// It is *not* exposed to the browser bundle, so the legacy `VITE_` prefix is not
// required. The fallback for backwards compatibility is preserved one release.
const apiProxyTarget =
  process.env.API_PROXY_TARGET ||
  process.env.VITE_API_PROXY_TARGET ||
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
      thresholds: {
        statements: 32,
        branches: 27,
        functions: 27,
        lines: 32,
      },
    },
  },
})

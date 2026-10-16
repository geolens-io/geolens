// Dev frontend readiness: the shell answers and the map builder's modules
// resolve. Serving "/" alone passes even when node_modules is stale or
// maplibre-gl is missing, because Vite only resolves imports when a module is
// requested.
const base = process.env.READINESS_URL ?? 'http://127.0.0.1:5173'
const builderModule = '/src/components/builder/BuilderMap.tsx'

async function get(path, type) {
  const res = await fetch(base + path, { signal: AbortSignal.timeout(8000) })
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`)
  // Vite answers unknown paths with the HTML shell and a 200.
  if (!(res.headers.get('content-type') ?? '').includes(type)) {
    throw new Error(`${path}: unexpected content type`)
  }
  return res.text()
}

try {
  await get('/', 'text/html')
  const source = await get(builderModule, 'javascript')
  // Importing an optimized dep makes Vite resolve it; a stale one answers 504.
  const dep = /["'](\/node_modules\/\.vite\/deps\/@vis__gl_react-maplibre\.js)(\?[^"']*)?["']/.exec(source)
  if (!dep) throw new Error(`${builderModule}: react-maplibre was not resolved`)
  const query = dep[2] ?? ''
  await get(dep[1] + query, 'javascript')
  await get('/node_modules/.vite/deps/maplibre-gl.js' + query, 'javascript')
} catch (err) {
  console.error(`frontend not ready: ${err.message}`)
  process.exit(1)
}

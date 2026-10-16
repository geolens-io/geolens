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

function findDep(source, from, name) {
  const match = new RegExp(`["'](/node_modules/\\.vite/deps/${name}\\.js(?:\\?[^"']*)?)["']`).exec(source)
  if (!match) throw new Error(`${from}: ${name} was not resolved`)
  return match[1]
}

try {
  await get('/', 'text/html')
  const source = await get(builderModule, 'javascript')
  // Importing an optimized dep makes Vite resolve it; a stale one answers 504.
  // Each optimized dep carries its own ?v= hash, so every URL comes from the
  // module that imports it.
  const reactMaplibre = findDep(source, 'builder module', '@vis__gl_react-maplibre')
  const reactMaplibreSource = await get(reactMaplibre, 'javascript')
  await get(findDep(reactMaplibreSource, 'react-maplibre', 'maplibre-gl'), 'javascript')
} catch (err) {
  console.error(`frontend not ready: ${err.message}`)
  process.exit(1)
}

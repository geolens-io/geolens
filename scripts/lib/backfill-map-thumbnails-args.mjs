// Pure argument parsing and map selection for backfill-map-thumbnails.mjs.

/** Parse argv (without node and script path) into { dryRun, includePublic, refresh }. */
export function parseArgs(argv) {
  const opts = { dryRun: false, includePublic: false, refresh: [] };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--dry-run') opts.dryRun = true;
    else if (arg === '--include-public') opts.includePublic = true;
    else if (arg === '--refresh') {
      // --refresh takes every following id up to the next flag.
      while (i + 1 < argv.length && !argv[i + 1].startsWith('--')) opts.refresh.push(argv[++i]);
      if (opts.refresh.length === 0) throw new Error('--refresh needs at least one map id');
    } else throw new Error(`unknown argument: ${arg}`);
  }
  return opts;
}

/**
 * Pick the maps to open. Without refresh ids that is every map missing a
 * thumbnail; with them it is exactly the named maps, thumbnail or not. Ids the
 * credential cannot see come back in `unknown`.
 */
export function selectMaps(maps, refresh) {
  if (refresh.length === 0) return { targets: maps.filter((m) => !m.thumbnail_url), unknown: [] };
  const byId = new Map(maps.map((m) => [m.id, m]));
  const ids = [...new Set(refresh)];
  return {
    targets: ids.filter((id) => byId.has(id)).map((id) => byId.get(id)),
    unknown: ids.filter((id) => !byId.has(id)),
  };
}

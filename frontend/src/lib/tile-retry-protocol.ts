import { AJAXError, type AddProtocolAction } from 'maplibre-gl';

// Keep one browser below the default ten-render server budget.
const MAX_CONCURRENT_TILES = 6;
const MAX_PENDING_TILES = 512;
const MAX_QUEUE_WAIT_MS = 120_000;
// Match the API proxy's read timeout; the pool's per-command timeout is not a render deadline.
const MAX_REQUEST_TIME_MS = 600_000;
const MAX_RETRIES = 2;
let activeTiles = 0;
const pendingTiles = new Set<() => void>();
const MAX_RETRY_DELAY_MS = 10_000;

function releaseTileSlot(): void {
  const next = pendingTiles.values().next().value;
  if (next) next();
  else activeTiles--;
}

function acquireTileSlot(url: string, signal: AbortSignal): Promise<() => void> {
  signal.throwIfAborted();
  if (activeTiles < MAX_CONCURRENT_TILES) {
    activeTiles++;
    return Promise.resolve(releaseTileSlot);
  }
  if (pendingTiles.size >= MAX_PENDING_TILES) {
    return Promise.reject(new AJAXError(429, 'Tile request queue is full', url, new Blob()));
  }
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      pendingTiles.delete(start);
      clearTimeout(timer);
      signal.removeEventListener('abort', abort);
    };
    const start = () => {
      cleanup();
      resolve(releaseTileSlot);
    };
    const abort = () => {
      cleanup();
      reject(signal.reason);
    };
    const timer = setTimeout(() => {
      cleanup();
      reject(new AJAXError(504, 'Tile request queue timed out', url, new Blob()));
    }, MAX_QUEUE_WAIT_MS);
    pendingTiles.add(start);
    signal.addEventListener('abort', abort, { once: true });
  });
}

function retryDelay(value: string | null): number {
  if (value === null) return 2000;
  if (/^\d+$/.test(value)) return Number(value) * 1000;
  const date = Date.parse(value);
  return Number.isFinite(date) ? Math.max(0, date - Date.now()) : 2000;
}

function waitForRetry(delay: number, signal: AbortSignal): Promise<void> {
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer);
      reject(signal.reason);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', abort);
      resolve();
    }, delay);
    signal.addEventListener('abort', abort, { once: true });
  });
}

const fetchTile: AddProtocolAction = async (request, controller) => {
  const url = request.url.slice('geolens-tile://'.length);
  for (let attempt = 0; ; attempt++) {
    controller.signal.throwIfAborted();
    const response = await fetch(url, {
      headers: request.headers,
      credentials: request.credentials ?? 'same-origin',
      cache: request.cache,
      referrerPolicy: request.referrerPolicy,
      signal: controller.signal,
    });
    if (response.ok) {
      return {
        data: await response.arrayBuffer(),
        cacheControl: response.headers.get('Cache-Control'),
        expires: response.headers.get('Expires'),
        etag: response.headers.get('ETag') ?? undefined,
      };
    }
    const delay = retryDelay(response.headers.get('Retry-After'));
    await response.body?.cancel();
    if (response.status !== 429 || attempt >= MAX_RETRIES || delay > MAX_RETRY_DELAY_MS) {
      throw new AJAXError(response.status, response.statusText, url, new Blob());
    }
    // A small jitter spreads the next wave across maps sharing the same cooldown.
    await waitForRetry(Math.max(250, delay) + Math.random() * 250, controller.signal);
  }
};

/** Schedule a tile within bounded capacity, preserving cooldowns and cancellation. */
export const tileRetryProtocol: AddProtocolAction = async (request, controller) => {
  const url = request.url.slice('geolens-tile://'.length);
  const release = await acquireTileSlot(url, controller.signal);
  const activeController = new AbortController();
  const abort = () => activeController.abort(controller.signal.reason);
  const timeout = setTimeout(() => {
    activeController.abort(new AJAXError(504, 'Tile request timed out', url, new Blob()));
  }, MAX_REQUEST_TIME_MS);
  try {
    controller.signal.throwIfAborted();
    controller.signal.addEventListener('abort', abort, { once: true });
    return await fetchTile(request, activeController);
  } finally {
    clearTimeout(timeout);
    controller.signal.removeEventListener('abort', abort);
    release();
  }
};

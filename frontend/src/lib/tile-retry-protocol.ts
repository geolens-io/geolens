import { AJAXError, type AddProtocolAction } from 'maplibre-gl';

const MAX_RETRIES = 2;
const MAX_RETRY_DELAY_MS = 10_000;

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

/** Fetch a vector tile, honoring short 429 cooldowns and MapLibre cancellation. */
export const tileRetryProtocol: AddProtocolAction = async (request, controller) => {
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

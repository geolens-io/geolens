import { ApiError, apiFetch } from './client';
import { abortableDelay } from '@/lib/abort';
import { createSlotPool } from '@/lib/slot-pool';
import type { components } from '@/types/api.generated';

export type AggregateRequest =
  | components['schemas']['CountRequest']
  | components['schemas']['StatsRequest']
  | components['schemas']['ValueCountsRequest']
  | components['schemas']['HistogramRequest']
  | components['schemas']['GroupByRequest'];

export type AggregateResponse =
  | components['schemas']['CountResponse']
  | components['schemas']['StatsResponse']
  | components['schemas']['ValueCountsResponse']
  | components['schemas']['HistogramResponse']
  | components['schemas']['GroupByResponse'];

// The endpoint answers a caller's third concurrent request with 429.
const slots = createSlotPool(2);
// It also allows each address ten requests a second. At most eight starts in
// any second keeps a full dashboard, a pan of many view-scoped widgets, and a
// few readers behind one office address clear of it.
export const AGGREGATE_STARTS_PER_WINDOW = 8;
const WINDOW_MS = 1000;
// How long the whole page waits after the rate limit refuses one request, when
// the response names no Retry-After: the limit's window.
const RATE_COOLDOWN_MS = WINDOW_MS;
const MAX_RETRIES = 3;

let recentStarts: number[] = [];
let cooldownUntil = 0;

/** Test-only: forget pacing and cooldown between cases. */
export function __resetAggregatePacingForTests() {
  recentStarts = [];
  cooldownUntil = 0;
}

/**
 * Books this request's start: after any cooldown, and once the start eight
 * back is a full window old. Starts are booked in order, so no window holds
 * more than eight.
 */
function bookStart(): number {
  const now = Date.now();
  const eighthBack = recentStarts.length >= AGGREGATE_STARTS_PER_WINDOW ? recentStarts[0] + WINDOW_MS : 0;
  const start = Math.max(now, cooldownUntil, eighthBack);
  recentStarts = [...recentStarts.slice(1 - AGGREGATE_STARTS_PER_WINDOW), start];
  return start - now;
}

/**
 * What a 429 means: the address's rate limit (a plain detail), or this caller
 * already having its share of running aggregates (`query_busy`,
 * `query_at_capacity`).
 */
function refusal(error: unknown): 'rate' | 'busy' | null {
  if (!(error instanceof ApiError) || error.status !== 429) return null;
  const code = typeof error.body === 'object' && error.body !== null ? (error.body as { code?: unknown }).code : null;
  return code === 'query_busy' || code === 'query_at_capacity' ? 'busy' : 'rate';
}

/**
 * One aggregate over a dataset's rows, for a widget. Requests share the
 * page's limits: two run at once, at most eight start in any second, and a
 * rate-limit refusal pauses all of them for its Retry-After. A refused
 * request is retried a few times before its error reaches the caller.
 * Embed viewers pass their embed token.
 */
export async function fetchAggregate(
  datasetId: string,
  body: AggregateRequest,
  { embedToken, signal }: { embedToken?: string; signal?: AbortSignal } = {},
): Promise<AggregateResponse> {
  for (let attempt = 0; ; attempt += 1) {
    let busyWait = 0;
    const release = await slots.acquire(signal);
    try {
      await abortableDelay(bookStart(), signal);
      return await apiFetch<AggregateResponse>(
        `/datasets/${encodeURIComponent(datasetId)}/aggregate/`,
        {
          method: 'POST',
          headers: embedToken ? { 'X-Embed-Token': embedToken } : {},
          body: JSON.stringify(body),
          signal,
        },
      );
    } catch (error) {
      const kind = refusal(error);
      if (kind === null || attempt >= MAX_RETRIES) throw error;
      if (kind === 'rate') {
        const wait = (error as ApiError).retryAfterMs ?? RATE_COOLDOWN_MS;
        cooldownUntil = Math.max(cooldownUntil, Date.now() + wait);
      } else {
        busyWait = 200 + Math.random() * 200;
      }
    } finally {
      release();
    }
    await abortableDelay(busyWait, signal);
  }
}

/** A create carries its key and attempt number as headers, and sends none without a key. */
import { createFeature } from '@/api/features';

function jsonResponse(body: unknown): Response {
  return { ok: true, status: 201, json: () => Promise.resolve(body) } as Response;
}

function sentHeaders(fetchMock: ReturnType<typeof vi.fn>, call: number): Headers {
  const init = (fetchMock.mock.calls[call] as unknown as [string, RequestInit])[1];
  return new Headers(init.headers);
}

describe('createFeature', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends the key and the attempt number as headers', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ id: 1 }));
    vi.stubGlobal('fetch', fetchMock);

    await createFeature('ds-1', { type: 'Point', coordinates: [1, 1] }, {}, 'sketch-abc', 3);

    const headers = sentHeaders(fetchMock, 0);
    expect(headers.get('Idempotency-Key')).toBe('sketch-abc');
    expect(headers.get('Idempotency-Attempt')).toBe('3');
  });

  it('sends no idempotency header when it has no key', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ id: 1 }));
    vi.stubGlobal('fetch', fetchMock);

    await createFeature('ds-1', { type: 'Point', coordinates: [1, 1] }, {});

    const headers = sentHeaders(fetchMock, 0);
    expect(headers.get('Idempotency-Key')).toBeNull();
    expect(headers.get('Idempotency-Attempt')).toBeNull();
  });
});

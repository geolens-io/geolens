import { streamGenerateMap, streamChatMessage } from '@/api/maps';
import { useAuthStore } from '@/stores/auth-store';
import type { StreamEvent } from '@/api/maps';

const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

function streamingResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    body,
    headers: new Headers(),
  } as unknown as Response;
}

async function collect<T>(gen: AsyncGenerator<T>): Promise<T[]> {
  const out: T[] = [];
  for await (const ev of gen) out.push(ev);
  return out;
}

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ token: 'test-token', refreshToken: null, expiresAt: null, user: null });
});

describe('streamGenerateMap SSE parser', () => {
  it('yields all events when the server uses CRLF separators (sse-starlette default)', async () => {
    // This is the exact failure mode that produced "Failed to generate map"
    // even though the backend completed cleanly. Splitting on \n alone
    // leaves a trailing \r on the boundary line, so `line === ''` never
    // matched and `done` was never yielded.
    mockFetch.mockResolvedValueOnce(
      streamingResponse([
        'event: tool_start\r\n',
        'data: {"type":"tool_start","tool":"search_datasets","label":"Searching..."}\r\n',
        '\r\n',
        'event: done\r\n',
        'data: {"type":"done","map_id":"abc-123","explanation":"ok","datasets_used":["a"]}\r\n',
        '\r\n',
      ]),
    );

    const events = await collect(streamGenerateMap({ prompt: 'p' }));

    expect(events).toHaveLength(2);
    expect(events[0].event).toBe('tool_start');
    expect(events[1].event).toBe('done');
    expect(events[1].data).toMatchObject({ type: 'done', map_id: 'abc-123' });
  });

  it('still yields events when the server uses LF-only separators', async () => {
    mockFetch.mockResolvedValueOnce(
      streamingResponse([
        'event: done\n',
        'data: {"type":"done","map_id":"xyz","explanation":"","datasets_used":[]}\n',
        '\n',
      ]),
    );

    const events = await collect(streamGenerateMap({ prompt: 'p' }));

    expect(events).toHaveLength(1);
    expect(events[0].event).toBe('done');
    expect((events[0].data as { map_id: string }).map_id).toBe('xyz');
  });

  it('yields events when frames arrive split mid-CRLF across chunks', async () => {
    // Each chunk break lands inside a \r\n pair to exercise the
    // buffer-pop behavior that hands the partial tail to the next read.
    mockFetch.mockResolvedValueOnce(
      streamingResponse([
        'event: done\r',
        '\ndata: {"type":"done","map_id":"split","explanation":"","datasets_used":[]}\r',
        '\n\r\n',
      ]),
    );

    const events = await collect(streamGenerateMap({ prompt: 'p' }));

    expect(events).toHaveLength(1);
    expect(events[0].event).toBe('done');
    expect((events[0].data as { map_id: string }).map_id).toBe('split');
  });

  it('threads the AbortSignal through to fetch', async () => {
    mockFetch.mockResolvedValueOnce(streamingResponse([]));
    const controller = new AbortController();

    await collect(streamGenerateMap({ prompt: 'p' }, controller.signal));

    expect(mockFetch).toHaveBeenCalledWith(
      expect.stringContaining('/ai/generate-map/stream/'),
      expect.objectContaining({ signal: controller.signal }),
    );
  });

});

describe('streamChatMessage SSE parser', () => {
  it('yields all events when the server uses CRLF separators', async () => {
    mockFetch.mockResolvedValueOnce(
      streamingResponse([
        'event: token\r\n',
        'data: {"text":"Hello"}\r\n',
        '\r\n',
        'event: done\r\n',
        'data: {"explanation":"Hello world"}\r\n',
        '\r\n',
      ]),
    );

    const events: StreamEvent[] = await collect(
      streamChatMessage('map-1', 'hi', [], 'en', undefined, undefined),
    );

    expect(events).toHaveLength(2);
    expect(events[0]).toMatchObject({ event: 'token', data: { text: 'Hello' } });
    expect(events[1]).toMatchObject({ event: 'done', data: { explanation: 'Hello world' } });
  });
});

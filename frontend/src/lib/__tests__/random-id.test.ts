import { afterEach, describe, expect, it, vi } from 'vitest';
import { randomId } from '../random-id';

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe('randomId', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns a version 4 UUID', () => {
    expect(randomId()).toMatch(UUID_V4);
  });

  it('still returns unique version 4 UUIDs where crypto.randomUUID is missing, as on plain HTTP', () => {
    const real = globalThis.crypto;
    vi.stubGlobal('crypto', { getRandomValues: real.getRandomValues.bind(real) });

    const ids = Array.from({ length: 1000 }, () => randomId());

    for (const id of ids) {
      expect(id).toMatch(UUID_V4);
    }
    expect(new Set(ids).size).toBe(ids.length);
  });
});

import { describe, expect, it } from 'vitest';

import {
  dedupeOrigins,
  InvalidOriginError,
  normalizeOrigin,
  WildcardOriginError,
} from '../url-normalize';

describe('normalizeOrigin', () => {
  // scheme-add
  it("adds https:// scheme when no scheme is present", () => {
    expect(normalizeOrigin('Example.com')).toBe('https://example.com');
  });

  // lowercase host
  it("lowercases the host", () => {
    expect(normalizeOrigin('https://Example.com/')).toBe('https://example.com');
  });

  // lowercase scheme
  it("lowercases an uppercase scheme", () => {
    expect(normalizeOrigin('HTTPS://example.com//')).toBe('https://example.com');
  });

  // trailing slash stripped (non-root)
  it("strips trailing slash", () => {
    expect(normalizeOrigin('http://localhost:3000/')).toBe('http://localhost:3000');
  });

  // default port stripped for https
  it("strips default port 443 for https", () => {
    expect(normalizeOrigin('https://example.com:443')).toBe('https://example.com');
  });

  // default port stripped for http
  it("strips default port 80 for http", () => {
    expect(normalizeOrigin('http://example.com:80/')).toBe('http://example.com');
  });

  // path discarded — origin only
  it("discards path component, returns origin only", () => {
    expect(normalizeOrigin('https://Example.COM:8080/foo')).toBe('https://example.com:8080');
  });

  // non-default port preserved
  it("preserves explicit non-default port", () => {
    expect(normalizeOrigin('http://localhost:3000')).toBe('http://localhost:3000');
  });

  // wildcard throws WildcardOriginError with correct message
  it("throws WildcardOriginError for wildcard '*'", () => {
    expect(() => normalizeOrigin('*')).toThrow(WildcardOriginError);
  });

  it("throws with message 'Wildcard origin not allowed' for '*'", () => {
    expect(() => normalizeOrigin('*')).toThrow(/Wildcard origin not allowed/);
  });

  // whitespace-only throws InvalidOriginError
  it("throws InvalidOriginError for whitespace-only input", () => {
    expect(() => normalizeOrigin('   ')).toThrow(InvalidOriginError);
  });

  // empty string throws InvalidOriginError
  it("throws InvalidOriginError for empty string", () => {
    expect(() => normalizeOrigin('')).toThrow(InvalidOriginError);
  });

  // malformed string throws InvalidOriginError
  it("throws InvalidOriginError for malformed input that URL constructor rejects", () => {
    expect(() => normalizeOrigin('not a url at all')).toThrow(InvalidOriginError);
  });
});

describe('dedupeOrigins', () => {
  it("deduplicates entries that normalize to the same canonical form", () => {
    expect(dedupeOrigins(['https://example.com', 'HTTPS://Example.com/'])).toEqual(['https://example.com']);
  });

  it("preserves insertion order while dropping duplicates", () => {
    expect(dedupeOrigins(['https://a.com', 'https://b.com', 'https://a.com'])).toEqual(['https://a.com', 'https://b.com']);
  });

  it("returns empty array for empty input", () => {
    expect(dedupeOrigins([])).toEqual([]);
  });

  it("filters out wildcard entries without throwing, preserving valid entries", () => {
    expect(dedupeOrigins(['*', 'https://example.com'])).toEqual(['https://example.com']);
  });
});

describe('parity with backend _normalize_origin', () => {
  // backend/app/modules/embed_tokens/schemas.py:14-31

  it("http://localhost:3000 stays unchanged", () => {
    expect(normalizeOrigin('http://localhost:3000')).toBe('http://localhost:3000');
  });

  it("https://dashboard.example.com stays unchanged", () => {
    expect(normalizeOrigin('https://dashboard.example.com')).toBe('https://dashboard.example.com');
  });

  it("https://partner.example stays unchanged", () => {
    expect(normalizeOrigin('https://partner.example')).toBe('https://partner.example');
  });

  it("HTTPS://EXAMPLE.COM:443/ collapses to https://example.com (case + default-port + trailing-slash)", () => {
    expect(normalizeOrigin('HTTPS://EXAMPLE.COM:443/')).toBe('https://example.com');
  });

  it("http://example.com:8080 preserves non-default port", () => {
    expect(normalizeOrigin('http://example.com:8080')).toBe('http://example.com:8080');
  });
});

import { describe, it, expect } from 'vitest';
import { redact } from '../redact';

const SAMPLE_JWT =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c';

describe('redact', () => {
  it('strips JWTs', () => {
    expect(redact(SAMPLE_JWT)).toBe('[redacted-token]');
    expect(redact(`Authorization header carried ${SAMPLE_JWT} oops`)).not.toContain(SAMPLE_JWT);
  });

  it('strips Authorization: Bearer tokens', () => {
    expect(redact('Authorization: Bearer abc.def-ghi123')).toContain('Bearer [redacted]');
  });

  it('strips key=value credentials with or without a query separator', () => {
    expect(redact('https://x/y?api_key=supersecret&z=1')).not.toContain('supersecret');
    expect(redact('request failed api_key=supersecret')).toContain('api_key=[redacted]');
    expect(redact('access_token=abc123def')).toContain('access_token=[redacted]');
  });

  it('strips JSON-style secret fields', () => {
    expect(redact('{"password":"hunter2","ok":true}')).not.toContain('hunter2');
  });

  it('strips the full quoted value even when it contains spaces', () => {
    expect(redact('password="correct horse battery staple"')).toBe('password="[redacted]"');
    expect(redact("token: 'a b c d e'")).not.toContain('a b c d e');
    // surrounding text must survive
    expect(redact('{"password":"correct horse","ok":true}')).toContain('"ok":true');
  });

  it('strips unquoted / object-literal secret fields', () => {
    expect(redact('{ token: "secret_token_123", apiKey: "key_456" }')).not.toContain('secret_token_123');
    expect(redact('{ token: "secret_token_123", apiKey: "key_456" }')).not.toContain('key_456');
  });

  it('strips signed-tile sig= parameters', () => {
    const out = redact('/api/tiles/data.table/3/2/1.pbf?sig=abc123HMACxyz&exp=1700000000&scope=Dataset:1');
    expect(out).not.toContain('abc123HMACxyz');
    expect(out).toContain('sig=[redacted]');
  });

  it('strips session identifiers', () => {
    expect(redact('JSESSIONID=ABC123DEF456GHI')).not.toContain('ABC123DEF456GHI');
    expect(redact('session_id=secretvalue')).not.toContain('secretvalue');
  });

  it('strips share/embed tokens that live in the URL path', () => {
    const out = redact('https://geolens.io/m/2fXkR9m3pL8qW4vN7tY');
    expect(out).not.toContain('2fXkR9m3pL8qW4vN7tY');
    expect(out).toContain('/m/[redacted]');
  });

  it('does not redact the /maps/:id builder route', () => {
    expect(redact('https://geolens.io/maps/42')).toContain('/maps/42');
  });

  it('strips email addresses', () => {
    expect(redact('contact jane.doe@example.com please')).toContain('[redacted-email]');
  });

  it('does not over-redact unrelated key names', () => {
    expect(redact('csrf_token=keepme')).toContain('keepme');
  });

  it('coerces non-string input safely', () => {
    expect(redact(null)).toBe('');
    expect(redact(undefined)).toBe('');
    expect(redact(42)).toBe('42');
  });
});

import { describe, expect, it } from 'vitest';
import { isSafeHttpUrl } from '@/lib/safe-http-url';

describe('isSafeHttpUrl', () => {
  it('accepts http and https URLs', () => {
    expect(isSafeHttpUrl('https://example.com/privacy')).toBe(true);
    expect(isSafeHttpUrl('http://example.com/privacy')).toBe(true);
  });

  it('is case-insensitive on the scheme', () => {
    expect(isSafeHttpUrl('HTTPS://example.com/privacy')).toBe(true);
  });

  it('rejects a javascript: value', () => {
    expect(isSafeHttpUrl('javascript:alert(document.cookie)')).toBe(false);
  });

  it('rejects a data: value', () => {
    expect(isSafeHttpUrl('data:text/html,<script>alert(1)</script>')).toBe(false);
  });

  it('rejects a scheme-relative value', () => {
    expect(isSafeHttpUrl('//evil.example.com/p')).toBe(false);
  });

  it('rejects null, undefined, and non-string input', () => {
    expect(isSafeHttpUrl(null)).toBe(false);
    expect(isSafeHttpUrl(undefined)).toBe(false);
  });
});

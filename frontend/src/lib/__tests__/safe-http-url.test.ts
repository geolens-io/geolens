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

  it('rejects an address with no host, or with whitespace or control characters', () => {
    for (const url of ['https://', 'https://exa mple.com', 'https://example.com/\n', ' https://example.com']) {
      expect(isSafeHttpUrl(url), JSON.stringify(url)).toBe(false);
    }
  });

  it('refuses what the server refuses: credentials, odd host labels, encoded or rewritten hosts', () => {
    for (const url of [
      'https://user:pass@example.com/report',
      'https://user@example.com/report',
      'https://internal_host/report',
      'https://-bad.example.com/',
      'https://a..b.example.com/',
      'https://example.com../',
      'https://exa%6dple.com/',
      'https://0x7f.1/',
      'https://192.168.1/',
    ]) {
      expect(isSafeHttpUrl(url), url).toBe(false);
    }
  });

  it('accepts ports, IP literals and international hosts', () => {
    for (const url of [
      'https://example.com:8443/report',
      'https://192.168.1.10/report',
      'https://[2001:db8::1]/report',
      'https://xn--bcher-kva.example/',
      'https://bücher.example/',
      'https://EXAMPLE.com/Report',
      'https://example.com./privacy',
    ]) {
      expect(isSafeHttpUrl(url), url).toBe(true);
    }
  });
});

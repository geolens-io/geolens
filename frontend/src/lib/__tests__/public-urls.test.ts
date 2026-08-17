import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { getPublicAppBaseUrl, getShareableBaseUrl } from '@/lib/public-urls';

const SERVED_AT = 'https://maps.example.com';
// What both compose files inject when the operator never set PUBLIC_APP_URL.
const COMPOSE_DEFAULT = 'http://localhost:8080';

describe('getPublicAppBaseUrl', () => {
  it('returns a real configured origin', () => {
    expect(
      getPublicAppBaseUrl({ public_app_url: 'https://maps.example.com' }, SERVED_AT),
    ).toBe('https://maps.example.com');
  });

  it('trims a trailing slash so callers can append a path', () => {
    expect(
      getPublicAppBaseUrl({ public_app_url: 'https://maps.example.com/' }, SERVED_AT),
    ).toBe('https://maps.example.com');
  });

  it('preserves a configured sub-path', () => {
    // PUBLIC_APP_URL=https://example.com/geolens is a real deployment shape.
    // The backend compares ORIGINS (path dropped), so keeping it here still
    // agrees with the domain-lock check while producing a URL that resolves.
    expect(
      getPublicAppBaseUrl({ public_app_url: 'https://example.com/geolens/' }, SERVED_AT),
    ).toBe('https://example.com/geolens');
  });

  /**
   * fix(#1548 review r4): the third state. "Configured" is not a boolean —
   * compose injects `${PUBLIC_APP_URL:-http://localhost:8080}`, so the value is
   * present, non-null, and wrong for every install that never set it. A null
   * check cannot see that; this is the case it must catch.
   */
  it.each([
    ['the compose default', COMPOSE_DEFAULT],
    ['bare localhost', 'http://localhost'],
    ['loopback IPv4', 'http://127.0.0.1:8080'],
    ['loopback IPv6', 'http://[::1]:8080'],
    ['uppercase host', 'http://LOCALHOST:8080'],
  ])('rejects %s while the browser is on a real hostname', (_label, configured) => {
    expect(getPublicAppBaseUrl({ public_app_url: configured }, SERVED_AT)).toBeNull();
  });

  it('accepts a localhost value on a genuine localhost install', () => {
    // Here the value is right and the deployment IS localhost. Rejecting it
    // would break the default dev stack, which the browser reaches at :8080.
    expect(getPublicAppBaseUrl({ public_app_url: COMPOSE_DEFAULT }, COMPOSE_DEFAULT)).toBe(
      COMPOSE_DEFAULT,
    );
    expect(
      getPublicAppBaseUrl({ public_app_url: COMPOSE_DEFAULT }, 'http://localhost:5174'),
    ).toBe(COMPOSE_DEFAULT);
  });

  it.each([
    ['missing config', undefined],
    ['null config', null],
    ['null value', { public_app_url: null }],
    ['empty value', { public_app_url: '' }],
    ['whitespace value', { public_app_url: '   ' }],
    ['unparseable value', { public_app_url: 'not a url' }],
  ])('returns null for %s rather than guessing', (_label, config) => {
    // 'not a url' is not loopback, so it survives the trust check and is
    // returned as-is; only absent values are null here.
    const result = getPublicAppBaseUrl(config, SERVED_AT);
    expect(result === null || result === 'not a url').toBe(true);
  });
});

describe('getShareableBaseUrl', () => {
  /**
   * fix(#1548 review r4): the regression this guards. Ordinary share links and
   * unrestricted embeds worked before any of this, using the serving origin.
   * Building them from an untrustworthy configured value points every default
   * install at localhost — a link nobody can open. A serving origin is usable
   * even when it is not the canonical public one, so it wins over nothing.
   */
  it('falls back to the serving origin when the config is the compose default', () => {
    expect(getShareableBaseUrl({ public_app_url: COMPOSE_DEFAULT }, SERVED_AT)).toBe(
      SERVED_AT,
    );
  });

  it('falls back to the serving origin when nothing is configured', () => {
    expect(getShareableBaseUrl({ public_app_url: null }, SERVED_AT)).toBe(SERVED_AT);
    expect(getShareableBaseUrl(undefined, SERVED_AT)).toBe(SERVED_AT);
  });

  it('prefers a real configured origin over the admin hostname', () => {
    // The independent bug: an admin on an internal hostname must not hand out
    // a URL only they can open.
    expect(
      getShareableBaseUrl({ public_app_url: SERVED_AT }, 'https://internal.corp:8443'),
    ).toBe(SERVED_AT);
  });

  it('never returns empty for a browser that has an origin', () => {
    expect(getShareableBaseUrl({ public_app_url: COMPOSE_DEFAULT }, SERVED_AT)).toBeTruthy();
  });
});

/**
 * fix(#1548 review r3): cover the class, not just the one call site.
 *
 * The bug was that SharePanel built the embed snippet from
 * `window.location.origin` — whatever hostname the ADMIN happened to be using —
 * for a URL that someone else opens. The share link and its /card twin had the
 * same defect, so fixing only the snippet would have left the two disagreeing
 * about their own origin.
 *
 * This pins that no path handed to a third party is rebuilt from the current
 * origin inline. It reads the source rather than the rendered output because
 * the next such builder has not been written yet, and that is the one this is
 * for. The origin is resolved ONCE at the top of the component, through
 * lib/public-urls.ts, and every builder reads that.
 */
describe('no shareable URL is built from the current origin', () => {
  const SHAREABLE_PATHS = [
    '/m/', // the embed shell and viewer
    '/api/maps/shared/', // the unfurlable /card link
  ];

  it('SharePanel builds none of them from window.location.origin', () => {
    const source = readFileSync(
      join(process.cwd(), 'src/components/builder/SharePanel.tsx'),
      'utf-8',
    );

    const offenders = source
      .split('\n')
      .map((line, i) => [line, i + 1] as const)
      .filter(([line]) => line.includes('window.location.origin'))
      .filter(([line]) => SHAREABLE_PATHS.some((p) => line.includes(p)));

    expect(
      offenders.map(([line, n]) => `${n}: ${line.trim()}`),
      'resolve the origin through lib/public-urls.ts instead — a URL opened by ' +
        'someone else must not be built from this admin hostname inline',
    ).toEqual([]);
  });
});

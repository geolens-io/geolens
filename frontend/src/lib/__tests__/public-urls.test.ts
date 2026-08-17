import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { getPublicAppBaseUrl } from '@/lib/public-urls';

describe('getPublicAppBaseUrl', () => {
  it('returns the configured public origin', () => {
    expect(getPublicAppBaseUrl({ public_app_url: 'https://maps.example.com' })).toBe(
      'https://maps.example.com',
    );
  });

  it('trims a trailing slash so callers can append a path', () => {
    expect(getPublicAppBaseUrl({ public_app_url: 'https://maps.example.com/' })).toBe(
      'https://maps.example.com',
    );
  });

  it('preserves a configured sub-path', () => {
    // PUBLIC_APP_URL=https://example.com/geolens is a real deployment shape.
    // The backend compares ORIGINS (path dropped), so keeping it here still
    // agrees with the domain-lock check while producing a URL that resolves.
    expect(
      getPublicAppBaseUrl({ public_app_url: 'https://example.com/geolens/' }),
    ).toBe('https://example.com/geolens');
  });

  it.each([
    ['missing config', undefined],
    ['null config', null],
    ['null value', { public_app_url: null }],
    ['empty value', { public_app_url: '' }],
    ['whitespace value', { public_app_url: '   ' }],
  ])('returns null for %s rather than guessing', (_label, config) => {
    expect(getPublicAppBaseUrl(config)).toBeNull();
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
 * origin. It reads the source rather than the rendered output because the next
 * such builder has not been written yet, and that is the one this is for.
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
      .filter(([line]) => SHAREABLE_PATHS.some((p) => line.includes(p)))
      // getShareUrl feeds the "Open" button only — navigation in this admin's
      // own browser, handed to nobody — and documents that exemption inline.
      .filter(([line]) => !line.includes('publicAppBaseUrl ??'));

    expect(
      offenders.map(([line, n]) => `${n}: ${line.trim()}`),
      'build these from getPublicAppBaseUrl(tileConfig) instead — a URL opened ' +
        'by someone else must come from the configured public origin',
    ).toEqual([]);
  });
});

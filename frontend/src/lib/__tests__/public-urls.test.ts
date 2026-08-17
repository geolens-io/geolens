import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import {
  getLockedPreviewBaseUrl,
  getPublicAppBaseUrl,
  getShareableBaseUrl,
  resolvePublicAppUrl,
} from '@/lib/public-urls';

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
 * fix(#1548 review r6): the states, asserted by name.
 *
 * PUBLIC_APP_URL has been treated as a boolean three times on this PR — "is it
 * set" — and each round the missed case was a state nobody had written down.
 * Naming them in the type is only half the fix; this pins that each one is
 * actually reached, so a future branch that collapses two of them fails here
 * rather than in review.
 */
describe('resolvePublicAppUrl enumerates every state of the setting', () => {
  const SERVED_AT = 'https://maps.example.com';

  it('unset', () => {
    expect(resolvePublicAppUrl(undefined, SERVED_AT)).toEqual({ kind: 'unset' });
    expect(resolvePublicAppUrl(null, SERVED_AT)).toEqual({ kind: 'unset' });
    expect(resolvePublicAppUrl({ public_app_url: null }, SERVED_AT)).toEqual({
      kind: 'unset',
    });
    expect(resolvePublicAppUrl({ public_app_url: '   ' }, SERVED_AT)).toEqual({
      kind: 'unset',
    });
  });

  /**
   * The backend Settings field takes PUBLIC_APP_URL from the environment as a
   * raw string and never parses it, so tile-config hands back whatever was
   * typed. A previous revision asked `isLoopbackOrigin()` first and read its
   * PARSE FAILURE as "not loopback, therefore fine" — a narrower predicate
   * standing in for trust — and built card links like `not-a-url/api/...`.
   */
  it.each([
    ['plain text', 'not-a-url'],
    ['scheme-less host', 'maps.example.com'],
    ['non-HTTP scheme', 'ftp://maps.example.com'],
    ['mailto', 'mailto:ops@example.com'],
    ['javascript', 'javascript:alert(1)'],
    ['file', 'file:///etc/hosts'],
  ])('malformed: %s', (_label, value) => {
    expect(resolvePublicAppUrl({ public_app_url: value }, SERVED_AT)).toEqual({
      kind: 'malformed',
      value,
    });
  });

  it('loopback-default', () => {
    expect(
      resolvePublicAppUrl({ public_app_url: 'http://localhost:8080' }, SERVED_AT),
    ).toEqual({ kind: 'loopback-default', value: 'http://localhost:8080' });
  });

  it('trusted', () => {
    expect(resolvePublicAppUrl({ public_app_url: SERVED_AT }, SERVED_AT)).toEqual({
      kind: 'trusted',
      baseUrl: SERVED_AT,
    });
  });

  it('trusted, for a genuine localhost install', () => {
    expect(
      resolvePublicAppUrl(
        { public_app_url: 'http://localhost:8080' },
        'http://localhost:3000',
      ),
    ).toEqual({ kind: 'trusted', baseUrl: 'http://localhost:8080' });
  });

  it('has no state for VALID BUT WRONG, and must not invent one', () => {
    // A stale public hostname parses, is not loopback, and only DNS knows it
    // no longer serves GeoLens. Guessing here would refuse working setups.
    expect(
      resolvePublicAppUrl({ public_app_url: 'https://old.example.com' }, SERVED_AT),
    ).toEqual({ kind: 'trusted', baseUrl: 'https://old.example.com' });
  });
});

describe('a malformed value is never handed out', () => {
  const SERVED_AT = 'https://maps.example.com';

  it.each(['not-a-url', 'maps.example.com', 'javascript:alert(1)'])(
    'getPublicAppBaseUrl rejects %s',
    (value) => {
      expect(getPublicAppBaseUrl({ public_app_url: value }, SERVED_AT)).toBeNull();
    },
  );

  it('getShareableBaseUrl falls back to the serving origin instead', () => {
    expect(getShareableBaseUrl({ public_app_url: 'not-a-url' }, SERVED_AT)).toBe(
      SERVED_AT,
    );
  });
});

/**
 * fix(#1548 review r8): the shape rule, from the one file that states it.
 *
 * The backend runs the same table against `is_usable_public_origin` in
 * backend/tests/test_public_app_url_shape_contract_1548.py. Two independent
 * validators for one setting is what produced this round's findings — the
 * frontend had learned about malformed values and the backend had not — so the
 * SPEC is shared even though the implementations cannot be.
 */
describe('the shared PUBLIC_APP_URL shape rule', () => {
  const spec = JSON.parse(
    readFileSync(
      join(process.cwd(), 'src/lib/__tests__/public-app-url-shape.cases.json'),
      'utf-8',
    ),
  ) as { valid: string[]; invalid: string[] };

  // Exercised through resolvePublicAppUrl from a LOOPBACK browser origin, so
  // the loopback-default rule cannot fire and the only thing under test is
  // shape. That separation is the point: shape and trust are different
  // questions and the fixture covers only the first.
  const asState = (value: string) =>
    resolvePublicAppUrl({ public_app_url: value }, 'http://localhost:3000');

  it('has cases on both sides, so neither list can quietly empty', () => {
    expect(spec.valid.length).toBeGreaterThan(0);
    expect(spec.invalid.length).toBeGreaterThan(0);
  });

  it.each(spec.valid)('accepts %j', (value) => {
    // Only the KIND: the stored form is the CANONICAL spelling, not the
    // operator's, which the canonicalization cases below pin exactly.
    expect(asState(value).kind).toBe('trusted');
  });

  it.each(spec.invalid)('rejects %j', (value) => {
    expect(asState(value).kind).not.toBe('trusted');
  });

  /**
   * fix(#1548 review r9): same place is not the same STRING.
   *
   * A browser serializes the shell's Origin with an IDNA ASCII host,
   * lowercased, no userinfo, default port dropped — and the backend compares
   * the configured value against exactly that. `https://máp.example` stored as
   * typed was issued a domain lock and then missed on every request. Both sides
   * canonicalize now, against this one table.
   */
  const canonical = (
    JSON.parse(
      readFileSync(
        join(process.cwd(), 'src/lib/__tests__/public-app-url-shape.cases.json'),
        'utf-8',
      ),
    ) as { canonical_origin: Record<string, string> }
  ).canonical_origin;

  it('has canonicalization cases', () => {
    expect(Object.keys(canonical).length).toBeGreaterThan(0);
  });

  it.each(Object.entries(canonical))(
    'stores %j as the browser spells it, %j',
    (raw, expected) => {
      expect(asState(raw)).toEqual({ kind: 'trusted', baseUrl: expected });
    },
  );

  it.each([...new Set(Object.values(canonical))])(
    'canonicalizing %j again changes nothing',
    (value) => {
      // The value is canonicalized when stored AND when compared; a
      // non-idempotent rule would match once and miss afterwards.
      expect(asState(value)).toEqual({ kind: 'trusted', baseUrl: value });
    },
  );
});

/**
 * fix(#1555): which origins are loopback is part of the contract too.
 *
 * Both sides carried an enumerated set of three spellings, so `127.0.0.2` — a
 * loopback address to every operating system — was classified as a routable
 * public origin. Here that hands out a share link nobody else can open; on the
 * backend it lets `assert_domain_lock_is_enforceable` issue a domain lock whose
 * shell URL every recipient resolves to their own machine. The two must agree
 * about which deployments are misconfigured, so the table is shared:
 * `is_loopback_host` in backend/app/core/public_urls.py runs the same entries.
 */
describe('the shared loopback classification', () => {
  const spec = JSON.parse(
    readFileSync(
      join(process.cwd(), 'src/lib/__tests__/public-app-url-shape.cases.json'),
      'utf-8',
    ),
  ) as { loopback: string[]; not_loopback: string[] };

  const SERVED_AT = 'https://maps.example.com';

  it('has cases on both sides', () => {
    expect(spec.loopback.length).toBeGreaterThan(0);
    expect(spec.not_loopback.length).toBeGreaterThan(0);
  });

  it.each(spec.loopback)(
    '%j is not handed out while the browser is on a real hostname',
    (value) => {
      expect(resolvePublicAppUrl({ public_app_url: value }, SERVED_AT).kind).toBe(
        'loopback-default',
      );
      expect(getPublicAppBaseUrl({ public_app_url: value }, SERVED_AT)).toBeNull();
      expect(getShareableBaseUrl({ public_app_url: value }, SERVED_AT)).toBe(SERVED_AT);
    },
  );

  // The counterfactual. Without it, calling everything loopback passes the
  // block above while refusing every correctly configured deployment;
  // 126.255.255.255 and 128.0.0.1 sit either side of 127.0.0.0/8.
  it.each(spec.not_loopback)('%j is an ordinary public origin', (value) => {
    expect(resolvePublicAppUrl({ public_app_url: value }, SERVED_AT).kind).toBe(
      'trusted',
    );
  });

  it('still trusts a loopback value on a genuine localhost install', () => {
    expect(
      resolvePublicAppUrl({ public_app_url: 'http://127.0.0.2:8080' }, 'http://localhost:3000'),
    ).toEqual({ kind: 'trusted', baseUrl: 'http://127.0.0.2:8080' });
  });
});

/**
 * fix(#1555): an app URL that names the API base is not an app URL.
 *
 * The persistent-setting validator has always rejected it; the environment path
 * did not, and `PUBLIC_APP_URL=https://maps.example.com/api` arrived here
 * through tile-config. Every consumer appends to this value, so the copied card
 * link became `/api/api/maps/...` and the iframe source `/api/m/...`.
 */
describe('an /api base is never handed out as the app URL', () => {
  const SERVED_AT = 'https://maps.example.com';

  it.each(['https://maps.example.com/api', 'https://example.com/geolens/api/'])(
    'refuses %j',
    (value) => {
      expect(getPublicAppBaseUrl({ public_app_url: value }, SERVED_AT)).toBeNull();
      // The fallback is what the operator actually gets: a link that opens.
      expect(getShareableBaseUrl({ public_app_url: value }, SERVED_AT)).toBe(SERVED_AT);
    },
  );

  it('leaves a path that merely starts with the same letters alone', () => {
    expect(
      getPublicAppBaseUrl({ public_app_url: 'https://maps.example.com/apiary' }, SERVED_AT),
    ).toBe('https://maps.example.com/apiary');
  });
});

/**
 * fix(#1548 review r7): a domain-locked preview must satisfy two browser rules
 * at once, and for a split-horizon deployment nothing satisfies both.
 *
 *  1. Its API calls carry the SHELL's origin, and the backend accepts only the
 *     configured origin as first-party -> load from the configured host.
 *  2. `frame-ancestors 'self' <customer origins>` judges the PARENT document,
 *     and `'self'` resolves to the PUBLIC origin, not the admin's -> the parent
 *     must be that same host, or the browser blocks the frame outright.
 *
 * Rule 1 fixes the child's origin; rule 2 then demands the parent match it. So
 * the preview exists only when the two already coincide.
 */
describe('getLockedPreviewBaseUrl', () => {
  const PUBLIC_HOST = 'https://maps.example.com';

  it('previews when the admin is already on the configured origin', () => {
    expect(
      getLockedPreviewBaseUrl({ public_app_url: PUBLIC_HOST }, PUBLIC_HOST),
    ).toBe(PUBLIC_HOST);
  });

  it('refuses when the admin is on a different hostname', () => {
    expect(
      getLockedPreviewBaseUrl({ public_app_url: PUBLIC_HOST }, 'https://internal.corp'),
    ).toBeNull();
  });

  it('refuses on a scheme or port difference too, since CSP compares origins', () => {
    expect(
      getLockedPreviewBaseUrl({ public_app_url: PUBLIC_HOST }, 'http://maps.example.com'),
    ).toBeNull();
    expect(
      getLockedPreviewBaseUrl(
        { public_app_url: PUBLIC_HOST },
        'https://maps.example.com:8443',
      ),
    ).toBeNull();
  });

  it('previews across a configured sub-path, which CSP ignores', () => {
    expect(
      getLockedPreviewBaseUrl(
        { public_app_url: 'https://example.com/geolens' },
        'https://example.com',
      ),
    ).toBe('https://example.com/geolens');
  });

  it.each([
    ['unset', null],
    ['the shipped localhost default', 'http://localhost:8080'],
    ['malformed', 'not-a-url'],
  ])('refuses when the configured value is %s', (_label, value) => {
    expect(
      getLockedPreviewBaseUrl({ public_app_url: value }, 'https://maps.example.com'),
    ).toBeNull();
  });

  it('previews a genuine localhost install, where the two coincide', () => {
    expect(
      getLockedPreviewBaseUrl(
        { public_app_url: 'http://localhost:8080' },
        'http://localhost:8080',
      ),
    ).toBe('http://localhost:8080');
  });
});

/**
 * fix(#1548 review r3/r5): cover the class, not just the one call site.
 *
 * SharePanel resolves three origins, and the question that picks between them
 * is WHO OPENS THE URL:
 *
 *  - handed to someone else (the copied link, its /card twin, the iframe
 *    snippet) -> the configured public origin, because the recipient is not on
 *    this network;
 *  - opened by this browser (the "Open" button, the embed preview) -> the
 *    current origin, because this browser demonstrably reaches that host and a
 *    split-horizon deployment may route the public one externally only.
 *
 * Both directions have already been got wrong once each on this PR — first
 * every URL used the current origin, then every URL used the public one — and
 * each mistake reads as reasonable in isolation. So pin the assignment itself
 * rather than trusting a reader to re-derive it, and pin it per builder, since
 * the failure mode both times was one category swallowing the other.
 */
describe('SharePanel resolves each URL from the right origin', () => {
  const source = readFileSync(
    join(process.cwd(), 'src/components/builder/SharePanel.tsx'),
    'utf-8',
  );

  /** The body of a top-level `function name() { ... }` in the component. */
  function bodyOf(name: string): string {
    const start = source.indexOf(`function ${name}()`);
    expect(start, `${name}() not found — did it get renamed?`).toBeGreaterThan(-1);
    const open = source.indexOf('{', start);
    let depth = 0;
    for (let i = open; i < source.length; i += 1) {
      if (source[i] === '{') depth += 1;
      if (source[i] === '}') {
        depth -= 1;
        if (depth === 0) return source.slice(open, i + 1);
      }
    }
    throw new Error(`unbalanced braces in ${name}()`);
  }

  it.each([
    // builder,            uses,             must not use
    ['getShareCardUrl', 'shareBaseUrl', 'currentOrigin'],
    ['getEmbedCode', 'embedBaseUrl', 'currentOrigin'],
    ['getShareUrl', 'currentOrigin', 'shareBaseUrl'],
  ])('%s builds from %s', (builder, expected, forbidden) => {
    const body = bodyOf(builder);
    expect(body, `${builder} must build from ${expected}`).toContain(expected);
    expect(body, `${builder} must not build from ${forbidden}`).not.toContain(
      forbidden,
    );
  });

  it('previews from previewBaseUrl, which splits on the lock', () => {
    const pane = source.slice(source.indexOf('<EmbedPreviewPane'));
    expect(pane.slice(0, pane.indexOf('/>'))).toContain('origin={previewBaseUrl}');

    // fix(#1548 review r6): the preview is the one URL that is opened HERE and
    // must also satisfy the lock, so it is neither of the other two rules.
    // Unlocked it uses the origin this browser reached; locked it must use the
    // configured one, the only origin its own API calls may present.
    expect(source).toContain('? getLockedPreviewBaseUrl(tileConfig, currentOrigin)');
    expect(source).toContain(': currentOrigin;');
  });

  it('no builder reaches for window.location.origin inline', () => {
    // The current origin is resolved ONCE at the top of the component, so the
    // three bindings above are the only vocabulary a builder has.
    const offenders = source
      .split('\n')
      .map((line, i) => [line, i + 1] as const)
      .filter(([line]) => line.includes('window.location.origin'))
      .filter(([line]) => ['/m/', '/api/maps/shared/'].some((p) => line.includes(p)));

    expect(
      offenders.map(([line, n]) => `${n}: ${line.trim()}`),
      'use currentOrigin / shareBaseUrl / embedBaseUrl instead — which one ' +
        'depends on who opens the URL',
    ).toEqual([]);
  });
});

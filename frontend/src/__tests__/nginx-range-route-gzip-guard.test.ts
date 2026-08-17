// fix(#1532 review r15): structural gate for edge compression of the routes
// that serve byte ranges.
//
// nginx compresses a 200 but never a 206, and when it compresses it rewrites a
// strong ETag to `W/"..."`. A route that advertises `Accept-Ranges: bytes` and
// binds its ranges to a strong ETag therefore breaks in two ways at once at the
// production edge: the client's first request returns gzipped bytes under a weak
// validator, its ranges return raw bytes under a strong one, and splicing them
// produces a file that is not the export. The weak validator also cannot
// authorize the resume at all (RFC 9110 13.1.5 requires a strong comparison).
//
// The app-level middleware disables FastAPI's INNER gzip and cannot help here:
// nginx sees the client's original Accept-Encoding and makes its own decision
// one hop further out.
//
// Nothing else exercises `nginx.conf`. The dev stack runs Vite, so the file is
// never loaded locally and no e2e run touches it. This gate is a text check,
// which means it cannot prove nginx's behaviour, only that the block that
// produces it is still present and still covers these routes. The behaviour
// itself was measured against a real `nginx:alpine` running this exact conf.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

const CONF = readFileSync(resolve(__dirname, '../../nginx.conf'), 'utf-8');

// Routes that serve byte ranges bound to a strong ETag. ADD TO THIS LIST when a
// route starts serving ranges; the point of the list is that a new one has to
// make a decision rather than inherit whatever gzip_types happens to say.
const RANGE_SERVING_PATHS = [
  '/api/datasets/0f8c1a2e-1111-2222-3333-444455556666/export',
  '/api/datasets/0f8c1a2e-1111-2222-3333-444455556666/download/cog',
];

// Routes that serve exactly one representation and no ranges. They must KEEP
// compressing: #1540 fixed this same splice by excluding a media type, and
// #1532 r11 had to undo that when it silenced compression on unrelated JSON and
// CSV endpoints. Without these, "turn gzip off everywhere" passes the test.
const COMPRESSIBLE_PATHS = [
  '/api/collections/roads/items',
  '/api/datasets/0f8c1a2e-1111-2222-3333-444455556666/records',
  '/api/admin/audit/export.csv',
];

/**
 * Every `location ~ <regex> { ... }` block in the conf that contains
 * `gzip off`, as a compiled regex.
 *
 * Brace-counted rather than matched with a single regex, because the blocks
 * nest: the export location lives inside `location /api/`, and a lazy `{[^}]*}`
 * would stop at the first inner brace and read the wrong body.
 */
function gzipOffLocationPatterns(): RegExp[] {
  const patterns: RegExp[] = [];
  const header = /location\s+~\s+(\S+)\s*\{/g;
  let match: RegExpExecArray | null;

  while ((match = header.exec(CONF)) !== null) {
    let depth = 1;
    let i = header.lastIndex;
    while (i < CONF.length && depth > 0) {
      if (CONF[i] === '{') depth += 1;
      else if (CONF[i] === '}') depth -= 1;
      i += 1;
    }
    const body = CONF.slice(header.lastIndex, i - 1);
    // Only this block's own directives, not a nested location's.
    const own = body.replace(/location\s+[^{]*\{[\s\S]*?\}/g, '');
    if (/^\s*gzip\s+off\s*;/m.test(own)) {
      patterns.push(new RegExp(match[1]));
    }
  }
  return patterns;
}

describe('nginx range-route gzip guard', () => {
  const patterns = gzipOffLocationPatterns();

  it('has at least one location that turns gzip off', () => {
    expect(patterns.length).toBeGreaterThan(0);
  });

  it.each(RANGE_SERVING_PATHS)('serves %s uncompressed at the edge', (path) => {
    const covered = patterns.some((p) => p.test(path));
    expect(
      covered,
      `${path} serves byte ranges bound to a strong ETag, but no nginx location ` +
        `with 'gzip off' matches it. At the production edge its 200 can come ` +
        `back gzipped under a weakened ETag while its 206 is raw, which is two ` +
        `different byte sequences under one URL.`
    ).toBe(true);
  });

  it.each(COMPRESSIBLE_PATHS)('still compresses %s', (path) => {
    const suppressed = patterns.find((p) => p.test(path));
    expect(
      suppressed,
      `${path} serves one representation and no ranges, so turning gzip off ` +
        `for it costs bandwidth and buys nothing. Matched by ${suppressed}.`
    ).toBeUndefined();
  });

  it('lists application/geo+json in gzip_types, which is why this matters', () => {
    // The counterfactual for the whole file. If the edge compressed nothing,
    // the assertions above would pass against a conf with no protection at all.
    const gzipTypes = /gzip_types([\s\S]*?);/.exec(CONF)?.[1] ?? '';
    expect(
      gzipTypes,
      'no compressible export media type is listed at the edge, so the ' +
        'gzip-off block above is not load-bearing and these tests prove nothing'
    ).toContain('application/geo+json');
  });
});

// Guards the coupling between the in-app "Report a problem" wizard and the
// GitHub Issue Form it prefills. Issue Forms silently ignore query params that
// don't exactly match a field id, and dropdowns only prefill on an exact
// option string — so drift in bug_report.yml degrades the wizard to a
// partially blank form with no error anywhere. This test makes that drift a
// CI failure instead.

// @types/node is already a devDependency (vite.config.ts tooling); this
// reference admits it here so the test can read a file OUTSIDE frontend/ —
// which vite's fs sandbox denies to ?raw imports.
/// <reference types="node" />
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { ISSUE_AREAS } from '../build-issue';

// Vitest runs with cwd = frontend/ (import.meta.url is http-scheme under
// jsdom, so it can't anchor a relative path). An ENOENT here means the
// template moved — also worth failing on.
const template = readFileSync(
  resolve(process.cwd(), '../.github/ISSUE_TEMPLATE/bug_report.yml'),
  'utf8',
);

// ponytail: line-based extraction, not a YAML parser — no yaml dep exists in
// package.json, and the template's shape is stable enough that a shape change
// failing this test IS the alert we want.
function extractFieldIds(yml: string): string[] {
  return [...yml.matchAll(/^\s*id:\s*(\S+)\s*$/gm)].map((m) => m[1]);
}

function extractAreaOptions(yml: string): string[] {
  const lines = yml.split('\n');
  const options: string[] = [];
  let inArea = false;
  let inOptions = false;
  for (const line of lines) {
    if (/^\s*id:\s*area\s*$/.test(line)) inArea = true;
    if (inArea && /^\s*options:\s*$/.test(line)) {
      inOptions = true;
      continue;
    }
    if (inOptions) {
      const item = line.match(/^\s+-\s+(.+?)\s*$/);
      if (!item) break; // end of the options list (validations: etc.)
      options.push(item[1]);
    }
  }
  return options;
}

describe('bug_report.yml parity with the in-app reporter', () => {
  it('every query param the wizard prefills matches a form field id', () => {
    const ids = extractFieldIds(template);
    expect(ids.length).toBeGreaterThan(0);
    // Mirrors compose() in build-issue.ts. `title` is absent by design: it is
    // GitHub's issue-title param, not an Issue Form field.
    for (const param of ['description', 'steps', 'expected', 'area', 'version', 'context']) {
      expect(ids).toContain(param);
    }
  });

  it('ISSUE_AREAS matches the area dropdown options exactly', () => {
    expect(extractAreaOptions(template)).toEqual([...ISSUE_AREAS]);
  });
});

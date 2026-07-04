import { describe, it, expect } from 'vitest';
import {
  buildClipboardReport,
  buildContext,
  buildIssueUrl,
  buildTechnicalClipboard,
  mapAreaFromPath,
  summarizeEntries,
} from '../build-issue';
import type { ReportEntry } from '../report-buffer';

function entry(partial: Partial<ReportEntry> = {}): ReportEntry {
  return { id: '1', ts: 0, severity: 'error', source: 'console', message: 'x', count: 1, ...partial };
}

describe('mapAreaFromPath', () => {
  it('maps map routes to Map Builder', () => {
    expect(mapAreaFromPath('/maps/abc123')).toBe('Map Builder');
  });
  it('maps share routes to Sharing / Embed', () => {
    expect(mapAreaFromPath('/m/sometoken')).toBe('Sharing / Embed');
  });
  it('maps the catalog root to Search / Catalog', () => {
    expect(mapAreaFromPath('/')).toBe('Search / Catalog');
  });
  it('falls back to Other', () => {
    expect(mapAreaFromPath('/settings')).toBe('Other');
  });
});

describe('buildIssueUrl', () => {
  it('prefills GitHub Issue Form field ids, never &body=', () => {
    const { url, truncated } = buildIssueUrl({
      title: 'T',
      description: 'D',
      steps: 'S',
      expected: 'E',
      area: 'Map Builder',
      version: '2.0.0',
      context: 'C',
    });
    expect(truncated).toBe(false);
    expect(url).toContain('template=bug_report.yml');
    expect(url).toContain('title=T');
    expect(url).toContain('description=D');
    expect(url).toContain('steps=S');
    expect(url).toContain('expected=E');
    expect(url).toContain('area=Map+Builder');
    expect(url).toContain('version=2.0.0');
    expect(url).toContain('context=C');
    expect(url).not.toContain('body=');
  });

  it('drops the context block and flags truncation when the URL is too long', () => {
    const context = 'x'.repeat(9000);
    const { url, truncated } = buildIssueUrl({
      title: 'T',
      description: 'D',
      steps: '',
      expected: '',
      area: 'Other',
      version: '',
      context,
    });
    expect(truncated).toBe(true);
    expect(url).not.toContain('context=');
    expect(url).toContain('description=D');
  });

  it('redacts secrets pasted into the user-provided fields', () => {
    const { url } = buildIssueUrl({
      title: 'crash',
      description: 'failing call api_key=PASTEDSECRET happened',
      steps: '',
      expected: '',
      area: 'Other',
      version: '',
      context: '',
    });
    const decoded = decodeURIComponent(url);
    expect(decoded).not.toContain('PASTEDSECRET');
    expect(decoded).toContain('api_key=[redacted]');
  });

  it('stays under the limit even when the user text alone is too long', () => {
    const huge = 'A'.repeat(9000);
    const { url, truncated } = buildIssueUrl({
      title: 'T',
      description: huge,
      steps: '',
      expected: '',
      area: 'Other',
      version: '',
      context: '',
    });
    expect(truncated).toBe(true);
    expect(url.length).toBeLessThanOrEqual(7000);
    expect(url).toContain('template=bug_report.yml');
  });
});

describe('buildContext', () => {
  it('redacts credentials in the page URL', () => {
    const ctx = buildContext({
      entries: [],
      includeErrors: false,
      includeEnv: false,
      includePage: true,
      pageUrl: 'https://app.example/maps/1?api_key=SUPERSECRET',
      userAgent: '',
      screen: '',
      language: 'en',
    });
    expect(ctx).not.toContain('SUPERSECRET');
    expect(ctx).toContain('[redacted]');
  });

  it('includes a captured-signals table when errors are present', () => {
    const ctx = buildContext({
      entries: [entry({ message: 'kaboom', source: 'maplibre' })],
      includeErrors: true,
      includeEnv: false,
      includePage: false,
      pageUrl: '',
      userAgent: '',
      screen: '',
      language: 'en',
    });
    expect(ctx).toContain('Captured signals');
    expect(ctx).toContain('kaboom');
    expect(ctx).toContain('maplibre');
  });

  it('omits the signals table when includeErrors is off', () => {
    const ctx = buildContext({
      entries: [entry({ message: 'hidden' })],
      includeErrors: false,
      includeEnv: false,
      includePage: false,
      pageUrl: '',
      userAgent: '',
      screen: '',
      language: 'en',
    });
    expect(ctx).not.toContain('hidden');
  });
});

describe('summarizeEntries', () => {
  it('returns a placeholder when there are no entries', () => {
    expect(summarizeEntries([])).toContain('No console');
  });
  it('marks suppressed entries and collapses counts', () => {
    const summary = summarizeEntries([entry({ message: 'tile 404', suppressed: true, count: 3 })]);
    expect(summary).toContain('(suppressed)');
    expect(summary).toContain('×3');
  });
});

describe('buildTechnicalClipboard', () => {
  it('includes the heading, version, and context', () => {
    const md = buildTechnicalClipboard({ version: '1.4.2', context: '- **Page:** /maps' });
    expect(md).toContain('## GeoLens technical details');
    expect(md).toContain('**GeoLens version:** 1.4.2');
    expect(md).toContain('- **Page:** /maps');
  });

  it('omits empty version and context blocks', () => {
    const md = buildTechnicalClipboard({ version: '', context: '' });
    expect(md).toBe('## GeoLens technical details');
  });
});

describe('buildClipboardReport', () => {
  it('assembles a full markdown report', () => {
    const md = buildClipboardReport({
      title: 'Bug',
      description: 'D',
      steps: 'S',
      expected: 'E',
      area: 'Map Builder',
      version: '2.0.0',
      context: 'CTX',
    });
    expect(md).toContain('# Bug');
    expect(md).toContain('Map Builder');
    expect(md).toContain('## Describe the bug');
    expect(md).toContain('## Steps to reproduce');
    expect(md).toContain('CTX');
  });
});

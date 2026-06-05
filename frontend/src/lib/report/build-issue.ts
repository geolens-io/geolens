// Assembles a captured report into a pre-filled GitHub issue.
//
// The repo's bug template (.github/ISSUE_TEMPLATE/bug_report.yml) is a GitHub
// *Issue Form*. Issue Forms ignore the legacy &body= param — fields prefill
// ONLY by query params matching their field ids (description / steps / expected
// / area / version / context). &title= still sets the issue title. Get this
// wrong and the form opens blank.
//
// GitHub caps issue-create URLs (~8KB before the server rejects). We keep the
// link comfortably under that; if the technical context pushes it over, we drop
// &context= from the link and the caller copies the full report to the clipboard
// instead, so the link always opens.

import { GEOLENS_BUG_REPORT_URL } from '@/lib/external-links';
import { redact } from './redact';
import type { ReportEntry } from './report-buffer';

/** Exact option strings from the bug_report.yml `area` dropdown. */
export const ISSUE_AREAS = [
  'Search / Catalog',
  'Dataset Detail',
  'Map Builder',
  'Collections',
  'Import / Ingestion',
  'Admin Panel',
  'Sharing / Embed',
  'Tiles / Rendering',
  'Auth / Permissions',
  'API / OGC',
  'Other',
] as const;
export type IssueArea = (typeof ISSUE_AREAS)[number];

/** Keep the deep link well under GitHub's ~8KB ceiling. */
const MAX_URL_LENGTH = 7000;

const SEVERITY_ICON: Record<ReportEntry['severity'], string> = {
  error: '🔴',
  warning: '🟡',
  info: '🔵',
};

/** Best-effort default for the Area dropdown from the current route. */
export function mapAreaFromPath(pathname: string): IssueArea {
  const path = pathname.toLowerCase();
  if (path.startsWith('/m/')) return 'Sharing / Embed';
  if (path.startsWith('/maps')) return 'Map Builder';
  if (path.startsWith('/datasets')) return 'Dataset Detail';
  if (path.startsWith('/collections')) return 'Collections';
  if (path.startsWith('/import')) return 'Import / Ingestion';
  if (path.startsWith('/admin')) return 'Admin Panel';
  if (path.startsWith('/settings')) return 'Other';
  if (path === '/' || path.startsWith('/search')) return 'Search / Catalog';
  return 'Other';
}

function escapePipes(text: string): string {
  return text.replace(/\|/g, '\\|').replace(/\n/g, ' ');
}

/** Human-readable markdown table of the most recent captured entries. */
export function summarizeEntries(entries: ReportEntry[], limit = 12): string {
  if (entries.length === 0) {
    return '_No console, network, or map errors were captured automatically._';
  }
  const rows = entries.slice(0, limit).map((entry) => {
    const count = entry.count > 1 ? ` ×${entry.count}` : '';
    const flag = entry.suppressed ? ' _(suppressed)_' : '';
    return `| ${SEVERITY_ICON[entry.severity]} | \`${entry.source}\` | ${escapePipes(entry.message)}${count}${flag} |`;
  });
  const more =
    entries.length > limit ? `\n\n_…and ${entries.length - limit} more captured ${entries.length - limit === 1 ? 'entry' : 'entries'}._` : '';
  return `| | Source | Message |\n| --- | --- | --- |\n${rows.join('\n')}${more}`;
}

function entriesDetailBlock(entries: ReportEntry[], limit = 30): string {
  return entries
    .slice(0, limit)
    .map((entry) => {
      const count = entry.count > 1 ? ` ×${entry.count}` : '';
      const flag = entry.suppressed ? ' (suppressed)' : '';
      const head = `[${entry.severity}] (${entry.source}) ${entry.message}${count}${flag}`;
      return entry.detail ? `${head}\n${entry.detail}` : head;
    })
    .join('\n\n');
}

export interface ReportContextOptions {
  entries: ReportEntry[];
  includeErrors: boolean;
  includeEnv: boolean;
  includePage: boolean;
  pageUrl: string;
  userAgent: string;
  screen: string;
  language: string;
}

/** Builds the markdown for the issue's "Additional context" field. */
export function buildContext(options: ReportContextOptions): string {
  const env: string[] = [];
  if (options.includePage && options.pageUrl) {
    env.push(`- **Page:** ${redact(options.pageUrl)}`);
  }
  if (options.includeEnv) {
    if (options.userAgent) env.push(`- **Browser:** ${options.userAgent}`);
    if (options.screen) env.push(`- **Viewport:** ${options.screen}`);
    if (options.language) env.push(`- **Language:** ${options.language}`);
  }

  const parts: string[] = [];
  if (env.length) parts.push(env.join('\n'));

  if (options.includeErrors && options.entries.length) {
    parts.push(`**Captured signals (${options.entries.length})**\n\n${summarizeEntries(options.entries)}`);
    const detail = entriesDetailBlock(options.entries);
    if (detail) {
      parts.push(`<details>\n<summary>Full technical detail</summary>\n\n\`\`\`\n${detail}\n\`\`\`\n</details>`);
    }
  }

  return parts.join('\n\n');
}

export interface BuildIssueParams {
  title: string;
  description: string;
  steps: string;
  expected: string;
  area: string;
  version: string;
  context: string;
  baseUrl?: string;
}

/**
 * Build the pre-filled GitHub Issue Form URL. Returns `truncated: true` when the
 * context block had to be dropped to keep the URL under GitHub's limit — the
 * caller should then copy the full report to the clipboard.
 */
export function buildIssueUrl(params: BuildIssueParams): { url: string; truncated: boolean } {
  const base = params.baseUrl ?? GEOLENS_BUG_REPORT_URL;

  const compose = (includeContext: boolean): string => {
    const search = new URLSearchParams();
    if (params.title) search.set('title', params.title);
    if (params.description) search.set('description', params.description);
    if (params.steps) search.set('steps', params.steps);
    if (params.expected) search.set('expected', params.expected);
    if (params.area) search.set('area', params.area);
    if (params.version) search.set('version', params.version);
    if (includeContext && params.context) search.set('context', params.context);
    // base already carries `?template=bug_report.yml`, so append with `&`.
    return `${base}&${search.toString()}`;
  };

  const full = compose(true);
  if (full.length <= MAX_URL_LENGTH) {
    return { url: full, truncated: false };
  }
  return { url: compose(false), truncated: true };
}

export interface ClipboardReportParams {
  title: string;
  description: string;
  steps: string;
  expected: string;
  area: string;
  version: string;
  context: string;
}

/** Full markdown report for the "Copy report" action and the truncation fallback. */
export function buildClipboardReport(params: ClipboardReportParams): string {
  const sections: string[] = [];
  sections.push(`# ${params.title || 'Bug report'}`);
  const meta: string[] = [];
  if (params.area) meta.push(`**Area:** ${params.area}`);
  if (params.version) meta.push(`**GeoLens version:** ${params.version}`);
  if (meta.length) sections.push(meta.join('  \n'));
  if (params.description) sections.push(`## Describe the bug\n\n${params.description}`);
  if (params.steps) sections.push(`## Steps to reproduce\n\n${params.steps}`);
  if (params.expected) sections.push(`## Expected behavior\n\n${params.expected}`);
  if (params.context) sections.push(`## Additional context\n\n${params.context}`);
  return sections.join('\n\n');
}

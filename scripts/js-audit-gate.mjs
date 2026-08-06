#!/usr/bin/env node
// npm-audit gate with a scoped allowlist — the JS twin of .trivyignore.yaml
// (npm audit has no native ignore mechanism). Runs `npm audit --json` in the
// current working directory and fails on any high/critical advisory that is
// not explicitly allowlisted below. Every entry needs a reason and an expiry;
// an expired entry stops suppressing, forcing a revisit.
import { execFileSync } from 'node:child_process';

const ALLOWLIST = [];

let raw;
try {
  raw = execFileSync('npm', ['audit', '--json'], {
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  });
} catch (err) {
  // npm audit exits non-zero when any vulnerability exists; the JSON report is
  // still on stdout. Anything without stdout is a real npm failure.
  if (!err.stdout) throw err;
  raw = err.stdout;
}
const report = JSON.parse(raw);

// Fail closed on anything that is not a real audit report. When the registry is
// unreachable (outage, egress proxy, rate limit) npm still exits non-zero and
// still writes JSON to stdout — but that JSON is `{"message": ..., "error": ...}`
// with no `vulnerabilities` key. The scan loop below reads
// `report.vulnerabilities ?? {}`, so it would iterate nothing, print the success
// line, and exit 0 — reporting a clean supply chain on a scan that never ran.
const noReport =
  report.error || typeof report.vulnerabilities !== 'object' || report.vulnerabilities === null;
if (noReport) {
  console.error(
    'npm audit did not produce a report:',
    report.message ?? JSON.stringify(report.error ?? report).slice(0, 500),
  );
  process.exit(1);
}

const today = new Date().toISOString().slice(0, 10);
const active = new Map(
  ALLOWLIST.filter((e) => e.expires >= today).map((e) => [e.id, e]),
);
for (const e of ALLOWLIST.filter((e) => e.expires < today)) {
  console.error(`allowlist entry ${e.id} expired ${e.expires} — no longer suppressed`);
}

// Advisories live in `via` objects on the directly-vulnerable package; string
// entries are transitive references rooted at one of those objects, so
// checking the objects alone covers the whole tree.
const failing = new Map();
const matched = new Set();
for (const vuln of Object.values(report.vulnerabilities ?? {})) {
  for (const via of vuln.via ?? []) {
    if (typeof via !== 'object') continue;
    if (via.severity !== 'high' && via.severity !== 'critical') continue;
    const id = (via.url ?? '').split('/').pop() ?? '';
    if (active.has(id)) {
      matched.add(id);
      console.log(`allowlisted ${via.severity}: ${via.name} — ${via.title} (${id}, expires ${active.get(id).expires})`);
    } else {
      failing.set(id || `${via.name}: ${via.title}`, via);
    }
  }
}

// fix(#1181): an entry whose advisory stopped firing is dead weight carrying a
// justification that quietly goes out of date — this one claimed "1.1.16 is the
// last of the 1.x line (unpatched)" months after 1.1.18 shipped. Warn, never
// block: an advisory can legitimately stop appearing on one lockfile state.
for (const [id, entry] of active) {
  if (!matched.has(id)) {
    console.warn(`allowlist entry ${id} matched no advisory — delete it (expires ${entry.expires})`);
  }
}

if (failing.size > 0) {
  for (const [id, via] of failing) {
    console.error(`BLOCKING ${via.severity}: ${via.name} — ${via.title} (${id})`);
  }
  process.exit(1);
}
console.log('npm audit gate: no unallowlisted high/critical advisories.');

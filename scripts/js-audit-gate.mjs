#!/usr/bin/env node
// npm-audit gate with a scoped allowlist — the JS twin of .trivyignore.yaml
// (npm audit has no native ignore mechanism). Runs `npm audit --json` in the
// current working directory and fails on any high/critical advisory that is
// not explicitly allowlisted below. Every entry needs a reason and an expiry;
// an expired entry stops suppressing, forcing a revisit.
import { execFileSync } from 'node:child_process';

const ALLOWLIST = [
  {
    id: 'GHSA-qwww-vcr4-c8h2', // react-router RSC-mode CSRF (high)
    reason:
      'Vulnerable code is react-router’s RSC server runtime; the frontend is a ' +
      'Vite SPA using library-mode <BrowserRouter> (frontend/src/main.tsx) — no ' +
      'RSC entry point exists, so the vulnerable code never executes. No patched ' +
      '7.x exists yet (the only fix is the 8.3.0 major). Drop this entry when a ' +
      '7.x backport ships or the router is upgraded to >=8.3.0.',
    expires: '2026-09-01',
  },
];

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
for (const vuln of Object.values(report.vulnerabilities ?? {})) {
  for (const via of vuln.via ?? []) {
    if (typeof via !== 'object') continue;
    if (via.severity !== 'high' && via.severity !== 'critical') continue;
    const id = (via.url ?? '').split('/').pop() ?? '';
    if (active.has(id)) {
      console.log(`allowlisted ${via.severity}: ${via.name} — ${via.title} (${id}, expires ${active.get(id).expires})`);
    } else {
      failing.set(id || `${via.name}: ${via.title}`, via);
    }
  }
}

if (failing.size > 0) {
  for (const [id, via] of failing) {
    console.error(`BLOCKING ${via.severity}: ${via.name} — ${via.title} (${id})`);
  }
  process.exit(1);
}
console.log('npm audit gate: no unallowlisted high/critical advisories.');

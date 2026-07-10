/**
 * ARC-02: generate src/types/api.generated.ts from backend/openapi.json.
 *
 * The frontend's backend-boundary types were hand-maintained in src/types/api.ts
 * (1,803 LOC, 149 importers) with no codegen guard, so any backend schema change
 * surfaced as a runtime bug rather than a compile error. This regenerates a typed
 * mirror straight from the OpenAPI snapshot, exactly like the SDKs do.
 *
 * Pipeline (mirrors the `sdks` Make target):
 *   1. flatten_openapi_defs.py rewrites pydantic's local `#/$defs/X` refs to
 *      `#/components/schemas/X` — openapi-typescript (redocly) can't resolve the
 *      `#/$defs/` form and errors out on the raw snapshot.
 *   2. openapi-typescript (pinned) emits the typed mirror.
 *
 * openapi-typescript is invoked via pinned `npx`, not a devDependency: its latest
 * (7.13.0) declares peer `typescript@^5` while this project is on typescript@6,
 * and the repo already runs its codegen tools this way (see the `sdks` target's
 * `uvx openapi-python-client@…` / `npx --yes @hey-api/openapi-ts@…`).
 *
 * Usage:
 *   npm run types:generate      # regenerate in place
 *   npm run types:check         # regenerate + fail on drift (CI gate)
 */

import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const OPENAPI_TS_VERSION = '7.13.0';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND_ROOT = path.resolve(__dirname, '..');
const REPO_ROOT = path.resolve(FRONTEND_ROOT, '..');
const OUTPUT = path.join('src', 'types', 'api.generated.ts');

const tmpDir = mkdtempSync(path.join(os.tmpdir(), 'geolens-api-types-'));
const flat = path.join(tmpDir, 'openapi-flat.json');

try {
  // 1. flatten $defs refs (Python tool, shared with the SDK pipeline)
  execFileSync(
    'uv',
    [
      'run',
      '--no-project',
      'python',
      'scripts/flatten_openapi_defs.py',
      '--input',
      'backend/openapi.json',
      '--output',
      flat,
    ],
    { cwd: REPO_ROOT, stdio: 'inherit' },
  );

  // 2. emit the typed mirror
  execFileSync(
    'npx',
    ['--yes', `openapi-typescript@${OPENAPI_TS_VERSION}`, flat, '-o', OUTPUT],
    { cwd: FRONTEND_ROOT, stdio: 'inherit' },
  );
} finally {
  rmSync(tmpDir, { recursive: true, force: true });
}

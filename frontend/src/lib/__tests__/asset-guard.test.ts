// fix(#1515): public/asset-guard.js ships in the shell as a plain <script>, so
// nothing imports it and nothing covered it. It is also the half that produced
// the flood: under an opaque origin `sessionStorage` THROWS, and reloading from
// the catch bypassed the latch entirely.
//
// The file is read and evaluated here rather than reimplemented, so the test
// fails if the shipped guard regresses.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const GUARD_SOURCE = readFileSync(
  resolve(__dirname, '../../../public/asset-guard.js'),
  'utf-8'
);

const reload = vi.fn();

type ListenerArgs = Parameters<typeof window.addEventListener>;
let installed: ListenerArgs | null = null;

/**
 * Evaluate the shipped guard and remember the listener it registers, so each
 * test starts from one live listener instead of accumulating them.
 */
function installGuard(): void {
  const spy = vi.spyOn(window, 'addEventListener');
  new Function(GUARD_SOURCE)();
  installed = spy.mock.calls.at(-1) as ListenerArgs;
  spy.mockRestore();
}

/** Opaque-origin storage: reading the property throws, per the browser. */
function denyStorage(): () => void {
  const original = Object.getOwnPropertyDescriptor(window, 'sessionStorage');
  const descriptor: PropertyDescriptor = {
    configurable: true,
    get() {
      throw new DOMException(
        "Failed to read the 'sessionStorage' property from 'Window': The document " +
          "is sandboxed and lacks the 'allow-same-origin' flag.",
        'SecurityError'
      );
    },
  };
  Object.defineProperty(window, 'sessionStorage', descriptor);
  if (globalThis !== (window as unknown as typeof globalThis)) {
    Object.defineProperty(globalThis, 'sessionStorage', descriptor);
  }
  return () => {
    if (original) {
      Object.defineProperty(window, 'sessionStorage', original);
      if (globalThis !== (window as unknown as typeof globalThis)) {
        Object.defineProperty(globalThis, 'sessionStorage', original);
      }
    }
  };
}

/**
 * Fire the error event a blocked/404 hashed asset produces.
 *
 * The src is RELATIVE, matching what the shell actually emits, and the guard
 * reads `el.src`, which the DOM resolves against the document base. An absolute
 * `http://` literal here worked equally well but tripped CodeQL's
 * "script loaded using unencrypted connection" rule on a test fixture.
 */
function failAsset(url = '/assets/index-abc123.js'): void {
  const el = document.createElement('script');
  el.setAttribute('src', url);
  document.body.appendChild(el);
  el.dispatchEvent(new Event('error'));
  el.remove();
}

beforeEach(() => {
  sessionStorage.clear();
  reload.mockClear();
  Object.defineProperty(window, 'location', {
    value: { ...window.location, reload },
    writable: true,
    configurable: true,
  });
  installGuard();
});

afterEach(() => {
  if (installed) {
    window.removeEventListener(...installed);
    installed = null;
  }
});

describe('asset-guard.js', () => {
  it('reloads once for a failed hashed asset and latches repeats', () => {
    failAsset();
    failAsset();
    failAsset();
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it('ignores failures that are not hashed assets', () => {
    failAsset('/some-other-script.js');
    expect(reload).not.toHaveBeenCalled();
  });

  it('does not reload when the latch is unreachable (#1515)', () => {
    const restore = denyStorage();
    try {
      failAsset();
      failAsset();
      failAsset();
      expect(reload).not.toHaveBeenCalled();
    } finally {
      restore();
    }
  });
});

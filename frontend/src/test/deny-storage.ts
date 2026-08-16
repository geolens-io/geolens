/**
 * Deny `sessionStorage` the way a browser denies it.
 *
 * In a frame with an opaque origin (sandboxed without `allow-same-origin`),
 * in private-mode Safari, and with third-party storage blocked, it is the
 * PROPERTY ACCESS that raises — `window.sessionStorage` throws a SecurityError
 * before any `getItem`/`setItem` call is reached.
 *
 * That is why stubbing the store (`vi.stubGlobal('sessionStorage', {...})`) or
 * mocking `getItem` to return null proves nothing about this failure: those
 * mocks answer a call the broken code never gets to make, and a
 * `typeof sessionStorage !== 'undefined'` guard passes in every one of these
 * contexts because the property does exist.
 *
 * Returns a restore function; call it in a `finally` or `afterEach`.
 */
function replaceSessionStorage(descriptor: PropertyDescriptor): () => void {
  const original = Object.getOwnPropertyDescriptor(window, 'sessionStorage');
  Object.defineProperty(window, 'sessionStorage', descriptor);
  if (globalThis !== (window as unknown as typeof globalThis)) {
    Object.defineProperty(globalThis, 'sessionStorage', descriptor);
  }
  return () => {
    if (!original) return;
    Object.defineProperty(window, 'sessionStorage', original);
    if (globalThis !== (window as unknown as typeof globalThis)) {
      Object.defineProperty(globalThis, 'sessionStorage', original);
    }
  };
}

/**
 * A store that WORKS but is full: reads and removes succeed, and `setItem`
 * throws QuotaExceededError for anything longer than `maxValueLength`.
 *
 * This is a different failure from denial and it has to be tested separately,
 * because it is the only one where a PREVIOUS value is still sitting in the
 * store when the new write fails. Denial has nothing persisted to go stale.
 *
 * Returns a restore function; call it in a `finally` or `afterEach`.
 */
export function limitSessionStorage(maxValueLength: number): () => void {
  const backing = new Map<string, string>();
  const store: Storage = {
    get length() {
      return backing.size;
    },
    clear: () => backing.clear(),
    getItem: (key: string) => backing.get(key) ?? null,
    key: (index: number) => [...backing.keys()][index] ?? null,
    removeItem: (key: string) => {
      backing.delete(key);
    },
    setItem: (key: string, value: string) => {
      if (value.length > maxValueLength) {
        throw new DOMException(
          `Setting the value of '${key}' exceeded the quota.`,
          'QuotaExceededError',
        );
      }
      backing.set(key, value);
    },
  };
  return replaceSessionStorage({ configurable: true, get: () => store });
}

export function denySessionStorage(): () => void {
  return replaceSessionStorage({
    configurable: true,
    get() {
      throw new DOMException(
        "Failed to read the 'sessionStorage' property from 'Window': The document " +
          "is sandboxed and lacks the 'allow-same-origin' flag.",
        'SecurityError',
      );
    },
  });
}

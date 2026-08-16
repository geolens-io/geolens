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
export function denySessionStorage(): () => void {
  const original = Object.getOwnPropertyDescriptor(window, 'sessionStorage');
  const descriptor: PropertyDescriptor = {
    configurable: true,
    get() {
      throw new DOMException(
        "Failed to read the 'sessionStorage' property from 'Window': The document " +
          "is sandboxed and lacks the 'allow-same-origin' flag.",
        'SecurityError',
      );
    },
  };
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

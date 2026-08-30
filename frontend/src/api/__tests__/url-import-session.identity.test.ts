/**
 * fix(#1708 codex r23): the URL-import session is scoped to an identity.
 *
 * Module state lives for the lifetime of the SPA, so a logout followed by a
 * login WITHOUT a page reload used to leave the session alive and attach the
 * next user to the previous user's in-flight import and job id.
 */
import type { UserResponse } from '@/types/api';
import { useAuthStore } from '@/stores/auth-store';
import {
  clearUrlImport,
  peekUrlImport,
  startUrlImport,
} from '@/api/url-import-session';

const mockUploadFromUrl = vi.fn();
vi.mock('@/api/ingest', () => ({
  uploadFromUrl: (...args: unknown[]) => mockUploadFromUrl(...args),
}));

function signIn(id: string | null) {
  useAuthStore.setState({
    user: id === null ? null : ({ id } as UserResponse),
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  clearUrlImport();
  signIn(null);
  // Never leave a rejection unhandled when a test discards a session.
  mockUploadFromUrl.mockReturnValue(new Promise(() => {}));
});

afterEach(() => {
  clearUrlImport();
  signIn(null);
});

describe('url-import session identity scoping', () => {
  test('the owner is captured when the import starts', () => {
    signIn('user-a');
    startUrlImport('https://files.example.test/a.geojson');
    expect(peekUrlImport()?.ownerId).toBe('user-a');
  });

  test('a different identity cannot adopt the session, and it is cleared', () => {
    signIn('user-a');
    startUrlImport('https://files.example.test/a.geojson');
    expect(peekUrlImport()).not.toBeNull();

    // User B signs in without a page reload — the module survived, so the
    // ownership check is what has to refuse.
    signIn('user-b');
    expect(peekUrlImport()).toBeNull();

    // Cleared, not merely hidden: user A signing back in must not find a
    // job whose staging the intervening identity could have touched.
    signIn('user-a');
    expect(peekUrlImport()).toBeNull();
  });

  test('an identity change clears the session promptly, without waiting for a mount', () => {
    signIn('user-a');
    startUrlImport('https://files.example.test/a.geojson');

    // The subscription fires on the store change itself.
    signIn('user-b');
    // Read through the raw module state by asking as user A again: if the
    // subscription had not fired, the session would still exist.
    signIn('user-a');
    expect(peekUrlImport()).toBeNull();
  });

  test('logout clears the session', () => {
    signIn('user-a');
    startUrlImport('https://files.example.test/a.geojson');
    expect(peekUrlImport()).not.toBeNull();

    signIn(null);
    expect(peekUrlImport()).toBeNull();
  });

  test('an anonymous session is not adoptable once signed in', () => {
    signIn(null);
    startUrlImport('https://files.example.test/anon.geojson');
    expect(peekUrlImport()?.ownerId).toBeNull();

    signIn('user-a');
    expect(peekUrlImport()).toBeNull();
  });

  test('the same identity still resumes its own import', () => {
    signIn('user-a');
    const session = startUrlImport('https://files.example.test/a.geojson');
    expect(peekUrlImport()).toBe(session);
    // A token refresh changes the token, not the identity, so an import in
    // flight must survive it.
    useAuthStore.setState({ token: 'rotated-token' });
    expect(peekUrlImport()).toBe(session);
  });
});

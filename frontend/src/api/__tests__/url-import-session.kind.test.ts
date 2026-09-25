/** The URL-import session is keyed by its upload kind, so only the same URL, filename and kind re-adopt it. */
import { clearUrlImport, peekUrlImport, startUrlImport } from '@/api/url-import-session';

const mockUploadFromUrl = vi.fn();
vi.mock('@/api/ingest', () => ({
  uploadFromUrl: (...args: unknown[]) => mockUploadFromUrl(...args),
}));

const URL = 'https://files.example.test/campus.zip';

beforeEach(() => {
  vi.clearAllMocks();
  clearUrlImport();
  mockUploadFromUrl.mockReturnValue(new Promise(() => {}));
});

afterEach(() => {
  clearUrlImport();
});

describe('url-import session kind', () => {
  test('the same URL, filename and kind re-adopt the running session', () => {
    const first = startUrlImport(URL, undefined, 'tiles3d');
    const second = startUrlImport(URL, undefined, 'tiles3d');

    expect(second).toBe(first);
    expect(mockUploadFromUrl).toHaveBeenCalledTimes(1);
    expect(peekUrlImport()?.kind).toBe('tiles3d');
  });

  test('the same URL under another kind starts a new import', () => {
    const tileset = startUrlImport(URL, undefined, 'tiles3d');
    const files = startUrlImport(URL);

    expect(files).not.toBe(tileset);
    expect(mockUploadFromUrl).toHaveBeenNthCalledWith(1, URL, undefined, 'tiles3d');
    expect(mockUploadFromUrl).toHaveBeenNthCalledWith(2, URL, undefined, undefined);
    expect(peekUrlImport()?.kind).toBeNull();
  });
});

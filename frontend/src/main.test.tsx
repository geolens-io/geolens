import { describe, expect, it, vi } from 'vitest';
import { Route } from 'react-router';
import { preload } from '@/lib/route-preload';

const { load, restore } = vi.hoisted(() => ({
  load: vi.fn(() => Promise.resolve()),
  restore: vi.fn(),
}));

vi.mock('@/i18n', () => ({ initializeI18n: () => Promise.resolve() }));
vi.mock('@/lib/session-sync', () => ({
  restoreSessionBeforeRender: restore,
  wireSessionSync: vi.fn(),
}));
vi.mock('react-dom/client', () => ({
  default: { createRoot: () => ({ render: vi.fn() }) },
}));
vi.mock('./index.css', () => ({}));
vi.mock('./App', () => ({
  appRoutes: (
    <Route path="/">
      <Route path="lazy-route" element={null} handle={preload(load)} />
    </Route>
  ),
}));

async function boot(path: string): Promise<void> {
  vi.resetModules();
  load.mockClear();
  window.history.pushState({}, '', path);
  document.body.innerHTML = '<div id="root"></div>';
  await import('./main');
}

describe('bootstrap', () => {
  it('starts the matched route chunk before the session restore resolves', async () => {
    let finish!: () => void;
    restore.mockReturnValue(new Promise<void>((resolve) => (finish = resolve)));
    await boot('/lazy-route');
    expect(restore).toHaveBeenCalled();
    expect(load).toHaveBeenCalledTimes(1);
    finish();
  });

  it('starts nothing for an unmatched path', async () => {
    restore.mockReturnValue(Promise.resolve());
    await boot('/unknown/path');
    expect(load).not.toHaveBeenCalled();
  });
});

import { isValidElement, type ReactElement } from 'react';
import { appRoutes } from './App';
import { ALL_TAB_KEYS } from '@/pages/admin/AdminSettingsPage';

// fix(#871): a legacy `admin/settings/appearance` → `/admin/settings/map`
// redirect sat next to `admin/settings/:tab` for four months. React Router
// ranks a fully static path above a dynamic one, so the redirect fired for
// every edition and the enterprise branding tab was unreachable —
// AdminSettingsPage's edition gate never saw the URL. The gating unit tests
// mock `useParams`, so they cannot catch a re-added static route; this walks
// the real route table instead.
function collectPaths(node: unknown, out: string[] = []): string[] {
  if (Array.isArray(node)) {
    node.forEach(child => collectPaths(child, out));
    return out;
  }
  if (!isValidElement(node)) return out;
  const props = (node as ReactElement<{ path?: string; children?: unknown }>).props;
  if (typeof props.path === 'string') out.push(props.path);
  collectPaths(props.children, out);
  return out;
}

describe('appRoutes', () => {
  it('declares no static admin/settings route that shadows a real settings tab', () => {
    const shadowing = collectPaths(appRoutes)
      .map(path => /^\/?admin\/settings\/([^/:]+)$/.exec(path)?.[1])
      .filter((tab): tab is string => tab !== undefined && (ALL_TAB_KEYS as readonly string[]).includes(tab));

    expect(shadowing).toEqual([]);
  });
});

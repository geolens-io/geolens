import { isValidElement, type ReactElement, type ReactNode } from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router';
import { appRoutes } from './App';
import { ALL_TAB_KEYS } from '@/pages/admin/AdminSettingsPage';

// fix(#871): a legacy `admin/settings/appearance` → `/admin/settings/map`
// redirect sat next to `admin/settings/:tab` for four months. React Router
// ranks a fully static path above a dynamic one, so the redirect fired for
// every edition and the enterprise branding tab was unreachable —
// AdminSettingsPage's edition gate never saw the URL. The gating unit tests
// mock `useParams`, so they cannot catch a re-added static route; this walks
// the real route table instead.
function findRouteElement(node: unknown, path: string): ReactNode | undefined {
  if (Array.isArray(node)) {
    for (const child of node) {
      const found = findRouteElement(child, path);
      if (found !== undefined) return found;
    }
    return undefined;
  }
  if (!isValidElement(node)) return undefined;
  const props = (node as ReactElement<{ path?: string; element?: ReactNode; children?: unknown }>).props;
  if (props.path === path) return props.element;
  return findRouteElement(props.children, path);
}

function LocationProbe() {
  const { pathname, search, hash } = useLocation();
  return <output>{`${pathname}${search}${hash}`}</output>;
}

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

  it('keeps the query when /search redirects to the home page', () => {
    render(
      <MemoryRouter initialEntries={['/search?q=rivers#results']}>
        <Routes>
          <Route path="/search" element={findRouteElement(appRoutes, 'search')} />
          <Route path="/" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByRole('status')).toHaveTextContent('/?q=rivers#results');
  });
});

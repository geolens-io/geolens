import { useEffect } from 'react';
import { Outlet, useMatch, useLocation, useNavigationType } from 'react-router';
import { Navbar } from './Navbar';
import { AppFooter } from './AppFooter';
import { DemoBanner } from './DemoBanner';
import { SiteBanner } from './SiteBanner';
import { useEdition } from '@/hooks/use-edition';
import { useBranding } from '@/hooks/use-settings';
import { SkipToContent } from './SkipToContent';
import { useAuthStore } from '@/stores/auth-store';
import { cn } from '@/lib/utils';

export function AppLayout() {
  const hasAuthToken = useAuthStore((state) => !!state.token);
  const isEditor = useAuthStore((state) => state.isEditor());
  const isMapRoute = Boolean(useMatch('/maps/:id'));
  const isAuthenticatedMapRoute = isMapRoute && (isEditor || hasAuthToken);
  const { pathname } = useLocation();
  const navType = useNavigationType();

  // React Router (component routes) doesn't reset window scroll on navigation,
  // so a list→detail click carries the list's scroll offset onto the shorter
  // detail page (lands scrolled to the bottom). Reset to top on PUSH/REPLACE
  // only — skip POP (browser Back/Forward) so the browser's own scroll
  // restoration returns the user to where they were in the list. Keyed on
  // pathname (not hash) so dataset tab-switches don't retrigger; the map route
  // manages its own fixed full-height layout, so leave it alone.
  useEffect(() => {
    if (isMapRoute || navType === 'POP') return;
    window.scrollTo(0, 0);
  }, [pathname, isMapRoute, navType]);
  const { isEnterprise } = useEdition();
  const { data: branding } = useBranding();
  const showFooterBranding = !isEnterprise || branding?.show_badge !== false;

  return (
    // fix(#522): the navbar is fixed (out of flow), so reserve its height
    // (h-14 + safe-area) as top padding on the shell. Applies to both branches:
    // min-h-screen pages get their content pushed below the navbar, and h-dvh
    // map routes correctly lose this height to flex-1 — exactly as they did when
    // the navbar consumed flow height. Banners render below the navbar as a result.
    <div
      className={cn(
        'flex flex-col pt-[calc(3.5rem+env(safe-area-inset-top))]',
        isAuthenticatedMapRoute ? 'h-dvh overflow-hidden' : 'min-h-screen',
      )}
    >
      <SkipToContent />
      {/* fix(#553): inside the flex shell so h-dvh map routes lose height to
          the banner instead of overflowing the viewport */}
      <SiteBanner />
      <Navbar />
      <DemoBanner />
      <main
        id="main-content"
        tabIndex={-1}
        // Always a flex column so flex-1 page content fills the space the
        // navbar/banner/footer leave — fixes the public-map scroll (was a
        // hardcoded 100dvh-navbar that ignored the footer) AND lets standalone
        // pages (404) center vertically in the available viewport (#305).
        // isMapRoute retained for any map-specific tweaks.
        // scroll-mt clears the fixed navbar when the skip-link scrolls
        // #main-content into view, so the heading isn't hidden under it (#305).
        // min-h-0 on authenticated map routes fixes the flexbox min-height:auto
        // trap so the builder's editor panel scrolls internally instead of the
        // whole builder page scrolling when an editor bar expands (#347 (BLDR-01)).
        className={cn(
          'flex flex-1 flex-col scroll-mt-16 animate-fade-in focus:outline-none',
          isMapRoute && 'flex-col',
          isAuthenticatedMapRoute && 'min-h-0',
        )}
      >
        <Outlet />
      </main>
      {!isAuthenticatedMapRoute && <AppFooter showBranding={showFooterBranding} />}
    </div>
  );
}

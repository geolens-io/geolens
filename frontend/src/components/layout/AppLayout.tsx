import { useEffect } from 'react';
import { Outlet, useMatch, useLocation, useNavigationType } from 'react-router';
import { Navbar } from './Navbar';
import { AppFooter } from './AppFooter';
import { SiteBanner } from './SiteBanner';
import { useEdition } from '@/hooks/use-edition';
import { useBranding } from '@/hooks/use-settings';
import { SkipToContent } from './SkipToContent';
import { cn } from '@/lib/utils';

export function AppLayout() {
  const isMapRoute = Boolean(useMatch('/maps/:id'));
  const { pathname } = useLocation();
  const navType = useNavigationType();

  // React Router doesn't reset window scroll, so a list→detail click would
  // land the shorter page scrolled down. Reset on PUSH/REPLACE only; POP lets
  // the browser restore the list position. Keyed on pathname (not hash) so tab
  // switches don't retrigger; the map route manages its own layout.
  useEffect(() => {
    if (isMapRoute || navType === 'POP') return;
    window.scrollTo(0, 0);
  }, [pathname, isMapRoute, navType]);
  const { isEnterprise } = useEdition();
  const { data: branding } = useBranding();
  const showFooterBranding = !isEnterprise || branding?.show_badge !== false;

  return (
    // The navbar is fixed, so its height (h-14 + safe-area) is reserved as top
    // padding: min-h-screen pages sit below it and h-dvh map routes lose that
    // height to flex-1, as if the navbar were in flow. Banners render below it.
    // Bottom padding reserves the space a floating launcher covers, footer included.
    <div
      className={cn(
        'flex flex-col pt-[calc(3.5rem+env(safe-area-inset-top))] pb-[var(--floating-dock-inset,0px)]',
        isMapRoute ? 'h-dvh overflow-hidden' : 'min-h-screen',
      )}
    >
      <SkipToContent />
      {/* Inside the flex shell so h-dvh map routes lose height to the banner
          instead of overflowing the viewport */}
      <SiteBanner />
      <Navbar />
      <main
        id="main-content"
        tabIndex={-1}
        // A flex column so flex-1 content fills the space the navbar, banner
        // and footer leave, and standalone pages (404) center vertically.
        // scroll-mt clears the fixed navbar when the skip link scrolls
        // #main-content into view. min-h-0 on map routes avoids the flexbox
        // min-height:auto trap so the builder's editor panel scrolls internally.
        className={cn(
          'flex flex-1 flex-col scroll-mt-16 animate-fade-in focus:outline-none',
          isMapRoute && 'min-h-0',
        )}
      >
        <Outlet />
      </main>
      {/* The map route carries its own GeoLens credit in the attribution control. */}
      {!isMapRoute && <AppFooter showBranding={showFooterBranding} />}
    </div>
  );
}

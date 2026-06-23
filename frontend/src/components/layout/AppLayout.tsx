import { Outlet, useMatch } from 'react-router';
import { Navbar } from './Navbar';
import { AppFooter } from './AppFooter';
import { DemoBanner } from './DemoBanner';
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
  const { isEnterprise } = useEdition();
  const { data: branding } = useBranding();
  const showFooterBranding = !isEnterprise || branding?.show_badge !== false;

  return (
    <div className="flex min-h-screen flex-col">
      <SkipToContent />
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
        // scroll-mt clears the now-sticky navbar when the skip-link scrolls
        // #main-content into view, so the heading isn't hidden under it (#305).
        className={cn('flex flex-1 flex-col scroll-mt-16 animate-fade-in focus:outline-none', isMapRoute && 'flex-col')}
      >
        <Outlet />
      </main>
      {!isAuthenticatedMapRoute && <AppFooter showBranding={showFooterBranding} />}
    </div>
  );
}

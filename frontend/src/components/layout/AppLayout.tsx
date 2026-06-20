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
        // ponytail: on map routes, become a flex column so the map fills the space
        // the navbar/banner/footer leave — fixes the public-map scroll where the
        // page hardcoded `100dvh-navbar` and ignored the footer below it.
        className={cn('flex-1 animate-fade-in focus:outline-none', isMapRoute && 'flex flex-col')}
      >
        <Outlet />
      </main>
      {!isAuthenticatedMapRoute && <AppFooter showBranding={showFooterBranding} />}
    </div>
  );
}

import { Outlet, useMatch } from 'react-router';
import { Navbar } from './Navbar';
import { AppFooter } from './AppFooter';
import { useEdition } from '@/hooks/use-edition';
import { useBranding } from '@/hooks/use-settings';
import { SkipToContent } from './SkipToContent';
import { useAuthStore } from '@/stores/auth-store';

export function AppLayout() {
  const isEditor = useAuthStore((state) => state.isEditor());
  const isMapBuilder = Boolean(useMatch('/maps/:id')) && isEditor;
  const { isEnterprise } = useEdition();
  const { data: branding } = useBranding();
  const showFooterBranding = !isEnterprise || branding?.show_badge !== false;

  return (
    <div className="flex min-h-screen flex-col">
      <SkipToContent />
      <Navbar />
      <main id="main-content" tabIndex={-1} className="flex-1 animate-fade-in focus:outline-none">
        <Outlet />
      </main>
      {!isMapBuilder && <AppFooter showBranding={showFooterBranding} />}
    </div>
  );
}

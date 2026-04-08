import { Outlet } from 'react-router';
import { useTranslation } from 'react-i18next';
import { SidebarProvider, SidebarInset, SidebarTrigger } from '@/components/ui/sidebar';
import { AdminSidebar } from './AdminSidebar';
import { Separator } from '@/components/ui/separator';

/**
 * Top-level layout for all `/admin/*` routes.
 *
 * Provides a persistent {@link AdminSidebar} with a mobile-collapsible header
 * and renders the matched child route inside a padded `SidebarInset`. Used as
 * the route element for the admin section in the router.
 */
export function AdminLayout() {
  const { t } = useTranslation();

  return (
    <SidebarProvider style={{
      "--sidebar-width": "16rem",
      "--sidebar-width-mobile": "18rem",
    } as React.CSSProperties}>
      <AdminSidebar />
      <SidebarInset>
        <header className="flex items-center gap-2 border-b px-4 h-10 md:hidden">
          <SidebarTrigger className="-ms-1" />
          <Separator orientation="vertical" className="h-4" />
          <span className="text-sm font-medium">{t('adminNav.admin')}</span>
        </header>
        <div className="p-6 space-y-6">
          <Outlet />
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}

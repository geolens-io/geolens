import { useState, useEffect } from 'react';
import { Link, NavLink, useLocation } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ChevronDown, User, LogOut, Settings, Shield, Plus, Database, FolderOpen, Map, Menu, Layers, Upload, LogIn, LifeBuoy, Sun, Moon } from 'lucide-react';
import { useTheme } from '@/components/theme-provider';
import { useAuth } from '@/hooks/use-auth';
import { useReportDialog } from '@/lib/report';
import { usePermissions } from '@/hooks/use-permissions';
import { useFeatureFlags } from '@/hooks/use-settings';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet';
import { Separator } from '@/components/ui/separator';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import { GeoLensLogo } from '@/components/GeoLensLogo';
import { CreateDatasetDialog } from '@/components/create/CreateDatasetDialog';
import { CollectionCreateDialog } from '@/components/collections/CollectionCreateDialog';
import { MapCreateDialog } from '@/components/maps/MapCreateDialog';
import { VrtCreateDialog } from '@/components/import/VrtCreateDialog';

// Full-height topbar tabs with a 2px baseline marker on the active route —
// the same underline vocabulary as the Import page's mode tabs. ring-inset
// keeps the focus ring visible at the header's clipped top edge.
const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    'relative inline-flex h-14 items-center px-3 text-sm font-medium transition-colors',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset',
    'after:pointer-events-none after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:bg-primary after:opacity-0 after:transition-opacity',
    isActive
      ? 'text-foreground after:opacity-100'
      : 'text-muted-foreground hover:text-foreground',
  );

const mobileNavLinkClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    'flex items-center rounded-md px-3 py-2 text-sm font-medium transition-colors',
    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
    isActive
      ? 'bg-accent text-accent-foreground'
      : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
  );

function CreateMenu() {
  const { user } = useAuth();
  const { can } = usePermissions();
  const { data: featureFlags } = useFeatureFlags();
  const { t } = useTranslation();
  const [datasetOpen, setDatasetOpen] = useState(false);
  const [collectionOpen, setCollectionOpen] = useState(false);
  const [mapOpen, setMapOpen] = useState(false);
  const [vrtOpen, setVrtOpen] = useState(false);

  const canCreateDataset = featureFlags?.enable_dataset_editing ?? false;
  const canImport = can('upload');
  const canCreateCollection = can('edit_metadata');
  const canCreateMap = true;
  const canCreateVrt = can('upload');
  const hasAnyCreateItems = canCreateDataset || canImport || canCreateCollection || canCreateMap || canCreateVrt;

  if (!user) return null;
  if (!hasAnyCreateItems) return null;

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm">
            <Plus className="h-4 w-4 me-1" />
            {t('create')}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {canCreateDataset && (
            <DropdownMenuItem onClick={() => setDatasetOpen(true)}>
              <Database className="h-4 w-4" />
              {t('nav.dataset')}
            </DropdownMenuItem>
          )}
          {can('upload') && (
            <DropdownMenuItem asChild>
              <Link to="/import">
                <Upload className="h-4 w-4" />
                {t('nav.importData')}
              </Link>
            </DropdownMenuItem>
          )}
          {(canCreateDataset || canImport) && <DropdownMenuSeparator />}
          {can('edit_metadata') && (
            <DropdownMenuItem onClick={() => setCollectionOpen(true)}>
              <FolderOpen className="h-4 w-4" />
              {t('nav.collection')}
            </DropdownMenuItem>
          )}
          <DropdownMenuItem onClick={() => setMapOpen(true)}>
            <Map className="h-4 w-4" />
            {t('nav.map')}
          </DropdownMenuItem>
          {can('upload') && (
            <DropdownMenuItem onClick={() => setVrtOpen(true)}>
              <Layers className="h-4 w-4" />
              {t('nav.virtualRaster')}
            </DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      <CreateDatasetDialog open={datasetOpen} onOpenChange={setDatasetOpen} />
      <CollectionCreateDialog open={collectionOpen} onOpenChange={setCollectionOpen} />
      <MapCreateDialog open={mapOpen} onOpenChange={setMapOpen} />
      <VrtCreateDialog open={vrtOpen} onOpenChange={setVrtOpen} />
    </>
  );
}

function UserMenu() {
  const { user, logout } = useAuth();
  const { can } = usePermissions();
  const { t } = useTranslation();
  const { t: tAuth } = useTranslation('auth');
  const { t: tReport } = useTranslation('report');
  const openReport = useReportDialog((s) => s.openReport);
  // #305: explicit light/dark override (default stays 'system', which
  // already honors prefers-color-scheme). resolvedTheme drives the icon/label.
  const { setTheme, resolvedTheme } = useTheme();

  // Anonymous: show sign-in button instead of user dropdown
  if (!user) {
    return (
      <Button variant="outline" size="sm" asChild>
        <Link to="/login">
          <LogIn className="h-4 w-4 me-1" />
          {tAuth('signIn')}
        </Link>
      </Button>
    );
  }

  const initial = user?.username?.charAt(0).toUpperCase();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="relative h-9 rounded-full ps-1 pe-1 md:pe-2"
        >
          {initial ? (
            <span className="flex size-7 items-center justify-center rounded-full bg-primary text-primary-foreground text-xs font-medium">
              {initial}
            </span>
          ) : (
            <User className="h-4 w-4 shrink-0" />
          )}
          {user && (
            <>
              <span className="hidden max-w-28 truncate text-sm font-medium md:block">
                {user.username}
              </span>
              <ChevronDown className="hidden size-4 text-muted-foreground md:block" />
            </>
          )}
          <span className="sr-only">{t('nav.userMenu')}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48">
        {user && (
          <>
            <DropdownMenuLabel className="flex items-center gap-2">
              {user.username}
              <Badge variant="secondary" className="text-2xs px-1.5 py-0">
                {user.roles?.[0]}
              </Badge>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
          </>
        )}

        {/* Settings link */}
        <DropdownMenuItem asChild>
          <Link to="/settings">
            <Settings className="h-4 w-4" />
            {t('nav.settings')}
          </Link>
        </DropdownMenuItem>

        {/* #305: light/dark toggle (no UI affordance existed before) */}
        <DropdownMenuItem
          onClick={(e) => {
            e.preventDefault();
            setTheme(resolvedTheme === 'dark' ? 'light' : 'dark');
          }}
        >
          {resolvedTheme === 'dark' ? (
            <Sun className="h-4 w-4" />
          ) : (
            <Moon className="h-4 w-4" />
          )}
          {resolvedTheme === 'dark'
            ? t('nav.lightMode', { defaultValue: 'Light mode' })
            : t('nav.darkMode', { defaultValue: 'Dark mode' })}
        </DropdownMenuItem>

        {/* Admin (admin users only) */}
        {can('manage_users') && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem asChild>
              <Link to="/admin">
                <Shield className="h-4 w-4" />
                {t('nav.admin')}
              </Link>
            </DropdownMenuItem>
          </>
        )}

        <DropdownMenuSeparator />

        {/* Report a problem — opens the in-app problem reporter */}
        <DropdownMenuItem onClick={openReport}>
          <LifeBuoy className="h-4 w-4" />
          {tReport('title')}
        </DropdownMenuItem>

        <DropdownMenuSeparator />

        {/* Logout */}
        <DropdownMenuItem onClick={logout} variant="destructive">
          <LogOut className="h-4 w-4" />
          {t('nav.logout')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function MobileNav() {
  const { user } = useAuth();
  const { can } = usePermissions();
  const { data: featureFlags } = useFeatureFlags();
  const { t } = useTranslation();
  const { t: tAuth } = useTranslation('auth');
  const location = useLocation();
  const [open, setOpen] = useState(false);

  const [datasetOpen, setDatasetOpen] = useState(false);
  const [collectionOpen, setCollectionOpen] = useState(false);
  const [mapOpen, setMapOpen] = useState(false);
  const [vrtOpen, setVrtOpen] = useState(false);

  // Auto-close sheet on navigation
  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);

  return (
    <>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden"
          >
            <Menu className="h-5 w-5" />
            <span className="sr-only">{t('nav.menu')}</span>
          </Button>
        </SheetTrigger>
        <SheetContent side="left" className="w-64">
          <SheetHeader>
            <SheetTitle><GeoLensLogo size="sm" /></SheetTitle>
            <SheetDescription className="sr-only">{t('nav.navigationMenu')}</SheetDescription>
          </SheetHeader>
          <nav aria-label={t('nav.navigationMenu')} className="flex flex-col gap-1 px-2">
            <NavLink to="/" end className={mobileNavLinkClass}>
              {t('nav.search')}
            </NavLink>
            <NavLink to="/collections" className={mobileNavLinkClass}>
              {t('nav.collections')}
            </NavLink>
            <NavLink to="/maps" className={mobileNavLinkClass}>
              {t('nav.maps')}
            </NavLink>
            {can('manage_users') && (
              <NavLink to="/admin" className={mobileNavLinkClass}>
                {t('nav.admin')}
              </NavLink>
            )}
            {user && (() => {
              const canCreateDataset = featureFlags?.enable_dataset_editing ?? false;
              const canImport = can('upload');
              const canCreateCollection = can('edit_metadata');
              const canCreateMap = true;
              const canCreateVrt = can('upload');
              const hasAnyCreateItems = canCreateDataset || canImport || canCreateCollection || canCreateMap || canCreateVrt;
              if (!hasAnyCreateItems) return null;
              return (
                <>
                  <Separator className="my-2" />
                  <p className="px-3 text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">
                    {t('create')}
                  </p>
                  {canCreateDataset && (
                    <button
                      className={mobileNavLinkClass({ isActive: false })}
                      onClick={() => { setDatasetOpen(true); setOpen(false); }}
                    >
                      <Database className="h-4 w-4 me-2" />
                      {t('nav.dataset')}
                    </button>
                  )}
                  {canCreateCollection && (
                    <button
                      className={mobileNavLinkClass({ isActive: false })}
                      onClick={() => { setCollectionOpen(true); setOpen(false); }}
                    >
                      <FolderOpen className="h-4 w-4 me-2" />
                      {t('nav.collection')}
                    </button>
                  )}
                  <button
                    className={mobileNavLinkClass({ isActive: false })}
                    onClick={() => { setMapOpen(true); setOpen(false); }}
                  >
                    <Map className="h-4 w-4 me-2" />
                    {t('nav.map')}
                  </button>
                  {canCreateVrt && (
                    <button
                      className={mobileNavLinkClass({ isActive: false })}
                      onClick={() => { setVrtOpen(true); setOpen(false); }}
                    >
                      <Layers className="h-4 w-4 me-2" />
                      {t('nav.virtualRaster')}
                    </button>
                  )}
                  {canImport && (
                    <Link
                      to="/import"
                      className={mobileNavLinkClass({ isActive: false })}
                      onClick={() => setOpen(false)}
                    >
                      <Upload className="h-4 w-4 me-2" />
                      {t('nav.importData')}
                    </Link>
                  )}
                </>
              );
            })()}
            {!user && (
              <>
                <Separator className="my-2" />
                <Link
                  to="/login"
                  className={mobileNavLinkClass({ isActive: false })}
                  onClick={() => setOpen(false)}
                >
                  <LogIn className="h-4 w-4 me-2" />
                  {tAuth('signIn')}
                </Link>
              </>
            )}
          </nav>
        </SheetContent>
      </Sheet>

      <CreateDatasetDialog open={datasetOpen} onOpenChange={setDatasetOpen} />
      <CollectionCreateDialog open={collectionOpen} onOpenChange={setCollectionOpen} />
      <MapCreateDialog open={mapOpen} onOpenChange={setMapOpen} />
      <VrtCreateDialog open={vrtOpen} onOpenChange={setVrtOpen} />
    </>
  );
}

export function Navbar() {
  const { t } = useTranslation();
  const { can } = usePermissions();

  return (
    <header className="sticky top-0 z-40 border-b bg-background pt-[env(safe-area-inset-top)]">
      {/* Full-bleed control bar — page content keeps its own max-width;
          the frame spans the viewport like the rest of the chrome. */}
      <div className="flex h-14 w-full items-center justify-between gap-4 px-4 sm:px-6">
        <div className="flex min-w-0 items-center gap-4">
          <MobileNav />
          <Link to="/" aria-label={t('appName')} className="rounded-md hover:text-primary transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background">
            <GeoLensLogo size="sm" />
          </Link>
          <Separator orientation="vertical" className="hidden md:block h-6" />
          <nav aria-label={t('nav.mainNavigation')} className="hidden h-14 md:flex items-center gap-1">
            <NavLink to="/" end className={navLinkClass}>
              {t('nav.search')}
            </NavLink>
            <NavLink to="/collections" className={navLinkClass}>
              {t('nav.collections')}
            </NavLink>
            <NavLink to="/maps" className={navLinkClass}>
              {t('nav.maps')}
            </NavLink>
            {/* Operators get a first-class entry — previously buried in the
                user dropdown only. */}
            {can('manage_users') && (
              <NavLink to="/admin" className={navLinkClass}>
                {t('nav.admin')}
              </NavLink>
            )}
          </nav>
        </div>
        <div className="flex items-center gap-2">
          <div className="hidden md:block">
            <CreateMenu />
          </div>
          <UserMenu />
        </div>
      </div>
    </header>
  );
}

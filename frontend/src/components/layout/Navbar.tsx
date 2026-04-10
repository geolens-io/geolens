import { useState, useEffect } from 'react';
import { Link, NavLink, useLocation } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ChevronDown, User, LogOut, Settings, Shield, Plus, Database, FolderOpen, Map, Menu, Layers, Upload, LogIn } from 'lucide-react';
import { useAuth } from '@/hooks/use-auth';
import { usePermissions } from '@/hooks/use-permissions';
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

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    'inline-flex items-center justify-center rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
    isActive
      ? 'bg-accent text-accent-foreground'
      : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
  );

const mobileNavLinkClass = ({ isActive }: { isActive: boolean }) =>
  cn(
    'flex items-center rounded-md px-3 py-2 text-sm font-medium transition-colors',
    isActive
      ? 'bg-accent text-accent-foreground'
      : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
  );

function CreateMenu() {
  const { user } = useAuth();
  const { can } = usePermissions();
  const { t } = useTranslation();
  const [datasetOpen, setDatasetOpen] = useState(false);
  const [collectionOpen, setCollectionOpen] = useState(false);
  const [mapOpen, setMapOpen] = useState(false);
  const [vrtOpen, setVrtOpen] = useState(false);

  if (!user) return null;

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
          <DropdownMenuItem onClick={() => setDatasetOpen(true)}>
            <Database className="h-4 w-4" />
            {t('nav.dataset')}
          </DropdownMenuItem>
          {can('upload') && (
            <DropdownMenuItem asChild>
              <Link to="/import">
                <Upload className="h-4 w-4" />
                {t('nav.importData')}
              </Link>
            </DropdownMenuItem>
          )}
          <DropdownMenuSeparator />
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
              <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
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
            {user && (
              <>
                <Separator className="my-2" />
                <p className="px-3 text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">
                  {t('create')}
                </p>
                <button
                  className={mobileNavLinkClass({ isActive: false })}
                  onClick={() => { setDatasetOpen(true); setOpen(false); }}
                >
                  <Database className="h-4 w-4 me-2" />
                  {t('nav.dataset')}
                </button>
                {can('edit_metadata') && (
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
                {can('upload') && (
                  <button
                    className={mobileNavLinkClass({ isActive: false })}
                    onClick={() => { setVrtOpen(true); setOpen(false); }}
                  >
                    <Layers className="h-4 w-4 me-2" />
                    {t('nav.virtualRaster')}
                  </button>
                )}
                {can('upload') && (
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
            )}
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

  return (
    <header className="border-b bg-background">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-6">
        <div className="flex items-center gap-4">
          <MobileNav />
          <Link to="/" aria-label={t('appName')} className="hover:text-primary transition-colors duration-150">
            <GeoLensLogo size="sm" />
          </Link>
          <Separator orientation="vertical" className="hidden md:block h-6" />
          <nav aria-label={t('nav.mainNavigation')} className="hidden md:flex items-center gap-2">
            <NavLink to="/" end className={navLinkClass}>
              {t('nav.search')}
            </NavLink>
            <NavLink to="/collections" className={navLinkClass}>
              {t('nav.collections')}
            </NavLink>
            <NavLink to="/maps" className={navLinkClass}>
              {t('nav.maps')}
            </NavLink>
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

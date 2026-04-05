import { useState, type FormEvent } from 'react';
import { ArrowRight, Globe, Shield } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Navigate, useLocation, useNavigate } from 'react-router';
import { PageShell } from '@/components/layout/PageShell';
import { Button } from '@/components/ui/button';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { useAuthStore } from '@/stores/auth-store';
import { useBranding } from '@/hooks/use-settings';
import {
  GEOLENS_LICENSE_URL,
  OGC_API_URL,
} from '@/lib/external-links';

const trustSignals = [
  { icon: Shield, labelKey: 'trust.license', href: GEOLENS_LICENSE_URL },
  { icon: Globe, labelKey: 'trust.ogc', href: OGC_API_URL },
] as const;

function TrustSignalStrip() {
  const { t } = useTranslation('search');

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {trustSignals.map((signal) => (
        <a
          key={signal.labelKey}
          href={signal.href}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 rounded-full border border-border/40 bg-background/70 px-3 py-1.5 text-[11px] font-medium text-muted-foreground/80 transition-colors hover:text-foreground"
        >
          <signal.icon className="size-3 shrink-0" aria-hidden="true" />
          {t(signal.labelKey)}
        </a>
      ))}
    </div>
  );
}

function ProductPreview() {
  return (
    <div className="hidden lg:block" aria-hidden="true">
      <div className="overflow-hidden rounded-xl border border-border/50 bg-background shadow-lg">
        {/* Window chrome */}
        <div className="flex items-center gap-1.5 border-b border-border/30 px-3 py-2">
          <div className="size-2 rounded-full bg-border" />
          <div className="size-2 rounded-full bg-border" />
          <div className="size-2 rounded-full bg-border" />
          <div className="ml-2 h-3.5 flex-1 max-w-32 rounded bg-muted/50" />
        </div>

        {/* Search bar */}
        <div className="border-b border-border/15 px-3 py-2">
          <div className="flex items-center gap-1.5 rounded-lg border border-border/40 px-2.5 py-1.5">
            <svg className="size-2.5 shrink-0 text-muted-foreground/30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></svg>
            <span className="text-[7px] text-muted-foreground/40">Search geospatial data...</span>
          </div>
        </div>

        {/* Filter tabs */}
        <div className="flex items-center gap-1 border-b border-border/15 px-3 py-1.5">
          <span className="rounded-md bg-foreground/8 px-1.5 py-0.5 text-[6px] font-semibold text-foreground/70">All (207)</span>
          <span className="px-1.5 py-0.5 text-[6px] text-muted-foreground/50">Vector (204)</span>
          <span className="px-1.5 py-0.5 text-[6px] text-muted-foreground/50">Raster</span>
          <span className="px-1.5 py-0.5 text-[6px] text-muted-foreground/50">Table (3)</span>
          <span className="ml-auto text-[5.5px] text-muted-foreground/35">207 results</span>
        </div>

        {/* Dataset cards */}
        <div className="divide-y divide-border/10">
          {/* Card 1: Nys Aquifers — real dataset */}
          <div className="flex gap-2.5 px-3 py-2.5">
            <div className="min-w-0 flex-1 space-y-0.5">
              <span className="inline-flex items-center gap-0.5 rounded-full bg-primary/12 px-1.5 py-px text-[5.5px] font-semibold text-primary/80">
                <svg className="size-1.5" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" /></svg>
                Vector
              </span>
              <p className="text-[8.5px] font-semibold text-primary">Nys Aquifers</p>
              <p className="text-[6.5px] leading-snug text-muted-foreground/60">Aquifer polygons in New York State</p>
              <p className="text-[5.5px] text-muted-foreground/40">MultiPolygon · 907 features · EPSG:4326</p>
            </div>
            {/* Quicklook — polygon outlines approximating NYS shape */}
            <div className="size-12 shrink-0 overflow-hidden rounded-md bg-muted/12">
              <svg className="size-full" viewBox="0 0 60 60" fill="none">
                <polygon points="12,18 28,10 42,14 48,28 44,42 32,48 18,44 10,32" style={{ fill: 'var(--primary)', stroke: 'var(--primary)' }} fillOpacity={0.12} strokeOpacity={0.4} strokeWidth="0.6" />
                <polygon points="22,22 34,16 46,24 44,38 34,44 20,38" style={{ fill: 'var(--primary)', stroke: 'var(--primary)' }} fillOpacity={0.08} strokeOpacity={0.3} strokeWidth="0.5" />
                <polygon points="16,30 26,22 38,28 36,40 24,44" style={{ fill: 'var(--primary)', stroke: 'var(--primary)' }} fillOpacity={0.1} strokeOpacity={0.35} strokeWidth="0.5" />
              </svg>
            </div>
          </div>

          {/* Card 2: Nys Address Points — real dataset */}
          <div className="flex gap-2.5 px-3 py-2.5">
            <div className="min-w-0 flex-1 space-y-0.5">
              <span className="inline-flex items-center gap-0.5 rounded-full bg-primary/12 px-1.5 py-px text-[5.5px] font-semibold text-primary/80">
                <svg className="size-1.5" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" /></svg>
                Vector
              </span>
              <p className="text-[8.5px] font-semibold">Nys Address Points</p>
              <p className="text-[6.5px] leading-snug text-muted-foreground/60">Addressed properties in New York State</p>
              <p className="text-[5.5px] text-muted-foreground/40">MultiPoint · 202,000 features · EPSG:4326</p>
            </div>
            {/* Quicklook — scattered points */}
            <div className="size-12 shrink-0 overflow-hidden rounded-md bg-muted/12">
              <svg className="size-full" viewBox="0 0 60 60" fill="none">
                <circle cx="18" cy="20" r="1.8" style={{ fill: 'var(--primary)' }} fillOpacity={0.6} />
                <circle cx="30" cy="15" r="1.5" style={{ fill: 'var(--primary)' }} fillOpacity={0.5} />
                <circle cx="42" cy="22" r="2" style={{ fill: 'var(--primary)' }} fillOpacity={0.55} />
                <circle cx="24" cy="32" r="1.6" style={{ fill: 'var(--primary)' }} fillOpacity={0.5} />
                <circle cx="36" cy="28" r="1.8" style={{ fill: 'var(--primary)' }} fillOpacity={0.6} />
                <circle cx="14" cy="40" r="1.4" style={{ fill: 'var(--primary)' }} fillOpacity={0.45} />
                <circle cx="28" cy="44" r="1.7" style={{ fill: 'var(--primary)' }} fillOpacity={0.55} />
                <circle cx="44" cy="38" r="1.5" style={{ fill: 'var(--primary)' }} fillOpacity={0.5} />
                <circle cx="38" cy="48" r="1.3" style={{ fill: 'var(--primary)' }} fillOpacity={0.45} />
                <circle cx="20" cy="48" r="1.6" style={{ fill: 'var(--primary)' }} fillOpacity={0.5} />
                <circle cx="48" cy="14" r="1.4" style={{ fill: 'var(--primary)' }} fillOpacity={0.4} />
                <circle cx="10" cy="28" r="1.5" style={{ fill: 'var(--primary)' }} fillOpacity={0.45} />
              </svg>
            </div>
          </div>

          {/* Card 3: Bulletin — real dataset, different type */}
          <div className="flex gap-2.5 px-3 pb-3 pt-2.5">
            <div className="min-w-0 flex-1 space-y-0.5">
              <span className="inline-flex items-center gap-0.5 rounded-full bg-amber-500/12 px-1.5 py-px text-[5.5px] font-semibold text-amber-700/70">
                Table
              </span>
              <p className="text-[8.5px] font-semibold">Bulletin</p>
              <p className="text-[6.5px] leading-snug text-muted-foreground/60">Initial creation 11/6/23</p>
              <p className="text-[5.5px] text-muted-foreground/40">29 rows</p>
            </div>
            <div className="size-12 shrink-0 rounded-md bg-muted/12" />
          </div>
        </div>
      </div>
    </div>
  );
}

export function LandingPage() {
  const { t } = useTranslation('search');
  const { t: tCommon } = useTranslation('common');
  useDocumentTitle(tCommon('appName'));
  const token = useAuthStore((s) => s.token);
  const { data: branding } = useBranding();
  const location = useLocation();
  const navigate = useNavigate();
  const [query, setQuery] = useState('');

  // Redirect: authenticated users → /search; landing page disabled → /search
  const landingDisabled = branding && branding.show_landing_page === false;
  const redirectTarget = token || landingDisabled
    ? `/search${location.search}`
    : location.search ? `/search${location.search}` : null;
  if (redirectTarget) return <Navigate to={redirectTarget} replace />;

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextQuery = query.trim();
    navigate({
      pathname: '/search',
      search: nextQuery ? `?${new URLSearchParams({ q: nextQuery }).toString()}` : '',
    });
  };

  const hasQuery = query.trim().length > 0;

  return (
    <PageShell maxWidth="wide" className="space-y-6 pb-8 pt-6 sm:pt-8">
      <section className="relative overflow-hidden rounded-3xl border border-border/60 bg-[linear-gradient(140deg,_hsl(var(--background))_12%,_hsl(var(--muted)/0.26)_100%)] px-5 py-7 shadow-sm sm:px-7 sm:py-8 lg:px-10 lg:py-9">
        <div className="absolute right-0 top-0 h-48 w-48 rounded-full bg-primary/8 blur-3xl" aria-hidden="true" />
        <div className="absolute bottom-0 left-10 h-36 w-36 rounded-full bg-accent/10 blur-3xl" aria-hidden="true" />

        <div className="relative lg:grid lg:grid-cols-[3fr_2fr] lg:items-center lg:gap-10">
          <div className="space-y-5">
            <p className="inline-flex rounded-full border border-border/60 bg-background/85 px-3 py-1 text-[0.65rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground sm:text-xs sm:tracking-[0.18em]">
              {t('landing.eyebrow')}
            </p>

            <div className="space-y-3">
              <h1 className="max-w-3xl text-3xl font-semibold tracking-tight sm:text-4xl lg:text-[3.2rem] lg:leading-[1.05]">
                {t('title')}
              </h1>
              <p className="max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base">
                {t('subtitle')}
              </p>
            </div>

            <form onSubmit={handleSubmit} role="search" aria-label={t('placeholder')} className="max-w-xl">
              <div className="flex h-12 items-stretch rounded-2xl border border-border/60 bg-background/92 shadow-sm transition-colors focus-within:border-primary/40 focus-within:ring-2 focus-within:ring-ring/20">
                <svg className="my-auto ml-4 size-4 shrink-0 text-muted-foreground" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <circle cx="11" cy="11" r="8" />
                  <path d="m21 21-4.3-4.3" />
                </svg>
                <input
                  type="text"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  aria-label={t('placeholder')}
                  placeholder={t('placeholder')}
                  className="min-w-0 flex-1 bg-transparent px-3 text-base text-foreground outline-none placeholder:text-muted-foreground"
                />
                <Button type="submit" size="sm" className="my-1 mr-1 rounded-xl px-3 sm:px-4">
                  <span className="sr-only sm:not-sr-only">
                    {hasQuery ? t('landing.searchCta') : t('landing.primaryCta')}
                  </span>
                  <ArrowRight className="size-4" aria-hidden="true" />
                </Button>
              </div>
            </form>

            <TrustSignalStrip />
          </div>

          <ProductPreview />
        </div>
      </section>
    </PageShell>
  );
}

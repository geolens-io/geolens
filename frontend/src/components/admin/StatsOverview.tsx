import { useTranslation } from 'react-i18next';
import {
  Database,
  HardDrive,
  MemoryStick,
  Layers,
  CheckCircle2,
  XCircle,
  RefreshCw,
  Shield,
  Users,
} from 'lucide-react';
import { useCatalogStats, useInfrastructure } from '@/hooks/use-admin';
import { AIStatusCard } from '@/components/admin/AIStatusCard';
import { formatBytes, formatNumber } from '@/lib/format';
import { semanticBadgeColors, visibilityColors } from '@/lib/status-colors';
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { LoadingState } from '@/components/layout/LoadingState';
import { ErrorState } from '@/components/layout/ErrorState';
import { getGeometryTypeLabel, getVisibilityLabel } from '@/i18n/labels';
import type { ProviderHealth } from '@/types/api';
import type { LucideIcon } from 'lucide-react';

function StatusDot({ status }: { status: string }) {
  return (
    <span
      className={`inline-block h-2.5 w-2.5 rounded-full ${
        status === 'ok' ? 'bg-emerald-500' : 'bg-destructive'
      }`}
    />
  );
}

function ServiceRow({
  icon: Icon,
  label,
  health,
  detail,
}: {
  icon: LucideIcon;
  label: string;
  health: ProviderHealth;
  detail?: string;
}) {
  return (
    <div className="flex items-center gap-3 py-2.5">
      <Icon className="h-4 w-4 text-muted-foreground flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <span className="text-sm font-medium">{label}</span>
        {detail && (
          <span className="text-xs text-muted-foreground ml-2">{detail}</span>
        )}
      </div>
      <code className="text-xs text-muted-foreground tabular-nums">
        {health.latency_ms}ms
      </code>
      <StatusDot status={health.status} />
    </div>
  );
}

function formatInfraType(value: string): string {
  return value
    .split(/[-_]/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

function SystemHealthCard() {
  const { t } = useTranslation('admin');
  const { data, isLoading, isError, refetch, isFetching } = useInfrastructure();

  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <Skeleton className="h-5 w-40" />
        </CardHeader>
        <CardContent className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-8 w-full" />
          ))}
        </CardContent>
      </Card>
    );
  }

  if (isError || !data) {
    return (
      <Card>
        <CardContent className="py-6">
          <p className="text-sm text-destructive">{t('infrastructure.errorLoading')}</p>
        </CardContent>
      </Card>
    );
  }

  const allHealthy = Object.values(data.health).every((h) => h.status === 'ok');
  const oidcEntries = Object.entries(data.oidc_providers);
  const allOidcHealthy = oidcEntries.every(([, h]) => h.status === 'ok');
  const overallHealthy = allHealthy && allOidcHealthy;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {overallHealthy ? (
              <CheckCircle2 className="h-5 w-5 text-emerald-500" />
            ) : (
              <XCircle className="h-5 w-5 text-destructive" />
            )}
            <div>
              <CardTitle className="text-base">
                {overallHealthy ? t('infrastructure.allOperational') : t('infrastructure.degraded')}
              </CardTitle>
              <p className="text-xs text-muted-foreground mt-0.5">
                {t('infrastructure.autoRefresh')}
              </p>
            </div>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => refetch()}
            disabled={isFetching}
            aria-label={t('infrastructure.refresh', {
              defaultValue: 'Refresh infrastructure status',
            })}
          >
            <RefreshCw className={`h-4 w-4 ${isFetching ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <div className="divide-y">
          {data.health.database && (
            <ServiceRow
              icon={Database}
              label={t('infrastructure.database')}
              health={data.health.database}
              detail={formatInfraType(data.config.database_type)}
            />
          )}
          {data.health.storage && (
            <ServiceRow
              icon={HardDrive}
              label={t('infrastructure.storage')}
              health={data.health.storage}
              detail={formatInfraType(data.config.storage_provider)}
            />
          )}
          {data.health.cache && (
            <ServiceRow
              icon={MemoryStick}
              label={t('infrastructure.cache')}
              health={data.health.cache}
              detail={formatInfraType(data.config.cache_provider)}
            />
          )}
          <div className="flex items-center gap-3 py-2.5">
            <Layers className="h-4 w-4 text-muted-foreground flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <span className="text-sm font-medium">{t('infrastructure.tileCache')}</span>
              <span className="text-xs text-muted-foreground ml-2">
                {formatInfraType(data.config.tile_cache)} &middot; TTL {data.config.tile_cache_ttl}s
              </span>
            </div>
            <Badge
              variant="secondary"
              className={
                data.config.cdn_configured
                  ? `${semanticBadgeColors.success} text-xs`
                  : 'text-xs'
              }
            >
              {data.config.cdn_configured ? t('infrastructure.cdn') : t('infrastructure.noCdn')}
            </Badge>
          </div>
          {oidcEntries.map(([slug, health]) => (
            <ServiceRow
              key={slug}
              icon={Shield}
              label={slug}
              health={health}
              detail={t('infrastructure.oidc')}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function StatCard({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <Card>
      <CardContent className="pt-6">
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className="text-3xl font-bold mt-1">{value}</p>
      </CardContent>
    </Card>
  );
}

export function StatsOverview() {
  const { t } = useTranslation('admin');
  const { data, isLoading, error } = useCatalogStats();

  if (isLoading) {
    return <LoadingState message={t('stats.loading')} className="py-12" />;
  }

  if (error) {
    return <ErrorState message={t('stats.errorLoading', { message: error.message })} />;
  }

  if (!data) return null;

  return (
    <div className="space-y-6">
      {/* System Health — prominent at top */}
      <SystemHealthCard />

      {/* Summary Stats */}
      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard label={t('stats.totalDatasets')} value={formatNumber(data.total_datasets)} />
        <StatCard label={t('stats.recentAdditions')} value={formatNumber(data.recent_additions)} />
        <StatCard label={t('stats.storageUsed')} value={formatBytes(data.total_storage_bytes)} />
      </div>

      {/* Breakdown Cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">{t('stats.byGeometryType')}</CardTitle>
          </CardHeader>
          <CardContent>
            {Object.keys(data.datasets_by_geometry_type).length === 0 ? (
              <p className="text-sm text-muted-foreground">{t('stats.noDatasets')}</p>
            ) : (
              <ul className="space-y-2">
                {Object.entries(data.datasets_by_geometry_type)
                  .sort(([, a], [, b]) => b - a)
                  .map(([type, count]) => {
                    const maxCount = Math.max(
                      ...Object.values(data.datasets_by_geometry_type),
                    );
                    const pct = maxCount > 0 ? (count / maxCount) * 100 : 0;
                    return (
                      <li key={type} className="space-y-1">
                        <div className="flex items-center justify-between text-sm">
                          <span>{getGeometryTypeLabel(t, type)}</span>
                          <span className="font-medium">{count}</span>
                        </div>
                        <div className="h-2 rounded-full bg-muted">
                          <div
                            className="h-2 rounded-full bg-primary"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </li>
                    );
                  })}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium">{t('stats.byVisibility')}</CardTitle>
          </CardHeader>
          <CardContent>
            {Object.keys(data.datasets_by_visibility).length === 0 ? (
              <p className="text-sm text-muted-foreground">{t('stats.noDatasets')}</p>
            ) : (
              <ul className="space-y-2">
                {Object.entries(data.datasets_by_visibility)
                  .sort(([, a], [, b]) => b - a)
                  .map(([visibility, count]) => (
                    <li
                      key={visibility}
                      className="flex items-center justify-between text-sm"
                    >
                      <Badge
                        className={
                          visibilityColors[visibility] ?? 'bg-muted text-muted-foreground border-border'
                        }
                        variant="secondary"
                      >
                        {getVisibilityLabel(t, visibility)}
                      </Badge>
                      <span className="font-medium">{count}</span>
                    </li>
                  ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium flex items-center gap-2">
              <Users className="h-4 w-4" />
              {t('stats.usersByStatus')}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {Object.keys(data.users_by_status).length === 0 ? (
              <p className="text-sm text-muted-foreground">{t('stats.noUsers')}</p>
            ) : (
              <ul className="space-y-2">
                {Object.entries(data.users_by_status)
                  .sort(([, a], [, b]) => b - a)
                  .map(([userStatus, count]) => (
                    <li
                      key={userStatus}
                      className="flex items-center justify-between text-sm"
                    >
                      <Badge
                        variant="secondary"
                        className={
                          userStatus === 'active'
                            ? semanticBadgeColors.success
                            : userStatus === 'pending'
                              ? semanticBadgeColors.warning
                              : ''
                        }
                      >
                        {userStatus}
                      </Badge>
                      <span className="font-medium">{count}</span>
                    </li>
                  ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <AIStatusCard />
      </div>
    </div>
  );
}

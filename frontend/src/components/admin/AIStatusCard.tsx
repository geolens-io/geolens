import { useTranslation } from 'react-i18next';
import { Link } from 'react-router';
import { Bot, ArrowRight } from 'lucide-react';
import { useAIStatus, useEmbeddingStats } from '@/hooks/use-admin';
import { useAuthStore } from '@/stores/auth-store';
import { semanticBadgeColors } from '@/lib/status-colors';
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

export function AIStatusCard() {
  const { t } = useTranslation('admin');
  // SF-06: gate the admin probe at the consumer. An admin endpoint must
  // never fire from an unauthenticated or non-admin context — mirrors the
  // consumer-side pattern in use-ai-availability.ts:7.
  const token = useAuthStore((s) => s.token);
  const isAdmin = useAuthStore((s) => s.isAdmin());
  const { data: aiStatus, isLoading } = useAIStatus({ enabled: !!token && isAdmin });
  const { data: embeddingStats } = useEmbeddingStats();

  if (isLoading || !aiStatus) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <Bot className="h-4 w-4" />
          {t('ai.cardTitle')}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {!aiStatus.configured ? (
          <p className="text-sm text-muted-foreground">{t('ai.notConfigured')}</p>
        ) : (
          <>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">{t('ai.provider')}</span>
              <span className="capitalize text-end break-all">{aiStatus.provider}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">{t('ai.status')}</span>
              {aiStatus.enabled ? (
                <Badge variant="secondary" className={semanticBadgeColors.success}>
                  {t('ai.enabled')}
                </Badge>
              ) : (
                <Badge variant="secondary" className={semanticBadgeColors.destructive}>
                  {t('ai.disabled')}
                </Badge>
              )}
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">{t('ai.semanticSearch')}</span>
              {aiStatus.semantic_search_enabled ? (
                <Badge variant="secondary" className={semanticBadgeColors.success}>
                  {t('ai.enabled')}
                </Badge>
              ) : (
                <Badge variant="secondary" className={semanticBadgeColors.destructive}>
                  {t('ai.disabled')}
                </Badge>
              )}
            </div>

            {/* Embedding coverage read-only */}
            {embeddingStats && (
              <div className="border-t pt-3 space-y-2">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">{t('ai.embeddingCoverage')}</span>
                  <span className="text-muted-foreground tabular-nums">
                    {embeddingStats.coverage_percent}%
                  </span>
                </div>
                <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                  <div
                    className="h-full rounded-full bg-primary transition-[width] duration-300 ease-out"
                    style={{ width: `${embeddingStats.coverage_percent}%` }}
                  />
                </div>
              </div>
            )}

            {/* Link to settings */}
            <div className="border-t pt-3">
              <Link
                to="/admin/settings/ai"
                className="inline-flex items-center gap-1.5 text-sm text-primary hover:underline"
              >
                {t('ai.manageSettings')}
                <ArrowRight className="h-3.5 w-3.5 rtl-mirror" />
              </Link>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

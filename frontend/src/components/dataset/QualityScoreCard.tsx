import { useTranslation } from 'react-i18next';
import type { DatasetResponse } from '@/types/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { qualityScoreClasses } from '@/lib/status-colors';
import { Badge } from '@/components/ui/badge';
import { deriveQualityFreshness } from '@/lib/quality-freshness';

type QualityScore = NonNullable<DatasetResponse['quality_detail']>;

interface QualityScoreCardProps {
  qualityScore: QualityScore | null | undefined;
  updateFrequency?: DatasetResponse['update_frequency'];
}

const dimensions: { key: keyof QualityScore; labelKey: string; weight: string }[] = [
  { key: 'metadata_completeness', labelKey: 'quality.metadataCompleteness', weight: '30%' },
  { key: 'geometry_validity', labelKey: 'quality.geometryValidity', weight: '30%' },
  { key: 'attribute_completeness', labelKey: 'quality.attributeCompleteness', weight: '25%' },
  { key: 'crs_defined', labelKey: 'quality.crsDefined', weight: '15%' },
];

function barColor(score: number): string {
  if (score >= 80) return 'bg-success';
  if (score >= 60) return 'bg-warning';
  return 'bg-destructive';
}

function freshnessBadgeClass(state: 'fresh' | 'stale' | 'missing'): string {
  if (state === 'fresh') return 'bg-success/10 text-success border-success/30';
  if (state === 'stale') return 'bg-warning/10 text-warning border-warning/30';
  return 'bg-muted text-muted-foreground border-border';
}

export function QualityScoreCard({ qualityScore, updateFrequency }: QualityScoreCardProps) {
  const { t, i18n } = useTranslation('dataset');
  if (!qualityScore) return null;

  const freshness = deriveQualityFreshness({
    computedAt: qualityScore.computed_at,
    updateFrequency,
    locale: i18n.language,
  });
  const cadenceGuidance = t(
    freshness.cadence === 'unknown'
      ? 'quality.freshness.cadenceUnknown'
      : `quality.freshness.cadence${freshness.cadence.charAt(0).toUpperCase()}${freshness.cadence.slice(1)}`,
  );
  const freshnessBadgeLabel = t(`quality.freshness.state.${freshness.state}`);
  const remediationHint = t(`quality.freshness.remediation.${freshness.state}`);
  const absoluteTimestamp = freshness.absoluteTimestamp ?? t('quality.freshness.notAvailable');
  const relativeAge = freshness.relativeAge ?? t('quality.freshness.unknownAge');

  return (
    <Card>
      <CardHeader className="space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <CardTitle>{t('quality.title')}</CardTitle>
            <p className="text-xs text-muted-foreground" data-testid="quality-freshness-time">
              {absoluteTimestamp} ({relativeAge})
            </p>
          </div>
          <Badge className={qualityScoreClasses(qualityScore.overall)}>
            {Math.round(qualityScore.overall)}
          </Badge>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Badge
            className={freshnessBadgeClass(freshness.state)}
            data-testid="quality-freshness-badge"
          >
            {freshnessBadgeLabel}
          </Badge>
          <p className="text-xs text-muted-foreground" data-testid="quality-cadence-guidance">
            {cadenceGuidance}
          </p>
        </div>

        {(freshness.state === 'stale' || freshness.state === 'missing') && (
          <p className="text-xs text-warning" data-testid="quality-remediation-hint">
            {remediationHint}
          </p>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {dimensions.map(({ key, labelKey, weight }) => {
          const value = qualityScore[key] as number;
          return (
            <div key={key} className="space-y-1">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>{t(labelKey)}</span>
                <span>{Math.round(value)} ({weight})</span>
              </div>
              <div className="h-2 rounded-full bg-muted">
                <div
                  className={`h-2 rounded-full transition-[width] duration-300 ease-out ${barColor(value)}`}
                  style={{ width: `${Math.min(value, 100)}%` }}
                />
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

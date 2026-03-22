import { useTranslation } from 'react-i18next';
import { AlertCircle, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { useValidation } from '@/hooks/use-dataset';
import { getValidationNavigationActions } from '@/lib/dataset-validation-navigation';
import { semanticBadgeColors } from '@/lib/status-colors';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';

interface DatasetHealthStripProps {
  datasetId: string;
  onNavigateToField: (field: string) => void;
}

export function DatasetHealthStrip({
  datasetId,
  onNavigateToField,
}: DatasetHealthStripProps) {
  const { t } = useTranslation('dataset');
  const { data, isLoading } = useValidation(datasetId);

  if (isLoading || !data) {
    return null;
  }

  const requiredCount = data.errors.length;
  const recommendedCount = data.warnings.length;
  const actionItems = getValidationNavigationActions([
    ...data.errors,
    ...data.warnings,
  ]).slice(0, 4);
  const hasIssues = requiredCount > 0 || recommendedCount > 0;

  return (
    <Card
      className="border-border/70 bg-muted/20 shadow-none hover:shadow-none"
      data-testid="dataset-health-strip"
    >
      <CardContent className="flex flex-col gap-3 py-4 md:flex-row md:items-center md:justify-between">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium">{t('validation.health.title')}</span>
            {hasIssues ? (
              <>
                {requiredCount > 0 && (
                  <Badge className={`${semanticBadgeColors.destructive} gap-1`}>
                    <AlertCircle className="h-3.5 w-3.5 text-rose-700 dark:text-rose-200" />
                    {t('validation.health.required', { count: requiredCount })}
                  </Badge>
                )}
                {recommendedCount > 0 && (
                  <Badge className={`${semanticBadgeColors.warning} gap-1`}>
                    <AlertTriangle className="h-3.5 w-3.5 text-amber-700 dark:text-amber-200" />
                    {t('validation.health.recommended', { count: recommendedCount })}
                  </Badge>
                )}
              </>
            ) : (
              <Badge className={`${semanticBadgeColors.success} gap-1`}>
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-700 dark:text-emerald-200" />
                {t('validation.health.ready')}
              </Badge>
            )}
          </div>

          <p
            className="text-sm text-muted-foreground"
            data-testid="dataset-health-description"
          >
            {hasIssues
              ? t('validation.health.description', {
                  requiredCount,
                  recommendedCount,
                })
              : t('validation.health.descriptionReady')}
          </p>
        </div>

        {actionItems.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {actionItems.map((action) => (
              <Button
                key={`${action.tab ?? 'page'}-${action.anchor}`}
                type="button"
                size="sm"
                variant="outline"
                className="bg-background"
                onClick={() => onNavigateToField(action.field)}
                data-testid={`dataset-health-action-${action.anchor}`}
              >
                {t(action.labelKey, { defaultValue: action.defaultLabel })}
              </Button>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

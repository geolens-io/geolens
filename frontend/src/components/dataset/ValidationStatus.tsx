import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertCircle, AlertTriangle, CheckCircle2, Lightbulb } from 'lucide-react';
import { useValidation } from '@/hooks/use-dataset';
import { useAllSettings } from '@/hooks/use-settings';
import { semanticBadgeColors } from '@/lib/status-colors';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  deriveLikelyValidationCauses,
  ValidationTroubleshootPanel,
} from '@/components/dataset/ValidationTroubleshootPanel';

interface ValidationStatusProps {
  datasetId: string;
  mode?: 'detailed' | 'compact';
  onNavigateToField?: (field: string) => void;
}

export function ValidationStatus({
  datasetId,
  mode = 'detailed',
  onNavigateToField,
}: ValidationStatusProps) {
  const { t } = useTranslation('dataset');
  const { data, isLoading } = useValidation(datasetId);
  const [troubleshootOpen, setTroubleshootOpen] = useState(false);
  const { data: allSettings } = useAllSettings();
  const requireMetadata = allSettings?.tabs?.general?.find(
    (s: { key: string }) => s.key === 'require_metadata_for_publish'
  )?.value ?? false;

  if (isLoading || !data) return null;

  const errorCount = data.errors.length;
  const warningCount = data.warnings.length;
  const hasIssues = errorCount > 0 || warningCount > 0;
  const likelyCauses = deriveLikelyValidationCauses([...data.errors, ...data.warnings], 2, t);

  const helperText = errorCount > 0
    ? t(requireMetadata ? 'validation.helperBlocking' : 'validation.helperIssues', {
      errorCount,
      warningCount,
    })
    : t('validation.helperWarnings', { warningCount });

  const statusBadge = errorCount > 0 ? (
    <Badge className={`${semanticBadgeColors.destructive} gap-1`}>
      <AlertCircle className="h-3.5 w-3.5 text-rose-700 dark:text-rose-200" />
      {t(requireMetadata ? 'validation.issuesBlocking' : 'validation.issuesFound', { count: errorCount })}
    </Badge>
  ) : warningCount > 0 ? (
    <Badge className={`${semanticBadgeColors.warning} gap-1`}>
      <AlertTriangle className="h-3.5 w-3.5 text-amber-700 dark:text-amber-200" />
      {t('validation.warnings', { count: warningCount })}
    </Badge>
  ) : (
    <Badge className={`${semanticBadgeColors.success} gap-1`}>
      <CheckCircle2 className="h-3.5 w-3.5 text-emerald-700 dark:text-emerald-200" />
      {t('validation.readyToPublish')}
    </Badge>
  );

  if (mode === 'compact') {
    return (
      <div className="flex flex-wrap items-center gap-2" data-testid="validation-status-compact">
        {statusBadge}
        {hasIssues && likelyCauses.length > 0 && (
          <span className="text-xs text-muted-foreground" data-testid="validation-likely-causes-compact">
            {t('validation.likelyCompact')} {likelyCauses.join(' · ')}
          </span>
        )}
        {hasIssues && (
          <Button
            type="button"
            variant="link"
            size="sm"
            className="h-auto px-0"
            onClick={() => setTroubleshootOpen(true)}
            data-testid="validation-troubleshoot-trigger"
          >
            {t('validation.troubleshootAction')}
          </Button>
        )}
        <ValidationTroubleshootPanel
          open={troubleshootOpen}
          onOpenChange={setTroubleshootOpen}
          errors={data.errors}
          warnings={data.warnings}
          onNavigateToField={onNavigateToField}
        />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {statusBadge}

      {hasIssues && (
        <div className="space-y-2 rounded-md border border-border/70 bg-muted/30 px-3 py-2">
          <p className="text-sm text-foreground" data-testid="validation-helper-text">
            {helperText}
          </p>

          {likelyCauses.length > 0 && (
            <ul className="space-y-1" data-testid="validation-likely-causes">
              {likelyCauses.map((cause) => (
                <li key={cause} className="text-sm text-muted-foreground flex items-center gap-1.5">
                  <Lightbulb className="h-3.5 w-3.5 text-warning" />
                  {cause}
                </li>
              ))}
            </ul>
          )}

          <Button
            type="button"
            variant="link"
            size="sm"
            className="h-auto px-0"
            onClick={() => setTroubleshootOpen(true)}
            data-testid="validation-troubleshoot-trigger"
          >
            {t('validation.troubleshootAction')}
          </Button>
        </div>
      )}

      {errorCount > 0 && (
        <ul className="space-y-1">
          {data.errors.map((issue, i) => (
            <li key={`err-${i}`} className="flex items-start gap-1.5 text-sm text-destructive">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
              <span>
                <span className="font-medium">{issue.field}:</span> {issue.message}
              </span>
            </li>
          ))}
        </ul>
      )}

      {warningCount > 0 && (
        <ul className="space-y-1">
          {data.warnings.map((issue, i) => (
            <li key={`warn-${i}`} className="flex items-start gap-1.5 text-sm text-warning">
              <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
              <span>
                <span className="font-medium">{issue.field}:</span> {issue.message}
              </span>
            </li>
          ))}
        </ul>
      )}

      <ValidationTroubleshootPanel
        open={troubleshootOpen}
        onOpenChange={setTroubleshootOpen}
        errors={data.errors}
        warnings={data.warnings}
        onNavigateToField={onNavigateToField}
      />
    </div>
  );
}

import { useTranslation } from 'react-i18next';
import { AlertCircle, AlertTriangle, Lightbulb } from 'lucide-react';
import type { ValidationIssue } from '@/types/api';
import { getValidationNavigationAction } from '@/lib/dataset-validation-navigation';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';

interface ValidationTroubleshootPanelProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
  onNavigateToField?: (field: string) => void;
}

interface RemediationGroup {
  id: string;
  titleKey: string;
  hintKey: string;
  count: number;
}

function formatFieldLabel(field: string): string {
  if (!field) return 'metadata';
  return field
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

const REMEDIATION_RULES: Array<{
  id: string;
  titleKey: string;
  hintKey: string;
  test: (issue: ValidationIssue) => boolean;
}> = [
  {
    id: 'required-fields',
    titleKey: 'validation.troubleshoot.requiredFields',
    hintKey: 'validation.troubleshoot.requiredFieldsHint',
    test: (issue) => /\b(required|missing|blank|empty)\b/i.test(issue.message),
  },
  {
    id: 'invalid-values',
    titleKey: 'validation.troubleshoot.invalidValues',
    hintKey: 'validation.troubleshoot.invalidValuesHint',
    test: (issue) => /\b(invalid|must|format|range|type)\b/i.test(issue.message),
  },
  {
    id: 'geometry-crs',
    titleKey: 'validation.troubleshoot.geometryCrs',
    hintKey: 'validation.troubleshoot.geometryCrsHint',
    test: (issue) => /\b(geometry|geom|crs|srid|extent|bbox)\b/i.test(issue.field),
  },
  {
    id: 'source-cadence',
    titleKey: 'validation.troubleshoot.sourceCadence',
    hintKey: 'validation.troubleshoot.sourceCadenceHint',
    test: (issue) => /\b(source|lineage|vintage|update|frequency)\b/i.test(issue.field),
  },
  {
    id: 'general',
    titleKey: 'validation.troubleshoot.general',
    hintKey: 'validation.troubleshoot.generalHint',
    test: () => true,
  },
];

function deriveRemediationGroups(issues: ValidationIssue[]): RemediationGroup[] {
  const groups = new Map<string, RemediationGroup>();

  for (const issue of issues) {
    const rule = REMEDIATION_RULES.find((candidate) => candidate.test(issue)) ?? REMEDIATION_RULES[REMEDIATION_RULES.length - 1];
    const existing = groups.get(rule.id);

    if (existing) {
      existing.count += 1;
      continue;
    }

    groups.set(rule.id, {
      id: rule.id,
      titleKey: rule.titleKey,
      hintKey: rule.hintKey,
      count: 1,
    });
  }

  return Array.from(groups.values())
    .sort((a, b) => b.count - a.count)
    .slice(0, 3);
}

export function deriveLikelyValidationCauses(
  issues: ValidationIssue[],
  limit = 2,
  t?: (key: string, opts?: Record<string, unknown>) => string,
): string[] {
  const causeCounts = new Map<string, number>();

  for (const issue of issues) {
    const fieldLabel = formatFieldLabel(issue.field);
    const message = issue.message.toLowerCase();
    let cause: string;

    if (/\b(required|missing|blank|empty)\b/.test(message)) {
      cause = t ? t('validation.causes.missing', { field: fieldLabel }) : `Missing ${fieldLabel}`;
    } else if (/\b(invalid|must|format|range|type)\b/.test(message)) {
      cause = t ? t('validation.causes.invalid', { field: fieldLabel }) : `Invalid ${fieldLabel}`;
    } else if (/\b(duplicate|conflict)\b/.test(message)) {
      cause = t ? t('validation.causes.conflicting', { field: fieldLabel }) : `Conflicting ${fieldLabel}`;
    } else {
      cause = t ? t('validation.causes.needsReview', { field: fieldLabel }) : `${fieldLabel} needs review`;
    }

    causeCounts.set(cause, (causeCounts.get(cause) ?? 0) + 1);
  }

  return Array.from(causeCounts.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, Math.max(limit, 1))
    .map(([label]) => label);
}

export function ValidationTroubleshootPanel({
  open,
  onOpenChange,
  errors,
  warnings,
  onNavigateToField,
}: ValidationTroubleshootPanelProps) {
  const { t } = useTranslation('dataset');
  const issueCount = errors.length + warnings.length;
  const remediationGroups = deriveRemediationGroups([...errors, ...warnings]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl" data-testid="validation-troubleshoot-dialog">
        <DialogHeader>
          <DialogTitle>{t('validation.troubleshoot.title')}</DialogTitle>
          <DialogDescription>
            {t('validation.troubleshoot.description', { count: issueCount })}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 max-h-[70vh] overflow-y-auto pr-1">
          <div className="space-y-2" data-testid="validation-troubleshoot-next-steps">
            <p className="text-sm font-medium">{t('validation.troubleshoot.likelyNextSteps')}</p>
            {remediationGroups.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                {t('validation.troubleshoot.noIssues')}
              </p>
            ) : (
              <ul className="space-y-2">
                {remediationGroups.map((group) => (
                  <li
                    key={group.id}
                    className="rounded-md border border-border/70 bg-muted/30 px-3 py-2"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <p className="text-sm font-medium flex items-center gap-1.5">
                        <Lightbulb className="h-4 w-4 text-warning mt-0.5" />
                        {t(group.titleKey)}
                      </p>
                      <Badge variant="outline">{group.count}</Badge>
                    </div>
                    <p className="text-sm text-muted-foreground mt-1">{t(group.hintKey)}</p>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {errors.length > 0 && (
            <section className="space-y-2" data-testid="validation-troubleshoot-errors">
              <p className="text-sm font-medium flex items-center gap-1.5">
                <AlertCircle className="h-4 w-4 text-destructive" />
                {t('validation.troubleshoot.blockingErrors', { count: errors.length })}
              </p>
              <ul className="space-y-1.5">
                {errors.map((issue, index) => (
                  <li
                    key={`error-${issue.field}-${index}`}
                    className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <p className="text-sm">
                        <span className="font-medium">{formatFieldLabel(issue.field)}:</span>{' '}
                        {issue.message}
                      </p>
                      {onNavigateToField && getValidationNavigationAction(issue.field) && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="shrink-0"
                          onClick={() => {
                            onOpenChange(false);
                            onNavigateToField(issue.field);
                          }}
                        >
                          {t('validation.goToField')}
                        </Button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}

          {warnings.length > 0 && (
            <section className="space-y-2" data-testid="validation-troubleshoot-warnings">
              <p className="text-sm font-medium flex items-center gap-1.5">
                <AlertTriangle className="h-4 w-4 text-warning" />
                {t('validation.troubleshoot.warnings', { count: warnings.length })}
              </p>
              <ul className="space-y-1.5">
                {warnings.map((issue, index) => (
                  <li
                    key={`warning-${issue.field}-${index}`}
                    className="rounded-md border border-warning/30 bg-warning/5 px-3 py-2"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <p className="text-sm">
                        <span className="font-medium">{formatFieldLabel(issue.field)}:</span>{' '}
                        {issue.message}
                      </p>
                      {onNavigateToField && getValidationNavigationAction(issue.field) && (
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="shrink-0"
                          onClick={() => {
                            onOpenChange(false);
                            onNavigateToField(issue.field);
                          }}
                        >
                          {t('validation.goToField')}
                        </Button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            data-testid="validation-troubleshoot-close"
          >
            {t('common:close')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

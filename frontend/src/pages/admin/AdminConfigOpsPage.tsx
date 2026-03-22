import { useState, useRef, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { PageHeader } from '@/components/layout/PageHeader';
import { useDocumentTitle } from '@/hooks/use-document-title';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Download,
  Upload,
  CheckCircle2,
  Loader2,
  AlertTriangle,
} from 'lucide-react';
import {
  useExportConfig,
  useDryRunImport,
  useImportConfig,
} from '@/hooks/use-config-ops';
import type {
  ImportMode,
  ConfigImportRequest,
  DryRunResult,
} from '@/api/config-ops';

function truncateValue(val: unknown, maxLen = 60): string {
  const s = typeof val === 'string' ? val : JSON.stringify(val);
  if (s == null) return '(null)';
  return s.length > maxLen ? s.slice(0, maxLen) + '...' : s;
}

function actionBadgeVariant(action: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  switch (action) {
    case 'update':
    case 'create':
      return 'default';
    case 'delete':
      return 'destructive';
    default:
      return 'secondary';
  }
}

// --- Export Section ---

function ExportSection() {
  const { t } = useTranslation();
  const exportMutation = useExportConfig();

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Download className="h-4 w-4" />
          {t('configOps.export.title')}
        </CardTitle>
        <CardDescription>
          {t('configOps.export.description')}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Button
          onClick={() => exportMutation.mutate()}
          disabled={exportMutation.isPending}
        >
          {exportMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin mr-2" />
          ) : (
            <Download className="h-4 w-4 mr-2" />
          )}
          {t('configOps.export.button')}
        </Button>
      </CardContent>
    </Card>
  );
}

// --- Import Section ---

function ImportSection() {
  const { t } = useTranslation();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [mode, setMode] = useState<ImportMode>('merge');
  const [fileData, setFileData] = useState<ConfigImportRequest | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [dryRunResult, setDryRunResult] = useState<DryRunResult | null>(null);

  const dryRunMutation = useDryRunImport();
  const importMutation = useImportConfig();

  const pickingRef = useRef(false);

  const openFilePicker = useCallback(() => {
    if (pickingRef.current) return;
    pickingRef.current = true;
    fileInputRef.current?.click();
    // Reset after a short delay to allow the dialog to open
    setTimeout(() => { pickingRef.current = false; }, 1000);
  }, []);

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    pickingRef.current = false;
    const file = e.target.files?.[0];
    if (!file) return;

    setParseError(null);
    setDryRunResult(null);
    setFileName(file.name);

    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(reader.result as string);
        // Accept either a full export (with version/exported_at) or a plain import payload
        const importData: ConfigImportRequest = {
          settings: parsed.settings ?? null,
          oauth_providers: parsed.oauth_providers ?? null,
        };
        if (!importData.settings && !importData.oauth_providers) {
          setParseError(t('configOps.import.parseErrorKeys'));
          setFileData(null);
          return;
        }
        setFileData(importData);
      } catch {
        setParseError(t('configOps.import.parseErrorInvalid'));
        setFileData(null);
      }
    };
    reader.readAsText(file);
  }

  function handlePreview() {
    if (!fileData) return;
    dryRunMutation.mutate(
      { data: fileData, mode },
      { onSuccess: (result) => setDryRunResult(result) },
    );
  }

  function handleApply() {
    if (!fileData) return;
    importMutation.mutate(
      { data: fileData, mode },
      {
        onSuccess: () => {
          setDryRunResult(null);
          setFileData(null);
          setFileName(null);
          if (fileInputRef.current) fileInputRef.current.value = '';
        },
      },
    );
  }

  const hasChanges =
    dryRunResult &&
    (dryRunResult.settings.changes.some((c) => c.action !== 'no_change') ||
      dryRunResult.oauth_providers.changes.some((c) => c.action !== 'no_change'));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Upload className="h-4 w-4" />
          {t('configOps.import.title')}
        </CardTitle>
        <CardDescription>
          {t('configOps.import.description')}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <input
          ref={fileInputRef}
          type="file"
          accept=".json"
          onChange={handleFileChange}
          className="hidden"
        />
        {/* File input */}
        <div className="space-y-2">
          <span className="text-sm font-medium">
            {t('configOps.import.fileLabel')}
          </span>
          <div className="flex items-center gap-3">
            <Button
              type="button"
              variant="outline"
              onClick={openFilePicker}
            >
              <Upload className="h-4 w-4 mr-2" />
              {t('configOps.import.chooseFile')}
            </Button>
            {fileName && fileData && (
              <p className="text-sm text-muted-foreground">{fileName}</p>
            )}
            {!fileName && (
              <p className="text-sm text-muted-foreground">
                {t('configOps.import.noFile')}
              </p>
            )}
          </div>
          {parseError && (
            <p className="text-sm text-destructive">{parseError}</p>
          )}
        </div>

        {/* Mode selector */}
        <div className="space-y-2">
          <Label>{t('configOps.import.modeLabel')}</Label>
          <Select value={mode} onValueChange={(v) => setMode(v as ImportMode)}>
            <SelectTrigger className="w-[260px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="merge">
                {t('configOps.import.modeMerge')}
              </SelectItem>
              <SelectItem value="overwrite">
                {t('configOps.import.modeOverwrite')}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Overwrite warning */}
        {mode === 'overwrite' && (
          <div className="flex items-start gap-2 rounded-md border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
            <AlertTriangle className="h-4 w-4 mt-0.5 flex-shrink-0" />
            <span>
              {t('configOps.import.overwriteWarning')}
            </span>
          </div>
        )}

        {/* Action buttons */}
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={handlePreview}
            disabled={!fileData || dryRunMutation.isPending}
          >
            {dryRunMutation.isPending && (
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
            )}
            {t('configOps.import.preview')}
          </Button>
          <Button
            onClick={handleApply}
            disabled={!dryRunResult || !hasChanges || importMutation.isPending}
          >
            {importMutation.isPending && (
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
            )}
            {t('configOps.import.apply')}
          </Button>
        </div>

        {/* Dry-run results */}
        {dryRunResult && (
          <div className="space-y-4 pt-2">
            {/* Settings changes */}
            {dryRunResult.settings.changes.length > 0 && (
              <div className="space-y-2">
                <h4 className="text-sm font-medium">
                  {t('configOps.import.settingsChanges')}
                </h4>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('configOps.import.key')}</TableHead>
                      <TableHead>{t('configOps.import.current')}</TableHead>
                      <TableHead>{t('configOps.import.imported')}</TableHead>
                      <TableHead>{t('configOps.import.action')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {dryRunResult.settings.changes.map((c) => (
                      <TableRow key={c.key}>
                        <TableCell className="font-mono text-xs">{c.key}</TableCell>
                        <TableCell className="text-xs max-w-[200px] truncate">
                          {truncateValue(c.current)}
                        </TableCell>
                        <TableCell className="text-xs max-w-[200px] truncate">
                          {truncateValue(c.imported)}
                        </TableCell>
                        <TableCell>
                          <Badge variant={actionBadgeVariant(c.action)}>
                            {c.action}
                          </Badge>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}

            {/* OAuth provider changes */}
            {dryRunResult.oauth_providers.changes.length > 0 && (
              <div className="space-y-2">
                <h4 className="text-sm font-medium">
                  {t('configOps.import.oauthChanges')}
                </h4>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t('configOps.import.slug')}</TableHead>
                      <TableHead>{t('configOps.import.action')}</TableHead>
                      <TableHead>{t('configOps.import.changedFields')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {dryRunResult.oauth_providers.changes.map((c) => (
                      <TableRow key={c.slug}>
                        <TableCell className="font-mono text-xs">{c.slug}</TableCell>
                        <TableCell>
                          <Badge variant={actionBadgeVariant(c.action)}>
                            {c.action}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-xs">
                          {c.changed_fields?.join(', ') || '-'}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}

            {!hasChanges && (
              <p className="text-sm text-muted-foreground">
                {t('configOps.import.noChanges')}
              </p>
            )}
          </div>
        )}

        {/* Import result summary */}
        {importMutation.isSuccess && importMutation.data && (
          <div className="flex items-start gap-2 rounded-md border border-green-500/50 bg-green-500/10 p-3 text-sm">
            <CheckCircle2 className="h-4 w-4 mt-0.5 text-green-600 flex-shrink-0" />
            <span>
              {t('configOps.import.success')}{' '}
              {t('configOps.import.successDetail', {
                settingsApplied: importMutation.data.settings_applied,
                settingsSkipped: importMutation.data.settings_skipped,
                oauthCreated: importMutation.data.oauth_created,
                oauthUpdated: importMutation.data.oauth_updated,
                oauthDeleted: importMutation.data.oauth_deleted,
              })}
            </span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// --- Main Page ---

export function AdminConfigOpsPage() {
  const { t } = useTranslation();
  useDocumentTitle('Admin Config Ops');

  return (
    <>
      <PageHeader
        title={t('configOps.page.title')}
        description={t('configOps.page.description')}
        breadcrumbs={[{ label: t('adminNav.admin'), to: '/admin' }]}
      />
      <div className="space-y-6 mt-6">
        <ExportSection />
        <ImportSection />
      </div>
    </>
  );
}

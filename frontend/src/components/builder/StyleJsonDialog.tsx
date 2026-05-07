import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download, Upload, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useExportMapStyleJson, useImportMapStyleJson } from '@/hooks/use-maps';
import type { MapStyleImportSummary } from '@/types/api';

interface StyleJsonDialogProps {
  mapId: string;
  mapName?: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function styleFilename(mapName?: string | null) {
  const safe = (mapName || 'map')
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'map';
  return `${safe}.style.json`;
}

function downloadJson(filename: string, data: Record<string, unknown>) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function ImportSummary({ summary }: { summary: MapStyleImportSummary }) {
  const { t } = useTranslation('builder');
  return (
    <div className="space-y-2 rounded border bg-muted/30 p-3 text-xs">
      <div className="flex items-center gap-2 font-medium">
        <CheckCircle2 className="h-3.5 w-3.5 text-success" />
        {t('styleJson.summary.imported', { count: summary.layers_imported })}
      </div>
      <div className="text-muted-foreground">
        {t('styleJson.summary.matched', { count: summary.sources_matched })};
        {' '}{t('styleJson.summary.skipped', { count: summary.layers_skipped })}
      </div>
      {summary.warnings.length > 0 && (
        <div className="space-y-1">
          {summary.warnings.map((warning, index) => (
            <div key={`${warning.code}-${index}`} className="flex items-start gap-1.5 text-warning-foreground">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{warning.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function StyleJsonDialog({ mapId, mapName, open, onOpenChange }: StyleJsonDialogProps) {
  const { t } = useTranslation('builder');
  const exportStyle = useExportMapStyleJson();
  const importStyle = useImportMapStyleJson();
  const [jsonText, setJsonText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<MapStyleImportSummary | null>(null);
  const filename = useMemo(() => styleFilename(mapName), [mapName]);

  async function handleExport() {
    const style = await exportStyle.mutateAsync(mapId);
    downloadJson(filename, style);
  }

  async function handleImport() {
    setError(null);
    setSummary(null);
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(jsonText) as Record<string, unknown>;
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        setError(t('styleJson.errors.notObject'));
        return;
      }
    } catch {
      setError(t('styleJson.errors.invalidJson'));
      return;
    }
    try {
      const result = await importStyle.mutateAsync(parsed);
      setSummary(result.summary);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('styleJson.errors.importFailed'));
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('styleJson.title')}</DialogTitle>
          <DialogDescription>
            {t('styleJson.description')}
          </DialogDescription>
        </DialogHeader>
        <Tabs defaultValue="export">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="export">{t('styleJson.tabs.export')}</TabsTrigger>
            <TabsTrigger value="import">{t('styleJson.tabs.import')}</TabsTrigger>
          </TabsList>
          <TabsContent value="export" className="space-y-3 pt-3">
            <div className="rounded border bg-muted/30 p-3 text-sm text-muted-foreground">
              {t('styleJson.exportHint', { filename })}
            </div>
            <Button onClick={handleExport} disabled={exportStyle.isPending} className="gap-2">
              <Download className="h-4 w-4" />
              {t('styleJson.exportButton')}
            </Button>
          </TabsContent>
          <TabsContent value="import" className="space-y-3 pt-3">
            <textarea
              className="min-h-48 w-full resize-y rounded border bg-background p-2 font-mono text-xs outline-none focus:ring-2 focus:ring-ring"
              value={jsonText}
              onChange={(event) => {
                setJsonText(event.target.value);
                setError(null);
                setSummary(null);
              }}
              placeholder='{"version":8,"sources":{},"layers":[]}'
              aria-label={t('styleJson.ariaLabel')}
              data-testid="style-json-input"
              spellCheck={false}
            />
            {error && (
              <div className="flex items-start gap-2 rounded border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}
            {summary && <ImportSummary summary={summary} />}
            <Button onClick={handleImport} disabled={importStyle.isPending || !jsonText.trim()} className="gap-2">
              <Upload className="h-4 w-4" />
              {t('styleJson.importButton')}
            </Button>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

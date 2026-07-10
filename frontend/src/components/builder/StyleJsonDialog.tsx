import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router';
import { Download, Upload, AlertTriangle, CheckCircle2, Info, ExternalLink } from 'lucide-react';
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
import type { MapStyleImportResponse, MapStyleImportSummary } from '@/types/api';
import { Textarea } from '@/components/ui/textarea';

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
    <div className="space-y-2 rounded-sm border bg-muted/30 p-3 text-xs">
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
  const navigate = useNavigate();
  const exportStyle = useExportMapStyleJson();
  const importStyle = useImportMapStyleJson();
  const [jsonText, setJsonText] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MapStyleImportResponse | null>(null);
  const filename = useMemo(() => styleFilename(mapName), [mapName]);

  async function handleExport() {
    const style = await exportStyle.mutateAsync(mapId);
    downloadJson(filename, style);
  }

  async function handleImport() {
    setError(null);
    setResult(null);
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
      const imported = await importStyle.mutateAsync(parsed);
      setResult(imported);
    } catch (err) {
      setError(err instanceof Error ? err.message : t('styleJson.errors.importFailed'));
    }
  }

  function openNewMap(newMapId: string) {
    onOpenChange(false);
    navigate(`/maps/${newMapId}`);
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
            <div className="rounded-sm border bg-muted/30 p-3 text-sm text-muted-foreground">
              {t('styleJson.exportHint', { filename })}
            </div>
            <Button onClick={handleExport} disabled={exportStyle.isPending} className="gap-2">
              <Download className="h-4 w-4" />
              {t('styleJson.exportButton')}
            </Button>
          </TabsContent>
          <TabsContent value="import" className="space-y-3 pt-3">
            <div className="flex items-start gap-2 rounded-sm border bg-muted/30 p-3 text-xs text-muted-foreground">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{t('styleJson.importHint')}</span>
            </div>
            <Textarea
              className="min-h-48 resize-y font-mono text-xs"
              value={jsonText}
              onChange={(event) => {
                setJsonText(event.target.value);
                setError(null);
                setResult(null);
              }}
              placeholder='{"version":8,"sources":{},"layers":[]}'
              aria-label={t('styleJson.ariaLabel')}
              data-testid="style-json-input"
              spellCheck={false}
            />
            {error && (
              <div className="flex items-start gap-2 rounded-sm border border-destructive/40 bg-destructive/10 p-2 text-xs text-destructive">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                <span>{error}</span>
              </div>
            )}
            {result && (
              <div className="space-y-2">
                <ImportSummary summary={result.summary} />
                <div className="flex items-center justify-between gap-2 rounded-sm border border-success/40 bg-success/10 p-2 text-xs">
                  <span className="text-muted-foreground">
                    {t('styleJson.summary.newMap', { name: result.map.name })}
                  </span>
                  <Button
                    size="sm"
                    variant="outline"
                    className="gap-1.5"
                    onClick={() => openNewMap(result.map.id)}
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                    {t('styleJson.openNewMap')}
                  </Button>
                </div>
              </div>
            )}
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

import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Sparkles, Loader2 } from 'lucide-react';
import { useCreateMap } from '@/hooks/use-maps';
import { streamGenerateMap } from '@/api/maps';
import { queryKeys } from '@/lib/query-keys';
import { useAIAvailability } from '@/hooks/use-ai-availability';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

interface MapCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function MapCreateDialog({ open, onOpenChange }: MapCreateDialogProps) {
  const { t, i18n } = useTranslation('builder');
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [aiPrompt, setAiPrompt] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [progressLabel, setProgressLabel] = useState('');
  const [generateError, setGenerateError] = useState<string | null>(null);
  const createMap = useCreateMap();
  const { isAIAvailable: aiAvailable } = useAIAvailability();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const inflightRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (open) {
      setName('');
      setDescription('');
      setAiPrompt('');
      setIsGenerating(false);
      setProgressLabel('');
      setGenerateError(null);
      createMap.reset();
    } else {
      // Closing the dialog cancels any in-flight stream so the SSE consumer
      // doesn't keep firing setState on an unmounted form.
      abortRef.current?.abort();
      abortRef.current = null;
      inflightRef.current = false;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  async function handleManualSubmit(e: React.FormEvent) {
    e.preventDefault();
    try {
      const newMap = await createMap.mutateAsync({
        name: name.trim(),
        description: description.trim() || null,
      });
      onOpenChange(false);
      toast.success(t('mapCreate.mapCreated'));
      navigate(`/maps/${newMap.id}`);
    } catch {
      toast.error(t('mapCreate.createFailed'));
    }
  }

  const handleAiGenerate = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    // Synchronous guard against same-tick double-fire (StrictMode dev double-
    // invoke, browser double-submit, etc.) — setIsGenerating is async so the
    // disabled button alone can't block a second submit dispatched in the
    // same render cycle.
    if (inflightRef.current) return;
    inflightRef.current = true;
    const controller = new AbortController();
    abortRef.current = controller;
    setIsGenerating(true);
    setProgressLabel('');
    setGenerateError(null);

    try {
      for await (const { event, data } of streamGenerateMap({
        prompt: aiPrompt.trim(),
        language: i18n.language,
      }, controller.signal)) {
        if (event === 'tool_start') {
          setProgressLabel((data as { label?: string }).label ?? '');
        } else if (event === 'done') {
          const result = data as {
            map_id: string;
            map_name: string;
            explanation: string;
            datasets_used: string[];
          };
          qc.invalidateQueries({ queryKey: queryKeys.maps.all });
          toast.success(
            t('mapCreate.mapCreatedWithDatasets', { count: result.datasets_used.length }),
            { description: result.explanation, duration: 8000 },
          );
          onOpenChange(false);
          navigate(`/maps/${result.map_id}`);
          return;
        } else if (event === 'error') {
          setGenerateError((data as { message?: string }).message ?? t('mapCreate.generateFailed'));
          return;
        }
      }
      // Stream ended without done event
      setGenerateError(t('mapCreate.generateFailed'));
    } catch (err) {
      // Aborted (dialog closed or unmounted mid-stream) — swallow silently.
      if (err instanceof DOMException && err.name === 'AbortError') return;
      if (controller.signal.aborted) return;
      setGenerateError(err instanceof Error ? err.message : t('mapCreate.generateFailed'));
    } finally {
      setIsGenerating(false);
      setProgressLabel('');
      inflightRef.current = false;
      if (abortRef.current === controller) abortRef.current = null;
    }
  }, [aiPrompt, i18n.language, navigate, onOpenChange, qc, t]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('mapCreate.title')}</DialogTitle>
          <DialogDescription>
            {aiAvailable
              ? t('mapCreate.descriptionAI')
              : t('mapCreate.description')}
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="manual">
          <TabsList className="w-full">
            <TabsTrigger value="manual">{t('mapCreate.tabManual')}</TabsTrigger>
            {aiAvailable && (
              <TabsTrigger value="ai">
                <Sparkles className="me-1 size-3.5" />
                {t('mapCreate.tabAI')}
                <Badge variant="outline" className="ms-1.5 border-warning/50 px-1.5 py-0 text-[10px] font-medium text-warning">
                  {t('chat.experimental')}
                </Badge>
              </TabsTrigger>
            )}
          </TabsList>

          <TabsContent value="manual">
            <form onSubmit={handleManualSubmit} className="space-y-4 pt-2">
              <div className="space-y-2">
                <Label htmlFor="map-name">{t('mapCreate.nameLabel')}</Label>
                <Input
                  id="map-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={t('mapCreate.namePlaceholder')}
                  required
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="map-description">{t('mapCreate.descriptionLabel')}</Label>
                <textarea
                  id="map-description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={3}
                  placeholder={t('mapCreate.descriptionPlaceholder')}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              </div>

              {createMap.error && (
                <p className="text-sm text-destructive">
                  {createMap.error instanceof Error
                    ? createMap.error.message
                    : t('mapCreate.createFailed')}
                </p>
              )}

              <DialogFooter>
                <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                  {t('common:cancel')}
                </Button>
                <Button
                  type="submit"
                  disabled={createMap.isPending || !name.trim()}
                >
                  {createMap.isPending && <Loader2 className="size-4 animate-spin" />}
                  {createMap.isPending ? t('mapCreate.creating') : t('common:create')}
                </Button>
              </DialogFooter>
            </form>
          </TabsContent>

          {aiAvailable && (
            <TabsContent value="ai">
              <form onSubmit={handleAiGenerate} className="space-y-4 pt-2">
                <div className="space-y-2">
                  <Label htmlFor="ai-prompt">{t('mapCreate.aiPromptLabel')}</Label>
                  <textarea
                    id="ai-prompt"
                    value={aiPrompt}
                    onChange={(e) => setAiPrompt(e.target.value)}
                    rows={4}
                    placeholder={t('mapCreate.aiPromptPlaceholder')}
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    disabled={isGenerating}
                  />
                  <p className="text-xs text-muted-foreground">
                    {t('mapCreate.aiHelpText')}
                  </p>
                </div>

                {isGenerating && progressLabel && (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="size-3.5 animate-spin" />
                    <span>{progressLabel}</span>
                  </div>
                )}

                {generateError && (
                  <p className="text-sm text-destructive">{generateError}</p>
                )}

                <DialogFooter>
                  <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                    {t('common:cancel')}
                  </Button>
                  <Button
                    type="submit"
                    disabled={isGenerating || aiPrompt.trim().length < 3}
                  >
                    {isGenerating ? (
                      <>
                        <Loader2 className="me-1.5 size-4 animate-spin" />
                        {t('mapCreate.generating')}
                      </>
                    ) : (
                      <>
                        <Sparkles className="me-1.5 size-4" />
                        {t('mapCreate.generateMap')}
                      </>
                    )}
                  </Button>
                </DialogFooter>
              </form>
            </TabsContent>
          )}
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

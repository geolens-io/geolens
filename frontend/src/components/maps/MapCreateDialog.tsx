import { useState, useEffect, useCallback } from 'react';
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

  useEffect(() => {
    if (open) {
      setName('');
      setDescription('');
      setAiPrompt('');
      setIsGenerating(false);
      setProgressLabel('');
      setGenerateError(null);
      createMap.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

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
    setIsGenerating(true);
    setProgressLabel('');
    setGenerateError(null);

    try {
      for await (const { event, data } of streamGenerateMap({
        prompt: aiPrompt.trim(),
        language: i18n.language,
      })) {
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
      setGenerateError(err instanceof Error ? err.message : t('mapCreate.generateFailed'));
    } finally {
      setIsGenerating(false);
      setProgressLabel('');
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
                <Sparkles className="mr-1 size-3.5" />
                {t('mapCreate.tabAI')}
                <Badge variant="outline" className="ml-1.5 border-warning/50 px-1.5 py-0 text-[10px] font-medium text-warning">
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
                        <Loader2 className="mr-1.5 size-4 animate-spin" />
                        {t('mapCreate.generating')}
                      </>
                    ) : (
                      <>
                        <Sparkles className="mr-1.5 size-4" />
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

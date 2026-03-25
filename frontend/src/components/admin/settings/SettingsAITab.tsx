import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { CheckCircle2, Info, Loader2, XCircle, AlertTriangle, Zap } from 'lucide-react';
import { SettingsFormActions } from './SettingsFormActions';
import { toast } from 'sonner';
import { Switch } from '@/components/ui/switch';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Separator } from '@/components/ui/separator';
import { Badge } from '@/components/ui/badge';
import { SettingSourceBadge } from './SettingSourceBadge';
import { findSetting } from './utils';
import { useApiKeyStatus } from '@/hooks/use-settings';
import { useAIStatus, useEmbeddingStats, useBackfillEmbeddings, useUpdateSemanticSearch } from '@/hooks/use-admin';
import { detectEmbeddingDims } from '@/api/settings';
import type { SettingItem } from '@/api/settings';

interface TabProps {
  settings: SettingItem[];
  envOnly: boolean;
  onSave: (changes: Record<string, unknown>) => void;
  onReset: (key: string) => void;
  isSaving: boolean;
}

export function SettingsAITab({ settings, envOnly, onSave, onReset, isSaving }: TabProps) {
  const { t } = useTranslation('admin');
  const { data: keyStatus } = useApiKeyStatus();
  const { data: aiStatus } = useAIStatus();
  const { data: embeddingStats } = useEmbeddingStats();
  const backfill = useBackfillEmbeddings();
  const semanticToggle = useUpdateSemanticSearch();

  const [aiEnabled, setAiEnabled] = useState(true);
  const [llmProvider, setLlmProvider] = useState('anthropic');
  const [llmModel, setLlmModel] = useState('');
  const [openaiBaseUrl, setOpenaiBaseUrl] = useState('');
  const [embeddingModel, setEmbeddingModel] = useState('');
  const [embeddingBaseUrl, setEmbeddingBaseUrl] = useState('');
  const [embeddingDims, setEmbeddingDims] = useState('');
  const [isDetecting, setIsDetecting] = useState(false);

  const syncFromSettings = useCallback(() => {
    const enabled = findSetting(settings, 'ai_enabled');
    const provider = findSetting(settings, 'llm_provider');
    const model = findSetting(settings, 'llm_model');
    const baseUrl = findSetting(settings, 'openai_base_url');
    const embModel = findSetting(settings, 'embedding_model');
    const embUrl = findSetting(settings, 'embedding_base_url');
    const embDims = findSetting(settings, 'embedding_dims');
    if (enabled) setAiEnabled(enabled.value as boolean);
    if (provider) setLlmProvider(provider.value as string);
    if (model) setLlmModel(model.value as string);
    if (baseUrl) setOpenaiBaseUrl(baseUrl.value as string);
    if (embModel) setEmbeddingModel(embModel.value as string);
    if (embUrl) setEmbeddingBaseUrl(embUrl.value as string);
    if (embDims) setEmbeddingDims(String(embDims.value));
  }, [settings]);

  useEffect(() => {
    syncFromSettings();
  }, [syncFromSettings]);

  function getDirtyFields(): Record<string, unknown> {
    const changes: Record<string, unknown> = {};
    const enabled = findSetting(settings, 'ai_enabled');
    const provider = findSetting(settings, 'llm_provider');
    const model = findSetting(settings, 'llm_model');
    const baseUrl = findSetting(settings, 'openai_base_url');
    const embModel = findSetting(settings, 'embedding_model');
    const embUrl = findSetting(settings, 'embedding_base_url');
    const embDims = findSetting(settings, 'embedding_dims');
    if (enabled && aiEnabled !== enabled.value) changes.ai_enabled = aiEnabled;
    if (provider && llmProvider !== provider.value) changes.llm_provider = llmProvider;
    if (model && llmModel !== model.value) changes.llm_model = llmModel;
    if (baseUrl && openaiBaseUrl !== baseUrl.value) changes.openai_base_url = openaiBaseUrl;
    if (embModel && embeddingModel !== embModel.value) changes.embedding_model = embeddingModel;
    if (embUrl && embeddingBaseUrl !== embUrl.value) changes.embedding_base_url = embeddingBaseUrl;
    if (embDims && String(embeddingDims) !== String(embDims.value)) changes.embedding_dims = Number(embeddingDims);
    return changes;
  }

  const dirty = getDirtyFields();
  const hasDirty = Object.keys(dirty).length > 0;

  const handleSemanticToggle = (checked: boolean) => {
    semanticToggle.mutate(checked);
  };

  const handleBackfill = (force = false) => {
    backfill.mutate(force, {
      onSuccess: (data) => {
        if (data.errors > 0 && data.created === 0) {
          toast.error(t('ai.backfillAllFailed', { errors: data.errors }));
        } else if (data.errors > 0) {
          toast.warning(t('ai.backfillPartial', { created: data.created, errors: data.errors }));
        } else if (data.created > 0) {
          toast.success(t('ai.backfillSuccess', { count: data.created }));
        } else {
          toast.info(t('ai.backfillEmpty'));
        }
      },
    });
  };

  const handleDetectDims = async () => {
    setIsDetecting(true);
    try {
      const result = await detectEmbeddingDims();
      setEmbeddingDims(String(result.dimensions));
      toast.success(t('ai.dimsDetected', { dims: result.dimensions }));
    } catch {
      toast.error(t('ai.dimsDetectFailed'));
    } finally {
      setIsDetecting(false);
    }
  };

  const openaiKeyMissing = keyStatus && !keyStatus.openai_configured;

  // Derive dynamic badge labels based on which keys are configured and provider selection
  const anthropicBadgeLabel = keyStatus?.anthropic_configured
    ? (llmProvider === 'anthropic' ? t('ai.usedForInference') : t('ai.availableNotSelected'))
    : null;
  const openaiUsages: string[] = [];
  if (keyStatus?.openai_configured) {
    if (llmProvider === 'openai_compatible') openaiUsages.push(t('ai.inference'));
    openaiUsages.push(t('ai.embeddings'));
  }

  return (
    <div className="space-y-6">
      {/* --- Inference (LLM) Configuration --- */}
      <div>
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mb-4">
          {t('ai.sectionInference')}
        </h3>

        <div className="flex items-center justify-between max-w-md">
          <div className="space-y-0.5">
            <div className="flex items-center gap-2">
              <Label htmlFor="ai-toggle">{findSetting(settings, 'ai_enabled')?.label ?? t('ai.labels.aiEnabled')}</Label>
              <SettingSourceBadge source={findSetting(settings, 'ai_enabled')?.source ?? 'default'} settingKey="ai_enabled" onReset={onReset} />
            </div>
            <p className="text-sm text-muted-foreground">{t('settings.general.aiFeaturesDescription')}</p>
          </div>
          <Switch
            id="ai-toggle"
            checked={aiEnabled}
            onCheckedChange={setAiEnabled}
            disabled={envOnly}
          />
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Label htmlFor="llm-provider">{findSetting(settings, 'llm_provider')?.label ?? t('ai.labels.llmProvider')}</Label>
          <SettingSourceBadge source={findSetting(settings, 'llm_provider')?.source ?? 'default'} settingKey="llm_provider" onReset={onReset} />
        </div>
        <Select value={llmProvider} onValueChange={setLlmProvider} disabled={envOnly}>
          <SelectTrigger id="llm-provider" className="w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="anthropic">{t('ai.providers.anthropic')}</SelectItem>
            <SelectItem value="openai_compatible">{t('ai.providers.openaiCompatible')}</SelectItem>
          </SelectContent>
        </Select>
        <p className="text-sm text-muted-foreground">{t('ai.providerDescription')}</p>
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Label htmlFor="llm-model">{findSetting(settings, 'llm_model')?.label ?? t('ai.labels.model')}</Label>
          <SettingSourceBadge source={findSetting(settings, 'llm_model')?.source ?? 'default'} settingKey="llm_model" onReset={onReset} />
        </div>
        <Input
          id="llm-model"
          type="text"
          value={llmModel}
          onChange={(e) => setLlmModel(e.target.value)}
          disabled={envOnly}
          className="max-w-sm"
          placeholder={llmProvider === 'anthropic' ? 'claude-sonnet-4-20250514' : 'gpt-4o'}
        />
        <p className="text-sm text-muted-foreground">{t('ai.modelDescription')}</p>
      </div>

      {llmProvider === 'openai_compatible' && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Label htmlFor="openai-base-url">{findSetting(settings, 'openai_base_url')?.label ?? t('ai.labels.openaiBaseUrl')}</Label>
            <SettingSourceBadge source={findSetting(settings, 'openai_base_url')?.source ?? 'default'} settingKey="openai_base_url" onReset={onReset} />
          </div>
          <Input
            id="openai-base-url"
            type="text"
            value={openaiBaseUrl}
            onChange={(e) => setOpenaiBaseUrl(e.target.value)}
            disabled={envOnly}
            placeholder="https://api.openai.com/v1"
            className="max-w-md"
          />
          <p className="text-sm text-muted-foreground">{t('ai.baseUrlDescription')}</p>
        </div>
      )}

      <Separator />

      {/* --- Semantic Search & Embeddings --- */}
      <div>
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mb-4">
          {t('ai.sectionSemanticSearch')}
        </h3>

        <div className="space-y-5">
          {/* Semantic search toggle */}
          <div className="flex items-center justify-between max-w-md">
            <div className="space-y-0.5">
              <Label htmlFor="semantic-toggle">{t('ai.semanticSearch')}</Label>
              <p className="text-sm text-muted-foreground">{t('ai.semanticSearchDescription')}</p>
            </div>
            <Switch
              id="semantic-toggle"
              checked={aiStatus?.semantic_search_enabled ?? false}
              onCheckedChange={handleSemanticToggle}
              disabled={semanticToggle.isPending}
            />
          </div>

          {/* Embedding model config */}
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Label htmlFor="embedding-model">{findSetting(settings, 'embedding_model')?.label ?? t('ai.labels.embeddingModel')}</Label>
              <SettingSourceBadge source={findSetting(settings, 'embedding_model')?.source ?? 'default'} settingKey="embedding_model" onReset={onReset} />
            </div>
            <Input
              id="embedding-model"
              type="text"
              value={embeddingModel}
              onChange={(e) => setEmbeddingModel(e.target.value)}
              disabled={envOnly}
              className="max-w-sm"
              placeholder="text-embedding-3-small"
            />
            <p className="text-sm text-muted-foreground">{t('ai.embeddingModelDescription')}</p>
          </div>

          {/* Embedding base URL */}
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Label htmlFor="embedding-base-url">{findSetting(settings, 'embedding_base_url')?.label ?? t('ai.labels.embeddingBaseUrl')}</Label>
              <SettingSourceBadge source={findSetting(settings, 'embedding_base_url')?.source ?? 'default'} settingKey="embedding_base_url" onReset={onReset} />
            </div>
            <Input
              id="embedding-base-url"
              type="text"
              value={embeddingBaseUrl}
              onChange={(e) => setEmbeddingBaseUrl(e.target.value)}
              disabled={envOnly}
              placeholder="https://api.openai.com/v1"
              className="max-w-md"
            />
            <p className="text-sm text-muted-foreground">{t('ai.embeddingBaseUrlDescription')}</p>
          </div>

          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Label htmlFor="embedding-dims">{findSetting(settings, 'embedding_dims')?.label ?? t('ai.labels.embeddingDims')}</Label>
              <SettingSourceBadge source={findSetting(settings, 'embedding_dims')?.source ?? 'default'} settingKey="embedding_dims" onReset={onReset} />
            </div>
            <div className="flex items-center gap-3">
              <Input
                id="embedding-dims"
                type="number"
                value={embeddingDims}
                onChange={(e) => setEmbeddingDims(e.target.value)}
                disabled={envOnly}
                className="w-32 font-mono tabular-nums"
                min={1}
              />
              <Button
                variant="outline"
                size="sm"
                onClick={handleDetectDims}
                disabled={isDetecting || envOnly || !keyStatus?.openai_configured}
              >
                {isDetecting ? (
                  <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                ) : (
                  <Zap className="mr-1.5 h-3 w-3" />
                )}
                {t('ai.detectDims')}
              </Button>
            </div>
            <p className="text-sm text-muted-foreground">{t('ai.embeddingDimsAutoDescription')}</p>
            {/* Dimension change warning when embeddings exist */}
            {embeddingStats && embeddingStats.embedded_records > 0 &&
              findSetting(settings, 'embedding_dims') &&
              String(embeddingDims) !== String(findSetting(settings, 'embedding_dims')!.value) && (
              <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 p-3">
                <AlertTriangle className="h-4 w-4 text-amber-500 mt-0.5 flex-shrink-0" />
                <p className="text-sm text-amber-700 dark:text-amber-400">
                  {t('ai.dimsChangeWarning', {
                    count: embeddingStats.embedded_records,
                    defaultValue: 'Changing dimensions will make {{count}} existing embedding(s) incompatible. You will need to regenerate all embeddings after saving.',
                  })}
                </p>
              </div>
            )}
          </div>

          {/* OpenAI key warning */}
          {openaiKeyMissing && (
            <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 p-3 max-w-md">
              <AlertTriangle className="h-4 w-4 text-amber-500 mt-0.5 flex-shrink-0" />
              <p className="text-sm text-amber-700 dark:text-amber-400">
                {t('ai.openaiKeyRequired')}
              </p>
            </div>
          )}

          {/* Embedding coverage */}
          {embeddingStats && (
            <div className="rounded-lg border p-4 max-w-md space-y-3">
              <div className="flex items-center justify-between text-sm">
                <span className="font-medium">{t('ai.embeddingCoverage')}</span>
                <span className="text-muted-foreground tabular-nums">
                  {embeddingStats.embedded_records}/{embeddingStats.total_records} ({embeddingStats.coverage_percent}%)
                </span>
              </div>
              <div className="h-2 rounded-full bg-muted overflow-hidden">
                <div
                  className="h-full rounded-full bg-primary transition-all"
                  style={{ width: `${embeddingStats.coverage_percent}%` }}
                />
              </div>
              <div className="flex gap-2">
                {embeddingStats.missing_records > 0 && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="flex-1"
                    onClick={() => handleBackfill(false)}
                    disabled={backfill.isPending}
                  >
                    {backfill.isPending ? (
                      <>
                        <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                        {t('ai.generating')}
                      </>
                    ) : (
                      t('ai.generateMissing')
                    )}
                  </Button>
                )}
                {embeddingStats.embedded_records > 0 && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="flex-1"
                    onClick={() => handleBackfill(true)}
                    disabled={backfill.isPending}
                  >
                    {backfill.isPending ? (
                      <>
                        <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                        {t('ai.generating')}
                      </>
                    ) : (
                      t('ai.regenerateAll')
                    )}
                  </Button>
                )}
              </div>
              {embeddingStats.missing_records === 0 && embeddingStats.embedded_records > 0 && (
                <p className="text-xs text-muted-foreground text-center">{t('ai.allEmbedded')}</p>
              )}
            </div>
          )}
        </div>
      </div>

      <Separator />

      {/* --- API Key Status --- */}
      <div>
        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wide mb-4">
          {t('ai.sectionApiKeys')}
        </h3>
        <div className="flex items-start gap-2 rounded-md border border-border bg-muted/30 p-3 max-w-md mb-4">
          <Info className="h-4 w-4 text-muted-foreground mt-0.5 flex-shrink-0" />
          <p className="text-sm text-muted-foreground">
            {t('ai.apiKeysEnvOnlyNote')}
          </p>
        </div>
        {keyStatus && (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm">
              {keyStatus.anthropic_configured ? (
                <CheckCircle2 className="h-4 w-4 text-green-500" />
              ) : (
                <XCircle className="h-4 w-4 text-muted-foreground" />
              )}
              <span className={keyStatus.anthropic_configured ? '' : 'text-muted-foreground'}>
                ANTHROPIC_API_KEY {keyStatus.anthropic_configured ? t('ai.keyConfigured') : t('ai.keyNotSet')}
              </span>
              {anthropicBadgeLabel && (
                <Badge variant="secondary" className="text-xs">{anthropicBadgeLabel}</Badge>
              )}
            </div>
            <div className="flex items-center gap-2 text-sm">
              {keyStatus.openai_configured ? (
                <CheckCircle2 className="h-4 w-4 text-green-500" />
              ) : (
                <XCircle className="h-4 w-4 text-muted-foreground" />
              )}
              <span className={keyStatus.openai_configured ? '' : 'text-muted-foreground'}>
                OPENAI_API_KEY {keyStatus.openai_configured ? t('ai.keyConfigured') : t('ai.keyNotSet')}
              </span>
              {openaiUsages.length > 0 && (
                <Badge variant="secondary" className="text-xs">{openaiUsages.join(' + ')}</Badge>
              )}
            </div>
          </div>
        )}
      </div>

      <Separator />

      <SettingsFormActions dirty={dirty} hasDirty={hasDirty} envOnly={envOnly} isSaving={isSaving} onSave={onSave} onDiscard={syncFromSettings} />
    </div>
  );
}

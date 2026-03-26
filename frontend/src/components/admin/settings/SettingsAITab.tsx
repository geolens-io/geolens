import { useState } from 'react';
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
import { useSettingsForm } from './useSettingsForm';
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
  onDirtyChange?: (dirty: boolean) => void;
}

const AI_FIELDS = [
  { key: 'ai_enabled', defaultValue: true },
  { key: 'ai_send_sample_values', defaultValue: true },
  { key: 'llm_provider', defaultValue: 'anthropic' },
  { key: 'llm_model', defaultValue: '' },
  { key: 'openai_base_url', defaultValue: '' },
  { key: 'embedding_model', defaultValue: '' },
  { key: 'embedding_base_url', defaultValue: '' },
  { key: 'embedding_dims', defaultValue: '0', coerce: String },
] as const;

export function SettingsAITab({ settings, envOnly, onSave, onReset, isSaving, onDirtyChange }: TabProps) {
  const { t } = useTranslation('admin');
  const { data: keyStatus } = useApiKeyStatus();
  const { data: aiStatus } = useAIStatus();
  const { data: embeddingStats } = useEmbeddingStats();
  const backfill = useBackfillEmbeddings();
  const semanticToggle = useUpdateSemanticSearch();

  const { values, setters, dirty, hasDirty, discard } = useSettingsForm(settings, AI_FIELDS);
  const [isDetecting, setIsDetecting] = useState(false);

  // Alias for readability in JSX
  const aiEnabled = values.ai_enabled as boolean;
  const sendSampleValues = values.ai_send_sample_values as boolean;
  const llmProvider = values.llm_provider as string;
  const llmModel = values.llm_model as string;
  const openaiBaseUrl = values.openai_base_url as string;
  const embeddingModel = values.embedding_model as string;
  const embeddingBaseUrl = values.embedding_base_url as string;
  const embeddingDims = values.embedding_dims as string;

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
      setters.embedding_dims(String(result.dimensions));
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
            onCheckedChange={setters.ai_enabled}
            disabled={envOnly}
          />
        </div>

        <div className="flex items-center justify-between max-w-md">
          <div className="space-y-0.5">
            <div className="flex items-center gap-2">
              <Label htmlFor="sample-values-toggle">{findSetting(settings, 'ai_send_sample_values')?.label ?? t('ai.labels.sendSampleValues')}</Label>
              <SettingSourceBadge source={findSetting(settings, 'ai_send_sample_values')?.source ?? 'default'} settingKey="ai_send_sample_values" onReset={onReset} />
            </div>
            <p className="text-sm text-muted-foreground">{t('ai.sendSampleValuesDescription')}</p>
          </div>
          <Switch
            id="sample-values-toggle"
            checked={sendSampleValues}
            onCheckedChange={setters.ai_send_sample_values}
            disabled={envOnly}
          />
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Label htmlFor="llm-provider">{findSetting(settings, 'llm_provider')?.label ?? t('ai.labels.llmProvider')}</Label>
          <SettingSourceBadge source={findSetting(settings, 'llm_provider')?.source ?? 'default'} settingKey="llm_provider" onReset={onReset} />
        </div>
        <Select value={llmProvider} onValueChange={setters.llm_provider} disabled={envOnly}>
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
          onChange={(e) => setters.llm_model(e.target.value)}
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
            onChange={(e) => setters.openai_base_url(e.target.value)}
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
              onChange={(e) => setters.embedding_model(e.target.value)}
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
              onChange={(e) => setters.embedding_base_url(e.target.value)}
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
                onChange={(e) => setters.embedding_dims(e.target.value)}
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

      <SettingsFormActions dirty={dirty} hasDirty={hasDirty} envOnly={envOnly} isSaving={isSaving} onSave={onSave} onDiscard={discard} onDirtyChange={onDirtyChange} />
    </div>
  );
}

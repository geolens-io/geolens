import { useEffect, useState } from 'react';
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
import {
  useEmbeddingStats,
  useBackfillEmbeddings,
  useBackfillJobStatus,
  useUpdateSemanticSearch,
} from '@/hooks/use-admin';
import { usePermissions } from '@/hooks/use-permissions';
import { useAIStatusReader } from '@/hooks/use-ai-status-reader';
import { detectEmbeddingDims } from '@/api/settings';
import type { SettingItem } from '@/api/settings';
import { probeAIStatus } from '@/api/admin';
import type { AIProbeCheck, AIProbeReport } from '@/types/api';

interface TabProps {
  settings: SettingItem[];
  envOnly: boolean;
  onSave: (changes: Record<string, unknown>) => void;
  onReset: (key: string) => void;
  isSaving: boolean;
  saveFailed?: boolean;
  onDirtyChange?: (dirty: boolean) => void;
}

const AI_FIELDS = [
  { key: 'ai_enabled', defaultValue: true },
  { key: 'ai_send_sample_values', defaultValue: true },
  { key: 'max_ai_tokens_per_user_per_day', defaultValue: 0 },
  { key: 'llm_provider', defaultValue: 'anthropic' },
  { key: 'llm_model', defaultValue: '' },
  { key: 'openai_base_url', defaultValue: '' },
  { key: 'embedding_model', defaultValue: '' },
  { key: 'embedding_base_url', defaultValue: '' },
  { key: 'embedding_dims', defaultValue: '0', coerce: String },
] as const;

export function SettingsAITab({ settings, envOnly, onSave, onReset, isSaving, saveFailed, onDirtyChange }: TabProps) {
  const { t } = useTranslation('admin');
  const { can } = usePermissions();
  const canManageUsers = can('manage_users');
  // fix(#653): the #652 inline gate moved into the shared useAIStatusReader
  // hook so ai-status surfaces can't drift from require_ai_status_reader again.
  const canProbe = useAIStatusReader();
  const { data: keyStatus } = useApiKeyStatus();
  // Coverage/backfill are manage_users operations in BOTH tenancy modes
  // (see /admin/embedding-stats + /admin/backfill-embeddings) — deliberately
  // NOT useAIStatusReader (#653). A settings-only operator can configure
  // embeddings without issuing forbidden operational probes.
  const { data: embeddingStatsData } = useEmbeddingStats({ enabled: canManageUsers });
  const embeddingStats = canManageUsers ? embeddingStatsData : undefined;
  const backfill = useBackfillEmbeddings();
  // fix(#1550 review P2): the id of the run this page queued, polled to its
  // terminal state so the coverage figure above refreshes when it lands.
  const [backfillJobId, setBackfillJobId] = useState<string | null>(null);
  const backfillJob = useBackfillJobStatus(backfillJobId);
  const backfillRunning =
    backfillJob.data?.status === 'pending' || backfillJob.data?.status === 'running';
  const semanticToggle = useUpdateSemanticSearch();

  const { values, setters, dirty, hasDirty, discard } = useSettingsForm(settings, AI_FIELDS, isSaving, saveFailed);
  const [isDetecting, setIsDetecting] = useState(false);
  const [isProbing, setIsProbing] = useState(false);
  const [probe, setProbe] = useState<AIProbeReport | null>(null);

  // fix(#652): probe results describe the PERSISTED config — drop them when
  // the saved settings change underneath us (e.g. after a Save reload).
  useEffect(() => {
    setProbe(null);
  }, [settings]);

  // Alias for readability in JSX
  const aiEnabled = values.ai_enabled as boolean;
  const sendSampleValues = values.ai_send_sample_values as boolean;
  const maxAiTokensPerDay = values.max_ai_tokens_per_user_per_day as number;
  const llmProvider = values.llm_provider as string;
  const llmModel = values.llm_model as string;
  const openaiBaseUrl = values.openai_base_url as string;
  const embeddingModel = values.embedding_model as string;
  const embeddingBaseUrl = values.embedding_base_url as string;
  const embeddingDims = values.embedding_dims as string;
  const semanticSearchEnabled = Boolean(
    findSetting(settings, 'semantic_search_enabled')?.value,
  );

  const handleSemanticToggle = (checked: boolean) => {
    semanticToggle.mutate(checked);
  };

  const handleBackfill = (force = false) => {
    if (!canManageUsers) return;
    // fix(#1542): the run is queued now, not done by the time this resolves —
    // a full regenerate takes minutes and used to hold the request open past
    // the 600s edge timeout. There are no counts to report yet.
    // fix(#1550 review P2): keep the job id so the run is actually tracked to
    // its end, rather than acknowledged and forgotten.
    backfill.mutate(force, {
      onSuccess: (data) => {
        setBackfillJobId(data.job_id);
        toast.info(t('ai.backfillQueued'));
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

  const handleTestConnection = async () => {
    setIsProbing(true);
    // fix(#652): drop previous rows first so a failed retry can't keep
    // showing stale green results next to only a toast.
    setProbe(null);
    try {
      const result = await probeAIStatus();
      setProbe(result.probe ?? null);
    } catch {
      toast.error(t('ai.testConnectionFailed'));
    } finally {
      setIsProbing(false);
    }
  };

  const probeRow = (label: string, check: AIProbeCheck) => (
    <div className="flex items-center gap-2 text-sm">
      {!check.configured ? (
        <XCircle className="h-4 w-4 text-muted-foreground" />
      ) : check.ok ? (
        <CheckCircle2 className="h-4 w-4 text-success" />
      ) : (
        <XCircle className="h-4 w-4 text-destructive" />
      )}
      <span>{label}</span>
      <span className="text-muted-foreground">
        {!check.configured
          ? t('ai.keyNotSet')
          : check.ok
            ? t('ai.probeOk')
            : (check.error ?? t('ai.probeFailed'))}
      </span>
    </div>
  );

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
      <div className="space-y-4">
        <h3 className="eyebrow mb-4">
          {t('ai.sectionInference')}
        </h3>

        <div className="flex items-center justify-between max-w-md">
          <div className="space-y-0.5">
            <div className="flex items-center gap-2">
              <Label htmlFor="ai-toggle">{t('ai.labels.aiEnabled')}</Label>
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
              <Label htmlFor="sample-values-toggle">{t('ai.labels.sendSampleValues')}</Label>
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

        <div className="space-y-2 max-w-md">
          <div className="flex items-center gap-2">
            <Label htmlFor="max-ai-tokens-per-day">
              {t('ai.labels.maxAiTokensPerDay')}
            </Label>
            <SettingSourceBadge
              source={findSetting(settings, 'max_ai_tokens_per_user_per_day')?.source ?? 'default'}
              settingKey="max_ai_tokens_per_user_per_day"
              onReset={onReset}
            />
          </div>
          <Input
            id="max-ai-tokens-per-day"
            type="number"
            min={0}
            className="w-56"
            value={maxAiTokensPerDay}
            onChange={(e) => setters.max_ai_tokens_per_user_per_day(Number(e.target.value))}
            disabled={envOnly}
          />
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Label htmlFor="llm-provider">{t('ai.labels.llmProvider')}</Label>
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
          <Label htmlFor="llm-model">{t('ai.labels.model')}</Label>
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
            <Label htmlFor="openai-base-url">{t('ai.labels.openaiBaseUrl')}</Label>
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
        <h3 className="eyebrow mb-4">
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
              checked={semanticSearchEnabled}
              onCheckedChange={handleSemanticToggle}
              disabled={semanticToggle.isPending}
            />
          </div>

          {/* Embedding model config */}
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Label htmlFor="embedding-model">{t('ai.labels.embeddingModel')}</Label>
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
              <Label htmlFor="embedding-base-url">{t('ai.labels.embeddingBaseUrl')}</Label>
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
              <Label htmlFor="embedding-dims">{t('ai.labels.embeddingDims')}</Label>
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
                  <Loader2 className="me-1.5 h-3 w-3 animate-spin" />
                ) : (
                  <Zap className="me-1.5 h-3 w-3" />
                )}
                {t('ai.detectDims')}
              </Button>
            </div>
            <p className="text-sm text-muted-foreground">{t('ai.embeddingDimsAutoDescription')}</p>
            {/* Dimension change warning when embeddings exist */}
            {embeddingStats && embeddingStats.embedded_records > 0 &&
              findSetting(settings, 'embedding_dims') &&
              String(embeddingDims) !== String(findSetting(settings, 'embedding_dims')!.value) && (
              <div className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning/5 p-3">
                <AlertTriangle className="h-4 w-4 text-warning mt-0.5 flex-shrink-0" />
                <p className="text-sm text-foreground">
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
            <div className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning/5 p-3 max-w-md">
              <AlertTriangle className="h-4 w-4 text-warning mt-0.5 flex-shrink-0" />
              <p className="text-sm text-foreground">
                {t('ai.openaiKeyRequired')}
              </p>
            </div>
          )}

          {/* Embedding coverage */}
          {canManageUsers && embeddingStats && (
            <div className="rounded-lg border p-4 max-w-md space-y-3">
              <div className="flex items-center justify-between text-sm">
                <span className="font-medium">{t('ai.embeddingCoverage')}</span>
                <span className="text-muted-foreground tabular-nums">
                  {embeddingStats.embedded_records}/{embeddingStats.total_records} ({embeddingStats.coverage_percent}%)
                </span>
              </div>
              <div className="h-2 rounded-full bg-muted overflow-hidden">
                <div
                  className="h-full rounded-full bg-primary transition-[width] duration-300 ease-out"
                  style={{ width: `${embeddingStats.coverage_percent}%` }}
                />
              </div>
              <div className="flex gap-2">
                {/* fix(#1506): the non-force backfill now selects on "no
                    vector under the ACTIVE model", so it covers stale records
                    too — the #1503 gate that subtracted them hid this button
                    on the one catalog state it can fix most cheaply. */}
                {embeddingStats.missing_records > 0 && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="flex-1"
                    onClick={() => handleBackfill(false)}
                    disabled={backfill.isPending || backfillRunning}
                  >
                    {backfill.isPending && backfill.variables === false ? (
                      <>
                        <Loader2 className="me-2 h-3 w-3 animate-spin" />
                        {t('ai.generating')}
                      </>
                    ) : (
                      t('ai.generateMissing')
                    )}
                  </Button>
                )}
                {/* fix(#1503): stale rows keep this button reachable. After a
                    model swap embedded_records drops to 0, and Regenerate All
                    is the only control that clears the superseded vectors. */}
                {(embeddingStats.embedded_records > 0 || embeddingStats.stale_records > 0) && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="flex-1"
                    onClick={() => handleBackfill(true)}
                    disabled={backfill.isPending || backfillRunning}
                  >
                    {backfill.isPending && backfill.variables === true ? (
                      <>
                        <Loader2 className="me-2 h-3 w-3 animate-spin" />
                        {t('ai.generating')}
                      </>
                    ) : (
                      t('ai.regenerateAll')
                    )}
                  </Button>
                )}
              </div>
              {embeddingStats.stale_records > 0 && (
                <div className="flex items-start gap-2 rounded-md border border-warning/30 bg-warning/5 p-3">
                  <AlertTriangle className="h-4 w-4 text-warning mt-0.5 flex-shrink-0" />
                  <p className="text-sm text-foreground">
                    {/* fix(#1506): Generate Missing re-embeds these without
                        touching the records the active model already covers,
                        so it is the cheaper remedy and named first. It adds
                        the current-model vector and leaves the superseded row
                        in place; Regenerate All is what deletes those. */}
                    {t('ai.staleEmbeddingsWarning', {
                      count: embeddingStats.stale_records,
                      defaultValue: '{{count}} embedding(s) were generated by a different model and cannot be used by semantic search. Generate missing embeddings to re-embed just those records, or regenerate all to also delete the superseded vectors.',
                    })}
                  </p>
                </div>
              )}
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
        <h3 className="eyebrow mb-4">
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
                <CheckCircle2 className="h-4 w-4 text-success" />
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
                <CheckCircle2 className="h-4 w-4 text-success" />
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

        {/* feat(#635): live probe — a settings-only operator would 403 on the
            probe endpoint; hide rather than dangle a dead button. */}
        {canProbe && (
          <div className="mt-4 space-y-2">
            {/* fix(#652): the probe resolves PERSISTED settings — block it while
                the form is dirty so green results can't vouch for unsaved edits. */}
            <Button
              variant="outline"
              size="sm"
              onClick={handleTestConnection}
              disabled={isProbing || hasDirty}
            >
              {isProbing ? (
                <Loader2 className="me-1.5 h-3 w-3 animate-spin" />
              ) : (
                <Zap className="me-1.5 h-3 w-3" />
              )}
              {isProbing ? t('ai.testing') : t('ai.testConnection')}
            </Button>
            <p className="text-sm text-muted-foreground max-w-md">
              {hasDirty ? t('ai.testConnectionDirty') : t('ai.testConnectionDescription')}
            </p>
            {/* fix(#652): hide (not clear) while dirty — a Discard restores
                exactly the config these rows were probed against. */}
            {probe && !hasDirty && (
              <div className="space-y-1.5 pt-1">
                {probeRow(t('ai.inference'), probe.chat)}
                {probeRow(t('ai.embeddings'), probe.embeddings)}
              </div>
            )}
          </div>
        )}
      </div>

      <Separator />

      <SettingsFormActions dirty={dirty} hasDirty={hasDirty} envOnly={envOnly} isSaving={isSaving} onSave={onSave} onDiscard={discard} onDirtyChange={onDirtyChange} />
    </div>
  );
}

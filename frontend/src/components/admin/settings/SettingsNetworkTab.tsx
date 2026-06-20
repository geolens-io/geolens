import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { SettingSourceBadge } from './SettingSourceBadge';
import { SettingsFormActions } from './SettingsFormActions';
import { findSetting } from './utils';
import { useSettingsForm } from './useSettingsForm';
import { useNotificationStatus, useSendTestNotification } from '@/hooks/use-settings';
import type { SettingItem, NotificationTestChannelResult } from '@/api/settings';

interface TabProps {
  settings: SettingItem[];
  envOnly: boolean;
  onSave: (changes: Record<string, unknown>) => void;
  onReset: (key: string) => void;
  isSaving: boolean;
  onDirtyChange?: (dirty: boolean) => void;
}

const FIELDS = [
  { key: 'cors_allowed_origins', defaultValue: '' },
  { key: 'global_rate_limit', defaultValue: 60 },
] as const;

function NotificationChannelBadge({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className="text-sm text-muted-foreground">{label}:</span>
      <Badge variant={ok ? 'default' : 'secondary'}>{ok ? 'Yes' : 'No'}</Badge>
    </span>
  );
}

function ChannelResult({ result }: { result: NotificationTestChannelResult }) {
  return (
    <div className="flex items-center gap-2 text-sm">
      <Badge variant={result.ok ? 'default' : 'destructive'}>{result.channel}</Badge>
      {result.ok ? (
        <span className="text-muted-foreground">Delivered</span>
      ) : (
        <span className="text-destructive">{result.error ?? 'Failed'}</span>
      )}
    </div>
  );
}

export function SettingsNetworkTab({ settings, envOnly, onSave, onReset, isSaving, onDirtyChange }: TabProps) {
  const { t } = useTranslation('admin');
  const { values, setters, dirty, hasDirty, discard } = useSettingsForm(settings, FIELDS);

  // Phase 1229 Plan 03 — notification channel status + test-send (NOTIF-06).
  const { data: notifStatus, isLoading: notifLoading } = useNotificationStatus();
  const testSend = useSendTestNotification();
  const [testResult, setTestResult] = useState<{ sent: boolean; channels: NotificationTestChannelResult[]; message: string } | null>(null);

  const handleSendTest = () => {
    setTestResult(null);
    testSend.mutate(undefined, {
      onSuccess: (data) => setTestResult(data),
      onError: () => {
        setTestResult({
          sent: false,
          channels: [],
          message: t('settings.notifications.testError'),
        });
      },
    });
  };

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Label htmlFor="cors-origins">{findSetting(settings, 'cors_allowed_origins')?.label ?? t('settings.network.corsAllowedOrigins')}</Label>
          <SettingSourceBadge source={findSetting(settings, 'cors_allowed_origins')?.source ?? 'default'} settingKey="cors_allowed_origins" onReset={onReset} />
        </div>
        <p className="text-sm text-muted-foreground">{t('settings.network.corsAllowedOriginsDescription')}</p>
        <textarea
          id="cors-origins"
          value={values.cors_allowed_origins as string}
          onChange={(e) => setters.cors_allowed_origins(e.target.value)}
          disabled={envOnly}
          placeholder={t('settings.network.corsAllowedOriginsPlaceholder')}
          rows={3}
          className="flex w-full max-w-md rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50"
        />
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Label htmlFor="global-rate-limit">{findSetting(settings, 'global_rate_limit')?.label ?? t('settings.network.globalRateLimit')}</Label>
          <SettingSourceBadge source={findSetting(settings, 'global_rate_limit')?.source ?? 'default'} settingKey="global_rate_limit" onReset={onReset} />
        </div>
        <p className="text-sm text-muted-foreground">{t('settings.network.globalRateLimitDescription')}</p>
        <Input
          id="global-rate-limit"
          type="number"
          min={1}
          max={1000}
          value={values.global_rate_limit as number}
          onChange={(e) => setters.global_rate_limit(Number(e.target.value))}
          disabled={envOnly}
          className="w-32"
        />
      </div>

      {/* Phase 1229 Plan 03 — Notification channel status + test-send (NOTIF-06) */}
      <div className="space-y-3 border rounded-md p-4">
        <div>
          <h3 className="text-sm font-medium">{t('settings.notifications.title')}</h3>
          <p className="text-sm text-muted-foreground mt-1">{t('settings.notifications.description')}</p>
        </div>

        {notifLoading ? (
          <p className="text-sm text-muted-foreground">Loading...</p>
        ) : notifStatus ? (
          <div className="flex flex-wrap gap-4">
            <NotificationChannelBadge ok={notifStatus.notifications_enabled} label={t('settings.notifications.statusEnabled')} />
            <NotificationChannelBadge ok={notifStatus.smtp_configured} label={t('settings.notifications.smtpConfigured')} />
            <NotificationChannelBadge ok={notifStatus.webhook_configured} label={t('settings.notifications.webhookConfigured')} />
          </div>
        ) : null}

        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            onClick={handleSendTest}
            disabled={testSend.isPending}
          >
            {testSend.isPending ? 'Sending...' : t('settings.notifications.sendTest')}
          </Button>
        </div>

        {testResult && (
          <div className="space-y-2">
            <p className="text-sm font-medium">
              {testResult.sent
                ? t('settings.notifications.testSuccess')
                : testResult.channels.length > 0
                  ? t('settings.notifications.testFailed')
                  : t('settings.notifications.testNoChannel')}
            </p>
            {testResult.channels.length > 0 && (
              <div className="space-y-1">
                {testResult.channels.map((r) => (
                  <ChannelResult key={r.channel} result={r} />
                ))}
              </div>
            )}
            {testResult.channels.length === 0 && (
              <p className="text-sm text-muted-foreground">{testResult.message}</p>
            )}
          </div>
        )}
      </div>

      <SettingsFormActions dirty={dirty} hasDirty={hasDirty} envOnly={envOnly} isSaving={isSaving} onSave={onSave} onDiscard={discard} onDirtyChange={onDirtyChange} />
    </div>
  );
}

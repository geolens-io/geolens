import { useTranslation } from 'react-i18next';
import { PageShell } from '@/components/layout/PageShell';
import { PageHeader } from '@/components/layout/PageHeader';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { FieldLabel } from '@/components/ui/field-label';
import { MyApiKeySection } from '@/components/settings/MyApiKeySection';
import { useAuth } from '@/hooks/use-auth';
import { changeAppLanguage } from '@/i18n';
import { fallbackLng, languageOptions } from '@/i18n/config';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { useMyUsage } from '@/hooks/use-quota';
import { formatBytes, formatNumber } from '@/lib/format';

export function SettingsPage() {
  const { t, i18n } = useTranslation();
  const { user } = useAuth();
  const { data: usage } = useMyUsage();
  useDocumentTitle(t('common:pageTitle.settings'));

  return (
    <PageShell maxWidth="narrow">
      <PageHeader title={t('nav.settings')} />
      <Tabs defaultValue="preferences">
        <TabsList>
          <TabsTrigger value="preferences">{t('settings.tabs.preferences')}</TabsTrigger>
          <TabsTrigger value="apiKeys">{t('settings.tabs.apiKeys')}</TabsTrigger>
        </TabsList>

        <TabsContent value="preferences" className="space-y-4">
          {/* Profile */}
          <Card className="border border-border">
            <CardHeader>
              <CardTitle>{t('settings.profile.title')}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-4">
                <div className="flex h-12 w-12 items-center justify-center rounded-full bg-primary text-primary-foreground text-lg font-medium">
                  {user?.username?.charAt(0).toUpperCase()}
                </div>
                <div>
                  <p className="font-medium">{user?.username}</p>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-sm text-muted-foreground">{t('settings.profile.role')}:</span>
                    <Badge variant="secondary">{user?.roles?.[0]}</Badge>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Storage usage */}
          <Card className="border border-border">
            <CardHeader>
              <CardTitle>{t('settings.storage.title')}</CardTitle>
              <CardDescription>{t('settings.storage.description')}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">{t('settings.storage.storageUsed')}</span>
                  <span className="font-medium">
                    {usage
                      ? usage.storage_cap > 0
                        ? `${formatBytes(usage.bytes_used)} / ${formatBytes(usage.storage_cap)}`
                        : formatBytes(usage.bytes_used)
                      : '—'}
                  </span>
                </div>
                {usage && usage.storage_cap > 0 ? (
                  <progress
                    value={usage.bytes_used}
                    max={usage.storage_cap}
                    aria-label={t('settings.storage.storageUsed')}
                    className="h-2 w-full appearance-none overflow-hidden rounded-full bg-muted [&::-webkit-progress-bar]:bg-muted [&::-webkit-progress-value]:bg-primary [&::-moz-progress-bar]:bg-primary"
                  />
                ) : usage ? (
                  <p className="text-xs text-muted-foreground">{t('settings.storage.unlimited')}</p>
                ) : null}
                {/* #347 (ADM-06): file storage only meters uploaded file bytes, so a
                    vector-only account reads 0 B despite having datasets. */}
                {usage && usage.bytes_used === 0 && usage.dataset_count > 0 && (
                  <p className="text-xs text-muted-foreground">{t('settings.storage.fileStorageNote')}</p>
                )}
              </div>
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-muted-foreground">{t('settings.storage.datasetsUsed')}</span>
                  <span className="font-medium">
                    {usage
                      ? usage.count_cap > 0
                        ? `${formatNumber(usage.dataset_count)} / ${formatNumber(usage.count_cap)}`
                        : formatNumber(usage.dataset_count)
                      : '—'}
                  </span>
                </div>
                {usage && usage.count_cap > 0 ? (
                  <progress
                    value={usage.dataset_count}
                    max={usage.count_cap}
                    aria-label={t('settings.storage.datasetsUsed')}
                    className="h-2 w-full appearance-none overflow-hidden rounded-full bg-muted [&::-webkit-progress-bar]:bg-muted [&::-webkit-progress-value]:bg-primary [&::-moz-progress-bar]:bg-primary"
                  />
                ) : usage ? (
                  <p className="text-xs text-muted-foreground">{t('settings.storage.unlimited')}</p>
                ) : null}
                {/* #347 (ADM-06): the dataset cap is enforced at upload only, so an
                    account can sit above a later-lowered cap (e.g. 18 / 10).
                    Label it instead of letting it read as a broken counter. */}
                {usage && usage.count_cap > 0 && usage.dataset_count > usage.count_cap && (
                  <p className="text-xs text-destructive">{t('settings.storage.overLimit')}</p>
                )}
              </div>
            </CardContent>
          </Card>


          {/* Language */}
          <Card className="border border-border">
            <CardHeader>
              <CardTitle>{t('settings.language.title')}</CardTitle>
            </CardHeader>
            <CardContent>
              <FieldLabel htmlFor="settings-language-select">
                {t('settings.language.title')}
              </FieldLabel>
              <Select
                value={i18n.resolvedLanguage ?? fallbackLng}
                onValueChange={(lng) => {
                  void changeAppLanguage(lng);
                }}
              >
                <SelectTrigger id="settings-language-select" className="w-48">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {languageOptions.map((language) => (
                    <SelectItem key={language.value} value={language.value}>
                      {language.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="apiKeys">
          <Card className="border border-border">
            <CardHeader>
              <CardTitle>{t('settings.tabs.apiKeys')}</CardTitle>
            </CardHeader>
            <CardContent>
              <MyApiKeySection />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </PageShell>
  );
}

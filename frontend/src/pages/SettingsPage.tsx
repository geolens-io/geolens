import { useTranslation } from 'react-i18next';
import { Sun, Moon, Monitor } from 'lucide-react';
import { PageShell } from '@/components/layout/PageShell';
import { PageHeader } from '@/components/layout/PageHeader';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { MyApiKeySection } from '@/components/settings/MyApiKeySection';
import { useAuth } from '@/hooks/use-auth';
import { useTheme } from '@/components/theme-provider';
import { changeAppLanguage } from '@/i18n';
import { fallbackLng, languageOptions } from '@/i18n/config';
import { cn } from '@/lib/utils';
import { useDocumentTitle } from '@/hooks/use-document-title';

const themes = ['light', 'dark', 'system'] as const;
const themeIcons = { light: Sun, dark: Moon, system: Monitor } as const;

export function SettingsPage() {
  const { t, i18n } = useTranslation();
  const { user } = useAuth();
  const { theme, setTheme } = useTheme();
  useDocumentTitle('Settings');

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
          <Card>
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

          {/* Appearance */}
          <Card>
            <CardHeader>
              <CardTitle>{t('settings.appearance.title')}</CardTitle>
              <CardDescription>{t('settings.appearance.description')}</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex gap-2">
                {themes.map((themeOption) => {
                  const Icon = themeIcons[themeOption];
                  return (
                    <button
                      key={themeOption}
                      onClick={() => setTheme(themeOption)}
                      className={cn(
                        'flex items-center gap-2 rounded-md border px-4 py-2 text-sm font-medium transition-colors',
                        theme === themeOption
                          ? 'border-primary bg-primary/10 text-primary'
                          : 'border-border text-muted-foreground hover:bg-accent hover:text-accent-foreground',
                      )}
                    >
                      <Icon className="h-4 w-4" />
                      {t(`theme.${themeOption}`)}
                    </button>
                  );
                })}
              </div>
            </CardContent>
          </Card>

          {/* Language */}
          <Card>
            <CardHeader>
              <CardTitle>{t('settings.language.title')}</CardTitle>
            </CardHeader>
            <CardContent>
              <Select
                value={i18n.resolvedLanguage ?? fallbackLng}
                onValueChange={(lng) => {
                  void changeAppLanguage(lng);
                }}
              >
                <SelectTrigger className="w-48">
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
          <Card>
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

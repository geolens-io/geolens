import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Pencil, Trash2, Plus } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogDescription,
} from '@/components/ui/dialog';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { SettingSourceBadge } from './SettingSourceBadge';
import { SettingsFormActions } from './SettingsFormActions';
import { findSetting } from './utils';
import { useSettingsForm } from './useSettingsForm';
import type { SettingItem, OAuthProviderConfig, OAuthProviderCreateData, OAuthProviderUpdateData } from '@/api/settings';
import {
  listOAuthProviders,
  createOAuthProvider,
  updateOAuthProvider,
  deleteOAuthProvider,
} from '@/api/settings';

interface TabProps {
  settings: SettingItem[];
  envOnly: boolean;
  onSave: (changes: Record<string, unknown>) => void;
  onReset: (key: string) => void;
  isSaving: boolean;
  onDirtyChange?: (dirty: boolean) => void;
}

function useProviderTypeLabels(): Record<string, string> {
  const { t } = useTranslation('admin');
  return {
    google: t('settings.oauth.providerTypes.google'),
    microsoft: t('settings.oauth.providerTypes.microsoft'),
    oidc: t('settings.oauth.providerTypes.oidc'),
  };
}

const GOOGLE_DISCOVERY_URL = 'https://accounts.google.com/.well-known/openid-configuration';

function getDefaultDiscoveryUrl(type: string, tenantId?: string): string | null {
  if (type === 'google') return GOOGLE_DISCOVERY_URL;
  if (type === 'microsoft' && tenantId) {
    return `https://login.microsoftonline.com/${tenantId}/v2.0/.well-known/openid-configuration`;
  }
  return null;
}

function slugify(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

interface ProviderFormData {
  provider_type: 'google' | 'microsoft' | 'oidc';
  display_name: string;
  slug: string;
  client_id: string;
  client_secret: string;
  discovery_url: string;
  scopes: string;
  default_role: string;
  group_claim: string;
  group_role_mapping: string; // JSON string for editing
  enabled: boolean;
  microsoft_tenant_id: string; // UI-only field
}

const EMPTY_FORM: ProviderFormData = {
  provider_type: 'google',
  display_name: 'Google',
  slug: 'google',
  client_id: '',
  client_secret: '',
  discovery_url: GOOGLE_DISCOVERY_URL,
  scopes: 'openid profile email',
  default_role: 'viewer',
  group_claim: '',
  group_role_mapping: '',
  enabled: true,
  microsoft_tenant_id: '',
};

// --- OAuth Provider Management Section ---

function OAuthProvidersSection({ envOnly }: { envOnly: boolean }) {
  const { t } = useTranslation('admin');
  const PROVIDER_TYPE_LABELS = useProviderTypeLabels();
  const queryClient = useQueryClient();

  const { data: providers = [], isLoading } = useQuery({
    queryKey: ['settings', 'oauth-providers'],
    queryFn: listOAuthProviders,
  });

  const createMutation = useMutation({
    mutationFn: (data: OAuthProviderCreateData) => createOAuthProvider(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings', 'oauth-providers'] });
      toast.success(t('settings.oauth.created'));
    },
    onError: () => {
      toast.error(t('settings.oauth.createFailed'));
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: OAuthProviderUpdateData }) =>
      updateOAuthProvider(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings', 'oauth-providers'] });
      toast.success(t('settings.oauth.updated'));
    },
    onError: () => {
      toast.error(t('settings.oauth.updateFailed'));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteOAuthProvider(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['settings', 'oauth-providers'] });
      toast.success(t('settings.oauth.deleted'));
    },
    onError: () => {
      toast.error(t('settings.oauth.deleteFailed'));
    },
  });

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingProvider, setEditingProvider] = useState<OAuthProviderConfig | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<OAuthProviderConfig | null>(null);
  const [form, setForm] = useState<ProviderFormData>(EMPTY_FORM);

  function openAddDialog() {
    setEditingProvider(null);
    setForm(EMPTY_FORM);
    setDialogOpen(true);
  }

  function openEditDialog(provider: OAuthProviderConfig) {
    setEditingProvider(provider);
    // Extract tenant ID from Microsoft discovery URL if applicable
    let tenantId = '';
    if (provider.provider_type === 'microsoft' && provider.discovery_url) {
      const match = provider.discovery_url.match(/microsoftonline\.com\/([^/]+)\//);
      if (match) tenantId = match[1];
    }
    setForm({
      provider_type: provider.provider_type,
      display_name: provider.display_name,
      slug: provider.slug,
      client_id: provider.client_id,
      client_secret: '', // never pre-filled
      discovery_url: provider.discovery_url ?? '',
      scopes: provider.scopes,
      default_role: provider.default_role,
      group_claim: provider.group_claim ?? '',
      group_role_mapping: provider.group_role_mapping
        ? JSON.stringify(provider.group_role_mapping, null, 2)
        : '',
      enabled: provider.enabled,
      microsoft_tenant_id: tenantId,
    });
    setDialogOpen(true);
  }

  function handleProviderTypeChange(type: string) {
    const providerType = type as ProviderFormData['provider_type'];
    const displayName = PROVIDER_TYPE_LABELS[providerType] ?? providerType;
    const discoveryUrl = getDefaultDiscoveryUrl(providerType, form.microsoft_tenant_id) ?? '';
    setForm((prev) => ({
      ...prev,
      provider_type: providerType,
      display_name: displayName,
      slug: slugify(displayName),
      discovery_url: discoveryUrl,
    }));
  }

  function handleTenantIdChange(tenantId: string) {
    const discoveryUrl = tenantId
      ? `https://login.microsoftonline.com/${tenantId}/v2.0/.well-known/openid-configuration`
      : '';
    setForm((prev) => ({
      ...prev,
      microsoft_tenant_id: tenantId,
      discovery_url: discoveryUrl,
    }));
  }

  function handleSubmit() {
    let groupMapping: Record<string, string> | null = null;
    if (form.group_role_mapping.trim()) {
      try {
        groupMapping = JSON.parse(form.group_role_mapping);
      } catch {
        toast.error(t('settings.oauth.invalidJson'));
        return;
      }
    }

    if (editingProvider) {
      const data: OAuthProviderUpdateData = {
        slug: form.slug,
        display_name: form.display_name,
        provider_type: form.provider_type,
        client_id: form.client_id,
        discovery_url: form.discovery_url || null,
        scopes: form.scopes,
        default_role: form.default_role,
        group_claim: form.group_claim || null,
        group_role_mapping: groupMapping,
        enabled: form.enabled,
      };
      // Only include client_secret if user entered a new one
      if (form.client_secret) {
        data.client_secret = form.client_secret;
      }
      updateMutation.mutate(
        { id: editingProvider.id, data },
        { onSuccess: () => setDialogOpen(false) },
      );
    } else {
      if (!form.client_secret) {
        toast.error(t('settings.oauth.secretRequired'));
        return;
      }
      const data: OAuthProviderCreateData = {
        slug: form.slug,
        display_name: form.display_name,
        provider_type: form.provider_type,
        client_id: form.client_id,
        client_secret: form.client_secret,
        discovery_url: form.discovery_url || null,
        scopes: form.scopes,
        default_role: form.default_role,
        group_claim: form.group_claim || null,
        group_role_mapping: groupMapping,
        enabled: form.enabled,
      };
      createMutation.mutate(data, { onSuccess: () => setDialogOpen(false) });
    }
  }

  const isMutating = createMutation.isPending || updateMutation.isPending;

  return (
    <>
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-base font-medium">{t('settings.oauth.title')}</h3>
            <p className="text-sm text-muted-foreground">
              {t('settings.oauth.description')}
            </p>
          </div>
          <Button
            size="sm"
            onClick={openAddDialog}
            disabled={envOnly}
          >
            <Plus className="mr-1 h-4 w-4" />
            {t('settings.oauth.addProvider')}
          </Button>
        </div>

        {isLoading ? (
          <p className="text-sm text-muted-foreground">{t('settings.oauth.loading')}</p>
        ) : providers.length === 0 ? (
          <p className="text-sm text-muted-foreground italic">
            {t('settings.oauth.emptyState')}
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('settings.oauth.provider')}</TableHead>
                <TableHead>{t('settings.oauth.type')}</TableHead>
                <TableHead>{t('settings.oauth.status')}</TableHead>
                <TableHead className="text-right">{t('settings.oauth.actions')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {providers.map((provider) => (
                <TableRow key={provider.id}>
                  <TableCell className="font-medium">{provider.display_name}</TableCell>
                  <TableCell>
                    <Badge variant="outline">
                      {PROVIDER_TYPE_LABELS[provider.provider_type] ?? provider.provider_type}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant={provider.enabled ? 'default' : 'secondary'}>
                      {provider.enabled ? t('settings.oauth.enabled') : t('settings.oauth.disabled')}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => openEditDialog(provider)}
                        disabled={envOnly}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setDeleteTarget(provider)}
                        disabled={envOnly}
                      >
                        <Trash2 className="h-4 w-4 text-destructive" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      {/* Add/Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {editingProvider ? t('settings.oauth.editTitle') : t('settings.oauth.addTitle')}
            </DialogTitle>
            <DialogDescription>
              {editingProvider
                ? t('settings.oauth.editDescription')
                : t('settings.oauth.addDescription')}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label>{t('settings.oauth.providerType')}</Label>
              <Select
                value={form.provider_type}
                onValueChange={handleProviderTypeChange}
                disabled={envOnly}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="google">{t('settings.oauth.providerTypes.google')}</SelectItem>
                  <SelectItem value="microsoft">{t('settings.oauth.providerTypes.microsoft')}</SelectItem>
                  <SelectItem value="oidc">{t('settings.oauth.providerTypes.oidc')}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {form.provider_type === 'microsoft' && (
              <div className="space-y-2">
                <Label htmlFor="tenant-id">{t('settings.oauth.tenantId')}</Label>
                <Input
                  id="tenant-id"
                  value={form.microsoft_tenant_id}
                  onChange={(e) => handleTenantIdChange(e.target.value)}
                  placeholder="e.g. your-tenant-id"
                  disabled={envOnly}
                />
                <p className="text-xs text-muted-foreground">
                  {t('settings.oauth.tenantIdHint')}
                </p>
              </div>
            )}

            <div className="space-y-2">
              <Label htmlFor="display-name">{t('settings.oauth.displayName')}</Label>
              <Input
                id="display-name"
                value={form.display_name}
                onChange={(e) => {
                  const name = e.target.value;
                  setForm((prev) => ({
                    ...prev,
                    display_name: name,
                    slug: slugify(name),
                  }));
                }}
                disabled={envOnly}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="slug">{t('settings.oauth.slug')}</Label>
              <Input
                id="slug"
                value={form.slug}
                onChange={(e) => setForm((prev) => ({ ...prev, slug: e.target.value }))}
                disabled={envOnly}
              />
              <p className="text-xs text-muted-foreground">
                {t('settings.oauth.slugHint')}
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="client-id">{t('settings.oauth.clientId')}</Label>
              <Input
                id="client-id"
                value={form.client_id}
                onChange={(e) => setForm((prev) => ({ ...prev, client_id: e.target.value }))}
                disabled={envOnly}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="client-secret">
                {t('settings.oauth.clientSecret')}
                {editingProvider && (
                  <span className="ml-1 text-xs text-muted-foreground font-normal">
                    ({t('settings.oauth.clientSecretKeep')})
                  </span>
                )}
              </Label>
              <Input
                id="client-secret"
                type="password"
                value={form.client_secret}
                onChange={(e) => setForm((prev) => ({ ...prev, client_secret: e.target.value }))}
                placeholder={editingProvider ? '********' : ''}
                disabled={envOnly}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="discovery-url">{t('settings.oauth.discoveryUrl')}</Label>
              <Input
                id="discovery-url"
                value={form.discovery_url}
                onChange={(e) => setForm((prev) => ({ ...prev, discovery_url: e.target.value }))}
                placeholder="https://.../.well-known/openid-configuration"
                disabled={envOnly}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="scopes">{t('settings.oauth.scopes')}</Label>
              <Input
                id="scopes"
                value={form.scopes}
                onChange={(e) => setForm((prev) => ({ ...prev, scopes: e.target.value }))}
                disabled={envOnly}
              />
            </div>

            <div className="space-y-2">
              <Label>{t('settings.oauth.defaultRole')}</Label>
              <Select
                value={form.default_role}
                onValueChange={(v) => setForm((prev) => ({ ...prev, default_role: v }))}
                disabled={envOnly}
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="viewer">{t('settings.oauth.roles.viewer')}</SelectItem>
                  <SelectItem value="editor">{t('settings.oauth.roles.editor')}</SelectItem>
                  <SelectItem value="admin">{t('settings.oauth.roles.admin')}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="group-claim">{t('settings.oauth.groupClaim')}</Label>
              <Input
                id="group-claim"
                value={form.group_claim}
                onChange={(e) => setForm((prev) => ({ ...prev, group_claim: e.target.value }))}
                placeholder='e.g. "groups"'
                disabled={envOnly}
              />
              <p className="text-xs text-muted-foreground">
                {t('settings.oauth.groupClaimHint')}
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="group-role-mapping">{t('settings.oauth.groupRoleMapping')}</Label>
              <textarea
                id="group-role-mapping"
                className="flex min-h-[80px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50"
                value={form.group_role_mapping}
                onChange={(e) => setForm((prev) => ({ ...prev, group_role_mapping: e.target.value }))}
                placeholder='{"IdP Group": "viewer", "Admins": "admin"}'
                disabled={envOnly}
              />
              <p className="text-xs text-muted-foreground">
                {t('settings.oauth.groupRoleMappingHint')}
              </p>
            </div>

            <div className="flex items-center gap-3">
              <Switch
                id="enabled"
                checked={form.enabled}
                onCheckedChange={(checked) =>
                  setForm((prev) => ({ ...prev, enabled: checked }))
                }
                disabled={envOnly}
              />
              <Label htmlFor="enabled">{t('settings.oauth.enabledToggle')}</Label>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              {t('common:cancel')}
            </Button>
            <Button
              onClick={handleSubmit}
              disabled={envOnly || isMutating || !form.client_id || !form.slug}
            >
              {editingProvider ? t('settings.oauth.saveChanges') : t('settings.oauth.createProvider')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null); }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('settings.oauth.deleteTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('settings.oauth.deleteDescription', { name: deleteTarget?.display_name })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('common:cancel')}</AlertDialogCancel>
            <AlertDialogAction
              variant="destructive"
              onClick={() => {
                if (deleteTarget) {
                  deleteMutation.mutate(deleteTarget.id, {
                    onSuccess: () => setDeleteTarget(null),
                  });
                }
              }}
            >
              {t('common:delete')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

// --- Main Auth Tab ---

const AUTH_FIELDS = [
  { key: 'registration_enabled', defaultValue: false },
  { key: 'access_token_expire_minutes', defaultValue: 15 },
  { key: 'refresh_token_expire_days', defaultValue: 7 },
  { key: 'login_rate_limit', defaultValue: 5 },
] as const;

export function SettingsAuthTab({ settings, envOnly, onSave, onReset, isSaving, onDirtyChange }: TabProps) {
  const { t } = useTranslation('admin');
  const { values, setters, dirty, hasDirty, discard } = useSettingsForm(settings, AUTH_FIELDS);

  return (
    <div className="space-y-8">
      {/* Registration Toggle */}
      <div className="flex items-center justify-between max-w-md">
        <div className="space-y-0.5">
          <div className="flex items-center gap-2">
            <Label htmlFor="registration-toggle">{t('settings.general.registration')}</Label>
            <SettingSourceBadge source={findSetting(settings, 'registration_enabled')?.source ?? 'default'} settingKey="registration_enabled" onReset={onReset} />
          </div>
          <p className="text-sm text-muted-foreground">{t('settings.general.registrationDescription')}</p>
        </div>
        <Switch
          id="registration-toggle"
          checked={values.registration_enabled as boolean}
          onCheckedChange={setters.registration_enabled}
          disabled={envOnly}
        />
      </div>

      {/* Token & Rate Limit Settings */}
      <div className="space-y-6">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Label htmlFor="access-token-expire">{t('settings.security.accessTokenExpire')}</Label>
            <SettingSourceBadge source={findSetting(settings, 'access_token_expire_minutes')?.source ?? 'default'} settingKey="access_token_expire_minutes" onReset={onReset} />
          </div>
          <Input
            id="access-token-expire"
            type="number"
            min={1}
            max={1440}
            value={values.access_token_expire_minutes as number}
            onChange={(e) => setters.access_token_expire_minutes(Number(e.target.value))}
            disabled={envOnly}
            className="w-32"
          />
        </div>

        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Label htmlFor="refresh-token-expire">{t('settings.security.refreshTokenExpire')}</Label>
            <SettingSourceBadge source={findSetting(settings, 'refresh_token_expire_days')?.source ?? 'default'} settingKey="refresh_token_expire_days" onReset={onReset} />
          </div>
          <Input
            id="refresh-token-expire"
            type="number"
            min={1}
            max={365}
            value={values.refresh_token_expire_days as number}
            onChange={(e) => setters.refresh_token_expire_days(Number(e.target.value))}
            disabled={envOnly}
            className="w-32"
          />
        </div>

        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Label htmlFor="login-rate-limit">{t('settings.security.loginRateLimitLabel')}</Label>
            <SettingSourceBadge source={findSetting(settings, 'login_rate_limit')?.source ?? 'default'} settingKey="login_rate_limit" onReset={onReset} />
          </div>
          <p className="text-sm text-muted-foreground">{t('settings.security.loginRateLimitDescription')}</p>
          <Input
            id="login-rate-limit"
            type="number"
            min={1}
            max={1000}
            value={values.login_rate_limit as number}
            onChange={(e) => setters.login_rate_limit(Number(e.target.value))}
            disabled={envOnly}
            className="w-32"
          />
        </div>

        <p className="text-sm text-muted-foreground italic">{t('settings.security.tokenLifetimeNote')}</p>

        <SettingsFormActions dirty={dirty} hasDirty={hasDirty} envOnly={envOnly} isSaving={isSaving} onSave={onSave} onDiscard={discard} onDirtyChange={onDirtyChange} />
      </div>

      {/* Separator */}
      <hr className="border-border" />

      {/* OAuth Providers */}
      <OAuthProvidersSection envOnly={envOnly} />
    </div>
  );
}

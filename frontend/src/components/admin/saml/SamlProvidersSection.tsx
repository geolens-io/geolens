/**
 * SAML providers admin CRUD section.
 *
 * Mirrors the shape of `OAuthProvidersSection` (in
 * `frontend/src/components/admin/settings/SettingsAuthTab.tsx`) per Phase
 * 217 PATTERNS Detail 13 Analog B + Anti-Pattern A8 (do NOT pollute
 * SettingsAuthTab with enterprise-only logic).
 *
 * Uses the SAME backend endpoints as OAuth (`/settings/oauth-providers/...`,
 * D-12) via the SAML wrappers in `@/api/saml`. The update wrapper resolves
 * to HTTP PUT (verified at backend/app/modules/settings/router.py:399).
 *
 * sp_entity_id pre-fill (Pitfall 14): uses the authoritative
 * `getTileConfig().public_api_url` query as the primary source; falls back
 * to `window.location.origin` only if the API call fails or returns null.
 * Warning text near the field prompts admins that SP entityID must match
 * the IdP registration exactly.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Pencil, Trash2, Plus, Download } from 'lucide-react';
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { getTileConfig } from '@/api/settings';
import {
  listSamlProviders,
  createSamlProvider,
  updateSamlProvider,
  deleteSamlProvider,
  fetchSamlMetadata,
  type SamlProviderConfig,
  type SamlProviderCreateData,
  type SamlProviderUpdateData,
} from '@/api/saml';
import { queryKeys } from '@/lib/query-keys';

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
}

interface SamlFormData {
  display_name: string;
  slug: string;
  idp_entity_id: string;
  idp_sso_url: string;
  idp_certificate: string;
  sp_entity_id: string;
  default_role: string;
  group_claim: string;
  group_role_mapping: string; // JSON string for editing
  enabled: boolean;
}

const EMPTY_FORM: SamlFormData = {
  display_name: '',
  slug: '',
  idp_entity_id: '',
  idp_sso_url: '',
  idp_certificate: '',
  sp_entity_id: '',
  default_role: 'viewer',
  group_claim: '',
  group_role_mapping: '',
  enabled: true,
};

export function SamlProvidersSection() {
  const { t } = useTranslation('admin');
  const queryClient = useQueryClient();

  const {
    data: providers = [],
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['saml', 'providers'] as const,
    queryFn: listSamlProviders,
  });

  // Authoritative public_api_url source for sp_entity_id pre-fill (Pitfall 14).
  // Falls back to window.location.origin only if this query fails or returns null.
  const { data: tileConfig } = useQuery({
    queryKey: queryKeys.settings.tileConfig,
    queryFn: getTileConfig,
  });

  const createMutation = useMutation({
    mutationFn: (data: SamlProviderCreateData) => createSamlProvider(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['saml', 'providers'] });
      queryClient.invalidateQueries({ queryKey: queryKeys.settingsOAuth.providers });
      toast.success(t('saml.created'));
    },
    onError: () => {
      toast.error(t('saml.createFailed'));
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: SamlProviderUpdateData }) =>
      updateSamlProvider(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['saml', 'providers'] });
      queryClient.invalidateQueries({ queryKey: queryKeys.settingsOAuth.providers });
      toast.success(t('saml.updated'));
    },
    onError: () => {
      toast.error(t('saml.updateFailed'));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteSamlProvider(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['saml', 'providers'] });
      queryClient.invalidateQueries({ queryKey: queryKeys.settingsOAuth.providers });
      toast.success(t('saml.deleted'));
    },
    onError: () => {
      toast.error(t('saml.deleteFailed'));
    },
  });

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingProvider, setEditingProvider] = useState<SamlProviderConfig | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<SamlProviderConfig | null>(null);
  const [form, setForm] = useState<SamlFormData>(EMPTY_FORM);

  /**
   * Build a sensible default sp_entity_id for the current slug, using the
   * authoritative public_api_url from `getTileConfig()` if available, falling
   * back to the browser's origin as a last resort. Returns "" when there is no
   * slug yet so the field stays empty until the admin types one.
   */
  function buildDefaultEntityId(slug: string): string {
    if (!slug) return '';
    const base =
      tileConfig?.public_api_url ?? `${window.location.origin}/api`;
    return `${base}/auth/saml/${slug}`;
  }

  // When the slug changes (and we are creating a new provider, NOT editing),
  // pre-fill sp_entity_id with the recommended default — but only if the admin
  // hasn't typed their own value yet.
  useEffect(() => {
    if (editingProvider) return;
    setForm((prev) => {
      const recommended = buildDefaultEntityId(prev.slug);
      // Only update if sp_entity_id is empty OR matches the previous recommendation
      // (so admin overrides aren't clobbered).
      if (!prev.sp_entity_id || prev.sp_entity_id.endsWith(`/auth/saml/`)) {
        return { ...prev, sp_entity_id: recommended };
      }
      return prev;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.slug, tileConfig?.public_api_url, editingProvider]);

  function openAddDialog() {
    setEditingProvider(null);
    setForm({ ...EMPTY_FORM });
    setDialogOpen(true);
  }

  function openEditDialog(provider: SamlProviderConfig) {
    setEditingProvider(provider);
    setForm({
      display_name: provider.display_name,
      slug: provider.slug,
      idp_entity_id: provider.idp_entity_id ?? '',
      idp_sso_url: provider.idp_sso_url ?? '',
      idp_certificate: '', // never pre-filled (write-only secret)
      sp_entity_id: provider.sp_entity_id ?? '',
      default_role: provider.default_role,
      group_claim: provider.group_claim ?? '',
      group_role_mapping: provider.group_role_mapping
        ? JSON.stringify(provider.group_role_mapping, null, 2)
        : '',
      enabled: provider.enabled,
    });
    setDialogOpen(true);
  }

  async function handleDownloadMetadata(slug: string) {
    try {
      const xml = await fetchSamlMetadata(slug);
      const blob = new Blob([xml], { type: 'application/samlmetadata+xml' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${slug}-metadata.xml`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      toast.error(t('saml.metadataFailed'));
    }
  }

  function handleSubmit() {
    let groupMapping: Record<string, string> | null = null;
    if (form.group_role_mapping.trim()) {
      try {
        groupMapping = JSON.parse(form.group_role_mapping);
      } catch {
        toast.error(t('saml.invalidJson'));
        return;
      }
    }

    if (editingProvider) {
      const data: SamlProviderUpdateData = {
        slug: form.slug,
        display_name: form.display_name,
        provider_type: 'saml',
        idp_entity_id: form.idp_entity_id,
        idp_sso_url: form.idp_sso_url,
        sp_entity_id: form.sp_entity_id,
        default_role: form.default_role,
        group_claim: form.group_claim || null,
        group_role_mapping: groupMapping,
        enabled: form.enabled,
      };
      // Only include idp_certificate if user pasted a new one (write-only;
      // empty string means "keep existing cert").
      if (form.idp_certificate) {
        data.idp_certificate = form.idp_certificate;
      }
      updateMutation.mutate(
        { id: editingProvider.id, data },
        { onSuccess: () => setDialogOpen(false) },
      );
    } else {
      if (!form.idp_certificate) {
        toast.error(t('saml.certRequired'));
        return;
      }
      const data: SamlProviderCreateData = {
        slug: form.slug,
        display_name: form.display_name,
        provider_type: 'saml',
        idp_entity_id: form.idp_entity_id,
        idp_sso_url: form.idp_sso_url,
        idp_certificate: form.idp_certificate,
        sp_entity_id: form.sp_entity_id,
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
            <h3 className="text-base font-medium">{t('saml.title')}</h3>
            <p className="text-sm text-muted-foreground">{t('saml.description')}</p>
          </div>
          <Button size="sm" onClick={openAddDialog}>
            <Plus className="me-1 h-4 w-4" />
            {t('saml.addProvider')}
          </Button>
        </div>

        {isLoading ? (
          <p className="text-sm text-muted-foreground">{t('saml.loading')}</p>
        ) : isError ? (
          <p className="text-sm text-destructive">{t('saml.loadFailed')}</p>
        ) : providers.length === 0 ? (
          <p className="text-sm text-muted-foreground italic">{t('saml.emptyState')}</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('saml.provider')}</TableHead>
                <TableHead>{t('saml.idpEntityId')}</TableHead>
                <TableHead>{t('saml.status')}</TableHead>
                <TableHead className="text-end">{t('saml.actions')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {providers.map((provider) => (
                <TableRow key={provider.id}>
                  <TableCell className="font-medium">
                    <div>{provider.display_name}</div>
                    <div className="text-xs text-muted-foreground">{provider.slug}</div>
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground break-all">
                    {provider.idp_entity_id ?? '—'}
                  </TableCell>
                  <TableCell>
                    <Badge variant={provider.enabled ? 'default' : 'secondary'}>
                      {provider.enabled ? t('saml.enabled') : t('saml.disabled')}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-end">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        title={t('saml.downloadMetadata')}
                        onClick={() => handleDownloadMetadata(provider.slug)}
                      >
                        <Download className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        title={t('saml.edit')}
                        onClick={() => openEditDialog(provider)}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        title={t('saml.delete')}
                        onClick={() => setDeleteTarget(provider)}
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
              {editingProvider ? t('saml.editTitle') : t('saml.addTitle')}
            </DialogTitle>
            <DialogDescription>
              {editingProvider
                ? t('saml.editDescription')
                : t('saml.addDescription')}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="saml-display-name">{t('saml.displayName')}</Label>
              <Input
                id="saml-display-name"
                value={form.display_name}
                onChange={(e) => {
                  const name = e.target.value;
                  setForm((prev) => ({
                    ...prev,
                    display_name: name,
                    slug: editingProvider ? prev.slug : slugify(name),
                  }));
                }}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="saml-slug">{t('saml.slug')}</Label>
              <Input
                id="saml-slug"
                value={form.slug}
                onChange={(e) => setForm((prev) => ({ ...prev, slug: e.target.value }))}
                disabled={!!editingProvider}
              />
              <p className="text-xs text-muted-foreground">{t('saml.slugHint')}</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="saml-idp-entity-id">{t('saml.idpEntityId')}</Label>
              <Input
                id="saml-idp-entity-id"
                value={form.idp_entity_id}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, idp_entity_id: e.target.value }))
                }
                placeholder="https://idp.example.com/saml/metadata"
              />
              <p className="text-xs text-muted-foreground">{t('saml.idpEntityIdHint')}</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="saml-idp-sso-url">{t('saml.idpSsoUrl')}</Label>
              <Input
                id="saml-idp-sso-url"
                value={form.idp_sso_url}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, idp_sso_url: e.target.value }))
                }
                placeholder="https://idp.example.com/saml/sso"
              />
              <p className="text-xs text-muted-foreground">{t('saml.idpSsoUrlHint')}</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="saml-idp-certificate">
                {t('saml.idpCertificate')}
                {editingProvider && (
                  <span className="ms-1 text-xs text-muted-foreground font-normal">
                    ({t('saml.idpCertificateKeep')})
                  </span>
                )}
              </Label>
              <textarea
                id="saml-idp-certificate"
                className="flex min-h-[140px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-xs font-mono shadow-xs placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50"
                value={form.idp_certificate}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, idp_certificate: e.target.value }))
                }
                placeholder={
                  editingProvider
                    ? '(leave blank to keep existing certificate)'
                    : '-----BEGIN CERTIFICATE-----\nMIIC...\n-----END CERTIFICATE-----'
                }
              />
              <p className="text-xs text-muted-foreground">{t('saml.idpCertificateHint')}</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="saml-sp-entity-id">{t('saml.spEntityId')}</Label>
              <Input
                id="saml-sp-entity-id"
                value={form.sp_entity_id}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, sp_entity_id: e.target.value }))
                }
                placeholder={buildDefaultEntityId(form.slug || 'your-slug')}
              />
              <p className="text-xs text-amber-700 dark:text-amber-500">
                {t('saml.spEntityIdWarning')}
              </p>
            </div>

            <div className="space-y-2">
              <Label>{t('saml.defaultRole')}</Label>
              <Select
                value={form.default_role}
                onValueChange={(v) =>
                  setForm((prev) => ({ ...prev, default_role: v }))
                }
              >
                <SelectTrigger className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="viewer">{t('saml.roles.viewer')}</SelectItem>
                  <SelectItem value="editor">{t('saml.roles.editor')}</SelectItem>
                  <SelectItem value="admin">{t('saml.roles.admin')}</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="saml-group-claim">{t('saml.groupClaim')}</Label>
              <Input
                id="saml-group-claim"
                value={form.group_claim}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, group_claim: e.target.value }))
                }
                placeholder='e.g. "groups"'
              />
              <p className="text-xs text-muted-foreground">{t('saml.groupClaimHint')}</p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="saml-group-role-mapping">{t('saml.groupRoleMapping')}</Label>
              <textarea
                id="saml-group-role-mapping"
                className="flex min-h-[80px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-xs placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50"
                value={form.group_role_mapping}
                onChange={(e) =>
                  setForm((prev) => ({ ...prev, group_role_mapping: e.target.value }))
                }
                placeholder='{"IdP Group": "viewer", "Admins": "admin"}'
              />
              <p className="text-xs text-muted-foreground">
                {t('saml.groupRoleMappingHint')}
              </p>
            </div>

            <div className="flex items-center gap-3">
              <Switch
                id="saml-enabled"
                checked={form.enabled}
                onCheckedChange={(checked) =>
                  setForm((prev) => ({ ...prev, enabled: checked }))
                }
              />
              <Label htmlFor="saml-enabled">{t('saml.enabledToggle')}</Label>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              {t('common:cancel')}
            </Button>
            <Button
              onClick={handleSubmit}
              disabled={
                isMutating ||
                !form.slug ||
                !form.display_name ||
                !form.idp_entity_id ||
                !form.idp_sso_url ||
                !form.sp_entity_id
              }
            >
              {editingProvider ? t('saml.saveChanges') : t('saml.createProvider')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <AlertDialog
        open={!!deleteTarget}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('saml.deleteTitle')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('saml.deleteDescription', { name: deleteTarget?.display_name })}
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

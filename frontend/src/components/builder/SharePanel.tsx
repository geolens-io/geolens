import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Globe, Lock, Copy, Loader2, Code, Link as LinkIcon, Info, Trash2, Shield, ExternalLink, ChevronRight, Users, AlertTriangle } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { ApiError } from '@/api/client';
import { formatDate } from '@/lib/format';
import { cn } from '@/lib/utils';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { usePublishMap, useCreateShareToken, useRevokeShareToken, useMapShareToken, useUpdateShareToken } from '@/hooks/use-maps';
import { checkMapVisibility } from '@/api/maps';
import { useCreateEmbedToken, useMapEmbedTokens, useUpdateEmbedToken } from '@/hooks/use-embed-tokens';
import type { MapVisibility } from '@/types/api';

function parseOrigins(input: string): string[] {
  return input
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => s.replace(/\/+$/, ''))
    .map((s) => (s.includes('://') ? s : `https://${s}`));
}

const VISIBILITY_OPTIONS: Array<{
  value: MapVisibility;
  icon: typeof Lock;
  iconClass: string;
  titleKey: string;
  descKey: string;
}> = [
  {
    value: 'private',
    icon: Lock,
    iconClass: 'text-muted-foreground',
    titleKey: 'share.privateTitle',
    descKey: 'share.privateDescription',
  },
  {
    value: 'internal',
    icon: Users,
    iconClass: 'text-warning',
    titleKey: 'share.internalTitle',
    descKey: 'share.internalDescription',
  },
  {
    value: 'public',
    icon: Globe,
    iconClass: 'text-success',
    titleKey: 'share.publicTitle',
    descKey: 'share.publicDescription',
  },
];

interface ShareDialogProps {
  mapId: string;
  visibility: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ShareDialog({ mapId, visibility, open, onOpenChange }: ShareDialogProps) {
  const { t } = useTranslation('builder');
  const publishMap = usePublishMap();
  const createShareToken = useCreateShareToken();
  const revokeShareToken = useRevokeShareToken();
  const createEmbedToken = useCreateEmbedToken();
  const updateShareToken = useUpdateShareToken();
  const updateEmbedToken = useUpdateEmbedToken();

  const [hasNonPublic, setHasNonPublic] = useState(false);
  const [embedTokenRaw, setEmbedTokenRaw] = useState<string | null>(null);
  const [domainInput, setDomainInput] = useState('');
  const [showSettings, setShowSettings] = useState(false);

  // Editable field state
  const [expiresValue, setExpiresValue] = useState('');
  const [domainsValue, setDomainsValue] = useState('');
  const [showDomainRestrict, setShowDomainRestrict] = useState(false);

  // Queries as source of truth
  const shareTokenQuery = useMapShareToken(mapId);
  const shareToken = shareTokenQuery.data?.token ?? null;
  const shareExpires = shareTokenQuery.data?.expires_at ?? null;
  const isExpired = shareExpires ? new Date(shareExpires) < new Date() : false;

  const embedTokensQuery = useMapEmbedTokens(shareToken ? mapId : undefined);
  const activeEmbedToken = embedTokensQuery.data?.tokens?.find(
    t => t.is_active && new Date(t.expires_at) > new Date()
  );
  const resolvedEmbedTokenId = activeEmbedToken?.id ?? null;
  const configDomains = activeEmbedToken?.allowed_origins?.join(', ') ?? null;

  const isPublic = visibility === 'public';

  async function handleVisibilityChange(newVisibility: MapVisibility) {
    if (newVisibility === visibility) return;
    try {
      await publishMap.mutateAsync({ id: mapId, visibility: newVisibility });
      if (newVisibility === 'public') {
        toast.success(t('toasts.mapNowPublic'));
      } else if (newVisibility === 'internal') {
        toast.success(t('toasts.mapNowInternal'));
      } else {
        toast.success(t('toasts.mapNowPrivate'));
      }
      if (newVisibility !== 'public') {
        setHasNonPublic(false);
        setEmbedTokenRaw(null);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        let datasets = err.message;
        try {
          const parsed = JSON.parse(err.message);
          if (parsed.datasets) datasets = parsed.datasets.join(', ');
        } catch {
          // Legacy format or unparseable — use raw message
        }
        toast.error(t('share.cannotPublish', { datasets }));
      } else {
        toast.error(t('toasts.visibilityFailed'));
      }
    }
  }

  async function runVisibilityCheck() {
    try {
      const check = await checkMapVisibility(mapId);
      setHasNonPublic(check.has_non_public);
      return check;
    } catch {
      return null;
    }
  }

  async function maybeCreateEmbedToken() {
    if (embedTokenRaw) return;
    if (activeEmbedToken) return;
    try {
      const origins = parseOrigins(domainInput);
      const tokenResult = await createEmbedToken.mutateAsync({
        mapId,
        allowedOrigins: origins.length > 0 ? origins : undefined,
      });
      setEmbedTokenRaw(tokenResult.raw_token);
    } catch {
      toast.error(t('share.embedTokenFailed'));
    }
  }

  async function handleGetShareLink() {
    if (shareToken) {
      const check = await runVisibilityCheck();
      if (check?.has_non_public) await maybeCreateEmbedToken();
      return;
    }
    try {
      await createShareToken.mutateAsync({ mapId });
      const check = await runVisibilityCheck();
      if (check?.has_non_public) await maybeCreateEmbedToken();
    } catch {
      toast.error(t('toasts.shareLinkFailed'));
    }
  }

  async function handleRevokeShareLink() {
    try {
      await revokeShareToken.mutateAsync(mapId);
      setEmbedTokenRaw(null);
      setExpiresValue('');
      setDomainsValue('');
      setDomainInput('');
      setShowDomainRestrict(false);
      setShowSettings(false);
      setHasNonPublic(false);
      toast.success(t('toasts.shareLinkRevoked'));
    } catch {
      toast.error(t('toasts.revokeFailed'));
    }
  }

  async function handleSaveExpiration() {
    try {
      const newExpires = expiresValue ? new Date(expiresValue + 'T23:59:59Z').toISOString() : null;
      await updateShareToken.mutateAsync({ mapId, expiresAt: newExpires });
      toast.success(t('share.expirationUpdated'));
    } catch {
      toast.error(t('share.updateFailed'));
    }
  }

  async function handleSaveDomains() {
    if (!resolvedEmbedTokenId) return;
    try {
      const origins = parseOrigins(domainsValue);
      await updateEmbedToken.mutateAsync({
        mapId,
        tokenId: resolvedEmbedTokenId,
        allowedOrigins: origins.length > 0 ? origins : null,
      });
      toast.success(t('share.domainsUpdated'));
    } catch {
      toast.error(t('share.updateFailed'));
    }
  }

  function getShareUrl() {
    if (!shareToken) return '';
    return `${window.location.origin}/m/${shareToken}`;
  }

  function getEmbedCode() {
    if (!shareToken) return '';
    const params = new URLSearchParams({ embed: 'true' });
    if (embedTokenRaw) {
      params.set('et', embedTokenRaw);
    }
    const url = `${window.location.origin}/m/${shareToken}?${params.toString()}`;
    return `<iframe src="${url}" width="800" height="600" sandbox="allow-scripts allow-same-origin" style="border:none;"></iframe>`;
  }

  async function handleCopyShareLink() {
    const url = getShareUrl();
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      toast.success(t('toasts.shareLinkCopied'));
    } catch {
      toast.error(t('toasts.copyFailed'));
    }
  }

  async function handleCopyEmbedCode() {
    const code = getEmbedCode();
    if (!code) return;
    try {
      await navigator.clipboard.writeText(code);
      toast.success(t('toasts.embedCodeCopied'));
    } catch {
      toast.error(t('toasts.copyFailed'));
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md max-h-[calc(100dvh-2rem)] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t('share.title')}</DialogTitle>
          <DialogDescription>{t('share.dialogDescription')}</DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          {/* Visibility selector */}
          <div className="space-y-2">
            <p className="text-sm font-medium">{t('share.visibilityTitle')}</p>
            <div className="space-y-1.5" role="radiogroup" aria-label={t('share.visibilityTitle')}>
              {VISIBILITY_OPTIONS.map((opt) => {
                const Icon = opt.icon;
                const isActive = visibility === opt.value;
                return (
                  <button
                    key={opt.value}
                    type="button"
                    role="radio"
                    aria-checked={isActive}
                    className={cn(
                      'w-full flex items-start gap-3 rounded-lg border px-3 py-2.5 text-start transition-colors',
                      isActive
                        ? 'ring-2 ring-primary border-primary bg-primary/5'
                        : 'border-border hover:border-muted-foreground/30 hover:bg-accent/50',
                    )}
                    onClick={() => handleVisibilityChange(opt.value)}
                    disabled={publishMap.isPending}
                  >
                    <Icon className={cn('h-4 w-4 mt-0.5 shrink-0', opt.iconClass)} />
                    <div className="min-w-0">
                      <p className="text-sm font-medium">{t(opt.titleKey)}</p>
                      <p className="text-xs text-muted-foreground">{t(opt.descKey)}</p>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {publishMap.isPending && (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              {t('share.updatingVisibility')}
            </div>
          )}

          {/* Share link section (only for public maps) */}
          {isPublic && (
            <>
              <div className="border-t pt-4 space-y-3">
                <div className="flex items-center gap-1.5">
                  <LinkIcon className="h-3.5 w-3.5 text-muted-foreground" />
                  <span className="text-sm font-medium">{t('share.shareLink')}</span>
                </div>

                {shareToken ? (
                  <div className="space-y-3">
                    {/* Copy Link + Open */}
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        className="flex-1"
                        onClick={handleCopyShareLink}
                      >
                        <Copy className="h-3.5 w-3.5 me-1.5" />
                        {t('share.copyLink')}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => window.open(getShareUrl(), '_blank')}
                      >
                        <ExternalLink className="h-3.5 w-3.5 me-1.5" />
                        {t('share.open')}
                      </Button>
                    </div>

                    {/* Status summary */}
                    {isExpired && (
                      <div className="flex items-center gap-1.5 text-xs text-destructive">
                        <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
                        <span>{t('share.expired')}</span>
                      </div>
                    )}
                    <div className="flex items-center gap-3 text-xs text-muted-foreground">
                      <span className={isExpired ? 'text-destructive' : undefined}>
                        {t('share.summaryExpires')}: {shareExpires ? formatDate(shareExpires) : t('share.summaryNever')}
                      </span>
                      {configDomains && (
                        <>
                          <span className="text-border">|</span>
                          <span className="truncate">{t('share.summaryDomains')}: {configDomains}</span>
                        </>
                      )}
                    </div>

                    {/* Link Settings -- collapsible */}
                    <div className="space-y-3">
                      <button
                        type="button"
                        className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
                        onClick={() => {
                          const next = !showSettings;
                          setShowSettings(next);
                          if (next) {
                            setExpiresValue(shareExpires ? shareExpires.split('T')[0] : '');
                            setDomainsValue(configDomains || '');
                            setShowDomainRestrict(!!configDomains);
                          }
                        }}
                      >
                        <ChevronRight className={cn('h-3 w-3 transition-transform', showSettings && 'rotate-90')} />
                        {t('share.linkSettings')}
                      </button>

                      {showSettings && (
                        <div className="space-y-4 ps-4 border-s-2 border-border">
                          {/* Expiration */}
                          <div className="space-y-1.5">
                            <label className="text-xs font-medium">{t('share.expirationLabel')}</label>
                            <div className="flex gap-2">
                              <Input
                                type="date"
                                value={expiresValue}
                                onChange={(e) => setExpiresValue(e.target.value)}
                                min={new Date().toISOString().split('T')[0]}
                                className="h-8 text-sm flex-1"
                                placeholder={t('share.expirationPlaceholder')}
                              />
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={handleSaveExpiration}
                                disabled={updateShareToken.isPending}
                              >
                                {updateShareToken.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : t('share.save')}
                              </Button>
                            </div>
                            <p className="text-xs text-muted-foreground">{t('share.expirationHint')}</p>
                          </div>

                          {/* Domain restriction */}
                          {resolvedEmbedTokenId && (
                            <div className="space-y-1.5">
                              <div className="flex items-center justify-between">
                                <div className="flex items-center gap-1.5">
                                  <Shield className="h-3 w-3 text-muted-foreground" />
                                  <label className="text-xs font-medium">{t('share.restrictToDomains')}</label>
                                </div>
                                <Switch
                                  checked={showDomainRestrict}
                                  onCheckedChange={(checked) => {
                                    setShowDomainRestrict(checked);
                                    if (checked && !domainsValue) {
                                      setDomainsValue(window.location.origin);
                                    }
                                    if (!checked && configDomains) {
                                      // Clear restrictions
                                      setDomainsValue('');
                                      handleSaveDomains();
                                    }
                                  }}
                                  aria-label={t('share.restrictToDomains')}
                                />
                              </div>
                              {showDomainRestrict && (
                                <div className="space-y-1.5">
                                  <div className="flex gap-2">
                                    <Input
                                      value={domainsValue}
                                      onChange={(e) => setDomainsValue(e.target.value)}
                                      placeholder="example.com, app.example.com"
                                      className="h-8 text-sm font-mono flex-1"
                                    />
                                    <Button
                                      variant="outline"
                                      size="sm"
                                      onClick={handleSaveDomains}
                                      disabled={updateEmbedToken.isPending}
                                    >
                                      {updateEmbedToken.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : t('share.save')}
                                    </Button>
                                  </div>
                                  <p className="text-xs text-muted-foreground">{t('share.domainHint')}</p>
                                </div>
                              )}
                            </div>
                          )}

                          {/* Revoke */}
                          <div className="pt-2 border-t">
                            <Button
                              variant="outline"
                              size="sm"
                              className="w-full text-destructive hover:text-destructive hover:bg-destructive/5"
                              onClick={handleRevokeShareLink}
                              disabled={revokeShareToken.isPending}
                            >
                              {revokeShareToken.isPending ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin me-1.5" />
                              ) : (
                                <Trash2 className="h-3.5 w-3.5 me-1.5" />
                              )}
                              {t('share.revokeShareLink')}
                            </Button>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <Button
                    variant="outline"
                    size="sm"
                    className="w-full"
                    onClick={handleGetShareLink}
                    disabled={createShareToken.isPending}
                  >
                    {createShareToken.isPending ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin me-1.5" />
                    ) : (
                      <LinkIcon className="h-3.5 w-3.5 me-1.5" />
                    )}
                    {t('share.generateShareLink')}
                  </Button>
                )}
              </div>

              {/* Embed code section (only when share token exists) */}
              {shareToken && (
                <div className="border-t pt-4 space-y-3">
                  <div className="flex items-center gap-1.5">
                    <Code className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="text-sm font-medium">{t('share.embedCode')}</span>
                  </div>
                  <div className="relative">
                    <textarea
                      readOnly
                      value={getEmbedCode()}
                      rows={3}
                      className="w-full rounded-md border border-input bg-muted/30 px-3 py-2 text-xs font-mono resize-none focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:border-ring"
                    />
                    <Button
                      variant="outline"
                      size="icon-xs"
                      className="absolute top-1.5 right-1.5"
                      onClick={handleCopyEmbedCode}
                      title={t('share.copyEmbedCode')}
                    >
                      <Copy className="h-3 w-3" />
                    </Button>
                  </div>
                  {hasNonPublic && (
                    <div className="flex items-start gap-2 rounded-md border border-info/30 bg-info/5 px-3 py-2">
                      <Info className="h-3.5 w-3.5 text-info mt-0.5 flex-shrink-0" />
                      <p className="text-xs text-foreground">
                        {t('share.embedTokenInfo')}
                      </p>
                    </div>
                  )}
                  <div className="space-y-1">
                    <p className="text-xs font-medium text-muted-foreground">{t('share.customizeTitle')}</p>
                    <ul className="text-xs text-muted-foreground space-y-0.5 ms-3">
                      <li><code className="bg-muted px-1 rounded text-[11px]">zoom=N</code> {t('share.customizeZoom')}</li>
                      <li><code className="bg-muted px-1 rounded text-[11px]">center=lng,lat</code> {t('share.customizeCenter')}</li>
                      <li><code className="bg-muted px-1 rounded text-[11px]">legend=true|false</code> {t('share.customizeLegend')}</li>
                    </ul>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

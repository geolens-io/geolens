import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Globe, Check } from 'lucide-react';
import { cn } from '@/lib/utils';
import { formatDateTimeSmart } from '@/lib/format';
import { ApiError } from '@/api/client';
import { probeService, previewServiceLayer, commitImport, arcgisSignin } from '@/api/ingest';
import type {
  ProbeResponse,
  LayerInfo,
  ServicePreviewResponse,
  ServicePreviewRequest,
  CommitImportRequest,
} from '@/types/api';
import { ImportPreview } from './ImportPreview';
import { ImportMetadataForm } from './ImportMetadataForm';
import { JobProgress } from './JobProgress';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { TypeTag } from './TypeTag';
import { looksLikeArcGisServiceUrl, originOf } from './utils';

type ServiceStep =
  | 'idle'
  | 'probing'
  | 'layer-select'
  | 'previewing'
  | 'review'
  | 'committing'
  | 'tracking';

// Plan section 3.1: for an ArcGIS FeatureServer/MapServer URL, the import
// wizard offers a three-way authentication choice instead of one optional
// token field. 'none' is the default and is an explicit choice ("this
// service is public"), not a blank state.
type ArcgisAuthMethod = 'none' | 'token' | 'signin';

export function ServiceUrlForm() {
  const { t } = useTranslation('import');
  const [step, setStep] = useState<ServiceStep>('idle');
  const [url, setUrl] = useState('');
  const [token, setToken] = useState('');
  const [probeResult, setProbeResult] = useState<ProbeResponse | null>(null);
  const [previewData, setPreviewData] = useState<ServicePreviewResponse | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // ArcGIS sign-in (plan 3.2 / lane A2).
  const [arcgisAuthMethod, setArcgisAuthMethod] = useState<ArcgisAuthMethod>('none');
  const [portalUrl, setPortalUrl] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [tokenExpiresAt, setTokenExpiresAt] = useState<string | null>(null);
  const [signingIn, setSigningIn] = useState(false);
  const [signinError, setSigninError] = useState<string | null>(null);

  // codex review #1757 P1: a stale in-flight sign-in response must never
  // resurrect a token or run after the auth context it belongs to is gone.
  // Bumped on every full auth-state reset below (method switch, URL origin
  // change, or the wizard's own reset()); handleArcgisSignin captures the
  // value at send time and ignores its own response if it no longer matches.
  const signinGenerationRef = useRef(0);
  const authOrigin = originOf(url);
  const lastAuthOriginRef = useRef(authOrigin);

  // codex review #1757 P1: a credential entered for one origin must never
  // survive being pointed at a different one, whether that's a pasted
  // token for a non-ArcGIS URL that becomes ArcGIS, or a minted ArcGIS
  // token for one portal surviving a swap to another. Editing only the
  // path within the SAME origin (e.g. switching between two FeatureServer
  // layers on one ArcGIS org) is not a credential hazard, so that alone
  // does not reset.
  useEffect(() => {
    if (authOrigin === lastAuthOriginRef.current) return;
    lastAuthOriginRef.current = authOrigin;
    signinGenerationRef.current += 1;
    setArcgisAuthMethod('none');
    setToken('');
    setPortalUrl('');
    setUsername('');
    setPassword('');
    setTokenExpiresAt(null);
    setSigninError(null);
  }, [authOrigin]);

  const reset = () => {
    signinGenerationRef.current += 1;
    setStep('idle');
    setUrl('');
    setToken('');
    setProbeResult(null);
    setPreviewData(null);
    setJobId(null);
    setError(null);
    setArcgisAuthMethod('none');
    setPortalUrl('');
    setUsername('');
    setPassword('');
    setTokenExpiresAt(null);
    setSigningIn(false);
    setSigninError(null);
  };

  // Switching methods discards the other branch's fields rather than
  // half-honouring them (mirrors the backend's own `auth` object rule,
  // plan 3.4). A stale password or a stale pasted token left over from the
  // method the user just backed out of must never ride along silently.
  const handleAuthMethodChange = (next: ArcgisAuthMethod) => {
    signinGenerationRef.current += 1;
    setArcgisAuthMethod(next);
    setToken('');
    setUsername('');
    setPassword('');
    setTokenExpiresAt(null);
    setSigninError(null);
    setPortalUrl(next === 'signin' ? originOf(url) : '');
  };

  const handleArcgisSignin = async () => {
    // codex review #1757 P1: capture the generation this request belongs to.
    // If the auth context resets (method switch, URL origin change, or the
    // wizard resetting) before this resolves, applying its result would
    // resurrect a token or error message the user already backed away
    // from, so only the token/expiry/error application below is gated on
    // it. Clearing the password and the loading flag happens unconditionally
    // in `finally`: this is the only sign-in that can be in flight at once
    // (the button and the select both disable while signingIn is true), so
    // there is never a newer request whose loading state this could stomp.
    const generation = signinGenerationRef.current;
    setSigningIn(true);
    setSigninError(null);
    try {
      const result = await arcgisSignin({
        portal_url: portalUrl.trim(),
        username: username.trim(),
        password,
      });
      if (signinGenerationRef.current === generation) {
        setToken(result.token);
        setTokenExpiresAt(result.expires_at);
      }
    } catch (err) {
      if (signinGenerationRef.current === generation) {
        setSigninError(
          err instanceof ApiError ? err.message : t('serviceUrl.arcgisSigninFailed'),
        );
      }
    } finally {
      // Clear the password from state the instant the attempt settles,
      // success or failure alike, and never retry automatically. ArcGIS
      // locks an account after five failed sign-ins in fifteen minutes, and
      // a retry loop here could do that to a real customer's account.
      setPassword('');
      setSigningIn(false);
    }
  };

  const handleConnect = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = url.trim();
    if (!trimmed) return;

    setStep('probing');
    setError(null);

    try {
      const result = await probeService(trimmed, token || undefined);
      setProbeResult(result);
      setStep('layer-select');
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : t('serviceUrl.connectFailed');
      setError(msg);
      setStep('idle');
      toast.error(msg);
    }
  };

  const handleLayerSelect = async (layer: LayerInfo) => {
    if (!probeResult) return;

    setStep('previewing');
    setError(null);

    const request: ServicePreviewRequest = {
      url: probeResult.url,
      service_type: probeResult.service_type,
      layer_name: layer.name,
      layer_title: layer.title,
      layer_id: layer.layer_id,
      token: token || undefined,
      object_id_field: layer.object_id_field,
    };

    try {
      const result = await previewServiceLayer(request);
      setPreviewData(result);
      setStep('review');
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        const body = err.body as { code?: string; existing_dataset_id?: string; existing_title?: string } | undefined;
        if (body?.code === 'duplicate_source' && body.existing_dataset_id) {
          const title = body.existing_title ?? t('serviceUrl.unknownDataset');
          const msg = t('serviceUrl.alreadyRegistered', { title });
          setError(msg);
          setStep('layer-select');
          toast.error(msg, {
            action: {
              label: t('serviceUrl.viewExisting'),
              onClick: () => { window.location.href = `/datasets/${body.existing_dataset_id}`; },
            },
          });
          return;
        }
      }
      const msg = err instanceof ApiError ? err.message : t('serviceUrl.previewFailed');
      setError(msg);
      setStep('layer-select');
      toast.error(msg);
    }
  };

  const handleCommit = async (metadata: CommitImportRequest) => {
    if (!previewData) return;

    setStep('committing');

    try {
      await commitImport(previewData.job_id, { ...metadata, ...(token && { token }) });
      setJobId(previewData.job_id);
      setStep('tracking');
      toast.success(t('serviceUrl.importStarted'));
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : t('serviceUrl.commitFailed');
      setError(msg);
      setStep('review');
      toast.error(msg);
    }
  };

  // ── Loading states ──
  if (step === 'probing' || step === 'previewing') {
    const loadingLabel = step === 'probing' ? t('serviceUrl.connecting') : t('serviceUrl.loadingPreview');
    return (
      <div className="flex items-center gap-3 rounded-xl border border-border bg-card px-5 py-8 justify-center">
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <span className="text-sm text-muted-foreground">{loadingLabel}</span>
      </div>
    );
  }

  // ── Layer selection with probe result ──
  if (step === 'layer-select' && probeResult) {
    return (
      <div className="space-y-5">
        {/* Probe input — detected state */}
        <div className="rounded-xl border border-border bg-card p-5">
          <label className="eyebrow mb-2.5 block">
            {t('serviceUrl.detectedLabel', { defaultValue: 'Service URL — detected' })}
          </label>
          <div className="flex items-stretch overflow-hidden rounded-lg border-[1.5px] border-success bg-surface-0">
            <span className="flex items-center gap-1.5 border-e border-border bg-success/10 px-3.5 font-mono text-mini font-semibold uppercase tracking-wider text-success">
              <Check className="size-3.5" />
              {probeResult.service_type}
            </span>
            <input
              type="text"
              readOnly
              value={probeResult.url}
              className="flex-1 bg-transparent px-3.5 py-2.5 font-mono text-sm text-foreground outline-none"
            />
            <button
              onClick={reset}
              className="border-s border-border bg-surface-2 px-4 text-xs font-medium text-muted-foreground hover:bg-surface-3 hover:text-foreground"
            >
              {t('serviceUrl.clear', { defaultValue: 'Clear' })}
            </button>
          </div>
        </div>

        {/* Service info + layer cards */}
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <div className="flex items-center gap-3.5 border-b border-border px-5 py-3.5">
            <span className="rounded-md bg-type-vrt-bg px-2.5 py-0.5 font-mono text-mini font-semibold uppercase tracking-wider text-type-vrt">
              {probeResult.service_type}
            </span>
            <div className="flex-1">
              <h3 className="text-sm font-medium tracking-tight">
                {probeResult.url}
              </h3>
              <p className="font-mono text-mini text-muted-foreground tracking-wide">
                {t('serviceUrl.layersAvailable', { count: probeResult.layers.length, defaultValue: `${probeResult.layers.length} layers available` })}
              </p>
            </div>
          </div>

          <div className="grid gap-2 p-2 sm:grid-cols-2">
            {probeResult.layers.length === 0 && (
              <p className="col-span-2 px-3 py-4 text-center text-sm text-muted-foreground">
                {t('serviceUrl.noLayers', { defaultValue: 'No layers were found in this service.' })}
              </p>
            )}
            {probeResult.layers.map((layer) => {
              // D-10 (Phase 1057 CLASS-07): consume backend-classified layer.kind directly.
              // Previously re-derived from geometry_type string contents, which failed
              // when geometry_type is null (the post-D-05 default for OGC API / WFS layers).
              return (
                <button
                  // fix(#1746): keyed by layer_id, not layer.name — two
                  // layers in the same service can share a display name
                  // (e.g. two ArcGIS sublayers both titled
                  // REC_PassiveConservedAccessScore), and a name-keyed list
                  // collapses/misrenders duplicates. layer_id is what the
                  // backend already dedupes on.
                  key={layer.layer_id ?? layer.name}
                  onClick={() => handleLayerSelect(layer)}
                  className={cn(
                    'flex items-center gap-2.5 rounded-lg border border-border p-2.5 text-start transition-colors',
                    'hover:bg-surface-2',
                  )}
                >
                  <TypeTag kind={layer.kind} size="sm" />
                  <div className="flex-1 min-w-0">
                    <p className="truncate text-xs font-medium tracking-tight">
                      {layer.title || layer.name}
                    </p>
                    <p className="truncate font-mono text-2xs text-muted-foreground tracking-wide mt-0.5">
                      {layer.name}
                      {layer.geometry_type && ` · ${layer.geometry_type}`}
                    </p>
                  </div>
                </button>
              );
            })}
          </div>

          {error && (
            <p className="border-t border-border px-5 py-3 text-sm text-destructive">{error}</p>
          )}
        </div>
      </div>
    );
  }

  // ── Review and commit ──
  if ((step === 'review' || step === 'committing') && previewData) {
    return (
      <div className="space-y-4">
        <ImportPreview preview={previewData} />
        {error && <p className="text-sm text-destructive">{error}</p>}
        <ImportMetadataForm
          defaultName={previewData.source_filename ?? previewData.layer_name}
          detectedCrs={previewData.crs}
          onCommit={handleCommit}
          isCommitting={step === 'committing'}
        />
        <Button variant="outline" onClick={reset}>
          {t('serviceUrl.startOver')}
        </Button>
      </div>
    );
  }

  // ── Job tracking ──
  if (step === 'tracking' && jobId) {
    return <JobProgress jobId={jobId} onReset={reset} />;
  }

  // ── Idle — URL input form ──
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <form onSubmit={handleConnect} className="space-y-5">
        <div>
          <label className="eyebrow mb-2.5 block">
            {t('serviceUrl.label', { defaultValue: 'Service URL — we\'ll auto-detect the type' })}
          </label>
          <div className="flex items-stretch overflow-hidden rounded-lg border-[1.5px] border-border bg-surface-0 transition-colors focus-within:border-primary">
            <span className="flex items-center gap-1.5 border-e border-border bg-surface-2 px-3.5 font-mono text-mini uppercase tracking-wider text-muted-foreground font-medium">
              <Globe className="size-3.5" />
              URL
            </span>
            <input
              type="url"
              placeholder={t('serviceUrl.placeholder')}
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="flex-1 bg-transparent px-3.5 py-2.5 font-mono text-sm text-foreground outline-none placeholder:text-muted-foreground/50"
            />
            <button
              type="submit"
              disabled={!url.trim()}
              className="bg-primary px-4 text-xs font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
            >
              {t('serviceUrl.probe', { defaultValue: 'Probe →' })}
            </button>
          </div>
          <div className="mt-2.5 flex flex-wrap gap-4 text-xs text-muted-foreground">
            <span>
              {t('serviceUrl.supported', { defaultValue: 'Supported:' })}{' '}
              <code className="rounded-sm bg-surface-2 px-1.5 py-px font-mono text-mini text-muted-foreground">WFS</code>{' '}
              <code className="rounded-sm bg-surface-2 px-1.5 py-px font-mono text-mini text-muted-foreground">ArcGIS FeatureServer</code>{' '}
              <code className="rounded-sm bg-surface-2 px-1.5 py-px font-mono text-mini text-muted-foreground">OGC API Features</code>
            </span>
          </div>
        </div>

        {looksLikeArcGisServiceUrl(url) ? (
          <div className="space-y-3" data-testid="arcgis-auth-block">
            <div className="space-y-2">
              <Label htmlFor="arcgis-auth-method" className="text-xs text-muted-foreground">
                {t('serviceUrl.authMethodLabel', { defaultValue: 'Authentication' })}
              </Label>
              <Select
                value={arcgisAuthMethod}
                onValueChange={(value) => handleAuthMethodChange(value as ArcgisAuthMethod)}
                disabled={signingIn}
              >
                <SelectTrigger
                  id="arcgis-auth-method"
                  aria-label={t('serviceUrl.authMethodLabel', { defaultValue: 'Authentication' })}
                  className="w-full"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">
                    {t('serviceUrl.authMethodNone', { defaultValue: 'No authentication' })}
                  </SelectItem>
                  <SelectItem value="signin">
                    {t('serviceUrl.authMethodSignin', {
                      defaultValue: 'Sign in with username and password',
                    })}
                  </SelectItem>
                  <SelectItem value="token">
                    {t('serviceUrl.authMethodToken', { defaultValue: 'Paste a token or API key' })}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            {arcgisAuthMethod === 'token' && (
              <div className="space-y-2">
                <Label htmlFor="access-token" className="text-xs text-muted-foreground">
                  {t('serviceUrl.arcgisTokenFieldLabel', { defaultValue: 'Token or API key' })}
                </Label>
                <Input
                  id="access-token"
                  type="password"
                  placeholder={t('serviceUrl.tokenPlaceholder')}
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  className="font-mono text-sm"
                  // fix(#1746): this is a request-only service token, not a
                  // login credential, and autocomplete="off" alone does not
                  // stop Chrome from offering a saved password here, so opt
                  // out of every password manager explicitly.
                  autoComplete="new-password"
                  data-1p-ignore
                  data-lpignore="true"
                  data-bwignore
                />
                <p className="text-xs text-muted-foreground">
                  {t('serviceUrl.arcgisTokenHelpText', {
                    defaultValue:
                      "Use an API key if your account can create one; Viewer accounts and accounts using single sign-on or multi-factor authentication can't. Otherwise, generate one from your portal's Sharing API with client=referer. Tokens last at most 15 days.",
                  })}
                </p>
              </div>
            )}

            {arcgisAuthMethod === 'signin' && (
              <div className="space-y-3 rounded-lg border border-border bg-surface-0 p-3.5">
                <div className="space-y-2">
                  <Label htmlFor="arcgis-portal-url" className="text-xs text-muted-foreground">
                    {t('serviceUrl.portalUrlLabel', { defaultValue: 'Portal URL' })}
                  </Label>
                  <Input
                    id="arcgis-portal-url"
                    type="url"
                    placeholder={t('serviceUrl.portalUrlPlaceholder', {
                      defaultValue: 'https://your-org.maps.arcgis.com',
                    })}
                    value={portalUrl}
                    onChange={(e) => setPortalUrl(e.target.value)}
                    className="font-mono text-sm"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="arcgis-username" className="text-xs text-muted-foreground">
                    {t('serviceUrl.usernameLabel', { defaultValue: 'Username' })}
                  </Label>
                  <Input
                    id="arcgis-username"
                    type="text"
                    autoComplete="username"
                    placeholder={t('serviceUrl.usernamePlaceholder', { defaultValue: 'Username' })}
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    className="text-sm"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="arcgis-password" className="text-xs text-muted-foreground">
                    {t('serviceUrl.passwordLabel', { defaultValue: 'Password' })}
                  </Label>
                  <Input
                    id="arcgis-password"
                    type="password"
                    placeholder={t('serviceUrl.passwordPlaceholder', { defaultValue: 'Password' })}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="text-sm"
                    // This is a genuine third-party ArcGIS login, not a
                    // GeoLens one, and a password manager offering to save it
                    // would save it against the GeoLens origin, which is
                    // misleading, so opt every manager out the same way the
                    // token field does (#1750).
                    autoComplete="new-password"
                    data-1p-ignore
                    data-lpignore="true"
                    data-bwignore
                  />
                </div>

                {signinError && (
                  <p className="text-sm text-destructive">{signinError}</p>
                )}

                <div className="flex flex-wrap items-center gap-3">
                  <Button
                    type="button"
                    size="sm"
                    disabled={signingIn || !portalUrl.trim() || !username.trim() || !password}
                    onClick={handleArcgisSignin}
                  >
                    {signingIn
                      ? t('serviceUrl.signingIn', { defaultValue: 'Signing in...' })
                      : t('serviceUrl.signinButton', { defaultValue: 'Sign in' })}
                  </Button>
                  {token && tokenExpiresAt && (
                    <span className="text-xs text-muted-foreground">
                      {t('serviceUrl.tokenValidUntil', {
                        time: formatDateTimeSmart(tokenExpiresAt),
                        defaultValue: `Token valid until ${formatDateTimeSmart(tokenExpiresAt)}`,
                      })}
                    </span>
                  )}
                </div>

                {token && (
                  <div className="space-y-2">
                    <Label htmlFor="arcgis-minted-token" className="text-xs text-muted-foreground">
                      {t('serviceUrl.arcgisTokenFieldLabel', { defaultValue: 'Token or API key' })}
                    </Label>
                    <Input
                      id="arcgis-minted-token"
                      type="password"
                      readOnly
                      value={token}
                      className="font-mono text-sm"
                      // Same request-only-credential opt-outs as the pasted
                      // token field above (#1746); this one just displays
                      // a value GeoLens minted rather than one the user typed.
                      autoComplete="new-password"
                      data-1p-ignore
                      data-lpignore="true"
                      data-bwignore
                    />
                  </div>
                )}

                <p className="text-xs text-muted-foreground">
                  {t('serviceUrl.signinHelpText', {
                    defaultValue:
                      "Signing in mints a token valid for 60 minutes; an import that runs longer will need a new one. This won't reach a portal on a private network, so paste a token instead if yours is private.",
                  })}
                </p>
              </div>
            )}
          </div>
        ) : (
          <div className="space-y-2">
            <Label htmlFor="access-token" className="text-xs text-muted-foreground">
              {t('serviceUrl.tokenLabel')}
            </Label>
            <Input
              id="access-token"
              type="password"
              placeholder={t('serviceUrl.tokenPlaceholder')}
              value={token}
              onChange={(e) => setToken(e.target.value)}
              className="font-mono text-sm"
              // fix(#1746): this is a request-only service token, not a login
              // credential — autocomplete="off" alone does not stop Chrome from
              // offering a saved password here, so opt out of every password
              // manager explicitly.
              autoComplete="new-password"
              data-1p-ignore
              data-lpignore="true"
              data-bwignore
            />
            <p className="text-xs text-muted-foreground">{t('serviceUrl.tokenHelpText')}</p>
          </div>
        )}

        {error && <p className="text-sm text-destructive">{error}</p>}
      </form>
    </div>
  );
}

import { useCallback, useEffect, useRef, useState } from 'react';
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
import { defaultPortalFor, looksLikeArcGisServiceUrl, originOf } from './utils';

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

// codex review #1757 round 4 P2: the ONE margin shared by the proactive
// timer (scheduleExpiryTimer) and the synchronous fallback (isPast,
// checked by expireStaleTokenIfPast/isTokenExpiredOrPast). The timer
// used to retire a token 30 seconds early while the synchronous check
// compared against the raw expires_at, so a tab resuming inside that
// 30-second window could still forward a token the component had
// already decided to retire.
const EXPIRY_MARGIN_MS = 30_000;

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
  const [tokenExpired, setTokenExpired] = useState(false);

  // codex review #1757 P1: a stale in-flight sign-in response must never
  // resurrect a token or run after the auth context it belongs to is gone.
  // Bumped on every full auth-state reset below (method switch, URL origin
  // change, or the wizard's own reset()); handleArcgisSignin captures the
  // value at send time and ignores its own response if it no longer matches.
  const signinGenerationRef = useRef(0);
  const authOrigin = originOf(url);
  const isArcGisShaped = looksLikeArcGisServiceUrl(url);
  const lastAuthOriginRef = useRef(authOrigin);
  const lastAuthShapeRef = useRef(isArcGisShaped);

  // codex review #1757 round 2: a minted token stops being usable 30
  // seconds before ArcGIS actually expires it (a safety margin, not a
  // display nicety), even if the wizard is left open. This timer is the
  // single place that enforces that; `expireStaleTokenIfPast` below is the
  // belt-and-suspenders check for the case a backgrounded tab throttled it.
  const expiryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearExpiryTimer = useCallback(() => {
    if (expiryTimerRef.current !== null) {
      clearTimeout(expiryTimerRef.current);
      expiryTimerRef.current = null;
    }
  }, []);

  // codex review #1757 round 2 P2: a minted token is bound to the method,
  // origin, portal URL, username, and password that produced it. Any of
  // those changing (a method switch, a URL origin change, an edit to the
  // portal URL/username/password after a mint, or the wizard's own
  // reset()) must not leave the old token, or its "valid until" claim,
  // looking current, and must invalidate any sign-in still in flight for
  // the context being replaced. A password edit clears the mint too, for
  // symmetry: a new password means a new attempt, not a continuation of
  // the old one. The expiry timer below reuses this same function. Lane
  // A3 applies the identical rule to its own credential block.
  const invalidateMintedCredential = useCallback(() => {
    signinGenerationRef.current += 1;
    clearExpiryTimer();
    setToken('');
    setTokenExpiresAt(null);
    setTokenExpired(false);
  }, [clearExpiryTimer]);

  function isPast(isoTime: string): boolean {
    return new Date(isoTime).getTime() - EXPIRY_MARGIN_MS <= Date.now();
  }

  // codex review #1757 round 2: the timer above is the normal path; this
  // is the fallback for a throttled background tab whose setTimeout fired
  // late (or never, before the user comes back and tries to submit).
  // Called at the top of every place that would otherwise forward `token`
  // to the backend. Returns true when it just refused a stale submission.
  function expireStaleTokenIfPast(): boolean {
    if (token && tokenExpiresAt && isPast(tokenExpiresAt)) {
      signinGenerationRef.current += 1;
      clearExpiryTimer();
      setToken('');
      setTokenExpiresAt(null);
      setTokenExpired(true);
      return true;
    }
    return false;
  }

  // codex review #1757 round 3 P2: the expiry timer's own `expire()` (and
  // expireStaleTokenIfPast above) both clear `token` and `tokenExpiresAt`
  // together, so once either has already run, `expireStaleTokenIfPast`
  // can no longer tell "expired" apart from "never had one" (`token` is
  // already ''). `tokenExpired` is the marker that survives that clear;
  // checking it first (with expireStaleTokenIfPast staying as the
  // fallback for a token that is past its deadline but has not been
  // cleared yet, e.g. a throttled background tab) is what lets a step
  // AFTER the credential form still tell the two apart and refuse with
  // the reconnect message instead of silently proceeding anonymously.
  function isTokenExpiredOrPast(): boolean {
    return tokenExpired || expireStaleTokenIfPast();
  }

  // codex review #1757 round 2: schedule the token's own expiry 30 seconds
  // ahead of ArcGIS's stated deadline, so a wizard left open does not go on
  // submitting a token the service is about to (or already does) reject.
  // Guarded by the generation it was minted under: if the auth context
  // moved on before this fires, `invalidateMintedCredential` already
  // cleared everything and this is a no-op.
  function scheduleExpiryTimer(expiresAt: string, generation: number): void {
    clearExpiryTimer();
    const delay = new Date(expiresAt).getTime() - EXPIRY_MARGIN_MS - Date.now();
    const expire = () => {
      expiryTimerRef.current = null;
      if (signinGenerationRef.current !== generation) return;
      signinGenerationRef.current += 1;
      setToken('');
      setTokenExpiresAt(null);
      setTokenExpired(true);
    };
    if (delay <= 0) {
      expire();
      return;
    }
    expiryTimerRef.current = setTimeout(expire, delay);
  }

  // codex review #1757 P1 / round 3: a credential entered for one auth
  // CONTEXT must never survive being pointed at a different one. Origin is
  // one axis (a pasted token for a non-ArcGIS URL that becomes ArcGIS, or a
  // minted ArcGIS token for one portal surviving a swap to another); the
  // service SHAPE is the other (a token typed for a non-ArcGIS URL, e.g.
  // a WFS field, surviving a path-only edit that turns the same origin
  // into an ArcGIS FeatureServer URL, where it would otherwise sit hidden
  // behind a select showing "No authentication" and still get forwarded).
  // Editing only the path within the SAME origin AND the same shape (e.g.
  // switching between two FeatureServer layers on one ArcGIS org) is not a
  // credential hazard, so that alone does not reset.
  useEffect(() => {
    const originChanged = authOrigin !== lastAuthOriginRef.current;
    const shapeChanged = isArcGisShaped !== lastAuthShapeRef.current;
    lastAuthOriginRef.current = authOrigin;
    lastAuthShapeRef.current = isArcGisShaped;
    if (!originChanged && !shapeChanged) return;
    invalidateMintedCredential();
    setArcgisAuthMethod('none');
    setPortalUrl('');
    setUsername('');
    setPassword('');
    setSigninError(null);
    // invalidateMintedCredential is a fresh closure each render, and the
    // ref checks above already guard this effect so it does real work
    // only on a genuine origin or shape change; including it here is for
    // correctness (react-hooks/exhaustive-deps), not because it can
    // change what this effect does.
  }, [authOrigin, isArcGisShaped, invalidateMintedCredential]);

  // codex review #1757 round 2: the expiry timer must not outlive the
  // component (a backgrounded/unmounted tab has no business scheduling
  // state updates). The wizard's own reset() also invalidates the mint
  // and so clears the timer, so this effect only needs to cover unmount.
  useEffect(() => clearExpiryTimer, [clearExpiryTimer]);

  const reset = () => {
    invalidateMintedCredential();
    setStep('idle');
    setUrl('');
    setProbeResult(null);
    setPreviewData(null);
    setJobId(null);
    setError(null);
    setArcgisAuthMethod('none');
    setPortalUrl('');
    setUsername('');
    setPassword('');
    setSigningIn(false);
    setSigninError(null);
  };

  // Switching methods discards the other branch's fields rather than
  // half-honouring them (mirrors the backend's own `auth` object rule,
  // plan 3.4). A stale password or a stale pasted token left over from the
  // method the user just backed out of must never ride along silently.
  const handleAuthMethodChange = (next: ArcgisAuthMethod) => {
    invalidateMintedCredential();
    setArcgisAuthMethod(next);
    setUsername('');
    setPassword('');
    setSigninError(null);
    setPortalUrl(next === 'signin' ? defaultPortalFor(url) : '');
  };

  const handleArcgisSignin = async () => {
    // codex review #1757 P1: capture the generation this request belongs to.
    // If the auth context resets (method switch, URL origin change, or the
    // wizard resetting) before this resolves, applying its result would
    // resurrect a token or error message the user already backed away
    // from, so only the token/expiry/error application below is gated on
    // it.
    const generation = signinGenerationRef.current;
    setSigningIn(true);
    setSigninError(null);
    setTokenExpired(false);
    try {
      const result = await arcgisSignin({
        portal_url: portalUrl.trim(),
        username: username.trim(),
        password,
      });
      if (signinGenerationRef.current === generation) {
        setToken(result.token);
        setTokenExpiresAt(result.expires_at);
        scheduleExpiryTimer(result.expires_at, generation);
      }
    } catch (err) {
      if (signinGenerationRef.current === generation) {
        setSigninError(
          err instanceof ApiError ? err.message : t('serviceUrl.arcgisSigninFailed'),
        );
      }
    } finally {
      // codex review #1757 P2: the credential inputs stay enabled while a
      // sign-in is pending (only the method select and the Sign in button
      // disable), so the user can correct the portal URL, username, or
      // password before this settles. That edit already bumped the
      // generation via invalidateMintedCredential, and may have put a new
      // password in state for the next attempt; clearing unconditionally
      // here would wipe that edit out from under the user when this
      // superseded request settles. Gate it on the same generation check
      // the success and error branches use above.
      if (signinGenerationRef.current === generation) {
        // Clear the password from state the instant the attempt settles,
        // success or failure alike, and never retry automatically. ArcGIS
        // locks an account after five failed sign-ins in fifteen minutes,
        // and a retry loop here could do that to a real customer's
        // account.
        setPassword('');
      }
      // Unlike the password, this always runs regardless of generation:
      // the button and the select both stay disabled while signingIn is
      // true, and this is the only sign-in that can be in flight at once,
      // so nothing else will ever flip it back to false if this does not.
      setSigningIn(false);
    }
  };

  const handleConnect = async (e: React.FormEvent) => {
    e.preventDefault();

    // codex review #1757 round 2 / round 3 P2: the timer above should
    // already have cleared an expired token, but a backgrounded tab can
    // throttle setTimeout, and by the time either it or the timer HAS run,
    // `token` state itself is already ''. Either way, calling
    // isTokenExpiredOrPast() here only schedules its side effects for the
    // NEXT render; `token` in this closure is still whatever it was when
    // this handler started running. `currentToken` is the corrected value
    // for the rest of THIS invocation, so Probe below can never forward a
    // token that just got invalidated (round 3 caught this: the discarded
    // boolean this used to check, then ignore, still let a stale `token`
    // reach probeService).
    const currentToken = isTokenExpiredOrPast() ? '' : token;

    // codex review #1757 round 2 P2: the sign-in fields live inside this
    // same <form> (a <form> cannot nest inside another), so pressing Enter
    // in the username or password field submitted straight to Probe
    // instead of signing in, sending the service a request under a
    // credential block that had never actually authenticated. While sign
    // in is the chosen method and no token has been minted yet (using the
    // corrected value above, not the possibly-stale `token`), route ANY
    // submission of this form (Enter in a field, or a click on the same
    // submit button) to sign-in instead of Probe.
    if (isArcGisShaped && arcgisAuthMethod === 'signin' && !currentToken) {
      if (!signingIn && portalUrl.trim() && username.trim() && password) {
        void handleArcgisSignin();
      }
      return;
    }

    const trimmed = url.trim();
    if (!trimmed) return;

    setStep('probing');
    setError(null);

    try {
      const result = await probeService(trimmed, currentToken || undefined);
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

    // codex review #1757 round 2 / round 3: this step is past the
    // credential form, so there is no method select left to route a retry
    // through. Refuse the preview outright and point the user back to
    // reconnect. isTokenExpiredOrPast also catches the case the expiry
    // timer already fired (and so already cleared `token` itself) while
    // this step was open, which expireStaleTokenIfPast alone cannot see.
    if (isTokenExpiredOrPast()) {
      setError(
        t('serviceUrl.arcgisTokenExpiredMidImport', {
          defaultValue:
            'Your ArcGIS sign-in expired while this was open. Go back and sign in again to continue.',
        }),
      );
      return;
    }

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

    // codex review #1757 round 2 / round 3: same reasoning as
    // handleLayerSelect, refusing rather than forwarding a token that
    // expired while this dialog was open, including the case the expiry
    // timer already fired and cleared `token` before this ran.
    if (isTokenExpiredOrPast()) {
      setError(
        t('serviceUrl.arcgisTokenExpiredMidImport', {
          defaultValue:
            'Your ArcGIS sign-in expired while this was open. Go back and sign in again to continue.',
        }),
      );
      return;
    }

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

        {isArcGisShaped ? (
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
                    onChange={(e) => {
                      setPortalUrl(e.target.value);
                      invalidateMintedCredential();
                    }}
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
                    onChange={(e) => {
                      setUsername(e.target.value);
                      invalidateMintedCredential();
                    }}
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
                    onChange={(e) => {
                      setPassword(e.target.value);
                      invalidateMintedCredential();
                    }}
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
                  {tokenExpired && (
                    <span className="text-xs text-destructive">
                      {t('serviceUrl.tokenExpired', {
                        defaultValue: 'Token expired, sign in again',
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

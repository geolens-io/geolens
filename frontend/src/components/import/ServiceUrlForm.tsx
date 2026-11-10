import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { toast } from 'sonner';
import { Globe, Check } from 'lucide-react';
import { cn } from '@/lib/utils';
import { formatDateTimeSmart, formatNumber } from '@/lib/format';
import { getGeometryTypeLabel } from '@/i18n/labels';
import { ApiError } from '@/api/client';
import { probeService, commitImport, arcgisSignin } from '@/api/ingest';
import {
  startServicePreview,
  attachServiceCommit,
  peekServiceImport,
  clearServiceImport,
  type ServiceImportSession,
} from '@/api/service-url-session';
import type {
  ProbeResponse,
  LayerInfo,
  ServicePreviewResponse,
  ServicePreviewRequest,
  CommitImportRequest,
  ServiceAuthRequest,
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
import {
  defaultPortalFor,
  looksLikeArcGisPortalUrl,
  looksLikeArcGisServiceUrl,
  originOf,
} from './utils';

type ServiceStep =
  | 'idle'
  | 'probing'
  | 'layer-select'
  | 'previewing'
  | 'review'
  | 'committing'
  | 'tracking';

// For an ArcGIS FeatureServer/MapServer URL the wizard offers a three-way
// authentication choice. 'none' is an explicit choice ("this service is
// public"), not a blank state.
type ArcgisAuthMethod = 'none' | 'token' | 'signin';

// For a non-ArcGIS-shaped URL (WFS, OGC API Features) the door offers the
// four-way choice the backend's CredentialMethod enum names. ArcGIS stays
// bearer-only (its token is percent-encoded into the query, so
// build_credential_header refuses to compose a header for it), hence a
// separate type from ArcgisAuthMethod rather than a shared one.
type ServiceCredentialMethod = 'none' | 'bearer' | 'basic' | 'header';

// The ONE margin shared by the proactive timer (scheduleExpiryTimer) and the
// synchronous fallback (msUntilExpiry, checked by
// expireStaleTokenIfPast/isTokenExpiredOrPast), so a tab resuming inside the
// window can't forward a token the component already decided to retire.
const EXPIRY_MARGIN_MS = 30_000;

function msUntilExpiry(isoTime: string): number {
  return new Date(isoTime).getTime() - EXPIRY_MARGIN_MS - Date.now();
}

export function ServiceUrlForm({ initialUrl = '' }: { initialUrl?: string }) {
  const { t } = useTranslation('import');
  const [step, setStep] = useState<ServiceStep>('idle');
  const [url, setUrl] = useState(initialUrl);
  const [token, setToken] = useState('');
  const [probeResult, setProbeResult] = useState<ProbeResponse | null>(null);
  const [previewData, setPreviewData] = useState<ServicePreviewResponse | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The probe's 403 is the only failure that blames the credential; matching
  // on the message lets any later setError() clear it without extra resets.
  const [credentialRefusal, setCredentialRefusal] = useState<string | null>(null);
  const credentialInvalid = error !== null && error === credentialRefusal;

  // ArcGIS sign-in.
  const [arcgisAuthMethod, setArcgisAuthMethod] = useState<ArcgisAuthMethod>('none');
  const [portalUrl, setPortalUrl] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [tokenExpiresAt, setTokenExpiresAt] = useState<string | null>(null);
  const [signingIn, setSigningIn] = useState(false);
  const [signinError, setSigninError] = useState<string | null>(null);
  const [tokenExpired, setTokenExpired] = useState(false);

  // Non-ArcGIS credential method. `token` above is reused for the bearer
  // branch, as for ArcGIS's 'token' method; the two are mutually exclusive
  // branches of the ternary below, so neither can read the other's value into
  // a request.
  const [serviceCredentialMethod, setServiceCredentialMethod] =
    useState<ServiceCredentialMethod>('none');
  const [basicUsername, setBasicUsername] = useState('');
  const [basicPassword, setBasicPassword] = useState('');
  const [headerName, setHeaderName] = useState('');
  const [headerValue, setHeaderValue] = useState('');
  const [credentialsReset, setCredentialsReset] = useState(false);

  // A stale in-flight sign-in response must never resurrect a token or run
  // after its auth context is gone. Bumped on every full auth-state reset
  // (method switch, URL origin change, the wizard's reset()); handleArcgisSignin
  // captures it at send time and ignores its response if it no longer matches.
  const signinGenerationRef = useRef(0);
  const authOrigin = originOf(url);
  const isArcGisShaped = looksLikeArcGisServiceUrl(url);
  const isArcGisPortalShaped = looksLikeArcGisPortalUrl(url);
  // Guards every `setState` after an `await` in the preview/commit helpers
  // below, as in UrlImportForm: the module-scoped session keeps running
  // regardless of mount state, but this component must not write into a tree
  // that is no longer live.
  const mountedRef = useRef(false);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);
  const lastAuthOriginRef = useRef(authOrigin);
  const lastAuthShapeRef = useRef(isArcGisShaped);

  // A minted token stops being usable 30 seconds before ArcGIS expires it (a
  // safety margin), even if the wizard is left open. This timer enforces that;
  // `expireStaleTokenIfPast` below covers a backgrounded tab that throttled it.
  const expiryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearExpiryTimer = useCallback(() => {
    if (expiryTimerRef.current !== null) {
      clearTimeout(expiryTimerRef.current);
      expiryTimerRef.current = null;
    }
  }, []);

  // A minted token is bound to the method, origin, portal URL, username and
  // password that produced it. Changing any of them (or the wizard's reset())
  // must not leave the old token or its "valid until" claim looking current,
  // and must invalidate any sign-in in flight for the replaced context. A
  // password edit clears the mint too: a new password is a new attempt. The
  // expiry timer below reuses this function; ArcgisCredentialBlock applies the
  // identical rule.
  const invalidateMintedCredential = useCallback(() => {
    signinGenerationRef.current += 1;
    clearExpiryTimer();
    setToken('');
    setTokenExpiresAt(null);
    setTokenExpired(false);
  }, [clearExpiryTimer]);

  // Fallback for a throttled background tab whose setTimeout fired late (or
  // never). Called at the top of every place that would forward `token` to the
  // backend. Returns true when it just refused a stale submission.
  function expireStaleTokenIfPast(): boolean {
    if (token && tokenExpiresAt && msUntilExpiry(tokenExpiresAt) <= 0) {
      signinGenerationRef.current += 1;
      clearExpiryTimer();
      setToken('');
      setTokenExpiresAt(null);
      setTokenExpired(true);
      return true;
    }
    return false;
  }

  // The expiry timer's `expire()` and expireStaleTokenIfPast both clear
  // `token` and `tokenExpiresAt`, after which "expired" can't be told from
  // "never had one". `tokenExpired` survives that clear; checking it first
  // (expireStaleTokenIfPast stays as the fallback for a token past its deadline
  // but not yet cleared) lets a step after the credential form refuse with the
  // reconnect message instead of silently proceeding anonymously.
  function isTokenExpiredOrPast(): boolean {
    return tokenExpired || expireStaleTokenIfPast();
  }

  // Schedule the token's expiry 30 seconds ahead of ArcGIS's stated deadline,
  // so a wizard left open doesn't submit a token the service is about to
  // reject. Guarded by the generation it was minted under: if the auth context
  // moved on, `invalidateMintedCredential` already cleared everything.
  function scheduleExpiryTimer(expiresAt: string, generation: number): void {
    clearExpiryTimer();
    const delay = msUntilExpiry(expiresAt);
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

  // A credential entered for one auth CONTEXT must never survive being pointed
  // at another. Origin is one axis (a pasted token for a non-ArcGIS URL that
  // becomes ArcGIS, or a minted token surviving a swap to another portal); the
  // service SHAPE is the other (a token typed for a WFS URL surviving a
  // path-only edit that turns the same origin into an ArcGIS FeatureServer URL,
  // where it would sit hidden behind a select showing "No authentication" and
  // still be forwarded). Editing only the path within the same origin and shape
  // (two FeatureServer layers on one org) is not a hazard and doesn't reset.
  useEffect(() => {
    const originChanged = authOrigin !== lastAuthOriginRef.current;
    const shapeChanged = isArcGisShaped !== lastAuthShapeRef.current;
    lastAuthOriginRef.current = authOrigin;
    lastAuthShapeRef.current = isArcGisShaped;
    if (!originChanged && !shapeChanged) return;
    const hadCredentials =
      arcgisAuthMethod !== 'none' ||
      serviceCredentialMethod !== 'none' ||
      [token, username, password, basicUsername, basicPassword, headerName, headerValue].some(
        (value) => value !== '',
      );
    // Retyping a URL passes through empty origins; a later no-op reset must not hide the notice.
    if (hadCredentials) setCredentialsReset(true);
    invalidateMintedCredential();
    setArcgisAuthMethod('none');
    setPortalUrl('');
    setUsername('');
    setPassword('');
    setSigninError(null);
    // The non-ArcGIS credential branch is the other half of the same hazard: a
    // username/password or header key typed for one origin or shape must not
    // survive another. `token` is covered by invalidateMintedCredential.
    setServiceCredentialMethod('none');
    setBasicUsername('');
    setBasicPassword('');
    setHeaderName('');
    setHeaderValue('');
    // invalidateMintedCredential is a fresh closure each render; including it
    // satisfies react-hooks/exhaustive-deps. The ref guards above make this a
    // no-op unless the origin or shape changed, so depending on the credential
    // fields doesn't re-run the reset as they change.
  }, [
    authOrigin,
    isArcGisShaped,
    invalidateMintedCredential,
    arcgisAuthMethod,
    serviceCredentialMethod,
    token,
    username,
    password,
    basicUsername,
    basicPassword,
    headerName,
    headerValue,
  ]);

  // The expiry timer must not outlive the component. The wizard's reset() also
  // invalidates the mint and clears the timer, so this only covers unmount.
  useEffect(() => clearExpiryTimer, [clearExpiryTimer]);

  // As in url-import-session.ts: reset is available from every terminal state,
  // but clearing the session mid-commit orphans a commit that then succeeds
  // untracked, with nothing left to adopt it.
  const commitInFlight = step === 'committing';

  const reset = () => {
    if (commitInFlight) return;
    setCredentialsReset(false);
    invalidateMintedCredential();
    clearServiceImport();
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
    setServiceCredentialMethod('none');
    setBasicUsername('');
    setBasicPassword('');
    setHeaderName('');
    setHeaderValue('');
  };

  // Switching methods discards the other branches' fields rather than
  // half-honouring them, as handleAuthMethodChange below (the backend's `auth`
  // object is oneOf-shaped).
  const handleServiceCredentialMethodChange = (next: ServiceCredentialMethod) => {
    setCredentialsReset(false);
    setServiceCredentialMethod(next);
    setToken('');
    setBasicUsername('');
    setBasicPassword('');
    setHeaderName('');
    setHeaderValue('');
  };

  // The `ServiceAuthRequest` the non-ArcGIS credential branch currently
  // describes, or undefined for 'none' or an incomplete method (the backend
  // requires basic/header to be complete). It stays anonymous rather than send
  // a body the door will 422, until both fields are filled.
  function buildServiceAuth(): ServiceAuthRequest | undefined {
    switch (serviceCredentialMethod) {
      case 'bearer':
        return token.trim() ? { method: 'bearer', token: token.trim() } : undefined;
      case 'basic':
        return basicUsername.trim() && basicPassword
          ? { method: 'basic', username: basicUsername.trim(), password: basicPassword }
          : undefined;
      case 'header':
        return headerName.trim() && headerValue
          ? { method: 'header', header_name: headerName.trim(), header_value: headerValue }
          : undefined;
      default:
        return undefined;
    }
  }

  // Switching methods discards the other branch's fields rather than
  // half-honouring them (the backend's `auth` object rule): a stale password
  // or pasted token from the method the user backed out of must never ride along.
  const handleAuthMethodChange = (next: ArcgisAuthMethod) => {
    setCredentialsReset(false);
    invalidateMintedCredential();
    setArcgisAuthMethod(next);
    setUsername('');
    setPassword('');
    setSigninError(null);
    setPortalUrl(next === 'signin' ? defaultPortalFor(url) : '');
  };

  const handleArcgisSignin = async () => {
    // Capture the generation this request belongs to. If the auth context
    // resets before this resolves, applying its result would resurrect a token
    // or error the user backed away from, so only the token/expiry/error
    // application below is gated on it.
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
      // The credential inputs stay enabled while a sign-in is pending (only the
      // method select and the Sign in button disable), so the user can edit the
      // portal URL, username or password before this settles. That edit bumped
      // the generation and may have put a new password in state; clearing
      // unconditionally would wipe it when this superseded request settles. Gate
      // on the same generation check as the success and error branches.
      if (signinGenerationRef.current === generation) {
        // Clear the password the instant the attempt settles, success or failure,
        // and never retry automatically: ArcGIS locks an account after five
        // failed sign-ins in fifteen minutes.
        setPassword('');
      }
      // Unlike the password, this always runs: the button and select stay
      // disabled while signingIn, and this is the only sign-in that can be in
      // flight, so nothing else would flip it back to false.
      setSigningIn(false);
    }
  };

  const handleConnect = async (e: React.FormEvent) => {
    e.preventDefault();

    // The timer should already have cleared an expired token, but a
    // backgrounded tab can throttle setTimeout, and once it or the timer has
    // run, `token` state is already ''. isTokenExpiredOrPast() only schedules
    // its side effects for the NEXT render, so `token` in this closure is
    // stale. `currentToken` is the corrected value for the rest of THIS
    // invocation, so Probe can never forward a just-invalidated token.
    const currentToken = isTokenExpiredOrPast() ? '' : token;

    // The sign-in fields live inside this same <form> (forms can't nest), so
    // pressing Enter in the username or password field would submit straight to
    // Probe under a credential block that never authenticated. While sign-in is
    // the chosen method and no token has been minted yet (using the corrected
    // value above), route ANY submission of this form to sign-in instead.
    if (isArcGisShaped && arcgisAuthMethod === 'signin' && !currentToken) {
      if (!signingIn && portalUrl.trim() && username.trim() && password) {
        void handleArcgisSignin();
      }
      return;
    }

    const trimmed = url.trim();
    if (!trimmed || isArcGisPortalShaped) return;

    setStep('probing');
    setError(null);

    try {
      // ArcGIS forwards a bare bearer token; a non-ArcGIS-shaped URL forwards
      // the structured `auth` object, which can also describe basic or a named
      // header.
      const result = isArcGisShaped
        ? await probeService(trimmed, currentToken || undefined)
        : await probeService(trimmed, undefined, buildServiceAuth());
      setProbeResult(result);
      setStep('layer-select');
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : t('serviceUrl.connectFailed');
      setCredentialRefusal(err instanceof ApiError && err.status === 403 ? msg : null);
      setError(msg);
      setStep('idle');
      toast.error(msg);
    }
  };

  // The session is owned by the module (`service-url-session.ts`), so a tab
  // switch mid-preview cannot strand the job. This only decides what THIS mount
  // displays; `session.promise` keeps running regardless.
  const runPreviewSession = useCallback(
    async (session: ServiceImportSession) => {
      setStep('previewing');
      setError(null);
      try {
        const result = await session.promise;
        if (!mountedRef.current) return;
        setPreviewData(result);
        setStep('review');
      } catch (err) {
        if (!mountedRef.current) return;
        if (err instanceof ApiError && err.status === 409) {
          const body = err.body as { code?: string; existing_dataset_id?: string; existing_title?: string } | undefined;
          if (body?.code === 'duplicate_source' && body.existing_dataset_id) {
            const title = body.existing_title ?? t('serviceUrl.unknownDataset');
            const msg = t('serviceUrl.alreadyRegistered', { title });
            setError(msg);
            // `probeResult` exists only when THIS mount started the preview; a
            // mount adopting a session that failed while unmounted never probed,
            // so there is no layer list to go back to. Fall back to idle rather
            // than render a layer-select with no layers.
            setStep(probeResult ? 'layer-select' : 'idle');
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
        setStep(probeResult ? 'layer-select' : 'idle');
        toast.error(msg);
      }
    },
    [t, probeResult],
  );

  const handleLayerSelect = async (layer: LayerInfo) => {
    if (!probeResult) return;

    // This step is past the credential form, so there is no method select to
    // route a retry through. Refuse the preview and point the user back to
    // reconnect. isTokenExpiredOrPast also catches an expiry timer that already
    // fired and cleared `token`, which expireStaleTokenIfPast alone cannot see.
    if (isTokenExpiredOrPast()) {
      setError(
        t('serviceUrl.arcgisTokenExpiredMidImport', {
          defaultValue:
            'Your ArcGIS sign-in expired while this was open. Go back and sign in again to continue.',
        }),
      );
      return;
    }

    // Same split as Probe: ArcGIS forwards its bearer token under the deprecated
    // `token` field, a non-ArcGIS service under the structured `auth` object.
    // The two are mutually exclusive on the wire (`reject_service_auth_conflict`).
    const request: ServicePreviewRequest = {
      url: probeResult.url,
      service_type: probeResult.service_type,
      layer_name: layer.name,
      layer_title: layer.title,
      layer_id: layer.layer_id,
      token: isArcGisShaped ? token || undefined : undefined,
      auth: isArcGisShaped ? undefined : buildServiceAuth(),
      object_id_field: layer.object_id_field,
    };

    // Pairs the minted token with its expiry in the session.
    await runPreviewSession(
      startServicePreview(request, isArcGisShaped, isArcGisShaped ? tokenExpiresAt : null),
    );
  };

  const handleCommit = async (metadata: CommitImportRequest) => {
    if (!previewData) return;

    // As in handleLayerSelect: refuse rather than forward a token that expired
    // while this dialog was open, including after the timer already cleared it.
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

    // Same split as Probe/Preview above.
    const auth = isArcGisShaped ? undefined : buildServiceAuth();

    const commitPromise = commitImport(previewData.job_id, {
      ...metadata,
      ...(isArcGisShaped && token ? { token } : {}),
      ...(auth ? { auth } : {}),
    });
    // Attached BEFORE the await, so an unmount mid-commit still leaves the
    // operation reachable for the next mount (as `attachUrlImportCommit`).
    attachServiceCommit(commitPromise);

    try {
      await commitPromise;
      if (!mountedRef.current) return;
      setJobId(previewData.job_id);
      setStep('tracking');
      toast.success(t('serviceUrl.importStarted'));
    } catch (err) {
      if (!mountedRef.current) return;
      const msg = err instanceof ApiError ? err.message : t('serviceUrl.commitFailed');
      setError(msg);
      setStep('review');
      toast.error(msg);
    }
  };

  // Restore the credential CONTEXT a resumed session was requested under (`url`,
  // the ArcGIS/non-ArcGIS shape, and whichever of `token`/`auth` it used) so a
  // commit after this remount rebuilds the original request instead of reading
  // fresh component defaults.
  //
  // The origin/shape-change effect below (`lastAuthOriginRef`/
  // `lastAuthShapeRef`) wipes credential state when `url` changes across a
  // render. Restoring `url` here would trigger it and undo this restoration, so
  // the refs are seeded to the resumed URL's origin/shape first and the effect
  // sees no change.
  const restoreSessionCredential = useCallback((session: ServiceImportSession) => {
    lastAuthOriginRef.current = originOf(session.url);
    lastAuthShapeRef.current = session.isArcGisShaped;
    setUrl(session.url);
    if (session.isArcGisShaped) {
      setToken(session.token ?? '');
      // A restored token with no expiry check reads as never-expiring; re-check
      // and reschedule instead of trusting it.
      if (session.token && session.tokenExpiresAt) {
        if (msUntilExpiry(session.tokenExpiresAt) <= 0) {
          setToken('');
          setTokenExpiresAt(null);
          setTokenExpired(true);
        } else {
          setTokenExpiresAt(session.tokenExpiresAt);
          scheduleExpiryTimer(session.tokenExpiresAt, signinGenerationRef.current);
        }
      }
      return;
    }
    const auth = session.auth;
    if (!auth) {
      setServiceCredentialMethod('none');
      return;
    }
    if (auth.method === 'bearer') {
      setServiceCredentialMethod('bearer');
      setToken(auth.token ?? '');
    } else if (auth.method === 'basic') {
      setServiceCredentialMethod('basic');
      setBasicUsername(auth.username ?? '');
      setBasicPassword(auth.password ?? '');
    } else if (auth.method === 'header') {
      setServiceCredentialMethod('header');
      setHeaderName(auth.header_name ?? '');
      setHeaderValue(auth.header_value ?? '');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only restore of the in-flight session's credentials
  }, []);

  // Re-attach to a preview or commit that was running (or finished) while this
  // form was unmounted. Otherwise the job id the server returned to a dead
  // component would be unreachable, plus a pending commit issued against it.
  // Mount-only, as in UrlImportForm: a later session start is driven by user
  // actions.
  useEffect(() => {
    const session = peekServiceImport();
    if (!session) return;
    restoreSessionCredential(session);
    if (session.commit && session.jobId) {
      setStep('committing');
      void (async () => {
        try {
          await session.commit;
          if (!mountedRef.current) return;
          setJobId(session.jobId);
          setStep('tracking');
        } catch (err) {
          if (!mountedRef.current) return;
          // The commit failed, so the job is still `pending` and previewable:
          // rebuild review from the session's retained preview data (it never
          // changes once the preview succeeded) rather than strand the user on
          // a committing spinner for a job nothing will finish.
          const msg = err instanceof ApiError ? err.message : t('serviceUrl.commitFailed');
          setError(msg);
          if (session.previewData) {
            setPreviewData(session.previewData);
            setStep('review');
          } else {
            setStep('idle');
          }
        }
      })();
      return;
    }
    void runPreviewSession(session);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only; later sessions start from user actions
  }, [restoreSessionCredential]);

  if (step === 'probing' || step === 'previewing') {
    const loadingLabel = step === 'probing' ? t('serviceUrl.connecting') : t('serviceUrl.loadingPreview');
    return (
      <div className="flex items-center gap-3 rounded-xl border border-border bg-card px-5 py-8 justify-center">
        <div className="h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <span className="text-sm text-muted-foreground">{loadingLabel}</span>
      </div>
    );
  }

  // The first line already shows the title, so the machine name only repeats when it differs.
  // A layer that cannot be imported gets no geometry or count; the reason line below covers it.
  const layerDetails = (layer: LayerInfo) =>
    [
      layer.title && layer.title !== layer.name ? layer.name : null,
      layer.importable !== false && layer.geometry_type
        ? getGeometryTypeLabel(t, layer.geometry_type)
        : null,
      layer.importable !== false && layer.feature_count != null
        ? t('review.featureCount', {
            count: layer.feature_count,
            value: formatNumber(layer.feature_count),
          })
        : null,
    ]
      .filter(Boolean)
      .join(' · ');

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
              className="min-w-20 flex-1 bg-transparent px-3.5 py-2.5 font-mono text-sm text-foreground outline-none"
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
            <div className="min-w-0 flex-1">
              <h3 className="truncate text-sm font-medium tracking-tight" title={probeResult.url}>
                {probeResult.url}
              </h3>
              <p className="font-mono text-mini text-muted-foreground tracking-wide">
                {t('serviceUrl.layersAvailable', { count: probeResult.layers.length })}
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
              // Consume backend-classified layer.kind directly; geometry_type is
              // null for OGC API / WFS layers.
              const unsupported = layer.importable === false;
              return (
                <button
                  // Keyed by layer_id, not layer.name: two layers in a service can
                  // share a display name (e.g. two ArcGIS sublayers titled
                  // REC_PassiveConservedAccessScore), and a name key would
                  // collapse duplicates. The backend dedupes on layer_id.
                  key={layer.layer_id ?? layer.name}
                  onClick={() => handleLayerSelect(layer)}
                  disabled={unsupported}
                  className={cn(
                    'flex items-center gap-2.5 rounded-lg border border-border p-2.5 text-start transition-colors',
                    unsupported ? 'cursor-not-allowed opacity-60' : 'hover:bg-surface-2',
                  )}
                >
                  <TypeTag kind={layer.kind} size="sm" />
                  <div className="flex-1 min-w-0">
                    <p className="truncate text-xs font-medium tracking-tight">
                      {layer.title || layer.name}
                    </p>
                    <p className="truncate font-mono text-2xs text-muted-foreground tracking-wide mt-0.5">
                      {layerDetails(layer)}
                    </p>
                    {unsupported && (
                      <p className="mt-0.5 text-2xs text-muted-foreground">
                        {t('serviceUrl.unsupportedLayerType', {
                          type: layer.source_layer_type ?? layer.layer_type,
                        })}
                      </p>
                    )}
                  </div>
                </button>
              );
            })}
          </div>

          {error && (
            <p role="alert" className="border-t border-border px-5 py-3 text-sm text-destructive">{error}</p>
          )}
        </div>
      </div>
    );
  }

  if ((step === 'review' || step === 'committing') && previewData) {
    return (
      <div className="space-y-4">
        <ImportPreview preview={previewData} source="service" />
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <ImportMetadataForm
          defaultName={previewData.source_filename ?? previewData.layer_name}
          detectedCrs={previewData.crs}
          onCommit={handleCommit}
          isCommitting={step === 'committing'}
        />
        <Button variant="outline" onClick={reset} disabled={commitInFlight}>
          {t('serviceUrl.startOver')}
        </Button>
      </div>
    );
  }

  if (step === 'tracking' && jobId) {
    return <JobProgress jobId={jobId} onReset={reset} />;
  }

  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <form onSubmit={handleConnect} className="space-y-5">
        <div>
          <label htmlFor="service-url" className="eyebrow mb-2.5 block">
            {t('serviceUrl.label', { defaultValue: 'Service URL — we\'ll auto-detect the type' })}
          </label>
          <div className="flex items-stretch overflow-hidden rounded-lg border-[1.5px] border-border bg-surface-0 transition-colors focus-within:border-primary">
            <span className="flex items-center gap-1.5 border-e border-border bg-surface-2 px-3.5 font-mono text-mini uppercase tracking-wider text-muted-foreground font-medium">
              <Globe className="size-3.5" />
              URL
            </span>
            <input
              id="service-url"
              type="url"
              aria-invalid={error && !credentialInvalid ? true : undefined}
              aria-describedby={error && !credentialInvalid ? 'service-url-error' : undefined}
              placeholder={t('serviceUrl.placeholder')}
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="flex-1 bg-transparent px-3.5 py-2.5 font-mono text-sm text-foreground outline-none placeholder:text-muted-foreground/50"
            />
            <button
              type="submit"
              disabled={!url.trim() || isArcGisPortalShaped}
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

        {credentialsReset && (
          <p
            role="status"
            data-testid="credentials-reset-notice"
            className="text-sm text-muted-foreground"
          >
            {t('serviceUrl.credentialsReset')}
          </p>
        )}

        {isArcGisPortalShaped ? (
          <p
            role="status"
            data-testid="arcgis-portal-url-hint"
            className="text-sm text-muted-foreground"
          >
            {t('serviceUrl.arcgisPortalUrlHint')}
          </p>
        ) : isArcGisShaped ? (
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
                  aria-invalid={credentialInvalid ? true : undefined}
                  aria-describedby={credentialInvalid ? 'access-token-help service-url-error' : 'access-token-help'}
                  className="font-mono text-sm"
                  // A request-only service token, not a login credential, and
                  // autocomplete="off" alone doesn't stop Chrome offering a saved
                  // password here, so opt out of every password manager.
                  autoComplete="new-password"
                  data-1p-ignore
                  data-lpignore="true"
                  data-bwignore
                />
                <p id="access-token-help" className="text-xs text-muted-foreground">
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
                    aria-invalid={signinError ? true : undefined}
                    aria-describedby={signinError ? 'arcgis-signin-error' : undefined}
                    className="text-sm"
                    // A third-party ArcGIS login, not a GeoLens one; a password
                    // manager would save it against the GeoLens origin, which is
                    // misleading, so opt every manager out as the token field does.
                    autoComplete="new-password"
                    data-1p-ignore
                    data-lpignore="true"
                    data-bwignore
                  />
                </div>

                {signinError && (
                  <p id="arcgis-signin-error" role="alert" className="text-sm text-destructive">{signinError}</p>
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
                    <span role="alert" className="text-xs text-destructive">
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
                      // Same password-manager opt-outs as the pasted token
                      // field above; this one displays a value GeoLens minted.
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
          <div className="space-y-3" data-testid="service-credential-block">
            <div className="space-y-2">
              <Label htmlFor="service-credential-method" className="text-xs text-muted-foreground">
                {t('serviceUrl.credentialMethodLabel', { defaultValue: 'Authentication' })}
              </Label>
              <Select
                value={serviceCredentialMethod}
                onValueChange={(value) =>
                  handleServiceCredentialMethodChange(value as ServiceCredentialMethod)
                }
              >
                <SelectTrigger
                  id="service-credential-method"
                  aria-label={t('serviceUrl.credentialMethodLabel', { defaultValue: 'Authentication' })}
                  className="w-full"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">
                    {t('serviceUrl.credentialMethodNone', { defaultValue: 'No authentication' })}
                  </SelectItem>
                  <SelectItem value="bearer">
                    {t('serviceUrl.credentialMethodBearer', { defaultValue: 'Bearer token' })}
                  </SelectItem>
                  <SelectItem value="basic">
                    {t('serviceUrl.credentialMethodBasic', { defaultValue: 'Username and password' })}
                  </SelectItem>
                  <SelectItem value="header">
                    {t('serviceUrl.credentialMethodHeader', { defaultValue: 'API key in a header' })}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>

            {serviceCredentialMethod === 'bearer' && (
              <div className="space-y-2">
                <Label htmlFor="service-credential-token" className="text-xs text-muted-foreground">
                  {t('serviceUrl.credentialTokenLabel', { defaultValue: 'Bearer token' })}
                </Label>
                <Input
                  id="service-credential-token"
                  type="password"
                  aria-invalid={credentialInvalid ? true : undefined}
                  aria-describedby={credentialInvalid ? 'service-url-error' : undefined}
                  placeholder={t('serviceUrl.credentialTokenPlaceholder', {
                    defaultValue: 'Paste your bearer token',
                  })}
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  className="font-mono text-sm"
                  // A request-only service token, not a login credential, and
                  // autocomplete="off" alone doesn't stop Chrome offering a saved
                  // password here, so opt out of every password manager.
                  autoComplete="new-password"
                  data-1p-ignore
                  data-lpignore="true"
                  data-bwignore
                />
              </div>
            )}

            {serviceCredentialMethod === 'basic' && (
              <div className="space-y-3 rounded-lg border border-border bg-surface-0 p-3.5">
                <div className="space-y-2">
                  <Label htmlFor="service-credential-username" className="text-xs text-muted-foreground">
                    {t('serviceUrl.usernameLabel', { defaultValue: 'Username' })}
                  </Label>
                  <Input
                    id="service-credential-username"
                    type="text"
                    autoComplete="username"
                    placeholder={t('serviceUrl.usernamePlaceholder', { defaultValue: 'Username' })}
                    value={basicUsername}
                    onChange={(e) => setBasicUsername(e.target.value)}
                    className="text-sm"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="service-credential-password" className="text-xs text-muted-foreground">
                    {t('serviceUrl.passwordLabel', { defaultValue: 'Password' })}
                  </Label>
                  <Input
                    id="service-credential-password"
                    type="password"
                    placeholder={t('serviceUrl.passwordPlaceholder', { defaultValue: 'Password' })}
                    value={basicPassword}
                    onChange={(e) => setBasicPassword(e.target.value)}
                    className="text-sm"
                    // A service login, as the ArcGIS sign-in fields above: opt
                    // every password manager out rather than let it offer to save
                    // a third-party credential against the GeoLens origin.
                    autoComplete="new-password"
                    data-1p-ignore
                    data-lpignore="true"
                    data-bwignore
                  />
                </div>
              </div>
            )}

            {serviceCredentialMethod === 'header' && (
              <div className="space-y-3 rounded-lg border border-border bg-surface-0 p-3.5">
                <div className="space-y-2">
                  <Label htmlFor="service-credential-header-name" className="text-xs text-muted-foreground">
                    {t('serviceUrl.headerNameLabel', { defaultValue: 'Header name' })}
                  </Label>
                  <Input
                    id="service-credential-header-name"
                    type="text"
                    autoComplete="off"
                    placeholder={t('serviceUrl.headerNamePlaceholder', { defaultValue: 'e.g. X-API-Key' })}
                    value={headerName}
                    onChange={(e) => setHeaderName(e.target.value)}
                    className="font-mono text-sm"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="service-credential-header-value" className="text-xs text-muted-foreground">
                    {t('serviceUrl.headerValueLabel', { defaultValue: 'Header value' })}
                  </Label>
                  <Input
                    id="service-credential-header-value"
                    type="password"
                    placeholder={t('serviceUrl.headerValuePlaceholder', { defaultValue: 'Your API key' })}
                    value={headerValue}
                    onChange={(e) => setHeaderValue(e.target.value)}
                    className="font-mono text-sm"
                    autoComplete="new-password"
                    data-1p-ignore
                    data-lpignore="true"
                    data-bwignore
                  />
                </div>
              </div>
            )}

            {serviceCredentialMethod !== 'none' && (
              <p className="text-xs text-muted-foreground">
                {t('serviceUrl.credentialHelpText', {
                  defaultValue:
                    'Choose the method your service documents. A bearer token is sent as an Authorization header; a username and password are sent as HTTP Basic auth; an API key can go under whatever header name the provider specifies — for example X-API-Key, Ocp-Apim-Subscription-Key, or key.',
                })}
              </p>
            )}
          </div>
        )}

        {error && (
          <p id="service-url-error" role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
      </form>
    </div>
  );
}

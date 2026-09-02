import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { ApiError } from '@/api/client';
import { arcgisSignIn } from '@/api/arcgis-signin';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

type ArcgisAuthMethod = 'none' | 'token' | 'signin';

interface ArcgisCredentialBlockProps {
  token: string;
  onTokenChange: (token: string) => void;
  disabled?: boolean;
}

// codex round (post-#1758 merge): lane A1's merged endpoint
// (arcgis_signin.py, signin_guard.py) ships four more caller-facing codes
// than existed when this map was first written. Confirmed against
// backend/openapi.json and the two source modules directly -- these are
// the complete set of codes `_signin_refusal` can raise, plus `rate_limited`
// (handled separately below by status, since it can also arrive with a
// plain string `detail` from the route-level slowapi limiter rather than
// this shape).
const SIGNIN_ERROR_I18N_KEY: Record<string, string> = {
  arcgis_signin_rejected: 'sourcePanel.refresh.credential.arcgis.errors.arcgisSigninRejected',
  arcgis_sso_account: 'sourcePanel.refresh.credential.arcgis.errors.arcgisSsoAccount',
  ssrf_refused: 'sourcePanel.refresh.credential.arcgis.errors.ssrfRefused',
  network_error: 'sourcePanel.refresh.credential.arcgis.errors.networkError',
  arcgis_portal_not_https: 'sourcePanel.refresh.credential.arcgis.errors.arcgisPortalNotHttps',
  arcgis_portal_host_invalid: 'sourcePanel.refresh.credential.arcgis.errors.arcgisPortalHostInvalid',
  arcgis_signin_in_progress: 'sourcePanel.refresh.credential.arcgis.errors.arcgisSigninInProgress',
};

/**
 * fix(#1755 item 4, plan 3.7/3.2): the refresh door's ArcGIS credential
 * prompt. Lane A2 (PR #1757, `feat/service-auth-a2-arcgis-signin-ui`) ships
 * the equivalent three-way method select for the import wizard
 * (`ServiceUrlForm.tsx`), plus an `arcgisSignin` client in
 * `api/ingest.ts` and hand-typed request/response types in `types/api.ts`.
 * Neither exists on main yet, so this is a minimal, independent copy built
 * against the same contract (plan 3.1's taxonomy, `POST
 * /api/services/arcgis/signin/`, confirmed against lane A1) rather than a
 * fork or an import of A2's branch. A2 also maps `arcgis_signin_rejected`,
 * `arcgis_sso_account`, `ssrf_refused` and `network_error` in
 * `lib/error-map.ts` against the `common` namespace (`translateApiErrorDetail`
 * always resolves there); this component keeps its own local copy under the
 * `dataset` namespace instead, resolved directly from the response code
 * rather than through that shared map, for the same reason -- no shared
 * component to import from yet. A2 and A3 should converge on one component
 * and one copy source in a follow-up once both are on main -- see the PR
 * body.
 *
 * None / Token / Sign in, per plan 3.1. Selecting a method discards the
 * other branch's fields rather than half-honouring them (plan 3.4's oneOf
 * rule, applied here to component state rather than a request body).
 */
export function ArcgisCredentialBlock({ token, onTokenChange, disabled }: ArcgisCredentialBlockProps) {
  const { t } = useTranslation('dataset');
  const [method, setMethod] = useState<ArcgisAuthMethod>('none');
  const [portalUrl, setPortalUrl] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [signInPending, setSignInPending] = useState(false);
  const [signInError, setSignInError] = useState<string | null>(null);
  // Bookkeeping only for the raw value; a ref avoids an extra re-render
  // on every mint/clear. Still explicitly cleared alongside the token
  // itself (codex #1759 round 1, P2).
  const expiresAtRef = useRef<string | null>(null);
  // codex #1759 round 2: distinct from `signInError` -- an expiry is not a
  // rejected sign-in, it is a credential that WAS valid going stale while
  // the dialog sat open. Drives the "Token expired" copy in place of
  // "Signed in".
  const [tokenExpired, setTokenExpired] = useState(false);
  const expiryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearExpiryTimer = () => {
    if (expiryTimerRef.current !== null) {
      clearTimeout(expiryTimerRef.current);
      expiryTimerRef.current = null;
    }
  };

  const isPastExpiry = () =>
    expiresAtRef.current !== null && Date.now() >= new Date(expiresAtRef.current).getTime();

  // codex #1759 round 3, P2: derived from the parent's `token` prop rather
  // than tracked in its own state. "Start refresh" (SourceRefreshAction)
  // clears its `token` state before awaiting the refresh request, win or
  // lose -- a separate `signedIn` boolean would go stale the moment that
  // happens (a rejected refresh left this block still claiming "Signed in"
  // while a retry silently submitted nothing). Deriving it means there is
  // nothing here that CAN desynchronise from the token: whenever `token`
  // clears, for any reason, this becomes false in the same render.
  const isSignedIn = method === 'signin' && token.trim() !== '';
  // fix(codex #1759 round 1, P1/P2): a generation counter, not just a
  // boolean, so a stale attempt's response is dropped even when a NEWER
  // attempt is already in flight (not only on unmount). Bumped on unmount
  // (the dialog closing unmounts this block -- SourceRefreshAction renders
  // it conditionally on `serviceTokenRequired`, which handleOpenChange
  // resets on close) and at the start of every sign-in attempt. Mirrors
  // the generation-counter pattern lane A2 applies in ServiceUrlForm.tsx,
  // so the two blocks converge later.
  const generationRef = useRef(0);

  useEffect(() => {
    return () => {
      generationRef.current += 1;
      clearExpiryTimer();
    };
  }, []);

  // codex #1759 round 2, belt: the scheduled timer above is the primary
  // mechanism, but re-verify on every render too (method switch, a field
  // edit, the `disabled` prop flipping when "Start refresh" is clicked) in
  // case the timer fires late -- background-tab throttling can delay a
  // `setTimeout` well past its nominal delay. Deliberately has no
  // dependency array so it runs after EVERY render, not only when
  // `isSignedIn` changes -- that is the whole point of a render-triggered
  // recheck. Self-heals by running the exact same clear the timer runs;
  // does nothing once `isSignedIn` is already false, so this cannot loop.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (isSignedIn && isPastExpiry()) {
      clearMintedCredential();
      setTokenExpired(true);
    }
  });

  // fix(codex #1759 round 1, P2): a minted token describes the fields it
  // was minted from. Once any of those fields changes, or a new attempt
  // starts, that token no longer describes the account "Start refresh"
  // would otherwise submit -- clear it immediately rather than leaving it
  // reachable until the next sign-in resolves (or fails).
  const clearMintedCredential = () => {
    expiresAtRef.current = null;
    clearExpiryTimer();
    onTokenChange('');
  };

  const handleMethodChange = (value: string) => {
    const next = value as ArcgisAuthMethod;
    setMethod(next);
    setSignInError(null);
    setTokenExpired(false);
    clearMintedCredential();
    if (next !== 'signin') {
      setPortalUrl('');
      setUsername('');
      setPassword('');
    }
  };

  const handlePortalUrlChange = (value: string) => {
    setPortalUrl(value);
    setTokenExpired(false);
    clearMintedCredential();
  };

  const handleUsernameChange = (value: string) => {
    setUsername(value);
    setTokenExpired(false);
    clearMintedCredential();
  };

  const handlePasswordChange = (value: string) => {
    setPassword(value);
    setTokenExpired(false);
    clearMintedCredential();
  };

  const handleSignIn = async () => {
    if (signInPending) return;
    // Start of every new attempt: bump the generation so a still-pending
    // earlier attempt's response (fix P1, below) can never land after this
    // one starts, and clear whatever an earlier attempt minted so a
    // slow-failing retry can't leave it behind for "Start refresh" to
    // submit (fix P2).
    const generation = (generationRef.current += 1);
    setSignInError(null);
    setTokenExpired(false);
    clearMintedCredential();
    setSignInPending(true);
    try {
      const result = await arcgisSignIn({
        portal_url: portalUrl.trim(),
        username,
        password,
      });
      // fix(codex #1759 round 1, P1): dropped when this attempt is stale --
      // either this block unmounted (the dialog was cancelled/closed while
      // the request was in flight; SourceRefreshAction renders this block
      // conditionally and unmounts it on close) or a newer attempt already
      // started. Calling `onTokenChange` here would call the STILL-MOUNTED
      // parent's setter from an unmounted child's stale closure -- React
      // allows that silently, so without this guard a token the user
      // dismissed reappears the next time the dialog opens.
      if (generationRef.current !== generation) return;
      onTokenChange(result.token);
      expiresAtRef.current = result.expires_at;
      // `isSignedIn` is derived from `token` (now non-empty) and `method`
      // (still 'signin' here) -- no separate flag to set.
      // The password has finished its one job -- minting the token -- and
      // must not linger in state any longer than that took.
      setPassword('');

      // codex #1759 round 2: the refresh door only stages this credential
      // and queues the worker -- it does not use it synchronously -- so a
      // dialog left open past the token's lifetime would otherwise submit
      // one already-dead on the wire, and the failure would only surface
      // later in the background. Schedule the clear for a safety margin
      // BEFORE the real expiry, not at it, so a slow clock or a slightly
      // stale local view of `expires_at` still clears before the origin
      // itself would refuse the token.
      clearExpiryTimer();
      const expiresAtMs = new Date(result.expires_at).getTime();
      const EXPIRY_SAFETY_MARGIN_MS = 30_000;
      const delay = Math.max(0, expiresAtMs - Date.now() - EXPIRY_SAFETY_MARGIN_MS);
      expiryTimerRef.current = setTimeout(() => {
        if (generationRef.current !== generation) return;
        clearMintedCredential();
        setTokenExpired(true);
      }, delay);
    } catch (err) {
      if (generationRef.current !== generation) return;
      // No `isSignedIn` to clear: `token` was already cleared at the start
      // of this attempt, before the request, so it was already false.
      let key = 'sourcePanel.refresh.credential.arcgis.errors.networkError';
      if (err instanceof ApiError) {
        if (err.status === 429) {
          key = 'sourcePanel.refresh.credential.arcgis.errors.rateLimited';
        } else {
          const body = err.body as { code?: string } | undefined;
          key = (body?.code && SIGNIN_ERROR_I18N_KEY[body.code]) || key;
        }
      }
      // The error text rendered here is always this component's own copy,
      // keyed off a stable code -- never the raw response body.
      setSignInError(t(key));
    } finally {
      if (generationRef.current === generation) {
        setSignInPending(false);
      }
    }
  };

  const fieldsDisabled = disabled || signInPending;
  const canSignIn = !fieldsDisabled && portalUrl.trim() !== '' && username !== '' && password !== '';

  return (
    <div className="space-y-3 rounded-md border border-border p-3">
      <div className="space-y-2">
        <Label htmlFor="arcgis-credential-method">
          {t('sourcePanel.refresh.credential.arcgis.methodLabel')}
        </Label>
        <select
          id="arcgis-credential-method"
          value={method}
          onChange={(event) => handleMethodChange(event.target.value)}
          disabled={fieldsDisabled}
          className="w-full rounded-md border border-border bg-surface-0 px-3 py-2 text-sm disabled:opacity-60"
        >
          <option value="none">{t('sourcePanel.refresh.credential.arcgis.methodNone')}</option>
          <option value="token">{t('sourcePanel.refresh.credential.arcgis.methodToken')}</option>
          <option value="signin">{t('sourcePanel.refresh.credential.arcgis.methodSignIn')}</option>
        </select>
      </div>

      {method === 'token' && (
        <div className="space-y-2">
          <Label htmlFor="arcgis-credential-token">
            {t('sourcePanel.refresh.credential.arcgis.tokenLabel')}
          </Label>
          <Input
            id="arcgis-credential-token"
            type="password"
            autoComplete="new-password"
            data-1p-ignore
            data-lpignore="true"
            data-bwignore
            value={token}
            onChange={(event) => onTokenChange(event.target.value)}
            placeholder={t('sourcePanel.refresh.credential.arcgis.tokenPlaceholder')}
            disabled={fieldsDisabled}
          />
        </div>
      )}

      {method === 'signin' && (
        <div className="space-y-3">
          <div className="space-y-2">
            <Label htmlFor="arcgis-credential-portal-url">
              {t('sourcePanel.refresh.credential.arcgis.portalUrlLabel')}
            </Label>
            <Input
              id="arcgis-credential-portal-url"
              type="text"
              autoComplete="url"
              value={portalUrl}
              onChange={(event) => handlePortalUrlChange(event.target.value)}
              placeholder={t('sourcePanel.refresh.credential.arcgis.portalUrlPlaceholder')}
              disabled={fieldsDisabled}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="arcgis-credential-username">
              {t('sourcePanel.refresh.credential.arcgis.usernameLabel')}
            </Label>
            <Input
              id="arcgis-credential-username"
              type="text"
              autoComplete="username"
              value={username}
              onChange={(event) => handleUsernameChange(event.target.value)}
              disabled={fieldsDisabled}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="arcgis-credential-password">
              {t('sourcePanel.refresh.credential.arcgis.passwordLabel')}
            </Label>
            <Input
              id="arcgis-credential-password"
              type="password"
              // fix(#1755 item 4, plan 3.2): a genuine third-party login, so a
              // password manager offering to save it is not absurd -- but it
              // would be saved against the GeoLens origin, which is
              // misleading. Opt out the same way the request-only service
              // token field does (#1750).
              autoComplete="new-password"
              data-1p-ignore
              data-lpignore="true"
              data-bwignore
              value={password}
              onChange={(event) => handlePasswordChange(event.target.value)}
              disabled={fieldsDisabled}
            />
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void handleSignIn()}
            disabled={!canSignIn}
          >
            {signInPending && <Loader2 className="me-2 h-4 w-4 animate-spin" />}
            {t('sourcePanel.refresh.credential.arcgis.signInButton')}
          </Button>
          {isSignedIn && !signInError && (
            <p className="text-xs text-muted-foreground">
              {t('sourcePanel.refresh.credential.arcgis.signedIn')}
            </p>
          )}
          {tokenExpired && !signInError && (
            <p className="text-sm text-destructive">
              {t('sourcePanel.refresh.credential.arcgis.tokenExpired')}
            </p>
          )}
          {signInError && <p className="text-sm text-destructive">{signInError}</p>}
        </div>
      )}
    </div>
  );
}

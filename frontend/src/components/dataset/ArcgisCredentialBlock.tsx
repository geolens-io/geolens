import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
import { arcgisSignIn } from '@/api/arcgis-signin';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

type ArcgisAuthMethod = 'none' | 'token' | 'signin';

interface ArcgisCredentialBlockProps {
  token: string;
  onTokenChange: (token: string) => void;
  disabled?: boolean;
}

// The ONE margin shared by the scheduled timer (handleSignIn, below) and this
// synchronous check, as in ServiceUrlForm.tsx (EXPIRY_MARGIN_MS). A
// backgrounded tab resuming inside the last 30 seconds must not pass the check
// and submit a credential the component already decided to retire: refresh
// only queues the worker, so a token that thin can expire before it is used.
const EXPIRY_SAFETY_MARGIN_MS = 30_000;

// A pure function, not a closure over `expiresAtRef`, so the check the
// render-triggered belt effect uses is also callable synchronously from
// SourceRefreshAction's handleConfirm (via the imperative handle below) BEFORE
// it reads and submits `token`. A background tab or system sleep can suspend
// both the timer and this component's re-renders, so the belt effect may not
// run before the user clicks "Start refresh". Margined by
// EXPIRY_SAFETY_MARGIN_MS (above) to agree with the timer.
export function isExpired(expiresAt: string | null, now: number): boolean {
  return expiresAt !== null && now >= new Date(expiresAt).getTime() - EXPIRY_SAFETY_MARGIN_MS;
}

export interface ArcgisCredentialBlockHandle {
  /** The expiry the currently minted token carries, or null. Read this and
   * call `isExpired` rather than trusting `token` alone to be current. */
  getExpiresAt: () => string | null;
  /** Transitions this block to its expired display state (clears the
   * credential, swaps "Signed in" for "Token expired") without waiting for
   * the timer or the belt effect. The caller is expected to have already
   * established, via `isExpired(getExpiresAt(), Date.now())`, that this is
   * warranted -- calling it unconditionally would clear a live token. */
  markExpired: () => void;
}

// apiFetch (client.ts) runs this error's `detail` through error-map.ts
// (`translateApiErrorDetail`) before this component sees it, so
// `ApiError.message` IS the translated text of every refusal shape this
// endpoint returns (arcgis_signin_rejected, arcgis_sso_account,
// ssrf_refused, arcgis_signin_in_progress, arcgis_portal_not_https and
// arcgis_portal_host_invalid under `common:errors.*`; a bare 429 stays
// unmapped because the generic `errors.rateLimited` covers it). Reusing it
// keeps one string per meaning, so this flow and the import wizard's can't
// drift apart. It also covers a FastAPI/pydantic validation array
// (`ArcGISSignInRequest` rejecting input before the route runs), which
// `classifyApiError`'s array branch turns into a translated, field-named
// message.

/**
 * The refresh door's ArcGIS credential prompt: None / Token / Sign in.
 * Selecting a method discards the other branch's fields rather than
 * half-honouring them (the backend's oneOf rule, applied to component state).
 *
 * This is a second copy of the import wizard's method select
 * (`ServiceUrlForm.tsx`), which also has its own `arcgisSignin` client in
 * `api/ingest.ts`; only the error copy is shared, via `ApiError.message` (see
 * above).
 */
export const ArcgisCredentialBlock = forwardRef<ArcgisCredentialBlockHandle, ArcgisCredentialBlockProps>(
  function ArcgisCredentialBlock({ token, onTokenChange, disabled }, ref) {
  const { t } = useTranslation('dataset');
  const [method, setMethod] = useState<ArcgisAuthMethod>('none');
  const [portalUrl, setPortalUrl] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [signInPending, setSignInPending] = useState(false);
  const [signInError, setSignInError] = useState<string | null>(null);
  // Bookkeeping for the raw value; a ref avoids a re-render on every mint/clear.
  // Still cleared alongside the token.
  const expiresAtRef = useRef<string | null>(null);
  // Distinct from `signInError`: a credential that WAS valid going stale while
  // the dialog sat open, not a rejected sign-in. Drives "Token expired" in
  // place of "Signed in".
  const [tokenExpired, setTokenExpired] = useState(false);
  const expiryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearExpiryTimer = () => {
    if (expiryTimerRef.current !== null) {
      clearTimeout(expiryTimerRef.current);
      expiryTimerRef.current = null;
    }
  };

  // Derived from the parent's `token` prop, not tracked in its own state:
  // "Start refresh" (SourceRefreshAction) clears `token` before awaiting the
  // refresh request, win or lose, so a separate `signedIn` boolean would go
  // stale (a rejected refresh left this block claiming "Signed in" while a
  // retry silently submitted nothing). Whenever `token` clears, this becomes
  // false in the same render.
  const isSignedIn = method === 'signin' && token.trim() !== '';
  // A generation counter, not a boolean, so a stale attempt's response is
  // dropped even when a NEWER attempt is in flight. Bumped on unmount (closing
  // the dialog unmounts this block: SourceRefreshAction renders it on
  // `serviceTokenRequired`, which handleOpenChange resets) and at the start of
  // every sign-in attempt. Same pattern as ServiceUrlForm.tsx.
  const generationRef = useRef(0);

  useEffect(() => {
    return () => {
      generationRef.current += 1;
      clearExpiryTimer();
    };
  }, []);

  // Belt and braces: the scheduled timer is primary, but re-verify on every
  // render too (method switch, field edit, `disabled` flipping on "Start
  // refresh") in case a background-tab-throttled `setTimeout` fires late.
  // Deliberately has no dependency array so it runs after EVERY render.
  // Self-heals with the same clear the timer runs; a no-op once `isSignedIn`
  // is false, so it cannot loop.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (isSignedIn && isExpired(expiresAtRef.current, Date.now())) {
      clearMintedCredential();
      setTokenExpired(true);
    }
  });

  // Exposes the synchronous pre-submit check documented on
  // `ArcgisCredentialBlockHandle`. `markExpired` reuses the clear-and-flip the
  // timer and belt effect perform, so the transition lives in one place.
  useImperativeHandle(ref, () => ({
    getExpiresAt: () => expiresAtRef.current,
    markExpired: () => {
      clearMintedCredential();
      setTokenExpired(true);
    },
  }));

  // A minted token describes the fields it was minted from. Once any of them
  // changes, or a new attempt starts, it no longer describes the account
  // "Start refresh" would submit: clear it immediately rather than leave it
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
    // Start of every attempt: bump the generation so a pending earlier
    // attempt's response can't land after this one starts, and clear whatever
    // an earlier attempt minted so a slow-failing retry can't leave it for
    // "Start refresh" to submit.
    const generation = (generationRef.current += 1);
    setSignInError(null);
    setTokenExpired(false);
    clearMintedCredential();
    setSignInPending(true);
    try {
      const result = await arcgisSignIn({
        portal_url: portalUrl.trim(),
        // ArcGISSignInRequest does not strip whitespace and PortalSignIn.mint
        // forwards the value unchanged, so a pasted username with stray
        // whitespace would burn one of the account's limited sign-in attempts
        // on a value that can't match. Same `username.trim()` as ServiceUrlForm.tsx.
        username: username.trim(),
        password,
      });
      // Dropped when this attempt is stale: this block unmounted (dialog
      // closed mid-request) or a newer attempt started. Calling `onTokenChange`
      // from an unmounted child's stale closure would call the STILL-MOUNTED
      // parent's setter, and a token the user dismissed would reappear the next
      // time the dialog opens.
      if (generationRef.current !== generation) return;
      onTokenChange(result.token);
      expiresAtRef.current = result.expires_at;
      // `isSignedIn` is derived from `token` and `method`, so no flag to set.
      // The password is cleared once, in the generation-matched `finally`, so
      // success and failure clear it the same way.

      // The refresh door only stages this credential and queues the worker, so
      // a dialog left open past the token's lifetime would submit one already
      // dead, and the failure would surface later in the background. Schedule
      // the clear a safety margin BEFORE the real expiry so a slow clock or
      // stale local `expires_at` still clears before the origin refuses it.
      clearExpiryTimer();
      const expiresAtMs = new Date(result.expires_at).getTime();
      const delay = Math.max(0, expiresAtMs - Date.now() - EXPIRY_SAFETY_MARGIN_MS);
      expiryTimerRef.current = setTimeout(() => {
        if (generationRef.current !== generation) return;
        clearMintedCredential();
        setTokenExpired(true);
      }, delay);
    } catch (err) {
      if (generationRef.current !== generation) return;
      // `token` was cleared at the start of this attempt, so `isSignedIn` is
      // already false. The error text is always this endpoint's own translated
      // copy (see above), never the raw response body.
      setSignInError(
        err instanceof Error ? err.message : t('common:errors.couldNotReachService'),
      );
    } finally {
      if (generationRef.current === generation) {
        // Cleared on every outcome, not only a successful mint: a rejected or
        // timed-out sign-in would otherwise leave the password in state and in
        // the controlled input, letting a second click resend it, which matters
        // under ArcGIS's five-attempts lockout. Gated on generation, not
        // unconditional, because an edit made during this attempt (portal URL,
        // username or password) bumped the generation and may have put a NEW
        // password in state; clearing unconditionally would wipe it when this
        // superseded request settles. The username is left alone; only the
        // password is too sensitive to linger.
        setPassword('');
        setSignInPending(false);
      }
    }
  };

  const fieldsDisabled = disabled || signInPending;
  // A whitespace-only username must never submit: it trims to '' and would
  // pass a bare `!== ''` check.
  const canSignIn = !fieldsDisabled && portalUrl.trim() !== '' && username.trim() !== '' && password !== '';

  return (
    <div className="space-y-3 rounded-md border border-border p-3">
      <div className="space-y-2">
        <Label htmlFor="arcgis-credential-method">
          {t('sourcePanel.refresh.credential.arcgis.methodLabel')}
        </Label>
        <Select value={method} onValueChange={handleMethodChange} disabled={fieldsDisabled}>
          <SelectTrigger id="arcgis-credential-method" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">{t('sourcePanel.refresh.credential.arcgis.methodNone')}</SelectItem>
            <SelectItem value="token">{t('sourcePanel.refresh.credential.arcgis.methodToken')}</SelectItem>
            <SelectItem value="signin">{t('sourcePanel.refresh.credential.arcgis.methodSignIn')}</SelectItem>
          </SelectContent>
        </Select>
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
              // A third-party login: a password manager offering to save it
              // would save it against the GeoLens origin, which is misleading.
              // Opt out as the request-only service token field does.
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
  },
);

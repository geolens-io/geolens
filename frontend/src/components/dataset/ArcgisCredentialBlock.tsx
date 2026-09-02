import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Loader2 } from 'lucide-react';
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

// codex #1759 round 3 P2: the ONE margin shared by the scheduled timer
// (handleSignIn, below) and this synchronous check -- mirrors lane A2's
// identical fix in ServiceUrlForm.tsx (EXPIRY_MARGIN_MS, codex review
// #1757 round 4 P2) for the same bug shape. The timer used to retire a
// token 30 seconds before its real expiry while this check compared
// against the raw `expires_at`, so a backgrounded tab resuming inside
// that last 30 seconds passed the check and `handleConfirm` submitted a
// credential this component had already decided to retire -- refresh
// only queues the worker, so a token that thin can expire before the
// worker ever uses it.
const EXPIRY_SAFETY_MARGIN_MS = 30_000;

// codex #1759 P2: a pure function, not a closure over `expiresAtRef`, so the
// exact same check the render-triggered belt effect below uses is also
// callable synchronously from SourceRefreshAction's handleConfirm (via the
// imperative handle below) BEFORE it reads and submits `token`. That gap is
// real: a background tab or a system sleep can suspend both the scheduled
// expiry timer and this component's own re-renders, so the belt effect
// never gets a chance to run before the user comes back and clicks "Start
// refresh" -- `handleConfirm` captures `token` synchronously in the same
// tick, ahead of any effect. Margined by EXPIRY_SAFETY_MARGIN_MS (above)
// so this agrees with the timer on when a token counts as retired.
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

// codex #1759, post-#1757-merge dedupe: this block used to carry its own
// {code -> key} table and its own copy for all seven of this endpoint's
// refusal shapes. Lane A2's error-map.ts (frontend/src/lib/error-map.ts)
// now maps every one of them -- arcgis_signin_rejected, arcgis_sso_account,
// ssrf_refused, arcgis_signin_in_progress, arcgis_portal_not_https and
// arcgis_portal_host_invalid -- under `common:errors.*`, and deliberately
// leaves a bare 429 unmapped there because the generic `errors.rateLimited`
// fallback already covers it. apiFetch (client.ts) already runs this
// error's `detail` through that exact map, via `translateApiErrorDetail`,
// before this component ever sees it, so `ApiError.message` (an instance
// of `Error`) IS that translated text -- reusing it, rather than a second
// table repeating the same strings, is the fix: one string, one meaning,
// so this flow and the import wizard's can never drift apart on wording.
// This also covers a FastAPI/pydantic validation array for free (a
// scheme-less portal URL, one carrying credentials, an overlong field --
// `ArcGISSignInRequest` rejecting input before the route runs), since
// `classifyApiError`'s array branch already turns that into a translated,
// field-named message.

/**
 * fix(#1755 item 4, plan 3.7/3.2): the refresh door's ArcGIS credential
 * prompt. Lane A2 (PR #1757, merged) ships the equivalent three-way method
 * select for the import wizard (`ServiceUrlForm.tsx`), its own
 * `arcgisSignin` client in `api/ingest.ts`, and hand-typed request/response
 * types in `types/api.ts`. This component and that select are still two
 * independent copies of the same taxonomy -- converging them into one
 * shared component remains a follow-up -- but the error COPY is no longer
 * duplicated: this component reuses A2's `common:errors.*` mapping in
 * `lib/error-map.ts` via `ApiError.message` (see the comment above) rather
 * than carrying a second `{code -> key}` table under its own namespace.
 *
 * None / Token / Sign in, per plan 3.1. Selecting a method discards the
 * other branch's fields rather than half-honouring them (plan 3.4's oneOf
 * rule, applied here to component state rather than a request body).
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
    if (isSignedIn && isExpired(expiresAtRef.current, Date.now())) {
      clearMintedCredential();
      setTokenExpired(true);
    }
  });

  // codex #1759 P2: exposes the synchronous pre-submit check documented on
  // `ArcgisCredentialBlockHandle` above. `markExpired` reuses the exact
  // clear-and-flip the timer and the belt effect both already perform, so
  // there is still only one place that transition happens.
  useImperativeHandle(ref, () => ({
    getExpiresAt: () => expiresAtRef.current,
    markExpired: () => {
      clearMintedCredential();
      setTokenExpired(true);
    },
  }));

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
        // codex #1759 round 3 P2: ArcGISSignInRequest does not strip
        // whitespace and PortalSignIn.mint forwards the value unchanged,
        // so a pasted username with leading/trailing whitespace would
        // burn one of the ArcGIS account's limited sign-in attempts on a
        // value that was never going to match. Mirrors the import
        // wizard's identical `username.trim()` (ServiceUrlForm.tsx).
        username: username.trim(),
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
      // (still 'signin' here) -- no separate flag to set. The password is
      // cleared once, below, in the generation-matched `finally` -- not
      // here, so success and failure clear it exactly the same way.

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
      // The error text rendered here is always this endpoint's own
      // translated copy (see the module comment above) -- never the raw
      // response body.
      setSignInError(
        err instanceof Error ? err.message : t('common:errors.couldNotReachService'),
      );
    } finally {
      if (generationRef.current === generation) {
        // codex #1759 round 4 P2: cleared here, unconditionally on
        // outcome, not only on a successful mint. A rejected sign-in or a
        // timed-out request used to leave the password sitting in state
        // and in the controlled input until the user edited it or closed
        // the dialog -- contradicting this block's own request-scoped
        // lifetime, and letting the same password be resent by a second
        // click, which matters under ArcGIS's five-attempts lockout.
        // Mirrors the sibling ServiceUrlForm.tsx flow's identical
        // generation-gated clear in its own `finally`. Gated on
        // generation, not unconditional, because an edit already made
        // during this attempt (portal URL, username, or password) bumped
        // the generation and may have put a NEW password in state for the
        // next attempt -- clearing unconditionally here would wipe that
        // out from under the user when this now-superseded request
        // settles. The username is left alone; only the password is
        // treated as too sensitive to linger.
        setPassword('');
        setSignInPending(false);
      }
    }
  };

  const fieldsDisabled = disabled || signInPending;
  // A whitespace-only username must never submit either -- it trims to
  // '' and would otherwise still pass a bare `!== ''` check.
  const canSignIn = !fieldsDisabled && portalUrl.trim() !== '' && username.trim() !== '' && password !== '';

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
  },
);

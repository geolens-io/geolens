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

const SIGNIN_ERROR_I18N_KEY: Record<string, string> = {
  arcgis_signin_rejected: 'sourcePanel.refresh.credential.arcgis.errors.arcgisSigninRejected',
  arcgis_sso_account: 'sourcePanel.refresh.credential.arcgis.errors.arcgisSsoAccount',
  ssrf_refused: 'sourcePanel.refresh.credential.arcgis.errors.ssrfRefused',
  network_error: 'sourcePanel.refresh.credential.arcgis.errors.networkError',
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
  const [signedIn, setSignedIn] = useState(false);
  // Bookkeeping only -- nothing renders the expiry, so a ref avoids an
  // extra re-render on every mint/clear. Still explicitly cleared
  // alongside `signedIn` and the token itself (codex #1759 round 1, P2).
  const expiresAtRef = useRef<string | null>(null);
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
    };
  }, []);

  // fix(codex #1759 round 1, P2): a minted token describes the fields it
  // was minted from. Once any of those fields changes, or a new attempt
  // starts, that token no longer describes the account "Start refresh"
  // would otherwise submit -- clear it immediately rather than leaving it
  // reachable until the next sign-in resolves (or fails).
  const clearMintedCredential = () => {
    setSignedIn(false);
    expiresAtRef.current = null;
    onTokenChange('');
  };

  const handleMethodChange = (value: string) => {
    const next = value as ArcgisAuthMethod;
    setMethod(next);
    setSignInError(null);
    clearMintedCredential();
    if (next !== 'signin') {
      setPortalUrl('');
      setUsername('');
      setPassword('');
    }
  };

  const handlePortalUrlChange = (value: string) => {
    setPortalUrl(value);
    clearMintedCredential();
  };

  const handleUsernameChange = (value: string) => {
    setUsername(value);
    clearMintedCredential();
  };

  const handlePasswordChange = (value: string) => {
    setPassword(value);
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
      setSignedIn(true);
      // The password has finished its one job -- minting the token -- and
      // must not linger in state any longer than that took.
      setPassword('');
    } catch (err) {
      if (generationRef.current !== generation) return;
      setSignedIn(false);
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
          {signedIn && !signInError && (
            <p className="text-xs text-muted-foreground">
              {t('sourcePanel.refresh.credential.arcgis.signedIn')}
            </p>
          )}
          {signInError && <p className="text-sm text-destructive">{signInError}</p>}
        </div>
      )}
    </div>
  );
}

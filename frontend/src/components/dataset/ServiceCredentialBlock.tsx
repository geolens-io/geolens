import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { ServiceAuthRequest } from '@/types/api';

type ServiceCredentialMethod = 'none' | 'bearer' | 'basic' | 'header';

interface ServiceCredentialBlockProps {
  onAuthChange: (auth: ServiceAuthRequest | undefined) => void;
  disabled?: boolean;
}

/**
 * fix(#1746 B4, plan 3.1): the refresh door's WFS / OGC API Features
 * credential prompt. Sibling to `ArcgisCredentialBlock` in this same
 * directory — that component's own module comment already notes the two
 * are independent copies of one taxonomy, converging remains a follow-up —
 * so this one matches its conventions (own state, a callback rather than a
 * controlled value, cleared fields on a method switch) without trying to
 * unify the two.
 *
 * Backend B2b widened this door beyond a bearer-only token to the same
 * four-way `CredentialMethod` the ArcGIS block already offers a three-way
 * slice of (ArcGIS itself stays bearer-only — an ArcGIS token is
 * percent-encoded into the query, so `build_credential_header` never
 * composes a header for it — which is why ArcGIS keeps its own sign-in
 * option instead of gaining Basic/header here).
 *
 * None of these three methods mints or expires a credential the way ArcGIS
 * sign-in does, so there is no imperative handle here for a synchronous
 * pre-submit expiry check — the parent reads whatever `onAuthChange` last
 * reported.
 */
export function ServiceCredentialBlock({ onAuthChange, disabled }: ServiceCredentialBlockProps) {
  const { t } = useTranslation('dataset');
  const [method, setMethod] = useState<ServiceCredentialMethod>('none');
  const [token, setToken] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [headerName, setHeaderName] = useState('');
  const [headerValue, setHeaderValue] = useState('');

  // Reports the credential this block currently describes on every change,
  // rather than the parent pulling it only at submit time — SourceRefreshAction
  // clears its own copy on dialog close/submit the same way it clears the
  // ArcGIS block's token, so it needs the live value, not just a snapshot.
  useEffect(() => {
    if (method === 'none') {
      onAuthChange(undefined);
      return;
    }
    if (method === 'bearer') {
      onAuthChange(token ? { method: 'bearer', token } : undefined);
      return;
    }
    if (method === 'basic') {
      onAuthChange(
        username.trim() && password
          ? { method: 'basic', username: username.trim(), password }
          : undefined,
      );
      return;
    }
    onAuthChange(
      headerName.trim() && headerValue
        ? { method: 'header', header_name: headerName.trim(), header_value: headerValue }
        : undefined,
    );
    // onAuthChange is SourceRefreshAction's setState setter, referentially
    // stable across renders; listed for correctness (react-hooks/exhaustive-deps).
  }, [method, token, username, password, headerName, headerValue, onAuthChange]);

  const handleMethodChange = (value: string) => {
    const next = value as ServiceCredentialMethod;
    setMethod(next);
    setToken('');
    setUsername('');
    setPassword('');
    setHeaderName('');
    setHeaderValue('');
  };

  const fieldsDisabled = disabled;

  return (
    <div className="space-y-3 rounded-md border border-border p-3">
      <div className="space-y-2">
        <Label htmlFor="service-credential-method">
          {t('sourcePanel.refresh.credential.service.methodLabel')}
        </Label>
        <select
          id="service-credential-method"
          value={method}
          onChange={(event) => handleMethodChange(event.target.value)}
          disabled={fieldsDisabled}
          className="w-full rounded-md border border-border bg-surface-0 px-3 py-2 text-sm disabled:opacity-60"
        >
          <option value="none">{t('sourcePanel.refresh.credential.service.methodNone')}</option>
          <option value="bearer">{t('sourcePanel.refresh.credential.service.methodBearer')}</option>
          <option value="basic">{t('sourcePanel.refresh.credential.service.methodBasic')}</option>
          <option value="header">{t('sourcePanel.refresh.credential.service.methodHeader')}</option>
        </select>
      </div>

      {method === 'bearer' && (
        <div className="space-y-2">
          <Label htmlFor="service-credential-token">
            {t('sourcePanel.refresh.credential.service.tokenLabel')}
          </Label>
          <Input
            id="service-credential-token"
            type="password"
            autoComplete="new-password"
            data-1p-ignore
            data-lpignore="true"
            data-bwignore
            value={token}
            onChange={(event) => setToken(event.target.value)}
            placeholder={t('sourcePanel.refresh.credential.service.tokenPlaceholder')}
            disabled={fieldsDisabled}
          />
        </div>
      )}

      {method === 'basic' && (
        <div className="space-y-3">
          <div className="space-y-2">
            <Label htmlFor="service-credential-username">
              {t('sourcePanel.refresh.credential.service.usernameLabel')}
            </Label>
            <Input
              id="service-credential-username"
              type="text"
              autoComplete="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              disabled={fieldsDisabled}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="service-credential-password">
              {t('sourcePanel.refresh.credential.service.passwordLabel')}
            </Label>
            <Input
              id="service-credential-password"
              type="password"
              autoComplete="new-password"
              data-1p-ignore
              data-lpignore="true"
              data-bwignore
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={fieldsDisabled}
            />
          </div>
        </div>
      )}

      {method === 'header' && (
        <div className="space-y-3">
          <div className="space-y-2">
            <Label htmlFor="service-credential-header-name">
              {t('sourcePanel.refresh.credential.service.headerNameLabel')}
            </Label>
            <Input
              id="service-credential-header-name"
              type="text"
              autoComplete="off"
              value={headerName}
              onChange={(event) => setHeaderName(event.target.value)}
              placeholder={t('sourcePanel.refresh.credential.service.headerNamePlaceholder')}
              disabled={fieldsDisabled}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="service-credential-header-value">
              {t('sourcePanel.refresh.credential.service.headerValueLabel')}
            </Label>
            <Input
              id="service-credential-header-value"
              type="password"
              autoComplete="new-password"
              data-1p-ignore
              data-lpignore="true"
              data-bwignore
              value={headerValue}
              onChange={(event) => setHeaderValue(event.target.value)}
              placeholder={t('sourcePanel.refresh.credential.service.headerValuePlaceholder')}
              disabled={fieldsDisabled}
            />
          </div>
        </div>
      )}

      {method !== 'none' && (
        <p className="text-xs text-muted-foreground">
          {t('sourcePanel.refresh.credential.service.helpText')}
        </p>
      )}
    </div>
  );
}

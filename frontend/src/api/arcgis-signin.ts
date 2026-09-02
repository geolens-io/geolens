import { apiFetch } from './client';
import { ARCGIS_SIGNIN_TIMEOUT_MS } from './ingest';

/**
 * Lane A1's endpoint (PR #1758, merged): `POST /api/services/arcgis/signin/`
 * (the sources router is mounted at prefix `/services`; the trailing slash
 * is canonical -- `redirect_slashes=False` means the wrong one 404s rather
 * than redirecting) exchanges a portal URL, username and password for a
 * short-lived ArcGIS token. Request and response shape confirmed against
 * `backend/openapi.json`'s `ArcGISSignInRequest`/`ArcGISSignInResponse`
 * schemas post-merge -- both are exactly `{portal_url, username, password}`
 * in, `{token, expires_at}` out, unchanged from the pre-merge contract this
 * client was built against.
 *
 * Lane A2 (PR #1757, merged) added an equivalent `arcgisSignin` to
 * `frontend/src/api/ingest.ts` with hand-typed request/response types in
 * `frontend/src/types/api.ts`. This file is still a separate, local copy of
 * the request function itself -- collapsing the two into one shared client
 * remains a follow-up -- but `ARCGIS_SIGNIN_TIMEOUT_MS` (below) is imported
 * from there rather than redeclared, so the two calls can't drift onto two
 * different numbers for the same backend bound.
 *
 * The password is sent once, in this request body, and nowhere else. This
 * function does not retry on failure; the caller must not add a retry loop
 * either, since ArcGIS locks an account after five failed sign-ins in
 * fifteen minutes and a retry here would spend the user's own attempts.
 */
export interface ArcgisSignInRequest {
  portal_url: string;
  username: string;
  password: string;
}

export interface ArcgisSignInResponse {
  token: string;
  expires_at: string;
}

export async function arcgisSignIn(
  request: ArcgisSignInRequest,
): Promise<ArcgisSignInResponse> {
  return apiFetch<ArcgisSignInResponse>('/services/arcgis/signin/', {
    method: 'POST',
    body: JSON.stringify(request),
    timeoutMs: ARCGIS_SIGNIN_TIMEOUT_MS,
  });
}

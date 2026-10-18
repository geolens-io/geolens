import { apiFetch } from './client';
import { ARCGIS_SIGNIN_TIMEOUT_MS } from './ingest';

/**
 * `POST /api/services/arcgis/signin/` (the sources router is mounted at
 * `/services`; the trailing slash is canonical, since `redirect_slashes=False`
 * makes the wrong one 404 rather than redirect) exchanges a portal URL, username
 * and password for a short-lived ArcGIS token: `{portal_url, username, password}`
 * in, `{token, expires_at}` out (`ArcGISSignInRequest`/`ArcGISSignInResponse` in
 * `backend/openapi.json`).
 *
 * `arcgisSignin` in `api/ingest.ts` is an equivalent hand-typed copy of this
 * request function; `ARCGIS_SIGNIN_TIMEOUT_MS` is imported from there so the two
 * calls can't drift onto different numbers for the same backend bound.
 *
 * The password is sent once, in this request body, and nowhere else. This
 * function does not retry, and the caller must not add a retry loop: ArcGIS locks
 * an account after five failed sign-ins in fifteen minutes and a retry would
 * spend the user's own attempts.
 */
interface ArcgisSignInRequest {
  portal_url: string;
  username: string;
  password: string;
}

interface ArcgisSignInResponse {
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

import { apiFetch } from './client';

/**
 * Lane A1's contract (service-auth plan, section 3.2): `POST
 * /api/services/arcgis/signin/` (the sources router is mounted at prefix
 * `/services`; the trailing slash is canonical -- `redirect_slashes=False`
 * means the wrong one 404s rather than redirecting) exchanges a portal URL,
 * username and password for a short-lived ArcGIS token.
 *
 * Lane A2 (PR #1757) already added an equivalent `arcgisSignin` to
 * `frontend/src/api/ingest.ts` with hand-typed request/response types in
 * `frontend/src/types/api.ts`. This file is a separate, local copy built
 * against the same contract rather than a pull of A2's branch -- collapse
 * onto A2's version in a follow-up once both lanes are on main (see the PR
 * body).
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
  });
}

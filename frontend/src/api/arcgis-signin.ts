import { apiFetch } from './client';

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
 * Lane A2 (PR #1757, not yet merged) adds an equivalent `arcgisSignin` to
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

// codex #1759 P2: apiFetch's default (REQUEST_TIMEOUT_MS, 30s in client.ts)
// is shorter than this endpoint's own advertised worst case. arcgis_signin.py
// bounds discovery at 20s and the mint POST at 25s
// (_DISCOVERY_DEADLINE_SECONDS, _MINT_DEADLINE_SECONDS) and sums them to "the
// 45 seconds the endpoint has always advertised" in its own comment -- a
// slow but legitimate sign-in past 30s would otherwise abort client-side
// with a spurious network error while the backend was still working.
const ARCGIS_SIGNIN_TIMEOUT_MS = 45_000;

export async function arcgisSignIn(
  request: ArcgisSignInRequest,
): Promise<ArcgisSignInResponse> {
  return apiFetch<ArcgisSignInResponse>('/services/arcgis/signin/', {
    method: 'POST',
    body: JSON.stringify(request),
    timeoutMs: ARCGIS_SIGNIN_TIMEOUT_MS,
  });
}

# SAML SSO

> **SAML SSO requires the `geolens-enterprise` overlay (commercial license).** See the [Enterprise Edition install guide](install-guide.md) for setup. Community edition does not include SAML.

GeoLens Enterprise adds SP-initiated SAML 2.0 single sign-on to any community deployment by loading an enterprise overlay package alongside the core API. Once installed, the admin UI gains a **SAML SSO** tab where you register one or more identity providers (IdPs); end users then sign in by clicking the provider's display name on the login page, complete authentication at the IdP, and are returned to GeoLens with an issued JWT.

| | Value |
|---|---|
| Package | `geolens-enterprise` (commercial; not on PyPI) |
| License | Commercial — contact sales |
| SAML library | [`pysaml2`](https://github.com/IdentityPython/pysaml2) ≥ 7.5.4 |
| Bindings supported | HTTP-Redirect (AuthnRequest), HTTP-POST (Response) |
| Replay defense | In-memory cache, TTL 600s (single-instance) |

## Overview

What it does:

- **SP-initiated SSO** — the user starts at GeoLens; GeoLens redirects them to the IdP; the IdP signs and returns a SAML assertion; GeoLens validates the assertion (signature, expiry, audience, replay) and issues a normal core JWT.
- **JIT user provisioning** — first-time users are auto-created via the existing `find_or_create_oauth_user()` pathway. NameID becomes the unique subject; email and display name come from SAML attributes.
- **Attribute → role mapping** — the IdP's `groups` attribute (or any configured claim) maps to GeoLens roles via the existing per-provider `group_role_mapping` JSON field.
- **Per-IdP SP metadata** — every provider exposes its own `/auth/saml/{slug}/metadata` XML so IdP admins can register or refresh trust automatically.

What V1 does **not** include (deferred to future iterations):

- **Single LogOut (SLO).** Logging out of GeoLens does not log the user out at the IdP, and vice versa.
- **IdP-initiated SSO.** Only SP-initiated flows are accepted (`allow_unsolicited = False`).
- **SP-side AuthnRequest signing.** GeoLens does not maintain an SP keypair; AuthnRequests go out unsigned. Most IdPs accept this.
- **SCIM provisioning.** Users are created on first SAML login only — there is no batch sync API.

## Installation

The enterprise overlay ships as a separate Python package (`geolens-enterprise`) plus an enterprise Docker compose file:

```bash
# Stop community-only stack if it is running
docker compose down

# Start the enterprise stack (loads the overlay + runs the e002 migration)
docker compose -f docker-compose.yml -f docker-compose.enterprise.yml up -d --build
```

Loading the overlay triggers the `e002_add_saml_columns` Alembic migration, which:

1. Adds four nullable columns to `catalog.oauth_providers` (`idp_entity_id`, `idp_sso_url`, `idp_certificate`, `sp_entity_id`).
2. Relaxes the `chk_oauth_providers_type` CHECK constraint to include `'saml'`.

The migration is reversible (`alembic downgrade -1` removes the columns and re-tightens the CHECK), but downgrading destroys any SAML provider rows. Back up first.

Verify the overlay loaded:

```bash
# Should show the SAML routes mounted
curl -fsS http://localhost:8000/openapi.json | jq '.paths | keys[] | select(test("/auth/saml/"))'
```

If the SAML routes are missing, confirm `geolens-enterprise` is installed (`uv pip list | grep enterprise`) and that the API logs include `loaded extension: identity` at startup.

## IdP Configuration

The walkthroughs below cover the three most common enterprise IdPs. The configuration shape is identical for any SAML 2.0 IdP — only the UI labels change.

The values you need from GeoLens for any IdP:

- **SP entityID** — what you put in the GeoLens admin UI under `sp_entity_id`. A sensible default is `https://<your-public-api-url>/auth/saml/<slug>`. **It must match the value the IdP is configured for, exactly** (Pitfall: a stray trailing slash will break audience validation).
- **ACS URL** — `https://<your-public-api-url>/auth/saml/<slug>/acs` (HTTP-POST binding).
- **SP metadata XML** — fetched from `https://<your-public-api-url>/auth/saml/<slug>/metadata` or downloaded via the admin UI's "Download SP Metadata" button per row. Many IdPs accept a metadata URL and re-poll it on a schedule.
- **Required attributes** — at minimum, `email`. Recommended: `displayName` (or your IdP's variant) and `groups` (or whatever claim name your IdP uses; configurable per-provider via `group_claim`).

> **Always request `NAMEID_FORMAT_PERSISTENT` from your IdP.** Email-format NameIDs (`NAMEID_FORMAT_EMAILADDRESS`) break user identity continuity if the IdP later changes a user's email — GeoLens uses NameID as the unique subject, so an email change becomes a new account. Persistent IDs are stable across email changes.

### Okta

1. **Applications → Create App Integration → SAML 2.0**.
2. **General Settings:** name the app (e.g., `GeoLens Production`).
3. **Configure SAML:**
   - **Single sign-on URL** = your ACS URL (`https://<api-url>/auth/saml/<slug>/acs`).
   - **Audience URI (SP Entity ID)** = your SP entityID (default `https://<api-url>/auth/saml/<slug>`).
   - **Name ID format:** `Persistent`.
   - **Application username:** `Okta username` (or whatever your tenant's stable identifier is).
4. **Attribute Statements:** add `email` (value: `user.email`), `displayName` (value: `user.displayName`), and `groups` (filter to the groups you want passed; recommend "Matches regex `.*`" for unrestricted, or specific groups for tighter scoping).
5. **Save**, then **View Setup Instructions** to grab the IdP entityID, SSO URL, and signing certificate. Paste these into GeoLens's SAML admin form (next section).

### Azure AD / Entra ID

1. **Enterprise applications → New application → Create your own application**.
2. Choose **Integrate any other application you don't find in the gallery (Non-gallery)**.
3. **Set up single sign-on → SAML.**
4. **Basic SAML Configuration:**
   - **Identifier (Entity ID)** = your SP entityID.
   - **Reply URL (Assertion Consumer Service URL)** = your ACS URL.
5. **Attributes & Claims:**
   - Default Azure AD claims include `emailaddress` and `displayname` — GeoLens's hardcoded fallback list recognizes both the simple keys (`email`, `displayName`) and the URN forms Azure AD sends (`http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress`, `http://schemas.microsoft.com/identity/claims/displayname`).
   - Add a `groups` claim (or set `group_claim` in the GeoLens admin to match Azure's group-claim URN, e.g., `http://schemas.microsoft.com/ws/2008/06/identity/claims/groups`).
6. **SAML Signing Certificate:** download the **Certificate (Base64)** — paste the PEM into GeoLens's `idp_certificate` field.
7. **Set up section:** copy **Login URL** (→ GeoLens `idp_sso_url`) and **Azure AD Identifier** (→ GeoLens `idp_entity_id`).

### ADFS (Active Directory Federation Services)

1. **AD FS Management → Relying Party Trusts → Add Relying Party Trust**.
2. Select **Enter data about the relying party manually**.
3. **Display name:** `GeoLens`.
4. **Configure URL:** check **Enable support for the SAML 2.0 WebSSO protocol** and enter your ACS URL.
5. **Configure Identifiers:** add your SP entityID.
6. Skip access control / authentication selection (use defaults; tighten later).
7. **Edit Claim Issuance Policy** on the new trust:
   - **Send LDAP Attributes as Claims:** map `E-Mail-Addresses` → `E-Mail Address`, `Display-Name` → `http://schemas.microsoft.com/identity/claims/displayname`.
   - **Send Group Membership as a Claim:** map a security group → `http://schemas.xmlsoap.org/claims/Group`. GeoLens's hardcoded fallback list recognizes the ADFS URN form for groups; configure `group_claim` in the GeoLens admin to match if you use a non-default claim name.
8. Export the **Token-signing certificate** from **Service → Certificates** (right-click → View Certificate → Details → Copy to File → Base-64 encoded X.509).
9. Federation Service identifier (→ GeoLens `idp_entity_id`) is at **Service → Edit Federation Service Properties → Federation Service identifier**.
10. SSO URL (→ GeoLens `idp_sso_url`) is `https://<adfs-host>/adfs/ls/`.

> **ADFS unsigned-AuthnRequest note.** Some ADFS configurations require signed AuthnRequests. V1 does not sign AuthnRequests (no SP keypair). If your ADFS rejects unsigned requests, work with your ADFS admin to allow them on this relying party, or wait for the SP-signing iteration.

## GeoLens Configuration

1. Sign in to the GeoLens admin UI as an administrator.
2. Click **SAML SSO** in the sidebar (visible only when the enterprise overlay is loaded).
3. Click **Add SAML provider**. The form fields:

| Field | Purpose |
|---|---|
| **Slug** | URL-safe identifier (e.g., `okta`, `azuread`, `adfs`). Used in `/auth/saml/<slug>/login` and `/acs` paths. Cannot be changed later without updating the IdP. |
| **Display name** | Shown on the login page button (e.g., "Sign in with Okta"). |
| **IdP entityID** | The IdP's entityID (URL-shaped). From your IdP's metadata. |
| **IdP SSO URL** | The IdP's SingleSignOnService endpoint (HTTP-Redirect or HTTP-POST binding). |
| **IdP signing certificate** | Paste the PEM (with or without `-----BEGIN CERTIFICATE-----` headers — both work). Stored Fernet-encrypted at rest; never returned in admin reads (write-only credential). |
| **SP entityID** | What this GeoLens instance presents to the IdP. Default suggestion is pre-filled (`<public-api-url>/auth/saml/<slug>`). **Must match what you configured IdP-side, exactly.** |
| **Default role** | Role assigned when no group claim matches. Typically `viewer`. |
| **Group claim** | SAML attribute name the IdP sends for group membership (e.g., `groups`, or your IdP's URN form). |
| **Group → role mapping** | JSON map: `{"engineering": "admin", "analysts": "editor", "external": "viewer"}`. The first matching group wins. Changes are recorded in the audit log with old/new values. |

4. Toggle **Enabled** on. Save.
5. Test: open a private browser window, navigate to `https://<your-app-url>/login`, click your provider's display name. You should be redirected to the IdP, sign in there, and land back in GeoLens authenticated.

To rotate the IdP signing certificate (typically yearly), edit the provider, paste the new PEM, save. Existing user sessions are unaffected; new logins use the new certificate. Leaving the certificate field blank on update preserves the existing one.

## Hardening Defaults

GeoLens applies enterprise-grade defaults out of the box. These are not tunable in the admin UI in V1 (deliberately — they are correctness-critical):

| Setting | Value | Reason |
|---|---|---|
| `want_assertions_signed` | `True` | The IdP MUST sign assertions. Unsigned assertions are rejected. |
| `want_response_signed` | `False` | The assertion signature is the strong artifact; wrapping the entire response in another signature is redundant. |
| `authn_requests_signed` | `False` | V1 does not maintain an SP signing keypair. AuthnRequests go out unsigned. |
| `allow_unsolicited` | `False` | IdP-initiated SSO and unsolicited responses are rejected. Every accepted assertion must correspond to an outstanding AuthnRequest GeoLens emitted. |
| `allow_unknown_attributes` | `True` | IdPs send arbitrary attribute names; only the documented fallback list is consumed by `_extract_attr`, the rest are ignored. |
| `accepted_time_diff` | `60` seconds | Clock-skew tolerance on `NotBefore` / `NotOnOrAfter` checks. Increase if your IdP and SP clocks drift more than this. |
| Replay cache | In-memory, TTL 600s | Each accepted assertion ID is recorded for 10 minutes; replays are rejected. **Single-instance only — see Limitations.** |

pysaml2 enforces, on every accepted assertion: signature verification (against the configured `idp_certificate`), `NotBefore` / `NotOnOrAfter` validity (with `accepted_time_diff` tolerance), `AudienceRestriction` includes our SP entityID, and `InResponseTo` matches an outstanding AuthnRequest.

## Limitations

### Multi-instance replay-cache hole

The replay cache is **in-memory per process**. If you run multiple API instances behind a load balancer, an attacker holding a stolen valid assertion can replay it to a different instance than the one that originally accepted it — the second instance has its own cache and will not recognize the replay.

**V1 mitigations (pick one):**

- **Single-instance enterprise deployments.** The simplest path; most enterprise GeoLens deployments are single-instance.
- **Sticky-session load balancing.** Pin a SAML session to the instance that issued the AuthnRequest (the same instance will receive the corresponding ACS POST). Most cloud load balancers support this via cookie-based stickiness.

The Redis-backed replay cache is the planned upgrade path when multi-instance demand surfaces. The replay-cache module is intentionally simple to keep this swap small.

### No SP signing key (AuthnRequests are unsigned)

GeoLens does not generate, store, or rotate an SP keypair in V1. Outbound AuthnRequests are unsigned; most IdPs accept this without complaint. If your IdP requires signed AuthnRequests (some ADFS configurations do), the SP-signing iteration is the structural fix.

### No Single LogOut (SLO)

Logging out of GeoLens (clearing the local JWT) does not log the user out at the IdP. Conversely, an IdP-side logout does not invalidate existing GeoLens JWTs (they expire on their normal schedule via `ACCESS_TOKEN_EXPIRE_MINUTES`). For high-security environments, set short access-token expiries and rely on refresh-token rotation to limit the post-IdP-logout window.

### No IdP-initiated SSO

V1 only accepts SP-initiated flows. If your IdP catalog page shows a "Launch GeoLens" button that takes the user directly to the SAML response, that flow will fail with "Unsolicited response" because GeoLens has no outstanding AuthnRequest to correlate against. End users must start at the GeoLens login page.

### Hardcoded attribute fallback list

Email, display name, and groups are extracted from a hardcoded list of common attribute names (simple keys + the SOAP/Microsoft URN forms). If your IdP sends a non-standard attribute name not on the list, configure `group_claim` per-provider for groups; for email and display name a future per-provider attribute-map JSON would be the structural fix.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `Assertion expired / NotBefore in the future` | Clock skew between IdP and SP | Sync NTP; increase `accepted_time_diff` if drift is unavoidable |
| `Audience mismatch` | The IdP's SP entityID doesn't match `sp_entity_id` exactly | Check for trailing slashes, http-vs-https, port differences. The two values must be byte-for-byte identical |
| `Signature invalid` / `xmlSecCryptoAppKeyLoadEx failed` | `idp_certificate` is stale, malformed, or doesn't match the IdP's current signing key | Re-export the IdP signing certificate; paste fresh into GeoLens admin. The PEM may include or omit `-----BEGIN CERTIFICATE-----` headers — both work |
| User created with the default role on every login | `group_claim` doesn't match the attribute name your IdP sends | Inspect the SAML response (browser dev tools → SAML-tracer extension); set `group_claim` to the actual attribute name (try `groups`, `Groups`, or your IdP's URN form) |
| User can't log in after IdP changed their email | IdP is using `NAMEID_FORMAT_EMAILADDRESS`; the new email is treated as a new NameID | Switch the IdP to `NAMEID_FORMAT_PERSISTENT`; old account can be merged manually via admin user management |
| `Unsolicited response` for every login | The user landed at the IdP first (IdP-initiated SSO) | Have users start at `https://<your-app-url>/login` and click the SAML provider button instead |
| `Unsolicited response: <reqid>` after restarting the API | The outstanding-request tracker is in-memory and was cleared on restart | The user retries the login flow; the new AuthnRequest will be tracked. Pending requests in flight at restart are lost |
| 404 on `/auth/saml/<slug>/login` in production | Either the enterprise overlay didn't load, or the slug is wrong | Check API startup logs for "loaded extension"; verify the slug in the URL exactly matches the slug saved in the admin UI |

## Audit Logging

Every SAML provider mutation (create, update, delete) is recorded in the standard GeoLens audit log via the same path OAuth provider mutations use:

- **Create** — `details.created` snapshot of all non-secret fields at creation time.
- **Update** — `details.changes` map of `{"<field>": {"old": <old>, "new": <new>}}` for every field that changed. Group → role mapping changes are captured here, satisfying the requirement that mapping changes be recorded with old/new values.
- **Delete** — `details.deleted` snapshot of the provider's last state.

Secret fields are unconditionally redacted — the audit log records `{"old": "<redacted>", "new": "<redacted>"}` for `idp_certificate` and the OAuth-side `client_secret` / `client_secret_encrypted`. The actual cert PEM is never written to the audit table; the log is safe to forward to centralized SIEM.

Query audit entries via the existing `/admin/audit` UI (filter by `entity_type=oauth_provider`) or the audit log API.

## Security Posture Summary

The V1 hardening posture is "ship-fast enterprise-grade":

- **Strong:** assertion signature verification (RSA-SHA256 typical), audience restriction, expiry validation with bounded clock-skew, replay defense (single-instance), `allow_unsolicited=False` (rejects IdP-initiated and unsolicited responses), unknown-attribute filtering, secret-at-rest encryption (Fernet via `SECRET_KEY`), audit-log redaction.
- **Deferred:** SP-side AuthnRequest signing, Single LogOut, multi-instance replay (Redis upgrade path), IdP-initiated SSO, SCIM, per-provider attribute-map customization.

If your threat model requires the deferred items, plan for them as separate iterations rather than rolling them into your initial deployment.

## References

- [pysaml2 documentation](https://pysaml2.readthedocs.io/)
- [SAML 2.0 Core specification](https://docs.oasis-open.org/security/saml/v2.0/saml-core-2.0-os.pdf)
- [SAML XML Signature Wrapping (XSW) attacks](https://research.aurainfosec.io/pentest/the-fault-in-our-stars/) — defended against by pysaml2 + xmlsec1; GeoLens's test suite exercises this explicitly.
- [`docs/admin-guide.md`](admin-guide.md) — operating GeoLens in production (audit log, user management, RBAC).
- [`docs/install-guide.md`](install-guide.md) — running a GeoLens instance, including the enterprise overlay.

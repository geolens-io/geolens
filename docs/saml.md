# SAML Single Sign-On

SAML 2.0 single sign-on with IdP-managed group-to-role mapping is an **Enterprise-only** feature shipped by the private `geolens-enterprise` overlay. The open-core build of GeoLens supports local password auth and OAuth 2.0 / OIDC providers (Google, Microsoft, generic OIDC); the SAML provider type is gated 404 in this repo by design.

For SAML setup, IdP metadata exchange, group claim mapping, and JIT-provisioning behavior, see the operator guide on the documentation site:

- **SAML configuration guide:** [docs.getgeolens.com/guides/admin/saml/](https://docs.getgeolens.com/guides/admin/saml/)

For information on obtaining the GeoLens Enterprise overlay, see the README **Enterprise and Security** section or contact `enterprise@getgeolens.com`.

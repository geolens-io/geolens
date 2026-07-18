# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.x     | Yes       |
| < 1.0   | No        |

We only patch the latest release. If you're running an older version, please upgrade before reporting.

## Reporting a Vulnerability

**Do not open a public issue for security vulnerabilities.**

Email **security@getgeolens.com** with:

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fix (optional)

## Response Timeline

- **Acknowledgement:** Within 48 hours of your report
- **Assessment:** Within 7 days we'll confirm the issue and share our remediation plan
- **Fix:** We aim to release a patch within 30 days of confirmation
- **Disclosure:** We'll coordinate public disclosure timing with you

## Scope

This policy covers:

- The `geolens` source repository (this repo)
- Official container images published to GHCR (`ghcr.io/geolens-io/*`)
- Official packages published to PyPI (`geolens`, `geolens-cli`, `geolens-mcp`) and npm (`@geolens/sdk`)
- The public demo at demo.getgeolens.com

Out of scope here (report to the respective repo or contact): the marketing/docs website (getgeolens.com), and Helm/deployment packaging ([geolens-deployments](https://github.com/geolens-io/geolens-deployments)).

## Recognition

We appreciate responsible disclosure and will credit reporters in release notes (unless you prefer to remain anonymous).

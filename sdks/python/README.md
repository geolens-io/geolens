# geolens (Python SDK)

Auto-generated Python SDK for the [GeoLens](https://github.com/geolens-io/geolens) API.

Apache-2.0 licensed. Typed `attrs`-based dataclasses + `httpx` async-ready client + Bearer-token + API-key auth helpers.

See `docs/sdks.md` in the GeoLens repo for installation, regeneration, and version-pin policy.

## Quickstart

```python
from geolens import GeolensClient

client = GeolensClient(base_url="https://geolens.example.com", bearer_token="...")
# See ../../docs/sdks.md for endpoint usage examples.
```

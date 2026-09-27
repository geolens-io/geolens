# geolens (Python SDK)

Auto-generated Python SDK for the [GeoLens](https://github.com/geolens-io/geolens) API.

Apache-2.0 licensed. Typed `attrs`-based dataclasses + `httpx` async-ready client + Bearer-token + API-key auth helpers.

See [docs.getgeolens.com](https://docs.getgeolens.com/) for installation, regeneration, and version-pin policy.

## Quickstart

```python
from geolens import GeolensClient

client = GeolensClient(base_url="https://geolens.example.com/api", bearer_token="...")
# The deployed API is served under /api, so include that suffix in base_url.
# See docs.getgeolens.com for endpoint usage examples.
```

## Downloading a COG

With S3 or a remote source behind a raster dataset, the COG download answers
302 with the file's URL. `cog_download` fetches that URL without sending your
GeoLens credentials to the storage host, and returns the bytes on every
storage backend:

```python
from geolens import cog_download

cog = cog_download.sync(dataset_id, client=client.client)  # or: await cog_download.asyncio(...)
data = cog.payload.read()
```

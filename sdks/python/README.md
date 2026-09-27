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

With a remote source behind a raster dataset, the COG download answers 302
with the file's URL. With S3 it may do the same when the server has presigned
downloads enabled, and streams the file otherwise. `cog_download` fetches that
URL without sending your GeoLens credentials to the storage host, and returns
the file on every storage backend. A further redirect from the storage host is
followed only on that same host. The file is streamed into a temporary file
that moves to disk past a few MiB, so a large COG isn't held in memory:

```python
import shutil

from geolens import cog_download

cog = cog_download.sync(dataset_id, client=client.client)  # or: await cog_download.asyncio(...)
with cog.payload as source, open("dataset.cog.tif", "wb") as target:
    shutil.copyfileobj(source, target)
```

# Egress & air-gap reference

This is a factual reference for what GeoLens reaches out to over the network, and
how to run it with no outbound internet access.

## Default posture

A stock `docker compose up` install makes **no outbound internet calls**. GeoLens
ships no usage telemetry or phone-home. Every egress in the matrix below is
opt-in: nothing in it runs unless you configure it.

## Egress matrix

| Feature | Env var(s) | Destination | Required? | Air-gap note |
| --- | --- | --- | --- | --- |
| AI chat / descriptions | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENAI_BASE_URL` | LLM provider API (Anthropic / OpenAI-compatible) | Optional | Point `OPENAI_BASE_URL` at an in-network LLM (e.g. a self-hosted Ollama at `http://host.docker.internal:11434/v1`), or leave AI unconfigured. |
| Embeddings / semantic search | `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL`, `OPENAI_API_KEY` | Embedding endpoint | Optional | Point at an in-network embedding server, or leave unset to disable semantic search. Falls back to `OPENAI_BASE_URL` when empty. |
| SSO login | OAuth/OIDC client credentials (Google / Microsoft / generic, configured in admin settings) | Identity provider | Optional | Use an in-network IdP, or use built-in password auth. |
| Basemaps | Basemap config + provider keys (Mapbox / Stadia / MapTiler) | Tile CDN | Optional | Ship offline / self-hosted basemap tiles. Raster rendered from your own COGs needs no external basemap tiles. |
| CDN tile delivery | `CDN_BASE_URL` | CDN origin | Optional | Leave unset to serve tiles directly from the app. |
| Remote datasets / COGs / STAC | Per-dataset source URL (set when you register a remote source) | Wherever you register | User-driven | Only fetched if you register remote sources. Uploaded data stays local. |
| Object storage | `S3_ENDPOINT` (when `STORAGE_PROVIDER=s3`) | S3 / MinIO | Optional | Use the in-cluster MinIO (`--profile cloud-dev`) or `STORAGE_PROVIDER=local` for fully local storage. |

## Air-gap checklist

- Leave the AI, embedding, SSO, and `CDN_BASE_URL` vars unset.
- Use `STORAGE_PROVIDER=local`, or in-cluster MinIO for S3-compatible storage.
- Register only local datasets (uploaded files); skip remote COG/STAC sources.
- Use self-hosted basemap tiles instead of a commercial tile CDN.
- Pull the release images into a private registry; the installer pulls prebuilt
  images, so no build-time egress is required.

GeoLens does not run any of the above unless you configure it.

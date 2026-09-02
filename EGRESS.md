# Egress & air-gap reference

This is a factual reference for what GeoLens reaches out to over the network, and
how to run it with no outbound internet access.

## Default posture

A stock `docker compose up` install makes **no server-side outbound calls**.
GeoLens ships no usage telemetry or phone-home. Every row in the matrix below
is opt-in except Basemaps: until an admin replaces the default basemap list
(Admin Settings > Map), the browser fetches map tiles and glyphs from
`tiles.openfreemap.org`. See the Air-gap checklist below to close that off.

## Egress matrix

| Feature | Env var(s) | Destination | Required? | Air-gap note |
| --- | --- | --- | --- | --- |
| AI chat / descriptions | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENAI_BASE_URL` | LLM provider API (Anthropic / OpenAI-compatible) | Optional | Point `OPENAI_BASE_URL` at an in-network LLM (e.g. a self-hosted Ollama at `http://host.docker.internal:11434/v1`), or leave AI unconfigured. |
| Embeddings / semantic search | `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL`, `OPENAI_API_KEY` | Embedding endpoint | Optional | Point at an in-network embedding server, or leave unset to disable semantic search. Falls back to `OPENAI_BASE_URL` when empty. |
| SSO login | OAuth/OIDC client credentials (Google / Microsoft / generic, configured in admin settings) | Identity provider | Optional | Use an in-network IdP, or use built-in password auth. |
| Basemaps | Admin Settings > Map basemap list (add provider keys for Mapbox / Stadia / MapTiler, or replace the defaults) | Tile CDN (`tiles.openfreemap.org` by default) | Default-on | Ship offline / self-hosted basemap tiles and remove the OpenFreeMap/OpenStreetMap presets. Raster rendered from your own COGs needs no external basemap tiles. |
| CDN tile delivery | `CDN_BASE_URL` | CDN origin | Optional | Leave unset to serve tiles directly from the app. |
| Remote datasets / COGs / STAC | Per-dataset source URL (set when you register a remote source) | Wherever you register | User-driven | Only fetched if you register remote sources. Uploaded data stays local. |
| Object storage | `S3_ENDPOINT` (when `STORAGE_PROVIDER=s3`) | S3 / MinIO | Optional | Use the in-cluster MinIO (`--profile cloud-dev`) or `STORAGE_PROVIDER=local` for fully local storage. |
| Backup offsite upload | `BACKUP_S3_ENABLED` plus the shared `S3_ENDPOINT` / `S3_BUCKET` / `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | S3-compatible endpoint | Optional | Default `false`; backups stay on the local `backup_data` volume with no egress. For an offsite copy without internet, point `S3_ENDPOINT` at an in-network MinIO. |
| Email notifications (admin alerts) | `NOTIFICATIONS_ENABLED`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_ADDRESS`, plus at least one `NOTIFY_ON_*` event switch | SMTP server | Optional | Off by default: event alerts need `NOTIFICATIONS_ENABLED=true` and a `NOTIFY_ON_*` switch (all default off); the admin test-send needs only the toggle plus channel config. Use an in-network mail relay, or leave unset. |
| Verification emails (self-serve signup) | `SMTP_HOST` (plus the other `SMTP_*` vars) | SMTP server | Optional | Two triggers: registration sends when the admin "email verification required" setting is on and `SMTP_HOST` is set; the resend-verification endpoint sends for any unverified account whenever `SMTP_HOST` is set, without checking that setting. `NOTIFICATIONS_ENABLED` gates neither. Leave `SMTP_HOST` unset to keep all SMTP egress off. |
| Webhook notifications | `NOTIFICATIONS_ENABLED`, `NOTIFICATION_WEBHOOK_URL`, `NOTIFICATION_WEBHOOK_SECRET`, plus at least one `NOTIFY_ON_*` event switch | Webhook receiver (Slack / Teams / custom) | Optional | Off by default: event alerts need `NOTIFICATIONS_ENABLED=true` and a `NOTIFY_ON_*` switch (all default off); the admin test-send needs only the toggle plus channel config. Point at an in-network receiver, or leave unset. |

## Air-gap checklist

- Leave the AI, embedding, SSO, notification (`SMTP_*`, `NOTIFICATION_WEBHOOK_URL`), and `CDN_BASE_URL` vars unset.
- Keep `BACKUP_S3_ENABLED=false` (the default); backups then never leave the local `backup_data` volume.
- Use `STORAGE_PROVIDER=local`, or in-cluster MinIO for S3-compatible storage.
- Register only local datasets (uploaded files); skip remote COG/STAC sources.
- Replace the default basemap list (Admin Settings > Map) with self-hosted tiles; the OpenFreeMap/OpenStreetMap presets are enabled out of the box.
- Pull the release images into a private registry; the installer pulls prebuilt
  images, so no build-time egress is required.

GeoLens does not run any of the above unless you configure it.

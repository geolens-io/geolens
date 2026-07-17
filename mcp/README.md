# geolens-mcp

Apache-2.0 read-only [Model Context Protocol](https://modelcontextprotocol.io) server for [GeoLens](https://github.com/geolens-io/geolens).

Point a coding agent (Claude Code, Cursor, Codex, …) at a GeoLens instance so it can discover datasets, inspect schemas, and read features and maps from inside a dev session.

**Read-only by design.** Every tool is a `GET` against an existing API endpoint — no writes, ingest, or admin. Calls are scoped to the caller's access: with an API key, the agent sees the datasets that key's user can see; with no credential it sees only public/published data.

## Install

```bash
pip install geolens-mcp        # or: uvx geolens-mcp
```

## Configure

The server reads its target instance and credentials from the environment (same names as the `geolens` CLI):

| Variable | Required | Meaning |
|---|---|---|
| `GEOLENS_INSTANCE` | yes | Instance URL, e.g. `https://geolens.example.com`. The `/api` suffix is appended automatically if you omit it. |
| `GEOLENS_API_KEY` | recommended | API key, sent as `X-Api-Key`. Create one in **Settings → API keys**. Omit for public-only access. |
| `GEOLENS_TOKEN` | — | JWT bearer token, used only if `GEOLENS_API_KEY` is unset. |

## Register with an MCP client

Claude Code:

```bash
claude mcp add geolens -e GEOLENS_INSTANCE=https://geolens.example.com -e GEOLENS_API_KEY=... -- uvx geolens-mcp
```

Cursor / Codex / any client that reads an `mcpServers` block:

```json
{
  "mcpServers": {
    "geolens": {
      "command": "uvx",
      "args": ["geolens-mcp"],
      "env": {
        "GEOLENS_INSTANCE": "https://geolens.example.com",
        "GEOLENS_API_KEY": "your-api-key"
      }
    }
  }
}
```

## Tools

| Tool | What it does |
|---|---|
| `search_datasets` | Catalog search by free text (semantic ranking where the instance enables it). Returns dataset records as GeoJSON features. |
| `get_dataset_schema` | A dataset's columns, geometry type, CRS/SRID, feature count, and extent. |
| `get_features` | Bounded GeoJSON features for a dataset (OGC API — Features), with optional bbox. |
| `list_maps` | Saved maps (id, name, visibility, layer count). |
| `get_map` | One saved map's full metadata, including layers and view state. |

## Not yet included

A `query` tool (run SQL through GeoLens's read-only sandbox) is intentionally **not** in this release. The sandbox has no direct REST endpoint today, and exposing raw SQL over HTTP needs security hardening (cost/DoS bounds, rate limiting, mandatory dataset scope) before it's safe to point at a production instance. Tracked in [#565](https://github.com/geolens-io/geolens/issues/565).

## Develop

```bash
cd mcp
uv run --extra dev python -m pytest -v
```

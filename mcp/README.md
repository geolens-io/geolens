# geolens-mcp

Apache-2.0 read-only [Model Context Protocol](https://modelcontextprotocol.io) server for [GeoLens](https://github.com/geolens-io/geolens).

Point a coding agent (Claude Code, Cursor, Codex, …) at a GeoLens instance so it can discover datasets, inspect schemas, read features and maps, and run read-only SQL from inside a dev session. It has no write, ingest or admin tools, and every call is scoped to the caller's access.

## Install

```bash
pip install geolens-mcp        # or: uvx geolens-mcp
```

The server reads `GEOLENS_INSTANCE` and, for non-public data, `GEOLENS_API_KEY` from the environment. Client setup, the tool list and the credential rules are in the [MCP guide](https://docs.getgeolens.com/guides/sdk/mcp/).

## Develop

```bash
cd mcp
uv run --extra dev python -m pytest -v
```

<!-- mcp-name: io.github.geolens-io/geolens -->
<!-- The marker above is how the MCP Registry proves ownership of the PyPI package: it
     looks for `mcp-name: <server name>` in the published package description, which is
     this file. Keep it byte-identical to `name` in server.json, and keep it alone on its
     line — the token has to be followed by whitespace or the comment close to match. -->

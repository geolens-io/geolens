# geolens-mcp

Apache-2.0 read-only [Model Context Protocol](https://modelcontextprotocol.io) server for [GeoLens](https://github.com/geolens-io/geolens).

Point a coding agent (Claude Code, Cursor, Codex, …) at a GeoLens instance so it can discover datasets, inspect schemas, read features and maps, and run read-only SQL from inside a dev session. It has no write, ingest or admin tools, and every call is scoped to the caller's access.

## Install

```bash
pip install geolens-mcp        # or: uvx geolens-mcp
```

The server reads `GEOLENS_INSTANCE` and, for non-public data, `GEOLENS_API_KEY` from the environment. Client setup, the tool list and the credential rules are in the [MCP guide](https://docs.getgeolens.com/guides/sdk/mcp/).

## Tools

All tools are read-only and scoped to the caller's access.

- `search_datasets`, `get_dataset_schema`, `get_features`: find datasets, read their columns and page through features.
- `list_maps`, `get_map`: saved maps and their layers.
- `list_stories`, `get_story`: published stories and their chapters. Drafts are never read. Against a server that predates chapter counts, `chapter_count` is null.
- `aggregate`: exact counts, statistics, histograms, group-bys and row pages over one dataset.
- `query`: one sandboxed SELECT. Use `aggregate` for counts and summaries.

```text
list_stories(search="skyline", limit=10)
get_story(story_id="<id from list_stories>")
aggregate(dataset_id="<id>", request={"op": "group_by", "group_column": "borough", "stat": "count", "limit": 5})
```

`aggregate` keeps the route's limits. A `too_wide` refusal means the `bbox` holds over 500,000 rows, so narrow it. A `query_busy` refusal means two aggregates are already running for you, so retry after a short pause.

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

# geolens-mcp

Apache-2.0 [Model Context Protocol](https://modelcontextprotocol.io) server for [GeoLens](https://github.com/geolens-io/geolens).

Point a coding agent (Claude Code, Cursor, Codex, …) at a GeoLens instance so it can discover datasets, inspect schemas, read features and maps, and run read-only SQL from inside a dev session. With a `map_author` API key it can also create private maps and add, style and frame their layers. It has no ingest, delete, sharing or admin tools, and every call is scoped to the caller's access.

## Install

```bash
pip install geolens-mcp        # or: uvx geolens-mcp
```

The server reads `GEOLENS_INSTANCE` and, for non-public data, `GEOLENS_API_KEY` from the environment. Client setup, the tool list and the credential rules are in the [MCP guide](https://docs.getgeolens.com/guides/sdk/mcp/).

## Tools

These tools read and are scoped to the caller's access.

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

## Map authoring

These tools need a `map_author` API key in `GEOLENS_API_KEY`. Create one in Settings under API Keys with the Map author scope. The key reads what a read-only key reads, and it can change only the maps it created: it can't edit a map made in the app or by another key, delete anything, rename a map or layer, or share a map. These tools refuse to run with any other credential, including a full or publish key or `GEOLENS_TOKEN`, and say so; the read tools keep working with it.

- `create_map`: a private map with an optional description and basemap. Returns its id and app URL.
- `add_layer`: adds a dataset as a layer, with an optional style and popup fields. Each new layer is drawn beneath the layers already on the map and the key can't reorder them, so add the layer you want on top first.
- `update_layer_style`: restyles a layer or changes its popup fields.
- `set_camera`, `set_basemap`: the view the map opens at and its basemap.

A style is a single colour, a colour per value of a text, boolean or integer column, or a colour per class of a numeric column (equal interval, quantile, natural breaks, standard deviation or your own breaks). Colours come from a named ramp or a list of hex colours, and the map builder opens the layer with the same settings.

```text
create_map(name="Street trees", basemap="blank")
add_layer(map_id="<id>", dataset_id="<id>", style={"type": "categories", "column": "species"}, popup_fields=["species", "planted"])
update_layer_style(map_id="<id>", layer_id="<id>", style={"type": "classes", "column": "dbh", "method": "quantile", "colors": "Greens"})
set_camera(map_id="<id>", center=[-73.97, 40.78], zoom=13)
```

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

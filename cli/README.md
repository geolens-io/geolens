# geolens (CLI)

Apache-2.0 command-line interface for the [GeoLens](https://github.com/geolens-io/geolens) API.

Log in, scan local directories of spatial data, publish files, apply manifest-driven catalogs, replace and refresh datasets, inspect source status, run PostGIS analysis operations, export STAC metadata and plan an ArcGIS migration against any GeoLens instance.

## Install

```bash
pip install geolens-cli      # installs the `geolens` command; Python 3.11 or newer
```

## Quick start

```bash
geolens login https://geolens.example.com/api
geolens publish ./data/cities.geojson
geolens status DATASET_ID        # the UUID at the end of the URL publish printed
```

The CLI wraps the [`geolens`](https://pypi.org/project/geolens/) Python SDK package.

## Migrate from ArcGIS

Three commands move an ArcGIS Online organization or a self-hosted ArcGIS portal into GeoLens. They are written for an ArcGIS organization administrator, because a portal search only returns items shared with the caller and a non-admin never sees other people's private items. On the GeoLens side the session must be an admin (`geolens login` as one), since the run reads the user list and hands ownership to the people the plan names.

```bash
geolens arcgis inventory --portal-url https://yourorg.maps.arcgis.com --scope org -o ./run
geolens arcgis plan ./run/arcgis-inventory.json --owner-map owners.json
geolens arcgis migrate ./run/arcgis-migration-plan.json
```

1. `inventory` reads the portal and writes `arcgis-inventory.json` and a readable report.
2. `plan` turns it into `arcgis-migration-plan.json`, which you review and edit. Each item has an action (`import_layers`, `import_file`, `import_map`, `export_only` or `skip`), a target owner, visibility, collections and title. `owners.json` maps ArcGIS usernames to GeoLens usernames or emails; an empty value means no owner yet.
3. `migrate` (hidden from `--help` until the whole flow ships) runs the plan one item at a time, in dependency order. Add `--dry-run` first to check the plan and the owners without importing anything.

### What each action does

- `import_layers`: GeoLens imports the feature layers and tables of a hosted or federated service itself; the CLI never contacts the service.
- `import_file`: a CSV, GeoJSON, Shapefile or File Geodatabase item is downloaded from the portal and uploaded. It is bounded by the instance's upload size limit; an item over it is skipped with its size.
- `export_only`: items GeoLens can't host (dashboards, forms, StoryMaps, Hub pages and so on) are saved under `export/<type>/<item id>/` next to the state file, with `item.json`, the item's data, its resources and, for a story, a readable `story.md`. `export/INDEX.md` lists them with what to use instead. `--export-cap-mb` (default 200) limits each item. An export can finish with files missing: one over the cap, JSON that can't be redacted, a request the portal refused, or an unsafe resource name. The item notes, the report and `INDEX.md` (status `partial` or `complete, with errors`) say which, so check them before retiring the ArcGIS source. A network or server error while exporting leaves the item failed, and a rerun retries it.
- `import_map` is not available yet; those items stay pending.

Items are imported as you, then handed to the owner the plan names. Each target user needs a role with `upload` (datasets) or `edit_metadata` (maps); `migrate` warns when the role matrix says otherwise and the server decides on each transfer. `--unmapped-owner` names an owner for items whose mapped owner is empty or inactive. Folders become collections (`defaults.collection_from` in the plan: `folder` or `none`); ArcGIS groups are not migrated yet and are listed in the report.

### Credentials

Public items need none. For anything else pass `--token`, `ARCGIS_TOKEN` or `--token-stdin`, or `--username` with the password in `ARCGIS_PASSWORD`, `--password-stdin` or a prompt. A token made from a password is renewed before it expires. A token you pasted is not: when it runs out the run stops, writes the state file and tells you to resume with a fresh one. Accounts that sign in with SAML or OpenID Connect have no password to give here, so use a token. Tokens and passwords are never written to the state file, the report or the export folder.

A private service hosted on a federated ArcGIS Server whose host differs from the portal's (or from `arcgis.com`) only receives the token when you name its host with `--trust-service-host <host>` (repeatable); without it the item fails before any import and the error names the host to pass.

GeoLens needs `REDIS_URL` set to take a token for a private service import; without it the instance answers 503 and the run stops with that message.

### Resuming and reports

Progress is saved in `arcgis-migration-state.json` (mode 0600) after every item. Run the same command again to resume: finished items are skipped, failed ones are retried (`--no-retry` leaves them alone), and layers already imported are never imported twice. `--only <item id>` runs one item plus the unfinished items it depends on. Only one run can use a state file at a time.

A run that gets as far as the item loop writes `arcgis-migration-report.md` and `.json` next to the state file, also when it is interrupted or stops on a failed request. `--dry-run` writes none, and neither does a run refused before it starts (an unusable plan, state file or owner mapping, or a failed GeoLens check). The report covers every item of the plan: the manual follow-ups (failed items, skipped files and layers, group-only sharing, partial exports, items that can't run yet or wait on others) and the unsupported items with where each was saved.

Exit codes:

- 0: no item of the plan is failed, and no item the run selected was left waiting or unable to run. Skipped items (a file over the upload limit or with too many layers) and pending items the run did not select, such as `import_map` items that can't run yet, don't change it, so read the report's counts and follow-ups before treating the migration as complete.
- 1: an item of the plan is failed (including one this run left out with `--only` or `--no-retry`, and a network or server error once items are running), an item was left pending because its action can't run yet or it waits on another item, or the run stopped (for example on an expired pasted token).
- 2: the plan, state file, owner mapping or credentials couldn't be used, or the portal URL redirected before any item ran. A redirect refused once items are running fails that item (exit 1).
- 3: GeoLens or ArcGIS authentication failed before any item ran (the GeoLens checks, or an ArcGIS password sign-in). An authentication failure once items are running fails that item (exit 1).
- 4: the portal couldn't be reached while signing in, before any item ran.
- 5: a server error from the GeoLens checks, before any item ran.
- 130: interrupted; run the same command to resume.

For a large migration, run the GeoLens worker with `WORKER_CONCURRENCY=2` or more, since each layer import is a background job.

## Documentation

The full command reference, manifest schema, exit codes and CI setup are in the [CLI guide](https://docs.getgeolens.com/guides/cli/).

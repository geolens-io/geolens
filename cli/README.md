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
- `export_only`: items GeoLens can't host (dashboards, forms, StoryMaps, Hub pages and so on) are saved under `export/<type>/<item id>/` next to the state file, with `item.json`, the item's data, its resources and, for a story, a readable `story.md`. `export/INDEX.md` lists them, and the source files of hosted layers, with what to use instead. `--export-cap-mb` (default 200) limits each item. An export can finish with files missing: one over the cap, JSON that can't be redacted, a request the portal refused, or an unsafe resource name. The item notes, the report and `INDEX.md` (status `partial` or `complete, with errors`) say which, so check them before retiring the ArcGIS source. A network or server error while exporting leaves the item failed, and a rerun retries it.
- `import_map`: a Web Map becomes a GeoLens map through the server's web map translator. Its operational layers are matched to the datasets the run imported for their service items, so the map waits for those items (`depends_on`); a layer from another organization or a service that was not imported is left out. Basemaps follow the plan's `basemap_map`. `webmap-loss/<item id>.json` next to the state file lists what was not carried over, and the report lists the path under its loss reports and in the follow-ups. The state keeps each ArcGIS layer id's map layer id.

Items are imported as you, then handed to the owner the plan names. Each target user needs a role with `upload` (datasets) or `edit_metadata` (maps). `--unmapped-owner` names an owner for items whose plan owner can't take them yet: the mapping is empty, the user hasn't signed in to GeoLens yet (an OIDC user before first sign-in), is inactive, or has a role without that permission, such as the `viewer` role new OIDC users get. Those items go to the `--unmapped-owner` for now and are recorded as waiting; a later run hands each one to its owner once the owner can take it, or to a new `--unmapped-owner` if you pass another. For a role, the run asks you to promote the user to editor instead of letting the transfer fail. Without `--unmapped-owner` such items stop the run before anything is imported, except a role without the permission, which is a warning and the server decides. A migrated item whose plan owner you later edit to an empty value, a name that matches no user or one that matches two is listed in the output and the report, and stays with its current owner. Folders become collections (`defaults.collection_from` in the plan: `folder` or `none`).

### Sharing and groups

ArcGIS sharing maps to GeoLens visibility: `private` stays private, `org` becomes internal, `public` stays public, and an item shared only with groups becomes `restricted`, shared with a GeoLens group for each of its ArcGIS groups. Under the `restrict_public_visibility` setting, a public item whose owner isn't a GeoLens admin becomes internal instead. Each ArcGIS group's entry in the plan's `group_map` decides its GeoLens group through `geolens_group`. Left `null`, `migrate` creates a group named after the ArcGIS group (or `ArcGIS - <name>` when another group already has that name; it never joins a group it didn't create) and adds the members the inventory read. A member resolves like an owner: through `owner_map` when it lists them, otherwise by the same username or email in GeoLens. One who isn't a GeoLens user yet stays pending and is added by a later run. Set `geolens_group` to an existing group's name to share with that group instead; its members are left as they are, since adding to it would also give them the rest of what it can read. An empty string maps the ArcGIS group to no GeoLens group, and an item none of whose groups maps to one becomes private. Items keep any group they are shared with in GeoLens, and a group someone removes from an item in GeoLens isn't added again. A map is shared with its groups without widening its layers, which keep the sharing of their own items. Members who later leave the ArcGIS group aren't removed.

Only an organization administrator sees every group an item is shared with, and a group can hide its members from everyone but its managers and administrators. `plan` lists items shared only with groups that a non-admin's inventory may have missed, and the report lists, as `under_shared` follow-ups, items whose groups weren't all read or carried over.

### Credentials

Public items need none. For anything else pass `--token`, `ARCGIS_TOKEN` or `--token-stdin`, or `--username` with the password in `ARCGIS_PASSWORD`, `--password-stdin` or a prompt. A token made from a password is renewed before it expires. A token you pasted is not: when it runs out the run stops, writes the state file and tells you to resume with a fresh one. Accounts that sign in with SAML or OpenID Connect have no password to give here, so use a token. Tokens and passwords are never written to the state file, the report or the export folder.

A private service hosted on a federated ArcGIS Server whose host differs from the portal's (or from `arcgis.com`) only receives the token when you name its host with `--trust-service-host <host>` (repeatable); without it the item fails before any import and the error names the host to pass.

GeoLens needs `REDIS_URL` set to take a token for a private service import; without it the instance answers 503 and the run stops with that message.

### Updating the plan

Run `plan` again on a newer inventory to bring an existing plan up to date. The plan records the defaults it gave each item, so the merge can tell your edits apart: a value you edited stays, and one you left alone takes the new default. When both changed, your value stays and `plan` prints what the inventory now gives. An edit stays an edit until you set it back to its default, even when the portal later changes to match it. New portal items are added at the end with defaults; the rest keep your order. An item gone from the portal stays in the plan with `"removed": true`; `migrate` doesn't run it again, and what it already migrated stays in GeoLens. Only a complete `--scope org` inventory read by an organization administrator marks items removed, since anyone else misses items not shared with them. Any other inventory (partial, truncated, user scope, anonymous, a non-admin account, or one written before the CLI recorded the account's role) marks the items it doesn't list `"unlisted": true`, and `migrate` leaves those pending, so the run exits 1 until a merge lists them again. If you never run a complete org inventory as an admin, an item deleted from the portal stays unlisted; set its action to `skip`, or delete it from the plan, to finish. A non-admin also may not see every group an item is shared with, so its inventory only adds groups to an item's `groups`; a group it doesn't list is kept until an admin's inventory leaves it out. `plan` and `migrate` refuse an inventory of another ArcGIS organization than the plan's, which matters on `www.arcgis.com`, where every organization shares one URL; a plan from an earlier version records no organization, so only its portal URL is checked. Your `owner_map`, `group_map`, `basemap_map` and plan `defaults` entries win over the inventory and `--owner-map`. To leave an item out, set its action to `skip`: an item deleted from the plan comes back with defaults on the next merge. `--force` replaces the plan with fresh defaults instead.

Plans written by earlier versions still migrate. They record no defaults and no inventory scope, so their items keep every value as an edit on every merge, `depends_on` included. Delete an item from the plan, or use `--force`, to give it defaults that follow the portal.

### Resuming and reports

Progress is saved in `arcgis-migration-state.json` (mode 0600) after every item. Run the same command again to resume: failed items are retried (`--no-retry` leaves them alone), and layers already imported are never imported twice. `--only <item id>` runs one item plus the unfinished items it depends on. Only one run can use a state file at a time.

A rerun first hands waiting items to their owners, then imports what isn't finished, then brings every item migrated before up to date. Each dataset of a service item is refreshed from its source with the run's ArcGIS credential, so private items need `--token` or `--username` on every rerun. A data file item is downloaded again and replaces its datasets. An `export_only` item is exported again when the portal changed it since its bundle was written, which the new bundle replaces in one step; if that export fails, the earlier bundle stays and the item is reported as not up to date. A service item is probed even when it had nothing to import, so a layer added since is reported. A migrated web map is not translated again: one whose portal item changed since its import is reported as not up to date, so you can update the GeoLens map by hand. The item's metadata is written again on each dataset that a refresh or replacement published, and a field the portal has emptied since is emptied too, unless it was edited in GeoLens. A visibility the portal's sharing changed since the import is applied to each dataset, unless it was changed in GeoLens or the state file can't tell, which is reported instead. Every service item is refreshed, because an item's `modified` date doesn't move when its features are edited. A refresh that stops for review (live edits, a destructive schema change, an empty result) publishes nothing: the run reports it with the `geolens refresh <dataset> --accept-blocked-run <run>` command that accepts it, and never accepts it for you. A rerun recognises the run you accept it with, and a refresh GeoLens accepted but whose answer was lost, as this command's own. A migrated web map whose owner was changed in GeoLens is reported, and one waiting for its planned owner is not handed over after such a change. `--only` limits the rerun to the items it names.

A rerun never overwrites a change made in GeoLens. After each write the state file records the dataset's last update, feature count and data revision, which counts every feature and column edit, your own included. Each dataset is compared right before its own refresh or replacement; one whose values differ (edited, re-shared, transferred or refreshed in GeoLens) is reported and left alone, and so is one deleted there. The request carries the recorded revision, so GeoLens stops the publication for review if the data is edited after the check, and a file replacement is checked again after its upload. A GeoLens too old to report data revisions gets no refresh or replacement at all; each dataset is reported until you upgrade it. A refresh that doesn't publish leaves the dataset's record as it was, and one edited while its refresh ran is reported and not recorded. Set the item's action to `skip` to stop bringing it up to date. A state file from an earlier version has no recorded values, so a dataset is taken as unchanged only when your GeoLens account made its last change, before the item finished. The state file is now version 2, which an earlier CLI refuses to read rather than rewrite.

A run that gets as far as the item loop writes `arcgis-migration-report.md` and `.json` next to the state file, also when it is interrupted or stops on a failed request. `--dry-run` writes none, and neither does a run refused before it starts (an unusable plan, state file or owner mapping, or a failed GeoLens check). The report covers every item of the plan: the manual follow-ups (failed items, skipped files and layers, group-only sharing, partial exports, items that can't run yet or wait on others) and the unsupported items with where each was saved.

Exit codes:

- 0: no item of the plan is failed, and no item the run selected was left waiting or unable to run. Skipped items (a file over the upload limit or with too many layers) and pending items the run did not select, such as items that can't run yet, don't change it, so read the report's counts and follow-ups before treating the migration as complete.
- 1: an item of the plan is failed (including one this run left out with `--only` or `--no-retry`, and a portal download or GeoLens server error once items are running), an item the run selected was left pending because its action can't run yet or it waits on another item, a migrated item couldn't be brought up to date or handed to its owner, `--cutover` refused, or the run stopped (for example on an expired pasted token).
- 2: the plan, state file, owner mapping or credentials couldn't be used, or the portal URL redirected before any item ran. A redirect refused once items are running fails that item (exit 1).
- 3: authentication failed before any item ran (the GeoLens checks, or an ArcGIS password sign-in), or the server rejected a `GEOLENS_TOKEN` at any point, which stops the run with this code. A stored login that is rejected once items are running fails that item (exit 1).
- 4: the portal couldn't be reached while signing in, or a GeoLens request couldn't connect or timed out at any point, which stops the run with this code. The exception is a timeout on the status poll of an import job: it is retried until the poll's deadline, and a deadline that runs out fails that item (exit 1). A portal download that fails once items are running also fails only that item (exit 1).
- 5: a server error from the GeoLens checks, before any item ran.
- 130: interrupted; run the same command to resume.

For a large migration, run the GeoLens worker with `WORKER_CONCURRENCY=2` or more, since each layer import and refresh is a background job.

### Cutover

A migration ends with one last run after the portal stops changing, marked with `--cutover`:

1. Tell the portal's users that it is frozen, and stop edits to its items and services.
2. Run `inventory --scope org` again as an organization administrator, then `plan` on it, so the plan holds everything the portal has now.
3. Run `migrate --dry-run --cutover` to see what the cutover would refuse, and fix what you can: retry failed items, map owners, promote owners to editor, accept or fix refreshes that stopped for review.
4. Run `migrate --cutover` with the same credentials as before. It runs like any rerun, then checks what wouldn't carry over and marks the run as the final one only when nothing is left, or when you accept each loss:
   - `--accept-unfinished-items`: a plan item isn't done (failed, skipped, can't run yet or waits on another item), is unlisted (even a finished one, since a rerun doesn't bring it up to date) or isn't up to date (its refresh failed or stopped for review, or GeoLens changed it). Items set to `skip` and items gone from the portal don't count.
   - `--accept-incomplete-inventory`: the plan wasn't last merged from a complete `--scope org` inventory read by an organization administrator, or the portal has items of the organization changed since that inventory started reading it, by the portal's own clock, so the plan may miss or misstate them. An inventory written by an earlier version, or by a portal that sent no time, records no start and fails this check; run it again. The run asks the portal with its ArcGIS credential, which must be an organization administrator's; without one, or when the portal can't answer, this check fails too.
   - `--accept-attachment-loss`: a migrated layer has attachments, or its service doesn't say. GeoLens doesn't import attachments yet.
   - `--accept-unresolved-users`: an item still waits for its owner, its plan owner doesn't name one GeoLens user, or its plan now names another owner than the one it was given; or a member of an ArcGIS group isn't in its GeoLens group yet.
   - `--accept-under-sharing`: an item shared only with ArcGIS groups may reach fewer people in GeoLens: the inventory wasn't read by an organization administrator, one of its groups maps to no GeoLens group, or a group's members couldn't be read.
5. Read `arcgis-migration-report.md`, which records the cutover and the losses you accepted, and keep it with the state file. Then retire the portal. A refresh after that fails with the service's error, and the datasets stay as they are.

A refused cutover exits 1 and leaves the run unmarked; nothing it imported or refreshed is undone. `--cutover` runs the whole plan, so it can't be combined with `--only`.

## Documentation

The full command reference, manifest schema, exit codes and CI setup are in the [CLI guide](https://docs.getgeolens.com/guides/cli/).

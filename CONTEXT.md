# GeoLens

GeoLens catalogs geospatial datasets and lets people compose maps from them.

## Language

**Uploaded source**: The file supplied for a dataset import or replacement, including copies made while preparing it. Its retention depends on outstanding import, retry and archival needs.
_Avoid_: Dataset asset, when referring to input awaiting disposal.

**Upload batch**: A group of uploaded files reviewed together before their imports are committed. A file with multiple layers can produce several imported datasets.

**Point cloud**: A dataset of individually positioned points, each carrying its own attributes such as classification, intensity or colour. It may come from LiDAR, photogrammetry or any other capture method.
_Avoid_: LiDAR dataset, COPC dataset.

**3D tileset**: A dataset published as a hierarchy of 3D content tiles, such as photogrammetry meshes or building models, following OGC 3D Tiles.
_Avoid_: 3D Tiles dataset, mesh.

**Saved layer**: A dataset's configured place in a saved map, including its style, visibility and drawing order. A point cloud or 3D tileset in a map is a saved layer like any other.

**Companion drawing**: A label, arrow or extrusion associated with a saved layer. It belongs to that layer's presentation rather than representing another saved layer.

**Dashboard**: A panel of widgets saved with a map, shown beside or below it. It follows the map's sharing and has no access of its own; a reader sees the widgets on the layers they can read.

**Widget**: One summary in a dashboard of a single saved layer, such as an indicator, a bar chart, a histogram or a category selector. It applies the layer's saved filter, or says when it can't.
_Avoid_: Chart, when the widget is a number.

**Pick**: A reader's choice of a bar, a histogram bin or selector values in a dashboard. It filters that layer on the map and its other widgets for the session, never the widget it came from, and is never saved.

**View scope**: A widget's choice to cover only the features in the current map view rather than the whole layer. A layer with no geometry is always covered whole.

**Source binding**: The system-managed record of where a dataset's current data came from and how to reach it again: the origin, the pointer and the details a refresh needs. It changes only when an import, replacement, refresh or restore publishes new data, and it never holds a credential.
_Avoid_: Origin (the derived kind alone), source URL (owner-editable text), `origin_ref`.

**Origin**: How a dataset's data entered the catalog: an upload, a registered table, a service, a STAC item, or drawing in the app. Derived from the source binding, never stored.

**Service import**: Bringing one remote service layer into GeoLens as a dataset that is a managed copy of it.
_Avoid_: ArcGIS import, when referring to a single layer.

**ArcGIS migration**: Moving an ArcGIS organization's or one user's content into GeoLens item by item, as a migration plan directs.
_Avoid_: Migration on its own (that is a database schema migration), AGOL import, ArcGIS exit.

**Portal**: The ArcGIS Online organization or self-hosted ArcGIS portal an ArcGIS migration reads from.

**Loss report**: The list of items and properties an ArcGIS migration did not carry over, each with its reason.

**Migration plan**: The operator-editable list of a portal's items that says what an ArcGIS migration does with each one and who owns the result.

**Cutover**: The final run of an ArcGIS migration, made after edits in the portal are frozen. After it GeoLens is the system of record for the migrated content.

**Role**: A user's permission tier (admin, editor or viewer). It decides what a user may do; it is not an audience that content is shared with.
_Avoid_: Group, when meaning an audience.

**Group**: A named set of users that datasets, maps and stories can be shared with. Admins manage groups and their members.
_Avoid_: Team, role, layer group (layers grouped inside a map).

**Restricted**: The visibility of a dataset, map or story that only its owner, admins and members of the groups it is shared with can see. A dataset can be restricted with no group left, which leaves only its owner and admins; a map or story left with no group becomes private.

**Story**: An ordered list of chapters told over saved maps. It has its own owner and visibility, and it can't be published more widely than any map it uses can be read.

**Chapter**: One step of a story: a title, blocks of text and an optional scene.

**Scene**: What the map shows for a chapter: a saved map, its camera and which of its saved layers are visible. A chapter without a scene keeps the one before it; chapters before the first scene show that first scene.
_Avoid_: Slide, view (a map's own saved camera).

**Draft**: The version of a story its owner edits. A save replaces the whole draft; readers don't see it until it's published.

**Publish**: Copying a story's draft to its published version, once every map its scenes use reaches the story's audience.

**Published version**: The copy of a story that readers see. It changes only when a draft is published.

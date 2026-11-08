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

**Dashboard**: A panel of widgets saved with a map, shown beside or below it, or on its own with the map hidden. It follows the map's sharing and has no access of its own; a reader sees the widgets on the layers they can read, and every text widget.

**Widget**: One item in a dashboard: a summary of a single saved layer, such as an indicator, a bar chart, a histogram or a category selector, or a block of Markdown text that reads no layer. A layer's widget applies the layer's saved filter, or says when it can't.
_Avoid_: Chart, when the widget is a number.

**Pick**: A reader's choice of a bar, a histogram bin or selector values in a dashboard. It filters that layer on the map and its other widgets for the session, never the widget it came from, and is never saved.
_Avoid_: Selection.

**View scope**: A widget's choice to cover only the features in the current map view rather than the whole layer. A layer with no geometry is always covered whole.

**Reference**: A value an author gives an indicator to compare with, named by its label. The difference shows as an amount, a percentage or both, and is judged by whether a higher value is better.

**Map data**: A reader's panel of a map's data, docked under the map; on a phone it expands to full screen. It shows a layer's attribute table or a list of the features in view.
_Avoid_: Data tab, data drawer.

**Attribute table**: A saved layer's rows as a table. It starts with the fields the layer's popup shows, and the reader can add or hide columns.

**Value label**: The name a dataset gives a stored value in a column, such as a coded-value domain's description of a code. Readers see the label; filters and picks match the stored value.

**Column allowlist**: The columns of a dataset that anyone reaching it only through an embed may see. Map tiles carry no others; row lists keep the row id.
_Avoid_: Tile columns.

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

**Chapter**: One step of a story: a title, its blocks and an optional scene.

**Block**: One piece of a chapter's content: text, an image, a gallery, a carousel, a video, a framed page, a button or a separator.
_Avoid_: Widget, which is a dashboard's summary.

**Scene**: What the map shows for a chapter: a saved map, its camera and which of its saved layers are visible. A scene never changes how a layer looks; a chapter that needs a different look shows another layer of the same map. A chapter without a scene keeps the one before it; chapters before the first scene show that first scene. A story with no scene shows its chapters without a map.
_Avoid_: Slide, view (a map's own saved camera).

**Reader settings**: A story's choices for how readers see it: whether the chapter list shows above the story, the layout, the panel position, the theme and the default transition.

**Layout**: Where a story's chapter text sits: a side panel next to the map, or a floating panel over a full-screen map. Phones put the map above the text.

**Panel position**: Which part of the map a floating panel covers: left, right or centre.

**Transition**: How the map moves into a chapter's scene: Fly, Glide or Cut. A chapter without its own transition uses the story's default. Layers the scene turns on or off fade, and a scene on another saved map fades in over the one before it. A reader who prefers reduced motion always gets a cut.
_Avoid_: Animation, camera move.

**Draft**: The version of a story its owner edits. A save replaces the whole draft; readers don't see it until it's published.

**Publish**: Copying a story's draft to its published version, once every map its scenes use reaches the story's audience.

**Published version**: The copy of a story that readers see. It changes only when a draft is published.

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

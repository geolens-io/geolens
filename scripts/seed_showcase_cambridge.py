"""The City of Cambridge, Massachusetts section of the showcase seed.

Five layers are bound to the city's public ArcGIS Online hosted feature layers,
one parcels file is uploaded at a pinned release, and two parcel datasets are
computed from them. A collection, two maps, an imported web map and two
dashboards sit on top. Everything is "built from the City of Cambridge's open
data": no title or description says the city uses or endorses GeoLens.

The builders take the seeder module (or any object that carries the names in
``SEEDER_HELPERS``) as their first argument, so this file imports nothing from
``seed-showcase.py``. Every builder finds its content by title or name and
updates it in place on a rerun. None deletes anything, and ``force`` is ignored
for that reason: ``--force`` does not rebuild the parcels upload, the derived
parcel datasets or the imported map. Delete them first to rebuild.
"""

import hashlib
import json
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

# What the builders read off the seeder; main() copies these into a namespace.
SEEDER_HELPERS = (
    "convert_to_service",
    "ingest_service",
    "fetch",
    "_get_or_analyze",
    "_get_or_ingest",
    "_dashboard_widget",
    "_seed_id",
    "warn_if_hidden_layers",
    "refresh_and_report",
    "refresh_quakes",
    "_story_scene",
    "_story_blocks_chapter",
    "_story_block",
)

# --- sources ------------------------------------------------------------------

ARCGIS_ROOT = "https://services1.arcgis.com/WnzC35krSYGuYov4/arcgis/rest/services"
PARCELS_URL = (
    "https://raw.githubusercontent.com/cambridgegis/cambridgegis_data/"
    "f5d7cc60fe95d6c80761d36fb047a1393eb17bb0/Assessing/FY2027/FY2027_Parcels/"
    "ASSESSING_ParcelsFY2027.geojson"
)
PARCELS_SOURCE_PAGE = (
    "https://github.com/cambridgegis/cambridgegis_data/tree/"
    "f5d7cc60fe95d6c80761d36fb047a1393eb17bb0/Assessing/FY2027/FY2027_Parcels"
)
PARCELS_SHA256 = "b3e6f852abbb5bfdecd0105ca1bb765206c22ecfa0cfac1fc1f97fe4a339f75c"
# Editor usernames in the city's file; the upload leaves them out.
PARCELS_DROPPED_COLUMNS = ("Editor", "last_edited_user", "created_user")
WEBMAP_PATH = Path(__file__).resolve().parent / "cambridge_trees_webmap.json"
ESRI_STREETS_URL = (
    "https://services.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer"
)

TREES_TITLE = "Cambridge Street Trees"
NEIGHBORHOODS_TITLE = "Cambridge Neighborhoods"
ZONING_TITLE = "Cambridge Zoning Districts"
FLOOD_TITLE = "Cambridge FEMA 1% Annual-Chance Floodplain"
ADDRESSES_TITLE = "Cambridge Address Points"
PARCELS_TITLE = "Cambridge Parcels FY2027"
PARCELS_ZONED_TITLE = "Cambridge Parcels with Zoning"
PARCELS_FLOOD_TITLE = "Cambridge Parcels in the 1% Floodplain"

# (dataset title, hosted feature layer name)
BINDINGS = (
    (TREES_TITLE, "Trees"),
    (NEIGHBORHOODS_TITLE, "CDD_Neighborhoods"),
    (ZONING_TITLE, "Zoning_Districts"),
    (FLOOD_TITLE, "FEMA_FloodPlains100Year"),
    (ADDRESSES_TITLE, "Address_Points"),
)
# The bindings in refresh order: the trees last, so they are the newest card on
# the catalog home after a sweep.
SERVICE_TITLES = tuple(
    sorted((title for title, _ in BINDINGS), key=lambda title: title == TREES_TITLE)
)
DATASET_TITLES = frozenset(
    [title for title, _ in BINDINGS]
    + [PARCELS_TITLE, PARCELS_ZONED_TITLE, PARCELS_FLOOD_TITLE]
)

COLLECTION_NAME = "Cambridge, MA: a city's open data"
TREES_MAP = "Cambridge open data: street trees, from an ArcGIS Online web map"
PARCELS_MAP = "Cambridge open data: parcels, zoning and the floodplain"
TREE_DASHBOARD = "Cambridge open data: street tree operations"
LAND_DASHBOARD = "Cambridge open data: land and zoning in numbers"
MAP_NAMES = frozenset({TREES_MAP, PARCELS_MAP, TREE_DASHBOARD, LAND_DASHBOARD})

# Stored column names are the service's field names lower-cased.
TREE_CODED_COLUMNS = frozenset(
    {
        "overheadwires",
        "memtree",
        "ownership",
        "adacompliant",
        "treegrateactionreq",
        "bareroot",
        "treewellcover",
        "structuralsoil",
        "abutsopenarea",
        "exposedrootflare",
        "locationretired",
        "sitereplanted",
        "biochar_added",
        "pb",
    }
)
# Editor usernames the city's layers carry. Popups and visible_fields never list them.
STAFF_COLUMNS = frozenset(
    {"creator", "inspectr", "created_user", "last_edited_user", "lasteditor", "editor"}
)

CITY_NOTE = (
    "Built from the City of Cambridge's open data (Open Data Commons PDDL 1.0). "
    "The City of Cambridge does not use or endorse GeoLens."
)
ONE_LICENSE = "Open Data Commons PDDL 1.0"
ONE_ATTRIBUTION = "City of Cambridge, MA open data (PDDL 1.0)"
ONE_ORG = "City of Cambridge, MA"
_BINDING_NOTE = (
    "a copy that GeoLens re-pulls from the city's ArcGIS Online organization "
    "on refresh, so it can lag the city's own"
)
# The text a dataset carries before its binding completes; it claims nothing.
STUB_SUMMARY = (
    "City of Cambridge open data; the binding to the city's ArcGIS Online "
    "layer has not completed."
)


def _source(service: str) -> str:
    return f"{ARCGIS_ROOT}/{service}/FeatureServer/0"


# Per dataset: the fields the catalog page, the DCAT export and the quality
# score read. ``requires_origin`` holds a binding's text back until the dataset
# observably reads from its service.
CAMBRIDGE_METADATA: dict[str, dict] = {
    TREES_TITLE: {
        "summary": (
            "Street trees, planting sites and removed trees in the City of "
            "Cambridge, Massachusetts, with species, trunk diameter, plant "
            "date, site type and neighborhood. This is the city's public "
            f"Trees layer on ArcGIS Online, {_BINDING_NOTE}. Plant dates and "
            "diameters are as the city recorded them, and recent years can "
            "be incomplete."
        ),
        "source_url": _source("Trees"),
        "update_frequency": "continual",
        "keywords": ["trees", "urban forestry", "street trees", "cambridge"],
        "theme_category": ["environment", "biota"],
        "requires_origin": "service",
    },
    NEIGHBORHOODS_TITLE: {
        "summary": (
            "The thirteen neighborhoods of the City of Cambridge, "
            "Massachusetts, as the city's Community Development Department "
            "draws them. This is the city's public CDD Neighborhoods layer "
            f"on ArcGIS Online, {_BINDING_NOTE}."
        ),
        "source_url": _source("CDD_Neighborhoods"),
        "update_frequency": "asNeeded",
        "keywords": ["neighborhoods", "boundaries", "cambridge"],
        "theme_category": ["boundaries"],
        "requires_origin": "service",
    },
    ZONING_TITLE: {
        "summary": (
            "Zoning districts of the City of Cambridge, Massachusetts, with "
            "the district code in the zone type column. This is the city's "
            f"public Zoning Districts layer on ArcGIS Online, {_BINDING_NOTE}. "
            "It is not the official zoning map."
        ),
        "source_url": _source("Zoning_Districts"),
        "update_frequency": "asNeeded",
        "keywords": ["zoning", "land use", "planning", "cambridge"],
        "theme_category": ["planningCadastre", "boundaries"],
        "requires_origin": "service",
    },
    FLOOD_TITLE: {
        "summary": (
            "The area FEMA maps as having a 1 percent chance of flooding in "
            "any year, clipped to the City of Cambridge, Massachusetts by the "
            "city from FEMA's National Flood Hazard Layer. This is the "
            "city's public FEMA 1% floodplain layer on ArcGIS Online, "
            f"{_BINDING_NOTE}. It is a screening layer, not a flood "
            "insurance determination."
        ),
        "source_url": _source("FEMA_FloodPlains100Year"),
        "update_frequency": "asNeeded",
        "keywords": ["flood", "floodplain", "fema", "cambridge"],
        "theme_category": ["environment", "inlandWaters"],
        "requires_origin": "service",
    },
    ADDRESSES_TITLE: {
        "summary": (
            "Address points of the City of Cambridge, Massachusetts, with "
            "the full address and map-lot number of each point. This is the "
            f"city's public Address Points layer on ArcGIS Online, {_BINDING_NOTE}."
        ),
        "source_url": _source("Address_Points"),
        "update_frequency": "continual",
        "keywords": ["addresses", "geocoding", "cambridge"],
        "theme_category": ["location", "planningCadastre"],
        "requires_origin": "service",
    },
    PARCELS_TITLE: {
        "summary": (
            "Land parcels of the City of Cambridge, Massachusetts from the "
            "city's FY2027 assessing release: 12,920 polygons with map and "
            "lot numbers. An upload of the file pinned in the city's public "
            "GitHub data repository, not a live service. The file's editor "
            "username columns were left out."
        ),
        "source_url": PARCELS_SOURCE_PAGE,
        "update_frequency": "annually",
        "usage_constraints": "For planning purposes only.",
        "keywords": ["parcels", "assessing", "cadastre", "cambridge"],
        "theme_category": ["planningCadastre"],
    },
    PARCELS_ZONED_TITLE: {
        "summary": (
            "Every parcel in the City of Cambridge's FY2027 assessing release "
            "with the zoning district it meets, from the city's zoning "
            "districts layer. Computed in GeoLens with a spatial join. A "
            "parcel that touches more than one district takes the one listed "
            "first in the city's layer, so about one parcel in eight can show "
            "a neighboring district. Use the city's zoning map for anything "
            "official."
        ),
        "source_url": PARCELS_SOURCE_PAGE,
        "update_frequency": "annually",
        "usage_constraints": "For planning purposes only.",
        "keywords": ["parcels", "zoning", "spatial join", "cambridge"],
        "theme_category": ["planningCadastre"],
    },
    PARCELS_FLOOD_TITLE: {
        "summary": (
            "The parcels of the City of Cambridge's FY2027 assessing release "
            "that touch the 1 percent annual-chance floodplain, with the "
            "zoning district of each. Computed in GeoLens by selecting the "
            "zoned parcels that intersect the city's FEMA floodplain layer. "
            "A parcel counts if any part of it meets the floodplain. This is "
            "a screening layer, not a flood insurance determination."
        ),
        "source_url": PARCELS_SOURCE_PAGE,
        "update_frequency": "annually",
        "usage_constraints": "For planning purposes only.",
        "keywords": ["parcels", "flood", "floodplain", "cambridge"],
        "theme_category": ["planningCadastre", "environment"],
    },
}
for title, _spec in CAMBRIDGE_METADATA.items():
    _spec.setdefault("license", ONE_LICENSE)
    _spec.setdefault("attribution", ONE_ATTRIBUTION)
    if title not in (PARCELS_ZONED_TITLE, PARCELS_FLOOD_TITLE):
        # The derived datasets are computed in GeoLens; the city is not their publisher.
        _spec.setdefault("source_organization", ONE_ORG)
_PATCH_FIELDS = (
    "summary",
    "license",
    "attribution",
    "source_organization",
    "source_url",
    "update_frequency",
    "usage_constraints",
    "theme_category",
)

_LAYER_NAMES = {
    TREES_TITLE: "street trees",
    NEIGHBORHOODS_TITLE: "neighborhoods",
    ZONING_TITLE: "zoning districts",
    FLOOD_TITLE: "the FEMA 1% annual-chance floodplain",
    ADDRESSES_TITLE: "address points",
}


def _human(items: list[str]) -> str:
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]


def collection_description(titles) -> str:
    """The collection's text, claiming only the datasets in ``titles``."""
    have = set(titles)
    parts = [
        "A city's open data in GeoLens, from the City of Cambridge, Massachusetts."
    ]
    layers = [name for title, name in _LAYER_NAMES.items() if title in have]
    if layers:
        parts.append(
            f"Bound to the city's public ArcGIS Online hosted feature layers, "
            f"which GeoLens re-pulls on refresh: {_human(layers)}."
        )
    if PARCELS_TITLE in have:
        parts.append("The parcels are an upload pinned to the city's FY2027 release.")
    derived = [t for t in (PARCELS_ZONED_TITLE, PARCELS_FLOOD_TITLE) if t in have]
    if derived:
        parts.append(
            "Two parcel datasets were computed from them in GeoLens."
            if len(derived) == 2
            else "A parcel dataset was computed from them in GeoLens."
        )
    parts.append(
        "The City of Cambridge publishes this data under the Open Data Commons "
        "PDDL 1.0 and does not use or endorse GeoLens."
    )
    return " ".join(parts)


COLLECTION_DESCRIPTION = collection_description(DATASET_TITLES)

# Readable column titles for what the widgets and popups show.
CAMBRIDGE_ATTRIBUTE_TITLES: dict[str, dict[str, str]] = {
    TREES_TITLE: {
        "sitetype": "Site type",
        "plantdate": "Planted",
        "diameter": "Trunk diameter",
        "neighborhood": "Neighborhood",
        "commonname": "Common name",
        "scientificname": "Scientific name",
        "streetname": "Street",
        "ownership": "Ownership",
        "overheadwires": "Overhead wires",
        "plantingseason": "Planting season",
    },
    PARCELS_ZONED_TITLE: {
        "ml": "Map-lot",
        "join_zone_type": "Zoning district",
        "shape_area": "Parcel area (sq ft)",
    },
    PARCELS_FLOOD_TITLE: {
        "ml": "Map-lot",
        "join_zone_type": "Zoning district",
        "shape_area": "Parcel area (sq ft)",
    },
    ADDRESSES_TITLE: {"full_addr": "Address", "ml": "Map-lot"},
    ZONING_TITLE: {"zone_type": "Zoning district"},
    NEIGHBORHOODS_TITLE: {"name": "Neighborhood"},
}

# --- data ---------------------------------------------------------------------


def parcels_bytes(s) -> bytes:
    """The pinned parcels file, without the editor username columns.

    The download is checked against PARCELS_SHA256 before anything is changed,
    so a moved or edited upstream file stops the seed rather than loading.
    """
    raw = s.fetch(PARCELS_URL)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != PARCELS_SHA256:
        raise RuntimeError(
            f"the Cambridge parcels file changed: sha256 {digest}, expected "
            f"{PARCELS_SHA256}"
        )
    collection = json.loads(raw)
    for feature in collection["features"]:
        for name in PARCELS_DROPPED_COLUMNS:
            feature["properties"].pop(name, None)
    return json.dumps(collection, separators=(",", ":")).encode()


def _require_columns(api, dataset_id: str, title: str, names) -> None:
    """Refuse a style or widget on a column the dataset does not have.

    A service can rename a field under a map, and a widget on a missing column
    saves without complaint and then shows nothing.
    """
    have = api.dataset_columns(dataset_id)
    missing = sorted(set(names) - have)
    if missing:
        raise RuntimeError(f"{title!r} has no column {', '.join(missing)}")


def _require_uncoded(api, dataset_id: str, title: str, names) -> None:
    """Dashboard widgets print stored values, so a coded-domain column is refused."""
    labelled = {
        a["field_name"] for a in api.attributes(dataset_id) if a.get("value_labels")
    }
    coded = sorted((labelled | TREE_CODED_COLUMNS) & set(names))
    if coded:
        raise RuntimeError(
            f"{title!r}: {', '.join(coded)} carries coded values and cannot "
            "back a dashboard widget"
        )


# --- catalog ------------------------------------------------------------------


STUB_FILENAME = "service_stub.geojson"
_SERVICE_BY_TITLE = dict(BINDINGS)


def _normalized(uri: str | None) -> str:
    if not uri:
        return ""
    parts = urlsplit(uri.strip())
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            parts.query,
            "",
        )
    )


def foreign_reason(detail: dict, title: str) -> str | None:
    """Why the dataset is not the one this seeder builds under ``title``, else None.

    A binding must read the city's own layer, or still be the seeder's stub; the
    parcels must be an upload and the derived datasets computed ones.
    """
    origin = detail.get("origin")
    service = _SERVICE_BY_TITLE.get(title)
    if service is not None:
        if origin == "service":
            uri = detail.get("origin_uri")
            if _normalized(uri) == _normalized(_source(service)):
                return None
            return f"is bound to {uri!r}, not the city's layer"
        if origin == "upload" and detail.get("source_filename") == STUB_FILENAME:
            return None
        return f"is a {origin} dataset, not a binding"
    expected = "upload" if title == PARCELS_TITLE else "postgis"
    return (
        None if origin == expected else f"is a {origin} dataset, not a {expected} one"
    )


def _is_ours(api, dataset_id: str, title: str) -> bool:
    """False, with a line on stderr, for a same-titled dataset that is not ours."""
    reason = foreign_reason(api.get_dataset(dataset_id), title)
    if reason:
        print(f"  ! {title!r} {reason}; left alone", file=sys.stderr)
    return reason is None


def _withdraw_stub(api, title: str) -> None:
    """Take a half-bound dataset off the public catalog and neutralize its text.

    The seeder's stub is committed public with a USGS summary, which must not
    outlive a failed binding of a city layer. A stub left by an earlier run is
    found by title. One that did reach its service is left as it is.
    """
    stub = api.created.get(title) or api.datasets_by_title().get(title)
    if stub and api.get_dataset(stub).get("origin") != "service":
        api.patch_dataset(stub, visibility="private", summary=STUB_SUMMARY)


def _bind(s, api, by_title: dict, title: str, service: str) -> str:
    url = _source(service)
    dataset_id = by_title.get(title)
    try:
        if dataset_id is None:
            dataset_id = s.ingest_service(api, url, title)
            by_title[title] = dataset_id
        else:
            s.convert_to_service(api, dataset_id, url, title)
    except (httpx.HTTPError, RuntimeError, TimeoutError):
        _withdraw_stub(api, title)
        raise
    return dataset_id


def _apply_metadata(api, dataset_id: str, title: str) -> bool:
    """Write the title's metadata when the dataset's own text differs.

    Returns False and writes nothing for a binding that does not read from its
    service yet, because its text asserts the binding.
    """
    spec = CAMBRIDGE_METADATA[title]
    current = api.get_dataset(dataset_id)
    required = spec.get("requires_origin")
    if required and current.get("origin") != required:
        print(
            f"  (holding the text for {title!r}: origin is {current.get('origin')!r})"
        )
        return False
    fields = {
        k: spec[k] for k in _PATCH_FIELDS if k in spec and current.get(k) != spec[k]
    }
    if current.get("visibility") != "public":
        fields["visibility"] = "public"
    if fields:
        api.patch_dataset(dataset_id, **fields)
    record_id = current["record_id"]
    # The server stores keywords lower-cased.
    have = {k.lower() for k in api.existing_keywords(record_id)}
    for keyword in spec.get("keywords", ()):
        if keyword.lower() not in have:
            api.add_keyword(record_id, keyword)
    return True


def _set_attribute_titles(api, dataset_id: str, titles: dict[str, str]) -> None:
    for attr in api.attributes(dataset_id):
        wanted = titles.get(attr["field_name"])
        if wanted is not None and attr["title"] != wanted:
            api.set_attribute_title(dataset_id, attr["id"], wanted)


def enrich_existing(api) -> list[str]:
    """Apply the metadata table to every Cambridge dataset this account owns.

    Called from the seeder's global metadata pass, so a rerun or an unrelated
    ``--only`` run repairs a dataset an earlier run left with the stub text.
    Each dataset is isolated; returns the titles that could not be written.
    """
    failed: list[str] = []
    for dataset in api.list_own_datasets():
        title = dataset["title"]
        if title not in CAMBRIDGE_METADATA:
            continue
        try:
            if not _is_ours(api, dataset["id"], title):
                continue
            if _apply_metadata(api, dataset["id"], title):
                _set_attribute_titles(
                    api, dataset["id"], CAMBRIDGE_ATTRIBUTE_TITLES.get(title, {})
                )
        except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
            print(f"  WARNING: metadata enrich failed for {title!r}: {e}")
            failed.append(title)
    return failed


def _ensure_collection(api, ids: dict[str, str]) -> str:
    """Create or update the collection, describing only the datasets that exist."""
    description = collection_description(ids)
    member_ids = list(ids.values())
    existing = {c["name"]: c for c in api.list_collections()}
    current = existing.get(COLLECTION_NAME)
    if current is None:
        collection_id = api.create_collection(COLLECTION_NAME, description)
    else:
        collection_id = current["id"]
        if current.get("description") != description:
            api.update_collection(collection_id, description=description)
    missing = [
        dataset_id
        for dataset_id in member_ids
        if collection_id
        not in {c["id"] for c in api.get_dataset(dataset_id).get("collections") or []}
    ]
    if missing:
        api.add_to_collection(collection_id, missing)
    return collection_id


def build_catalog(s, api, force: bool = False, force_pinned: bool = False) -> str:
    """Bind the five city layers, upload the parcels and compute the parcel datasets.

    The zoning join and the floodplain selection are separate datasets: a second
    spatial join over a spatial-join result is refused because both would write
    a join_count column. Returns the collection id.
    """
    print("\n[cambridge-catalog] the City of Cambridge's open data")
    by_title = api.datasets_by_title()
    for title in sorted(DATASET_TITLES & set(by_title)):
        if not _is_ours(api, by_title[title], title):
            raise RuntimeError(
                f"{title!r} is not the Cambridge dataset; nothing was changed"
            )
    ids: dict[str, str] = {}

    def finish(title: str) -> None:
        # Each dataset gets its own text as soon as it exists, so a later
        # failure cannot leave it public with the stub's wording.
        _apply_metadata(api, ids[title], title)
        _set_attribute_titles(
            api, ids[title], CAMBRIDGE_ATTRIBUTE_TITLES.get(title, {})
        )

    try:
        for title, service in BINDINGS:
            ids[title] = _bind(s, api, by_title, title, service)
            finish(title)
        ids[PARCELS_TITLE] = s._get_or_ingest(
            api,
            by_title,
            PARCELS_TITLE,
            "ASSESSING_ParcelsFY2027.geojson",
            lambda: parcels_bytes(s),
            CAMBRIDGE_METADATA[PARCELS_TITLE]["summary"],
            timeout=900,
        )
        finish(PARCELS_TITLE)
        ids[PARCELS_ZONED_TITLE] = s._get_or_analyze(
            api,
            by_title,
            PARCELS_ZONED_TITLE,
            ids[PARCELS_TITLE],
            "spatial_join",
            CAMBRIDGE_METADATA[PARCELS_ZONED_TITLE]["summary"],
            join_dataset_id=ids[ZONING_TITLE],
            join_fields=["zone_type"],
        )
        finish(PARCELS_ZONED_TITLE)
        ids[PARCELS_FLOOD_TITLE] = s._get_or_analyze(
            api,
            by_title,
            PARCELS_FLOOD_TITLE,
            ids[PARCELS_ZONED_TITLE],
            "select_by_location",
            CAMBRIDGE_METADATA[PARCELS_FLOOD_TITLE]["summary"],
            mask_dataset_id=ids[FLOOD_TITLE],
        )
        finish(PARCELS_FLOOD_TITLE)
    finally:
        if ids:
            collection_id = _ensure_collection(api, ids)
            print(f"  -> collection {collection_id}")
    return collection_id


def _datasets(api, titles) -> dict[str, str] | None:
    by_title = api.datasets_by_title()
    if not all(t in by_title for t in titles):
        return None
    if not all(_is_ours(api, by_title[t], t) for t in titles):
        return None
    return {t: by_title[t] for t in titles}


def _missing_catalog() -> str:
    return "(missing: the Cambridge datasets - run --only cambridge-catalog first)"


# --- maps ---------------------------------------------------------------------

_CAMERA = {
    "center_lng": -71.1142,
    "center_lat": 42.3782,
    "zoom": 12.9,
    "pitch": 0,
    "bearing": 0,
    "basemap_style": "openfreemap-positron",
    "show_basemap_labels": True,
}
_LAYER_KEYS = (
    "sort_order",
    "visible",
    "opacity",
    "paint",
    "layout",
    "filter",
    "label_config",
    "popup_config",
    "style_config",
    "show_in_legend",
)

SITE_TYPES = (
    ("Tree", "Tree", "#228b22"),
    ("Proposed Tree", "Proposed tree", "#1e78c8"),
    ("Planting Site", "Planting site", "#f0b41e"),
    ("Retired", "Retired", "#8c8c8c"),
    ("Stump", "Stump", "#965a32"),
    ("Damaged Tree Well", "Damaged tree well", "#c83c3c"),
)
_OTHER_COLOR = "#bebebe"
TREE_POPUP_FIELDS = [
    "commonname",
    "scientificname",
    "diameter",
    "plantdate",
    "sitetype",
    "neighborhood",
    "ownership",
    "overheadwires",
]


def _categorical(column: str, categories: list[tuple[str, str, str]], fallback: str):
    """A categorical color expression and the style_config the legend reads."""
    pairs = [part for value, _, color in categories for part in (value, color)]
    expression = [
        "case",
        ["==", ["get", column], None],
        fallback,
        ["match", ["to-string", ["get", column]], *pairs, fallback],
    ]
    style = {
        "mode": "categorical",
        "column": column,
        "categories": [
            {"value": value, "label": label, "color": color}
            for value, label, color in categories
        ],
        "ramp": "custom",
    }
    return expression, style


def _outline_only(color: str, width: float) -> dict:
    return {
        "paint": {"fill-color": "#000000", "fill-opacity": 0.0},
        "style_config": {
            "builder": {
                "fill_disabled": True,
                "outline_color": color,
                "outline_width": width,
            }
        },
    }


def _covers(have, want) -> bool:
    """Whether the stored value holds everything wanted; the server may add defaults."""
    if isinstance(want, dict):
        return isinstance(have, dict) and all(
            k in have and _covers(have[k], v) for k, v in want.items()
        )
    if isinstance(want, list) and want and all(isinstance(x, dict) for x in want):
        # Lists of objects gain defaults too; other lists are filters and expressions.
        return (
            isinstance(have, list)
            and len(have) == len(want)
            and all(_covers(h, w) for h, w in zip(have, want))
        )
    if isinstance(want, float) and isinstance(have, int | float):
        return abs(have - want) < 1e-9
    return have == want


def _ensure_map(api, name: str, description: str) -> tuple[str, bool]:
    map_id = api.list_maps().get(name)
    if map_id is not None:
        return map_id, False
    return api.create_map(name, description), True


def _sync_layers(api, map_id: str, wanted: list[dict]) -> None:
    """Add the layers the map lacks and bring stored ones up to the wanted style.

    Layers are matched by display name, so a layer a person added is left alone.
    """
    stored = {x.get("display_name"): x for x in api.get_map(map_id)["layers"]}
    for body in wanted:
        have = stored.get(body["display_name"])
        if have is None:
            api.add_layer(map_id, body)
            continue
        delta = {
            k: body[k]
            for k in _LAYER_KEYS
            if body.get(k) is not None and not _covers(have.get(k), body[k])
        }
        if delta:
            api.update_layer(map_id, {"id": have["id"], **delta})


def _set_map(api, map_id: str, current: dict, **wanted) -> None:
    delta = {k: v for k, v in wanted.items() if current.get(k) != v}
    if current.get("center_lng") is None:
        delta.update(_CAMERA)
    if delta:
        api.set_view(map_id, **delta)


def import_webmap(api, body: dict) -> dict:
    """POST an ArcGIS web map to the import endpoint and return its answer."""
    r = api.client.post(
        f"{api.base}/api/maps/import/arcgis-webmap/", headers=api.h, json=body
    )
    r.raise_for_status()
    return r.json()


_LOSS_PHRASES = {
    "label_style": "the label styling",
    "label_font": "the label font",
    "popup_field_label": "popup field aliases",
    "popup_field_format": "popup number and date formats",
    "popup_expression": "computed popup fields",
    "popup_media": "popup charts",
    "popup_html": "custom popup text",
    "symbol_style": "some symbol details",
    "picture_marker": "picture markers",
    "arcade": "Arcade expressions",
}


def lost_phrases(loss_report: dict) -> list[str]:
    """Plain words for what an import's loss report says did not carry over."""
    phrases = []
    for kind in loss_report.get("summary", {}):
        phrase = _LOSS_PHRASES.get(kind, "other details")
        if phrase not in phrases:
            phrases.append(phrase)
    return phrases


def _human_list(items: list[str]) -> str:
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]


def trees_map_description(loss_report: dict) -> str:
    lost = _human_list(lost_phrases(loss_report)) or "nothing the import reported"
    return (
        "Street trees in Cambridge, Massachusetts, drawn from an ArcGIS Online "
        "web map definition written for this demo over the city's public "
        "layers; the city's own web maps carry no license. GeoLens translated "
        "the definition when it imported it. The colors by site type, the "
        "popup fields, the neighborhood outlines and names, and the zoom "
        "range at which the trees appear carried over. Not carried over: "
        f"{lost}. The trees and neighborhoods are copies of the city's public "
        "ArcGIS Online layers, which GeoLens re-pulls on refresh. " + CITY_NOTE
    )


def build_trees_map(s, api, force: bool = False, force_pinned: bool = False) -> str:
    """Import the authored web map once; on a rerun refresh only its description."""
    ids = _datasets(api, (TREES_TITLE, NEIGHBORHOODS_TITLE))
    if ids is None:
        return _missing_catalog()
    try:
        webmap = json.loads(WEBMAP_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return f"(missing: {WEBMAP_PATH.name} is unreadable: {e})"
    print("\n[cambridge-trees] " + TREES_MAP)
    body = {
        "webmap": webmap,
        "name": TREES_MAP,
        "title": TREES_MAP,
        "visibility": "public",
        "basemap_map": {ESRI_STREETS_URL: "openfreemap-positron"},
        "dataset_matches": {
            "cambridge_neighborhoods": ids[NEIGHBORHOODS_TITLE],
            "cambridge_street_trees": ids[TREES_TITLE],
        },
    }
    dry = import_webmap(api, {**body, "dry_run": True})
    description = trees_map_description(dry["loss_report"])
    map_id = api.list_maps().get(TREES_MAP)
    if map_id is None:
        map_id = import_webmap(api, body)["map"]["id"]
        print(f"  imported -> map {map_id}")
    current = api.get_map(map_id)
    delta = {
        k: v
        for k, v in (
            ("description", description),
            ("legend_title", "Site type"),
            ("visibility", "public"),
        )
        if current.get(k) != v
    }
    if delta:
        api.set_view(map_id, **delta)
    s.warn_if_hidden_layers(api, map_id, TREES_MAP)
    return map_id


# The twelve district codes with the most parcels in the FY2027 assessing
# release, most first. Ranked by parcels, not by district polygons: a code with
# a few large polygons can hold far more lots than one with many small ones.
ZONE_COLORS = (
    ("C-1", "#e8c547"),
    ("OS", "#3f9f4f"),
    ("CAM-6", "#8e5bd6"),
    ("BB", "#d6338a"),
    ("BA", "#f28c28"),
    ("BA-1", "#e07b91"),
    ("C-2", "#1fa6b8"),
    ("MAS-12", "#6b4a2f"),
    ("C-2B", "#a3c639"),
    ("C-3", "#3d4f8a"),
    ("O-1", "#d4a373"),
    ("BA-3", "#0f766e"),
)
_FLOOD_BLUE = "#2563eb"
_FLAGGED_RED = "#e11d48"


def parcels_map_description(zoned_on: str) -> str:
    return (
        "Cambridge, Massachusetts parcels with the zoning district they meet "
        "and the FEMA 1% annual-chance floodplain. Click a parcel for its "
        "map-lot number and zoning district. A red outline marks a parcel "
        "that touches the floodplain, and its popup says so. The parcels are "
        "the city's FY2027 assessing release, an upload pinned to that "
        f"release. The join to zoning was run in GeoLens on {zoned_on}, and "
        "a parcel on a district edge can show the neighboring district. "
        "Zoning districts, the floodplain, neighborhoods and address points "
        "(from zoom 16) are copies of the city's public ArcGIS Online layers, "
        "which GeoLens re-pulls on refresh. The twelve district codes with the "
        "most parcels are colored; the rest are gray. Not an official zoning map or "
        "a flood determination. " + CITY_NOTE
    )


def _parcels_map_layers(ids: dict[str, str]) -> list[dict]:
    zone_fill, zone_style = _categorical(
        "zone_type", [(v, v, c) for v, c in ZONE_COLORS], "#c9ccd1"
    )
    return [
        {
            "dataset_id": ids[ADDRESSES_TITLE],
            "sort_order": 0,
            "display_name": "Address points (zoom 16 and closer)",
            "show_in_legend": False,
            "paint": {
                "circle-radius": 2.5,
                "circle-color": "#1f2937",
                "circle-stroke-color": "#ffffff",
                "circle-stroke-width": 0.8,
            },
            "layout": {"_minzoom": 16},
            "popup_config": {
                "enabled": True,
                "expression": "{full_addr}",
                "visible_fields": ["full_addr", "ml"],
            },
        },
        {
            "dataset_id": ids[PARCELS_FLOOD_TITLE],
            "sort_order": 1,
            "display_name": "Parcels touching the 1% floodplain",
            **_outline_only(_FLAGGED_RED, 2.0),
            "popup_config": {
                "enabled": True,
                "expression": "Parcel {ml}: zoning {join_zone_type}, "
                "in the 1% annual-chance floodplain",
                "visible_fields": ["ml", "join_zone_type"],
            },
        },
        {
            "dataset_id": ids[PARCELS_ZONED_TITLE],
            "sort_order": 2,
            "display_name": "Parcels (FY2027)",
            "show_in_legend": True,
            **_outline_only("#64748b", 0.5),
            "popup_config": {
                "enabled": True,
                "expression": "Parcel {ml}: zoning {join_zone_type}",
                "visible_fields": ["ml", "join_zone_type"],
            },
        },
        {
            "dataset_id": ids[NEIGHBORHOODS_TITLE],
            "sort_order": 3,
            "display_name": "Neighborhoods",
            "show_in_legend": True,
            **_outline_only("#334155", 2.0),
            "label_config": {
                "column": "name",
                "fontSize": 13,
                "textColor": "#1e293b",
                "haloColor": "#ffffff",
                "haloWidth": 2,
                "minZoom": 10.5,
            },
            "popup_config": {"enabled": False},
        },
        {
            "dataset_id": ids[FLOOD_TITLE],
            "sort_order": 4,
            "display_name": "FEMA 1% annual-chance floodplain",
            "paint": {
                "fill-color": _FLOOD_BLUE,
                "fill-opacity": 0.4,
                "fill-outline-color": _FLOOD_BLUE,
            },
            "popup_config": {"enabled": False},
        },
        {
            "dataset_id": ids[ZONING_TITLE],
            "sort_order": 5,
            "display_name": "Zoning districts",
            "paint": {"fill-color": zone_fill, "fill-opacity": 0.45},
            "style_config": zone_style,
            "popup_config": {
                "enabled": True,
                "expression": "Zoning district {zone_type}",
                "visible_fields": ["zone_type"],
            },
        },
    ]


# What each layer's popup, label and style read, by dataset.
PARCELS_MAP_COLUMNS = {
    ADDRESSES_TITLE: ["full_addr", "ml"],
    PARCELS_ZONED_TITLE: ["ml", "join_zone_type"],
    PARCELS_FLOOD_TITLE: ["ml", "join_zone_type"],
    ZONING_TITLE: ["zone_type"],
    NEIGHBORHOODS_TITLE: ["name"],
}


def build_parcels_map(s, api, force: bool = False, force_pinned: bool = False) -> str:
    titles = (
        ADDRESSES_TITLE,
        NEIGHBORHOODS_TITLE,
        ZONING_TITLE,
        FLOOD_TITLE,
        PARCELS_ZONED_TITLE,
        PARCELS_FLOOD_TITLE,
    )
    ids = _datasets(api, titles)
    if ids is None:
        return _missing_catalog()
    print("\n[cambridge-parcels] " + PARCELS_MAP)
    for title, columns in PARCELS_MAP_COLUMNS.items():
        _require_columns(api, ids[title], title, columns)
    zoned_on = (api.get_dataset(ids[PARCELS_ZONED_TITLE]).get("created_at") or "")[:10]
    description = parcels_map_description(zoned_on or date.today().isoformat())
    map_id, created = _ensure_map(api, PARCELS_MAP, description)
    _sync_layers(api, map_id, _parcels_map_layers(ids))
    _set_map(
        api,
        map_id,
        api.get_map(map_id),
        description=description,
        legend_title="Zoning district",
        visibility="public",
    )
    s.warn_if_hidden_layers(api, map_id, PARCELS_MAP)
    print(f"  -> map {map_id} ({'created' if created else 'updated'}, public)")
    return map_id


# --- dashboards -----------------------------------------------------------------

DASHBOARD_READABLE = [
    "markdown:1",
    "indicator:1",
    "bar_chart:1",
    "histogram:1",
    "category_selector:1",
    "pie_chart:1",
    "table:1",
    "feature_list:1",
    # Indicators with a reference and bar charts by date store as version 2;
    # leaving them out would lock those widgets on the next save.
    "indicator:2",
    "bar_chart:2",
]
_MEASURED_DIAMETER = [
    "all",
    [">", ["get", "diameter"], 0],
    ["<=", ["get", "diameter"], 60],
]


def _years_filter(first: int, last: int) -> dict:
    """CQL2 for plantdate within UTC calendar years first to last, as the date buckets cut it."""
    return {
        "op": "and",
        "args": [
            {
                "op": ">=",
                "args": [
                    {"property": "plantdate"},
                    {"timestamp": f"{first}-01-01T00:00:00Z"},
                ],
            },
            {
                "op": "<",
                "args": [
                    {"property": "plantdate"},
                    {"timestamp": f"{last + 1}-01-01T00:00:00Z"},
                ],
            },
        ],
    }


def _plant_years_layer_filter(first: int, last: int) -> list:
    return [
        "all",
        [">=", ["get", "plantdate"], f"{first}-01-01T00:00:00+00:00"],
        ["<", ["get", "plantdate"], f"{last + 1}-01-01T00:00:00+00:00"],
    ]


def tree_dashboard_description() -> str:
    return (
        "Street tree work in Cambridge, Massachusetts: trees by site type, "
        "planting by year, proposed planting sites and trunk diameters. Move "
        "the map to change what most widgets count. The data is a copy of "
        "the city's public Trees layer on ArcGIS Online, which GeoLens "
        "re-pulls on refresh. " + CITY_NOTE
    )


def land_dashboard_description() -> str:
    return (
        "Cambridge, Massachusetts parcels by zoning district, and the parcels "
        "that touch the FEMA 1% annual-chance floodplain. The parcels are the "
        "city's FY2027 assessing release; zoning and floodplain were joined "
        "in GeoLens. A parcel on a district edge can show the neighboring "
        "district. " + CITY_NOTE
    )


# A widget counts what its layer's filter lets through, so each filtered count
# needs a hidden layer of its own. The collapsed group tells a builder user why
# three layers are never drawn.
_WIDGET_INPUTS = {
    "builder": {
        "folder_group_id": "cambridge-widget-inputs",
        "folder_group_name": "Widget inputs (hidden)",
        "folder_group_expanded": False,
    }
}


def _tree_layers(trees_ds: str) -> list[dict]:
    fill, style = _categorical(
        "sitetype", [(v, label, c) for v, label, c in SITE_TYPES], _OTHER_COLOR
    )
    radius = ["interpolate", ["linear"], ["zoom"], 10, 1.5, 14, 3, 18, 7]
    popup = {
        "enabled": True,
        "expression": "{sitetype}: {commonname}",
        "visible_fields": TREE_POPUP_FIELDS,
    }
    quiet = {"circle-radius": 3, "circle-color": "#ffffff", "circle-opacity": 0.0}
    return [
        {
            "dataset_id": trees_ds,
            "sort_order": 1,
            "display_name": "Street trees by site type",
            "paint": {
                "circle-radius": radius,
                "circle-color": fill,
                "circle-opacity": 0.85,
                "circle-stroke-color": "#ffffff",
                "circle-stroke-width": 0.5,
            },
            "style_config": style,
            "popup_config": popup,
        },
        {
            "dataset_id": trees_ds,
            "sort_order": 0,
            "display_name": "Proposed planting sites",
            "show_in_legend": True,
            "filter": ["==", ["get", "sitetype"], "Proposed Tree"],
            "paint": {
                "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 3, 18, 10],
                "circle-color": "#1e78c8",
                "circle-opacity": 0.0,
                "circle-stroke-color": "#1e78c8",
                "circle-stroke-width": 1.5,
            },
            "popup_config": {
                "enabled": True,
                "expression": "Proposed planting site: {streetname}",
                "visible_fields": ["streetname", "plantingseason", "neighborhood"],
            },
        },
        {
            "dataset_id": trees_ds,
            "sort_order": 2,
            "display_name": f"Trees planted {RECENT_LABEL}",
            "show_in_legend": False,
            "visible": False,
            "style_config": _WIDGET_INPUTS,
            "filter": _plant_years_layer_filter(*RECENT_YEARS),
            "paint": quiet,
            "popup_config": {"enabled": False},
        },
        {
            "dataset_id": trees_ds,
            "sort_order": 4,
            "display_name": "Trees planted since 2008",
            "show_in_legend": False,
            "visible": False,
            "style_config": _WIDGET_INPUTS,
            "filter": [">=", ["get", "plantdate"], "2008-01-01T00:00:00+00:00"],
            "paint": quiet,
            "popup_config": {"enabled": False},
        },
        {
            "dataset_id": trees_ds,
            "sort_order": 3,
            "display_name": "Trees with a recorded trunk diameter",
            "show_in_legend": False,
            "visible": False,
            "style_config": _WIDGET_INPUTS,
            "filter": _MEASURED_DIAMETER,
            "paint": quiet,
            "popup_config": {"enabled": False},
        },
    ]


RECENT_YEARS = (2021, 2025)
EARLIER_YEARS = (2016, 2020)
RECENT_LABEL = "2021-2025"
EARLIER_LABEL = "2016-2020"


def _count_planted(api, trees_ds: str, years: tuple[int, int]) -> int:
    return api.aggregate(trees_ds, op="count", filter=_years_filter(*years))["count"]


def _tree_widgets(
    s, layer_ids: dict[str, str], planted: int, reference: int
) -> list[dict]:
    def widget(key, kind, title, layer, config, scope="view"):
        built = s._dashboard_widget(
            "cambridge-trees", layer_ids[layer], key, kind, title, config
        )
        built["scope"] = scope
        return built

    all_trees = "Street trees by site type"
    indicator = widget(
        "planted",
        "indicator",
        f"Trees planted {RECENT_LABEL}",
        f"Trees planted {RECENT_LABEL}",
        {
            "stat": "count",
            "reference": reference,
            "reference_label": EARLIER_LABEL,
            "higher_is_better": True,
            "comparison": "both",
        },
        scope="layer",
    )
    indicator["v"] = 2
    by_year = widget(
        "by-year",
        "bar_chart",
        "Trees planted per year since 2008",
        "Trees planted since 2008",
        {
            "mode": "date",
            "column": "plantdate",
            "date_bucket": "year",
            "stat": "count",
            "limit": 50,
        },
    )
    by_year["v"] = 2
    return [
        indicator,
        by_year,
        widget(
            "site-types",
            "pie_chart",
            "Trees by site type",
            all_trees,
            {"column": "sitetype", "stat": "count", "limit": 8},
        ),
        widget(
            "species",
            "bar_chart",
            "Most common species of measured trees",
            "Trees with a recorded trunk diameter",
            {"column": "commonname", "stat": "count", "limit": 10},
            scope="layer",
        ),
        widget(
            "neighborhoods",
            "table",
            "Measured trees by neighborhood",
            "Trees with a recorded trunk diameter",
            {
                "group_column": "neighborhood",
                "stats": [
                    {"stat": "count"},
                    {"stat": "mean", "column": "diameter"},
                ],
                "sort_by": 0,
                "sort": "desc",
                "limit": 15,
            },
            scope="layer",
        ),
        widget(
            "diameters",
            "histogram",
            "Trunk diameter of measured trees (inches)",
            "Trees with a recorded trunk diameter",
            {"column": "diameter", "bins": 20},
            scope="layer",
        ),
        widget(
            "neighborhood-picker",
            "category_selector",
            "Pick a neighborhood (filters the map and the site-type chart)",
            all_trees,
            {"column": "neighborhood"},
        ),
        widget(
            "proposed",
            "feature_list",
            "Proposed planting sites",
            "Proposed planting sites",
            {
                "title_column": "streetname",
                "subtitle_column": "plantingseason",
                "sort_column": "streetname",
                "sort": "asc",
                "page_size": 25,
            },
        ),
        {
            "id": s._seed_id("cambridge-trees", "about"),
            "type": "markdown",
            "v": 1,
            "title": None,
            "config": {
                "text": "Data: the City of Cambridge's public Trees layer on "
                "ArcGIS Online. This is a copy that GeoLens re-pulls on refresh, "
                "so counts can differ from the city's current "
                "numbers. Plant dates and diameters are as the city recorded "
                "them, and recent years can be incomplete. The planted-trees "
                "indicator compares 2021-2025 with 2016-2020 over the whole city. Planting dates are recorded as the city enters them. "
                "Picking a neighborhood filters the map and the site-type "
                "chart only; the other widgets keep counting the whole city.\n\n"
                "Built from the City of Cambridge's open data (PDDL 1.0). "
                "The city does not use or endorse GeoLens."
            },
        },
    ]


def _dashboard_unchanged(current: dict, dashboard: dict) -> bool:
    """Whether the map already stores these widgets, so a rerun saves nothing."""
    stored = current.get("dashboard_config") or {}
    widgets = stored.get("widgets") or []
    return (
        stored.get("panel", "right") == dashboard.get("panel", "right")
        and stored.get("map_hidden", False) == dashboard.get("map_hidden", False)
        and len(widgets) == len(dashboard["widgets"])
        and all(_covers(a, b) for a, b in zip(widgets, dashboard["widgets"]))
    )


def _save_dashboard(api, map_id: str, current: dict, description: str, dashboard: dict):
    """Write the description, public visibility, first camera and dashboard when they differ."""
    wanted = {"description": description, "visibility": "public"}
    if current.get("center_lng") is None:
        wanted.update(_CAMERA)
    delta = {k: v for k, v in wanted.items() if current.get(k) != v}
    if not _dashboard_unchanged(current, dashboard):
        delta["dashboard_config"] = dashboard
    if delta:
        api.set_view(map_id, **delta)


def _ensure_dashboard_map(api, name: str, description: str, layers: list[dict]):
    map_id, created = _ensure_map(api, name, description)
    _sync_layers(api, map_id, layers)
    current = api.get_map(map_id)
    by_name = {x["display_name"]: x["id"] for x in current["layers"]}
    return map_id, created, current, by_name


def seed_tree_dashboard(s, api, force: bool = False, force_pinned: bool = False) -> str:
    ids = _datasets(api, (TREES_TITLE,))
    if ids is None:
        return _missing_catalog()
    trees_ds = ids[TREES_TITLE]
    print("\n[cambridge-tree-dashboard] " + TREE_DASHBOARD)
    columns = [
        "sitetype",
        "plantdate",
        "diameter",
        "neighborhood",
        "streetname",
        "plantingseason",
        *TREE_POPUP_FIELDS,
    ]
    _require_columns(api, trees_ds, TREES_TITLE, columns)
    _require_uncoded(
        api,
        trees_ds,
        TREES_TITLE,
        [
            "sitetype",
            "plantdate",
            "diameter",
            "neighborhood",
            "streetname",
            "plantingseason",
        ],
    )
    description = tree_dashboard_description()
    map_id, created, current, layer_ids = _ensure_dashboard_map(
        api, TREE_DASHBOARD, description, _tree_layers(trees_ds)
    )
    planted, reference = (
        _count_planted(api, trees_ds, RECENT_YEARS),
        _count_planted(api, trees_ds, EARLIER_YEARS),
    )
    _save_dashboard(
        api,
        map_id,
        current,
        description,
        {
            "version": 1,
            "panel": "right",
            "readable": DASHBOARD_READABLE,
            "widgets": _tree_widgets(s, layer_ids, planted, reference),
        },
    )
    s.warn_if_hidden_layers(api, map_id, TREE_DASHBOARD)
    print(
        f"  -> map {map_id} ({'created' if created else 'updated'}, public); "
        f"planted {RECENT_LABEL}: {planted}, {EARLIER_LABEL}: {reference}"
    )
    return map_id


def _land_layers(zoned_ds: str, flood_ds: str) -> list[dict]:
    outline = _outline_only("#64748b", 0.5)
    return [
        {
            "dataset_id": zoned_ds,
            "sort_order": 0,
            "display_name": "Parcels with zoning",
            **outline,
            "popup_config": {
                "enabled": True,
                "expression": "Parcel {ml}: zoning {join_zone_type}",
                "visible_fields": ["ml", "join_zone_type"],
            },
        },
        {
            "dataset_id": flood_ds,
            "sort_order": 1,
            "display_name": "Parcels touching the 1% floodplain",
            **_outline_only(_FLAGGED_RED, 1.4),
            "popup_config": {
                "enabled": True,
                "expression": "Parcel {ml}: zoning {join_zone_type}, "
                "in the 1% annual-chance floodplain",
                "visible_fields": ["ml", "join_zone_type"],
            },
        },
    ]


def _land_widgets(s, layer_ids: dict[str, str]) -> list[dict]:
    def widget(key, kind, title, layer, config):
        built = s._dashboard_widget(
            "cambridge-land", layer_ids[layer], key, kind, title, config
        )
        built["scope"] = "layer"
        return built

    parcels, flooded = "Parcels with zoning", "Parcels touching the 1% floodplain"
    # The page grid holds five 1-column cells at desktop width and a wide
    # widget takes two. Each row is five cells of similar height: the numbers,
    # the two pies with the notes, then the table and bar chart.
    return [
        widget("parcels", "indicator", "Parcels", parcels, {"stat": "count"}),
        widget(
            "flooded",
            "indicator",
            "Parcels touching the 1% floodplain",
            flooded,
            {"stat": "count"},
        ),
        widget(
            "land-area",
            "indicator",
            "Land area of all parcels (sq ft)",
            parcels,
            {"stat": "sum", "column": "shape_area"},
        ),
        widget(
            "flooded-area",
            "indicator",
            "Land area of floodplain parcels (sq ft)",
            flooded,
            {"stat": "sum", "column": "shape_area"},
        ),
        {
            "id": s._seed_id("cambridge-land", "floodplain"),
            "type": "markdown",
            "v": 1,
            "title": None,
            "config": {
                "text": "The 1% annual-chance floodplain is the area FEMA maps "
                "as having a 1 in 100 chance of flooding in any year, often "
                "called the 100-year floodplain. A parcel is counted if any "
                "part of it meets that area. This is a screening count, not a "
                "flood insurance determination."
            },
        },
        widget(
            "zones",
            "pie_chart",
            "Parcels by zoning district",
            parcels,
            {
                "column": "join_zone_type",
                "stat": "count",
                "limit": 6,
                "use_layer_colors": False,
            },
        ),
        widget(
            "flooded-zones",
            "pie_chart",
            "Floodplain parcels by zoning district",
            flooded,
            {
                "column": "join_zone_type",
                "stat": "count",
                "limit": 6,
                "use_layer_colors": False,
            },
        ),
        {
            "id": s._seed_id("cambridge-land", "about"),
            "type": "markdown",
            "v": 1,
            "title": None,
            "config": {
                "text": "Parcels: the City of Cambridge's FY2027 assessing "
                "release. Zoning districts and the floodplain: copies of the "
                "city's public ArcGIS Online layers, which GeoLens re-pulls on "
                "refresh. The zoning join and the floodplain selection were "
                "run in GeoLens, and each dataset's provenance panel shows "
                "the steps.\n\nBuilt from the City of Cambridge's open data "
                "(PDDL 1.0). The city does not use or endorse GeoLens."
            },
        },
        widget(
            "zone-table",
            "table",
            "Zoning districts: parcels and land area",
            parcels,
            {
                "group_column": "join_zone_type",
                "stats": [
                    {"stat": "count"},
                    {"stat": "sum", "column": "shape_area"},
                ],
                "sort_by": 0,
                "sort": "desc",
                "limit": 12,
            },
        ),
        widget(
            "zone-area",
            "bar_chart",
            "Land area by zoning district (sq ft)",
            parcels,
            {
                "column": "join_zone_type",
                "stat": "sum",
                "stat_column": "shape_area",
                "limit": 10,
            },
        ),
        widget(
            "largest",
            "indicator",
            "Largest parcel (sq ft)",
            parcels,
            {"stat": "max", "column": "shape_area"},
        ),
    ]


def seed_land_dashboard(s, api, force: bool = False, force_pinned: bool = False) -> str:
    ids = _datasets(api, (PARCELS_ZONED_TITLE, PARCELS_FLOOD_TITLE))
    if ids is None:
        return _missing_catalog()
    print("\n[cambridge-land-dashboard] " + LAND_DASHBOARD)
    for title in ids:
        _require_columns(api, ids[title], title, ["join_zone_type", "shape_area"])
        _require_uncoded(api, ids[title], title, ["join_zone_type", "shape_area"])
    description = land_dashboard_description()
    layers = _land_layers(ids[PARCELS_ZONED_TITLE], ids[PARCELS_FLOOD_TITLE])
    map_id, created, current, layer_ids = _ensure_dashboard_map(
        api, LAND_DASHBOARD, description, layers
    )
    _save_dashboard(
        api,
        map_id,
        current,
        description,
        {
            "version": 1,
            "map_hidden": True,
            "readable": DASHBOARD_READABLE,
            "widgets": _land_widgets(s, layer_ids),
        },
    )
    s.warn_if_hidden_layers(api, map_id, LAND_DASHBOARD)
    print(f"  -> map {map_id} ({'created' if created else 'updated'}, public)")
    return map_id


# --- refresh ------------------------------------------------------------------


def refresh_services(s, api, quake_titles) -> int:
    """Re-pull every service-bound dataset this account owns, one at a time.

    The earthquake bindings go through the seeder's own refresh, which knows
    their legacy title and any retained copy. The Cambridge bindings are
    required: a missing one, or one that is not service-origin, counts as a
    failure, since the demo's job reads a zero exit as "the data is current".
    Any other owned service-bound dataset is refreshed as well, every dataset
    by id so two under one title both refresh, and one dataset's transport
    error never stops the sweep. The street trees go last, so the newest
    catalog card is the intended lead.
    """
    failed = False
    try:
        failed = s.refresh_quakes(api) != 0
    except httpx.HTTPError as e:
        print(f"  ! earthquake refresh: {e}", file=sys.stderr)
        failed = True
    owned = [(d["id"], d["title"]) for d in api.list_own_datasets()]
    titles = {title for _, title in owned}
    for title in SERVICE_TITLES:
        if title not in titles:
            print(
                f"  ! no dataset titled {title!r}; run a normal seed", file=sys.stderr
            )
            failed = True

    def rows(keep):
        return [(i, t) for i, t in owned if keep(t)]

    ordered = (
        rows(lambda t: t in SERVICE_TITLES and t != TREES_TITLE)
        + rows(lambda t: t not in SERVICE_TITLES and t not in quake_titles)
        + rows(lambda t: t == TREES_TITLE)
    )
    for dataset_id, title in ordered:
        try:
            origin = api.dataset_origin(dataset_id)
            if origin != "service":
                if title not in SERVICE_TITLES:
                    continue
                print(
                    f"  ! {title!r} has origin {origin!r}, not 'service'; "
                    "run a normal seed first",
                    file=sys.stderr,
                )
                failed = True
                continue
            print(f"Refreshing {title}...")
            if not s.refresh_and_report(api, dataset_id, title):
                failed = True
        except httpx.HTTPError as e:
            print(f"  ! {title!r}: {e}", file=sys.stderr)
            failed = True
    return 1 if failed else 0


# --- story --------------------------------------------------------------------

STORY_TITLE = "Cambridge's open data in GeoLens"
# The title this story had before it was shortened; a rerun renames it in place.
STORY_TITLE_LEGACY = (
    "Cambridge open data: from an ArcGIS Online organization to GeoLens"
)
STORY_SUMMARY = (
    "What a GIS lead can do with a city's public ArcGIS Online organization: "
    "inventory it, bind its layers, translate a web map, derive new data and "
    "share it through open standards. Built from the City of Cambridge's open "
    "data; the city does not use or endorse GeoLens."
)
ASSETS_DIR = Path(__file__).resolve().parent / "cambridge_story_assets"
# (file, alt text, caption)
STORY_IMAGES = (
    (
        "share-panel.png",
        "The map Share panel with Specific groups selected and two groups, GIS team and Urban forestry, added.",
        "Share a map with named groups instead of everyone.",
    ),
    (
        "admin-groups.png",
        "The Admin Groups page: a table of sharing groups with member counts.",
        "Groups are managed by an administrator and used by sharing and access.",
    ),
    (
        "dataset-access.png",
        "A dataset's Access tab with its visibility setting and group sharing.",
        "Per-dataset visibility and group sharing.",
    ),
)
# A recorded run of `geolens arcgis inventory`, quoted as printed. The counts
# belong to the run date and are not read at seed time.
INVENTORY_RUN_DATE = "7 November 2026"
INVENTORY_EXCERPT = """\
Portal   City of Cambridge (ArcGIS Online)
Items    1248
  supported     506
  partial       345
  unsupported   397

Feature Service          505 (464 hosted)
Web Map                  265
Web Mapping Application  110
StoryMap                  69
Map Service               59
Dashboard                 37

Retiring: 52 classic Esri Story Maps,
          9 Web AppBuilder apps"""


def _count(api, dataset_id: str, what: str, **body) -> int:
    value = api.aggregate(dataset_id, op="count", **body)["count"]
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(f"the count of {what} is not a number: {value!r}")
    return value


def _story_cover(api, story_id: str, trees_map_id: str, fallback: str) -> str:
    """The story's cover asset: kept once set, else the trees map's thumbnail.

    An instance whose map has no thumbnail yet gets the first gallery image.
    """
    stored = api.story_cover_asset(story_id)
    if stored:
        return str(stored)
    thumbnail = api.map_thumbnail(trees_map_id)
    if thumbnail is None:
        return fallback
    data, kind = thumbnail
    return api.upload_story_asset(
        story_id, "street-trees-map." + kind.removeprefix("image/"), data, kind
    )


def _story_images() -> list[tuple[str, bytes, str, str]]:
    out = []
    for name, alt, caption in STORY_IMAGES:
        path = ASSETS_DIR / name
        if not path.is_file():
            raise RuntimeError(f"story screenshot {path} is missing")
        out.append((name, path.read_bytes(), alt, caption))
    return out


def _gallery_assets(api, story_id: str | None, block_id: str, count: int):
    """Asset ids of the gallery's pictures, reused while the pictures are the same."""
    if story_id is not None:
        for chapter in api.story_document(story_id).get("chapters", []):
            for block in chapter.get("blocks", []):
                stored = (block.get("config") or {}).get("images") or []
                if block.get("id") == block_id and len(stored) == count:
                    return [str(x["asset_id"]) for x in stored]
    return None


def _story_camera(lng: float, lat: float, zoom: float, pitch: float = 0) -> dict:
    return {"center": [lng, lat], "zoom": zoom, "bearing": 0, "pitch": pitch}


# Each view centers on what its chapter is about; the reader centers a scene
# in the part of the map the floating panel leaves free.
WEBMAP_CAMERA = _story_camera(-71.0857, 42.3656, 14.4)
FLOOD_VIEW = (-71.1383, 42.3993, 15.3)
CALM_VIEW = (-71.1010, 42.3700, 13.6)
ZONING_LAYER = "Zoning districts"
PARCELS_CALM_LAYERS = ("Parcels (FY2027)", "Neighborhoods")


def seed_cambridge_story(
    s, api, force: bool = False, force_pinned: bool = False
) -> str:
    """The published Cambridge story over the section's maps, found by title.

    Maps and link targets are resolved by name when this runs, and every count
    in the text is aggregated from the datasets. The three screenshots are
    stored in the repository next to this file; a rerun over the same pictures
    reuses the uploaded assets. The maps are not touched.
    """
    maps = api.list_maps()
    ids = _datasets(api, (TREES_TITLE, PARCELS_ZONED_TITLE, PARCELS_FLOOD_TITLE))
    collection = {c["name"]: c["id"] for c in api.list_collections()}.get(
        COLLECTION_NAME
    )
    missing = [name for name in sorted(MAP_NAMES) if name not in maps]
    if ids is None or collection is None or missing:
        return "(missing: the Cambridge catalog, collection and maps - run the Cambridge builders first)"
    print("\n[cambridge-story] " + STORY_TITLE)
    app_url = api.public_app_url()
    trees_map = api.get_map(maps[TREES_MAP])
    parcels_map = api.get_map(maps[PARCELS_MAP])
    ops_map = api.get_map(maps[TREE_DASHBOARD])
    for doc in (trees_map, parcels_map, ops_map):
        if doc.get("center_lng") is None or doc.get("center_lat") is None:
            raise RuntimeError(f"{doc.get('name')!r} has no saved camera")

    records = _count(api, ids[TREES_TITLE], "tree records")
    standing = _count(
        api,
        ids[TREES_TITLE],
        "standing trees",
        filter={"op": "=", "args": [{"property": "sitetype"}, "Tree"]},
    )
    parcels = _count(api, ids[PARCELS_ZONED_TITLE], "parcels")
    flooded = _count(api, ids[PARCELS_FLOOD_TITLE], "floodplain parcels")
    recent = _count_planted(api, ids[TREES_TITLE], RECENT_YEARS)
    earlier = _count_planted(api, ids[TREES_TITLE], EARLIER_YEARS)

    images = _story_images()
    stories = api.list_stories()
    story_id = stories.get(STORY_TITLE) or stories.get(STORY_TITLE_LEGACY)
    verb = "updated"
    if story_id is None:
        story_id = api.create_story(STORY_TITLE, STORY_SUMMARY)
        verb = "created"
    digest = hashlib.sha256(b"".join(data for _, data, _, _ in images)).hexdigest()
    gallery_id = s._seed_id("story", "cambridge-signed-in", "gallery", digest)
    asset_ids = _gallery_assets(
        api, story_id if verb == "updated" else None, gallery_id, len(images)
    )
    if asset_ids is None:
        asset_ids = [
            api.upload_story_asset(story_id, name, data, "image/png")
            for name, data, _, _ in images
        ]

    def text(key: str, body: str) -> dict:
        return s._story_block(key, "text", "markdown", config={"text": body})

    def button(
        key: str, name: str, label: str, url: str, new_tab: bool = False
    ) -> dict:
        return s._story_block(
            key, name, "button", config={"label": label, "url": url, "new_tab": new_tab}
        )

    def separator(key: str) -> dict:
        return s._story_block(key, "separator", "separator", config={"style": "line"})

    def chapter(key: str, title: str, scene, blocks: list[dict]) -> dict:
        key = "cambridge-" + key
        out = s._story_blocks_chapter(key, title, scene, blocks)
        if scene is None:
            out["scene_hidden"] = False
        return out

    def scene(
        doc: dict,
        camera: dict | None = None,
        transition: str | None = None,
        visibility: dict[str, bool] | None = None,
    ):
        return s._story_scene(doc, visibility, camera, transition)

    parcel_layers = {x["display_name"]: x["id"] for x in parcels_map["layers"]}
    if not set(PARCELS_CALM_LAYERS) | {ZONING_LAYER} <= set(parcel_layers):
        raise RuntimeError("the parcels map is missing a layer the story shows")
    # The zoning fills hide the flagged outlines they sit under.
    flood_only = {parcel_layers[ZONING_LAYER]: False}
    calm = {
        layer_id: name in PARCELS_CALM_LAYERS
        for name, layer_id in parcel_layers.items()
    }

    collection_url = f"{app_url}/api/collections/{ids[TREES_TITLE]}/items"
    document = {
        "version": 1,
        "settings": {
            "layout": "floating",
            "panel_position": "left",
            "navigation": True,
            "transition": "glide",
            "theme": "follow",
        },
        "chapters": [
            chapter(
                "origin",
                "A city's data, where it lives today",
                scene(trees_map, None, "fly"),
                [
                    text(
                        "origin",
                        "The City of Cambridge, Massachusetts publishes its GIS layers "
                        "as open data (Open Data Commons PDDL 1.0) in a public ArcGIS "
                        "Online organization. This whole section is built from those "
                        "layers.\n\nThe city does not use or endorse GeoLens.",
                    ),
                    button(
                        "origin",
                        "city",
                        "The city's open data page",
                        "https://www.cambridgema.gov/GIS",
                        True,
                    ),
                ],
            ),
            chapter(
                "inventory",
                "What an inventory finds",
                scene(trees_map),
                [
                    text(
                        "inventory",
                        "Before moving anything, list it. This command ran against the "
                        f"public organization on {INVENTORY_RUN_DATE}, with no sign-in:"
                        "\n\n```\ngeolens arcgis inventory --scope org \\\n"
                        "  --portal-url \\\n"
                        "  https://cambridgegis.maps.arcgis.com\n```\n\n"
                        f"```\n{INVENTORY_EXCERPT}\n```\n\n"
                        "Run it against your own organization with a sign-in, then "
                        "`geolens arcgis plan` and `geolens arcgis migrate`.",
                    )
                ],
            ),
            chapter(
                "bound",
                "Bound, not copied by hand",
                scene(trees_map, _story_camera(-71.1190, 42.3736, 16.3, 55), "fly"),
                [
                    text(
                        "bound",
                        "Five layers are bound to the city's hosted feature layers, and "
                        "the demo's daily job re-pulls them, so they are copies that can "
                        f"lag the city. The trees layer holds {records:,} records, "
                        f"{standing:,} of them standing trees. A tree "
                        "popup shows the layer's coded-value domain labels instead of "
                        "raw codes.\n\nThe parcels are an upload pinned to the FY2027 "
                        "release, so the dataset page shows both kinds of origin side "
                        "by side.",
                    ),
                    button(
                        "bound",
                        "trees",
                        "Open the trees dataset",
                        f"{app_url}/datasets/{ids[TREES_TITLE]}",
                    ),
                ],
            ),
            chapter(
                "webmap",
                "A web map, translated",
                scene(trees_map, WEBMAP_CAMERA, "fly"),
                [
                    text(
                        "webmap",
                        "This map came from an ArcGIS web map definition written for "
                        "this demo over the city's layers. The colors by site type, the "
                        "popup fields, the neighborhood outlines and the zoom range "
                        "carried over. Popup aliases, number and date formats, computed "
                        "fields, popup charts and label styling did not, and the import "
                        "report lists each loss.",
                    ),
                    button(
                        "webmap",
                        "map",
                        "Open the map",
                        f"{app_url}/maps/{maps[TREES_MAP]}",
                    ),
                ],
            ),
            chapter(
                "parcels",
                "Parcels that answer a question",
                scene(parcels_map, _story_camera(*FLOOD_VIEW), "fly", flood_only),
                [
                    text(
                        "parcels",
                        "A spatial join in GeoLens gave each of the "
                        f"{parcels:,} parcels its zoning district, and a second step "
                        "flagged the ones that touch the FEMA 1% annual-chance "
                        f"floodplain: {flooded:,} of them. The provenance panel on each "
                        "derived dataset shows the three sources and the steps.\n\n"
                        "This is a screening count, not a flood determination.",
                    ),
                    separator("parcels"),
                    button(
                        "parcels",
                        "dashboard",
                        "Land and zoning in numbers",
                        f"{app_url}/maps/{maps[LAND_DASHBOARD]}",
                    ),
                ],
            ),
            chapter(
                "operations",
                "Operations, not just maps",
                scene(ops_map, _story_camera(-71.1010, 42.3735, 15.2), "fly"),
                [
                    text(
                        "operations",
                        "The tree operations dashboard answers the questions a forestry "
                        f"crew asks: {recent:,} trees planted in {RECENT_LABEL} against "
                        f"{earlier:,} in {EARLIER_LABEL}, which species, and where the "
                        "proposed planting sites are. Pick a bar and the map filters "
                        "to it.",
                    ),
                    button(
                        "operations",
                        "dashboard",
                        "Open the dashboard",
                        f"{app_url}/maps/{maps[TREE_DASHBOARD]}",
                    ),
                ],
            ),
            chapter(
                "clients",
                "Your ArcGIS Pro and QGIS users keep working",
                scene(parcels_map, _story_camera(*CALM_VIEW), "fly", calm),
                [
                    text(
                        "clients",
                        "Every vector dataset is an OGC API Features collection and a "
                        "vector tile set. The trees collection is at:\n\n"
                        f"`{collection_url}`\n\n"
                        'The QGIS plugin "GeoLens" on plugins.qgis.org browses the '
                        "catalog. ArcGIS Pro opens the OGC API Features address "
                        "through Add Data.",
                    )
                ],
            ),
            chapter(
                "signed-in",
                "What signed-in users get",
                None,
                [
                    text(
                        "signed-in",
                        "A public demo cannot show a signed-in session, so these are "
                        "pictures. Groups and restricted sharing decide who sees a map "
                        "or dataset. Feature editing keeps versions and uses write "
                        "keys. API keys carry scopes.",
                    ),
                    {
                        "id": gallery_id,
                        "type": "carousel",
                        "v": 1,
                        "config": {
                            "images": [
                                {"asset_id": asset, "alt": alt, "caption": caption}
                                for asset, (_, _, alt, caption) in zip(
                                    asset_ids, images, strict=True
                                )
                            ]
                        },
                    },
                ],
            ),
            chapter(
                "run",
                "Run it yourself",
                None,
                [
                    text(
                        "run",
                        "GeoLens is self-hosted and Apache-2.0. Start with the "
                        "quickstart, or read the code.",
                    ),
                    button(
                        "run",
                        "docs",
                        "Quickstart",
                        "https://docs.getgeolens.com/",
                        True,
                    ),
                    button(
                        "run",
                        "repo",
                        "GitHub repository",
                        "https://github.com/geolens-io/geolens",
                        True,
                    ),
                    button(
                        "run",
                        "collection",
                        "Browse the Cambridge collection",
                        f"{app_url}/collections/{collection}",
                    ),
                ],
            ),
        ],
    }
    cover = _story_cover(api, story_id, maps[TREES_MAP], asset_ids[0])
    api.publish_story(
        story_id, STORY_TITLE, STORY_SUMMARY, document, cover_asset_id=cover
    )
    print(f"  -> story {story_id} ({verb}, published, public)")
    return story_id
